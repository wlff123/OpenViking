from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import time
import urllib.request
from typing import Any


def encode_signed_callback(payload: dict[str, Any], secret: bytes) -> tuple[bytes, str]:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return body, signature


def send_callback(url: str, payload: dict[str, Any], secret: bytes) -> None:
    body, signature = encode_signed_callback(payload, secret)
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Viking-Forge-Signature": signature,
        },
        method="POST",
    )
    delays = (0, 2, 8)
    for index, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                if 200 <= response.status < 300:
                    return
        except Exception:
            if index == len(delays) - 1:
                raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--secret", required=True)
    parser.add_argument("--payload", required=True)
    args = parser.parse_args()
    send_callback(args.url, json.loads(args.payload), args.secret.encode())


if __name__ == "__main__":
    main()
