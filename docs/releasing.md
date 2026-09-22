# Cutting a release

1. Bump `VERSION` (and every file it must stay in sync with —
   `uv run pytest` fails `test_version_in_sync_across_all_manifests` if one
   is missed) and merge that PR to `main`.
2. As the last step of merging that PR, or immediately after, tag the bump
   commit: `git tag vX.Y.Z <bump-commit-sha> && git push origin vX.Y.Z`.
3. `.github/workflows/release.yml` creates the GitHub Release from that tag
   automatically, with notes generated from the merged PRs since the
   previous tag. Verify it landed: `gh release view vX.Y.Z`.

The tag is the point of no return — pushing it publishes a release with no
review step in between. Don't push the tag until the bump PR is actually
merged and you're ready for it to ship.
