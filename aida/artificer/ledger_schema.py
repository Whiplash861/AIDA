from __future__ import annotations

SCHEMA_SQL = r"""
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operational_events (
                    event_id TEXT PRIMARY KEY, timestamp_utc TEXT NOT NULL,
                    monotonic_ns INTEGER NOT NULL, source TEXT NOT NULL,
                    event_type TEXT NOT NULL, status TEXT NOT NULL,
                    aida_version TEXT NOT NULL, platform_profile_id TEXT NOT NULL,
                    operation_id TEXT, task_name TEXT, duration_ms REAL,
                    error_category TEXT, metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_type_time
                    ON operational_events(event_type, timestamp_utc);
                CREATE INDEX IF NOT EXISTS idx_events_operation
                    ON operational_events(operation_id);
                CREATE TABLE IF NOT EXISTS platform_profiles (
                    profile_id TEXT PRIMARY KEY, captured_at_utc TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS capability_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, capability TEXT NOT NULL,
                    status TEXT NOT NULL, detail TEXT NOT NULL,
                    verified_at_utc TEXT NOT NULL, profile_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artificer_findings (
                    finding_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
                    category TEXT NOT NULL, title TEXT NOT NULL, severity TEXT NOT NULL,
                    confidence REAL NOT NULL, evidence_quality REAL NOT NULL,
                    first_seen_utc TEXT NOT NULL, last_seen_utc TEXT NOT NULL,
                    observation_count INTEGER NOT NULL, status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_findings_status
                    ON artificer_findings(status, severity);
                CREATE TABLE IF NOT EXISTS upgrade_proposals (
                    proposal_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL, payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS proposal_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, proposal_id TEXT NOT NULL,
                    decision TEXT NOT NULL, developer_id TEXT NOT NULL,
                    reason TEXT NOT NULL, decided_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS modification_attempts (
                    attempt_id TEXT PRIMARY KEY, proposal_id TEXT, path TEXT NOT NULL,
                    status TEXT NOT NULL, created_at_utc TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS validation_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id TEXT NOT NULL,
                    passed INTEGER NOT NULL, check_name TEXT NOT NULL,
                    detail TEXT NOT NULL, checked_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rollback_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id TEXT NOT NULL,
                    status TEXT NOT NULL, detail TEXT NOT NULL,
                    occurred_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS consent_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, telemetry_level TEXT NOT NULL,
                    source TEXT NOT NULL, changed_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS developer_registry (
                    developer_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dispatch_queue (
                    dispatch_id TEXT PRIMARY KEY, report_type TEXT NOT NULL,
                    status TEXT NOT NULL, payload_json TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT
                );
                CREATE TABLE IF NOT EXISTS audit_chain (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_type TEXT NOT NULL, record_id TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    previous_hash TEXT NOT NULL, chain_hash TEXT NOT NULL
                );
                """
