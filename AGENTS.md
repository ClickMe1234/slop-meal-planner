# Repository contribution instructions

## Canonical checkout

- This checkout at `C:\GitHub\slop-meal-planner\` is the only active project repository.
- Perform all development, branch creation, commits, pulls, and pushes from this checkout only.
- Before committing or pushing, verify that `git rev-parse --show-toplevel` resolves to `C:\GitHub\slop-meal-planner` and that `git remote get-url origin` returns `https://github.com/ClickMe1234/slop-meal-planner.git`.

## Release metadata

- Every pull request intended for merge must include a Semantic Versioning bump appropriate to its scope.
- Keep the release version synchronized in `VERSION`, `backend/pyproject.toml`, `frontend/package.json`, and the root package entry in `frontend/package-lock.json`.
- Every pull request must add a dated entry at the top of `CHANGELOG.md` describing the user or developer impact.
- Treat a missing version bump or changelog entry as incomplete PR work; validate both before pushing or merging.
