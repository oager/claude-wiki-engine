---
name: tiered-build
description: "Three-model build pipeline routing design, spec/verification, and implementation to cost-appropriate models with hard gates (Fable design, Opus spec+verify, Sonnet build). Trigger on 'tiered build', 'run my pipeline', 'design-then-build', /tiered-build, or handing over a design doc to take to the next phase."
---

# Tiered Build Pipeline

This skill encodes a three-model build workflow. Each model does the part it's
best suited for, and the handoff between phases is always a **file on disk**, never
in-session conversation context. That's what makes the pipeline resumable: any phase
can be re-run or picked up mid-stream by reading the prior artifact.

- **Fable** → design, foresight, and downstream guidance (Phase 1; optional Phase 5 taste review)
- **Opus** → build-ready spec + verification + task decomposition (Phase 2)
- **Sonnet** → implementation, one agent per task (Phase 3)
- **Opus** → optional final review against spec (Phase 4)

## Fable economics: bank it, don't round-trip it

Fable is the scarcest/metered tier, so its output is front-loaded and banked as durable
artifacts. Two rules follow:

- **Banking mode.** Design docs are on-disk and model-independent. While Fable is cheap
  (on-subscription), run Phase 1 across the whole backlog in bulk and bank the design
  docs; execute Phases 2–4 later at leisure. Pairs with `/hunger-games` for ranking
  which ideas earn a design.
- **Re-entry rule.** A design-level blocker found in Phase 2 kicks back to Fable while
  it's cheap; once metered, Opus resolves it from the design doc's alternatives
  graveyard instead of a paid round-trip.

## Core rule: gates are hard

Never start a phase before the prior phase's artifact exists on disk. Never collapse
two phases into one response. Each phase ends by stating (a) the path of the artifact
it wrote and (b) the gate that must clear before the next phase begins. If a gate
hasn't cleared, stop and say so rather than proceeding.

## Entry point detection

Adapt the starting phase to what the user hands over:

- A **feature name or description** with no artifacts → start at **Phase 1**.
- An existing **design doc** (`*-design.md`) → skip to **Phase 2**.
- An existing **spec** (`*-spec.md` with a task list) → skip to **Phase 3**.

State which phase you're entering and why before beginning.

## Model switching is manual

`/model` switching happens in the user's session — this skill can't flip models itself.
So at each phase boundary that requires a model change, **open the phase with an explicit
instruction telling the user to switch**, e.g. "Switch to Opus now with `/model` before
continuing." Then proceed as that model reading the prior artifact fresh. This keeps the
file-based handoff honest: each model reads the artifact rather than relying on leftover
conversation state.

---

## Phase 1 — DESIGN (Fable)

High-level planning and architecture only. **No code.** The bar for this phase: the
design doc must be complete enough that **no one downstream ever needs to ask Fable a
follow-up question** — every re-entry is a paid round-trip.

**1a. Ground first** (read-only probes of the real system, BEFORE eliciting). Verify the
facts the design will stand on: does the data the feature assumes actually exist, in the
shape assumed? What's already installed/available? 2–3 probe rounds max, strictly
read-only — this is grounding, not an audit. Probes routinely invalidate a feature's
premise before any design tokens are spent on it, and they sharpen the elicitation
questions (some forks only become visible once the facts are in). Every claim the
design relies on is either **verified here** or **named as an assumption** in Risk &
Response — no third category.

**1b. Elicit** (skippable for small features). Ask the user the 3–7 questions whose
answers would *change the design* — tacit constraints, prior attempts, what "done"
means to them, angles they haven't considered. **Pose each as concrete options with a
recommended default**, not open-ended — options resolve in one round; open questions
produce vague answers and extra round-trips. If answers conflict on the surface,
reconcile them explicitly in the design doc's locked-answers section (often both are
satisfiable: one now, one as a designed seam).

**1c. Design directions** (only when the shape is genuinely contested). For large or
ambiguous features, sketch 2–3 distinct directions with tradeoffs and recommend one;
the user picks at the gate. Skip when the shape is obvious — breadth on a
straightforward feature is waste.

**1d. The design document**, covering:
- **§0 Verified Facts** — the probe results as a table: fact → design consequence,
  dated. This is the doc's foundation; downstream models treat §0 as ground truth and
  everything not in it as unverified.
- **Locked answers** — the user's elicitation picks, restated, with any surface
  conflicts reconciled.
