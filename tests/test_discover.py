import subprocess

from mien.config import AWSService, GitHubService, GoogleService, OCIService, Profile
from mien.discover import (Found, discover_aws, discover_gcloud, discover_github,
                           discover_oci, render_report)


def test_discover_aws_reads_config_and_credentials(tmp_path):
    aws = tmp_path / ".aws"
    aws.mkdir()
    (aws / "config").write_text(
        "[default]\nregion = us-east-1\n[profile work]\nregion = us-west-1\n")
    (aws / "credentials").write_text("[personal]\naws_access_key_id = AKIA\n")
    names = {f.identifier for f in discover_aws(tmp_path)}
    assert names == {"default", "work", "personal"}


def test_discover_oci_reads_sections(tmp_path):
    oci = tmp_path / ".oci"
    oci.mkdir()
    (oci / "config").write_text("[DEFAULT]\nuser = ocid1\n[work]\nuser = ocid2\n")
    assert {f.identifier for f in discover_oci(tmp_path)} == {"DEFAULT", "work"}


def test_discover_gcloud_reads_configurations(tmp_path):
    conf = tmp_path / ".config" / "gcloud" / "configurations"
    conf.mkdir(parents=True)
    (conf / "config_default").write_text("[core]\naccount = me@acme.example\n")
    (conf / "config_side").write_text("[core]\naccount = me@side.example\n")
    found = sorted(discover_gcloud(tmp_path), key=lambda f: f.identifier)
    assert [(f.identifier, f.detail) for f in found] == [
        ("default", "me@acme.example"), ("side", "me@side.example")]


def test_discover_github_parses_gh_auth_status():
    out = ("github.com\n"
           "  ✓ Logged in to github.com account octocat (keyring)\n"
           "  ✓ Logged in to github.com account octo-work (keyring)\n")
    fake = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out, stderr="")
    names = {f.identifier for f in discover_github(fake)}
    assert names == {"octocat", "octo-work"}


def test_discover_github_absent_gh_is_silent():
    def missing(*a, **k):
        raise FileNotFoundError
    assert discover_github(missing) == []


def test_render_report_marks_bound_and_unbound():
    found = [
        Found("github", "octocat", "github.com"),
        Found("github", "octo-work", "github.com"),
        Found("aws", "work"),
    ]
    profiles = {
        "personal": Profile(name="personal",
                            github=GitHubService(username="octocat",
                                                 host="github.com", token_ref="r")),
    }
    report = render_report(found, profiles)
    assert "✓ octocat (github.com) — in a mien profile" in report
    assert "· octo-work (github.com) — not imported" in report
    assert "mien login <profile> --service github --username octo-work" in report
    assert "· work — not imported" in report
    assert "--service aws --aws-profile work" in report


def test_render_report_empty():
    assert "No local" in render_report([], {})
