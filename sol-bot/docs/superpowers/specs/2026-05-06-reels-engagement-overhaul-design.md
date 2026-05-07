# Reels Engagement Overhaul — Design Spec

**Date:** 2026-05-06
**Owner:** @napoleotics / The Clam Letter
**Status:** Approved (brainstorm)
**Scope:** Three sequential phases, each independently shippable.

---

## 1. Why this exists

Current reels (Hyperframes v3, 15s, "data-card-5beat") get distribution but
underperform on engagement signal. Real metrics from the last 7 days:

| Platform | Reach signal | Engagement signal |
|---|---|---|
| Instagram | 1,393 views, 100% non-followers, 1,155 reach | 20 interactions; 90% from existing followers; 10% from non-followers |
| TikTok | 828 views, 96.3% from For You | 31 likes, **4 comments, 0 shares**, 8 profile views |
| YouTube Shorts | avg view 11s, **77.94% avg view %** | low subscriber conversion |

**Diagnosis:** the algorithm distributes the content (For You, non-follower
reach, solid avg view %). The bottleneck is **conversion of view → social
signal** (comments, shares, follows). The current pipeline optimizes for
information density, not for provoking action.

This is a different problem from "low retention" and demands a different fix:
the content must end with a comment-trigger, contain a share-worthy moment,
and carry a recurring brand signature that earns the follow.

## 2. Concrete failures of the current pipeline

Grounded in the code, not generic critique:

1. **Hook on screen = first sentence of TTS.** `reel.html` line 291 renders
   `{{HOOK}}` as the headline paraphrase, and `tts_text` (`reels_generator.py`
   line 134) starts `"Breaking. <headline>."`. Two channels of attention,
   same content. Wasteful.

2. **No real rehook at second 5.** `reel.html` lines 430-432 fire stat1/2/3 at
   2.0s/4.7s/7.4s with identical `slide-in + opacity` tweens. Same motion
   three times = no pattern interrupt.

3. **Static background.** `reel.html` line 402 sets `gsap.set("#bg", {scale:
   1.0})` — never changes. Background videos run unmodulated for 15s.

4. **Single voice, no profile per content type.** `gen_tts_sol.py` is hardcoded
   to one ElevenLabs voice. WIRE/DEBATE/ANALYSIS all sound the same.

5. **No CTA.** Caption ends with hashtags. No on-screen comment-bait, no
   contrarian question to provoke reply.

6. **No platform variants.** Same MP4 to TikTok, Reels, and Shorts. Different
   algorithms, different first-2-second expectations, same file.

7. **No instrumentation loop.** `analytics.db` records `posts.created_at,
   platform, content` but nothing about WHICH variant was used. Can't ask
   "did hook-style A outperform B" because A/B isn't tracked.

8. **Iteration debris.** Six `news_to_reel.py.bak.*` files indicate parametric
   patching without a clear model. Worth consolidating during phase 1.

## 3. Goals & non-goals

**Goals:**
- 3× the comment rate on TikTok (baseline 4 comments / 828 views = 0.48% →
  target 1.5%).
- First share on TikTok within 2 weeks of phase 2 ship (baseline 0).
- IG engagement from non-followers 10% → 25%.
- Visually distinguishable output by phase 1 ship (A/B-able against current
  reels on the same headline).
- Don't break the dashboard or the publish flow during any phase.

**Non-goals:**
- Higher production cost per video (must stay within current ElevenLabs +
  Hyperframes budget envelope).
- Manual editing — fully automated end-to-end.
- New platforms (no Shorts → LinkedIn migration in this scope).
- Replacing Hyperframes (the renderer stays).

## 4. Architecture overview

### 4.1 The `ReelSpec` contract

Defined fully in phase 1, populated progressively across phases. Every
phase reads/writes against this single shape so phases compose without
schema churn.

