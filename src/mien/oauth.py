from __future__ import annotations

import os
import re
import webbrowser
from urllib.parse import parse_qs, quote

import click
from google_auth_oauthlib.flow import InstalledAppFlow

from mien.security import register_secret

MANUAL_REDIRECT_URI = "http://localhost"
_QUOTES = "\"'`\u2018\u2019\u201c\u201d"


_CONSOLE_BROWSERS = {"lynx", "w3m", "links", "elinks", "www-browser"}


def _browser_available() -> bool:
    # A console browser registers fine on a headless host but cannot show the
    # consent page, so the local-server flow would wait forever for a redirect.
    try:
        return webbrowser.get().name not in _CONSOLE_BROWSERS
    except webbrowser.Error:
        return False


def parse_redirect_input(text: str) -> tuple[str, str]:
    """Extract (code, state) from what the user pasted: the redirected URL or its
    query string. Both must carry state; a bare code is refused because nothing
    would tie it to this login attempt.

    Whitespace is removed everywhere, not just at the ends: a URL wrapped by the
    terminal arrives with newlines in the middle, and neither an authorization code
    nor a URL contains a legitimate space. Error messages never echo the input.
    """
    text = re.sub(r"\s+", "", text).strip(_QUOTES)
    if not text:
        raise click.ClickException("nothing was pasted (empty input)")
    text = text.split("#", 1)[0]
    if "?" in text:
        query = text.split("?", 1)[1]
    elif "=" in text or "&" in text:
        query = text
    else:
        raise click.ClickException(
            "a bare code cannot be verified; paste the full redirected URL "
            "(or its query string) so its state can be checked"
        )
    params = parse_qs(query)
    if "error" in params:
        raise click.ClickException(f"Google denied the request: {params['error'][0]}")
    if not params.get("code"):
        raise click.ClickException(
            "no 'code' found in the pasted value; paste the full redirected URL "
            "or its query string"
        )
    if not params.get("state"):
        raise click.ClickException(
            "no 'state' found in the pasted value; paste the full redirected URL "
            "or its query string so its state can be checked"
        )
    return params["code"][0], params["state"][0]


def _echo_ssh_hint(port: int | None) -> None:
    if not os.environ.get("SSH_CONNECTION"):
        return
    if port:
        msg = (
            f"This host is reached over SSH. From the machine that has the browser, run:\n"
            f"  ssh -L {port}:localhost:{port} <host>\n"
            f"then open the URL below in that browser; the redirect reaches this process directly."
        )
    else:
        msg = (
            "This host is reached over SSH. To skip the paste step, re-run with "
            "--port <port> and forward that port from your browser machine."
        )
    click.echo(msg, err=True)


def _manual_flow(flow: InstalledAppFlow):
    # State is verified by oauthlib against the value generated in
    # authorization_url(), so the response is rebuilt from the parsed parts: the
    # paste may be a bare query string, and oauthlib rejects an http redirect
    # unless OAUTHLIB_INSECURE_TRANSPORT is set process-wide, hence https.
    flow.redirect_uri = MANUAL_REDIRECT_URI
    url, _ = flow.authorization_url(prompt="consent", access_type="offline")
    click.echo("Open this URL in a browser on any machine and grant access:\n")
    click.echo(url + "\n")
    click.echo(
        "The browser then lands on a localhost page that fails to load. Select its "
        "address bar (Cmd+L / Ctrl+L), copy, and paste it here. Safari shows only the "
        "domain; the copy still contains the full URL."
    )
    code, state = parse_redirect_input(click.prompt("Redirected URL", hide_input=True))
    for secret in (code, state):
        register_secret(secret)
    try:
        flow.fetch_token(
            authorization_response=f"https://localhost/?code={quote(code, safe='')}&state={quote(state, safe='')}"
        )
    except Exception as exc:
        msg = str(exc)
        for secret in (code, state):
            msg = msg.replace(secret, "<redacted>").replace(quote(secret, safe=""), "<redacted>")
        raise click.ClickException(f"could not complete Google login: {msg}") from exc
    return flow.credentials


def google_installed_app_flow(
    *,
    client_id: str,
    client_secret: str,
    scopes: list[str],
    no_browser: bool = False,
    port: int | None = None,
) -> str:
    cfg = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(cfg, scopes=scopes)
    browser = not no_browser and _browser_available()
    if browser:
        creds = flow.run_local_server(port=port or 0, prompt="consent", access_type="offline")
    elif port:
        if not no_browser:
            click.echo("No browser available on this host.", err=True)
        _echo_ssh_hint(port)
        creds = flow.run_local_server(
            port=port, open_browser=False, prompt="consent", access_type="offline"
        )
    else:
        if not no_browser:
            click.echo("No browser available on this host; using the manual paste flow.", err=True)
            _echo_ssh_hint(None)
        creds = _manual_flow(flow)
    if not creds.refresh_token:
        raise RuntimeError(
            "OAuth completed but no refresh token was returned. "
            "Re-run with prompt=consent and ensure access_type=offline."
        )
    return creds.refresh_token


def exchange_refresh_token(*, client_id: str, client_secret: str, refresh_token: str) -> str:
    """Exchange refresh token for an access token."""
    import httpx

    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]
