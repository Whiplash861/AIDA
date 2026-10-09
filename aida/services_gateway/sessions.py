"""Device sessions; only token hashes are retained on the gateway."""
from __future__ import annotations
import hashlib
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class DeviceSession:
    session_id: str
    device_id: str
    expires_at: int

class SessionStore:
    def __init__(self, path: str | Path | None = None, *, lifetime: int = 604800):
        self.path = Path(path or os.getenv("AIDA_GATEWAY_SESSION_DB") or Path.home() / ".aida" / "gateway" / "sessions.sqlite3")
        self.lifetime = max(60, min(lifetime, 30 * 86400))

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(self.path, timeout=5)
        if os.name != "nt":
            self.path.chmod(0o600)
        connection.execute("CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, session_id TEXT UNIQUE NOT NULL, device_id TEXT NOT NULL, expires_at INTEGER NOT NULL)")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def issue(self) -> tuple[str, DeviceSession]:
        token = secrets.token_urlsafe(48)
        session = DeviceSession(secrets.token_hex(16), secrets.token_hex(16), int(time.time()) + self.lifetime)
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
            connection.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)", (self._hash(token), session.session_id, session.device_id, session.expires_at))
        return token, session

    def authenticate(self, token: str) -> DeviceSession | None:
        if not token or len(token) > 512 or not token.isascii():
            return None
        with self._connect() as connection:
            row = connection.execute("SELECT session_id, device_id, expires_at FROM sessions WHERE token_hash = ? AND expires_at > ?", (self._hash(token), int(time.time()))).fetchone()
        return DeviceSession(*row) if row else None

    def revoke(self, session: DeviceSession) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE session_id = ?", (session.session_id,))

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()
