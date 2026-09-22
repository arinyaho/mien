# Contributing

## Running tests

```bash
uv run pytest
```

Fast, no network required.

## Invariants a PR must not break

These come from [CLAUDE.md](CLAUDE.md):

- **Activation is stateless.** Environment set by `mien use` doesn't survive
  past the shell it was set in. Code and docs must not assume a profile
  stays active across invocations.
- **Wrong identity is the failure mode that matters.** Prefer designs that
  fail loudly over designs that fall back to a default.
- **Secrets never reach argv, history, or a transcript.** Read them through
  the hidden prompt, `--secret-cmd`, or stdin — never paste a literal.
- **No real-world identifiers in the repository.** No employer or client
  names, no personal email addresses, no project IDs, no secret names — in
  code, tests, fixtures, docs, or commit messages.
- **Configuration comes from the user's own config, never from a
  checked-out repository.** A cloned repo must not influence which identity
  acts on the machine.

## Design rationale

The reasoning behind non-obvious decisions — rejected alternatives,
non-goals, what's deliberately out of scope — lives in
[docs/design-rationale.md](docs/design-rationale.md).

## Opening an issue

File it on this repository's [GitHub Issues](https://github.com/arinyaho/mien/issues).
`good-first-issue` marks tasks that are small and well-scoped for a first
contribution.
