"""Review annotations are separate from observed differences and Health decisions."""
from copy import deepcopy
from datetime import datetime
import re

from ..schema import validate_document
from .domain import RouteInputError


def review_catalog(model):
    return {projection["entry_key"]: dict(resource=row["resource"], mode=mode)
            for row in model["rows"] for mode, projection in row["modes"].items()
            if projection["entry_key"] is not None}


def validate_review(document, model):
    validate_document(document, kind="RouteDiffReview")
    if document["comparison_fingerprint"] != model["result"]["comparison_fingerprint"]:
        raise RouteInputError("/comparison_fingerprint", "review belongs to another comparison")
    catalog, seen = review_catalog(model), set()
    for entry in document["entries"]:
        key = entry["entry_key"]
        if key in seen or key not in catalog or any(entry[k] != catalog[key][k] for k in ("resource", "mode")):
            raise RouteInputError("/entries", "unknown, duplicate or mismatched review entry")
        if (entry["status"] == "REVIEWED") != (entry["reviewed_at"] is not None):
            raise RouteInputError("/entries/reviewed_at", "review timestamp must agree with status")
        if entry["reviewed_at"] is not None:
            stamp = entry["reviewed_at"]
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", stamp, re.IGNORECASE):
                    raise ValueError("invalid date-time")
                if not stamp.upper().endswith("Z") and (int(stamp[-5:-3]) >= 24 or int(stamp[-2:]) >= 60):
                    raise ValueError("invalid timezone offset")
                parsed = datetime.fromisoformat(stamp.upper().replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("timezone required")
            except ValueError as error:
                raise RouteInputError("/entries/reviewed_at", "invalid review date-time") from error
        seen.add(key)
    return deepcopy(document)
