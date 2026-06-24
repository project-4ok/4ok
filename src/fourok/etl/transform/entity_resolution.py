from __future__ import annotations

import contextlib
import io
import json
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path


@dataclass(frozen=True)
class LabeledIdentity:
    identity_ref: str
    source_system: str
    identity_type: str
    value: str
    display_name: str
    expected_entity: str


@dataclass(frozen=True)
class EntityResolutionMetrics:
    identity_count: int
    expected_entity_count: int
    predicted_entity_count: int
    pair_count: int
    true_positive_pairs: int
    false_positive_pairs: int
    false_negative_pairs: int
    precision: float
    recall: float


@dataclass(frozen=True)
class EntityLinkCandidate:
    left_ref: str
    right_ref: str
    method: str
    decision: str
    expected_match: bool


def load_labeled_identities(path: Path) -> list[LabeledIdentity]:
    raw_identities = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_identities, list):
        raise ValueError("Entity resolution fixture must be a list")
    return [_labeled_identity(raw_identity) for raw_identity in raw_identities]


def exact_email_clusters(identities: list[LabeledIdentity]) -> dict[str, str]:
    return {
        identity.identity_ref: f"exact_email:{identity.value.strip().casefold()}"
        for identity in identities
    }


def display_name_email_alias_clusters(
    identities: list[LabeledIdentity],
    *,
    similarity_threshold: float = 0.8,
) -> dict[str, str]:
    clusters = exact_email_clusters(identities)
    identities_by_ref = {identity.identity_ref: identity for identity in identities}

    for left in identities:
        for right in identities:
            if left.identity_ref >= right.identity_ref:
                continue
            if not _same_email_domain(left, right):
                continue
            if (
                _display_name_similarity(left.display_name, right.display_name)
                < similarity_threshold
            ):
                continue
            _merge_clusters(
                clusters,
                source_cluster=clusters[right.identity_ref],
                target_cluster=clusters[left.identity_ref],
            )

    return {identity_ref: clusters[identity_ref] for identity_ref in sorted(identities_by_ref)}


def splink_probability_clusters(
    identities: list[LabeledIdentity],
    *,
    threshold: float = 0.7,
) -> dict[str, str]:
    import pandas as pd
    from splink import Linker, SettingsCreator, block_on
    from splink import comparison_library as cl
    from splink.internals.duckdb.database_api import DuckDBAPI

    records = [
        {
            "unique_id": identity.identity_ref,
            "source_dataset": identity.source_system,
            "email": identity.value.strip().casefold(),
            "display_name": identity.display_name,
            "email_domain": _email_domain(identity.value),
            "expected_entity": identity.expected_entity,
        }
        for identity in identities
    ]
    settings = SettingsCreator(
        link_type="dedupe_only",
        comparisons=[
            cl.EmailComparison("email"),
            cl.NameComparison("display_name"),
        ],
        blocking_rules_to_generate_predictions=[block_on("email_domain")],
        probability_two_random_records_match=0.2,
        retain_matching_columns=True,
    )
    linker = Linker(
        pd.DataFrame(records),
        settings,
        DuckDBAPI(),
        set_up_basic_logging=False,
    )
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        linker.training.estimate_m_from_label_column("expected_entity")
        linker.training.estimate_u_using_random_sampling(max_pairs=1000, seed=1)
        predictions = linker.inference.predict(threshold_match_probability=0.0)
        prediction_rows = predictions.as_record_dict()

    clusters = {identity.identity_ref: identity.identity_ref for identity in identities}
    for row in prediction_rows:
        if row["match_probability"] >= threshold:
            _merge_clusters(
                clusters,
                source_cluster=clusters[row["unique_id_r"]],
                target_cluster=clusters[row["unique_id_l"]],
            )
    return clusters


def evaluate_clusters(
    identities: list[LabeledIdentity],
    predicted_clusters: dict[str, str],
) -> EntityResolutionMetrics:
    expected_pairs = _positive_pairs(
        {identity.identity_ref: identity.expected_entity for identity in identities}
    )
    predicted_pairs = _positive_pairs(predicted_clusters)
    true_positive_pairs = len(expected_pairs.intersection(predicted_pairs))
    false_positive_pairs = len(predicted_pairs - expected_pairs)
    false_negative_pairs = len(expected_pairs - predicted_pairs)
    precision = _rate(true_positive_pairs, true_positive_pairs + false_positive_pairs)
    recall = _rate(true_positive_pairs, true_positive_pairs + false_negative_pairs)

    return EntityResolutionMetrics(
        identity_count=len(identities),
        expected_entity_count=len({identity.expected_entity for identity in identities}),
        predicted_entity_count=len(set(predicted_clusters.values())),
        pair_count=len(expected_pairs),
        true_positive_pairs=true_positive_pairs,
        false_positive_pairs=false_positive_pairs,
        false_negative_pairs=false_negative_pairs,
        precision=precision,
        recall=recall,
    )


def review_candidates(
    identities: list[LabeledIdentity],
    *,
    method: str,
    predicted_clusters: dict[str, str],
) -> list[EntityLinkCandidate]:
    expected_clusters = {identity.identity_ref: identity.expected_entity for identity in identities}
    decision = "accept" if method == "exact_email" else "review"
    return [
        EntityLinkCandidate(
            left_ref=left_ref,
            right_ref=right_ref,
            method=method,
            decision=decision,
            expected_match=expected_clusters[left_ref] == expected_clusters[right_ref],
        )
        for left_ref, right_ref in sorted(_positive_pairs(predicted_clusters))
    ]


def _labeled_identity(raw_identity: object) -> LabeledIdentity:
    if not isinstance(raw_identity, dict):
        raise ValueError("Entity resolution identity must be an object")
    return LabeledIdentity(
        identity_ref=_required_string(raw_identity, "identity_ref"),
        source_system=_required_string(raw_identity, "source_system"),
        identity_type=_required_string(raw_identity, "identity_type"),
        value=_required_string(raw_identity, "value"),
        display_name=_required_string(raw_identity, "display_name"),
        expected_entity=_required_string(raw_identity, "expected_entity"),
    )


def _required_string(raw_identity: dict[str, object], key: str) -> str:
    value = raw_identity.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Entity resolution identity requires string field: {key}")
    return value


def _same_email_domain(left: LabeledIdentity, right: LabeledIdentity) -> bool:
    return _email_domain(left.value) != "" and _email_domain(left.value) == _email_domain(
        right.value
    )


def _email_domain(value: str) -> str:
    if "@" not in value:
        return ""
    return value.rsplit("@", maxsplit=1)[1].casefold()


def _display_name_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, _normalize_name(left), _normalize_name(right)).ratio()


def _normalize_name(value: str) -> str:
    return " ".join(value.casefold().replace(".", " ").split())


def _merge_clusters(
    clusters: dict[str, str],
    *,
    source_cluster: str,
    target_cluster: str,
) -> None:
    if source_cluster == target_cluster:
        return
    for identity_ref, cluster in list(clusters.items()):
        if cluster == source_cluster:
            clusters[identity_ref] = target_cluster


def _positive_pairs(clusters: dict[str, str]) -> set[tuple[str, str]]:
    refs = sorted(clusters)
    pairs = set()
    for index, left_ref in enumerate(refs):
        for right_ref in refs[index + 1 :]:
            if clusters[left_ref] == clusters[right_ref]:
                pairs.add((left_ref, right_ref))
    return pairs


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator
