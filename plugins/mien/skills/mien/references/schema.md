# Config schema (`~/.config/mien/config.json`)

Default location: `~/.config/mien/config.json`. Override with `MIEN_CONFIG=/some/path`.

Top level:

```jsonc
{
  "$schema_version": 1,
  "secrets_backend": { "type": "...", /* options */ },
  "bootstrap": { /* optional, backend-specific */ },
  "secret_naming": { "default": "...", "slack_token": "..." },
  "profiles": { "<name>": { /* see Profile blocks */ } }
}
```

## Backends

- `gcp_secret_manager`: `{"type": "gcp_secret_manager", "project": "<gcp-project>"}`
- `macos_keychain`: `{"type": "macos_keychain", "service_prefix": "mien-"}`
- `keyring`: `{"type": "keyring", "service_prefix": "mien-"}` — Linux Secret Service / Windows Credential Locker; free, no cloud; requires a desktop session (does NOT work headless)

## Unknown keys are fatal

A key mien does not recognize — at profile level, or inside any service block (`google`, `github`, a `slack` entry, `aws`, `oci`, `atlassian`, `notion`) — is a hard error, not a dropped field. The load raises `ConfigError`, so *every* command that reads the config (`list`, `use`, `exec`, `run`, `which`, `whoami`, `doctor`, `statusline`, `guard`) exits 1 until the key is removed. One typo anywhere makes the whole config unusable, not just the profile it sits in.

That blast radius is deliberate. Silently dropping the key is the quieter failure and the worse one: `"defualt_for"` discards the directory claim and the directory falls through to some other profile's catch-all glob; `"profil"` in an `aws` block leaves `AWS_PROFILE` unexported and the CLI falls back to its own default account. Nothing warns, the command succeeds, and it succeeds as the wrong person. A misconfigured identity has to fail loudly.

The message names the offending key and lists the valid ones for that block, so the fix is mechanical. **When hand-editing a profile, add only keys enumerated below.**

Keys from older mien versions are tolerated by name, and only at the value that made their removal a no-op — an old config still loads:

| key | where | tolerated value |
| --- | --- | --- |
| `git_name` | profile | any (no code path ever read it) |
| `gcloud_login_required` | `google` | `false` |
| `team_id` | `slack` entry | `null` |

Any *other* value for `gcloud_login_required` / `team_id` is an error rather than a silent drop: it meant something once, so discarding it would change behaviour without saying so.

## Profile blocks

Every profile-level key is optional; a service the profile omits (or sets to `null`) simply does not exist for it. This is the complete accepted set:

| key | type | |
| --- | --- | --- |
| `google` | object \| null | Google account (Gmail/Calendar/Drive + GCP) |
| `github` | object \| null | GitHub account |
| `slack` | array of objects | zero or more workspaces |
| `aws` | object \| null | AWS credentials or named profile |
| `oci` | object \| null | OCI CLI profile |
| `atlassian` | object \| null | Jira/Confluence account |
| `notion` | object \| null | Notion integration token |
| `project_env` | array of objects | ambient env by directory |
| `default_for` | array of strings | directory globs claiming identity |
| `owns_remotes` | array of strings | git-remote globs claiming identity |
| `git_email` | string \| null | git author address for the cross-check |

**Shapes are checked, not coerced.** A service block must be a JSON object, `slack` and `project_env` must be arrays of JSON objects, and `default_for` / `owns_remotes` must be arrays of strings. A wrong type is reported as a `ConfigError` naming the block — never coerced, and never allowed to escape as a `TypeError`, because the fail-open surfaces (`mien guard`, `mien statusline`) recognize only `ConfigError` as "I have stopped working" and would otherwise exit in silence.

Within a block, a **missing required field** is the same class of error as an unknown one, reported with the block's valid key list.

### `google`
```jsonc
{
  "email": "...",
  "oauth_client_id": "...",
  "oauth_client_secret_ref": "<backend-ref>",
  "refresh_token_ref":       "<backend-ref>",
  "adc_ref":                 "<backend-ref>|null",
  "gcloud_config_name":      "<typically equals profile name>",
  "default_project":         "..."|null
}
```

All seven keys are required when the block is present. The three nullable ones (`oauth_client_secret_ref`, `adc_ref`, `default_project`) may hold `null`, but the key itself must still be there.

### `github`
```jsonc
{
  "username": "...",
  "host": "github.com",
  "token_ref":     "<backend-ref>|null",   // optional
  "ssh_key_path":  "<path>|null",          // optional
  "ssh_key_ref":   "<backend-ref>|null"    // optional
}
```

`username` and `host` are required. `ssh_key_ref` (key contents in the backend, materialized per-shell) takes precedence over `ssh_key_path` (a static on-device key file).

### `slack` (array)
```jsonc
[{ "workspace": "team-a", "user_token_ref": "<backend-ref>" }]
```

Both keys are required in each entry.

### `aws`
```jsonc
{
  "region":                  "..."|null,
  "profile":                 "..."|null,
  "access_key_id_ref":       "<backend-ref>|null",
  "secret_access_key_ref":   "<backend-ref>|null"
}
```

All four are optional — the block may carry a named `~/.aws/config` profile, static keys from the backend, or both.

### `oci`
```jsonc
{ "profile": "..."|null, "config_file": "<path>|null" }
```

Both optional.

### `atlassian`
```jsonc
{ "email": "...", "base_url": "https://<site>.atlassian.net", "api_token_ref": "<backend-ref>" }
```

All three are required. Atlassian Cloud is HTTP Basic (`email:token`), so the email is part of the credential, not decoration.

