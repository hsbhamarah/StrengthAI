# Client portal API contract

All paths use `/api/v1`. Public operations: `POST /auth/login` (email, password, optional coach MFA code), `POST /auth/invites/accept` (single-use token and new password), and `GET /health`. A successful login returns a CSRF token and sets an HTTP-only session cookie. All subsequent writes require `X-CSRF-Token` and same Origin. `GET /auth/me`, `GET /auth/sessions`, `POST /auth/sessions/revoke-others`, `POST /auth/logout`, and `POST /auth/password` require a session.

Coach-only operations:

| Method and path | Result |
| --- | --- |
| `GET/POST /athletes` | List or create clients. |
| `POST /athletes/{id}/invites` | Return a one-time, 72-hour invite URL. |
| `POST /invites/{id}/revoke`, `POST /athletes/{id}/deactivate` | Revoke invite or client access. |
| `GET/POST /templates`, `PUT /templates/{id}`, `POST /templates/{id}/clone` | Manage reusable drafts. |
| `POST /templates/{id}/publish`, `GET /templates/{id}/versions` | Create and list immutable versions. |
| `POST /versions/{id}/assign` | Assign a version to unique athlete IDs with an ISO start date. |
| `POST /template-imports`, `POST /template-imports/{id}/preview`, `POST /template-imports/{id}/approve` | Upload, preview, and explicitly convert an Excel workbook into drafts. Approval requires matching content and mapping hashes. |
| `GET /athletes/{id}/program`, `GET /athletes/{id}/analytics`, `GET /athletes/{id}/history`, `GET /audit` | Inspect programs, deterministic metrics, revisions, and audit metadata. |

Client-only operations: `GET /me/program`, `PUT /me/sets/{id}`, and `PUT /me/recovery/{week_id}`. A client can access only records in their own published assignments. Set status is `completed`, `failed`, `skipped`, or `unreported`; a missing actual is `null`. Completed requires positive reps, failed requires zero reps, and skipped/unreported have no performance values. Recovery accepts optional sleep hours, readiness 1–10, and a pain/concerns note. Missing or incomplete recovery leaves training analytics available and the weekly review incomplete.

Program drafts use `weeks[] → sessions[] → exercises[] → sets[]`. Sessions have a day offset 0–6 from the week's start. Sets carry target reps/load/RPE/RIR and optional bounds, side, type, and set index. Publishing validates a nonempty program; assignment materializes distinct prescription records per client. Template edits never mutate a published version or recorded actuals.
