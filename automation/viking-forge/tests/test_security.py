import hashlib
import hmac

from viking_forge.security import compute_issue_revision, verify_hmac_signature


def test_issue_revision_changes_only_with_title_or_body():
    first = compute_issue_revision("Title", "Body")
    second = compute_issue_revision("Title", "Body")
    changed = compute_issue_revision("Title", "Changed")

    assert first == second
    assert first != changed
    assert first == hashlib.sha256(b"Title\0Body").hexdigest()


def test_hmac_signature_uses_raw_body_and_constant_format():
    body = b'{"action":"opened"}'
    secret = b"secret"
    supplied = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()

    assert verify_hmac_signature(secret, body, supplied, prefix="sha256=") is True
    assert verify_hmac_signature(secret, body + b" ", supplied, prefix="sha256=") is False
    assert verify_hmac_signature(secret, body, "broken", prefix="sha256=") is False
