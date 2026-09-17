import json

from mien.security import redact, register_secret


def test_redaction_covers_known_values_headers_json_maps_and_exception_args(
    monkeypatch, tmp_path
):
    env_sentinel = "sentinel-env-token"
    map_sentinel = "sentinel-json-token"
    explicit_sentinel = "sentinel-exception-token"
    credential_map = tmp_path / "slack.json"
    credential_map.write_text(json.dumps({"team-a": map_sentinel}))

    monkeypatch.setenv("NPM_TOKEN", env_sentinel)
    monkeypatch.setenv("MIEN_SLACK_TOKENS", str(credential_map))
    register_secret(explicit_sentinel)
    exc = OSError(
        2,
        "Authorization: Bearer header-sentinel",
        explicit_sentinel,
    )

    output = redact(
        f"{exc}; env={env_sentinel}; map={map_sentinel}; "
        "Authorization: Basic basic-sentinel"
    )

    for sentinel in (
        env_sentinel, map_sentinel, explicit_sentinel,
        "header-sentinel", "basic-sentinel",
    ):
        assert sentinel not in output
    assert output.count("[REDACTED]") >= 5
