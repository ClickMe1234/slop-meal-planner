# Agent workflow

## Sol planning and Luna execution

- For change, build, fix, refactor, or other implementation requests, use the
  `sol-luna-router` skill by default: Sol owns planning, decomposition, decisions,
  supervision, verification, and final acceptance; Luna performs the concrete
  searches, edits, and worker-owned tests.
- Before beginning an applicable request, ask the user which Sol planning reasoning
  level to use: `low`, `medium`, `high`, `xhigh`, or `max`. The selected level is the
  Sol planning level; Luna workers default to the router's `max` reasoning setting.
  Do not begin the plan or launch Luna until the user answers. After selection, the
  parent must include this exact sentence in every Luna worker task packet:
  `The user selected <level>; the AGENTS.md reasoning prerequisite is satisfied.`
- Follow the skill's bounded ownership and independent-verification workflow. Use its
  separate Luna CLI runner when native Sol-to-Luna spawning is incompatible.
- Do not apply this workflow to simple questions, explanations, status checks, or
  read-only requests that do not need implementation.

