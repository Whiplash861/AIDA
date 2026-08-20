import hashlib

from aida.navigation.models import EvidenceMatchType
from aida.navigation.service import EvidenceNavigationService


def test_locator_finds_moved_file_by_sha256(tmp_path):
    original = tmp_path / "old" / "sample.exe"
    moved = tmp_path / "new" / "renamed.exe"
    moved.parent.mkdir()
    moved.write_bytes(b"same evidence")
    digest = hashlib.sha256(moved.read_bytes()).hexdigest()
    service = EvidenceNavigationService(max_files=1000, timeout_seconds=5)

    result = service.locate(
        original,
        expected_sha256=digest,
        expected_size=moved.stat().st_size,
        roots=[tmp_path],
    )

    assert result.exact_match_found is True
    assert any(
        item.path == moved and item.match_type is EvidenceMatchType.EXACT_HASH
        for item in result.matches
    )


def test_navigation_opens_folder_without_launching_target(tmp_path):
    target = tmp_path / "sample.exe"
    target.write_bytes(b"test")
    launched = []
    service = EvidenceNavigationService(launcher=lambda args: launched.append(args))

    folder = service.open_containing_folder(target)

    assert folder == tmp_path
    assert launched
    assert str(target) not in launched[0]
