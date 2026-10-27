# Multi-pass annotation protocol (session teacher)

You replace an API teacher. For every unit CID assigned to you (files in your units dir DIR):

## Pass 1: annotate
1. Read `DIR/_system_prompt.md` once and follow it EXACTLY (roles-v2, tie-break rules, rule 6b on
   evidence `lines`). Schema: `DIR/_schema.json` (every anchor needs `lines`: 1-3 absolute line
   numbers from the line-numbered RTL that mention the entity).
2. Read `DIR/CID.prompt.md`. Write pure JSON to `DIR/CID.pass1.json` (Write tool, never bash heredocs).
3. Run `.venv/Scripts/python experiments/e2_session_annotation/check_answer.py DIR/CID.pass1.json`. Fixing ERRORs (e.g. wrong
   evidence line) is part of pass 1: overwrite pass1 until it reports OK.

## Pass 2..4: audit
For pass n (n >= 2):
1. Re-open the RTL in `DIR/CID.prompt.md` (do not work from memory) and audit the previous pass with
   this checklist:
   1. For EVERY anchor: do the cited lines really show this entity doing what the role claims?
      Is it the right entity of its concept (register vs. next-state twin vs. port copy)?
   2. Role: is there a more specific roles-v2 role? Apply the tie-break rules literally.
   3. Importance: critical only if a block diagram is wrong without it; MEDIUM view
      (critical+major) within the size rule; ports critical only for the primary handshake/data.
   4. Missing concepts: walk the entity table top to bottom; every STATE register, memory, FSM?
      row and high-ctrl_fanout signal is covered by an anchor or deliberately left as detail.
   5. Every port in exactly one interface; group anchor_ids are anchors.
   Also address every WARN printed by the checker for the previous pass.
2. Write the FULL annotation (changed or not) to `DIR/CID.pass{n}.json`, run the checker, fix ERRORs.
3. Append to `DIR/CID.audit.md`: `pass n: <list of changes, or "no change">` with a one-line reason
   per change.
4. If pass n changed nothing (same anchor ids, roles and importances as pass n-1), STOP. Otherwise
   continue with pass n+1. Never go beyond pass 4.

Finally copy the last pass to `DIR/CID.answer.json`.

## Independence
Open only your assigned prompt files and the `_` files in DIR. Do not read other answers, gold/,
src/, docs/, examples/, data/corpus/, experiments/e3_perturb_benchmark/data/, runs/store/, runs/out/.
