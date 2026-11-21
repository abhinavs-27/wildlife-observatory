"""LAN-only FTP receiver for cameras that push motion clips (e.g. Reolink Argus via FTP upload).

Uploads land in `<inbox>/.incoming/`. Only when a transfer completes is the file atomically
renamed into `<inbox>/ready/`, which the edge's folder watcher ingests. Interrupted uploads are
deleted. Below the disk floor, uploads are refused with `452` so the camera keeps the clip and
retries later. Not verified against the real camera yet (see docs/hardware-untestable.md).
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

log = logging.getLogger("observatory.ftp")


def disk_used_pct(path: Path) -> float:
    u = shutil.disk_usage(path)
    return 100 * u.used / u.total


def unique_dest(ready: Path, name: str) -> Path:
    dest = ready / name
    i = 1
    while dest.exists():
        dest = ready / f"{Path(name).stem}-{i}{Path(name).suffix}"
        i += 1
    return dest


def make_handler(inbox: Path, disk_floor_pct: float, tls_cert: str | None = None):
    incoming = inbox / ".incoming"
    ready = inbox / "ready"
    incoming.mkdir(parents=True, exist_ok=True)
    ready.mkdir(parents=True, exist_ok=True)
    if tls_cert:  # FTPS needs pyOpenSSL (pip install pyopenssl)
        from pyftpdlib.handlers import TLS_FTPHandler
        base = TLS_FTPHandler
    else:
        base = FTPHandler

    class ReceiverHandler(base):  # type: ignore[misc, valid-type]
        def ftp_STOR(self, file, mode="w"):
            if disk_used_pct(inbox) >= disk_floor_pct:
                self.respond("452 Insufficient storage space.")
                return
            return super().ftp_STOR(file, mode)

        def on_file_received(self, file):
            src = Path(file)
            dest = unique_dest(ready, src.name)
            os.replace(src, dest)  # atomic within the same filesystem
            log.info("received %s -> %s", src.name, dest)

        def on_incomplete_file_received(self, file):
            log.warning("incomplete upload removed: %s", file)
            try:
                os.remove(file)
            except OSError:
                pass

    if tls_cert:
        ReceiverHandler.certfile = tls_cert
    return ReceiverHandler, incoming


def build_server(inbox: Path, user: str, password: str, host: str = "0.0.0.0", port: int = 2121,
                 passive_ports: range | None = None, masquerade: str | None = None,
                 disk_floor_pct: float = 95.0, tls_cert: str | None = None) -> FTPServer:
    handler, incoming = make_handler(inbox, disk_floor_pct, tls_cert)
    auth = DummyAuthorizer()
    # Camera may create sub-directories; it can write but not delete or read others' files.
    auth.add_user(user, password, str(incoming), perm="elwmM")
    handler.authorizer = auth
    handler.banner = "wildlife-observatory ftp receiver"
    if passive_ports:
        handler.passive_ports = passive_ports
    if masquerade:
        handler.masquerade_address = masquerade
    return FTPServer((host, port), handler)


def main() -> None:  # pragma: no cover - exercised via CLI/compose
    data = Path(os.environ.get("DATA_DIR", "./data"))
    inbox = data / "inbox"
    lo, _, hi = os.environ.get("FTP_PASSIVE_PORTS", "30000-30009").partition("-")
    server = build_server(
        inbox,
        os.environ.get("FTP_USER", "camera"),
        _read_secret("FTP_PASSWORD"),
        host=os.environ.get("FTP_HOST", "0.0.0.0"),
        port=int(os.environ.get("FTP_PORT", "2121")),
        passive_ports=range(int(lo), int(hi) + 1),
        masquerade=os.environ.get("FTP_MASQUERADE_ADDRESS") or None,
        disk_floor_pct=float(os.environ.get("DISK_FLOOR_PCT", "95")),
        tls_cert=os.environ.get("FTP_TLS_CERT") or None,
    )
    log.info("FTP receiver listening; uploads -> %s", inbox / "ready")
    server.serve_forever()


def _read_secret(name: str) -> str:
    path = os.environ.get(f"{name}_FILE")
    if path and Path(path).exists():
        return Path(path).read_text().strip()
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} (or {name}_FILE) must be set")
    return value
