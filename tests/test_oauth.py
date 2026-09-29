from unittest.mock import MagicMock

import click
import pytest

from mien.oauth import google_installed_app_flow


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


def _manual_flow_mocks(mocker, pasted, *, available=False):
    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = ("https://auth.example/consent", "st")
    fake_flow.credentials.refresh_token = "refresh-manual"
    mocker.patch("mien.oauth.InstalledAppFlow.from_client_config", return_value=fake_flow)
    mocker.patch("mien.oauth._browser_available", return_value=available)
    mocker.patch("mien.oauth.click.prompt", return_value=pasted)
    return fake_flow


def test_no_browser_uses_manual_paste_flow(mocker):
    flow = _manual_flow_mocks(mocker, "http://localhost/?state=st&code=abc")
    rt = google_installed_app_flow(client_id="c", client_secret="s", scopes=["x"])
    assert rt == "refresh-manual"
    flow.run_local_server.assert_not_called()
    flow.fetch_token.assert_called_once_with(authorization_response="https://localhost/?state=st&code=abc")


def test_no_browser_flag_forces_manual_even_with_browser(mocker):
    flow = _manual_flow_mocks(mocker, "http://localhost/?code=abc", available=True)
    google_installed_app_flow(client_id="c", client_secret="s", scopes=["x"], no_browser=True)
    flow.run_local_server.assert_not_called()


def test_manual_flow_rejects_input_without_code(mocker):
    _manual_flow_mocks(mocker, "http://localhost/?error=access_denied")
    with pytest.raises(click.ClickException, match="code="):
        google_installed_app_flow(client_id="c", client_secret="s", scopes=["x"])


def test_manual_flow_reports_state_mismatch(mocker):
    flow = _manual_flow_mocks(mocker, "http://localhost/?state=evil&code=abc")
    flow.fetch_token.side_effect = ValueError("state mismatch")
    with pytest.raises(click.ClickException, match="state mismatch"):
        google_installed_app_flow(client_id="c", client_secret="s", scopes=["x"])
