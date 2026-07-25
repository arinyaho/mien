import pytest

from mien.cli import _CAPTURE_MARKERS


@pytest.fixture(autouse=True)
def _no_capture_context(monkeypatch):
    """Neutralize agent-harness markers for every test.

    `mien token` refuses to print a secret when it detects a harness that records
    stdout. The test suite is frequently *run* from inside such a harness, so
    without this the same test would pass locally and fail under an agent — the
    behaviour under test would depend on who invoked pytest. Tests that exercise
    the refusal set a marker explicitly.

    `MIEN_TOKEN` is cleared for the mirror-image reason: it *disarms* the
    refusal, so an ambient `MIEN_TOKEN=capture-ok` would silently turn the
    refusal tests green-by-default.
    """
    for marker in (*_CAPTURE_MARKERS, "MIEN_TOKEN"):
        monkeypatch.delenv(marker, raising=False)
