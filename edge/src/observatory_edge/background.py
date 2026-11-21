"""Background loops inside the edge process: inbox watcher, alerts, leases, backups, heartbeat."""

from __future__ import annotations

import logging
import shutil
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .adapters import LocalFolderAdapter, poll_adapter_once
from .alerts import make_sender, queue_system_alert, send_pending_alerts
from .backup import create_backup
from .config import Settings
from .db import connect, utcnow
from .jobs import requeue_expired
from .queries import health_details

log = logging.getLogger("observatory.background")


def disk_pct(settings: Settings) -> float:
    u = shutil.disk_usage(settings.data_dir)
    return 100 * u.used / u.total


class BackgroundLoops:
    def __init__(self, settings: Settings, inbox_device: str = "backyard"):
        self.settings = settings
        self.inbox_device = inbox_device
        self.stop_evt = threading.Event()
        self.threads: list[threading.Thread] = []
        self._last_backup_day = None
        self._last_heartbeat_day = None
        self._alerted_problems: set[str] = set()

    def start(self) -> None:
        for name, fn, every in (("inbox", self.tick_inbox, 3), ("alerts", self.tick_alerts, 10),
                                ("maintenance", self.tick_maintenance, 60)):
            t = threading.Thread(target=self._loop, args=(name, fn, every), daemon=True)
            t.start()
            self.threads.append(t)

    def stop(self) -> None:
        self.stop_evt.set()

    def _loop(self, name, fn, every) -> None:
        conn = connect(self.settings.db_path)
        while not self.stop_evt.is_set():
            try:
                fn(conn)
            except Exception:
                log.exception("background loop %s failed", name)
            self.stop_evt.wait(every)

    def tick_inbox(self, conn) -> None:
        if disk_pct(self.settings) >= self.settings.disk_floor_pct:
            return  # ingest paused; FTP receiver also refuses uploads (452)
        ad = LocalFolderAdapter(self.settings.inbox_dir, self.settings.ingest_stable_s,
                                delete_after=True)
        counts = poll_adapter_once(conn, self.settings, ad, self.inbox_device)
        if counts:
            log.info("inbox ingest: %s", dict(counts))

    def tick_alerts(self, conn) -> None:
        send_pending_alerts(conn, self.settings, make_sender(self.settings))

    def tick_maintenance(self, conn) -> None:
        requeue_expired(conn, self.settings.max_attempts)
        tz = ZoneInfo(self.settings.camera_timezone)
        now = datetime.now(tz)
        if now.hour == 3 and self._last_backup_day != now.date():
            self._last_backup_day = now.date()
            try:
                create_backup(conn, self.settings)
            except Exception as e:
                queue_system_alert(conn, "failure", "Observatory backup failed", str(e))
        h = health_details(conn, self.settings)
        if now.hour == 8 and self._last_heartbeat_day != now.date():
            self._last_heartbeat_day = now.date()
            n = conn.execute("SELECT COUNT(*) FROM media WHERE created_at >= datetime('now','-1 day')"
                             ).fetchone()[0]
            body = f"Observatory OK: {n} captures in 24h, disk {h['disk_pct']}%"
            if h["problems"]:
                body = "Observatory needs attention: " + "; ".join(h["problems"])
            queue_system_alert(conn, "heartbeat", "Wildlife Observatory daily check", body)
        for p in h["problems"]:
            if p not in self._alerted_problems:
                self._alerted_problems.add(p)
                queue_system_alert(conn, "failure", "Wildlife Observatory problem", p)
        self._alerted_problems &= set(h["problems"])
        log.debug("maintenance tick at %s", utcnow())
        time.sleep(0)
