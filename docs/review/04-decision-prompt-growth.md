# 04 - Follow-Up Prompt Growth (P2)

## Finding

Follow-up prompts could lose the original task context and were less useful when the important
failure details appeared at the end of long verification output.

## Status

Addressed.

## Resolution

- Follow-up prompts now include the original task when provided by the supervisor.
- Long verification output excerpts are tail-focused.
- The existing prompt hard cap remains in place.
- Regression tests cover original task inclusion and tail-focused truncation.

## Residual Risk

The supervisor does not yet include a full history of attempted fixes in follow-up prompts.
No-change detection remains the primary loop guard for repeated ineffective iterations.
