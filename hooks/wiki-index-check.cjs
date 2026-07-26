#!/usr/bin/env node
/*
 * PostToolUse hook (Write|Edit|MultiEdit) for the claude-wiki-engine.
 * Warns when a memory wiki PAGE is written/edited and either:
 *   (a) it is NOT referenced in MEMORY.md — so plain "save to file" writes don't silently orphan
 *       the page outside the LLM-wiki index; or
 *   (b) its frontmatter is missing `tags:`/`updated:`, or nests them under a `metadata:` key —
 *       either way the page is silently dropped from every frontmatter query (e.g. Dataview).
 * (b) added in v0.4.0: that failure is invisible, and the periodic lint that catches it
 * (/doc-review Pass G) may run only occasionally — silent failure + rare check = worth a
 * write-time warning. Rules whose failure is LOUD stay with lint.
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

  const warnings = [];

  // --- (a) indexed in MEMORY.md? ---
  let indexTxt = '';
  try { indexTxt = fs.readFileSync(memRoot + '/MEMORY.md', 'utf8'); } catch { /* no index */ }
  if (indexTxt) {
    const esc = stem.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    if (!new RegExp('\\((?:[^)]*/)?' + esc + '\\.md\\)').test(indexTxt)) {
      warnings.push(rel + ' is not referenced in ' + (path.basename(memRoot) || 'the wiki')
        + '/MEMORY.md. If this is a durable knowledge page, index it via /wiki-ingest (MEMORY.md '
        + 'line — under the right ## section if the index is sectioned — plus tags and a Related '
        + 'footer per schema.md). If it is scratch, ignore.');
    }
  }

  // --- (b) query-critical frontmatter ---
  let pageTxt = '';
  try { pageTxt = fs.readFileSync(fp, 'utf8'); } catch { /* unreadable; skip this check */ }
  if (pageTxt) {
    const fm = /^---\r?\n([\s\S]*?)\r?\n---/.exec(pageTxt);
    if (!fm) {
      warnings.push(rel + ' has no YAML frontmatter — it is invisible to every frontmatter query. '
        + 'Add name/description/type/tags/updated per schema.md.');
    } else {
      const body = fm[1];
      const has = (k) => new RegExp('^' + k + ':', 'm').test(body);
      const missing = ['tags', 'updated'].filter((k) => !has(k));
      if (/^metadata:/m.test(body) && missing.length) {
        warnings.push(rel + ' nests its frontmatter under a `metadata:` key. Queries read those as '
          + '`metadata.*`, so tags/updated/type are ALL invisible — the page silently drops out of '
          + 'every tag and sort-by-updated query. Un-nest to top level per schema.md.');
      } else if (missing.length) {
        warnings.push(rel + ' is missing top-level `' + missing.join('`, `') + '` in frontmatter — '
          + 'a page without those is silently dropped from queries (dates absolute YYYY-MM-DD).');
      }
    }
  }

  if (!warnings.length) process.exit(0);

  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PostToolUse',
      additionalContext: 'Wiki: ' + warnings.join(' | ')
    },
    suppressOutput: true
  }));
} catch (_e) {
  process.exit(0); // never break the write on hook error
}
