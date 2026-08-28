from __future__ import annotations

from hashlib import sha256
from importlib.resources import files

from stech_agent.db.connection import AgentDatabase


MIGRATIONS = ((1, "001_initial.sql"),)


def migrate(db: AgentDatabase) -> None:
    with db.transaction(immediate=True) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                filename TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for version, filename in MIGRATIONS:
            resource = files("stech_agent.db.sql").joinpath(filename)
            sql = resource.read_text(encoding="utf-8")
            checksum = sha256(sql.encode("utf-8")).hexdigest()
            row = con.execute("SELECT checksum FROM schema_migrations WHERE version = ?", (version,)).fetchone()
            if row:
                if row[0] != checksum:
                    raise RuntimeError(f"Migration {version} cambió después de aplicarse")
                continue
            con.executescript(sql)
            con.execute(
                "INSERT INTO schema_migrations(version, filename, checksum) VALUES (?, ?, ?)",
                (version, filename, checksum),
            )
