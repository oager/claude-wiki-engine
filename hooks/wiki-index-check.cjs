#!/usr/bin/env node
/*
 * PostToolUse hook (Write|Edit|MultiEdit) for the claude-wiki-engine.
 * Warns when a memory wiki PAGE is written/edited but is NOT yet referenced in MEMORY.md,
 * so plain "save to file" writes don't silently orphan outside the LLM-wiki index.
 * Cross-platform: derives all paths from the written file_path (no hardcoded home). Never blocks.
 * install.py copies this to <config>/hooks/ and registers it in settings.json (PostToolUse).
 */
const fs = require('fs');
try {
  const raw = fs.readFileSync(0, 'utf8') || '{}';
  const data = JSON.parse(raw);
  const ti = data.tool_input || {};
  const fp = ti.file_path || (data.tool_response && data.tool_response.filePath) || '';
  if (!fp) process.exit(0);
  const norm = fp.replace(/\\/g, '/');
  const marker = '/.claude/memory/';
  const idx = norm.indexOf(marker);
  if (idx === -1) process.exit(0);                 // not a memory file
  if (!/\.md$/i.test(norm)) process.exit(0);       // not markdown
  if (norm.includes('/memory/raw/')) process.exit(0); // inbox/archive are exempt
  const base = norm.slice(norm.lastIndexOf('/') + 1);
  const stem = base.replace(/\.md$/i, '');
  const exempt = new Set(['MEMORY.md', 'log.md', 'schema.md', 'overview.md', 'dashboard.md', 'README.md']);
  if (exempt.has(base)) process.exit(0);
  const memRoot = norm.slice(0, idx + '/.claude/memory'.length);
  let indexTxt = '';
  try { indexTxt = fs.readFileSync(memRoot + '/MEMORY.md', 'utf8'); } catch { process.exit(0); }
  const esc = stem.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  if (new RegExp('\\((?:[^)]*/)?' + esc + '\\.md\\)').test(indexTxt)) process.exit(0);
  const msg = 'Wiki: memory/' + base + ' is not referenced in MEMORY.md. If this is a durable '
    + 'knowledge page, index it via /wiki-ingest (MEMORY.md line + tags + Related footer per '
    + 'memory/schema.md). If it is scratch, ignore.';
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: { hookEventName: 'PostToolUse', additionalContext: msg },
    suppressOutput: true
  }));
} catch (_e) {
  process.exit(0); // never break the write on hook error
}
