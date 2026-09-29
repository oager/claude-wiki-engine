---
key: <owner-repo>
repo: <owner/repo>
type: <trading-bot | web-app | static-site | workspace>
updated: <YYYY-MM-DDTHH:MMZ>
updated_by: <hostname>
repo_sha: <repo_sha from close.py>
vault_sha: <vault_sha from close.py>
---
# Handoff: <key>

## Next up
_Rewritten every /sync. Ranked, max 5; item 1 = where the next session starts._
1.

## Warnings
none

## Current state

## Open items

## Profile
```json
{}
```
<!-- Profile shape (every key optional; /preflight and /sync read only these):
  "gh": "owner/repo"      GitHub repo for PR/CI state, when it differs from origin
  "shared": true          publish .claude/HANDOFF.md for collaborators
  "services": [{"unit": "name", "scope": "user|system", "host": "logical-host", "deploys_from_repo": true}]
  "health":   [{"url": "http://localhost:8080/health", "expect": "text in the body", "host": "logical-host"}]
  "ports":    [{"port": 8080, "owner": "process name", "host": "logical-host"}]
  "queues":   [{"name": "label", "file": "path", "count": "regex, default ^- "}]
  "logs":     [{"path": "logs/app.log", "max_age_h": 24}]
  "metrics":  [{"name": "label", "file": "state.json", "key": "dotted.key"}]
  Relative paths are from the repo root. `host` is omitted for this machine; unit, url and host must not start with "-". -->

## Standing notes

## Last session
