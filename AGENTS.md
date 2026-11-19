# SignalScout agent instructions

## Coding guidelines

- State assumptions that affect the outcome. Ask when the answer would materially change the implementation.
- Choose the simplest implementation that fully solves the task. Reuse existing code and conventions.
- Keep edits scoped to the request. Match surrounding style and remove code made unused by your changes.
- Define how you'll verify success. Reproduce bugs when practical and run the checks that exercise the changed behavior.

## Agent skills

### Frontend and UI

Use `impeccable:impeccable` when designing, building, reviewing, or polishing frontend and UI work. Verify rendered changes at the supported screen sizes.

### Issue tracker

Use GitHub Issues for SignalScout specs and tickets. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default Matt Pocock triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

Use the single-context glossary and ADR layout. See `docs/agents/domain.md`.
