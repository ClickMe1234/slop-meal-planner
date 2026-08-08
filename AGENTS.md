# Agent workflow

## Sol planning and Luna execution

- For change, build, fix, refactor, or other implementation requests, use the
  `sol-luna-router` skill by default: Sol owns planning, decomposition, decisions,
  supervision, verification, and final acceptance; Luna performs the concrete
  searches, edits, and worker-owned tests.
- Before beginning an applicable request, ask the user which Sol planning reasoning
  level to use: `low`, `medium`, `high`, `xhigh`, `max`, or `ultra`. Do not begin the
  plan or launch Luna until the user answers. This question is required even when a
  default could otherwise be inferred.
- Follow the skill's bounded ownership and independent-verification workflow. Use its
  separate Luna CLI runner when native Sol-to-Luna spawning is incompatible.
- Do not apply this workflow to simple questions, explanations, status checks, or
  read-only requests that do not need implementation.

