# Model Routing and Selection for Sol Bot
**Fecha:** Marzo 2026
**Fuente:** Análisis externo verificado con OpenRouter docs + Anthropic pricing

---

## Executive Summary

Sol Bot's current routing has a looming operational risk: `google/gemini-2.0-flash-001` is marked **"Going away June 1, 2026"** on OpenRouter (~67 days from March 26, 2026). This alone justifies a near-term migration for WIRE and DEBATE.

**Core strategy:**
- Keep Claude Sonnet 4.6 as the "quality anchor" for ANALYSIS, CONNECTION, and most DEBATE
- Replace Gemini 2.0 Flash with Gemini 3.1 Flash Lite Preview (or Gemini 3 Flash) for cost-sensitive auto slots
- Separate routing by mode: auto = cost-aware with escalation; manual = best publish-ready first pass
- Swap reply generation to Claude Haiku 4.5
- For analytics_insights.py: keep high-quality reasoning + cut cost with Claude Batch API (50% off)

---

## Capability Requirements by Tweet Type

Sol Bot is **not** "news summarization." It is an editorial persona publishing under time pressure, with hard constraints: Spanish-native tone, sarcasm/dryness, consistent contrarian framing. This pushes model selection toward **instruction-following reliability and style consistency** more than raw benchmark intelligence.

### WIRE (breaking, 2 lines, "data + impact")
Must: extract the 1-2 load-bearing facts, compress causality without hedging, respect formatting limits.
**Failure mode:** shallow output on geopolitically complex items = insufficient reasoning budget + weak salience selection under tight length constraints.

### DEBATE (rhetorical question that drives engagement)
This is deceptively hard: the model must identify the narrative assumption, construct a tension/contradiction, and phrase a question that feels "inevitable" rather than obvious.
**In practice, DEBATE behaves closer to "mini-analysis" than "light copy"** — benefits from stronger reasoning model with high instruction adherence.

### ANALYSIS and CONNECTION
Highest-leverage outputs, most brand-defining. Require long-horizon coherence, strong compression, and reliable persona injection. Current choice (Claude Sonnet tier) aligns with how Anthropic positions Sonnet 4.6.

### content_calendar.py
Planning under uncertainty, not prose generation. A small increase in spend is justified because the plan amortizes over the day's outputs.

### reply_scanner.py
"High-volume micro-style" task. You need low latency, high steering, minimal verbosity, and consistent voice. Best model = not the smartest, but the one that stays on-character under short constraints reliably and cheaply.

### analytics_insights.py
Deep reasoning + structured recommendations, but latency is irrelevant. Best fit for batching/caching ROI.

---

## Model Landscape and Pricing (OpenRouter, Early 2026)

### Key Candidates

| Modelo | Input/M | Output/M | Notes |
|---|---|---|---|
| Gemini 2.0 Flash | $0.10 | $0.40 | ⚠️ Going away June 1, 2026 |
| Gemini 3 Flash Preview | $0.50 | $3.00 | Near-Pro reasoning, thinking levels, auto context caching |
| Gemini 3.1 Flash Lite Preview | $0.25 | $1.50 | High-efficiency, improved translation/extraction, thinking levels |
| Claude Sonnet 4.6 | $3.00 | $15.00 | Improved consistency + instruction following vs prev versions |
| Claude Haiku 4.5 | $1.00 | $5.00 | Fastest/most efficient Claude |
| Claude Opus 4.6 | $5.00 | $25.00 | Deepest, long-running professional workflows |
| DeepSeek V3.2 | $0.26 | $0.38 | Strong reasoning + agentic tool-use, controllable reasoning |
| Mistral Small 4 | $0.15 | $0.60 | Unified small model for reasoning + coding |
| Llama 3.3 70B Instruct | $0.10 | $0.32 | Explicit Spanish support, multilingual dialogue |
| GPT-5.1 (OpenAI) | $1.25 | $10.00 | Improved instruction adherence and general reasoning |
| GPT-4.1 Mini | $0.40 | $1.60 | Low-latency, strong instruction eval scores |

### OpenRouter Economics
- Does NOT mark up underlying provider pricing
- When routing/fallback enabled, billed only for the successful run
- Provider routing is price-weighted by default, tunable for throughput/latency
- Exposes per-request token counts and cost via API for auditing

---

## Final Routing Table

| Workload | Auto Primary | Auto Fallback/Escalation | Manual Primary | Manual Escalation |
|---|---|---|---|---|
| WIRE | Gemini 3.1 Flash Lite Preview | → Sonnet 4.6 when complexity high; Haiku 4.5 for formatting failures | Sonnet 4.6 | Opus 4.6 for high-stakes items |
| DEBATE | Claude Sonnet 4.6 | → GPT-5.1 if Sonnet over-cautious; Gemini as last resort | Claude Sonnet 4.6 | Opus 4.6 for sharpest framing |
| ANALYSIS | Claude Sonnet 4.6 | → Opus 4.6 for multi-actor geopolitics / sovereign risk | Sonnet 4.6 (default) | Opus 4.6 when owner wants best-in-class |
| CONNECTION | Claude Sonnet 4.6 | → Opus 4.6 for more original synthesis; GPT-5.1 for different creative taste | Sonnet 4.6 | Opus 4.6 |