- Architecture overview and the major components/modules
- Data flow and external interfaces (APIs, DBs, services)
- Key decisions with rationale (why this approach over alternatives)
- **Alternatives graveyard** — each rejected approach in two lines: why rejected, and
  the **revisit trigger** that would resurrect it ("if X turns out false → Alternative
  B, sketched here"). This is the pre-reasoned Plan B that Phase 2 blockers and
  build-time forks fall back on without a Fable round-trip.
- **Risk & Response** — the 3–7 load-bearing risks, each stated as: the failure or
  wrong-assumption, **the assumption it's rooted in**, and a one-line design-level
  fallback. Cap it there: this is not a move-by-move simulation. Most risks trace to
  an unverified assumption — name it explicitly so the gate can resolve it.
- **Confidence map** — which parts of the design are solid vs. speculative ("confident
  in the data model; the caching strategy is a best guess"). Opus aims its hardest
  verification where the designer was least sure.
- **Executor briefing** — 3–6 bullets addressed to the Sonnet build agents: where a
  fast executor will predictably go wrong on *this* build (the tempting-but-wrong
  refactor, the API that looks like it does X but doesn't, files not to touch,
  non-obvious constraints). Opus threads these into the relevant task blocks. Keep it
  to *this build's* traps — for the project's standing gotchas, point at the project
  memory page that holds them instead of restating (restated copies go stale).
- **Quality bar** — success criteria and explicit non-goals; if the feature has a UI,
  the design direction (aesthetic reference, tokens, layout intent). Acceptance
  criteria (Phase 2) define *correct*; this section defines *excellent*.
- Open questions that need a human answer

**Artifact:** `docs/plans/<feature>-design.md`
**Gate:** The user reviews the design before Phase 2 begins — **confirms or denies each
flagged assumption** in the Risk & Response list, and picks a direction if 1c ran. A
confirmed assumption kills its risk at the root; a denied one changes the design now,
before Opus specs against it. Do not auto-advance.

End Phase 1 by stating the artifact path and prompting the user to review, then to
switch to Opus for Phase 2.

---

## Phase 2 — SPEC + VERIFY (Opus)

> Open this phase with: "Switch to Opus now with `/model` before continuing."

Opus reads `docs/plans/<feature>-design.md` from disk and does three things:

**1. Flesh out the spec.** Turn the design into something buildable: interface and
function signatures, types, schemas, acceptance criteria, and concrete test cases per
component.

**2. Verify the design.** Stress-test it. Look for gaps, contradictions, missing edge
cases, security and performance concerns, and under-specified areas. **Use the
confidence map to aim**: the areas Fable marked speculative get the hardest scrutiny;
the areas marked solid get a sanity pass, not a re-derivation. List every issue.
Resolve what you can; flag the rest for the user. A design-level blocker follows the
re-entry rule (back to Fable while cheap; otherwise resolve from the alternatives
graveyard).

Then build the **Risk Register** from Phase 1's Risk & Response list plus anything new
you found. One row per risk:

> risk | rooted assumption | class | signal | countermove | abort condition

- **class = runtime** (can fail while the code runs): the countermove becomes **code** —
  fold it into the owning task's acceptance criteria with a **failure-path test**.
- **class = build-time** (an assumption can fail *during implementation* — missing
  endpoint, library can't do X): the countermove is a **pre-decided fork written into
  the task block** ("if you observe X → do B instead") or an explicit **kick-back
  trigger** ("if X, stop and return to Phase 2"). Never leave a foreseeable fork to a
  build agent's judgment.
- **abort condition** — the observation that means stop, don't force it.

Depth is proportional to risk: most tasks carry no register rows; only genuinely risky
ones do. Verification "passing" means no unresolved blockers remain AND every register
row has a mitigation in the spec or a user-accepted abort condition.

**3. Decompose into build tasks.** Break the work into discrete, self-contained tasks,
each sized for **one Sonnet agent**. Because sub-agents share no memory, every task must
carry its own context: file scope (which files it may touch), acceptance criteria, and
test requirements. **Thread the design doc's executor briefing into the relevant task
blocks** — each trap lands in the task it applies to, verbatim. A task an agent can't
complete without seeing the rest of the design is too big — split it.

**Artifact:** `docs/plans/<feature>-spec.md`, ending with a numbered task list.
**Gate:** Verification must pass (no unresolved blockers) before Phase 3. If blockers
remain, stop and surface them.

End Phase 2 by stating the artifact path, the verification result, and the number of
build tasks.

---

## Phase 3 — BUILD (Sonnet agents)

> Open this phase with: "Spawn these as Sonnet agents — pin the sub-agents to Sonnet."

From the Opus main session, spawn **one Sonnet Task sub-agent per build task**. Each
agent receives only its own task block from the spec — file scope, acceptance criteria,
tests — not the full design history.

Rules for agents:
- Implement to spec. Agents do **not** redesign or second-guess Phase 1/2 decisions; if
  a task looks wrong, that's a signal to stop and kick it back to Phase 2, not to freelance.
- Work only inside the declared file scope.
- Write tests alongside the implementation.
- If the task block carries Risk Register rows: implement the countermove **and its
  failure-path test** — not just the happy path. Follow pre-decided forks as written;
  on an abort condition or kick-back trigger, **stop and report** rather than forcing
  a broken path.

**Parallelize** agents whose file scopes don't overlap; run sequentially any that do, to
avoid write collisions.

**Output:** code + passing tests for each task.
**Gate:** All tasks implemented with tests passing before Phase 4.

---

## Phase 4 — FINAL CHECK (Opus, optional)

> Back in the main session, still on Opus.

Opus reviews the assembled output against `docs/plans/<feature>-spec.md`:
- Contract adherence — do the implementations match the interfaces/signatures in the spec?
- Integration seams — do the independently-built pieces actually fit together?
- Test coverage — are the spec's test cases present and passing?
- Risk Register closure — is every runtime countermove implemented **with its
  failure-path test**, and was every triggered fork/abort handled as written (not
  silently bypassed)?
- **Real-data, real-env smoke (MANDATORY — not skippable even when the rest of this
  phase is).** At least one end-to-end request/run against the real data and the real
  runtime environment (real DB, real files, the actual env vars the deployed process
  gets). Fixture tests passing is NOT this gate: fixtures encode the builder's
  assumptions, so they pass together with the bugs. A test harness missing the
  production env produces *convincingly wrong* output — verify the harness env before
  trusting its numbers. Where a data format has an on-disk twin (csv+parquet, etc.),
  smoke against a real sample of BOTH.

Report any drift between what was specified and what was built. The review bullets are
optional (recommended for multiple interacting build tasks); the smoke is the gate to
deploy regardless.

---

## Phase 5 — TASTE REVIEW (Fable, optional)

> Open this phase with: "Switch to Fable now with `/model` before continuing."

For UI-heavy or design-sensitive features only. Fable reviews the *built* result against
the design doc's quality bar and design intent — the things Phase 4's contract check
can't see: visual hierarchy, interaction feel, aesthetic drift from the stated
direction, correct-but-mediocre outcomes. Report as a short punch list, not a redesign.
Worth running while Fable is cheap; skip once metered unless the feature is
design-critical.

**Method: review the LIVE artifact, never the code.** Stand up the built thing for real
(throwaway server with the real env, rendered output, tunnel if needed) and inspect it
as a user would — programmatic DOM/fetch probes are more reliable than screenshots when
screenshots flake. The findings that matter most (the contradiction between two views,
the number that reads wrong) are only visible in live pixels; code reading here just
re-runs Phase 4.

**Economics: Fable finds, cheaper tiers fix.** Each punch-list item must state *what
correct looks like* precisely enough that Opus/Sonnet can implement it without design
judgment — that specification is the Fable work. Then hand the list down: switch back
to Opus (or spawn Sonnet agents) for the fixes and re-verification. Fable re-checks the
resulting pixels afterward if warranted — it does not write the fix code. Fable
implementing punch-list fixes itself is the pipeline's own thesis violated at its most
expensive tier.

---

## Closing the run — bank the lessons

The pipeline isn't done at deploy. After the built thing is live and verified, file the
run's durable lessons into **project memory**: the §0 facts that changed the design,
the gotchas the smoke/taste phases surfaced, and any "still binding" constraints future
builds must honor. This is what makes the NEXT run's Phase-1 grounding cheap — its §0
starts from a warm list instead of re-deriving everything by probe. A run whose lessons
die in the conversation pays for them again next time.

## Conventions across all phases

- Concise by default; expand only where a phase genuinely needs the detail (spec bodies
  and task decomposition are the usual places).
- **Artifact size is a recurring tax, not a one-time cost** — every artifact gets
  re-read by multiple models across phases. Design doc ≤ ~400 dense lines (§0 facts,
  decisions, graveyard, risks); the spec carries the implementation detail. Cut
  anything a downstream model can derive.
- Each phase's closing line names the artifact path it wrote and the gate to advance.
- Keep artifacts in `docs/plans/` unless the user's repo uses a different convention —
  if so, match it.
