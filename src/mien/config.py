from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from dataclasses import fields as dc_fields
from pathlib import Path

SCHEMA_VERSION = 1


@dataclass
class BackendConfig:
    type: str
    options: dict = field(default_factory=dict)


@dataclass
class SecretNaming:
    default: str
    slack_token: str


@dataclass
class GoogleService:
    email: str
    oauth_client_id: str
    oauth_client_secret_ref: str | None
    refresh_token_ref: str
    adc_ref: str | None
    gcloud_config_name: str
    default_project: str | None


@dataclass
class GitHubService:
    username: str
    host: str
    token_ref: str | None = None
    ssh_key_path: str | None = None
    ssh_key_ref: str | None = None


@dataclass
class SlackWorkspace:
    workspace: str
    user_token_ref: str


@dataclass
class AWSService:
    region: str | None = None
    profile: str | None = None
    access_key_id_ref: str | None = None
    secret_access_key_ref: str | None = None


@dataclass
class OCIService:
    profile: str | None = None
    config_file: str | None = None


@dataclass
class AtlassianService:
    email: str
    base_url: str
    api_token_ref: str


@dataclass
class NotionService:
    api_token_ref: str


@dataclass
class ProjectEnvScope:
    match: str
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class Profile:
    name: str
    google: GoogleService | None = None
    github: GitHubService | None = None
    slack: list[SlackWorkspace] = field(default_factory=list)
    aws: AWSService | None = None
    oci: OCIService | None = None
    atlassian: AtlassianService | None = None
    notion: NotionService | None = None
    project_env: list[ProjectEnvScope] = field(default_factory=list)
    # Directory globs this profile claims as its default identity. Kept separate
    # from project_env: that maps directories to environment values, this maps
    # directories to *who you are*, and the two are set independently.
    default_for: list[str] = field(default_factory=list)
    # Git remote globs this profile owns, matched against a repo's `origin` in a
    # canonical `host/path` form (scheme, `user@`, and a trailing `.git` stripped;
    # an ssh `:` normalized to `/`) — e.g. ["github.com/me/*",
    # "github.com/me-labs/*"]. This claims identity by *what the repo is* rather
    # than where it sits, so it fits repositories kept side by side with no
    # per-employer directory convention.
    owns_remotes: list[str] = field(default_factory=list)
    # The git author address a commit under this identity carries. Setting git's
    # own `user.email` is git's job (native `includeIf`); mien reads git_email
    # only for the author cross-check, so guard/statusline can warn when a
    # commit's `user.email` disagrees with the identity acting here. Set it when
    # you commit under an address none of the profile's accounts carry.
    git_email: str | None = None


@dataclass
class Config:
    schema_version: int
    secrets_backend: BackendConfig
    bootstrap: dict
    secret_naming: SecretNaming
    profiles: dict[str, Profile]


def config_path() -> Path:
    override = os.environ.get("MIEN_CONFIG")
    if override:
        return Path(override)
    home = Path(os.environ.get("HOME", str(Path.home())))
    return home / ".config" / "mien" / "config.json"


def serialize_config(cfg: Config) -> str:
    return json.dumps(_config_to_dict(cfg), indent=2, sort_keys=False)


def deserialize_config(raw: str | dict) -> Config:
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"invalid config JSON: {exc}") from exc
    else:
        data = raw
    data = _mapping_from_raw("config", data)
    version = data.get("$schema_version", data.get("schema_version"))
    if version != SCHEMA_VERSION:
        raise ConfigError(
            f"Unsupported schema_version {version!r}; expected {SCHEMA_VERSION}")
    return _config_from_dict(data)


def load_config() -> Config | None:
    path = config_path()
    if not path.exists():
        return None
    return deserialize_config(path.read_text())


def save_config(cfg: Config) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_config(cfg))
    path.chmod(0o600)


