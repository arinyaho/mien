from __future__ import annotations

from typing import NamedTuple

from mien.config import BackendConfig, ConfigError, config_path

from .base import BackendError, BackendUnauthorized, SecretNotFound, SecretsBackend

__all__ = [
    "BACKEND_OPTIONS",
    "BackendError",
    "BackendOptionSpec",
    "BackendUnauthorized",
    "SecretNotFound",
    "SecretsBackend",
    "UnknownBackendType",
    "ensure_known_backend",
    "ensure_known_backend_options",
    "load_backend",
]


class BackendOptionSpec(NamedTuple):
    """The option keys one backend reads out of `secrets_backend`.

    `required` is what `load_backend` indexes directly (a missing one is a
    `KeyError` at first use); `optional` is what it reads with a default.
    """

    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()


# The option contract of every backend, kept here rather than in config.py so
# a backend's keys are declared next to the loader that reads them. config.py
# validates a parsed config against this (see `ensure_known_backend_options`).
BACKEND_OPTIONS: dict[str, BackendOptionSpec] = {
    "gcp_secret_manager": BackendOptionSpec(required=("project",)),
    "macos_keychain": BackendOptionSpec(optional=("service_prefix",)),
    "keyring": BackendOptionSpec(optional=("service_prefix",)),
}

SUPPORTED_BACKENDS = tuple(BACKEND_OPTIONS)

# Backend types an older mien could write into a config but that no longer
# exist here. Named explicitly so a config carrying one gets the migration
# story rather than the generic "did you typo it?" answer.
RETIRED_BACKENDS = ("oci_vault",)


class UnknownBackendType(BackendError):
    """The config names a backend type this mien cannot load."""


def ensure_known_backend(cfg: BackendConfig) -> None:
    """Reject a backend type this mien cannot talk to, with the recovery path.

    Called both by `load_backend` and by the commands that branch on the
    backend type *without* loading it (`push`, `sync`) — otherwise a retired
    cloud backend reads as "not a cloud backend", i.e. local, and `push`
    reports a successful no-op while doing nothing.
    """
    if cfg.type in SUPPORTED_BACKENDS:
        return
    supported = ", ".join(SUPPORTED_BACKENDS)
    if cfg.type in RETIRED_BACKENDS:
        raise UnknownBackendType(
            f"secrets backend {cfg.type!r} has been removed from mien.\n\n"
            f"Secrets stored in it are no longer reachable: this mien cannot talk\n"
            f"to that backend, and nothing migrates them for you. `mien init` does\n"
            f"not convert an existing config — re-running it writes a fresh one and\n"
            f"drops the profiles you have.\n\n"
            f"To move forward:\n"
            f"  - Re-init on a supported backend ({supported}):\n"
            f"      mien init\n"
            f"    then `mien login` again for each profile and service.\n"
            f"  - Or, to keep what is stored there, install a mien old enough to\n"
            f"    still have the {cfg.type!r} backend and export the secrets first.\n\n"
            f"Config: {config_path()}"
        )
    raise UnknownBackendType(
        f"unknown secrets backend {cfg.type!r}.\n\n"
        f"Supported backends: {supported}.\n"
        f"Fix `secrets_backend.type` in {config_path()}, or run `mien init` to "
        f"write a fresh config."
    )


def ensure_known_backend_options(cfg: BackendConfig) -> None:
    """Reject a `secrets_backend` option key this backend does not read.

    `type` already fails loudly when it is missing or unknown; without this the
    keys beside it were swept into `options` unchecked, so `"projct": "x"` parsed
    clean and surfaced later as a bare `KeyError: 'project'` out of
    `load_backend` — from `mien doctor`, the command mien's own markers tell you
    to run. A typo in the backend's options is a config error like any other, so
    it is reported at parse time, by key name, as a `ConfigError`.

    An unknown `type` is not this function's business: it is left to
    `ensure_known_backend`, which has the migration story.
    """
    spec = BACKEND_OPTIONS.get(cfg.type)
    if spec is None:
        return
    valid = spec.required + spec.optional
    for key in cfg.options:
        if key not in valid:
            listed = ", ".join(valid) if valid else "(none)"
            raise ConfigError(
                f"secrets_backend: unknown option {key!r} for backend "
                f"{cfg.type!r}. Valid options: {listed}."
            )
    for key in spec.required:
        if key not in cfg.options:
            raise ConfigError(
                f"secrets_backend: backend {cfg.type!r} requires option {key!r}, "
                f"which is missing — mien cannot reach your secrets without it. "
                f"Add it, or run `mien init` to write a fresh config."
            )


def load_backend(cfg: BackendConfig) -> SecretsBackend:
    if cfg.type == "macos_keychain":
        # Imported lazily: keychain.py binds keyring.backends.macOS at module
        # level, which is macOS-only. A Linux user on the keyring backend must be
        # able to load_backend without dragging that in.
        from .keychain import MacOSKeychainBackend
        return MacOSKeychainBackend(service_prefix=cfg.options.get("service_prefix", "mien-"))
    if cfg.type == "gcp_secret_manager":
        from .gcp import GCPSecretManagerBackend
        return GCPSecretManagerBackend(project=cfg.options["project"])
    if cfg.type == "keyring":
        from .keyring_store import KeyringBackend
        return KeyringBackend(service_prefix=cfg.options.get("service_prefix", "mien-"))
    ensure_known_backend(cfg)
    raise AssertionError(f"backend {cfg.type!r} is supported but has no loader")
