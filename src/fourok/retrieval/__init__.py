def __getattr__(name: str):
    if name == "RetrievalAPI":
        from fourok.retrieval.api import RetrievalAPI

        return RetrievalAPI
    raise AttributeError(f"{__name__} has no attribute {name!r}")


__all__ = ["RetrievalAPI"]
