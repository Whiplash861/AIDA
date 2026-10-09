from __future__ import annotations

import json
from aida.artificer.models import SourceReviewAnnotation, utc_now


class LedgerReviewsMixin:
    def store_source_review(self, annotation: SourceReviewAnnotation) -> SourceReviewAnnotation:
        with self._lock, self._connect() as connection:
            existing = connection.execute("SELECT payload_json FROM source_reviews WHERE review_id=?", (annotation.review_id,)).fetchone()
            if existing:
                return SourceReviewAnnotation.from_record(json.loads(existing[0]))
            payload = annotation.to_record()
            connection.execute("INSERT INTO source_reviews VALUES(?,?,?,?,?,?)", (
                annotation.review_id, annotation.finding_id, annotation.path, annotation.source_sha256,
                annotation.created_at_utc.isoformat(), self._json(payload)))
            self._chain(connection, "source_review", annotation.review_id, payload)
        return annotation

    def get_source_review(self, review_id: str) -> SourceReviewAnnotation | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT payload_json FROM source_reviews WHERE review_id=?", (review_id,)).fetchone()
        return SourceReviewAnnotation.from_record(json.loads(row[0])) if row else None

    def list_source_reviews(self, *, finding_id: str | None = None, limit: int = 100, open_only: bool = True) -> list[SourceReviewAnnotation]:
        sql = "SELECT r.payload_json FROM source_reviews r JOIN artificer_findings f ON f.finding_id=r.finding_id WHERE 1=1"
        arguments = []
        if open_only:
            sql += " AND f.status='open'"
        if finding_id is not None:
            sql += " AND r.finding_id=?"
            arguments.append(finding_id)
        sql += " ORDER BY r.created_at_utc DESC,r.review_id LIMIT ?"
        arguments.append(max(1, min(1000, int(limit))))
        with self._lock, self._connect() as connection:
            rows = connection.execute(sql, arguments).fetchall()
        return [SourceReviewAnnotation.from_record(json.loads(row[0])) for row in rows]

    def record_source_stage(self, manifest: dict) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("INSERT INTO source_stages VALUES(?,?,?,?) ON CONFLICT(stage_id) DO UPDATE SET payload_json=excluded.payload_json", (
                manifest["stage_id"], manifest["review_id"], utc_now().isoformat(), self._json(manifest)))
            self._chain(connection, "source_stage", manifest["stage_id"], manifest)
