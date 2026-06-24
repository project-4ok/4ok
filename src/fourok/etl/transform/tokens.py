"""Deferred token formatting helpers for future PII/tokenization work."""

from __future__ import annotations

from hashlib import blake2b

TOKEN_PREFIX = {
    "iban": "BANK_ACCOUNT",
    "email": "EMAIL",
    "phone": "PHONE",
    "payment_identifier": "PAYMENT_ID",
    "address": "ADDRESS",
    "person": "PERSON",
    "organization": "ORGANIZATION",
    "location": "LOCATION",
}


def normalize_token_value(*, token_type: str, raw_value: str) -> str:
    value = " ".join(raw_value.strip().split())
    if token_type in {"email", "iban", "payment_identifier"}:
        return value.upper()
    if token_type == "phone":
        return "".join(character for character in value if character.isdigit() or character == "+")
    return value.casefold()


def deterministic_token(*, token_type: str, normalized_value: str) -> str:
    digest = blake2b(
        f"{token_type}:{normalized_value}".encode(),
        digest_size=8,
        person=b"4oktoken",
    ).hexdigest()
    return f"{TOKEN_PREFIX[token_type]}_{digest.upper()}"
