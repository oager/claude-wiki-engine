#!/usr/bin/env node
/*
 * PostToolUse hook (Write|Edit|MultiEdit) for the claude-wiki-engine.
 * Warns when a memory wiki PAGE is written/edited but is NOT yet referenced in MEMORY.md,
 * so plain "save to file" writes don't silently orphan outside the LLM-wiki index.
 * Config-adaptive: finds the wiki root by walking up from the written file to the nearest ancestor
 * that has a MEMORY.md index -- so it works for a global ~/.claude/memory, a repo-vendored wiki, a
 * project-scoped .claude/projects/<slug>/memory, or any custom --memory path, with no hardcoded
 * location. Cross-platform (no hardcoded home). Never blocks.
 * install.py copies this to <config>/hooks/ and registers it in settings.json (PostToolUse).
 */
const fs = require('fs');
const path = require('path');
try {
  const raw = fs.readFileSync(0, 'utf8') || '{}';
  const data = JSON.parse(raw);
  const ti = data.tool_input || {};
  const fp = ti.file_path || (data.tool_response && data.tool_response.filePath) || '';
  if (!fp) process.exit(0);
  const norm = fp.replace(/\\/g, '/');
  if (!/\.md$/i.test(norm)) process.exit(0);       // not markdown
  // Find the wiki root: nearest ancestor dir containing a MEMORY.md index. This is the wiki's
  // stable signature, so the hook adapts to wherever memory is configured instead of matching a
  // fixed '/.claude/memory/' path.
  let memRoot = '';
  const parts = norm.split('/');
  for (let k = parts.length - 1; k >= 1; k--) {
    const dir = parts.slice(0, k).join('/');
    try { if (fs.existsSync(dir + '/MEMORY.md')) { memRoot = dir; break; } } catch (_e) {}
  }
  if (!memRoot) process.exit(0);                    // not inside a wiki (no MEMORY.md ancestor)
  const rel = norm.slice(memRoot.length + 1);
  if (rel === 'raw' || rel.startsWith('raw/')) process.exit(0); // inbox/archive are exempt
  const base = norm.slice(norm.lastIndexOf('/') + 1);
  const stem = base.replace(/\.md$/i, '');
  const exempt = new Set(['MEMORY.md', 'log.md', 'schema.md', 'overview.md', 'dashboard.md', 'README.md']);
  if (exempt.has(base)) process.exit(0);
  let indexTxt = '';
  try { indexTxt = fs.readFileSync(memRoot + '/MEMORY.md', 'utf8'); } catch { process.exit(0); }
  const esc = stem.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  if (new RegExp('\\((?:[^)]*/)?' + esc + '\\.md\\)').test(indexTxt)) process.exit(0);
  const msg = 'Wiki: ' + rel + ' is not referenced in ' + (path.basename(memRoot) || 'the wiki')
    + '/MEMORY.md. If this is a durable knowledge page, index it via /wiki-ingest (MEMORY.md line + '
    + 'tags + Related footer per schema.md). If it is scratch, ignore.';
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: { hookEventName: 'PostToolUse', additionalContext: msg },
    suppressOutput: true
  }));
} catch (_e) {
  process.exit(0); // never break the write on hook error
}
