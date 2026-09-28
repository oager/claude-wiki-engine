---
name: preflight
description: Session startup — sync the memory vault, load memory (per-project state + the global wiki index), orient on the current project's state, and give a short briefing. Run at the start of a new working session. Read-only.
disable-model-invocation: true
---

# Preflight — Session Startup

Boot sequence for a new session: pull the latest memory, load context, check where the project
stands, and give a concise orientation briefing. This is **read-only** — it never modifies files.

## Steps

### 0. Sync the memory vault (across machines)
- Detect the config/vault path: `~/.claude/` on Linux/macOS, `%USERPROFILE%\.claude\` on Windows.
- `git -C <vault> pull --ff-only` to pull the latest memory from other machines. If it fails or
  conflicts, report and continue — never block the session.
- **Vault-health check (around the pull):** if the vault is a shared tree that an auto-commit tool
  (e.g. Obsidian-git) also writes to, it can wedge. Before trusting the pull, detect a stuck state:
  - `git -C <vault> status --porcelain` shows unmerged entries (`UU`/`AA`/`DU`…), OR
    `<vault>/.git/MERGE_HEAD` exists → the repo is **stuck mid-merge**; until it's cleared, no machine
    can pull or push and memory sync is frozen.
  - Surface it under a `⚠ Vault:` line in the report and offer to finish the merge. Do **NOT** silently
    `reset --hard` / `push --force` (destroys concurrent sessions' work) — resolve the offending file
    and `commit --no-edit`.

### 1. Load memory (read, don't modify)
- **Per-project memory:** if the project keeps a session-state file (`<project-memory>/SESSION_RESUME.md`),
  read it for current state. Otherwise read the project's `MEMORY.md` index and open the entries most
  relevant to today's work.
- **Global wiki index:** read `<vault>/memory/MEMORY.md` (catalog only — one line per page). It is
  path-independent (identical on every machine after Step 0's pull), so it orients you across projects
  even if Claude was launched from the wrong folder. Open individual wiki pages only when directly
  relevant. (Page bodies, `overview.md`, and project docs are the heavier `preflight-deep` variant —
  keep this boot fast: the index is a few KB; bodies are the expensive part.)

### 2. Orient on the project
- `git -C <project> status --short` + the last few commits — what changed recently, anything
  uncommitted or mid-flight?
- Read whatever state/log the project uses to show progress (a status file, a recent run log).
  **Freshness assert:** if the newest state timestamp is >24h behind the clock, flag it as
  **stale** and do NOT report old figures as current (a process may be wedged even if it looks alive).
- If the project tracks open review items or TODOs, count the open ones and list them. If none, skip.
- **Remote projects (SSH nodes):** if the work actually runs on a remote box you connect to — the way
  the team works on **node 1** / **node 2** over SSH — run these checks *over that SSH connection*, not
  locally: the processes (`systemctl is-active <svc>` / `ps`), the logs (`tail`), and the state files
  live on the node. Compare freshness against the **node's** clock (`ssh <node> date -u`), not your
  laptop's. Configure your `node1` / `node2` SSH access first (see the Quantum-connect setup); a running
  service whose newest state is hours stale is the signal that matters most here.

### 3. Report
Concise briefing (10–15 lines max):
```
PREFLIGHT — {project} — {timestamp}
━━━━━━━━━━━━━━━━━━━━━━
State:    {current phase from SESSION_RESUME / recent work}
Repo:     {clean / N uncommitted · last commit}
Recent:   {notable recent activity — or "nothing unusual"}
Open:     {N open review/TODO items — or omit line if none}
⚠ Vault:  {stuck-merge / frozen-sync warning — or omit line if clean}
━━━━━━━━━━━━━━━━━━━━━━
Ready. {one suggestion for what to look at first, or "no action needed"}
```

## Rules
- READ ONLY — don't modify any files.
- Keep it concise — the goal is to orient quickly, not read an essay.
- Flag anything that needs attention (stuck vault, stale state, mid-flight work).
- If this is the very first session (no `SESSION_RESUME` / empty memory), say so and suggest running
  `/sync` after getting set up.