def _config_to_dict(cfg: Config) -> dict:
    profiles = {}
    for name, prof in cfg.profiles.items():
        profiles[name] = {
            "google": asdict(prof.google) if prof.google else None,
            "github": asdict(prof.github) if prof.github else None,
            "slack": [asdict(w) for w in prof.slack],
            "aws": asdict(prof.aws) if prof.aws else None,
            "oci": asdict(prof.oci) if prof.oci else None,
            "atlassian": asdict(prof.atlassian) if prof.atlassian else None,
            "notion": asdict(prof.notion) if prof.notion else None,
            "project_env": [asdict(s) for s in prof.project_env],
            "default_for": list(prof.default_for),
            "owns_remotes": list(prof.owns_remotes),
            "git_email": prof.git_email,
        }
    return {
        "$schema_version": cfg.schema_version,
        "secrets_backend": {"type": cfg.secrets_backend.type, **cfg.secrets_backend.options},
        "bootstrap": cfg.bootstrap,
        "secret_naming": asdict(cfg.secret_naming),
        "profiles": profiles,
    }


def _glob_list_from_raw(
    profile_name: str, field_name: str, kind: str, value: object, example: str
) -> list[str]:
    """Validate a profile's list-of-globs field instead of coercing it.

    A bare string would otherwise be exploded into one glob per character by
    ``list()``, and the resulting ``"*"`` element claims everything -- silently
    routing credentials to the wrong profile. Shared by ``default_for``
    (``kind="directory"``) and ``owns_remotes`` (``kind="remote"``).
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(
            f"profile {profile_name!r}: {field_name} must be a list of {kind} glob "
            f"strings (e.g. [{example!r}]), got {type(value).__name__}: {value!r}"
        )
    for item in value:
        if not isinstance(item, str):
            raise ConfigError(
                f"profile {profile_name!r}: {field_name} entries must be {kind} glob "
                f"strings, got {type(item).__name__}: {item!r}"
            )
    return list(value)


def _mapping_from_raw(where: str, value: object) -> dict:
    """Validate that a config block is a JSON object instead of assuming it is.

    Every block below is read with ``.items()``, ``in``, or ``dict()``, so a
    wrong-typed value would escape as ``TypeError``/``AttributeError`` rather
    than ``ConfigError`` -- and the fail-open surfaces (guard, status line) only
    recognize ``ConfigError`` as "I have stopped working", so anything else exits
    in silence. Same shape-check-don't-coerce rule as ``_glob_list_from_raw``.
    """
    if not isinstance(value, dict):
        raise ConfigError(
            f"{where} must be a JSON object, got {type(value).__name__}: {value!r}"
        )
    return value


def _object_list_from_raw(where: str, value: object) -> list[dict]:
    """Validate a config block that is a list of JSON objects. See above."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(
            f"{where} must be a list of JSON objects, got "
            f"{type(value).__name__}: {value!r}"
        )
    return [_mapping_from_raw(f"{where}[{i}]", item) for i, item in enumerate(value)]


class ConfigError(ValueError):
    """The config file cannot be understood.

    Distinct from a plain ValueError so the CLI can report it as an actionable
    error instead of a traceback, and so the fail-open surfaces (status line,
    guard) can say that they have stopped working rather than going quiet.
    """


# Keys a service block may still carry from an older mien, and the value each
# one had to hold for its removal to be a no-op. Deliberately an explicit map
# rather than "drop anything unrecognized": an unknown key is far more likely a
# typo (`profil`, `ssh_keypath`) than a retired field, and silently dropping it
# would leave the service unconfigured — no `AWS_PROFILE`/`OCI_CLI_PROFILE`
# exported, the tool falling back to its own default account, and the command
# succeeding as somebody else. A misconfigured identity has to fail loudly.
# Profile-level keys an older config may still carry, with the value that made
# each a no-op. Same reasoning as the service-level map below.
_RETIRED_PROFILE_KEYS: dict[str, object] = {"git_name": None}


def _check_profile_keys(name: str, p: dict) -> None:
    """Reject a profile key mien does not recognize.

    A typo here is the quietest way to act as the wrong person: `defualt_for`
    simply drops the directory claim, and the directory then falls to some other
    profile's catch-all glob. Nothing warns, and the wrong identity acts.
    """
    known = {f.name for f in dc_fields(Profile)} - {"name"}
    for k in p:
        if k in known or k in _RETIRED_PROFILE_KEYS:
            continue
        raise ConfigError(
            f"profile {name!r}: unknown key {k!r}. Valid keys are: "
            f"{', '.join(sorted(known))}."
        )


_RETIRED_SERVICE_KEYS: dict[type, dict[str, object]] = {
    GoogleService: {"gcloud_login_required": False},
    SlackWorkspace: {"team_id": None},
}


