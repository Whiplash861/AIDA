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


def test_known_hash_mismatch_is_never_promoted_to_identity(tmp_path):
    target = tmp_path / "sample.exe"
    target.write_bytes(b"changed content")
    stat = target.stat()
    result = EvidenceNavigationService().locate(target, expected_sha256="0" * 64,
        expected_size=stat.st_size, expected_modified_ns=stat.st_mtime_ns, roots=[tmp_path])
    assert result.exact_match_found is False
    assert all(item.match_type is EvidenceMatchType.POSSIBLE_FILENAME for item in result.matches)
    assert "differs" in result.matches[0].reason


def test_existing_path_must_match_supplied_size(tmp_path):
    target = tmp_path / "sample.exe"
    target.write_bytes(b"changed")
    result = EvidenceNavigationService().locate(target, expected_size=999, roots=[tmp_path])
    assert not result.exact_match_found


def test_hashing_obeys_time_budget(tmp_path):
    target = tmp_path / "large.bin"
    target.write_bytes(b"x" * (2 * 1024 * 1024))
    ticks = iter([0, 2, 3, 4, 5])
    service = EvidenceNavigationService(clock=lambda: next(ticks), timeout_seconds=1)
    result = service.locate(target, expected_sha256="0" * 64, roots=[tmp_path])
    assert result.truncated
    assert not result.exact_match_found
