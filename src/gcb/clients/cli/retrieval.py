from __future__ import annotations

import argparse

from gcb.api.retrieval import RetrievalAPI
from gcb.cli_parts.runtime_helpers import _database_url_from_args


def retrieval_api_from_args(args: argparse.Namespace) -> RetrievalAPI:
    return RetrievalAPI(
        state=getattr(args, "state", None),
        database_url=_database_url_from_args(args),
        config=getattr(args, "config", None),
    )
