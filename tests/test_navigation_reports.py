from pathlib import Path

import pytest

from aida.navigation.models import EvidenceLocateResult, EvidenceMatch, EvidenceMatchType
from aida.navigation.service import render_location_result


def result(match=None, *, truncated=False):
    return EvidenceLocateResult(Path("original.exe"), (match,) if match else (), 4, .25, truncated, bool(match))


def test_exact_path_without_hash_does_not_claim_verified_content_identity():
    match = EvidenceMatch(Path("original.exe"), EvidenceMatchType.EXACT_PATH, 1, "Original path exists")
    text = render_location_result(result(match))
    assert "File found at the requested path" in text
    assert "content fingerprint was not verified" in text
    assert "Content fingerprint matches" not in text
    assert "EXACT IDENTITY MATCH" not in text


def test_hash_match_preserves_fingerprint_but_does_not_imply_safety():
    match = EvidenceMatch(Path("moved.exe"), EvidenceMatchType.EXACT_HASH, 1, "Recorded SHA-256 matches", sha256="a" * 64)
    text = render_location_result(result(match))
    assert "Content fingerprint matches the recorded file" in text
    assert "a" * 64 in text
    assert "Finding a file does not determine whether it is harmful" in text


@pytest.mark.parametrize("kind", [EvidenceMatchType.EXACT_IDENTITY, EvidenceMatchType.POSSIBLE_FILENAME])
def test_metadata_or_filename_match_requires_content_verification(kind):
    match = EvidenceMatch(Path("candidate.exe"), kind, .9, "Metadata matches")
    text = render_location_result(result(match))
    assert "matching path, name, size or date alone does not prove" in text
    assert "verify the content fingerprint before treating it as the original file" in text
    assert "Content fingerprint matches" not in text


@pytest.mark.parametrize("truncated", [False, True])
def test_no_match_is_limited_scope_not_proof_that_file_is_absent(truncated):
    text = render_location_result(result(truncated=truncated))
    assert "No matching or probable file was located within the permitted search scope" in text
    assert "does not prove that the file is absent" in text
    assert "What AIDA found" in text and "What remains unknown" in text and "What to do next" in text
    assert ("time or file limit" in text) is truncated
