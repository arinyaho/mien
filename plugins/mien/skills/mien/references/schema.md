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

Those five are the complete accepted top-level set; anything else is an error (see below). `$schema_version` is what mien writes, and the unprefixed `schema_version` is accepted as an equivalent spelling — accepted, never advertised: the error listing the valid keys names only `$schema_version`, so a hand-written config is steered to one spelling. Give both and the prefixed one wins.

**Two of the five are required.** `$schema_version` — omit it and the load fails with `Unsupported schema_version None; expected 1`, because a file that does not say which schema it is written to is one mien cannot claim to understand, and this is checked *before* the unknown-key check so a config from a future schema is told its version is unsupported rather than blamed for a key that version legitimately added. And `secrets_backend`, or more precisely `secrets_backend.type` — without it mien cannot tell where secrets live. `bootstrap`, `secret_naming` and `profiles` each default to empty when absent.

`secret_naming` accepts exactly two keys, `default` and `slack_token`, each a template for a rendered backend secret name. Either may be omitted, in which case the built-in template applies (`mien-{profile}-{service}-{kind}` and `mien-{profile}-slack-{workspace}-token`).

## Backends

`secrets_backend` carries a `type` plus exactly the options that backend reads — every required one present, nothing else alongside them.

| type | required options | optional options | |
| --- | --- | --- | --- |
| `gcp_secret_manager` | `project` | — | GCP Secret Manager |
| `macos_keychain` | — | `service_prefix` (default `mien-`) | macOS login keychain |
| `keyring` | — | `service_prefix` (default `mien-`) | Linux Secret Service / Windows Credential Locker; free, no cloud; requires a desktop session (does NOT work headless) |

```jsonc
{ "type": "gcp_secret_manager", "project": "<gcp-project>" }
{ "type": "macos_keychain", "service_prefix": "mien-" }
{ "type": "keyring", "service_prefix": "mien-" }
```

An option this backend does not read (`"projct"`), or a required one that is missing (`project` under `gcp_secret_manager`), is a parse-time `ConfigError` naming the key — see below.

**An unrecognized `type` is a different check with a different message**, and not this one: it is raised not while parsing but the first time a command actually reaches for the backend — anything that reads or writes a secret, plus `sync` and `push`, which branch on whether the backend is a cloud one and must not read a retired cloud backend as "local, nothing to do". A config-only command (`mien which`, `mien list`, `mien discover`) still works with a backend type mien does not know. A type mien has *retired* (`oci_vault`) gets the migration story — re-init on a supported backend and log in again, or install a mien old enough to still export what is stored there — rather than the "did you typo an option?" answer. Options are only checked against a type mien knows, so an unknown type is reported on its own terms instead of dragging a pile of "unknown option" noise along with it.

## Unknown keys are fatal

A key mien does not recognize — at the top level, inside `secrets_backend` (an option the declared backend does not read), inside `secret_naming`, at profile level, inside any service block (`google`, `github`, a `slack` entry, `aws`, `oci`, `atlassian`, `notion`), or inside a `project_env` entry — is a hard error, not a dropped field. So is a required key that is *missing*, including a required backend option. The load raises `ConfigError`, so one typo anywhere makes the whole config unusable until it is fixed — not just the profile it sits in.

`bootstrap` is the one block held to no key list: it is backend-specific and free-form, so mien checks only that it is a JSON object.

That blast radius is deliberate. Silently dropping the key is the quieter failure and the worse one: `"profles"` at the top level yields a config with *zero* profiles, so every identity disappears and `mien which` resolves to nothing; `"defalt"` in `secret_naming` reverts to the built-in template, so `mien login` writes secrets under a different name than the config declares and anything already stored under the intended name becomes unreachable; `"defualt_for"` discards a directory claim and the directory falls through to some other profile's catch-all glob; `"profil"` in an `aws` block leaves `AWS_PROFILE` unexported and the CLI falls back to its own default account. Nothing warns, the command succeeds, and it succeeds as the wrong person. A misconfigured identity has to fail loudly.

What "fail loudly" costs depends on what the command was about to do. The rule is stated once here, deliberately, rather than as a roster of command names: a roster goes stale the next time a command is added, and this is the rule the code implements — **every command that reads the config fails hard, except the three always-on surfaces below, which fail open and announce.**

