from __future__ import annotations

from dataclasses import dataclass

from masfactory.utils.naming import validate_name


@dataclass(frozen=True)
class PathFilter:
    """
    Compiled path filter used by NodeTemplate rule matching.

    Syntax:
      segment (">" segment)*

    Where:
      - segment is either a valid name (see `validate_name`) or a wildcard:
        - "*"  matches exactly one path segment
        - "**" matches zero or more path segments

    Matching:
      The pattern is matched against the node creation path (root > ... > owner_graph > node_name).
      Matching is "anywhere" by default (i.e., the pattern may match a contiguous slice of the path),
      with the additional semantics of "*" and "**" within the pattern.
    """

    tokens: tuple[str, ...]
    raw: str


def parse_path_filter(path_filter: str) -> PathFilter:
    if not isinstance(path_filter, str) or not path_filter.strip():
        raise ValueError("path_filter must be a non-empty string")

    raw = path_filter
    parts = [p.strip() for p in path_filter.split(">")]
    if any(p == "" for p in parts):
        raise ValueError(f"Invalid path_filter '{raw}': empty segment")

    tokens: list[str] = []
    for part in parts:
        if part in {"*", "**"}:
            tokens.append(part)
            continue
        validate_name(part, kind="path segment")
        tokens.append(part)

    return PathFilter(tokens=tuple(tokens), raw=raw)


def match_path_filter(path_filter: PathFilter, path: tuple[str, ...]) -> bool:
    """
    Return True if `path_filter` matches anywhere inside `path`.

    This is implemented by anchoring the pattern to the full path while prefixing/suffixing it with
    an implicit "**" so the match can start/end at arbitrary positions.
    """
    pattern = ("**",) + path_filter.tokens + ("**",)

    # Standard glob-style DP matching for tokens over path segments.
    memo: dict[tuple[int, int], bool] = {}

    def dp(i: int, j: int) -> bool:
        key = (i, j)
        if key in memo:
            return memo[key]

        if i == len(pattern):
            return j == len(path)

        token = pattern[i]

        if token == "**":
            # Match zero segments, or consume one segment and stay on "**".
            ans = dp(i + 1, j) or (j < len(path) and dp(i, j + 1))
        elif token == "*":
            ans = j < len(path) and dp(i + 1, j + 1)
        else:
            ans = j < len(path) and path[j] == token and dp(i + 1, j + 1)

        memo[key] = ans
        return ans

    return dp(0, 0)


__all__ = ["PathFilter", "parse_path_filter", "match_path_filter"]

