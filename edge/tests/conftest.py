import io
from pathlib import Path

import pytest
from PIL import Image

from observatory_edge.config import Settings
from observatory_edge.db import connect, init_db


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(data_dir=tmp_path / "data", ingest_stable_s=0)
    s.ensure_dirs()
    return s


@pytest.fixture
def conn(settings):
    c = connect(settings.db_path)
    init_db(c)
    yield c
    c.close()


def make_jpeg(path: Path, color=(120, 80, 40), exif_dt: str | None = None, size=(64, 48)) -> Path:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    if exif_dt:
        exif = Image.Exif()
        exif[0x8769] = {0x9003: exif_dt}  # ExifIFD -> DateTimeOriginal
        img.save(buf, "JPEG", exif=exif)
    else:
        img.save(buf, "JPEG")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue())
    return path
