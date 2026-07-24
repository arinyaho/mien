"""Inventory the identities already configured on this machine, so onboarding is
"here's what you have, import what you want" rather than a blank config.

Read-only: it inspects the local config of each provider (AWS/OCI profiles,
gcloud configurations, GitHub accounts) and reports which are already bound to a
mien profile and which are not, with the command to import each. It never reads a
secret and never writes anything — importing stays an explicit `mien login`.
"""

from __future__ import annotations

import configparser
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mien.config import Profile


@dataclass(frozen=True)
class Found:
    provider: str      # "aws" | "oci" | "gcloud" | "github"
    identifier: str    # profile / config / account name — how a mien profile refers to it
    detail: str = ""   # e.g. the account email behind a gcloud config


def _ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error):
        pass
    return parser


def discover_aws(home: Path) -> list[Found]:
    """AWS profiles from `~/.aws/config` (`[profile x]`, `[default]`) and
    `~/.aws/credentials` (`[x]`)."""
    names: set[str] = set()
    for section in _ini(home / ".aws" / "config").sections():
        names.add(section[len("profile "):] if section.startswith("profile ") else section)
    names.update(_ini(home / ".aws" / "credentials").sections())
    return [Found("aws", n) for n in sorted(names)]


def discover_oci(home: Path) -> list[Found]:
    """OCI profiles are the section names in `~/.oci/config` (incl. DEFAULT)."""
    parser = _ini(home / ".oci" / "config")
    names = set(parser.sections())
    if parser.defaults():
        names.add("DEFAULT")
    return [Found("oci", n) for n in sorted(names)]


def discover_gcloud(home: Path) -> list[Found]:
    """gcloud configurations from `~/.config/gcloud/configurations/config_<name>`,
    each a `[core] account = …` ini."""
    base = home / ".config" / "gcloud" / "configurations"
    found: list[Found] = []
    if not base.is_dir():
        return found
    for path in sorted(base.glob("config_*")):
        name = path.name[len("config_"):]
        account = _ini(path).get("core", "account", fallback="")
        found.append(Found("gcloud", name, account))
    return found


def discover_github(run=subprocess.run) -> list[Found]:
    """GitHub accounts from `gh auth status`. Skipped silently if gh is absent."""
    try:
        result = run(["gh", "auth", "status"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    found: list[Found] = []
    for line in (result.stdout + result.stderr).splitlines():
        # "✓ Logged in to github.com account <name> (…)"
        if "Logged in to" in line and " account " in line:
            after = line.split(" account ", 1)[1].strip()
            name = after.split()[0] if after else ""
            host = line.split("Logged in to", 1)[1].strip().split()[0]
            if name:
                found.append(Found("github", name, host))
    return found


def discover_all(home: Path | None = None, *, github_run=subprocess.run) -> list[Found]:
    home = home or Path(os.environ.get("HOME", str(Path.home())))
    return (discover_aws(home) + discover_oci(home) + discover_gcloud(home)
            + discover_github(github_run))


def _bound_identifiers(profiles: dict[str, Profile], provider: str) -> set[str]:
    """The identifiers a provider is already bound to across mien profiles."""
    bound: set[str] = set()
    for prof in profiles.values():
        if provider == "aws" and prof.aws and prof.aws.profile:
            bound.add(prof.aws.profile)
        elif provider == "oci" and prof.oci and prof.oci.profile:
            bound.add(prof.oci.profile)
        elif provider == "gcloud" and prof.google and prof.google.gcloud_config_name:
            bound.add(prof.google.gcloud_config_name)
        elif provider == "github" and prof.github and prof.github.username:
            bound.add(prof.github.username)
    return bound


def _import_hint(item: Found) -> str:
    p = "<profile>"
    if item.provider == "aws":
        return f"mien login {p} --service aws --aws-profile {item.identifier}"
    if item.provider == "oci":
        return f"mien login {p} --service oci --oci-profile {item.identifier}"
    if item.provider == "github":
        return f"mien login {p} --service github --username {item.identifier}"
    if item.provider == "gcloud":
        email = f" --email {item.detail}" if item.detail else ""
        return f"mien login {p} --service google{email} --client-id <id>"
    return ""


def render_report(found: list[Found], profiles: dict[str, Profile]) -> str:
    """A human report: per provider, each discovered identity marked as already in
    a mien profile or not imported (with the command to import it)."""
    if not found:
        return ("No local AWS / OCI / gcloud / GitHub identities found to import. "
                "Set one up with `mien login`.")
    labels = {"aws": "AWS profiles", "oci": "OCI profiles",
              "gcloud": "gcloud configurations", "github": "GitHub accounts"}
    lines: list[str] = []
    for provider in ("github", "gcloud", "aws", "oci"):
        items = [f for f in found if f.provider == provider]
        if not items:
            continue
        bound = _bound_identifiers(profiles, provider)
        lines.append(f"{labels[provider]}:")
        for item in items:
            detail = f" ({item.detail})" if item.detail else ""
            if item.identifier in bound:
                lines.append(f"  ✓ {item.identifier}{detail} — in a mien profile")
            else:
                lines.append(f"  · {item.identifier}{detail} — not imported")
                lines.append(f"      {_import_hint(item)}")
    return "\n".join(lines)
