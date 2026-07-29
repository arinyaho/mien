import json
from pathlib import Path

import pytest

from mien.config import (
    BackendConfig,
    ConfigError,
    Config,
    GitHubService,
    GoogleService,
    Profile,
    SecretNaming,
    SlackWorkspace,
    config_path,
    deserialize_config,
    load_config,
    save_config,
    serialize_config,
)


def test_config_path_uses_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "custom.json"))
    assert config_path() == tmp_path / "custom.json"


def test_config_path_default(monkeypatch, tmp_path):
    monkeypatch.delenv("MIEN_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config_path() == tmp_path / ".config" / "mien" / "config.json"


def test_load_config_missing_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "nope.json"))
    assert load_config() is None


def test_save_then_load_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "c.json"))
    cfg = Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={"service_prefix": "mien-"}),
        bootstrap={},
        secret_naming=SecretNaming(
            default="mien-{profile}-{service}-{kind}",
            slack_token="mien-{profile}-slack-{workspace}-token",
        ),
        profiles={
            "personal": Profile(
                name="personal",
                google=GoogleService(
                    email="me@example.com",
                    oauth_client_id="cid",
                    oauth_client_secret_ref=None,
                    refresh_token_ref="mien-personal-google-refresh",
                    adc_ref=None,
                    gcloud_config_name="personal",
                    default_project=None,
                ),
                github=GitHubService(username="me", host="github.com", token_ref="mien-personal-github-token"),
                slack=[SlackWorkspace(workspace="team-a", user_token_ref="mien-personal-slack-team-a-token")],
            )
        },
    )
    save_config(cfg)
    loaded = load_config()
    assert loaded == cfg


def test_owns_remotes_survives_a_roundtrip_and_rejects_a_bare_string(monkeypatch, tmp_path):
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "c.json"))
    cfg = Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="x", slack_token="y"),
        profiles={"personal": Profile(
            name="personal",
            owns_remotes=["github.com/me/*", "github.com/me-labs/*"],
        )},
    )
    save_config(cfg)
    assert load_config() == cfg
    assert load_config().profiles["personal"].owns_remotes == [
        "github.com/me/*", "github.com/me-labs/*"]

    # A bare string must be rejected, not exploded into one glob per character
    # (a "*" element would claim every remote).
    p = tmp_path / "c.json"
    p.write_text(json.dumps({
        "$schema_version": 1,
        "secrets_backend": {"type": "macos_keychain"},
        "profiles": {"x": {"owns_remotes": "github.com/x/*"}},
    }))
    with pytest.raises(ValueError, match="owns_remotes"):
        load_config()


def test_git_identity_fields_survive_a_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "c.json"))
    cfg = Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="x", slack_token="y"),
        profiles={"work": Profile(name="work", git_email="me@x.example")},
    )
    save_config(cfg)
    loaded = load_config()
    assert loaded == cfg
    assert loaded.profiles["work"].git_email == "me@x.example"
    # Absent by default.
    assert Profile(name="p").git_email is None


def test_retired_fields_in_an_older_config_are_ignored():
    raw = {
        "$schema_version": 1,
        "secrets_backend": {"type": "macos_keychain"},
        "bootstrap": {},
        "secret_naming": {},
        "profiles": {
            "work": {
                "google": {
                    "email": "me@x.example",
                    "oauth_client_id": "cid",
                    "oauth_client_secret_ref": None,
                    "refresh_token_ref": "r",
                    "adc_ref": None,
                    "gcloud_config_name": "work",
                    "default_project": None,
                    "gcloud_login_required": False,
                },
                "slack": [{"workspace": "team-a", "team_id": None, "user_token_ref": "r"}],
                "git_name": "Me",
            }
        },
    }
    prof = deserialize_config(raw).profiles["work"]
    assert prof.google.email == "me@x.example"
    assert prof.slack == [SlackWorkspace(workspace="team-a", user_token_ref="r")]


@pytest.mark.parametrize("service, block", [
    ("aws", {"profile_name": "work"}),          # meant `profile`
    ("oci", {"profil": "WORK"}),                # meant `profile`
    ("github", {"username": "octo", "host": "github.com",
                 "ssh_keypath": "/k"}),   # meant `ssh_key_path`
])
def test_a_misspelled_service_key_still_fails_loudly(service, block):
    """Tolerating retired keys must not become tolerating typos.

    A dropped `profile` key leaves the service unconfigured, so mien exports no
    `AWS_PROFILE`/`OCI_CLI_PROFILE` and the tool falls back to its own default
    account — the command then succeeds as somebody else. Wrong identity is the
    failure this project exists to prevent, so it has to be loud.
    """
    raw = {
        "$schema_version": 1,
        "secrets_backend": {"type": "macos_keychain"},
        "bootstrap": {}, "secret_naming": {},
        "profiles": {"work": {service: block}},
    }
    with pytest.raises(ConfigError, match="Valid keys are"):
        deserialize_config(raw)


