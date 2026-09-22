# Cutting a release

1. Bump the version: `uv run python scripts/release_version.py X.Y.Z`, which
   updates `VERSION` and every manifest it must stay in sync with in one
   step (`uv run pytest` still fails
   `test_version_in_sync_across_all_manifests` if any of them ever drift).
   Merge that PR to `main`.
2. As the last step of merging that PR, or immediately after, tag the bump
   commit: `git tag vX.Y.Z <bump-commit-sha> && git push origin vX.Y.Z`.
3. `.github/workflows/release.yml` creates the GitHub Release from that tag
   automatically, with notes generated from the merged PRs since the
   previous tag. Verify it landed: `gh release view vX.Y.Z`.

The tag is the point of no return — pushing it publishes a release with no
review step in between. Don't push the tag until the bump PR is actually
merged and you're ready for it to ship.