```python
ReelSpec = {
    # === Identity ===
    "reel_id": str,
    "headline": {"title": str, "summary": str, "source": str},
    "topic_tag": str,

    # === Hook layer (used by template + script) ===
    "hook": {
        "variant": "shock" | "question" | "character" | "contradiction",
        "text": str,            # ≤ 60 chars, on-screen
        "tts_lead": str,        # spoken hook, may differ from on-screen
    },

    # === Rehook at ~5s ===
    "rehook": {
        "text": str,            # complement, NOT repeat of hook
        "interrupt_kind": "cut" | "zoom_punch" | "freeze_stamp" | "color_flash",
    },

    # === Beats (replaces stat1/2/3) ===
    "beats": [
        {"t": float, "type": "stat" | "contradiction" | "twist" | "callback",
         "text": str, "emphasis_words": list[str]}
    ],

    # === CTA — engagement conversion lever ===
    "cta": {
        "variant": "comment_bait" | "share_trigger" | "follow_hook",
        "text": str,            # on-screen final 2s
        "tts_close": str,       # spoken close
    },

    # === Voice ===
    "voice_profile": "urgent" | "analytical" | "markets",
    "tts_text": str,            # full narration (assembled from above)

    # === Render selection ===
    "template_variant": "shock" | "character" | "markets" | "analysis",
    "background": str,          # filename in reels-hf/assets/
    "label": "BREAKING" | "DEVELOPING" | "ANALYSIS" | "MARKETS",

    # === Platform pack (filled in phase 3) ===
    "platform_pack": {
        "tiktok":  {"hook_intensity": "high", "title": str, "duration_s": 15},
        "reels":   {"hook_intensity": "medium", "title": str, "duration_s": 15},
        "shorts":  {"hook_intensity": "high", "title": str, "duration_s": 30},
    },

    # === Caption (post copy) ===
    "caption": str,

    # === v2 backcompat fields (so dashboard keeps working) ===
    "stat1": str, "stat2": str, "stat3": str, "body": str,
    "rhetorical_move": str, "numeric_highlights": list[str],
    "suggested_bg": str, "suggested_bg_score": int,
}
```

**Backwards compat:** in phase 1, `reels_generator` keeps emitting `stat1/2/3`
and `body` derived from `beats` so the existing dashboard preview still
renders. Phase 2 deprecates the v2 fields cleanly.

### 4.2 Phase boundaries

```
                       ┌────────────────────────────────────┐
                       │  reels_generator.generate_reel()   │
                       │  → ReelSpec                        │
                       └────────────┬───────────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              ▼                     ▼                     ▼
       ┌────────────┐        ┌────────────┐        ┌────────────┐
       │ gen_tts_*  │        │ render_*   │        │ DB write   │
       │ (PHASE 2)  │        │ (PHASE 1)  │        │ (PHASE 3)  │
       └────────────┘        └────────────┘        └────────────┘
```

Phase 1 owns the renderer: `render_reel_hf.py` + new templates.
Phase 2 owns the generator and the TTS layer.
Phase 3 owns the DB schema + dashboard analytics view + per-platform packs.

---

## 5. Phase 1 — Trash-edit motor

**Outcome:** same copy + same TTS, but a video that looks visually distinct
from the current reels. A/B-able against existing.

### 5.1 Templates (HTML compositions)

Replace single `templates/reel.html` with four variants under
`reels-hf/templates/`:

- `tpl_shock.html` — giant centered stat, screen-flash on the number, hook
  enters via clip-path glitch (3 keyframes).
- `tpl_character.html` — character video full-bleed, freeze-frame at 2s with
  text stamp ("WHAT HE SAID:"), quote enters in karaoke sync to TTS.
- `tpl_markets.html` — chart line animates left→right, big number reveals at
  inflection, ticker strip on bottom.
- `tpl_analysis.html` — split-screen: footage on top half, takeaway text
  scrolling/replacing on bottom; transition cuts every 2s.

