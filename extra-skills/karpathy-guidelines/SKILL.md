---
name: karpathy-guidelines
description: Andrej Karpathy's coding principles — applied before writing, reviewing, or refactoring any code
disable-model-invocation: true
---

# Karpathy Guidelines

Apply before writing, reviewing, or refactoring code. These are Karpathy's actual principles distilled from his essays, talks, and published advice.

## 1. Read before you write

Never write a line before you understand what already exists. Read the relevant files, trace the execution path, understand the data flowing through. Writing into a codebase you haven't read is how you create hidden dependencies and subtle bugs.

> "Spend more time reading than writing."

**In practice:** Use Read/Grep/Glob before any Edit. If you can't trace from entry point to the thing you're changing, read more.

## 2. Become one with the data

Before transforming, storing, or processing anything — inspect it. Print it, log it, read an actual sample. Bugs hide in assumptions about data shape, nulls, encoding, edge values.

> From "A Recipe for Training Neural Networks": "Visualize everything... look at raw data, look at intermediate representations, look at outputs."

**In practice:** For any new data source or format: read a real example before writing a handler.

## 3. Simplest thing first — always

Start with the dumbest, most direct solution. Complexity must be earned through demonstrated need, not anticipated. Abstraction before the third repetition is waste.

> "The best code is no code at all."

**In practice:** If you're tempted to build a class, a helper, or a pipeline — first ask: can a single function do this? Can a single expression?

## 4. Minimize total code in existence

Every line is a liability. Maintenance cost scales with LOC. Prefer deleting to adding. A 50-line solution beats a 200-line solution even if the 200-line version is more "correct" for hypothetical future requirements.

**In practice:** After solving the problem, ask: what can I delete? Can the same behavior be expressed in fewer moving parts?

## 5. One change at a time

Never change multiple independent things simultaneously. You can't isolate a failure you can't reproduce. Serial changes with a test/verify step between each is slower to type but faster to debug.

> From his NN recipe: "Change one thing at a time. If you change multiple things and something breaks, you don't know what caused it."

**In practice:** If a task involves 3 independent changes, make them sequentially. Verify state between each.

## 6. Verify assumptions explicitly — don't trust intuition

Every "I think this works" is a bug waiting to surface in production. If you assume a function returns X, add a log or assertion to prove it. If you assume a file contains Y format, read it.

**In practice:** Before building on an assumption, prove it. Write a one-liner test if needed.

## 7. End-to-end skeleton before optimization

Get the full pipeline working — even badly — before optimizing any component. Optimizing a component in isolation often means optimizing the wrong thing. The bottleneck is rarely where you expect.

> "Get a dumb baseline working. Then make it smarter."

**In practice:** For any new feature: wire all pieces together with stubs first. Verify data flows end-to-end. Then flesh out each piece.

## 8. Be suspicious of your first solution

The first solution that comes to mind is rarely the right one. It's usually the most familiar one. Spend 30 seconds asking: is there a fundamentally simpler approach? What would this look like if I deleted 80% of it?

**In practice:** Before committing to an approach, state the alternative and discard it explicitly.

## 9. Don't trust defaults — know every knob

Defaults are chosen for the average case. Your case is not average. Every timeout, buffer size, retry count, and model parameter you leave at default is a hidden assumption. Know what it does.

**In practice:** When using a library or API, read what the defaults are. If you're keeping a default, be able to say why it's appropriate here.

## 10. Neural net debugging applies everywhere

From his NN recipe — generalizes to all complex systems:
- Start with the simplest possible version and add complexity incrementally
- Overfit a tiny subset first (proves the system can learn/do the task at all)
- If something breaks, bisect — cut the system in half until you find the bad half
- Don't add features until the simple version is provably working

**In practice:** Can't debug a 500-line function? Strip it down to 20 lines that reproduce the failure. Then fix that.

---

## Checklist before coding

- [ ] Read all relevant files — no blind writes
- [ ] Inspected real data / state for this task
- [ ] Have the simplest solution in mind — not the most complete one
- [ ] Clear on exactly what I'm changing and why
- [ ] Plan to make changes one at a time with verify steps
- [ ] Know what success looks like (how will I confirm it works)
