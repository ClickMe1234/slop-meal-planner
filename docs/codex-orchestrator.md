# Codex implementation orchestrator

This repository uses a coordinator-and-workers workflow for implementation:

```text
user request
    -> Sol Medium coordinator
        -> independent Luna Max implementation subagents
        -> coordinator review and integration
        -> coordinator tests and final verification
```

The coordinator owns the overall task, reads `CODEBASE_MAP.md`, decomposes the
work, assigns disjoint file scopes, reviews returned changes, resolves any
conflicts, and runs the final checks. Workers are used for bounded slices such
as a backend service plus its tests, a frontend page plus its tests, or an
independent review. Workers should edit their forked workspace directly and
report changed files and validation results.

## Starting a task

In Codex, select:

- Coordinator model: `gpt-5.6-sol`
- Coordinator reasoning effort: `medium`
- Worker model: `gpt-5.6-luna`
- Worker reasoning effort: `max`

Then send your normal implementation request in this repository. The root
`AGENTS.md` contains the durable delegation policy that the coordinator and
workers read, so you do not need to repeat the orchestration instructions.
When a session starts from the CLI, the equivalent command is:

```sh
codex --model gpt-5.6-sol -c model_reasoning_effort=medium
```

If the installed Codex CLI does not expose that flag, set the same values in
the model and reasoning controls in the Codex UI or user configuration. The
coordinator selects `gpt-5.6-luna` and `max` when spawning each worker. Model
selection is session-level; it is not a setting the application itself can
enforce through source code.

## Delegation rules

Use subagents when the work can be split into independent, reviewable slices.
Keep tightly coupled decisions and integration in the coordinator. Every
delegated brief should name the exact goal, relevant files, write scope,
acceptance criteria, and required tests. The coordinator should wait only when
the result is needed for the next critical-path step, then inspect the actual
diff before proceeding.
