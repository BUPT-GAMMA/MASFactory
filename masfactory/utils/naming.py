from __future__ import annotations

import re


_VALID_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def is_valid_name(name: str) -> bool:
    return bool(_VALID_NAME_RE.fullmatch(name))


def validate_name(name: str, *, kind: str = "name") -> None:
    if not isinstance(name, str) or not name:
        raise ValueError(f"{kind} must be a non-empty string")
    if not is_valid_name(name):
        raise ValueError(
            f"Invalid {kind} '{name}'. Only letters A–Z/a–z, digits 0–9, '_' and '-' are allowed."
        )


__all__ = ["is_valid_name", "validate_name"]

