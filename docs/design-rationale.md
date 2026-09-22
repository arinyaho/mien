# Design rationale

Reasoning that exists nowhere else in the repository — rejected
alternatives, non-goals, and why a few things are shaped the way they are.
Everything else is better stated in [SECURITY.md](../SECURITY.md),
[README.md](../README.md), and module docstrings.

## Why the environment-variable plane, and what was rejected

Why `GH_TOKEN` rather than `gh auth switch`. gh reads GH_TOKEN from the environment, and that takes precedence over hosts.yml. Setting it per shell gives session isolation without mutating ~/.config/gh/hosts.yml, which is global. One CLI, two sessions, two identities.

Why `CLOUDSDK_ACTIVE_CONFIG_NAME` rather than `gcloud config configurations activate`. The same reasoning: gcloud honours the variable per process, while activating a configuration globally affects every other shell.

This is the load-bearing mechanism choice of the whole tool, and the repository never states it elsewhere. SECURITY.md asserts the resulting invariant — activation only ever writes to the current process environment — and the variables are listed in several places, but the obvious alternative a reader would reach for, and why it fails, appear nowhere else.

## Non-goals, and the rule for admitting a feature

Explicitly out of scope, with YAGNI enforced:

- Service-specific helper commands (mail search, slack post, and so on). Existing CLIs and ad-hoc curl calls cover daily use; a helper is added only when a pattern is repeatedly proven.
- Cross-identity fan-out or aggregation — "search all four mailboxes at once".
- A web UI, GUI or TUI dashboard.
- Profile templates and cloning.
- Audit logging beyond what the underlying secret backend already provides.

The framing that holds the list together: `exec` and `token` are credential-routing primitives, not service helpers.

Two entries from an earlier version of this list have since been answered rather than deferred, and shouldn't be carried forward as open: encrypted local file backends (age, sops, gpg) were effectively covered by the keyring backend, and a cloud vault backend was built and then deleted as dead weight.

The repository has no non-goals list anywhere else. This is the scope boundary that keeps the tool from turning into a mail client.

## Why it exists at all

The four pain points that motivated it, for someone holding several accounts across Google, GitHub and Slack at once:

- Re-authenticating hosted Gmail/Calendar/Drive integrations every time another account is needed.
- A globally active gcloud configuration cross-contaminating parallel agent sessions.
- No unified place to switch "who I am" — every tool needing its own ritual.
- Secrets scattered across local files, the OS keychain and ad-hoc environment variables.

The README says what the tool does and never why it exists.

## Manifest: two decisions that read as omissions

Storing the configuration next to the secrets adds no exposure. Anyone with read access to the backend project can already read the real secrets, so the manifest exposes strictly less. SECURITY.md documents the manifest's contents and attack surface thoroughly but never says this, so a reader is left to wonder whether it was considered.

No conflict detection, deliberately. Concurrent edits from several machines are last-write-wins, with recovery through the backend's own version history. This was chosen, not overlooked — plain auto-push, with conflict detection left out of v1.

## What was deliberately let go

Earlier drafts of this reasoning covered task-by-task implementation notes for modules that have since shipped, earlier and worse drafts of files that now exist, a design section on the config schema and CLI surface that the reference documentation has since outgrown, and a security section comprehensively obsoleted by SECURITY.md, which is both more accurate and more honest than its ancestor.

One detail is worth recording as a correction rather than a loss: the shipped rule for overlapping directory scopes is *better* than the original plan's. The plan accepted alphabetical-wins across profiles; the code resolves by match specificity and refuses an exact tie rather than guessing.

## Discoverability: a profile must be able to say what it exports

Knowing a profile has a credential is not knowing how to use it. The identity views named every service a profile carried and never the environment variable each credential arrives as, and the one command that answered — `exec <profile> -- env` — is a secret dump that an agent sandbox blocks. The answer was therefore reachable only by reading mien's source, and the reasonable conclusion from a blocked dump was that the service was unsupported.

The rule this settles: any view that exists to make credentials discoverable must be usable where secret dumps are forbidden. Names, sources and set/unset only. A view that leaks the value is one that gets blocked, which returns you to the original bug.

It also has to report what a profile does NOT set. `exec` overlays the environment without scrubbing, so an unset variable is one another identity's ambient value survives into — silence there reads as fine and is not.

## Why Slack has no token subcommand

`mien token` mints google, atlassian and notion. It does not mint slack, and that asymmetry is deliberate rather than an omission: a profile may hold several workspaces, so there is no single "the token" — the credential is a workspace-to-token map delivered as a file path. Unifying would widen a command that already refuses to run under an agent harness, and it would not have addressed the discoverability failure, whose cause was never that the token could not be printed but that the variable could not be named.

What was fixed instead is the refusal: asking for a service token does not mint now explains why and names the exec form that works. `aws`, `oci`, `github` and `custom` answer the same way. The reasoning lives in the error rather than in a document, because the error is where the reader is standing.

## Mirrors are kept honest by tests, not by abstraction

`plan_env` answers "what would this profile export" without reading a secret; `build_env` answers it by actually reading them. They cannot share code, so nothing but a test forces them to agree on the same key set. The parity test is treated as part of the function rather than as coverage, and each of its rows is checked to be the unique killer of the branch it names — the alternative, a shared declarative source consumed by both, buys less than it costs.
