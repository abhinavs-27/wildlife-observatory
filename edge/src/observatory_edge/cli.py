"""`observatory` command line."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import get_settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {"ts": self.formatTime(record), "level": record.levelname, "logger": record.name,
             "msg": record.getMessage()}
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info)
        return json.dumps(d)


def setup_logging(json_logs: bool) -> None:
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter() if json_logs else logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[h], force=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="observatory")
    ap.add_argument("--json-logs", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the edge API (+ background loops)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--no-background", action="store_true")

    i = sub.add_parser("import", help="bulk import a folder (never alerts)")
    i.add_argument("folder", type=Path)
    i.add_argument("--device", default="backyard")

    b = sub.add_parser("backup", help="create a verified SQLite backup now")
    r = sub.add_parser("restore", help="restore a backup over the DB (stop the edge first)")
    r.add_argument("backup", type=Path)

    p = sub.add_parser("backup-pull", help="(on the Mac) fetch the latest backup from the Pi")
    p.add_argument("--edge-url", required=True)
    p.add_argument("--token", required=True)
    p.add_argument("--dest", type=Path, default=Path("~/WildlifeObservatoryBackups").expanduser())

    sub.add_parser("ftp", help="run the LAN-only FTP receiver for camera uploads")

    a = sub.add_parser("ask", help="ask a question")
    a.add_argument("question", nargs="+")
    sub.add_parser("health", help="print health details")

    args = ap.parse_args(argv)
    setup_logging(args.json_logs)
    settings = get_settings()

    if args.cmd == "serve":
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(settings, start_background=not args.no_background),
                    host=args.host, port=args.port, log_config=None)
        return 0

    if args.cmd == "ftp":
        from .ftp_receiver import main as ftp_main
        ftp_main()
        return 0

    if args.cmd == "backup-pull":
        from .backup import pull_backup
        print(pull_backup(args.edge_url, args.token, args.dest))
        return 0

    from .db import connect, init_db
    settings.ensure_dirs()
    conn = connect(settings.db_path)
    init_db(conn)

    if args.cmd == "import":
        from .adapters import import_folder
        counts = import_folder(conn, settings, args.folder, device=args.device)
        print(json.dumps(dict(counts)))
    elif args.cmd == "backup":
        from .backup import create_backup
        print(create_backup(conn, settings))
    elif args.cmd == "restore":
        from .backup import restore_backup
        conn.close()
        restore_backup(args.backup, settings.db_path)
        print(f"restored {args.backup} -> {settings.db_path}")
    elif args.cmd == "ask":
        from .search import answer
        res = answer(conn, settings, " ".join(args.question))
        print(res.text)
        if res.sources:
            print("sources: encounters " + ", ".join(map(str, res.sources[:20])))
    elif args.cmd == "health":
        from .queries import health_details
        print(json.dumps(health_details(conn, settings), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
