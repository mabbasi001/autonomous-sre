"""The fixed action catalogue. Anything not listed here cannot be
proposed, approved, or executed - there is no way to register an action
at runtime.
"""

READ_ONLY = "read_only"
LOW = "low"

CATALOGUE = {
    "service.status": {"risk": READ_ONLY},
    "http.check": {"risk": READ_ONLY},
    "logs.collect_excerpt": {"risk": READ_ONLY},
    "service.restart": {"risk": LOW},
}


def risk_of(action: str) -> str | None:
    entry = CATALOGUE.get(action)
    return entry["risk"] if entry else None
