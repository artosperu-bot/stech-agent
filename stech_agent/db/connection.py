from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator


class AgentDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _open(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("PRAGMA foreign_keys=ON")
        return con

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        con = self._open()
        try:
            yield con
        finally:
            con.close()

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        con = self._open()
        try:
            con.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()
