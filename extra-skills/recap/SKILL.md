---
name: recap
description: Generate a paste-ready handoff markdown file summarizing the current session's work. For sharing with Ubuntu/Linux Claude (CryptoDesk side) or any other Claude session that needs to catch up on what Windows Claude has been doing. Saves the file to Downloads so it's easy to paste.
disable-model-invocation: true
---

# /recap — session handoff document

Generates a handoff markdown the user can drop into another Claude session (most commonly the Ubuntu Claude running alongside CryptoDesk, but works for any cold session that needs today's context).

## Flow

### 1. Gather source material (read-only — no edits)

Pull from these in order:

```
Read ~/.claude/projects/C--Users-oager-claude-workspaces/memory/SESSION_RESUME.md
Read C:\Users\oager\claude-workspaces\cryptobot\state\current_setups.md
```

Then get recent cryptobot activity to see what's been pushed:

```
Bash: cd "$USERPROFILE/claude-workspaces/cryptobot" && git log --oneline -10
Bash: cd "$USERPROFILE/tradingview-mcp" && git log --oneline -5 --all
```

If this session has notable debugging findings that haven't been committed yet, also peek at recent memory changes:

```
Bash: ls -lt "$USERPROFILE/.claude/projects/C--Users-oager-claude-workspaces/memory/" | head -5
```

### 2. Check live state (optional, only if TV is up)

If `tv_health_check` succeeds, also pull current alert count + any that fired recently:

```
mcp__tradingview__alert_list
```

Note fired alerts and what happened next. This is valuable context for the recap.

### 3. Structure the recap

Aim for **100-200 lines of markdown**, paste-friendly, readable in 2 minutes. Use this skeleton:

```markdown
# Recap from Windows Claude session — [YYYY-MM-DD]

**TL;DR**: [one sentence — what's the most important thing to know]

## What to do first

```bash
cd ~/crypto-trading-bot
git pull origin main
cat CLAUDE.md
cat state/current_setups.md
```

That's the full context. What follows is the highlight reel.

## What happened this session

[2-4 bullet points of the key work — setups identified, alerts created, bugs fixed, tools built]

## Macro regime (most recent read)

[Pull current values or cite the SESSION_RESUME read — flag as stale if > 4 hours old]

## Active setups snapshot

[Table with symbol, side, zone, entry, SL, TP1/2/3, status]

[Call out which are CryptoDesk-scope (BTC/ETH) vs Windows-scope (alts)]

## Alert book

[List the TV alerts + their triggers]

[Note any that fired in this session and what we decided]

## Priority protocol reminder

[One short section restating the rules from CLAUDE.md]

## One thing that would help

[Actionable ask for the Linux side — usually a cron line or a code check]

## Hard rules unchanged

[Restate: user-gated trade execution, advisory-only state, strategy canon protection]
```

Copy the prose style from `Downloads\windows_claude_recap_2026-04-18.md` — that's the reference format, tested and used successfully.

### 4. Save to Downloads with dated filename

```
Write C:\Users\oager\Downloads\windows_claude_recap_YYYY-MM-DD.md
```

Use today's date. If a recap with today's date already exists, append a `-2`, `-3`, etc. suffix rather than overwriting (user may want to compare versions).

### 5. Report

One-line confirmation:

```
Recap saved to C:\Users\oager\Downloads\windows_claude_recap_YYYY-MM-DD.md
Paste that into Ubuntu Claude or any cold session. [N] lines, [token estimate] tokens.
```

## What to include vs what to cut

**Include**:
- New setups (symbol + zone + entry + SL + TPs, abbreviated)
- Alert changes (what fired, what was added/deleted)
- Macro regime read with implication
- Infrastructure changes that affect the other side (repo patches, cron recommendations, shared ledger updates)
- Anything that's "changed since last recap" — diff, not full state

**Cut**:
- Tool-invocation details ("I called chart_set_symbol then...") — noise
- Full commit diffs — link to the commit hash instead
- Strategy KB quotes — the other Claude can read the KB itself
- Anything already in `state/current_setups.md` verbatim — point there instead
- Speculation and "what if" — keep to decisions made

## Don't

- **Don't write the recap into the cryptobot repo.** It's an ephemeral handoff doc, not a committed artifact. Downloads is the right place.
- **Don't commit anything as part of /recap.** Reading and summarizing only. Any commits should be done explicitly via `/ship` or `/sync`.
- **Don't duplicate the full active_setups memory file.** The recap is a summary + pointer, not a copy.
- **Don't write private info** (cookies, session IDs, exchange API keys) into the recap — it's going to be pasted into another session and might end up in logs or exports.

## Common follow-up

After saving, user typically opens the file, pastes content into the target session, and continues there. If the target session is set up with the same `CLAUDE.md` discipline, it can just `git pull` the cryptobot repo and be caught up — the recap is bridging context, not replacing it.
