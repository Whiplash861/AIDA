from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aida.technomancer.models import Advisory, HardwareInventory, TelemetrySample


class TechnomancerStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                machine_id TEXT NOT NULL,
                data_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_samples_machine_time ON samples(machine_id, timestamp);
            CREATE TABLE IF NOT EXISTS daily_summaries (
                machine_id TEXT NOT NULL,
                day TEXT NOT NULL,
                sample_count INTEGER NOT NULL,
                data_json TEXT NOT NULL,
                PRIMARY KEY(machine_id, day)
            );
            CREATE TABLE IF NOT EXISTS hardware (
                machine_id TEXT PRIMARY KEY,
                captured_at TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                data_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS advisories (
                advisory_id TEXT PRIMARY KEY,
                active INTEGER NOT NULL,
                data_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                data_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                advisory_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                notes TEXT
            );
            CREATE TABLE IF NOT EXISTS aptitude (
                domain TEXT PRIMARY KEY,
                level REAL NOT NULL,
                confidence REAL NOT NULL,
                evidence_count INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            """)

    def record_sample(self, sample: TelemetrySample) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO samples(timestamp, machine_id, data_json) VALUES (?, ?, ?)",
                (sample.timestamp, sample.machine_id, json.dumps(sample.to_dict())),
            )

    def samples_since(self, machine_id: str, since_timestamp: float) -> list[TelemetrySample]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT data_json FROM samples WHERE machine_id=? AND timestamp>=? ORDER BY timestamp",
                (machine_id, since_timestamp),
            ).fetchall()
        return [TelemetrySample(**json.loads(row["data_json"])) for row in rows]

    def observation_days(self, machine_id: str, now_timestamp: float) -> float:
        with self._connection() as conn:
            raw = conn.execute("SELECT MIN(timestamp) AS value FROM samples WHERE machine_id=?", (machine_id,)).fetchone()["value"]
            summary = conn.execute("SELECT MIN(day) AS value FROM daily_summaries WHERE machine_id=?", (machine_id,)).fetchone()["value"]
        candidates: list[float] = []
        if raw is not None:
            candidates.append(float(raw))
        if summary:
            dt = datetime.fromisoformat(str(summary)).replace(tzinfo=timezone.utc)
            candidates.append(dt.timestamp())
        if not candidates:
            return 0.0
        return max(0.0, (now_timestamp - min(candidates)) / 86400.0)

    def compact(self, machine_id: str, raw_retention_days: int = 30, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=raw_retention_days)
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT timestamp, data_json FROM samples WHERE machine_id=? AND timestamp<? ORDER BY timestamp",
                (machine_id, cutoff.timestamp()),
            ).fetchall()
            grouped: dict[str, list[dict]] = {}
            for row in rows:
                day = datetime.fromtimestamp(row["timestamp"], timezone.utc).date().isoformat()
                grouped.setdefault(day, []).append(json.loads(row["data_json"]))
            for day, items in grouped.items():
                numeric = ["cpu_percent", "memory_percent", "swap_percent", "disk_percent", "gpu_percent", "vram_percent", "gpu_temp_c", "wifi_signal_percent"]
                summary: dict[str, float | int | None] = {}
                for key in numeric:
                    vals = [float(item[key]) for item in items if item.get(key) is not None]
                    if vals:
                        summary[f"avg_{key}"] = sum(vals) / len(vals)
                        summary[f"max_{key}"] = max(vals)
                conn.execute(
                    "INSERT OR REPLACE INTO daily_summaries(machine_id, day, sample_count, data_json) VALUES (?, ?, ?, ?)",
                    (machine_id, day, len(items), json.dumps(summary)),
                )
            conn.execute("DELETE FROM samples WHERE machine_id=? AND timestamp<?", (machine_id, cutoff.timestamp()))

    def record_inventory(self, inventory: HardwareInventory) -> bool:
        payload = inventory.to_dict()
        fingerprint_payload = dict(payload)
        fingerprint_payload.pop("captured_at", None)
        fingerprint = json.dumps(fingerprint_payload, sort_keys=True)
        changed = False
        with self._connection() as conn:
            existing = conn.execute("SELECT fingerprint FROM hardware WHERE machine_id=?", (inventory.machine_id,)).fetchone()
            changed = bool(existing and existing["fingerprint"] != fingerprint)
            conn.execute(
                "INSERT OR REPLACE INTO hardware(machine_id, captured_at, fingerprint, data_json) VALUES (?, ?, ?, ?)",
                (inventory.machine_id, inventory.captured_at, fingerprint, json.dumps(payload)),
            )
            if changed:
                conn.execute(
                    "INSERT INTO events(timestamp, event_type, data_json) VALUES (?, ?, ?)",
                    (datetime.now(timezone.utc).isoformat(), "hardware.changed", json.dumps(payload)),
                )
                conn.execute("UPDATE advisories SET active=0")
        return changed

    def latest_inventory(self, machine_id: str) -> HardwareInventory | None:
        with self._connection() as conn:
            row = conn.execute("SELECT data_json FROM hardware WHERE machine_id=?", (machine_id,)).fetchone()
        return HardwareInventory(**json.loads(row["data_json"])) if row else None

    def upsert_advisory(self, advisory: Advisory) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO advisories(advisory_id, active, data_json) VALUES (?, ?, ?)",
                (advisory.advisory_id, int(advisory.active), json.dumps(advisory.to_dict())),
            )

    def active_advisories(self, kind: str | None = None) -> list[Advisory]:
        with self._connection() as conn:
            rows = conn.execute("SELECT data_json FROM advisories WHERE active=1").fetchall()
        advisories = [Advisory(**json.loads(row["data_json"])) for row in rows]
        if kind:
            advisories = [item for item in advisories if item.kind == kind]
        return sorted(advisories, key=lambda item: (item.severity, item.confidence), reverse=True)

    def mark_surfaced(self, advisory_id: str, when: str) -> None:
        items = self.active_advisories()
        for item in items:
            if item.advisory_id == advisory_id:
                item.last_surfaced_at = when
                self.upsert_advisory(item)
                return

    def record_outcome(self, advisory_id: str, outcome: str, notes: str = "") -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO outcomes(timestamp, advisory_id, outcome, notes) VALUES (?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), advisory_id, outcome, notes),
            )

    def outcome_score(self, category_prefix: str) -> float | None:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT outcome FROM outcomes WHERE advisory_id LIKE ?",
                (f"{category_prefix}%",),
            ).fetchall()
        if not rows:
            return None
        positive = sum(str(row["outcome"]).lower() in {"success", "resolved", "helped"} for row in rows)
        return positive / len(rows)

    def update_aptitude(self, domain: str, level: float, confidence: float) -> None:
        with self._connection() as conn:
            row = conn.execute("SELECT evidence_count FROM aptitude WHERE domain=?", (domain,)).fetchone()
            count = int(row["evidence_count"]) + 1 if row else 1
            conn.execute(
                "INSERT OR REPLACE INTO aptitude(domain, level, confidence, evidence_count, updated_at) VALUES (?, ?, ?, ?, ?)",
                (domain, max(0.0, min(1.0, level)), max(0.0, min(1.0, confidence)), count, datetime.now(timezone.utc).isoformat()),
            )

    def aptitude(self, domain: str) -> tuple[float, float]:
        with self._connection() as conn:
            row = conn.execute("SELECT level, confidence FROM aptitude WHERE domain=?", (domain,)).fetchone()
        return (float(row["level"]), float(row["confidence"])) if row else (0.5, 0.0)