- **Failing hard means exit 1.** The command prints the parse error, the config's path, and what that costs you, then stops. No partial degradation: if it loads the config at all — to act as an identity, resolve one, display one, or write one back — a config it cannot understand stops it. Acting on a config mien cannot understand is exactly how the wrong identity acts.
- **The three exceptions are the always-on display and gate surfaces, and they fail open — exit 0 — but say so.** `mien statusline` and `mien prompt` print a compact red marker (`⚠ mien:config unreadable — run 'mien doctor'`, and `⚠mien:config` for the prompt) on **stdout**, where the identity segment would go, and exit 0: those two render their own stdout, so a message on stderr would leave the segment blank — and a status line that empties out reads as "nothing to report" when in fact mien can no longer tell who you are here. `mien guard` prints `mien: guard is NOT enforcing — config unreadable: <error>` on **stderr** and exits 0 — deliberately, so a broken config never wedges a commit, but never silently: a guard that has stopped guarding without admitting it is the worse failure. Neither surface refuses, and neither goes quiet.
- **A few commands read no config at all, so a broken one cannot touch them:** `init`, `shell-init`, `status`, `unset`, `preflight`. `init` is the one that matters when you are stuck: it checks only whether the file *exists* and never parses it, so it is the way out of a config too broken to hand-edit. It writes a fresh one over the top — it replaces your profiles, it does not repair them.

The message names the offending key and lists the valid ones for that block, so the fix is mechanical. **When hand-editing, add only keys enumerated here — the five top-level keys above, `type` plus that backend's own options from the table above, `default` / `slack_token` inside `secret_naming`, and the profile and service keys below.**

Keys from older mien versions are tolerated by name, and only at the value that made their removal a no-op — an old config still loads:

| key | where | tolerated value |
| --- | --- | --- |
| `git_name` | profile | any (no code path ever read it) |
| `gcloud_login_required` | `google` | `false` |
| `team_id` | `slack` entry | `null` |

Any *other* value for `gcloud_login_required` / `team_id` is an error rather than a silent drop: it meant something once, so discarding it would change behaviour without saying so. The error carries that key's own remedy, because for a key whose capability was removed the obvious fix — delete it — *is* a behaviour change.

`team_id` is the one retired key mien still *writes*. Every serialized `slack` entry carries `"team_id": null`, including the copy `mien push` stores as the shared backend manifest, as a write-side compatibility shim: an older mien reading that manifest still requires the key and fails without it. It remains retired on the way in — loading drops it — so it is a field of the file, not of the config. Expect it in a config mien wrote; do not add it by hand, and do not read anything into it.

## Profile blocks

Every profile-level key is optional; a service the profile omits (or sets to `null`) simply does not exist for it. Present-but-empty is not the same thing: `"google": {}` is a truncated block, not an absent one, and goes through every check — so `aws` and `oci`, whose fields are all optional, parse as empty blocks, while `google` reports the seven keys it is missing. This is the complete accepted set:

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

**Shapes are checked, not coerced.** A service block must be a JSON object, `slack` and `project_env` must be arrays of JSON objects, and `default_for` / `owns_remotes` must be arrays of strings. A wrong type is reported as a `ConfigError` naming the block — never coerced, and never allowed to escape as a `TypeError`, because the fail-open surfaces (`mien guard`, `mien statusline`, `mien prompt`) recognize only `ConfigError` as "I have stopped working" and would otherwise exit in silence.

**Values are checked too, at the leaves.** The type each field is declared with is enforced, not merely documented: `"username": 42` is `profile 'work': github: 'username' must be a string, got int: 42`, at parse time, rather than a value carried until something first uses it as text and dies there as an `AttributeError` the fail-open surfaces do not recognize. Nullability is part of that type — a field written below as `"..."|null` accepts `null`, and one written without it does not. So `"secret_naming": {"default": null}` is an error: a null there is not "fall back to the built-in template", it is a template that cannot be rendered. Booleans are not integers for this purpose; `true` is accepted only where the field really is a boolean.

