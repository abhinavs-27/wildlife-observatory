"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("./data")
    worker_token: str = "dev-token"
    camera_timezone: str = "America/New_York"
    country: str = "USA"
    admin1_region: str = "NJ"
    encounter_gap_s: int = 120
    track_max_gap_s: int = 30
    animal_threshold: float = 0.2
    alert_threshold: float = 0.5
    person_threshold: float = 0.5
    uncertain_score: float = 0.5
    lease_s: int = 600
    max_attempts: int = 3
    alert_max_age_s: int = 900
    ntfy_url: str = "https://ntfy.sh"
    ntfy_topic: str = ""
    disk_floor_pct: float = 95.0
    worker_offline_s: int = 300
    backups_keep: int = 7
    ingest_stable_s: float = 2.0
    extra: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "observatory.sqlite"

    @property
    def originals_dir(self) -> Path:
        return self.data_dir / "originals"

    @property
    def frames_dir(self) -> Path:
        return self.data_dir / "frames"

    @property
    def quarantine_dir(self) -> Path:
        return self.data_dir / "quarantine"

    @property
    def inbox_dir(self) -> Path:
        return self.data_dir / "inbox" / "ready"

    @property
    def backups_dir(self) -> Path:
        return Path(_env("BACKUP_DIR", str(self.data_dir / "backups")))

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.originals_dir, self.frames_dir, self.quarantine_dir,
                  self.inbox_dir, self.backups_dir):
            d.mkdir(parents=True, exist_ok=True)

    def with_(self, **kw) -> "Settings":
        return replace(self, **kw)


def get_settings() -> Settings:
    return Settings(
        data_dir=Path(_env("DATA_DIR", "./data")),
        worker_token=_env("WORKER_TOKEN", "dev-token"),
        camera_timezone=_env("CAMERA_TIMEZONE", "America/New_York"),
        country=_env("COUNTRY", "USA"),
        admin1_region=_env("ADMIN1_REGION", "NJ"),
        encounter_gap_s=int(_env("ENCOUNTER_GAP_S", "120")),
        track_max_gap_s=int(_env("TRACK_MAX_GAP_S", "30")),
        animal_threshold=float(_env("ANIMAL_THRESHOLD", "0.2")),
        alert_threshold=float(_env("ALERT_THRESHOLD", "0.5")),
        person_threshold=float(_env("PERSON_THRESHOLD", "0.5")),
        uncertain_score=float(_env("UNCERTAIN_SCORE", "0.5")),
        lease_s=int(_env("LEASE_S", "600")),
        max_attempts=int(_env("MAX_ATTEMPTS", "3")),
        alert_max_age_s=int(_env("ALERT_MAX_AGE_S", "900")),
        ntfy_url=_env("NTFY_URL", "https://ntfy.sh"),
        ntfy_topic=_env("NTFY_TOPIC", ""),
        disk_floor_pct=float(_env("DISK_FLOOR_PCT", "95")),
        worker_offline_s=int(_env("WORKER_OFFLINE_S", "300")),
        backups_keep=int(_env("BACKUPS_KEEP", "7")),
        ingest_stable_s=float(_env("INGEST_STABLE_S", "2")),
    )
