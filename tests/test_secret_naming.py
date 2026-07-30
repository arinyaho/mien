import pytest

from mien.secret_naming import (BUILTIN_DEFAULT, BUILTIN_SLACK_TOKEN,
                                REQUIRED_TOKENS, render_name, template_tokens)


def test_renders_default_template():
    assert render_name(
        "mien-{profile}-{service}-{kind}",
        profile="personal", service="google", kind="refresh",
    ) == "mien-personal-google-refresh"


def test_renders_slack_template_with_workspace():
    assert render_name(
        "mien-{profile}-slack-{workspace}-token",
        profile="work", workspace="team-a",
    ) == "mien-work-slack-team-a-token"


def test_missing_token_raises():
    with pytest.raises(KeyError):
        render_name("mien-{profile}-{kind}", profile="x")


def test_template_tokens_reports_what_a_template_substitutes():
    assert template_tokens(BUILTIN_DEFAULT) == {"profile", "service", "kind"}
    assert template_tokens(BUILTIN_SLACK_TOKEN) == {"profile", "workspace"}
    assert template_tokens("mien-secret") == set()


def test_template_tokens_counts_only_what_actually_substitutes():
    """The two cases that make a substring search for "{kind}" the wrong test.

    `{{kind}}` is an escaped literal — it renders the characters `{kind}` for
    every credential — and `{kind[0]}` reproduces one character of the token, so
    two kinds sharing a first character still render the same name. Neither keeps
    two credentials apart, so neither counts as the token being present.
    """
    assert template_tokens("mien-{profile}-{{kind}}") == {"profile"}
    assert render_name("mien-{profile}-{{kind}}", profile="work") == "mien-work-{kind}"
    assert "kind" not in template_tokens("mien-{profile}-{kind[0]}")


def test_the_builtin_templates_spend_every_token_they_are_rendered_with():
    """The rule's own fixed point: what mien ships must satisfy what mien demands."""
    assert set(REQUIRED_TOKENS["default"]) <= template_tokens(BUILTIN_DEFAULT)
    assert set(REQUIRED_TOKENS["slack_token"]) <= template_tokens(BUILTIN_SLACK_TOKEN)
