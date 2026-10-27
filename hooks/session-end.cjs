#!/usr/bin/env node
/*
 * SessionEnd hook for the claude-wiki-engine session tools.
 * On exit, marks this session's entry in the live registry (handoffs/.live/) ended so other sessions stop listing it
 * under "Also open here"; an ended entry is deleted after 12 h. On /clear or /resume it does nothing (the process
 * lives on; close.py keeps the entry so the focus carries over). The desktop Code tab sends "other" on /clear and
 * starts a new process: `close.py session refresh` (run by /sync) adopts the ended entry and its focus. No-op when the session tools are not installed. Never blocks the exit: every
 * failure is swallowed. Claude Code kills SessionEnd hooks after 1.5 s by default
 * (CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS); a killed or missed run only means the entry is pruned lazily by the
 * next session of that project.
 * install.py copies this to <config>/hooks/ and registers it in settings.json (SessionEnd).
 */
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
try {
  const closePy = path.join(__dirname, '..', 'tools', 'session', 'close.py');
  if (!fs.existsSync(closePy)) process.exit(0);
  const input = fs.readFileSync(0, 'utf8') || '{}';
  for (const py of ['python3', 'python']) {
    const r = spawnSync(py, [closePy, 'session', 'end'], { input, stdio: ['pipe', 'ignore', 'ignore'], timeout: 8000 });
    if (!r.error && r.status === 0) break;
  }
} catch (_e) {}
process.exit(0);
