# Vera Bot — magicpin AI Challenge Submission

**Team**: Abhinav Kumar | **Model**: GPT-4o | **Version**: 1.0.0

---

## Approach

### 4-Context Composition with Trigger-Kind Routing

The core insight is that different trigger kinds require fundamentally different message *frames*:

- `research_digest` → cite the finding (trial_n, %, source), tie to merchant's patient cohort
- `perf_dip` → name the exact metric + delta, loss aversion, one concrete reversible action
- `recall_due` → patient name + specific slots from payload + catalog price
- `active_planning_intent` → **action mode**, never re-qualify, use effort externalization

`composer/prompt_builder.py` has per-kind guidance for 20+ trigger kinds. The system prompt enforces:
- Verifiable fact anchor in every message (number, date, source)
- Voice match by category (peer_clinical for dentists, warm_practical for salons, etc.)
- Single CTA in the last sentence only
- Hindi-English code-mix where `"hi"` is in `identity.languages`
- No fabrication, no preamble, no re-introduction

**Model**: `gpt-4o`, `temperature=0` (deterministic).

---

## Architecture

```
bot.py                     ← FastAPI server (5 endpoints) + standalone compose()
composer/
  vera_composer.py         ← Anthropic API calls with retry + fallback
  prompt_builder.py        ← Trigger-kind routing + 20+ prompt frames
  output_validator.py      ← JSON parsing + schema enforcement
storage/
  context_store.py         ← Thread-safe versioned in-memory store
conversation/
  manager.py               ← Conversation state machine
  auto_reply.py            ← Pattern-match + verbatim-repetition detection
  intent.py                ← ACTION / DISMISS / QUESTION / ENGAGED routing
conversation_handlers.py   ← Multi-turn respond() function (§7.4)
generate_submission.py     ← Batch generation script for submission.jsonl
```

---

## Running the Server

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
uvicorn bot:app --host 0.0.0.0 --port 8080
```

**Local test with judge simulator:**
```bash
export BOT_URL=http://localhost:8080
python judge_simulator.py
```

---

## Key Design Decisions

### Specificity-first composition
Every prompt explicitly asks for the single most specific verifiable fact from the context. Generic language ("increase your sales") is listed as an anti-pattern in the system prompt.

### Trigger-kind routing
A flat dispatcher maps each `kind` to a dedicated guidance fragment. `research_digest` includes the resolved `DigestItem` (title, source, trial_n, patient_segment). `active_planning_intent` explicitly says: *"This is ACTION mode — do not re-qualify."*

### Auto-reply detection (two-signal)
1. Pattern match against 15 known canned phrases (English + Hindi transliterated)
2. Verbatim repetition: same exact message 2+ times → auto-reply

On first detection: one polite probe ("Is the owner/manager available?").
On second detection: graceful exit, `action: "end"`.

### Intent-based reply routing
Every merchant reply is classified into: `ACTION`, `DISMISS`, `QUESTION`, `ENGAGED`, `UNKNOWN`.
- `ACTION` → switch to do-it mode immediately (no re-qualifying)
- `DISMISS` → graceful exit
- `QUESTION` → continue conversation with answer

### Conversation dedup
`vera_bodies` list tracks every sent message. Before returning a reply, the `is_body_repeated` check prevents verbatim repetition (−2 penalty in judge rubric).

---

## Tradeoffs

| Decision | Tradeoff |
|---|---|
| Single LLM call per compose | Simple, fast (<5s), but no multi-step retrieval |
| In-memory context store | No persistence across restarts (acceptable per brief) |
| Pattern-based auto-reply detection | Covers known patterns; novel auto-replies may slip through once |
| temperature=0 | Deterministic output; slightly less creative variation across ticks |

---

## What Additional Context Would Have Helped Most

1. **Real merchant conversation history** (3-5 turns) — the biggest driver of personalization is what was said last. The seed history has 0-2 turns; 10+ turns would let the composer avoid topic fatigue.
2. **Actual slot availability** for recall and booking triggers — the mock slots work for the test set but production needs real calendar data.
3. **Peer benchmark granularity** — having peer stats at `city × locality × plan-tier` rather than city-wide would sharpen the CTR/calls comparisons.
4. **Language detection per turn** — a merchant who writes in Hindi on turn 3 after English on turn 1 should shift the response language. Current implementation uses `identity.languages`, not per-turn detection.

---

## Submission Files

| File | Description |
|---|---|
| `bot.py` | FastAPI server + standalone `compose()` |
| `submission.jsonl` | 30 pre-composed test pairs (T01–T30) |
| `conversation_handlers.py` | Multi-turn `respond()` (§7.4 optional) |
| `README.md` | This file |