def test_a_retired_key_holding_a_meaningful_value_is_reported():
    """`gcloud_login_required: true` once suppressed the ADC export.

    Dropping it silently would start exporting GOOGLE_APPLICATION_CREDENTIALS
    for a profile that had asked mien not to, changing behaviour without saying
    so. Only the no-op value (False) is tolerated.
    """
    raw = {
        "$schema_version": 1,
        "secrets_backend": {"type": "macos_keychain"},
        "bootstrap": {}, "secret_naming": {},
        "profiles": {"work": {"google": {
            "email": "me@x.example", "oauth_client_id": "cid",
            "oauth_client_secret_ref": "s", "refresh_token_ref": "r",
            "adc_ref": None, "gcloud_config_name": "work",
            "default_project": None, "gcloud_login_required": True,
        }}},
    }
    with pytest.raises(ValueError, match="no longer supported") as exc:
        deserialize_config(raw)
    msg = str(exc.value)
    # The remedy must not be "remove it, or you meant something else": both of
    # those *are* the silent behaviour change this raise exists to prevent. The
    # reader of `gcloud_login_required` is gone, so deleting the key starts the
    # ADC export for the one profile that asked for no ADC, and there is no other
    # setting to have meant. So the message has to name the consequence and the
    # way to keep the old behaviour.
    assert "GOOGLE_APPLICATION_CREDENTIALS" in msg
    assert "not a no-op" in msg
    assert "oauth_client_secret_ref' to null" in msg


def test_a_retired_slack_key_holding_a_value_names_what_removing_it_costs():
    """`team_id` was only ever written as null, so a value here is hand-typed.

    Unlike `gcloud_login_required` nothing ever read it, so the message may say
    "deleting it changes nothing" — but it still has to say that, rather than
    leaving the reader to guess whether a delete is safe.
    """
    raw = {
        "$schema_version": 1,
        "secrets_backend": {"type": "keyring"},
        "profiles": {"work": {"slack": [
            {"workspace": "team-a", "user_token_ref": "r", "team_id": "T0001"}]}},
    }
    with pytest.raises(ConfigError, match="no longer supported") as exc:
        deserialize_config(raw)
    assert "deleting the key changes nothing" in str(exc.value)


def test_save_creates_parent_dir_and_chmods_600(monkeypatch, tmp_path):
    target = tmp_path / "deep" / "nested" / "config.json"
    monkeypatch.setenv("MIEN_CONFIG", str(target))
    cfg = Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={},
        secret_naming=SecretNaming(default="x", slack_token="y"),
        profiles={},
    )
    save_config(cfg)
    assert target.exists()
    assert (target.stat().st_mode & 0o777) == 0o600


def test_load_rejects_unknown_schema_version(monkeypatch, tmp_path):
    p = tmp_path / "c.json"
    monkeypatch.setenv("MIEN_CONFIG", str(p))
    p.write_text(json.dumps({"$schema_version": 99, "secrets_backend": {"type": "macos_keychain"}, "profiles": {}}))
    with pytest.raises(ValueError, match="schema_version"):
        load_config()


def _cfg() -> Config:
    return Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="gcp_secret_manager", options={"project": "p1"}),
        bootstrap={"gcp_account": "me@x.com"},
        secret_naming=SecretNaming(
            default="mien-{profile}-{service}-{kind}",
            slack_token="mien-{profile}-slack-{workspace}-token",
        ),
        profiles={
            "work": Profile(
                name="work",
                github=GitHubService(username="u", host="github.com", token_ref="ref://gh"),
            )
        },
    )


def test_serialize_then_deserialize_roundtrips():
    cfg = _cfg()
    restored = deserialize_config(serialize_config(cfg))
    assert restored == cfg


def test_deserialize_accepts_dict_and_str():
    cfg = _cfg()
    as_str = serialize_config(cfg)
    from_str = deserialize_config(as_str)
    from_dict = deserialize_config(json.loads(as_str))
    assert from_str == from_dict


def test_deserialize_rejects_bad_schema_version():
    bad = json.dumps({"$schema_version": 99, "secrets_backend": {"type": "macos_keychain"},
                       "bootstrap": {}, "secret_naming": {}, "profiles": {}})
    with pytest.raises(ValueError, match="schema_version"):
        deserialize_config(bad)


