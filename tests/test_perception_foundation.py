from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from aida.perception.models import EvidenceKind, EvidenceSource
from aida.perception.service import PerceptionService


class PerceptionServiceTests(unittest.TestCase):
    def test_observe_image_creates_local_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "screenshot.png"
            path.write_bytes(b"not-a-real-image-but-valid-test-fixture")

            evidence = PerceptionService().observe_image(
                path,
                source=EvidenceSource.FILE_PICKER,
            )

            self.assertEqual(evidence.kind, EvidenceKind.SCREENSHOT)
            self.assertEqual(evidence.source, EvidenceSource.FILE_PICKER)
            self.assertEqual(evidence.local_path, path.resolve())
            self.assertEqual(len(evidence.sha256 or ""), 64)
            self.assertTrue(evidence.unknown)

    def test_rejects_unsupported_file_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "notes.txt"
            path.write_text("test", encoding="utf-8")
            with self.assertRaises(ValueError):
                PerceptionService().observe_image(
                    path,
                    source=EvidenceSource.DRAG_DROP,
                )


if __name__ == "__main__":
    unittest.main()
