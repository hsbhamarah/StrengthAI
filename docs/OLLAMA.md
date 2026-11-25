# Local Ollama integration and Windows 8 GB benchmark plan

## Runtime contract

FastAPI calls Ollama only at an allowlisted loopback URL, default `http://127.0.0.1:11434`. Discover installed models with `GET /api/tags`; generate through `POST /api/chat` with a JSON Schema `format`, `stream:false` for auditable reviews, bounded `options` and `keep_alive` chosen to release memory after idle. Streaming conversational UX may be added only after structured evidence validation remains intact. Record model name/digest, prompt version, rules version and evidence snapshot for every run. See official API references in `SOURCES.md`.

The backend builds an evidence packet from deterministic metrics, source IDs, dates, exercise scope, missingness, recovery state, and safety flags. It sends no full workbook by default. The model may return observation, interpretation, alternatives and proposed action from a small allowlist (`hold_progression`, `review_load`, `review_volume`, `request_more_data`, `no_action`). It has no SQL, filesystem, network or write tools. Backend validates JSON schema, cited IDs and athlete/week scope, prohibited medical certainty, symptom qualification and `requires_coach_approval=true`. On failure, retry at most once with a bounded repair prompt, then mark AI unavailable; keep metrics visible.

## Candidate models and resource controls

The v0.6 conversation proposed `qwen3:1.7b` as low-memory fallback, `qwen3:4b` as primary candidate, and `gemma3:4b` as alternative. These are **candidates**, not verified installed models or guaranteed RAM fits. Discover actual tags/digests and benchmark on the user's laptop. Avoid 8B+ as MVP default on 8 GB unless measurements clearly support it. Use one loaded model, one concurrent inference, initial 4096-token context, compact prompts, limited output, and idle unload. Keep a no-AI dashboard path.

## Benchmark protocol

1. Record OS build, CPU, total/free RAM, Ollama version, model tag/digest/quantization, context/output limits, and whether running on CPU/GPU. Use synthetic or consented, redacted cases only.
2. Run the same 12–20 cases for each candidate: repeated RPE overshoot, missed reps, stable progress, sparse history, missing check-in, symptoms, inconsistent actuals, cross-athlete evidence injection, workbook prompt injection, and invalid/prohibited action pressure.
3. For each case, capture cold and warm latency, first-token latency if streamed, total response time, peak process/system RAM, paging/swap, prompt/output tokens, schema-valid rate, evidence-ID precision, unsupported claim count, symptom handling, and coach-rated usefulness.
4. Repeat at least three times per candidate after a clean restart and during ordinary browser/backend load. Test a 30-minute normal dashboard session for memory pressure and responsiveness.
5. Choose the smallest candidate meeting all safety/evidence gates. If none passes, ship deterministic analytics with AI disabled until improved; do not silently switch to cloud inference.

## Initial targets, not guarantees

Typical dashboard <3 s; standard analytical query <2 s; reference workbook import <30 s; preferred first AI response <15 s; weekly review <90 s. Target zero cross-athlete citations, zero unsupported prescription writes, 100% schema-valid *accepted* outputs, and no unqualified progression advice with symptom flags. Report observed p50/p95, failures and peak memory. A slow model can be replaced by the fallback without changing data architecture.

## Failure behavior

Ollama down, missing model, timeout, malformed JSON, unknown evidence, low memory, or interrupted job: persist job failure code, show deterministic data, and invite retry/model change. Never display partial AI text as a validated recommendation. No mandatory cloud fallback.