Within a block, a **missing required field** is the same class of error as an unknown one, reported with the block's valid key list.

**Required-to-be-present and may-hold-`null` are different rules**, and a hand-edit needs both. A field is required because it declares no default, and it accepts `null` because its type says so — so a required key can legitimately carry `null` (every `"...|null"` key in the `google` block below is required *and* nullable), and dropping the key is an error even where `null` is fine. Conversely, a key you may omit entirely still has to hold a value of its declared type when you do write it.

### `google`
```jsonc
{
  "email": "...",
  "oauth_client_id": "...",
  "oauth_client_secret_ref": "<backend-ref>|null",
  "refresh_token_ref":       "<backend-ref>|null",
  "adc_ref":                 "<backend-ref>|null",
  "gcloud_config_name":      "<typically equals profile name>",
  "default_project":         "..."|null
}
```

All seven keys are required to be *present* when the block is present. Four of them may also hold `null`: `oauth_client_secret_ref`, `refresh_token_ref`, `adc_ref` and `default_project`. The other three — `email`, `oauth_client_id`, `gcloud_config_name` — must be strings.

`null` here is a working state, not an unset field. A gcloud-login-only profile has no stored refresh token and no stored OAuth client secret; every reader guards on that (`mien env`, `mien whoami`, `mien logout`), mien's own configs carry `null` there, and it is exactly the shape the `gcloud_login_required` retirement remedy above tells you to write. Omitting the key is still an error — presence and nullability are separate rules, and `null` is how you say "this profile has no such secret".

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

**It never selects an acting identity.** `owns_remotes` feeds the display surfaces (`mien statusline`, `mien prompt`) — which show whose repository this is and warn when the active `MIEN_PROFILE` disagrees — and `mien guard`, which *refuses* on that same disagreement. Blocking on the repository's own signal is safe: a crafted `origin` can at worst cause a false refusal you can override, never a mis-action. It is deliberately *not* consulted by `mien which` / `run` / `exec`, which choose an identity that *acts*: a checked-out repository controls its own `origin`, and letting a repository select an acting identity would violate the rule that a clone cannot influence which identity acts. A directory scope is part of your own config and may select an acting identity; a repository's self-declared remote may not.

### `project_env` (array)

Non-secret environment values applied ambiently by directory. `mien env sync`
renders every profile's scopes into `~/.config/mien/ambient.zsh` as
`case "$PWD/" in <base>/*)` blocks and wires `~/.zshenv` to source it.

```jsonc
[{ "match": "*/work/acme", "env": { "AWS_PROFILE": "work" } }]
```

Each entry must be a JSON object carrying a `match` glob; `env` is optional and must itself be a JSON object whose **keys are shell identifiers** — letters, digits and underscores, never starting with a digit (`[A-Za-z_][A-Za-z0-9_]*`, ASCII only, which is what zsh's `export` accepts, not what Python's `isidentifier()` does) — and whose **values are strings**. Both halves are checked because each pair is written into `ambient.zsh` verbatim as `export <key>=<value>`: a non-string value (`{"PORT": 8080}` is a plausible hand-edit) dies in the renderer as a bare `AttributeError` nothing catches, so `mien env sync` aborts with a Python traceback on stderr instead of an actionable `Error:` line, and nothing is written; and a key that is not an identifier survives every gate downstream — `zsh -n` *parses* `export 2FA="x"`, so the file is written, and sourcing it then fails at that line and **abandons the rest of the file**, silently dropping every later export, including every other profile's scopes. `export MY VAR="x"` is quieter still: valid syntax that exports `MY` empty and never sets the variable you wrote. `match` and `env` are the only accepted keys — an entry with no `match`, or one carrying any other key, is a `ConfigError`. `match` must be a non-empty string: a non-string one would reach the renderer as an `AttributeError` nothing catches, and an *empty* one normalizes to a base of `""`, so the emitted `case "$PWD/" in /*)` fires in every directory and exports that scope's env everywhere — the same silent widening the list-of-strings rule exists to stop. The unknown-key rule matters most here: a typo'd `env` would otherwise leave the scope exporting nothing, so the directory silently falls back to whatever account the underlying CLI defaults to.

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
