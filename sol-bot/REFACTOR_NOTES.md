# Sol-Bot Rhetorical Moves Refactor — 2026-04-20

## What changed

Scope: `generate_combinada_tweet` (the fused headline + analysis post used
by `/noticia`, `/publica`, the dashboard, and the scheduler). No other
generation path touched.

### `generator.py`
- Added `from collections import Counter`.
- New module-level registries:
  - `RHETORICAL_MOVES` — 6 moves (`cold_fact_drop`, `buried_lede`,
    `nobody_noticed`, `history_rhyme`, `math_check`, `cold_conclusion`),
    each with `name`, `instruction`, `example`, and 5 `structural_variants`
    so the same move cannot produce the same-shaped post twice in a row.
  - `HOOK_ANGLE_INSTRUCTIONS` — one concrete instruction per existing
    `HOOK_ANGLES` key, injected into the prompt to shape the first line
    of analysis.
  - `CLOSER_TYPES` — 7 closers (`mechanics_reveal`, `absent_variable`,
    `time_compression`, `cost_in_dollars`, `no_close_at_all`,
    `question_drop`, `historical_echo`). `no_close_at_all` explicitly
    tells the model to stop on the penultimate analysis line.
- New helper `_pick_rhetorical_move(memory, recent_n=8)`: inverse-square
  weighted pick, penalizes moves that appear in the last 8 memory entries.
- `generate_combinada_tweet(headline, manual=False, move_override=None)`:
  - Picks move (override or weighted random; invalid override falls back
    to weighted random with a warning).
  - Picks a random `structural_variant` of that move.
  - Picks a random `hook_angle` and injects its instruction.
  - Picks a random `closer_type` and injects its instruction + example.
  - Prompt preserves: Line-1-verbatim format, English-only rule,
    `owner correction` override, `THREADS_COMBINADA_LENGTH_GUIDE`,
    and `build_continuity_prompt` injection into the system prompt.
  - Passes `rhetorical_move=move_key` into `memory.add_tweet`.

### `memory.py`
- `add_tweet` accepts optional `rhetorical_move: str | None = None`.
  The field is only written to the entry when non-None, so old records
  stay lean and no schema break is introduced.
- New `get_recent_moves(n=8)` returns `rhetorical_move` values from the
  last N entries, filtering out entries that never had one.

### Evaluator (`sol_post_evaluator_prompt.txt` and `sol_evaluator_prompt.json`)
- Scoring now on **5** dimensions — added `STRUCTURAL_FRESHNESS` (5/3/1).
- Defaults `structural_freshness` to `3` when no `recent_posts` context is
  supplied.
- Tiers rescaled to a 25-point max: A=21–25, B=16–20, C=11–15, D=5–10.
- JSON output now includes `"structural_freshness"` and `"max_score":25`.
- `.json` user-role content now ends with
  `\n\nRecent Sol posts (for freshness scoring, may be empty):\n{{recent_posts}}`.

### Untouched (by design)
`SYSTEM_PROMPT`, `CHARACTER_SHEET`, `WRITING_RULES`, `BANNED_PHRASES`,
`generate_tweet`, `generate_thread`, model routing (`MODEL_MAP_*`,
`get_model`, `_get_client`, `_call_api`), `free_mode`, and all callers
(`sol_commands.py`, `sol_dashboard_api.py`). Signatures are additive —
`move_override` defaults to `None`, `rhetorical_move` defaults to `None`.

## Rollback

All four edited files have `.pre-refactor` siblings created before the
refactor (in `/root/x-bot/sol-bot/`):

```bash
cd /root/x-bot/sol-bot
cp generator.py.pre-refactor generator.py
cp memory.py.pre-refactor memory.py
cp sol_post_evaluator_prompt.txt.pre-refactor sol_post_evaluator_prompt.txt
cp sol_evaluator_prompt.json.pre-refactor sol_evaluator_prompt.json
rm REFACTOR_NOTES.md
systemctl restart sol-bot
```

`context.json` entries written with `rhetorical_move` will remain after
rollback. The field is ignored by the pre-refactor code — no error,
no migration needed.

## 24h test plan

1. Run `/noticia` then `/publica` six to eight times across the next day.
2. After each batch, inspect `context.json`:
   ```bash
   jq '[.[] | select(.rhetorical_move) | .rhetorical_move] | group_by(.) | map({move: .[0], n: length})' context.json
   ```
   Expected: no single move is >40% of recent entries; no `buried_lede`
   streak longer than 2 in a row.
3. Inspect evaluator output for each post — `structural_freshness`
   should be populated (1, 3, or 5) and `max_score` should be `25`.
4. Spot-check three published posts: first analysis line, closer shape,
   and overall structure should visibly differ from each other.

## Expected outcome

Pre-refactor the model was collapsing to the Buried Lede move in roughly
60% of `combinada` posts. With the 6-move registry, inverse-square
recency penalty, 5 structural variants per move, 7 hook-angle
instructions, and 7 closer types, per-move distribution should settle
near 16–20% (1/6), with visible shape variation even when the same move
is picked twice in a window.