`render_reel_hf.py` selects the file by `template_variant`. Default for
phase 1 is `tpl_shock` for BREAKING, `tpl_analysis` for ANALYSIS — no LLM
choice yet (that's phase 2).

### 5.2 Pattern interrupts (shared across templates)

These run on a shared GSAP timeline include (`reels-hf/templates/_interrupts.js`):

- **Microcut at 2.0s, 4.0s, 6.0s, 9.0s, 12.0s.** Implementation: `gsap.to(
  "#bg", {scale: 1.0 → 1.08, duration: 0.08, yoyo: true})` plus 60ms black
  flash overlay (`#cut-flash` div with `opacity 0 → 1 → 0`).
- **Rehook punch at 5.0s.** Background `scale 1 → 1.18 → 1.05` over 0.4s with
  `ease: "back.out(2)"`, paired with a `#rehook-stamp` div sliding in from
  bottom with `rehook.text`.
- **Freeze stamp** (only when `hook.variant == "character"`): pause `<video>`
  via `bg.pause()` at 2.0s, hold 0.3s with red text overlay, resume.
- **Color flash** at peaks (TTS `emphasis_words` timestamps): full-screen
  red/yellow div with `opacity 0 → 0.55 → 0` over 0.12s.
- **Karaoke captions** at the bottom third: each TTS word gets its own
  `<span>` with `data-start` aligned to TTS forced-alignment timestamps.
  Active word: `scale 1.15`, color yellow, others dimmed `opacity 0.55`.
- **Loop bridge** at 14.0-15.0s: last frame's hook fades while the very
  first frame's badge cross-fades in over the bottom-right corner. Music
  bed re-attacks last beat to match the SFX `loop_thump` already in place.

### 5.3 Karaoke caption timing

ElevenLabs returns audio without word timestamps. Two options:

- **A (chosen):** call ElevenLabs with `output_format=mp3_44100_192` and run
  whisper-cpp (already on the VPS for transcript jobs) on the resulting MP3
  with `--output-json` to get word-level timestamps. Runs once per render,
  cached by hash of `tts_text`.
- B: estimate timing by character count + WPM. Rejected: alignment drift on
  long words / proper nouns kills the karaoke effect.

A `tts_align.py` helper module wraps this and emits `[{word, start, end},
...]` injected into the template via `{{CAPTION_WORDS_JSON}}`.

### 5.4 Files touched in phase 1

- **NEW** `reels-hf/templates/tpl_shock.html`
- **NEW** `reels-hf/templates/tpl_character.html`
- **NEW** `reels-hf/templates/tpl_markets.html`
- **NEW** `reels-hf/templates/tpl_analysis.html`
- **NEW** `reels-hf/templates/_interrupts.js`
- **NEW** `tts_align.py` — whisper-based word alignment
- **MODIFIED** `render_reel_hf.py` — pick template by `template_variant`,
  pass karaoke JSON, hold lock during alignment
- **MODIFIED** `reels_generator.py` — minimum: emit `template_variant`,
  `hook.variant` (default `shock`), `cta.text` (placeholder for phase 1).
  All other ReelSpec fields filled with defaults.
- **NEW** `tests/test_render_reel_hf.py` — assert each template renders
  without ffmpeg error against a fixture ReelSpec
- **MODIFIED** `reels-hf/CLAUDE.md` — document the four-template selection
  rule
- **DELETE** `news_to_reel.py.bak.*` (six files), `reels_generator.py.bak-pre-bg-motion`,
  `gen_news_video.py.bak.pre-bitrate` — only after phase 1 ships and we have
  one good week of metrics.

### 5.5 Phase 1 acceptance

- `pytest tests/test_render_reel_hf.py` passes for all four templates.
- `npx hyperframes lint` returns zero errors on each template.
- Manual: generate the same headline through current pipeline AND new pipeline,
  publish both to a private TikTok account, eyeball comparable.
- Render time per reel ≤ 90s (current is ~70s; alignment adds ~10-20s).
- Render lock semantics preserved (no double-render race).

---

## 6. Phase 2 — Script + voice strategy

**Outcome:** scripts are written for spoken delivery, end with a CTA designed
to provoke comment/share, and voice is selected by content type.

### 6.1 Generator rewrite

`reels_generator.generate_reel_copy()` is replaced by `generate_reel_spec()`,
emitting the full `ReelSpec`. The LLM call is restructured into three
sub-calls (cheap, parallelizable):

1. **Hook chooser** (Haiku) — given headline, picks `hook.variant` and writes
   3 candidate hooks, picks the one with highest predicted engagement.
   System prompt explicitly excludes news-headline-style phrasing.
2. **Beat composer** (Sonnet for ANALYSIS, Haiku elsewhere) — produces 3-4
   beats with emphasis_words flagged for color-flash sync.
3. **CTA writer** (Haiku) — given the news topic, generates a comment-bait
   question OR a share-trigger fact. Decision rule: if topic is divisive
   (political, fiscal), comment-bait; if it's a single surprising number,
   share-trigger.

Each sub-call has its own focused system prompt. Caching via Anthropic
`cache_control: ephemeral` on the static system blocks (already wired in
`generator.py` at commit `82dcdec`, unused on OpenRouter path).

### 6.2 Voice profiles

Three ElevenLabs voice IDs in `.env`:

```
ELEVENLABS_VOICE_URGENT=...      # for BREAKING
ELEVENLABS_VOICE_ANALYTICAL=...  # for ANALYSIS / DEBATE
ELEVENLABS_VOICE_MARKETS=...     # for MARKETS
```

`gen_tts_sol.py` becomes a thin wrapper that picks the voice ID by
`voice_profile`. ElevenLabs `voice_settings`:

| Profile | stability | similarity | style | speaker_boost |
|---|---|---|---|---|
| urgent | 0.35 | 0.75 | 0.6 | true |
| analytical | 0.55 | 0.80 | 0.3 | false |
| markets | 0.45 | 0.78 | 0.4 | false |

(Lower stability = more expressivity, which is what the research pointed at
re: "voz plana mata el hook".)

### 6.3 Spoken-delivery rules in the script prompt

System prompt for beat composer adds:
- Sentences ≤ 14 words.
- Punctuation indicates pauses (`,` short, `.` hard stop, `…` thinking
  pause).
- `emphasis_words` always include the surprising stat or the contrarian
  verb — these drive the color-flash and karaoke scale.
- Forbidden: passive voice, hedges (`may`, `could`, `might`), em-dashes
  (already a rule, kept).

### 6.4 Files touched in phase 2

- **MODIFIED** `reels_generator.py` — three-call pipeline, full ReelSpec
- **MODIFIED** `gen_tts_sol.py` — voice selection by profile
- **MODIFIED** `.env` (and `.env.example` if present) — three voice IDs
- **MODIFIED** `reels-hf/templates/*.html` — read `cta` block at the loop
  bridge (last 2s)
- **NEW** `tests/test_reels_generator_spec.py` — assert each variant emits
  a complete ReelSpec
- **MODIFIED** `CLAUDE.md` — voice profile mapping documented

### 6.5 Phase 2 acceptance

- `pytest tests/test_reels_generator_spec.py` passes.
- 5 manually-reviewed reels show distinct voice timbre per profile.
- 5 manually-reviewed scripts each end with a CTA that's not a hashtag.
- A comment-bait CTA appears in ≥ 60% of BREAKING reels over a 1-week sample.

---

## 7. Phase 3 — Platform packs + analytics loop

**Outcome:** different render settings per platform, every variant choice
recorded, dashboard ranks variants by engagement.

### 7.1 Platform packs

Same `ReelSpec` produces three MP4s:

- **TikTok pack** — first 1.5s extra-aggressive: hook stamp scales 1.0→1.15,
  caption appears 200ms earlier. Title (post text) is the hook itself
  (TikTok captions are short).
- **Reels pack** — softer entrance, brand cleaner. Title is the hook + 2-3
  hashtags. No karaoke captions on Reels (they double-render the platform's
  own captions ugly).
- **Shorts pack** — 30s allowed: insert one extra `beat` of type `callback`
  before the CTA. Title is YouTube-search-optimized (keyword-front-loaded).

Implementation: `render_reel_hf.render_reel(spec, platform="tiktok")` becomes
`render_pack(spec)` returning `{tiktok_path, reels_path, shorts_path}`.
Templates accept a `platform` data attribute; differences are CSS-driven
where possible.

### 7.2 Database schema migration

New columns on `analytics.db.posts` (and `threads_analytics.db.posts` where
applicable):

```sql
ALTER TABLE posts ADD COLUMN hook_variant TEXT;
ALTER TABLE posts ADD COLUMN voice_profile TEXT;
ALTER TABLE posts ADD COLUMN template_variant TEXT;
ALTER TABLE posts ADD COLUMN cta_variant TEXT;
ALTER TABLE posts ADD COLUMN platform_pack TEXT;
```

Migration is additive — old rows keep `NULL`. Backfill not necessary; we
care about forward measurement.

`reel_metrics_etl.py` joins `posts` against platform metrics tables and
emits a `variant_performance` view:

```sql
CREATE VIEW variant_performance AS
SELECT
  hook_variant, voice_profile, template_variant, cta_variant,
  platform,
  COUNT(*) AS n,
  AVG(views) AS avg_views,
  AVG(comments * 1.0 / NULLIF(views, 0)) AS comment_rate,
  AVG(shares * 1.0 / NULLIF(views, 0)) AS share_rate
FROM posts JOIN <platform_metrics> USING (post_id)
GROUP BY 1, 2, 3, 4, 5;
```

### 7.3 Dashboard analytics view

`sol_dashboard_api.py` adds `/analytics/variants` endpoint returning the
view. New dashboard page `/dashboard#variants` shows:

- Comment rate by `hook_variant`, sortable.
- Share rate by `cta_variant`.
- View → follow conversion by `voice_profile`.
- Filter by date range.

Visualization: simple HTML tables first, no charts. Charts are scope creep.

### 7.4 Files touched in phase 3

- **NEW** `migrations/001_variant_columns.sql`
- **MODIFIED** `analytics.db` (via migration)
- **MODIFIED** `reel_metrics_etl.py` — emit variant_performance view
- **MODIFIED** `render_reel_hf.py` — `render_pack()` API
- **MODIFIED** `reels-hf/templates/*.html` — `data-platform` attribute
- **MODIFIED** `sol_dashboard_api.py` — `/analytics/variants` endpoint
- **MODIFIED** `templates/dashboard.html` — new section
- **MODIFIED** `publish_service.py` — record variant fields on publish
- **MODIFIED** `news_to_reel.py` — pass through variant fields
- **NEW** `tests/test_variant_recording.py`
- **MODIFIED** `CLAUDE.md` — DB schema doc

### 7.5 Phase 3 acceptance

- One render produces three platform-specific MP4s in ≤ 3 minutes total.
- After 1 week, `/analytics/variants` shows ≥ 5 rows with non-NULL n per
  combo.
- Migration runs idempotently (re-running is a no-op).
- Existing dashboard pages keep working (regression guard).

---

## 8. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Whisper alignment drifts on noisy TTS | Medium | Already fast on VPS. Cache by hash of `tts_text`. Fallback to char-count estimate if alignment confidence < 0.7. |
| Trash-edit looks "TikTok-trash" for The Clam Letter brand | Medium | Templates differ per content type. ANALYSIS template is restrained by design. Keep the brand block clean. |
| ElevenLabs costs jump with three voices | Low | Same characters spoken; 3 voice IDs same plan. No per-voice fee. |
| DB migration breaks existing dashboard SQL | Low | Additive only. Pre-deploy: backup `analytics.db`, run migration on a copy first. |
| Hyperframes timeline complexity hits performance | Medium | Each template stays ≤ 1 timeline. Microcuts use `transform`-only animations (no layout). Lint pass required. |
| Phase 2 schema break on dashboard preview | High | Phase 1 keeps v2 fields populated. Phase 2 keeps emitting `stat1/2/3` derived from `beats[0..2].text`. Deprecate at end of phase 3. |

## 9. Out-of-scope / explicit YAGNI

- AI-generated backgrounds. Use existing curated `reels-hf/assets/` library.
- Sentiment-adaptive music. Single music bed stays.
- Auto-A/B testing harness. Phase 3 measures; humans iterate.
- Multi-language. English only.
- Long-form versions (60s+). 15s + 30s Shorts only.

## 10. Sequencing & merge strategy

Each phase ships as its own PR against the production branch
(`feat/sol-manual-commands` per memory). Phase N+1 doesn't start until
phase N is merged and observed in prod for ≥ 3 days.

The branch model (per `.../memory/project_sol_bot_branch_truth.md`): work on
`feat/sol-manual-commands`, never on `main` (main has stale parallel
refactor PR #11 that was never deployed).
