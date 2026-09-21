from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


# One source of truth for harness detection and custom-variable refusal. This
# lives below both ``env`` and ``shell`` so environment construction can fail
# closed without creating an import cycle.
CAPTURE_MARKER_VARS: dict[str, str] = {
    "CLAUDECODE": "the marker Claude Code sets to say an agent, not a person, is driving this shell",
    "CLAUDE_CODE_ENTRYPOINT": "the marker Claude Code sets to name the agent entrypoint that is driving this shell",
    "CODEX_THREAD_ID": "the marker Codex sets to identify the agent thread driving this shell",
    "MIEN_CAPTURED": "the marker you set yourself to tell mien this harness records what mien prints",
}

LEGACY_SLACK_TOKEN_OPT_IN = "MIEN_SLACK_LEGACY_DEFAULT_TOKEN"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def capture_context() -> str | None:
    """Return the first harness marker present in the process environment.

    Presence, including an empty value, is intentionally enough. Harnesses do
    not owe mien a particular marker value, and an empty-but-present safety
    signal must not turn secret handling back on.
    """
    return next((name for name in CAPTURE_MARKER_VARS if name in os.environ), None)


def legacy_slack_token_enabled() -> bool:
    """Whether a human terminal explicitly requested the legacy raw variable."""
    return (
        capture_context() is None
        and os.environ.get(LEGACY_SLACK_TOKEN_OPT_IN, "").strip().lower()
        in _TRUE_VALUES
    )


_REGISTERED_SECRETS: set[str] = set()

# Values of these environment variables are credentials rather than selectors
# or paths. Custom variables are registered while ``build_env`` resolves them.
_DIRECT_SECRET_ENV_VARS = frozenset({
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "MIEN_SLACK_DEFAULT_TOKEN",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "ATLASSIAN_API_TOKEN",
    "NOTION_TOKEN",
})
_SECRETISH_NAME = re.compile(
    r"(?:^|_)(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY)(?:$|_)", re.I
)
_AUTH_HEADER = re.compile(
    r"(?i)(\bauthorization\s*[:=]\s*(?:bearer|basic)\s+)([^\s,;\"']+)"
)


def _redact_authorization(match: re.Match[str]) -> str:
    credential = match.group(2)
    # Documentation and actionable errors use shell placeholders. They are
    # variable names, not credential values, and must remain useful.
    if credential.startswith(("$", "<", "[REDACTED]")):
        return match.group(0)
    return match.group(1) + "[REDACTED]"


def register_secret(value: str | bytes | None) -> None:
    """Remember a resolved credential so later diagnostics can remove it."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if value:
        value = value.strip()
        # Tiny values create destructive false positives (a one-character test
        # token could erase that letter from every diagnostic). Real provider
        # credentials are substantially longer; four still covers sentinels.
        if len(value) >= 4:
            _REGISTERED_SECRETS.add(value)


def register_json_credential_map(value: Any) -> None:
    """Register every leaf value of a credential JSON object or array."""
    if isinstance(value, dict):
        for item in value.values():
            register_json_credential_map(item)
    elif isinstance(value, list):
        for item in value:
            register_json_credential_map(item)
    elif isinstance(value, (str, bytes)):
        register_secret(value)


def _register_environment_secrets() -> None:
    for name, value in os.environ.items():
        if name in _DIRECT_SECRET_ENV_VARS or _SECRETISH_NAME.search(name):
            register_secret(value)

    # A custom credential may have an innocuous name (for example `LICENSE`).
    # When the config is readable, its keys are still known secret-bearing env
    # variables and must be treated exactly like TOKEN/SECRET-shaped names.
    try:
        from mien.config import load_config

        cfg = load_config()
        if cfg:
            for profile in cfg.profiles.values():
                for name in profile.custom:
                    register_secret(os.environ.get(name))
    except Exception:
        # Redaction is called while handling failures, including config
        # failures. It must never replace the original error with its own.
        pass

    # These variables contain paths, not credentials. Their JSON payloads do
    # contain credentials, so register leaf values without ever printing them.
    for name in ("MIEN_SLACK_TOKENS", "GOOGLE_APPLICATION_CREDENTIALS"):
        raw_path = os.environ.get(name)
        if not raw_path:
            continue
        try:
            path = Path(raw_path)
            if not path.is_file() or path.stat().st_size > 1024 * 1024:
                continue
            register_json_credential_map(json.loads(path.read_text()))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue


def redact(value: object) -> str:
    """Return text safe for errors, tracebacks, logs, and diagnostics."""
    _register_environment_secrets()
    text = str(value)
    text = _AUTH_HEADER.sub(_redact_authorization, text)
    for secret in sorted(_REGISTERED_SECRETS, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


def redact_bytes(value: bytes) -> bytes:
    """Redact captured child output without assuming it is valid UTF-8."""
    _register_environment_secrets()
    redacted = value
    for secret in sorted(_REGISTERED_SECRETS, key=len, reverse=True):
        redacted = redacted.replace(secret.encode("utf-8"), b"[REDACTED]")
    try:
        return _AUTH_HEADER.sub(
            _redact_authorization, redacted.decode("utf-8")
        ).encode("utf-8")
    except UnicodeDecodeError:
        return redacted
