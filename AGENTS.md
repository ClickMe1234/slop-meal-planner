# Agent workflow

- Before changing the repository, read the root [CODEBASE_MAP.md](CODEBASE_MAP.md).
  It is the maintained orientation guide for the product features, frontend
  routes, API modules, domain model, services, runtime/deployment paths,
  migrations, tests, security boundaries, and safe change patterns. Use it to
  locate the nearest code and test, then verify details against the source.
- When an architectural, feature, workflow, deployment, or migration change
  makes that guide inaccurate, update CODEBASE_MAP.md in the same change.

- Use the current Codex agent directly for implementation work unless the user explicitly requests delegation or a multi-agent workflow.
- Do not require the `sol-luna-router` skill or a separate reasoning-level confirmation before starting implementation.

## Versioning and releases

- Treat a requested application release or version bump as a SemVer release.
  The `VERSION` file is the source of truth; use `MAJOR.MINOR.PATCH` (so this
  requested 1.4 release is `1.4.0`).
- For every application release, update `VERSION`, frontend `package.json` and
  lockfile, backend `pyproject.toml`, backend default API/user-agent versions,
  README, CHANGELOG, and immutable deployment-image references together. Add a
  dated release entry that describes the user-visible change.
- Run the release-metadata test before opening the PR. Do not leave a version
  bump only in a package manifest or rely on a container tag to imply it.

## UI implementation

- Match the existing visual language before inventing a new pattern. Reuse the
  primitives in `frontend/src/components/ui.tsx` (`Button`, `Card`, `Badge`,
  `PageHeader`, `Notice`, `EmptyState`, `Loading`, and `Segmented`), Lucide
  icons, and the colour, spacing, type, radius, and shadow variables in
  `frontend/src/styles.css`. Add a shared primitive or reusable class when a
  pattern will appear more than once.
- Keep pages visually consistent with their neighbours: use the established
  page widths, headers, cards, form controls, action rows, loading/empty/error
  states, and light/dark themes. Preserve the project's warm, restrained visual
  style and responsive PWA layout instead of introducing an isolated design
  system.
- Check every changed UI at desktop and at representative mobile viewport
  dimensions, not width alone: at minimum 320 x 568, a common phone size such
  as 390 x 844, and landscape such as 844 x 390. Also exercise the project's
  760 px and 430 px breakpoints. Check the available height with the fixed top
  and bottom navigation, safe-area insets, modals, and the on-screen keyboard;
  content and primary actions must remain visible, reachable, and scrollable.
- Use wrapping or scrolling for action groups and `min-width: 0` on shrinking
  flex/grid children. Long user and recipe text must wrap or use deliberate
  ellipsis; labels, values, badges, buttons, and icons must not overlap, clip,
  disappear, or force horizontal page scrolling. Do not solve mobile density
  by silently hiding an action the user still needs.
- Keep controls accessible and touch-friendly. Prefer real buttons, links,
  inputs, and forms; give icon-only controls an `aria-label`, decorative icons
  `aria-hidden`, and stateful controls the appropriate `aria-*` state. Retain
  visible keyboard focus, logical tab order, sufficient contrast in both
  themes, and the existing approximately 44 px touch-target convention.
- Every new interactive element must be wired to a real outcome when it is
  introduced: navigate, submit, mutate state/data, open or close a controlled
  surface, or perform the stated browser action. Do not add placeholder buttons,
  empty handlers, `href="#"`, or controls that only look interactive. If the
  behavior is not implemented, omit the control or render it explicitly
  disabled with an explanation.
- Give interactions complete states. Prevent duplicate async submissions,
  disable controls only when the reason is valid, show progress while work is
  pending, surface success or actionable failure, and restore a usable state
  after errors. In demo mode, controls that are shown must still produce a
  meaningful local result or clearly explain why the live action is unavailable.
- Add or update the nearest React Testing Library/Vitest test for behavior, not
  merely presence: click or submit the control and assert the resulting route,
  visible state, API call, or side effect. For layout-sensitive changes, run the
  production build and inspect the affected page at desktop and mobile sizes;
  tests alone do not catch clipping or overflow.
