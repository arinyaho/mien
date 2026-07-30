# Usage recipes

## Add a Google identity

You need an OAuth Desktop client in *some* GCP project (does not have to be the same as the secrets backend project). Get its client ID and client secret.

```bash
mien login personal --service google --email me@example.com --client-id <id>
# paste the client secret when prompted
# follow the browser flow that opens
```

## Add a GitHub identity (paste a PAT)

```bash
mien login personal --service github
# enter username, paste a fine-grained or classic PAT
```

## Add a Slack identity (one workspace at a time)

```bash
mien login personal --service slack --workspace team-a
# paste an xoxp- user token
```

## Add a Notion identity

```bash
mien login personal --service notion
# paste a Notion integration token
```

## Add a credential of your own (any single env var)

An LLM API key, an npm/PyPI token, a database URL — anything that is one
environment variable carrying one secret:

```bash
mien login personal --service custom --name ANTHROPIC_API_KEY
# paste the key (hidden prompt)

mien exec personal -- claude -p "…"        # arrives as $ANTHROPIC_API_KEY
mien logout personal --service custom --name ANTHROPIC_API_KEY
```

`--name` is the variable name. It must be a shell identifier (`[A-Za-z_][A-Za-z0-9_]*`), and it may not be any of: a name mien already uses for a built-in service (`GH_TOKEN`, `AWS_PROFILE`, `NOTION_TOKEN`, … — the refusal names the service it would fight), one the shell or mien itself reads as an instruction (`PATH`, `HOME`, `IFS`, `PS1`, `TMPDIR`, `MIEN_CONFIG`), or one of the agent-harness capture markers mien reads to know an agent is driving (`CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `MIEN_CAPTURED`). All four refusals fire at `login` time and again whenever the config is parsed, so a hand-edited config fails the same way; `schema.md` carries the full list and the reason for each.

The config stores only a reference, so the secret stays in the backend. `mien status` reports the variable as `<set>`, never its value, and there is no `mien token custom` — `mien exec` is the interface.

## Activate (interactive shell)

```bash
mien-use personal            # the wrapper keys the ephemeral files to this shell ($$)
gh pr list
gcloud projects list
```

The exports live in *this* shell only. A second terminal is unaffected, and a new shell
starts with no profile.

## Pin an identity to a project

Give a profile the directories it owns, and work in those directories runs as that
identity without naming it:

```jsonc
"profiles": {
  "work":     { "default_for": ["*/Projects/acme*"] },
  "personal": { "default_for": ["*/Projects/mien"] }
}
```

```bash
mien which                     # → work
mien run -- gh pr list
```

Useful when several agent sessions run at once: each one is in its own project
directory, so each gets its own identity with no coordination between them.

## Activate (AI agent)

Agent harnesses run each command in a fresh shell, so an `eval` from an earlier tool call
has already been discarded — silently. Prefer a stateless form:

```bash
mien run -- gh pr list                 # if the directory pins an identity
mien exec personal -- gh pr list       # otherwise, name it

# for an HTTP call, let the child shell expand the credential — quote with '…' so
# your shell doesn't. The secret never reaches stdout or the transcript; it does
# still appear in the child's argv (`ps`), the same as any curl -H form.
mien exec personal -- sh -c 'curl -s -H "Authorization: Bearer $NOTION_TOKEN" \
  -H "Notion-Version: 2022-06-28" https://api.notion.com/v1/users/me'
mien exec personal -- sh -c 'curl -s -u "$ATLASSIAN_EMAIL:$ATLASSIAN_API_TOKEN" \
  "$ATLASSIAN_BASE_URL/rest/api/3/issue/PROJ-123"'   # Atlassian is Basic, not Bearer
mien exec personal -- sh -c 'curl -s -H "Authorization: Bearer $(gcloud auth application-default print-access-token)" \
  "https://gmail.googleapis.com/gmail/v1/users/me/profile"'
```

Google is the one service with no bare-token variable — `mien exec` gives it
`GOOGLE_APPLICATION_CREDENTIALS`, an ADC *file path* a client library reads directly, so
the token is minted from it in the child above. `mien token google` still prints one, but that is
the case its harness refusal covers: from an agent it needs `--force` or
`MIEN_TOKEN=capture-ok`.

If a sequence genuinely needs one shell, keep the `eval` and the commands in a single
invocation. See the skill's *Activation pattern* section.

## Verify the live identity before something destructive

`mien whoami` prints what the config says a profile is — fast, offline, no network — as a
card of the whole bundled identity: every provider that profile is (Google, GitHub, Slack,
AWS, OCI, Atlassian, Notion), plus the remotes and directories it owns, in one view. It
shows names and selectors only, never a token. Add `--json` for the machine-readable form.
`mien whoami --live` goes further: it asks GitHub, AWS, and Google who the profile
*actually* authenticates as and compares that to the config.

```bash
mien whoami personal            # offline: the whole identity as a card
mien whoami personal --json     # offline: the same, machine-readable
mien whoami --live personal     # verified: who the providers say you are
```

`--live` exits non-zero on a mismatch (wrong identity) or a dead credential (revoked or
expired token), and those are reported distinctly since they need different remedies. A
provider that could not be reached is shown but does not fail the check.

Two limits worth knowing before you rely on the exit code as a gate: **AWS is reported, not verified** — a profile name is not an ARN, so there is no configured value to compare and a wrong-but-valid AWS account will not trip the gate; and **GitHub, AWS and Google are the only services with a live probe at all**, so everything else the profile configures is listed by name under `not checked (no live probe yet)` rather than pretended verified. `custom` is always on that line — mien is told a variable name, never what the credential is for — and so is a gcloud-login-only `google` with no stored refresh token, which the probe structurally cannot verify. Read the line rather than assuming a clean report covered the service you care about; the gate itself is trustworthy for GitHub and Google. Chain it before anything you cannot take back:

```bash
mien whoami --live work && mien exec work -- gh pr merge 123
```

## Cross-identity one-off

```bash
mien exec work -- gh pr list
```

## Adding secrets without leaving a trace

Adding a credential mid-task — "the Slack key is in this file", "here's a fresh
PAT" — is routine. Every `mien login` secret is read without ever touching `argv`,
shell history, or `ps`: interactively through a hidden `getpass` prompt, or from
stdin / a helper command. Every backend then stores it without argv exposure too —
`macos_keychain` and `keyring` through in-process Keychain / Secret Service
bindings, `gcp_secret_manager` over its API. Pick the recipe
that matches where the secret already lives.

### From a file on disk

The secret is sitting in a file (a saved token, an exported key). Redirect the
file into `--token-stdin` — the path appears in history, the secret does not:

```bash
mien login work --service slack --workspace team-a --token-stdin < ./slack-key.txt
mien login work --service github --username u --token-stdin < ~/tokens/gh-work
mien login work --service custom --name ANTHROPIC_API_KEY --token-stdin < ~/tokens/anthropic
```

Delete the file afterward if it was only a hand-off (`rm ./slack-key.txt`); the
secret now lives in the backend.

### From a credential manager (a reference, not the value)

The secret lives in 1Password, GCP Secret Manager, the macOS Keychain, etc. Pass
`--secret-cmd` a command that *fetches* it — only the reference reaches history,
never the secret. `mien` runs the command and reads its stdout:

```bash
mien login work --service github --username u \
  --secret-cmd 'op read op://Private/github-work/token'
mien login work --service aws --access-key-id AKIA... \
  --secret-cmd 'gcloud secrets versions access latest --secret=aws-work'
mien login work --service custom --name NPM_TOKEN \
  --secret-cmd 'op read op://Private/npm-work/token'
```

Equivalently, pipe the manager's output into `--token-stdin`
(`op read … | mien login … --token-stdin`) — same guarantee, the value never
becomes an argument.

### By hand, in your own terminal

No file, no manager — you have the secret and want to paste it. Run `mien login`
yourself (**not** through an AI agent's non-interactive shell) and answer the
hidden prompt:

```bash
mien login work --service github --username u
#   → "Paste a GitHub token:" (input hidden, nothing logged)
```

### Google (two secrets)

Google needs a client secret *and* a refresh token; combine any two mechanisms
above — here a manager reference for the client secret and a file for the token:

```bash
mien login work --service google --email me@x.com --client-id <id> \
  --secret-cmd 'op read op://Private/google-oauth/client_secret' \
  --refresh-token-stdin < ~/saved-refresh-token
```

Rule of thumb: never type or paste a secret as a CLI argument, and never ask an
AI agent to run `mien login` for you — its shell can't answer a hidden prompt, so
the secret would end up in the session transcript. Hand it a file (`--token-stdin
< path`) or a `--secret-cmd` reference instead.

## Reuse on a second machine

Secrets already live in the cloud backend; the config manifest carries the
profile map. On the new machine:

```bash
gcloud auth application-default login --account=<bootstrap-email>
gcloud auth application-default set-quota-project <sm-project>
mien init --backend gcp_secret_manager --project <sm-project> \
  --bootstrap-email <bootstrap-email>
#   → "Found an existing mien config (N profiles: ...). Import it? [Y/n]"
mien-use <profile>
```

`mien init --no-import` skips the import prompt. `mien init --yes` auto-imports
without asking. A non-interactive run *without* `--yes` does **not** auto-import:
the confirmation prompt aborts, and because `init` has already written a fresh
empty config by that point, you are left with no profiles. Pass `--yes` or
`--no-import` explicitly when running `init` from a script or an agent — and note
that `--yes` means trusting whatever the backend manifest contains. Later, re-pull with `mien sync` (`--dry-run` to preview) or force-upload
local state with `mien push`. `mien sync` and `mien push` require a cloud backend
(`gcp_secret_manager`); they are a no-op or error on `macos_keychain`.
