"""Durable local investigation records, including an evidence snapshot."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


VERIFICATION_QUESTIONS = [
    "Does this settlement contain occupied homes?",
    "Are healthcare facilities missing from the available mapping dataset?",
    "Which services are actually provided by mapped facilities?",
    "Are mapped roads and paths usable, and what transport options are available?",
    "Are local organisations already providing outreach?",
    "Would residents consider the proposed intervention helpful?",
]


RESIDENTIAL_LABELS = ("residential", "non_residential", "uncertain")


class TaskStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS verification_tasks (
                id TEXT PRIMARY KEY, settlement_id TEXT NOT NULL, region_id TEXT NOT NULL,
                status TEXT NOT NULL, notes TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, evidence_json TEXT NOT NULL,
                outreach_json TEXT
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS settlement_reviews (
                id TEXT PRIMARY KEY, settlement_id TEXT NOT NULL, region_id TEXT NOT NULL,
                label TEXT NOT NULL, notes TEXT NOT NULL, reviewer TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS confirmed_facilities (
                id TEXT PRIMARY KEY, region_id TEXT NOT NULL, name TEXT NOT NULL,
                category TEXT NOT NULL, status TEXT NOT NULL,
                lon REAL NOT NULL, lat REAL NOT NULL, created_at TEXT NOT NULL
            )""")

    def connection(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def decode(row: sqlite3.Row) -> dict:
        task = dict(row)
        task["evidence"] = json.loads(task.pop("evidence_json"))
        outreach = task.pop("outreach_json")
        task["hypothetical_outreach_location"] = json.loads(outreach) if outreach else None
        task["recommended_verification_questions"] = VERIFICATION_QUESTIONS
        return task

    def create(self, settlement: dict, region_id: str, notes: str = "", status: str = "unverified",
               outreach: dict | None = None) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        task_id = str(uuid4())
        with self.connection() as db:
            db.execute("INSERT INTO verification_tasks VALUES (?,?,?,?,?,?,?,?,?)", (
                task_id, settlement["id"], region_id, status, notes, now, now,
                json.dumps(settlement, allow_nan=False), json.dumps(outreach) if outreach else None,
            ))
        return self.get(task_id)

    def get(self, task_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM verification_tasks WHERE id=?", (task_id,)).fetchone()
        return self.decode(row) if row else None

    def list(self, region_id: str | None = None, status: str | None = None) -> list[dict]:
        query = "SELECT * FROM verification_tasks"
        where, args = [], []
        if region_id:
            where.append("region_id=?")
            args.append(region_id)
        if status:
            where.append("status=?")
            args.append(status)
        if where:
            query += " WHERE " + " AND ".join(where)
        with self.connection() as db:
            rows = db.execute(query + " ORDER BY created_at DESC, id", args).fetchall()
        return [self.decode(row) for row in rows]

    def update(self, task_id: str, changes: dict) -> dict | None:
        updates = {key: value for key, value in changes.items() if key in {"notes", "status"} and value is not None}
        if not self.get(task_id):
            return None
        if updates:
            updates["updated_at"] = datetime.now(timezone.utc).isoformat()
            with self.connection() as db:
                db.execute("UPDATE verification_tasks SET " + ",".join(f"{key}=?" for key in updates) + " WHERE id=?",
                           [*updates.values(), task_id])
        return self.get(task_id)

    # ---- settlement reviews: human labels that change the computed evidence ----

    @staticmethod
    def _decode_review(row: sqlite3.Row) -> dict:
        return {"id": row["id"], "settlement_id": row["settlement_id"], "region_id": row["region_id"],
                "label": row["label"], "notes": row["notes"], "reviewer": row["reviewer"],
                "created_at": row["created_at"]}

    def add_review(self, settlement: dict, region_id: str, label: str, notes: str = "",
                   reviewer: str = "local reviewer") -> dict:
        now = datetime.now(timezone.utc).isoformat()
        review_id = str(uuid4())
        with self.connection() as db:
            db.execute("INSERT INTO settlement_reviews VALUES (?,?,?,?,?,?,?)",
                       (review_id, settlement["id"], region_id, label, notes, reviewer, now))
        return self.get_review(review_id)

    def get_review(self, review_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM settlement_reviews WHERE id=?", (review_id,)).fetchone()
        return self._decode_review(row) if row else None

    def reviews(self, region_id: str | None = None, settlement_id: str | None = None) -> list[dict]:
        query = "SELECT * FROM settlement_reviews"
        clauses, args = [], []
        if region_id:
            clauses.append("region_id=?")
            args.append(region_id)
        if settlement_id:
            clauses.append("settlement_id=?")
            args.append(settlement_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        with self.connection() as db:
            rows = db.execute(query + " ORDER BY created_at DESC", args).fetchall()
        return [self._decode_review(row) for row in rows]

    def latest_labels(self, region_id: str) -> dict[str, str]:
        """Most recent label per settlement within the region."""
        labels: dict[str, str] = {}
        for review in self.reviews(region_id):
            labels.setdefault(review["settlement_id"], review["label"])
        return labels

    # ---- confirmed facilities recorded through human verification ----

    def add_confirmed_facility(self, region_id: str, name: str, category: str, status: str,
                               coordinates: list[float]) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        facility_id = f"confirmed-{str(uuid4())[:8]}"
        with self.connection() as db:
            db.execute("INSERT INTO confirmed_facilities VALUES (?,?,?,?,?,?,?,?)",
                       (facility_id, region_id, name, category, status, float(coordinates[0]), float(coordinates[1]), now))
        return self.get_confirmed_facility(facility_id)

    def get_confirmed_facility(self, facility_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM confirmed_facilities WHERE id=?", (facility_id,)).fetchone()
        return self.decode_confirmed_facility(row) if row else None

    @staticmethod
    def decode_confirmed_facility(row: sqlite3.Row) -> dict:
        return {"id": row["id"], "region_id": row["region_id"], "name": row["name"],
                "category": row["category"], "status": row["status"],
                "coordinates": [row["lon"], row["lat"]], "created_at": row["created_at"],
                "source": "Confirmed through local review with the demo application"}

    def confirmed_facilities(self, region_id: str) -> list[dict]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM confirmed_facilities WHERE region_id=? ORDER BY created_at", (region_id,)).fetchall()
        return [self.decode_confirmed_facility(row) for row in rows]
