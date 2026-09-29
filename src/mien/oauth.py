from __future__ import annotations

import webbrowser

import click
from google_auth_oauthlib.flow import InstalledAppFlow

MANUAL_REDIRECT_URI = "http://localhost"


def _browser_available() -> bool:
    try:
        webbrowser.get()
    except webbrowser.Error:
        return False
    return True


def _manual_flow(flow: InstalledAppFlow):
    # The pasted URL is rewritten to https because oauthlib rejects http redirects
    # unless OAUTHLIB_INSECURE_TRANSPORT is set process-wide. State is verified by
    # oauthlib against the value generated in authorization_url().
    flow.redirect_uri = MANUAL_REDIRECT_URI
    url, _ = flow.authorization_url(prompt="consent", access_type="offline")
    click.echo("Open this URL in a browser on any machine and grant access:\n")
    click.echo(url + "\n")
    click.echo(
        "The browser will then be redirected to a localhost page that fails to load. "
        "Copy the full URL from its address bar and paste it here."
    )
    pasted = click.prompt("Redirected URL").strip()
    if "code=" not in pasted or not pasted.startswith(("http://", "https://")):
        raise click.ClickException("pasted value is not a redirect URL containing 'code='")
    if pasted.startswith("http://"):
        pasted = "https://" + pasted[len("http://"):]
    try:
        flow.fetch_token(authorization_response=pasted)
    except Exception as exc:
        raise click.ClickException(f"could not complete Google login: {exc}") from exc
    return flow.credentials


def google_installed_app_flow(
    *, client_id: str, client_secret: str, scopes: list[str], no_browser: bool = False
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
    if no_browser or not _browser_available():
        if not no_browser:
            click.echo("No browser available on this host; using the manual paste flow.", err=True)
        creds = _manual_flow(flow)
    else:
        creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
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
