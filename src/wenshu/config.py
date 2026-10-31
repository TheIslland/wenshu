"""Runtime configuration for Wenshu."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "Wenshu"
APP_SLUG = "wenshu"
VERSION = "0.1.0"
DEFAULT_PORT = 8765
PORT_SCAN = 12


def default_data_dir() -> Path:
    override = os.environ.get("WENSHU_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path(user_data_dir(APP_NAME, appauthor=False)).resolve()


@dataclass(slots=True)
class RuntimeConfig:
    data_dir: Path
    port: int = DEFAULT_PORT
    host: str = "127.0.0.1"
    token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    demo: bool = False
    no_browser: bool = False

    @classmethod
    def build(
        cls,
        *,
        data_dir: str | Path | None = None,
        port: int = DEFAULT_PORT,
        demo: bool = False,
        no_browser: bool = False,
        token: str | None = None,
    ) -> RuntimeConfig:
        resolved = Path(data_dir).expanduser().resolve() if data_dir else default_data_dir()
        return cls(
            data_dir=resolved,
            port=int(port),
            token=token or os.environ.get("WENSHU_TOKEN") or secrets.token_urlsafe(24),
            demo=bool(demo),
            no_browser=bool(no_browser),
        )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "wenshu.db"

    @property
    def attachments_dir(self) -> Path:
        return self.data_dir / "attachments"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.attachments_dir,
            self.exports_dir,
            self.backups_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass
