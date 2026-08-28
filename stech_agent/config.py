from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True, slots=True)
class AgentPaths:
    app_data: Path
    database: Path
    exports: Path
    logs: Path

    @classmethod
    def default(cls) -> "AgentPaths":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "STECH_PRODUCT_AGENT"
        return cls(
            app_data=base,
            database=base / "data" / "agent.sqlite3",
            exports=Path.home() / "Documents" / "STECH Agent",
            logs=base / "logs",
        )

    def ensure(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.exports.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
