"""Active governed context, policy, audit, and lifecycle control."""

from gcb.governance.context import GovernedContext, SearchContextResponse
from gcb.governance.identity import principal_from_trusted_claims
from gcb.governance.policy import PrincipalContext

__all__ = [
    "GovernedContext",
    "PrincipalContext",
    "SearchContextResponse",
    "SourceChange",
    "SourceChangeOperation",
    "principal_from_trusted_claims",
]


def __getattr__(name: str):
    if name in {"SourceChange", "SourceChangeOperation"}:
        from gcb.etl.load import source_changes

        return getattr(source_changes, name)
    raise AttributeError(name)
