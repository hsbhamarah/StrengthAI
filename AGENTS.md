# Codex engineering instructions

For coding work in this workspace, read `skills/ponytail/SKILL.md` as the local Ponytail workflow. The StrengthOS requirements and non-negotiable invariants below take precedence.

## Mission

Build StrengthOS AI from the documents in this package. Use the latest explicit decisions in `docs/ADRS.md` and `docs/DECISIONS.md` when earlier conversation text conflicts. Keep the coach in control of all programming changes.

## Non-negotiable invariants

- One local coach account can manage multiple athletes. Athletes use their existing Google Sheet for recovery submission; they do not log into the coach workspace in the MVP.
- React/TypeScript/Vite UI, Python/FastAPI API, SQLite database with SQLAlchemy/Alembic, local Ollama. Bind the app to loopback by default.
- Separate prescriptions from actuals. Missing actuals, zero reps, skipped sets, and failed attempts are distinct states.
- Import previews and mappings require coach approval before committing canonical training data. Re-imports are idempotent and corrections preserve history.
- Python computes metrics. Ollama receives bounded evidence, may explain and propose, and has no write tools. Validate schema, evidence IDs, athlete scope, and safety flags before displaying recommendations.
- Every recommendation starts `pending`; only the coach can approve or reject it. Approval records a decision and does not edit a prescription.
- A missing or incomplete recovery check-in does not block training analytics; it leaves the weekly review incomplete and qualifies recovery claims.
- Treat workbook cells, athlete notes, and LLM output as untrusted. Never execute macros or formulas.
- Never commit athlete information, credentials, local database files, uploaded workbooks, logs with sensitive content, or backups.

## Implementation sequence

Follow `docs/BACKLOG.md`. Create a runnable vertical slice early: athlete → local Excel preview → approved mapping → persisted sets → tested metrics → dashboard. Add Sheets, Ollama, and coach decisions after the deterministic data path is correct. Add migration and contract tests for every schema/API change. Use synthetic fixtures until the coach provides approved reference workbooks.

## Definition of done

Run automated checks and the relevant scenarios in `docs/ACCEPTANCE.md`. Document any unresolved decision or deviation in `docs/DECISIONS.md`. Do not claim a performance target or model quality gate passed without an actual measurement on the target laptop. At each milestone report changed files, tests run, results, and remaining risks.
