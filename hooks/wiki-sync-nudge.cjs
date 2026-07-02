#!/usr/bin/env node
/*
 * Stop hook for the claude-wiki-engine.
 * ONCE per session, gently nudges a /wiki-sync review before wrapping up, so durable knowledge gets
 * offered for ingest. Loop-safe (honors stop_hook_active) and low-noise (a tmp flag fires it once).
 * If the session was routine, Claude is told to just say so and stop. Disable with WIKI_SYNC_NUDGE=off.
 * install.py copies this to <config>/hooks/ and registers it in settings.json (Stop).
 */
const fs = require('fs');
const os = require('os');
try {
  if (process.env.WIKI_SYNC_NUDGE === 'off') process.exit(0);
  const raw = fs.readFileSync(0, 'utf8') || '{}';
  const d = JSON.parse(raw);
  if (d.stop_hook_active) process.exit(0);            // already continuing from a stop hook -> never loop
  // Key the once-per-session flag on session_id, falling back to the per-session transcript_path so
  // sessions without a session_id don't all collide on a shared 'default' flag (which would fire the
  // nudge only once ever until tmp clears, instead of once per session). Keep the unique tail.
  const seed = d.session_id || d.transcript_path || 'default';
  const sid = String(seed).replace(/[^a-z0-9]/gi, '_').slice(-40) || 'default';
  const flag = `${os.tmpdir()}/.wiki_sync_nudge_${sid}`;
  if (fs.existsSync(flag)) process.exit(0);           // already nudged once this session
  try { fs.writeFileSync(flag, '1'); } catch (_e) {}
  process.stdout.write(JSON.stringify({
    decision: 'block',
    reason: 'Session checkpoint (once): if this session produced DURABLE, reusable knowledge '
      + '(a lesson, decision, root cause, or fact worth reusing), run /wiki-sync to review and offer '
      + 'ingest candidates. If it was routine/ephemeral, just say there is nothing to ingest and stop.'
  }));
} catch (_e) {
  process.exit(0); // never trap the session on a hook error
}
