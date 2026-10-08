from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    secret: str
    max_rows: int
    admin_user: str
    admin_password: str


def get_settings() -> Settings:
    data_dir = Path(os.getenv("ALLDB_DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        data_dir=data_dir,
        secret=os.getenv("ALLDB_SECRET", "change-me-before-production"),
        max_rows=max(1, min(int(os.getenv("ALLDB_MAX_ROWS", "5000")), 100000)),
        admin_user=os.getenv("ALLDB_ADMIN_USER", ""),
        admin_password=os.getenv("ALLDB_ADMIN_PASSWORD", ""),
    )
