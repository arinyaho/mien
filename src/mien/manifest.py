from __future__ import annotations

from mien.backends.base import SecretsBackend
from mien.config import BackendConfig, Config, ConfigError, deserialize_config, serialize_config

MANIFEST_SECRET_NAME = "mien-config-manifest"
_CLOUD_BACKENDS = {"gcp_secret_manager"}


class ManifestError(ConfigError):
    """The backend's config manifest cannot be understood.

    The manifest is parsed by the same ``deserialize_config`` as the local
    config file, so both failures arrive as ``ConfigError`` and are otherwise
    indistinguishable -- yet they need opposite advice. A broken LOCAL config is
    why the status line shows a warning and ``mien guard`` stops enforcing, and
    it is fixed by editing the file. A broken REMOTE manifest (typically written
    by a differently-versioned mien) leaves local state entirely intact and is
    fixed by overwriting it with ``mien push``. Raised only where a manifest is
    parsed, so its origin is known rather than guessed at.
    """


def is_cloud_backend(backend_cfg: BackendConfig) -> bool:
    return backend_cfg.type in _CLOUD_BACKENDS


def push_manifest(cfg: Config, backend: SecretsBackend) -> None:
    backend.put(MANIFEST_SECRET_NAME, serialize_config(cfg).encode("utf-8"))


def _ref_secret_name(ref: str) -> str | None:
    if "/secrets/" in ref:
        return ref.split("/secrets/", 1)[1].rsplit("/versions/", 1)[0]
    if ref.startswith("ref://"):
        return ref.removeprefix("ref://").rsplit("/versions/", 1)[0]
    return None


def pull_manifest(backend: SecretsBackend) -> Config | None:
    refs = backend.list(prefix=MANIFEST_SECRET_NAME)
    if not refs:
        return None
    exact = [r for r in refs if _ref_secret_name(r) == MANIFEST_SECRET_NAME]
    chosen = exact or refs  # refs a backend doesn't derive from the name -> keep prefix list
    data = backend.get(chosen[0])
    try:
        return deserialize_config(data.decode("utf-8"))
    except ConfigError as exc:
        raise ManifestError(str(exc)) from exc
