# Security and privacy controls

## Boundaries and data flow

Coach browser → FastAPI on loopback → SQLite/files and Ollama on loopback. Google Sheets API is the only routine external data path. Athlete-entered workbook text, notes and check-ins are untrusted input. Recovery and symptom notes are sensitive; minimize and restrict them.

| Control | MVP implementation and verification |
| --- | --- |
| Local exposure | Bind FastAPI to `127.0.0.1`; confirm Ollama is loopback-only; disable public port forwarding and broad CORS. Verify listening addresses on Windows. |
| Coach authentication | One local coach email and password, modern password hash (Argon2id or equivalent), rate-limited login, HttpOnly SameSite session cookie, CSRF protection for mutations, session expiry. No default credentials in package. |
| Authorization | Every athlete-scoped API query checks selected athlete ownership within the local coach account. Google source ID must match athlete. AI evidence IDs validated against the same scope. |
| Google OAuth | Desktop installed-app flow with state/PKCE where supported; read-only Sheets scope; protect refresh token using Windows credential protection/DPAPI; never log tokens; support disconnect/revoke. Do not place client secrets or token JSON in repo. |
| Spreadsheet input | Allowlisted file types and size/row/cell limits; parse without executing macros/formulas or external links; store uploads outside web root; reject archive bombs and malformed files gracefully. |
| Prompt injection | Treat spreadsheet cells and athlete notes as quoted data; model gets only bounded evidence; no general tool execution; validate output schema, evidence IDs and action allowlist. |
| Data integrity | SQLite foreign keys, transactions, import snapshot hashes, revision history, append-only audit events, idempotent jobs, selective recomputation. |
| Backups | Encrypted backups to coach-selected external location; use consistent SQLite backup API; include necessary source/mapping files; test restore to a clean instance and document key recovery. |
| Logs | Avoid raw workbooks, credentials, full AI prompts, symptom narratives and athlete names by default. Use request/job IDs and redacted structured errors. |
| Retention/deletion | Coach-configurable policy after O-05 decision; document what is retained in revisions/backups and support deletion/export workflow before real-data release. |
| Dependency supply chain | Pin versions, review updates, use dependency scanning, and do not fetch models/dependencies silently during app use. |

## Safety behavior

The system offers coaching review support, not a diagnosis. New/worsening pain or instability generates a prominent coach-review state and prevents unqualified load-progression advice. The coach must review the source check-in and decide next steps. Missing recovery input is labelled missing; it is never interpreted as good or bad recovery.

## Release checks

Attempt cross-athlete API and evidence-ID access; test CSRF and unauthenticated mutations; import malicious-looking formula/note text; verify no code execution or prompt instruction following; inspect listeners and logs; disconnect Google and test token removal; restore encrypted backup; confirm any recommendation decision leaves prescriptions unchanged.
