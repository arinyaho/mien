from __future__ import annotations

from string import Formatter

# The built-in templates. Defined here, beside the renderer, rather than at each
# use, so the parser's fallback (`mien.config._config_from_dict`), the fresh
# config `mien init` writes, and the fix a template error recommends cannot drift
# apart -- a message that recommended a template the parser then refused would be
# worse than no message.
BUILTIN_DEFAULT = "mien-{profile}-{service}-{kind}"
BUILTIN_SLACK_TOKEN = "mien-{profile}-slack-{workspace}-token"

# The tokens each template is rendered with, and therefore the ones it MUST
# spend, one secret name per credential. Read off the `render_name` call sites in
# `mien login`; every one of the three is load-bearing:
#
# - `kind` separates two credentials of ONE service on one profile: github's
#   `token` from its `ssh_key`, google's `oauth_client_secret` from its
#   `refresh`, aws's `access_key_id` from its `secret_access_key` -- and, for
#   `--service custom`, one variable name from the next, which is the whole of
#   what keeps `ANTHROPIC_API_KEY` and `NPM_TOKEN` apart.
# - `service` separates two services on one profile: atlassian's `api_token`
#   from notion's, which are the same `kind` under different services.
# - `profile` separates the identities, which is mien's entire purpose: without
#   it `work` and `personal` share one github token secret.
# - `workspace` (slack only) separates two Slack workspaces on one profile.
#
# `slack_token` gets no `service` token because the literal "slack" is the
# template's own job; it is not something mien substitutes.
REQUIRED_TOKENS: dict[str, tuple[str, ...]] = {
    "default": ("profile", "service", "kind"),
    "slack_token": ("profile", "workspace"),
}

# What a template that drops a token collapses onto a single secret name. Used to
# say, in the error, which credentials would land on top of each other.
TOKEN_SEPARATES: dict[str, str] = {
    "profile": "every profile renders the same name",
    "service": "every service renders the same name",
    "kind": "every credential of one service renders the same name, and every "
            "`--service custom` variable with it",
    "workspace": "every Slack workspace renders the same name",
}


def render_name(template: str, **tokens: str) -> str:
    return template.format_map(_StrictDict(tokens))


def template_tokens(template: str) -> set[str]:
    """The token names ``template`` actually substitutes.

    Parsed with ``string.Formatter`` rather than searched for as substrings,
    because the two disagree in exactly the cases that matter. ``"{{kind}}"`` is
    an escaped literal that renders the characters ``{kind}`` for every
    credential -- it contains ``{kind}`` and substitutes nothing. And a field
    that only reaches INTO the token (``{kind[0]}``, ``{kind.foo}``) does not
    reproduce it, so two kinds sharing a first character still collide; those
    field names are not ``kind`` and are deliberately not counted.

    A malformed template (``"mien-{profile"``) raises ``ValueError`` from
    ``parse``, which is the caller's to translate -- it is a template that cannot
    render at all.
    """
    return {
        name for _, name, _, _ in Formatter().parse(template) if name is not None
    }


class _StrictDict(dict):
    def __missing__(self, key: str) -> str:
        raise KeyError(f"missing token {{{key}}} in template")
