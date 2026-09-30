from unittest.mock import MagicMock

import click
import pytest

from mien.oauth import google_installed_app_flow, parse_redirect_input


def test_returns_refresh_token_from_creds(mocker):
    fake_creds = MagicMock()
    fake_creds.refresh_token = "refresh-abc"
    fake_flow = MagicMock()
    fake_flow.run_local_server.return_value = fake_creds

    mocker.patch(
        "mien.oauth.InstalledAppFlow.from_client_config",
        return_value=fake_flow,
    )
    mocker.patch("mien.oauth._browser_available", return_value=True)
    rt = google_installed_app_flow(
        client_id="cid",
        client_secret="csec",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    assert rt == "refresh-abc"
    fake_flow.run_local_server.assert_called_once()
    args, kwargs = fake_flow.run_local_server.call_args
    assert kwargs.get("port") == 0


def test_raises_when_no_refresh_token(mocker):
    fake_creds = MagicMock()
    fake_creds.refresh_token = None
    fake_flow = MagicMock()
    fake_flow.run_local_server.return_value = fake_creds
    mocker.patch("mien.oauth.InstalledAppFlow.from_client_config", return_value=fake_flow)
    mocker.patch("mien.oauth._browser_available", return_value=True)
    with pytest.raises(RuntimeError, match="refresh token"):
        google_installed_app_flow(client_id="c", client_secret="s", scopes=["x"])


CODE = "4/0AbCdEf-ghi_JKL"
FULL = "http://localhost/?state=st&code=4%2F0AbCdEf-ghi_JKL&scope=openid"


@pytest.mark.parametrize("text, expected", [
    (FULL, (CODE, "st")),
    (f"  '{FULL}'\n", (CODE, "st")),
    ('"' + FULL + '"', (CODE, "st")),
    ("http://localhost/?state=st&co\nde=4%2F0AbCdEf-ghi_JKL", (CODE, "st")),
    ("http://localhost:8085/?code=4%2F0AbCdEf-ghi_JKL&state=st\r\n", (CODE, "st")),
    ("code=4%2F0AbCdEf-ghi_JKL&state=st", (CODE, "st")),
    ("?code=4%2F0AbCdEf-ghi_JKL&state=st", (CODE, "st")),
    ("localhost/?state=st&code=4%2F0AbCdEf-ghi_JKL", (CODE, "st")),
    ("localhost:8085/?code=4%2F0AbCdEf-ghi_JKL&state=st", (CODE, "st")),
    ("scope=https://www.googleapis.com/auth/drive&code=4%2F0AbCdEf-ghi_JKL&state=st", (CODE, "st")),
])
def test_parse_redirect_input(text, expected):
    assert parse_redirect_input(text) == expected


@pytest.mark.parametrize("text, match", [
    ("", "empty"),
    ("   \n", "empty"),
    ("http://localhost/?error=access_denied&state=st", "access_denied"),
    ("http://localhost/?state=st", "code"),
    ("state=st", "code"),
    ("code=4%2F0AbCdEf-ghi_JKL", "state"),
    (CODE, "state"),
    (f' "{CODE}" \n', "state"),
    ("4%2F0AbCdEf-ghi_JKL", "state"),
])
def test_parse_redirect_input_errors(text, match):
    with pytest.raises(click.ClickException, match=match):
        parse_redirect_input(text)


def _mocks(mocker, pasted, *, available=False):
    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = ("https://auth.example/consent", "st")
    fake_flow.credentials.refresh_token = "refresh-manual"
    mocker.patch("mien.oauth.InstalledAppFlow.from_client_config", return_value=fake_flow)
    mocker.patch("mien.oauth._browser_available", return_value=available)
    mocker.patch("mien.oauth.click.prompt", return_value=pasted)
    return fake_flow


def _login(**kw):
    return google_installed_app_flow(client_id="c", client_secret="s", scopes=["x"], **kw)


def test_no_browser_pastes_url_and_rebuilds_https_response(mocker):
    flow = _mocks(mocker, FULL)
    assert _login() == "refresh-manual"
    flow.run_local_server.assert_not_called()
    flow.fetch_token.assert_called_once_with(
        authorization_response="https://localhost/?code=4%2F0AbCdEf-ghi_JKL&state=st"
    )


def test_code_only_paste_is_rejected_without_exchange(mocker):
    flow = _mocks(mocker, CODE)
    with pytest.raises(click.ClickException, match="state"):
        _login()
    flow.fetch_token.assert_not_called()


def test_no_browser_flag_forces_manual_even_with_browser(mocker):
    flow = _mocks(mocker, FULL, available=True)
    _login(no_browser=True)
    flow.run_local_server.assert_not_called()


def test_prompt_is_preceded_by_copy_hint(mocker, capsys):
    _mocks(mocker, FULL)
    seen = {}

    def prompt(*a, **k):
        seen["out"] = capsys.readouterr().out
        return FULL

    mocker.patch("mien.oauth.click.prompt", side_effect=prompt)
    _login()
    assert "Cmd+L" in seen["out"] and "Ctrl+L" in seen["out"]


def test_ssh_without_port_suggests_port(mocker, monkeypatch, capsys):
    _mocks(mocker, FULL)
    monkeypatch.setenv("SSH_CONNECTION", "1.2.3.4 5 6.7.8.9 22")
    _login()
    assert "--port" in capsys.readouterr().err


def test_explicit_no_browser_over_ssh_does_not_suggest_port(mocker, monkeypatch, capsys):
    _mocks(mocker, FULL, available=True)
    monkeypatch.setenv("SSH_CONNECTION", "1.2.3.4 5 6.7.8.9 22")
    _login(no_browser=True)
    assert "--port" not in capsys.readouterr().err


def test_port_without_browser_listens_and_prints_tunnel(mocker, monkeypatch, capsys):
    flow = _mocks(mocker, FULL)
    flow.run_local_server.return_value.refresh_token = "refresh-tunnel"
    monkeypatch.setenv("SSH_CONNECTION", "1.2.3.4 5 6.7.8.9 22")
    assert _login(port=8085) == "refresh-tunnel"
    flow.run_local_server.assert_called_once()
    kwargs = flow.run_local_server.call_args.kwargs
    assert kwargs["port"] == 8085 and kwargs["open_browser"] is False
    assert "ssh -L 8085:localhost:8085" in capsys.readouterr().err


def test_no_browser_with_port_listens_without_opening_browser(mocker):
    flow = _mocks(mocker, FULL, available=True)
    flow.run_local_server.return_value.refresh_token = "r"
    _login(no_browser=True, port=8085)
    kwargs = flow.run_local_server.call_args.kwargs
    assert kwargs["port"] == 8085 and kwargs["open_browser"] is False


@pytest.mark.parametrize("name", ["lynx", "w3m", "links", "elinks", "www-browser"])
def test_console_browser_is_not_a_browser(mocker, name):
    from mien import oauth
    fake = MagicMock()
    fake.name = name
    mocker.patch("mien.oauth.webbrowser.get", return_value=fake)
    assert oauth._browser_available() is False


def test_gui_browser_is_a_browser(mocker):
    from mien import oauth
    fake = MagicMock()
    fake.name = "MacOSX"
    mocker.patch("mien.oauth.webbrowser.get", return_value=fake)
    assert oauth._browser_available() is True


def test_exchange_failure_redacts_code_and_state_in_every_form(mocker):
    flow = _mocks(mocker, FULL)
    flow.fetch_token.side_effect = RuntimeError(
        "boom https://localhost/?code=4%2F0AbCdEf-ghi_JKL&state=st-secret-value plain 4/0AbCdEf-ghi_JKL"
    )
    mocker.patch("mien.oauth.click.prompt", return_value=FULL.replace("state=st", "state=st-secret-value"))
    with pytest.raises(click.ClickException) as exc:
        _login()
    msg = exc.value.message
    assert "0AbCdEf" not in msg and "st-secret-value" not in msg


def test_port_with_browser_opens_it(mocker):
    flow = _mocks(mocker, FULL, available=True)
    flow.run_local_server.return_value.refresh_token = "r"
    _login(port=8085)
    kwargs = flow.run_local_server.call_args.kwargs
    assert kwargs["port"] == 8085 and kwargs.get("open_browser", True) is True


def test_real_flow_rejects_wrong_state_without_leaking_code(mocker):
    mocker.patch("mien.oauth._browser_available", return_value=False)
    mocker.patch("mien.oauth.click.prompt", return_value=FULL.replace("state=st", "state=evil"))
    with pytest.raises(click.ClickException) as exc:
        _login()
    assert "state" in exc.value.message.lower()
    assert CODE not in exc.value.message and "0AbCdEf" not in exc.value.message
