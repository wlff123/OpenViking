from __future__ import annotations

import hashlib
import hmac


def compute_issue_revision(title: str, body: str | None) -> str:
    payload = f"{title}\0{body or ''}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_hmac_signature(
    secret: bytes,
    body: bytes,
    supplied: str | None,
    *,
    prefix: str = "",
) -> bool:
    if not supplied or not supplied.startswith(prefix):
        return False
    expected = prefix + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)
