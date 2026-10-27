# Single-pass annotation protocol (session teacher)

You replace the API teacher. For every unit CID assigned to you (files in your units dir DIR):

1. Read `DIR/_system_prompt.md` once and follow it EXACTLY: roles-v2, tie-break rules, and rule 6b on
   evidence `lines` (1-3 absolute line numbers of the line-numbered RTL that mention the entity).
   The output schema is `DIR/_schema.json`.
2. Read `DIR/CID.prompt.md` (line-numbered RTL, entity table, summaries of child modules, and for
   some units a natural-language spec). Annotate at full detail with careful importance tiers.
3. Write pure JSON (no markdown fences) to `DIR/CID.answer.json` with the Write tool (never bash
   heredocs).
4. Validate from `layers/l1_extract`:
   `uv run python experiments/e2_session_annotation/check_answer.py DIR/CID.answer.json`
   Fix every ERROR and re-run until it prints OK. Fix a WARN when you agree with it.
5. One annotation pass. Do not run extra self-audit passes.

Independence: open only your assigned prompt files and the `_` files in DIR. Do not read other
answers, gold/, src/, docs/, examples/, experiments/*/data, runs/store/ or runs/out/.

Finish with one line per CID: `CID OK <attempts>` or `CID FAILED <reason>`.