### `notion`
```jsonc
{ "api_token_ref": "<backend-ref>" }
```

Required when the block is present.

### `git_email`

The git author address a commit under this identity carries. Hand-edited, like `default_for` / `owns_remotes`.

```jsonc
"git_email": "me@acme.example"
```

Setting git's own `user.email` is git's job (native `includeIf`); mien reads `git_email` only for the author cross-check, so `mien guard` and the status line can warn when a commit's `user.email` disagrees with the identity acting here. Set it when you commit under an address none of the profile's accounts carry.

### `default_for` (array)

Directory globs this profile claims as its default identity. Resolved by `mien
which` and `mien run`.

```jsonc
["*/Projects/acme*", "*/work/*"]
```

A scope covers the directory itself and everything under it; a sibling sharing a
prefix is not covered (`*/Projects/acme` does not capture `acme-fork`). The
longest matching scope wins, and equally specific scopes on different profiles
are an error rather than a coin flip. An active `MIEN_PROFILE` overrides the
directory, with a warning on stderr when the two disagree; if it names a profile
the config does not have, the command fails instead of resolving to nothing.

`~` and `$VAR` are expanded before matching, so `~/Projects/acme` and
`$HOME/Projects/acme` are equivalent to the literal path. A variable that is
**unset or set to the empty string** is left literal and therefore matches
nothing, as is `~` when `HOME` is empty. This differs deliberately from the
`project_env` shell, where zsh expands both to the empty string — there
`$UNSET/Projects/acme` becomes `/Projects/acme`, which is *disjoint* from the
intended tree (it silently covers an unrelated path and stops covering the one
you meant), and a scope that is nothing but a reference — `$UNSET`, or
`$UNSET/*`, which normalizes to the same base — collapses to the pattern `/*`
and covers every absolute path. For identity, failing closed beats either
outcome.

Must be a list of strings. A bare string is rejected rather than coerced: JSON
has no way to tell a one-element list from a scalar, and silently accepting
`"default_for": "*/Projects/acme"` would iterate it character by character, one
of which is `*`.

Distinct from `project_env`, which maps directories to environment *values*;
`default_for` maps directories to *which identity you are*.

### `owns_remotes` (array)

Git-remote globs this profile owns. Where `default_for` claims identity by
directory, `owns_remotes` claims it by the repository's `origin` remote — by
*what the repo is* rather than where it sits — so it fits repositories kept side
by side with no per-employer directory convention.

```jsonc
["github.com/acme-*/*", "github.com/me/*"]
```

The remote is normalized before matching: the scheme, any `user@`, and a trailing
`.git` are stripped and an ssh `:` becomes `/`, so every form of the same URL
(`https://…`, `git@github.com:…`, `ssh://…`) reduces to one canonical
`host/path`, lower-cased. A pattern matches that form and everything under it, so
a bare owner (`github.com/acme`) claims the owner and its repositories. The
longest match wins; an exact tie is an error, as with `default_for`. A profile may
list several — a personal account and the organizations it also manages. Same
list-of-strings rule: a bare string is rejected, not coerced.

**Advisory only.** `owns_remotes` drives the status line (`mien statusline`) — it
displays whose repository this is and warns when the active `MIEN_PROFILE`
disagrees. It is deliberately *not* consulted by `mien which` / `run` / `exec`,
which choose an identity that *acts*: a checked-out repository controls its own
`origin`, and letting a repository select an acting identity would violate the
rule that a clone cannot influence which identity acts. A directory scope is part
of your own config and may select an acting identity; a repository's self-declared
remote may not.

### `project_env` (array)

Non-secret environment values applied ambiently by directory. `mien env sync`
renders every profile's scopes into `~/.config/mien/ambient.zsh` as
`case "$PWD/" in <base>/*)` blocks and wires `~/.zshenv` to source it.

```jsonc
[{ "match": "*/work/acme", "env": { "AWS_PROFILE": "work" } }]
```

Each entry must be a JSON object carrying a `match` glob; `env` is optional and must itself be an object of plain values. `match` and `env` are the only accepted keys — an entry with no `match`, or one carrying any other key, is a `ConfigError`. The unknown-key rule matters most here: a typo'd `env` would otherwise leave the scope exporting nothing, so the directory silently falls back to whatever account the underlying CLI defaults to.

`match` follows the same directory-glob rules as `default_for` (the directory
itself and everything under it; a trailing `/*` or `/` is normalized away).
Values are non-secret only — no secrets-backend refs.

**Variable references in `match` are evaluated in `~/.zshenv`, which zsh reads
before `~/.zshrc` and `~/.zprofile`.** Anything the user exports from their own
dotfiles is therefore unset at match time and expands to nothing, with the
consequences described under `default_for` above: `$WORK_ROOT/*` becomes `/*`
and applies that scope's env — `AWS_PROFILE` included — in every directory. Only
parameters that already exist that early (`$HOME`, `$USER` and the like, set by
zsh itself or inherited from the login process) are safe; `~` is safe too, since
tilde expansion consults the password database. `$TMPDIR` is deliberately *not*
treated as safe — macOS launchd sets it, but stock sshd and a default Linux PAM
do not, and mien pins no platform. `mien env sync` prints a warning naming the
profile and scope for any other reference, and still writes the file — an
existing working config is not broken by the check.

## Reserved backend secret name

`mien-config-manifest` is reserved: `mien` stores a non-secret snapshot of
`config.json` (refs and identifiers only — no secret values) under this name in
the cloud backend (`gcp_secret_manager`). It is pushed automatically
after every `mien login` / `mien logout`. Do not create a profile whose rendered
secret name collides with it.
