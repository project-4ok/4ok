from gcb.honcho.preflight import (
    REQUIRED_SOURCE_SECRETS,
    source_connection_preflight,
    source_secret_preflight,
)


def test_source_secret_preflight_reports_presence_without_values() -> None:
    report = source_secret_preflight(
        {
            "LINEAR_API_KEY": "linear-secret",
            "TWENTY_API_KEY": "twenty-secret",
            "SLACK_BOT_TOKEN": "slack-secret",
        }
    )

    assert report == {
        "status": "ok",
        "required": list(REQUIRED_SOURCE_SECRETS),
        "available": {
            "LINEAR_API_KEY": True,
            "TWENTY_API_KEY": True,
            "SLACK_BOT_TOKEN": True,
        },
        "missing": [],
    }
    assert "linear-secret" not in str(report)
    assert "twenty-secret" not in str(report)
    assert "slack-secret" not in str(report)


def test_source_secret_preflight_reports_missing_secrets() -> None:
    report = source_secret_preflight({"LINEAR_API_KEY": "linear-secret"})

    assert report["status"] == "missing"
    assert report["available"] == {
        "LINEAR_API_KEY": True,
        "TWENTY_API_KEY": False,
        "SLACK_BOT_TOKEN": False,
    }
    assert report["missing"] == ["TWENTY_API_KEY", "SLACK_BOT_TOKEN"]


def test_source_connection_preflight_checks_sources_independently_without_values() -> None:
    calls: list[set[str]] = []

    def fake_collect(secrets, *, limit, sources):
        calls.append(sources)
        assert secrets["LINEAR_API_KEY"] == "linear-secret"
        if sources == {"twenty"}:
            raise RuntimeError("GraphQL request failed with HTTP 403")
        return {"linear_users": [], "slack_users": []}

    report = source_connection_preflight(
        {
            "LINEAR_API_KEY": "linear-secret",
            "TWENTY_API_KEY": "twenty-secret",
            "SLACK_BOT_TOKEN": "slack-secret",
        },
        sources={"linear", "twenty"},
        collect_snapshot=fake_collect,
    )

    assert calls == [{"linear"}, {"twenty"}]
    assert report == {
        "status": "failed",
        "sources": {
            "linear": {"status": "ok"},
            "twenty": {
                "status": "failed",
                "error": "GraphQL request failed with HTTP 403",
            },
        },
    }
    assert "linear-secret" not in str(report)
    assert "twenty-secret" not in str(report)