def _service_from_dict(cls, data: dict):
    """Build a service dataclass, tolerating only known-retired keys.

    A retired key is dropped when it holds the value that made it a no-op. Any
    other value meant something once, so it is reported rather than ignored —
    silently discarding it would change behaviour without saying so.
    """
    retired = _RETIRED_SERVICE_KEYS.get(cls, {})
    cleaned = {}
    for k, v in data.items():
        if k in retired:
            if v != retired[k]:
                raise ConfigError(
                    f"{cls.__name__}: {k!r}={v!r} is no longer supported "
                    f"(only {retired[k]!r} was ever written). Remove it from your "
                    "config, or check whether you meant a different setting."
                )
            continue
        cleaned[k] = v
    try:
        return cls(**cleaned)
    except TypeError as exc:
        # Almost always a typo. Name it and list what is valid, rather than
        # letting a bare TypeError traceback out — this is the likelier way a
        # hand-edited config goes wrong, so it deserves the clearer message.
        known = ", ".join(f.name for f in dc_fields(cls))
        raise ConfigError(
            f"{cls.__name__}: {exc}. Valid keys are: {known}."
        ) from exc


def _service_from_raw(cls, profile_name: str, key: str, value: object):
    """Build an optional service block, checking its shape first."""
    if not value:
        return None
    return _service_from_dict(
        cls, _mapping_from_raw(f"profile {profile_name!r}: {key}", value))


def _config_from_dict(raw: dict) -> Config:
    sb_raw = dict(_mapping_from_raw("secrets_backend", raw.get("secrets_backend") or {}))
    if "type" not in sb_raw:
        raise ConfigError(
            "secrets_backend.type is missing — mien cannot tell where your "
            "secrets live. Expected one of: gcp_secret_manager, macos_keychain, "
            "keyring.")
    sb_type = sb_raw.pop("type")
    secrets_backend = BackendConfig(type=sb_type, options=sb_raw)

    sn = _mapping_from_raw("secret_naming", raw.get("secret_naming") or {})
    secret_naming = SecretNaming(
        default=sn.get("default", "mien-{profile}-{service}-{kind}"),
        slack_token=sn.get("slack_token", "mien-{profile}-slack-{workspace}-token"),
    )

    profiles: dict[str, Profile] = {}
    for name, p in _mapping_from_raw("profiles", raw.get("profiles") or {}).items():
        p = _mapping_from_raw(f"profile {name!r}", p)
        _check_profile_keys(name, p)
        google = _service_from_raw(GoogleService, name, "google", p.get("google"))
        github = _service_from_raw(GitHubService, name, "github", p.get("github"))
        slack = [
            _service_from_dict(SlackWorkspace, w)
            for w in _object_list_from_raw(f"profile {name!r}: slack", p.get("slack"))
        ]
        aws = _service_from_raw(AWSService, name, "aws", p.get("aws"))
        oci = _service_from_raw(OCIService, name, "oci", p.get("oci"))
        atlassian = _service_from_raw(AtlassianService, name, "atlassian", p.get("atlassian"))
        notion = _service_from_raw(NotionService, name, "notion", p.get("notion"))
        project_env = []
        for s_ in _object_list_from_raw(f"profile {name!r}: project_env", p.get("project_env")):
            if "match" not in s_:
                raise ConfigError(
                    f"profile {name!r}: a project_env entry has no 'match' glob: {s_!r}")
            project_env.append(ProjectEnvScope(
                match=s_["match"],
                env=dict(_mapping_from_raw(
                    f"profile {name!r}: project_env {s_['match']!r} env",
                    s_.get("env") or {})),
            ))
        profiles[name] = Profile(
            name=name,
            google=google,
            github=github,
            slack=slack,
            aws=aws,
            oci=oci,
            atlassian=atlassian,
            notion=notion,
            project_env=project_env,
            default_for=_glob_list_from_raw(
                name, "default_for", "directory", p.get("default_for"), "*/Projects/acme"),
            owns_remotes=_glob_list_from_raw(
                name, "owns_remotes", "remote", p.get("owns_remotes"), "github.com/acme/*"),
            git_email=p.get("git_email"),
        )

    return Config(
        schema_version=SCHEMA_VERSION,
        secrets_backend=secrets_backend,
        bootstrap=_mapping_from_raw("bootstrap", raw.get("bootstrap") or {}),
        secret_naming=secret_naming,
        profiles=profiles,
    )
