"""Header fingerprint: recognises a partner's file layout regardless of column order or spacing."""

import hashlib
import re


def normalise_header(header: str) -> str:
    """Lower-case, trimmed, inner whitespace collapsed: 'Order  ID ' -> 'order id'."""
    return re.sub(r"\s+", " ", str(header).strip().lower())


def header_fingerprint(headers: list[str]) -> str:
    """SHA-256 of the normalised, sorted header names. Same columns in any order -> same fingerprint."""
    names = sorted(normalise_header(header) for header in headers if str(header).strip())
    return hashlib.sha256("\x1f".join(names).encode("utf-8")).hexdigest()
