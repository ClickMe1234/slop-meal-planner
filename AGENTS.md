# Repository contribution instructions

## Release metadata

- Every pull request intended for merge must include a Semantic Versioning bump appropriate to its scope.
- Keep the release version synchronized in `VERSION`, `backend/pyproject.toml`, `frontend/package.json`, and the root package entry in `frontend/package-lock.json`.
- Every pull request must add a dated entry at the top of `CHANGELOG.md` describing the user or developer impact.
- Treat a missing version bump or changelog entry as incomplete PR work; validate both before pushing or merging.
