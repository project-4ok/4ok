from pathlib import Path

import pytest

from fourok.etl.transform.entity_resolution import (
    display_name_email_alias_clusters,
    evaluate_clusters,
    exact_email_clusters,
    load_labeled_identities,
    review_candidates,
    splink_probability_clusters,
)

FIXTURE = (
    Path(__file__).parents[2] / "fixtures" / "entity_resolution" / "multi_source_identities.json"
)


def test_exact_email_baseline_has_no_false_merges_but_has_false_splits() -> None:
    identities = load_labeled_identities(FIXTURE)
    metrics = evaluate_clusters(identities, exact_email_clusters(identities))

    assert metrics.identity_count == 10
    assert metrics.expected_entity_count == 5
    assert metrics.predicted_entity_count == 7
    assert metrics.true_positive_pairs == 3
    assert metrics.false_positive_pairs == 0
    assert metrics.false_negative_pairs == 4
    assert metrics.precision == 1.0
    assert metrics.recall == pytest.approx(3 / 7)


def test_cluster_evaluation_detects_false_merge() -> None:
    identities = load_labeled_identities(FIXTURE)
    predicted_clusters = exact_email_clusters(identities)
    predicted_clusters["gmail:email:anna.refunds@example.com"] = "bad:shared"
    predicted_clusters["gmail:email:sam.support@example.com"] = "bad:shared"

    metrics = evaluate_clusters(identities, predicted_clusters)

    assert metrics.false_positive_pairs == 1
    assert metrics.precision < 1.0


def test_display_name_alias_baseline_improves_recall_but_creates_false_merge() -> None:
    identities = load_labeled_identities(FIXTURE)
    metrics = evaluate_clusters(identities, display_name_email_alias_clusters(identities))

    assert metrics.predicted_entity_count == 4
    assert metrics.true_positive_pairs == 7
    assert metrics.false_positive_pairs == 1
    assert metrics.false_negative_pairs == 0
    assert metrics.precision == pytest.approx(7 / 8)
    assert metrics.recall == 1.0


def test_entity_link_review_rules_accept_exact_email_and_review_aliases() -> None:
    identities = load_labeled_identities(FIXTURE)
    exact_candidates = review_candidates(
        identities,
        method="exact_email",
        predicted_clusters=exact_email_clusters(identities),
    )
    alias_candidates = review_candidates(
        identities,
        method="display_name_email_alias",
        predicted_clusters=display_name_email_alias_clusters(identities),
    )

    assert {candidate.decision for candidate in exact_candidates} == {"accept"}
    assert all(candidate.expected_match for candidate in exact_candidates)
    assert {candidate.decision for candidate in alias_candidates} == {"review"}
    assert any(not candidate.expected_match for candidate in alias_candidates)
    assert (
        "gmail:email:alex.owner@example.com",
        "slack:email:alex.legal@example.com",
    ) in {
        (candidate.left_ref, candidate.right_ref)
        for candidate in alias_candidates
        if not candidate.expected_match
    }


def test_splink_probability_experiment_matches_alias_tradeoff_on_small_fixture() -> None:
    identities = load_labeled_identities(FIXTURE)
    metrics = evaluate_clusters(identities, splink_probability_clusters(identities))

    assert metrics.true_positive_pairs == 7
    assert metrics.false_positive_pairs == 1
    assert metrics.false_negative_pairs == 0
    assert metrics.precision == pytest.approx(7 / 8)
    assert metrics.recall == 1.0