### Why Gemini 3.1 Flash Lite for WIRE?
- Must replace 2.0 Flash (going away June 1)
- Positioned as high-efficiency, improved in translation/extraction, supports thinking levels
- Very inexpensive → WIRE's high frequency in scheduler stays cheap

### Why Sonnet 4.6 for DEBATE/ANALYSIS/CONNECTION?
- "Judgment + framing" tasks where instruction following and coherent reasoning matter more than raw speed
- Anthropic explicitly claims Sonnet 4.6 improves consistency and instruction following
- For a publishing agent with strict voice, more dependable than smaller/cheaper models

### Why not keep Gemini for DEBATE?
Observed failure mode ("obvious or poorly constructed questions") matches constrained reasoning budget + weak creative framing. DEBATE is low-volume enough that anchoring in Sonnet and substituting only after measuring is the safer approach.

---

## Manual vs Automatic Mode Routing

**Automatic mode** is throughput-oriented with tolerance for 30–60 seconds. Room for two-stage generation or complexity escalation.

**Manual mode** is human-wait-time dominated. The owner wants a publishable draft in one pass; spending an extra $0.005–$0.02 is cheaper than a second iteration loop.

### Practical production approach:
- **Manual default:** Sonnet 4.6 for all types
- **Manual `/opus` or `/max` command:** swap to Opus 4.6 for ANALYSIS/CONNECTION/DEBATE
- **Scheduler:** WIRE starts cheap (Gemini 3.1 Flash Lite), with escalation rule for complex items

---

## Complexity Escalation Triggers

Escalate WIRE from Gemini 3.1 Flash Lite → Sonnet 4.6 when:
- The news mentions 3+ sovereign actors (countries, central banks, multilateral blocs) or 2+ simultaneous theaters
- The headline includes ambiguous verbs: "reportedly," "considering," "sources say"
- The "impact" requires multi-hop inference (e.g., tariffs → supply chain → inflation → yields)
- The generator's first pass fails strict requirements (2 lines; contains hedging; lacks numbers)

---

## Recommendations by Module

### content_calendar.py
**Recommendation: Claude Opus 4.6**
- High-leverage planning task that determines what Sol covers all day
- Opus 4.6 positioned for long-running, multi-step professional workflows
- Quality gain amortizes across all posts that day
- **Implementation:** use structured outputs (JSON Schema) for machine-parseable calendar (planned tweet types, topic clusters, hook/mood, risk flags)

### reply_scanner.py
**Recommendation: Claude Haiku 4.5**
- High frequency, ≤200 chars, must stay on-character
- Keeps you inside the same "Claude family" → better voice consistency vs mixing vendors

**Two-tier option if reply volume scales:**
1. Draft 2–3 candidates with Mistral Small 4 ($0.15/$0.60) or DeepSeek V3.2
2. Haiku 4.5 selects and lightly rewrites the best one

### analytics_insights.py
**Recommendation: Claude Sonnet 4.6 + Anthropic Batch API**
- Heavy, low frequency, not urgent = perfect fit for batch pricing
- Anthropic Batch API provides 50% discount on both input and output tokens
- Output should be structured (recommendations + evidence + confidence + proposed experiments)

---

## Cost Estimates per Tweet

Using 2,500 input / 200 output tokens as baseline:

| Model | Cost/tweet |
|---|---|
| Mistral Small 4 | ~$0.00050 |
| Llama 3.3 70B | ~$0.00031 |
| DeepSeek V3.2 | ~$0.00073 |
| Gemini 3.1 Flash Lite | ~$0.00093 |
| Gemini 3 Flash | ~$0.00185 |
| GPT-4.1 Mini | ~$0.00132 |
| Claude Haiku 4.5 | ~$0.00350 |
| GPT-5.1 | ~$0.00513 |
| Claude Sonnet 4.6 | ~$0.01050 |
| Claude Opus 4.6 | ~$0.01750 |

**Note:** At Sol Bot's current posting volume, quality and voice consistency should dominate cost decisions. The primary economic risk is not per-tweet cost but accidental growth in prompt size or multi-pass loops.

---

## Production Optimizations

### Prompt Caching
Sol's prompt has a large stable prefix (character sheet + hook framework + mood definitions + format rules). Cache hits cost 0.1× base input.

**Most impactful:** inside a single scheduler run (2–3 tweets) where the stable prefix is identical and generated within a short time window.

### Structured Outputs for Publishability
Return a strict schema instead of raw free-form text:
```json
{
  "x_text": "...",
  "threads_text": "...",
  "risk_flags": [],
  "topic_tags": [],
  "self_check": {
    "under_280_chars": true,
    "under_2_lines_wire": true,
    "no_hedging": true
  }
}
```
OpenRouter supports structured outputs via JSON Schema for Gemini, Anthropic (Sonnet 4.5+ / Opus 4.1+), and OpenAI models.

### Metrics to Track (Harden Routing)
Use OpenRouter's usage and generation stats to capture per-output token cost and model ID:
- **Publish-ready rate** (primary KPI)
- **Persona adherence violations**
- **Repetition rate** (topic overlap with last 15 tweets)
- **Hallucination indicators** (numbers not present in source context)
- **Regeneration rate** (how often owner asks for a redo)

Treat "needs editing" as a hard failure. Mode-specific policies: scheduler can accept 2-pass pipeline (draft → polish); manual should optimize for one-pass excellence.
