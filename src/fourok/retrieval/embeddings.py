from __future__ import annotations

import json
import math
import os
import re
import urllib.request
from dataclasses import dataclass
from hashlib import blake2b
from typing import Any

HASH_EMBEDDING_DIMENSIONS = 32
OPENAI_EMBEDDING_DIMENSIONS = 256
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"

_urlopen = urllib.request.urlopen


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    text: str


def chunk_text(text: str, *, max_words: int = 90, overlap_words: int = 15) -> list[Chunk]:
    words = text.split()
    if not words:
        return []
    if max_words <= overlap_words:
        raise ValueError("max_words must be greater than overlap_words")

    chunks: list[Chunk] = []
    start = 0
    while start < len(words):
        chunk_words = words[start : start + max_words]
        chunks.append(Chunk(chunk_index=len(chunks), text=" ".join(chunk_words)))
        if start + max_words >= len(words):
            break
        start += max_words - overlap_words
    return chunks


def embed_text(text: str, *, dimensions: int | None = None) -> list[float]:
    provider = embedding_provider()
    resolved_dimensions = dimensions or embedding_dimensions()
    if provider == "openai":
        return _openai_embed_text(text, dimensions=resolved_dimensions)
    return _hash_embed_text(text, dimensions=resolved_dimensions)


def embedding_provider() -> str:
    configured = os.environ.get("FOUROK_EMBEDDING_PROVIDER")
    if configured:
        return configured.strip().casefold()
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "hash"


def embedding_dimensions() -> int:
    configured = os.environ.get("FOUROK_EMBEDDING_DIMENSIONS")
    if configured:
        return int(configured)
    if embedding_provider() == "openai":
        return OPENAI_EMBEDDING_DIMENSIONS
    return HASH_EMBEDDING_DIMENSIONS


def cosine_similarity(left: list[float], right: list[float]) -> float:
    return sum(
        left_value * right_value for left_value, right_value in zip(left, right, strict=True)
    )


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def _hash_embed_text(text: str, *, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    for term in _terms(text):
        digest = blake2b(term.encode(), digest_size=4, person=b"fourokembed").digest()
        bucket = int.from_bytes(digest[:2], "big") % dimensions
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[bucket] += sign

    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return vector
    return [value / magnitude for value in vector]


def _openai_embed_text(text: str, *, dimensions: int) -> list[float]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required when FOUROK_EMBEDDING_PROVIDER=openai")
    model = os.environ.get("FOUROK_OPENAI_EMBEDDING_MODEL", OPENAI_EMBEDDING_MODEL)
    endpoint = os.environ.get("FOUROK_OPENAI_EMBEDDING_URL", "https://api.openai.com/v1/embeddings")
    payload = {
        "model": model,
        "input": text,
        "dimensions": dimensions,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with _urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    embedding = _extract_openai_embedding(body)
    if len(embedding) != dimensions:
        raise RuntimeError(
            f"OpenAI embedding returned {len(embedding)} dimensions; expected {dimensions}"
        )
    return embedding


def _extract_openai_embedding(body: dict[str, Any]) -> list[float]:
    data = body.get("data")
    if not isinstance(data, list) or not data:
        raise RuntimeError("OpenAI embedding response did not include data")
    first = data[0]
    if not isinstance(first, dict):
        raise RuntimeError("OpenAI embedding response data item was not an object")
    embedding = first.get("embedding")
    if not isinstance(embedding, list):
        raise RuntimeError("OpenAI embedding response did not include embedding")
    return [float(value) for value in embedding]


def _terms(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.casefold())
