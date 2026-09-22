# mien

![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Claude Code](https://img.shields.io/badge/Claude%20Code-plugin-8A2BE2)
![GitHub Copilot](https://img.shields.io/badge/GitHub%20Copilot-agent%20plugin-24292F)

Multi-identity credential router for Google, GitHub, and Slack — designed for developers juggling multiple accounts (personal + work) across services.

## What it does

Activate a named identity in your current shell:

```bash
eval "$(mien use --owner-pid $$ personal)"   # or: mien-use personal (the wrapper passes $$ for you)
gh pr list                 # uses your personal GitHub
gcloud projects list       # uses your personal GCP
TOKEN=$(mien token google) # mint a Gmail/Cal/Drive access token on demand
```

A second shell can run `mien-use work` (or `eval "$(mien use --owner-pid $$ work)"`) independently — activation touches only that shell. Tokens live in a secrets backend rather than in a dotfile.

## Architecture

- **Per-session env vars** activate `gcloud`, `gh`, etc.
- **Ephemeral files** (mode 0600, `${TMPDIR}/mien/`) hold per-session ADC, SSH key and Slack tokens. `mien exec` and `mien run` delete theirs when the child exits; the ones `mien use` leaves for your shell are swept on a best-effort basis — see [SECURITY.md](SECURITY.md#lifetime-and-cleanup).
- **Pluggable secrets backend**: GCP Secret Manager, macOS Keychain, or keyring (Linux Secret Service / Windows Credential Locker — free, no cloud, requires a desktop session).

[SECURITY.md](SECURITY.md) describes what is stored where, who can read it, and what `mien` deliberately does not protect — including that it does **not** hide credentials from an AI agent it hands them to.

## Install

### CLI

```bash
uv tool install git+https://github.com/arinyaho/mien    # or: pipx install git+https://github.com/arinyaho/mien
echo 'eval "$(mien shell-init)"' >> ~/.zshrc            # adds the mien-use / mien-unset wrappers
```

No checkout needed — both lines install from the repo directly. `mien shell-init` prints the shell wrappers; `eval`-ing it defines `mien-use` and `mien-unset` and wires the exit-trap cleanup. Use `--shell bash` (or add to `~/.bashrc`) for bash.

To hack on it, clone and install from the working tree instead:

```bash
git clone https://github.com/arinyaho/mien ~/projects/mien
cd ~/projects/mien && uv tool install --editable .
```

### As an agent skill

`mien` ships a SKILL.md that teaches AI agents (Claude Code, Codex, GitHub Copilot Chat, Hermes Agent) when and how to invoke the CLI on your behalf. The skill assumes the `mien` binary is already on `PATH` — install the CLI first (above), then add the skill:

> **One rule worth knowing yourself:** `mien` routes the environment-variable plane only. Your agent's built-in service connectors (Atlassian, Slack, Notion, Google) hold one fixed account each and ignore a profile switch entirely — so a session told to use `work` still reads Jira as whoever the connector authenticated as, silently. For any service a profile has credentials for, the agent should call the REST API under `mien exec <profile> -- `. The skill says so as its first rule; see [SECURITY.md](SECURITY.md#protection-goals-and-what-is-not-protected).

**Claude Code:**

```bash
/plugin marketplace add arinyaho/mien
/plugin install mien@arinyaho
```

Codex, GitHub Copilot Chat, and Hermes Agent install the same skill their own way — see **[docs/guide.md](docs/guide.md#agent-skill-install)**. Once installed, the agent invokes `mien` automatically when you mention identity-scoped work — e.g. "as my work account", "switch to personal".

## Bootstrap

```bash
mien discover                           # what identities are already on this machine?
mien init                               # pick a backend
mien login personal --service github
mien login personal --service google --email me@x.com --client-id <id>
mien login personal --service slack --workspace team-a
mien login personal --service custom --name ANTHROPIC_API_KEY   # a credential of your own
```

`mien discover` is the onboarding shortcut: it inventories the identities already configured locally (AWS/OCI profiles, gcloud configurations, GitHub accounts) *and* the places — the git remote owners of the repositories on this machine — showing which are already bound to a mien profile and which are not, with the command to bind each:

```
Git remote owners:
  ✓ github.com/acme-inc — owned by work
  · github.com/me (github.com/me/blog) — no profile owns it
      mien discover --own github.com/me --profile <profile>
```

It reads no secret and touches no backend. Claiming an owner is the one thing that writes: `mien discover --own github.com/me --profile personal` adds `github.com/me/*` to that profile's [`owns_remotes`](docs/guide.md#project-pinned-identity) — which is what the status line, `mien guard` and `mien exec` read to tell whose place a repository is. Importing a credential stays an explicit `mien login`.

Full reference — profile export inspection, workspace binding, status line, identity guards, git integration, custom credentials, ambient env — lives in **[docs/guide.md](docs/guide.md)**.
