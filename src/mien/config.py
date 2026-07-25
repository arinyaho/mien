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
            raise ValueError(f"invalid config JSON: {exc}") from exc
    else:
        data = raw
    version = data.get("$schema_version", data.get("schema_version"))
    if version != SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema_version {version!r}; expected {SCHEMA_VERSION}")
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
        raise ValueError(
            f"profile {profile_name!r}: {field_name} must be a list of {kind} glob "
            f"strings (e.g. [{example!r}]), got {type(value).__name__}: {value!r}"
        )
    for item in value:
        if not isinstance(item, str):
            raise ValueError(
                f"profile {profile_name!r}: {field_name} entries must be {kind} glob "
                f"strings, got {type(item).__name__}: {item!r}"
            )
    return list(value)


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


def _config_from_dict(raw: dict) -> Config:
    sb_raw = dict(raw.get("secrets_backend", {}))
    sb_type = sb_raw.pop("type")
    secrets_backend = BackendConfig(type=sb_type, options=sb_raw)

    sn = raw.get("secret_naming") or {}
    secret_naming = SecretNaming(
        default=sn.get("default", "mien-{profile}-{service}-{kind}"),
        slack_token=sn.get("slack_token", "mien-{profile}-slack-{workspace}-token"),
    )

    profiles: dict[str, Profile] = {}
    for name, p in (raw.get("profiles") or {}).items():
        google = _service_from_dict(GoogleService, p["google"]) if p.get("google") else None
        github = _service_from_dict(GitHubService, p["github"]) if p.get("github") else None
        slack = [_service_from_dict(SlackWorkspace, w) for w in (p.get("slack") or [])]
        aws = _service_from_dict(AWSService, p["aws"]) if p.get("aws") else None
        oci = _service_from_dict(OCIService, p["oci"]) if p.get("oci") else None
        atlassian = _service_from_dict(AtlassianService, p["atlassian"]) if p.get("atlassian") else None
        notion = _service_from_dict(NotionService, p["notion"]) if p.get("notion") else None
        project_env = [
            ProjectEnvScope(match=s["match"], env=dict(s.get("env") or {}))
            for s in (p.get("project_env") or [])
        ]
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
        bootstrap=raw.get("bootstrap") or {},
        secret_naming=secret_naming,
        profiles=profiles,
    )
