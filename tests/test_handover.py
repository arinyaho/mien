"""`mien exec` refuses to hand credentials to an agent standing somewhere else.

Two layers are exercised here: the pure decision (`mien.handover.refusal_reason`)
and the command that consults it. The pure layer is where the fail-open promises
are pinned, because a CliRunner cannot easily produce "the config object itself
misbehaves"; the command layer pins that the decision is actually wired in front
of the credential, and with the *display* resolver rather than the acting one.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from mien.cli import main
from mien.config import (BackendConfig, Config, Profile, SecretNaming,
                         save_config)
from mien.handover import refusal_reason

ACME_REMOTE = "https://github.com/acme-core/api.git"


@pytest.fixture
def runner():
    return CliRunner()


def _write_config(tmp_path, monkeypatch, profiles: dict[str, Profile]) -> None:
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "config.json"))
    save_config(Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles=profiles,
    ))


def _owns_remotes(**owns: list[str]) -> dict[str, Profile]:
    """Profiles that claim their work only through the remotes they own.

    This is the shape of a real config — `default_for` is frequently empty — and
    the shape that tells the two resolvers apart.
    """
    return {name: Profile(name=name, owns_remotes=pats) for name, pats in owns.items()}


def _dir_scopes(**scopes: list[str]) -> dict[str, Profile]:
    return {name: Profile(name=name, default_for=globs) for name, globs in scopes.items()}


def _exec(runner, monkeypatch, mocker, profile, *, cwd="/flat/api", remote=None,
          agent=True, env=None):
    """Invoke `mien exec <profile> -- true` from a faked place.

    Returns (result, subprocess.call mock) so a test can assert both the outcome
    and whether a child was ever spawned.
    """
    monkeypatch.delenv("MIEN_EXEC", raising=False)
    monkeypatch.setattr("mien.cli._logical_cwd", lambda: cwd)
    monkeypatch.setattr("mien.cli.git_origin_remote", lambda _cwd: remote)
    mocker.patch("mien.cli.load_backend")
    called = mocker.patch("mien.cli.subprocess.call", return_value=0)
    invoke_env = dict(env or {})
    if agent:
        invoke_env.setdefault("CLAUDECODE", "1")
    result = runner.invoke(main, ["exec", profile, "--", "true"], env=invoke_env)
    return result, called


# --- the decision itself -----------------------------------------------------


class TestRefusalReason:
    def test_refuses_an_agent_driven_mismatch(self):
        reason = refusal_reason(
            _owns_remotes(work=["github.com/acme-*/*"]), "/flat/api", "personal",
            remote=ACME_REMOTE, agent_driven=True,
        )
        assert reason is not None
        assert "personal" in reason and "work" in reason
        assert "mien exec work --" in reason

    def test_allows_when_the_named_profile_is_the_one_claimed(self):
        assert refusal_reason(
            _owns_remotes(work=["github.com/acme-*/*"]), "/flat/api", "work",
            remote=ACME_REMOTE, agent_driven=True,
        ) is None

    def test_allows_a_human(self):
        assert refusal_reason(
            _owns_remotes(work=["github.com/acme-*/*"]), "/flat/api", "personal",
            remote=ACME_REMOTE, agent_driven=False,
        ) is None

    def test_allows_when_nothing_claims_the_place(self):
        assert refusal_reason(
            _owns_remotes(work=["github.com/acme-*/*"]), "/flat/api", "personal",
            remote=None, agent_driven=True,
        ) is None

    def test_allows_an_ambiguous_claim(self):
        """Two profiles claim it equally: `claimed_profile` raises rather than
        guess, and a guess is exactly what must not become a refusal."""
        assert refusal_reason(
            _dir_scopes(alpha=["/flat/api"], bravo=["/flat/api"]),
            "/flat/api", "personal", agent_driven=True,
        ) is None

    def test_allows_when_the_config_itself_misbehaves(self):
        """The never-wedge promise, at its widest: any exception allows.

        A config that cannot even be iterated stands in for every unreadable or
        unexpected shape. The handover must survive a bug in its own gate.
        """
        class Broken(dict):
            def __iter__(self):
                raise RuntimeError("unreadable config")

            def keys(self):
                raise RuntimeError("unreadable config")

        assert refusal_reason(
            Broken(), "/flat/api", "personal", remote=ACME_REMOTE, agent_driven=True,
        ) is None

    def test_names_the_source_of_the_claim(self):
        """A repo claim and a directory claim are corrected in different places,
        so the message must say which one spoke."""
        by_repo = refusal_reason(
            _owns_remotes(work=["github.com/acme-*/*"]), "/flat/api", "personal",
            remote=ACME_REMOTE, agent_driven=True,
        )
        by_dir = refusal_reason(
            _dir_scopes(work=["/flat/*"]), "/flat/api", "personal",
            agent_driven=True,
        )
        assert "origin" in by_repo and "default_for" not in by_repo
        assert "default_for" in by_dir and "origin" not in by_dir


# --- the command -------------------------------------------------------------


def test_exec_refuses_a_profile_the_repository_disowns(
    runner, tmp_path, monkeypatch, mocker
):
    """The case the feature exists for: an agent names the wrong identity in a
    repository that plainly belongs to another, and the bundle is handed over
    anyway. The refusal must land before the backend is touched."""
    _write_config(tmp_path, monkeypatch,
                  _owns_remotes(work=["github.com/acme-*/*"],
                                personal=["github.com/me/*"]))
    result, called = _exec(runner, monkeypatch, mocker, "personal", remote=ACME_REMOTE)

    assert result.exit_code != 0
    assert "refusing to hand over credentials" in result.output
    assert "'personal'" in result.output and "'work'" in result.output
    assert "mien exec work -- <your command>" in result.output
    assert "did not fail" in result.output  # it is a refusal, not a failure
    called.assert_not_called()


def test_exec_refusal_rests_on_owns_remotes_not_only_directory_scopes(
    runner, tmp_path, monkeypatch, mocker
):
    """The check must use the *display* resolver, which reads `owns_remotes`.

    Wired to the acting resolver (`resolve_profile`) instead, this whole feature
    would be a no-op for any profile with an empty `default_for` — which is most
    of them. Neither profile here has a directory scope at all, so this test
    fails outright if the wrong resolver is used, while a `default_for`-based
    test would pass either way.
    """
    _write_config(tmp_path, monkeypatch,
                  _owns_remotes(work=["github.com/acme-*/*"],
                                personal=["github.com/me/*"]))
    result, called = _exec(runner, monkeypatch, mocker, "personal", remote=ACME_REMOTE)
    assert result.exit_code != 0
    assert "origin" in result.output  # the claim came from the repository
    called.assert_not_called()


def test_exec_refuses_a_directory_scope_mismatch(runner, tmp_path, monkeypatch, mocker):
    _write_config(tmp_path, monkeypatch, _dir_scopes(work=["/flat/*"], personal=[]))
    result, called = _exec(runner, monkeypatch, mocker, "personal")
    assert result.exit_code != 0
    assert "default_for" in result.output
    called.assert_not_called()


def test_exec_allows_the_profile_this_place_claims(runner, tmp_path, monkeypatch, mocker):
    _write_config(tmp_path, monkeypatch,
                  _owns_remotes(work=["github.com/acme-*/*"],
                                personal=["github.com/me/*"]))
    result, called = _exec(runner, monkeypatch, mocker, "work", remote=ACME_REMOTE)
    assert result.exit_code == 0, result.output
    assert called.call_args.args[0] == ["true"]


def test_exec_allows_where_nothing_claims_the_place(runner, tmp_path, monkeypatch, mocker):
    """Fail open: an unclaimed directory is not evidence of a mistake."""
    _write_config(tmp_path, monkeypatch, _owns_remotes(work=["github.com/acme-*/*"]))
    result, called = _exec(runner, monkeypatch, mocker, "work",
                           cwd="/somewhere/else", remote=None)
    assert result.exit_code == 0, result.output
    called.assert_called_once()


def test_exec_allows_an_ambiguously_claimed_place(runner, tmp_path, monkeypatch, mocker):
    _write_config(tmp_path, monkeypatch,
                  _dir_scopes(alpha=["/flat/api"], bravo=["/flat/api"],
                              personal=[]))
    result, called = _exec(runner, monkeypatch, mocker, "personal")
    assert result.exit_code == 0, result.output
    called.assert_called_once()


def test_a_human_is_never_blocked(runner, tmp_path, monkeypatch, mocker):
    """No agent harness, no check. A person can see where they are standing, and
    is the one who would need an escape hatch — so they never meet the gate."""
    _write_config(tmp_path, monkeypatch,
                  _owns_remotes(work=["github.com/acme-*/*"],
                                personal=["github.com/me/*"]))
    result, called = _exec(runner, monkeypatch, mocker, "personal",
                           remote=ACME_REMOTE, agent=False)
    assert result.exit_code == 0, result.output
    called.assert_called_once()


@pytest.mark.parametrize("value", ["off", "0", "false", "no"])
def test_the_kill_switch_disarms_the_refusal(
    runner, tmp_path, monkeypatch, mocker, value
):
    """One escape, for a person debugging a false refusal — same spellings
    `MIEN_GUARD` accepts."""
    _write_config(tmp_path, monkeypatch,
                  _owns_remotes(work=["github.com/acme-*/*"],
                                personal=["github.com/me/*"]))
    result, called = _exec(runner, monkeypatch, mocker, "personal",
                           remote=ACME_REMOTE, env={"MIEN_EXEC": value})
    assert result.exit_code == 0, result.output
    called.assert_called_once()


def test_the_refusal_never_names_the_kill_switch(runner, tmp_path, monkeypatch, mocker):
    """The agent reading this error must not be handed the bypass.

    Documented in the README for the human who needs it; absent here on purpose.
    An override an agent can see is an override an agent will take, and there is
    direct evidence in this project that documentation alone does not hold it to
    the safe path — which is why refusal, not advice, is the control.
    """
    _write_config(tmp_path, monkeypatch,
                  _owns_remotes(work=["github.com/acme-*/*"],
                                personal=["github.com/me/*"]))
    result, _ = _exec(runner, monkeypatch, mocker, "personal", remote=ACME_REMOTE)
    assert result.exit_code != 0
    assert "MIEN_EXEC" not in result.output
    assert "--force" not in result.output


def test_a_bug_in_the_check_never_wedges_the_handover(
    runner, tmp_path, monkeypatch, mocker
):
    """Fail open through the CLI layer too, not only inside the pure function."""
    _write_config(tmp_path, monkeypatch,
                  _owns_remotes(work=["github.com/acme-*/*"],
                                personal=["github.com/me/*"]))

    def boom(_cwd):
        raise RuntimeError("git blew up")

    monkeypatch.setattr("mien.cli.git_origin_remote", boom)
    monkeypatch.delenv("MIEN_EXEC", raising=False)
    monkeypatch.setattr("mien.cli._logical_cwd", lambda: "/flat/api")
    mocker.patch("mien.cli.load_backend")
    called = mocker.patch("mien.cli.subprocess.call", return_value=0)
    result = runner.invoke(main, ["exec", "personal", "--", "true"],
                           env={"CLAUDECODE": "1"})
    assert result.exit_code == 0, result.output
    called.assert_called_once()


def test_an_unreadable_config_fails_as_a_config_error_not_a_refusal(
    runner, tmp_path, monkeypatch, mocker
):
    """A broken config is reported as such; the new gate adds nothing to it and
    certainly does not turn it into a handover refusal."""
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{ not json at all")
    monkeypatch.setenv("MIEN_CONFIG", str(cfg_path))
    monkeypatch.delenv("MIEN_EXEC", raising=False)
    called = mocker.patch("mien.cli.subprocess.call", return_value=0)
    result = runner.invoke(main, ["exec", "personal", "--", "true"],
                           env={"CLAUDECODE": "1"})
    assert result.exit_code != 0
    assert "refusing to hand over credentials" not in result.output
    called.assert_not_called()


# --- the invariant this feature rests on -------------------------------------


def test_owns_remotes_still_never_selects_an_identity(runner, tmp_path, monkeypatch):
    """The asymmetry, pinned: the repo signal may block, but must never grant.

    `owns_remotes` now reaches an acting command — but only to refuse. If it
    ever also *resolved* for `which`/`run`, a cloned repository could choose the
    identity that acts by editing its own `origin`, which is the exact thing the
    two-resolver split exists to prevent (SECURITY.md, "Choosing an identity
    that acts never trusts the repository").
    """
    place = tmp_path / "api"
    place.mkdir()
    _write_config(tmp_path, monkeypatch, _owns_remotes(work=["github.com/acme-*/*"]))
    monkeypatch.delenv("MIEN_PROFILE", raising=False)
    monkeypatch.setattr("mien.cli.git_origin_remote", lambda _cwd: ACME_REMOTE)
    monkeypatch.chdir(place)

    which = runner.invoke(main, ["which"])
    assert which.exit_code != 0
    assert "no profile claims" in which.output
    assert "work" not in which.stdout

    run = runner.invoke(main, ["run", "--", "true"])
    assert run.exit_code != 0
    assert "no profile claims" in run.output
