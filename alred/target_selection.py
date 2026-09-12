"""Resolve inventory targets once, before collection or device mutation."""

from dataclasses import dataclass
from logging import Logger
from typing import Any, Iterable

from .operation import OperationError
from .parsing import should_exclude, should_include


class TargetSelectionError(OperationError):
    """An explicit target selection cannot be resolved safely."""


@dataclass
class TargetSelection:
    mode: str
    tokens: list[str]
    matched_hosts: list[str]
    hosts: list[dict[str, Any]]
    skipped: int

    def context(self) -> dict[str, Any]:
        return {"mode": self.mode, "tokens": self.tokens}


def resolve_target_hosts(
    hosts: list[dict[str, Any]],
    policy: dict[str, Any],
    logger: Logger | None,
    *,
    targets: str | Iterable[str] | None = None,
    mode: str | None = None,
) -> TargetSelection:
    """Match case-sensitive hostname literals, then apply the existing policy."""
    mode = mode or "exact"
    if mode not in {"exact", "contains"}:
        raise TargetSelectionError("invalid --target-hosts-match: " + mode)
    raw = targets.split(",") if isinstance(targets, str) else list(targets or [])
    if mode == "contains" and (not raw or any(not token.strip() for token in raw)):
        raise TargetSelectionError(
            "contains requires non-empty comma-separated --target-hosts"
        )
    tokens = sorted({token.strip() for token in raw if token.strip()})
    matches = {token: [] for token in tokens}
    matched = []
    seen = set()
    for host in hosts:
        hostname = str(host.get("hostname", ""))
        if hostname in seen:
            continue
        seen.add(hostname)
        hits = [
            token
            for token in tokens
            if (token == hostname if mode == "exact" else token in hostname)
        ]
        for token in hits:
            matches[token].append(hostname)
        if not tokens or hits:
            matched.append(host)
    unmatched = [token for token, names in matches.items() if not names]
    if mode == "contains" and unmatched:
        raise TargetSelectionError(
            "No inventory hostname matches: " + ", ".join(unmatched)
        )
    selected = []
    skipped = 0
    for host in matched:
        include_ok, include_reason = should_include(host, policy)
        exclude_hit, exclude_reason = should_exclude(host, policy)
        if not include_ok or exclude_hit:
            if logger is not None:
                logger.info(
                    "SKIP %s: %s",
                    host["hostname"],
                    include_reason if not include_ok else exclude_reason,
                )
            skipped += 1
        else:
            selected.append(host)
    if logger is not None:
        logger.info(
            "Target selection mode=%s tokens=%s matched=%s selected=%s count=%d",
            mode,
            tokens,
            [host["hostname"] for host in matched],
            [host["hostname"] for host in selected],
            len(selected),
        )
    if mode == "contains" and not selected:
        raise TargetSelectionError("No target hosts remain after policy filtering")
    if mode == "contains":
        print(
            f"Target hosts (contains): {', '.join(host['hostname'] for host in selected)} ({len(selected)} hosts)"
        )
    return TargetSelection(
        mode, tokens, [host["hostname"] for host in matched], selected, skipped
    )
