"""Transport-independent progress and cooperative cancellation for route processing."""
from dataclasses import dataclass, field
from typing import Callable


class RouteProcessingCancelled(Exception):
    """The future CLI maps this explicit interruption to exit code 130."""
    exit_code = 130


@dataclass(frozen=True)
class ProcessingControl:
    on_progress: Callable[[dict], None] | None = None
    is_cancelled: Callable[[], bool] | None = None
    _validated: set[tuple[str, str]] = field(default_factory=set, init=False, compare=False, repr=False)

    @staticmethod
    def validation_digest(document):
        from ..schema import canonical_sha256

        # JSON encodes tuples like lists and integer keys like strings. Such Python
        # values must still reach schema validation, even if their JSON hashes match.
        pending = [document]
        seen = set()
        while pending:
            value = pending.pop()
            if type(value) in (dict, list):
                if id(value) in seen:
                    continue
                seen.add(id(value))
            if type(value) is dict:
                if any(type(key) is not str for key in value):
                    return None
                pending.extend(value.values())
            elif type(value) is list:
                pending.extend(value)
            elif type(value) not in (str, int, float, bool, type(None)):
                return None
        try:
            return canonical_sha256(document)
        except (ValueError, TypeError, RecursionError):
            return None

    def was_validated(self, kind: str, content_digest: str | None) -> bool:
        return content_digest is not None and (kind, content_digest) in self._validated

    def remember_validated(self, kind: str, content_digest: str | None) -> None:
        if content_digest is None:
            return
        # Store only hashes, never the large documents or mutable object identities.
        if len(self._validated) >= 8:
            self._validated.clear()
        self._validated.add((kind, content_digest))

    def checkpoint(self, stage: str, completed: int, total: int | None, *, unit: str = "lines", **context):
        if self.is_cancelled is not None and self.is_cancelled():
            raise RouteProcessingCancelled("route processing cancelled")
        if self.on_progress is not None:
            self.on_progress(dict(stage=stage, completed=completed, total=total, unit=unit, **context))