def test_project_env_round_trips():
    from mien.config import ProjectEnvScope
    cfg = Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={},
        secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={"work": Profile(name="work", project_env=[
            ProjectEnvScope(match="*/work/arinyaho", env={"AWS_PROFILE": "work", "WORK_ROOT": "$HOME/work/arinyaho"}),
            ProjectEnvScope(match="*/arinyaho-ai*", env={"PYTHONPATH": "$HOME/x/src"}),
        ])},
    )
    back = deserialize_config(serialize_config(cfg))
    scopes = back.profiles["work"].project_env
    assert [s.match for s in scopes] == ["*/work/arinyaho", "*/arinyaho-ai*"]
    assert scopes[0].env["AWS_PROFILE"] == "work"


def test_config_without_project_env_defaults_empty():
    raw = {"$schema_version": 1, "secrets_backend": {"type": "macos_keychain"},
           "bootstrap": {}, "secret_naming": {"default": "d", "slack_token": "s"},
           "profiles": {"p": {"github": None}}}
    assert deserialize_config(raw).profiles["p"].project_env == []


def _raw_with_default_for(value) -> dict:
    return {"$schema_version": 1, "secrets_backend": {"type": "macos_keychain"},
            "bootstrap": {}, "secret_naming": {"default": "d", "slack_token": "s"},
            "profiles": {"work": {"default_for": value}}}


def test_default_for_scalar_string_is_rejected():
    # A bare string must not be char-split into globs: the resulting "*" would
    # claim every directory on the machine and misroute credentials.
    with pytest.raises(ValueError) as exc:
        deserialize_config(_raw_with_default_for("*/Projects/acme"))
    assert "profile 'work': default_for must be a list of directory glob strings" in str(exc.value)
    assert "got str" in str(exc.value)


def test_default_for_non_string_entry_is_rejected():
    with pytest.raises(ValueError) as exc:
        deserialize_config(_raw_with_default_for([123]))
    assert "profile 'work': default_for entries must be directory glob strings" in str(exc.value)
    assert "got int" in str(exc.value)


def test_default_for_list_of_strings_is_accepted():
    cfg = deserialize_config(_raw_with_default_for(["*/Projects/acme", "*/work/*"]))
    assert cfg.profiles["work"].default_for == ["*/Projects/acme", "*/work/*"]


def test_default_for_missing_defaults_empty():
    raw = _raw_with_default_for(None)
    raw["profiles"]["work"].pop("default_for")
    assert deserialize_config(raw).profiles["work"].default_for == []


