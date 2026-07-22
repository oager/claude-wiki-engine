---
name: error-harden
description: Post-bugfix error hardening checklist — enumerate failure modes, implement auto-handling, add alerts, create/update ERROR_HANDLING.md. Invoke immediately after fixing any bug.
type: skill
---

# /error-harden — Post-Bugfix Error Hardening

Run immediately after fixing any bug, while code context is still fresh.

## Step 1: State the root cause (one sentence)

Write it before touching any code. Forces clarity.

Example: "Redis IV history resets on restart → percentile always 50.0 → risk gate permanently inert."

## Step 2: Enumerate related failure modes

Same code path — what else can go wrong?

- What external dependencies does this touch? (DB, network, disk, process, env var, third-party API)
- What happens if each dependency is unavailable / slow / returns garbage?
- What silent failures exist? (wrong value returned without error, resource leak, infinite loop, stale data)
- What race conditions or restart-state issues exist?

List every failure mode, even unlikely ones.

## Step 3: Classify and handle each — in priority order

Work through A → B → C → D. Stop at the first that applies.

### A. Auto-handle in-process (implement now)

| Pattern | When to use |
|---------|-------------|
| Retry with backoff | Transient network / DB errors |
| Fallback value | Safe default when data unavailable — **must justify why the fallback is safe** |
| Skip with `log.warning` | Non-critical path, continue without it |
| Startup check + abort | Precondition must be true or process should not run (e.g. `_check_ramdisk()`) |
| Circuit break | Stop retrying after N failures, alert once, recover automatically |

### B. Alert (implement now)

If auto-handling is not possible, at minimum alert. Use existing project patterns:

| Mechanism | Use for |
|-----------|---------|
| Discord `_notify()` / `_discord_alert()` | Operator-facing, actionable |
| `log.error` | Picked up by monitoring / log grep |
| `cron_fail.sh` exit code | Cron jobs — non-zero exit triggers the script |
| Startup pre-flight check | Abort + Discord before processing begins |

One alert per failure mode, not one per occurrence — gate with a flag or rate limit.

### C. External check (implement now)

If the failure cannot be detected inside the process:

- Health-check cron (`pgrep` the process, check log recency, `df -h` disk space)
- Watchdog that monitors a heartbeat file
- Dashboard metric that goes stale

### D. Document (if A/B/C all impossible)

Add to `ERROR_HANDLING.md` under "Known Unhandled Failures" with trigger, manual detection steps, and recovery procedure.

## Step 4: Update ERROR_HANDLING.md

**Read the file first.** If the project already has an `ERROR_HANDLING.md`, follow its existing format and structure — do not introduce a generic table schema on top of an established narrative format.

### If the file already exists

- Find the section that owns the component you just hardened.
- Add a dated subsection or bullet block describing: what broke, what the fix does, what alert fires and when, manual recovery steps.
- If the failure is not yet handled (D above), add a row to the Gaps table if one exists, or a "Known Unhandled Failures" section.
- Update the "Last updated:" date at the top.

### If no ERROR_HANDLING.md exists yet (new project)

Location: project root or `docs/ERROR_HANDLING.md`. Use this starter structure:

```markdown
# Error Handling — [Project Name]

Last updated: YYYY-MM-DD

## 1. [First Layer — e.g. Process Resilience]

### [Component name]
- Handling: ...
- Alert: ...
- Recovery: ...

## Gaps (not yet handled)

| Gap | Impact | Priority | Status |
|-----|--------|----------|--------|
```

Use narrative subsections, not a flat registry table — it scales better as the file grows.

## Step 4.5: Promote strategy-independent lessons to the wiki

`ERROR_HANDLING.md` stays project-scoped — most failure modes are repo-specific, keep them there.
But if the root cause is a **strategy-independent engineering lesson** (applies beyond this bot — e.g.
"check all callers when changing a function's return type", "use `print(file=f)` not `f.write` in
scp-deployed scripts"), offer `/wiki-ingest` to file it to the global wiki `concepts/` (gated by the
Cross-Bot Promotion Rule). Do not promote repo-specific handling.

## Step 5: Commit

Commit error-hardening changes separately from the bug fix when possible (clean history).
Use `fix(harden):` or `feat(harden):` prefix.

---

## Rules

- **Write Step 1 before touching any code.** Clarity first.
- **Prefer A > B > C > D** — auto-handle beats alert beats external check beats document.
- **Fallback values must be explicitly safe.** Justify in a comment why the fallback cannot cause harm.
- **One alert per failure mode, not one per occurrence.**
- **Always update ERROR_HANDLING.md** — even for fully auto-handled failures. The registry is for the next developer, not just for open failures.
- **Do not gold-plate.** A `log.warning` + doc row beats spending 2 hours on a perfect circuit breaker for a once-a-year edge case.
