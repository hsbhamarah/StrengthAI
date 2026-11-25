# Google Sheets weekly recovery check-in contract

**Chosen access:** athletes enter data in their existing Google Sheet; the local app reads through the coach's authorized Google account. The app does not host a public athlete form and does not write to Sheets in MVP.

## Template worksheet

Dedicated tab: `Recovery Check-in`. One row per athlete training week; row 1 contains stable machine-readable headers. Protect headers/data-validation cells where feasible in the source workbook. A workbook belongs to one mapped athlete; `athlete_id` is assigned from the connection, not trusted from editable cells.

| Header | Required | Type and validation | Meaning |
| --- | --- | --- | --- |
| `week_key` | Yes | Unique nonblank text matching mapped training week | Stable identity; not row number. |
| `submitted_at` | Yes* | ISO 8601 date/time or agreed local date | Athlete-entered claim, not independently auditable timestamp. *If absent, mark incomplete; `observed_at` is still recorded by sync. |
| `sleep_hours` | Yes | Decimal 0–24 | Average hours/night for the week. |
| `sleep_quality` | Yes | Integer 1–5; 1 very poor, 5 very good | Subjective quality. |
| `soreness` | Yes | Integer 1–5; 1 none, 5 severe | Higher = more soreness. |
| `stress` | Yes | Integer 1–5; 1 very low, 5 very high | Higher = more stress. |
| `readiness` | Yes | Integer 1–5; 1 very low, 5 very high | Higher = more ready. |
| `pain_instability` | Yes | `Yes` / `No` | New or worsening pain, instability or injury symptoms. |
| `symptom_details` | Conditional | Nonblank text if `pain_instability=Yes` | Coach review context; minimize collection. |
| `comments` | No | Text, bounded length | Additional athlete context. |

Example synthetic row: `B1-W05 | 2026-11-16T08:00:00+05:30 | 7.0 | 4 | 2 | 3 | 4 | No |  | Training felt normal`.

## Synchronization

1. Coach authorizes desktop OAuth using read-only Sheets scope and selects/enters an athlete-shared spreadsheet ID. Record which Google account and sheet ID are linked, without logging tokens.
2. Fetch only approved worksheet ranges. Validate header fingerprint before parsing. Drift produces a mapping exception; last good local snapshot remains available.
3. Map `week_key` to exactly one athlete week. Validate every field. Record `observed_at` as app's UTC fetch time separately from claimed `submitted_at`.
4. Hash normalized row content. Unchanged sync is a no-op; changed row creates a recovery revision and recalculates affected review state. A missing row after prior import is an exception, not immediate deletion.
5. Manual sync is P0. Polling is P1 and runs only while the application is open; show last successful sync and any connectivity/auth error.

## State derivation

State priority: `review_required` if valid row reports symptoms needing attention; else `incomplete` if row exists but required fields fail; else `late` if complete and a trustworthy deadline comparison can be made using *claimed* submission time; else `complete`; else `pending` when due and row absent; else `not_due`. The UI must disclose that `late` is based on an athlete-entered time. If only `observed_at` is known, show `complete` with `first_seen_after_deadline` metadata rather than claiming actual late submission.

**Weekly review gate:** missing/incomplete row keeps review incomplete but does not suppress training metrics. Symptom reports trigger a prominent coach-review flag and qualified AI wording. A revised check-in retains the earlier payload.

When a training week has no dates or due timestamp, the app cannot classify an absent check-in as due or late. Training import and metrics still run; deadline-related recovery status remains undetermined until the coach supplies a due rule.

## Google access limits

Use least-privilege `spreadsheets.readonly` for known IDs and no Drive discovery by default. Google documents that this scope can read all Sheets the authorizing account can access; it cannot be narrowed to a worksheet, so enforce selected spreadsheet IDs in the application and document this to the coach. `drive.file` is per-file but allows write operations; it is an alternative only if a file picker flow is explicitly designed and approved. See `SOURCES.md`.

## Acceptance examples

Valid row attaches to correct athlete/week; wrong/duplicate week key blocks import; `Yes` without details is incomplete and flags review; value 6 for readiness is invalid; a changed row creates revision; missing check-in preserves training analytics; network outage retains last good data and displays stale sync state.
