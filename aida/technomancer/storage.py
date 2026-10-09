from __future__ import annotations

import json
import sqlite3
import math
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aida.memory.privacy import sanitize_text
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
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        conn.execute(f"PRAGMA max_page_count={256 * 1024 * 1024 // page_size}")
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > 2:
                raise RuntimeError("Technomancer database requires a newer AIDA version")
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
            conn.execute("CREATE TABLE IF NOT EXISTS hardware_epochs (machine_id TEXT PRIMARY KEY, started_at REAL NOT NULL, generation INTEGER NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS runtime_health (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)")
            conn.execute("PRAGMA user_version=2")

    def _epoch(self, conn, machine_id):
        row = conn.execute("SELECT started_at FROM hardware_epochs WHERE machine_id=?", (machine_id,)).fetchone()
        return float(row[0]) if row else 0.0

    def record_runtime_health(self, *, success: bool, error_category: str | None = None) -> None:
        with self._connection() as conn:
            row = conn.execute("SELECT value_json FROM runtime_health WHERE key='latest'").fetchone()
            previous = json.loads(row[0]) if row else {}
            now = datetime.now(timezone.utc).isoformat()
            payload = {"observed_at": now, "success": success, "error_category": error_category,
                       "last_success_at": now if success else previous.get("last_success_at"),
                       "consecutive_failures": 0 if success else previous.get("consecutive_failures", 0) + 1}
            conn.execute("INSERT OR REPLACE INTO runtime_health VALUES('latest',?)", (json.dumps(payload),))

    def runtime_health(self) -> dict:
        with self._connection() as conn:
            row = conn.execute("SELECT value_json FROM runtime_health WHERE key='latest'").fetchone()
        return json.loads(row[0]) if row else {"success": None, "observed_at": None}

    def record_sample(self, sample: TelemetrySample) -> None:
        if not math.isfinite(sample.timestamp) or sample.timestamp > time.time() + 60:
            raise ValueError("Invalid or future sample timestamp")
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO samples(timestamp, machine_id, data_json) VALUES (?, ?, ?)",
                (sample.timestamp, sample.machine_id, json.dumps(sample.to_dict())),
            )

    def samples_since(self, machine_id: str, since_timestamp: float, *, until_timestamp: float | None = None) -> list[TelemetrySample]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT data_json FROM samples WHERE machine_id=? AND timestamp>=? AND timestamp<=? ORDER BY timestamp",
                (machine_id, max(since_timestamp, self._epoch(conn, machine_id)), time.time() if until_timestamp is None else until_timestamp),
            ).fetchall()
        return [TelemetrySample(**json.loads(row["data_json"])) for row in rows]

    def observation_days(self, machine_id: str, now_timestamp: float) -> float:
        """Covered hours in qualified days, not age of the oldest sample.

        A day needs at least 12 observations spanning six distinct hours; each
        hour contributes at most one hour. Long gaps never count as observation.
        """
        with self._connection() as conn:
            epoch = self._epoch(conn, machine_id)
            rows = conn.execute("SELECT timestamp FROM samples WHERE machine_id=? AND timestamp>=? AND timestamp<=?",
                                (machine_id, epoch, now_timestamp)).fetchall()
            summaries = conn.execute("SELECT day,data_json FROM daily_summaries WHERE machine_id=?", (machine_id,)).fetchall()
        days = {}
        for row in rows:
            stamp = datetime.fromtimestamp(row[0], timezone.utc)
            item = days.setdefault(stamp.date().isoformat(), {"count": 0, "hours": set()})
            item["count"] += 1
            item["hours"].add(stamp.hour)
        for row in summaries:
            if datetime.fromisoformat(row["day"]).replace(tzinfo=timezone.utc).timestamp() < epoch:
                continue
            data = json.loads(row["data_json"])
            item = days.setdefault(row["day"], {"count": 0, "hours": set()})
            item["count"] += data.get("coverage_count", 0)
            item["hours"].update(data.get("coverage_hours", []))
        return sum(len(item["hours"]) / 24 for item in days.values() if item["count"] >= 12 and len(item["hours"]) >= 6)

    def compact(self, machine_id: str, raw_retention_days: int = 30, now: datetime | None = None, *, summary_retention_days: int = 730) -> None:
        now = now or datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=max(1, raw_retention_days))).replace(hour=0, minute=0, second=0, microsecond=0)
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
                old = conn.execute("SELECT sample_count,data_json FROM daily_summaries WHERE machine_id=? AND day=?", (machine_id, day)).fetchone()
                summary = json.loads(old["data_json"]) if old else {}
                old_count = int(old["sample_count"]) if old else 0
                summary["coverage_count"] = summary.get("coverage_count", 0) + len(items)
                summary["coverage_hours"] = sorted(set(summary.get("coverage_hours", [])) | {datetime.fromtimestamp(item["timestamp"], timezone.utc).hour for item in items})
                for key in numeric:
                    vals = [float(item[key]) for item in items if item.get(key) is not None]
                    if vals:
                        count = summary.get(f"count_{key}", old_count if f"avg_{key}" in summary else 0)
                        total = summary.get(f"avg_{key}", 0) * count + sum(vals)
                        summary[f"count_{key}"] = count + len(vals)
                        summary[f"avg_{key}"] = total / (count + len(vals))
                        summary[f"max_{key}"] = max(max(vals), summary.get(f"max_{key}", max(vals)))
                conn.execute(
                    "INSERT OR REPLACE INTO daily_summaries(machine_id, day, sample_count, data_json) VALUES (?, ?, ?, ?)",
                    (machine_id, day, old_count + len(items), json.dumps(summary)),
                )
            conn.execute("DELETE FROM samples WHERE machine_id=? AND timestamp<?", (machine_id, cutoff.timestamp()))
            oldest_day = (now - timedelta(days=max(30, min(3650, summary_retention_days)))).date().isoformat()
            conn.execute("DELETE FROM daily_summaries WHERE machine_id=? AND day<?", (machine_id, oldest_day))
            for table in ("events", "outcomes"):
                conn.execute(f"DELETE FROM {table} WHERE id IN (SELECT id FROM {table} ORDER BY id DESC LIMIT -1 OFFSET 10000)")

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
            conn.execute("INSERT OR IGNORE INTO hardware_epochs VALUES(?,0,1)", (inventory.machine_id,))
            if changed:
                conn.execute("UPDATE hardware_epochs SET started_at=?,generation=generation+1 WHERE machine_id=?", (time.time(), inventory.machine_id))
                conn.execute(
                    "INSERT INTO events(timestamp, event_type, data_json) VALUES (?, ?, ?)",
                    (datetime.now(timezone.utc).isoformat(), "hardware.changed", json.dumps(payload)),
                )
                conn.execute("UPDATE advisories SET active=0")
                conn.execute("DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY id DESC LIMIT -1 OFFSET 10000)")
        return changed

    def latest_inventory(self, machine_id: str) -> HardwareInventory | None:
        with self._connection() as conn:
            row = conn.execute("SELECT data_json FROM hardware WHERE machine_id=?", (machine_id,)).fetchone()
        return HardwareInventory(**json.loads(row["data_json"])) if row else None

    def upsert_advisory(self, advisory: Advisory) -> None:
        with self._connection() as conn:
            row = conn.execute("SELECT data_json,active FROM advisories WHERE advisory_id=?", (advisory.advisory_id,)).fetchone()
            if row and row["active"]:
                old = json.loads(row["data_json"])
                advisory.first_seen = old["first_seen"]
                advisory.last_surfaced_at = advisory.last_surfaced_at or old.get("last_surfaced_at")
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
        return sorted(advisories, key=lambda item: ({"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}.get(item.severity, -1), item.confidence), reverse=True)

    def resolve_absent_advisories(self, active_ids) -> None:
        active_ids = set(active_ids)
        with self._connection() as conn:
            for row in conn.execute("SELECT advisory_id,data_json FROM advisories WHERE active=1").fetchall():
                if row["advisory_id"] not in active_ids:
                    payload = json.loads(row["data_json"])
                    payload["active"] = False
                    conn.execute("UPDATE advisories SET active=0,data_json=? WHERE advisory_id=?", (json.dumps(payload), row["advisory_id"]))

    def mark_surfaced(self, advisory_id: str, when: str) -> None:
        items = self.active_advisories()
        for item in items:
            if item.advisory_id == advisory_id:
                item.last_surfaced_at = when
                self.upsert_advisory(item)
                return

    def record_outcome(self, advisory_id: str, outcome: str, notes: str = "") -> None:
        outcome = outcome.strip().lower()
        if outcome not in {"success", "resolved", "helped", "failed", "no_change", "unknown"}:
            raise ValueError("Outcome must be success, resolved, helped, failed, no_change or unknown")
        with self._connection() as conn:
            if not conn.execute("SELECT 1 FROM advisories WHERE advisory_id=?", (advisory_id,)).fetchone():
                raise KeyError(advisory_id)
            conn.execute(
                "INSERT INTO outcomes(timestamp, advisory_id, outcome, notes) VALUES (?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), advisory_id, outcome, sanitize_text(notes)),
            )

            conn.execute("DELETE FROM outcomes WHERE id IN (SELECT id FROM outcomes ORDER BY id DESC LIMIT -1 OFFSET 10000)")

    def outcome_score(self, category_prefix: str) -> float | None:
        """Feedback is retained, but is not causal evidence for purchase advice."""
        return None

    def update_aptitude(self, domain: str, level: float, confidence: float) -> None:
        if not domain.strip() or any(not math.isfinite(value) or not 0 <= value <= 1 for value in (level, confidence)):
            raise ValueError("Aptitude requires a domain and finite values between zero and one")
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM aptitude WHERE domain=?", (domain,)).fetchone()
            count = int(row["evidence_count"]) + 1 if row else 1
            if row:
                weight = min(0.5, confidence)
                level = float(row["level"]) * (1 - weight) + level * weight
                confidence = max(float(row["confidence"]), confidence)
            conn.execute(
                "INSERT OR REPLACE INTO aptitude(domain, level, confidence, evidence_count, updated_at) VALUES (?, ?, ?, ?, ?)",
                (domain, max(0.0, min(1.0, level)), max(0.0, min(1.0, confidence)), count, datetime.now(timezone.utc).isoformat()),
            )

    def aptitude(self, domain: str) -> tuple[float, float]:
        with self._connection() as conn:
            row = conn.execute("SELECT level, confidence FROM aptitude WHERE domain=?", (domain,)).fetchone()
        if not row:
            return 0.5, 0.0
        with self._connection() as conn:
            updated = conn.execute("SELECT updated_at FROM aptitude WHERE domain=?", (domain,)).fetchone()[0]
        age = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(updated)).total_seconds() / 86400)
        return float(row["level"]), float(row["confidence"]) * 0.5 ** (age / 180)
