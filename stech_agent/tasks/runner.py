from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from stech_agent.db.connection import AgentDatabase


@dataclass(frozen=True, slots=True)
class ClaimedTaskItem:
    id: int
    task_id: int
    sku: str
    attempts: int
    resume_required: bool


class TaskRunner:
    def __init__(self, db: AgentDatabase, task_id: int):
        self.db = db
        self.task_id = task_id

    def recover_inflight(self) -> int:
        with self.db.transaction(immediate=True) as con:
            rows = con.execute(
                "SELECT id, metadata_json FROM task_items WHERE task_id=? AND state='RUNNING'",
                (self.task_id,),
            ).fetchall()
            for row in rows:
                metadata = json.loads(row["metadata_json"] or "{}")
                metadata["recovered_after_crash"] = True
                con.execute(
                    """
                    UPDATE task_items
                    SET state='PENDING', resume_required=1, metadata_json=?, started_at=NULL
                    WHERE id=?
                    """,
                    (json.dumps(metadata, ensure_ascii=False), row["id"]),
                )
            if rows:
                con.execute("UPDATE tasks SET state='PENDING', updated_at=CURRENT_TIMESTAMP WHERE id=?", (self.task_id,))
            return len(rows)

    def claim_next(self) -> ClaimedTaskItem | None:
        with self.db.transaction(immediate=True) as con:
            row = con.execute(
                """
                SELECT * FROM task_items
                WHERE task_id=? AND state='PENDING'
                ORDER BY resume_required DESC, position ASC
                LIMIT 1
                """,
                (self.task_id,),
            ).fetchone()
            if not row:
                remaining = con.execute(
                    "SELECT COUNT(*) FROM task_items WHERE task_id=? AND state NOT IN ('COMPLETED','FAILED','CANCELLED')",
                    (self.task_id,),
                ).fetchone()[0]
                if remaining == 0:
                    failed = con.execute(
                        "SELECT COUNT(*) FROM task_items WHERE task_id=? AND state='FAILED'",
                        (self.task_id,),
                    ).fetchone()[0]
                    con.execute(
                        "UPDATE tasks SET state=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        ("FAILED" if failed else "COMPLETED", self.task_id),
                    )
                return None
            attempts = int(row["attempts"]) + 1
            con.execute(
                "UPDATE task_items SET state='RUNNING', attempts=?, started_at=CURRENT_TIMESTAMP WHERE id=?",
                (attempts, row["id"]),
            )
            con.execute("UPDATE tasks SET state='RUNNING', updated_at=CURRENT_TIMESTAMP WHERE id=?", (self.task_id,))
            return ClaimedTaskItem(
                id=int(row["id"]),
                task_id=self.task_id,
                sku=row["sku"],
                attempts=attempts,
                resume_required=bool(row["resume_required"]),
            )

    def mark_step_result(self, item_id: int, *, success: bool, metadata: dict[str, Any] | None = None) -> None:
        state = "COMPLETED" if success else "FAILED"
        with self.db.transaction(immediate=True) as con:
            con.execute(
                """
                UPDATE task_items
                SET state=?, resume_required=0, metadata_json=?, finished_at=CURRENT_TIMESTAMP
                WHERE id=? AND task_id=?
                """,
                (state, json.dumps(metadata or {}, ensure_ascii=False), item_id, self.task_id),
            )
            remaining = con.execute(
                "SELECT COUNT(*) FROM task_items WHERE task_id=? AND state IN ('PENDING','RUNNING')",
                (self.task_id,),
            ).fetchone()[0]
            if remaining == 0:
                failed = con.execute(
                    "SELECT COUNT(*) FROM task_items WHERE task_id=? AND state='FAILED'",
                    (self.task_id,),
                ).fetchone()[0]
                con.execute(
                    "UPDATE tasks SET state=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    ("FAILED" if failed else "COMPLETED", self.task_id),
                )