@pytest.mark.parametrize("raw, expect", [
    ('{"$schema_version": 1, "secrets_backend": {"type": "keyring"},',  # trailing comma
     "invalid config JSON"),
    ('{"$schema_version": 2, "secrets_backend": {"type": "keyring"}}',
     "Unsupported schema_version"),
    ('{"$schema_version": 1, "secrets_backend": {"project": "p"}}',
     "secrets_backend.type is missing"),
    ('{"$schema_version": 1, "secrets_backend": {"type": "keyring"},'
     ' "profiles": {"w": {"default_for": "a-string"}}}',
     "must be a list"),
    ('{"$schema_version": 1, "secrets_backend": {"type": "keyring"},'
     ' "profiles": {"w": {"defualt_for": ["/x"]}}}',
     "unknown key"),
    # Wrong-typed blocks: every one of these is read as a dict/list further down.
    ('["not", "a", "config"]', "config must be a JSON object"),
    ('{"$schema_version": 1, "secrets_backend": "keyring"}',
     "secrets_backend must be a JSON object"),
    ('{"$schema_version": 1, "secrets_backend": {"type": "keyring"},'
     ' "bootstrap": "me@example.com"}',
     "bootstrap must be a JSON object"),
    ('{"$schema_version": 1, "secrets_backend": {"type": "keyring"},'
     ' "secret_naming": "mien-{profile}"}',
     "secret_naming must be a JSON object"),
    ('{"$schema_version": 1, "secrets_backend": {"type": "keyring"},'
     ' "profiles": ["work"]}',
     "profiles must be a JSON object"),
    ('{"$schema_version": 1, "secrets_backend": {"type": "keyring"},'
     ' "profiles": {"work": null}}',
     "profile 'work' must be a JSON object"),
    ('{"$schema_version": 1, "secrets_backend": {"type": "keyring"},'
     ' "profiles": {"work": {"github": "octocat"}}}',
     "profile 'work': github must be a JSON object"),
    ('{"$schema_version": 1, "secrets_backend": {"type": "keyring"},'
     ' "profiles": {"work": {"aws": ["eu-west-1"]}}}',
     "profile 'work': aws must be a JSON object"),
    ('{"$schema_version": 1, "secrets_backend": {"type": "keyring"},'
     ' "profiles": {"work": {"slack": "team-a"}}}',
     "profile 'work': slack must be a list"),
    ('{"$schema_version": 1, "secrets_backend": {"type": "keyring"},'
     ' "profiles": {"work": {"slack": ["team-a"]}}}',
     r"profile 'work': slack\[0\] must be a JSON object"),
    ('{"$schema_version": 1, "secrets_backend": {"type": "keyring"},'
     ' "profiles": {"work": {"project_env": {"match": "*"}}}}',
     "profile 'work': project_env must be a list"),
    ('{"$schema_version": 1, "secrets_backend": {"type": "keyring"},'
     ' "profiles": {"work": {"project_env": ["*/acme/*"]}}}',
     r"profile 'work': project_env\[0\] must be a JSON object"),
    ('{"$schema_version": 1, "secrets_backend": {"type": "keyring"},'
     ' "profiles": {"work": {"project_env": [{"match": "*", "env": "A=1"}]}}}',
     "profile 'work': project_env '\\*' env must be a JSON object"),
    # A mistyped backend option used to be swept into `options` unchecked and
    # escape much later as a bare `KeyError: 'project'` out of `load_backend` —
    # from `mien doctor`, the command mien's own markers tell you to run.
    ('{"$schema_version": 1,'
     ' "secrets_backend": {"type": "gcp_secret_manager", "projct": "x"}}',
     "unknown option 'projct'"),
    ('{"$schema_version": 1, "secrets_backend": {"type": "gcp_secret_manager"}}',
     "requires option 'project'"),
    ('{"$schema_version": 1,'
     ' "secrets_backend": {"type": "keyring", "servce_prefix": "mien-"}}',
     "unknown option 'servce_prefix'"),
    ('{"$schema_version": 1,'
     ' "secrets_backend": {"type": "macos_keychain", "project": "p"}}',
     "unknown option 'project'"),
    # `envs` builds a scope that matches and exports nothing: no AWS_PROFILE, the
    # tool falls back to its own default account, the command runs as somebody
    # else. Same class of failure as a mistyped profile key, same treatment.
    ('{"$schema_version": 1, "secrets_backend": {"type": "keyring"},'
     ' "profiles": {"work": {"project_env":'
     ' [{"match": "*/work", "envs": {"AWS_PROFILE": "work"}}]}}}',
     "unknown key 'envs'"),
])
def test_every_way_a_config_breaks_is_a_configerror(raw, expect):
    """One type for every parse failure, so the CLI can report them all.

    ConfigError is what `mien guard` keys off to announce that it has stopped
    enforcing. A parse failure that escapes as a bare ValueError/KeyError makes
    the guard exit 0 in silence — the mis-authored commit this tool prevents.
    """
    with pytest.raises(ConfigError, match=expect):
        deserialize_config(raw)


@pytest.mark.parametrize("backend", [
    {"type": "gcp_secret_manager", "project": "p1"},
    {"type": "macos_keychain"},
    {"type": "macos_keychain", "service_prefix": "acme-"},
    {"type": "keyring"},
    {"type": "keyring", "service_prefix": "acme-"},
])
def test_valid_backend_options_are_still_accepted(backend):
    """Option checking must not reject a config that works today."""
    raw = {"$schema_version": 1, "secrets_backend": backend, "profiles": {}}
    cfg = deserialize_config(raw)
    assert cfg.secrets_backend.type == backend["type"]
    assert cfg.secrets_backend.options == {
        k: v for k, v in backend.items() if k != "type"}


def test_an_unrecognized_backend_type_keeps_its_own_error():
    """Option checking must not steal the migration story from a retired type.

    `oci_vault` has secrets stranded in it; `ensure_known_backend` is what says
    so. Parsing has to get out of the way and let the caller reach that message.
    """
    raw = {"$schema_version": 1,
           "secrets_backend": {"type": "oci_vault", "vault_ocid": "ocid1..."},
           "profiles": {}}
    cfg = deserialize_config(raw)
    assert cfg.secrets_backend.options == {"vault_ocid": "ocid1..."}


def test_project_env_entry_with_only_known_keys_is_accepted():
    raw = {"$schema_version": 1, "secrets_backend": {"type": "keyring"},
           "profiles": {"work": {"project_env": [
               {"match": "*/work", "env": {"AWS_PROFILE": "work"}},
               {"match": "*/solo"},
           ]}}}
    scopes = deserialize_config(raw).profiles["work"].project_env
    assert [(s.match, s.env) for s in scopes] == [
        ("*/work", {"AWS_PROFILE": "work"}), ("*/solo", {})]


def test_a_retired_profile_key_still_loads():
    """`git_name` was removed; a config written before that must still open."""
    raw = {
        "$schema_version": 1,
        "secrets_backend": {"type": "keyring"},
        "profiles": {"w": {"git_name": "Me", "owns_remotes": ["github.com/me/*"]}},
    }
    prof = deserialize_config(raw).profiles["w"]
    assert prof.owns_remotes == ["github.com/me/*"]
