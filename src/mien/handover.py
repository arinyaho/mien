"""Decide whether `mien exec` may hand a profile's credentials over, here.

`mien exec <profile> -- <cmd>` names its identity explicitly, which is exactly
what makes it the right form for an agent: it does not depend on shell state
that does not survive between calls. The cost is that the name is only as good
as whoever typed it. A human who types the wrong profile sees the result in the
next command; an agent that picks the wrong profile hands a whole credential
bundle to a command running in someone else's repository, and nothing in the
transcript looks unusual.

So this module answers one question, for one moment: an agent is driving, it
asked for profile X, and this place visibly claims profile Y — should the
handover happen? The answer is no, and the refusal is the whole control. There
is deliberately no per-call bypass: an override an agent can reach for is an
override an agent will reach for, which is how the check becomes decoration.

**Why this consults the repository's `origin`, when identity resolution never
does.** Choosing an identity that *acts* (`resolve_profile`, and `mien which` /
`run` above it) considers only your own directory scopes and a `.mien` you have
approved, because a clone controls its own `origin` and could otherwise steer
which identity a command runs as. This check runs in the opposite direction: it
can only ever *block* a handover, never select or grant one. A crafted `origin`
therefore buys an attacker a false refusal — an annoyance — and never a
mis-action. That asymmetry is what already makes `mien guard` legitimate (see
SECURITY.md), and it is why this uses the *display* resolver, `claimed_profile`,
including `owns_remotes`. Using the acting resolver here would make the check a
no-op in practice: most real profiles carry no `default_for` at all and claim
their work entirely through the remotes they own.

**An approved `.mien` outranks all of that.** Approving a declaration is the
user saying, in their own state, that this workspace acts as this profile — the
one signal here that is not a guess about whose place this is. So when the
caller hands one in, it *is* the claim: naming it allows the handover, even in a
repository whose `origin` belongs to someone else (a personal fork of a work
repo, a work checkout inside a personal tree), and naming something else is
refused against the declaration rather than the remote. Without this the gate
would refuse exactly what `which`, `run` and the status line all allow, and its
only remaining advice would be to act as an identity the user did not bind this
workspace to. An *unapproved* `.mien` carries none of that weight and is not
passed in: approval is what turns a checked-out file into a user's decision.

Fail open, always. Every uncertainty — nothing claims this place, two profiles
claim it equally, no repository, no remote, an unreadable config, an unexpected
exception anywhere in here — allows the handover. A bug in a safety check must
cost a missed refusal, never a wedged workflow.
"""

from __future__ import annotations

from collections.abc import Mapping

from mien.config import Profile
from mien.resolve import claimed_profile


def _place(claimed: str, source: str | None) -> str:
    """How this location claims `claimed`, phrased for the person reading it.

    The sources are worth distinguishing: an `origin` owner is a fact about the
    repository in front of you, a `default_for` scope is a rule you wrote, an
    approved `.mien` is a workspace you bound by hand — and they are corrected
    in three different places.
    """
    if source == "declaration":
        return f"this workspace declares {claimed!r} (an approved .mien)"
    if source == "repo":
        return f"this repository belongs to {claimed!r} (its git origin owner)"
    return f"this directory belongs to {claimed!r} (a default_for scope)"


def refusal_reason(
    profiles: Mapping[str, Profile],
    cwd: str,
    requested: str,
    *,
    remote: str | None = None,
    declared: str | None = None,
    agent_driven: bool,
) -> str | None:
    """Why handing `requested`'s credentials over here must be refused, or None.

    Pure: every input is passed in — the config's profiles, the working
    directory, the profile the caller named, the repository's `origin` URL (or
    None), the profile an *approved* `.mien` declares here (or None), and
    whether an agent harness is driving this call. It reads no environment,
    touches no filesystem, touches no backend and spends no credential, so it is
    safe to call before anything is loaded — which is where `exec` calls it.

    Refuses only on a confident, agent-driven mismatch: something claims this
    place, and it is not the profile that was named. Everything else returns
    None, including any exception raised inside this function.
    """
    try:
        # A person at a terminal is never blocked: they can see where they are,
        # and the next command tells them if they were wrong. The check exists
        # for the caller that cannot.
        if not agent_driven:
            return None

        if declared:
            # The user's own binding for this workspace, and therefore the claim:
            # it answers for this place instead of the remote, in both directions.
            if declared == requested:
                return None
            claimed, source = declared, "declaration"
        else:
            claimed, source = claimed_profile(profiles, cwd, remote=remote)
            if not claimed or claimed == requested:
                return None

        return (
            f"refusing to hand over credentials: this call asked for profile "
            f"{requested!r}, but {_place(claimed, source)}.\n"
            "  Nothing ran and no credential was loaded — mien declined the "
            "handover; the command itself did not fail.\n"
            "  Act as the identity this place claims:\n"
            f"    mien exec {claimed} -- <your command>\n"
            f"  If {requested!r} really is the right identity for this work, run "
            f"it somewhere that belongs to {requested!r}."
        )
    except Exception:
        # Fail open on anything at all: an ambiguous scope, a config shape this
        # code did not expect, a bug here. A refusal that is not certain is
        # worse than no refusal — it teaches people to route around the check.
        return None
