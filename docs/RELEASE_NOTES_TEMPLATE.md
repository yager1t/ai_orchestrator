# GitHub Release Notes Template

Use this template for every GitHub Release. Keep the notes useful for someone
who has not followed the development thread.

```markdown
## vX.Y.Z - Short Release Theme

Release date: YYYY-MM-DD

One short paragraph explaining the release theme and why it matters.

### Highlights

- Added/changed the main user-facing capability.
- Added/changed the main operator or automation capability.
- Added/changed the main safety, durability, or compatibility behavior.

### Operator impact

Explain what a local operator can do after this release that was harder or not
possible before. Mention the most important commands when relevant.

### Documentation and contracts

- List new or updated docs.
- List stable JSON/API/CLI contracts if the release changes automation
  behavior.
- List compatibility or migration expectations.

### Safety notes

Call out approval, sandbox, policy, redaction, or destructive-action behavior.
If the release has no safety-sensitive changes, write: No safety-sensitive
behavior changes.

### Verification

- Local checks run before tagging.
- GitHub Actions status.
- Publishing status, when applicable.

Full diff: https://github.com/yager1t/ai_orchestrator/compare/vPREVIOUS...vX.Y.Z
```

## Minimum Quality Bar

- The title includes the version and a human-readable release theme.
- The first paragraph explains why the release exists, not only what changed.
- Highlights cover the important product, operator, and safety/durability
  changes.
- Any new stable JSON, CLI, docs, policy, sandbox, or state-store behavior is
  named explicitly.
- Verification names the checks actually run; do not imply checks that were not
  executed.
- The full diff link points from the previous release tag to the new tag.
