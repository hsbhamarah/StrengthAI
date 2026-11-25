# Ingestion and mapping specification

## Inputs and boundaries

Accept coach-selected `.xlsx` files locally; Google Sheets by spreadsheet ID and read-only OAuth. `.xls` requires an explicit conversion path, not an implicit parser promise. Never execute macros, formulas, links, or workbook scripts. Parse cell *values* and preserve formula text only as inert lineage when present. Limit file size, sheet count, rows and cells before deep parsing; make limits configurable after reference workbook measurement.

## Canonical hierarchy

`athlete → block → week → session → exercise prescription → prescribed set / actual set`. A mapping can describe normalized tables, one row per set, wide tables with repeated set groups, or separate prescribed/actual worksheets. The coach maps semantic fields and grouping keys; parser code handles cell extraction but does not guess athlete identity across sources.

| Canonical field | Required when applicable | Source examples / rule |
| --- | --- | --- |
| athlete_id | Always | Assigned by selected athlete/source, never inferred from name cell alone. |
| block/week/session | Always | Explicit identifiers or approved sheet-name/date rules. Week key must be stable; dates are optional until the coach supplies them. |
| exercise_label | Training rows | Map to exercise ID through approved alias table; ambiguous variants block commit. |
| set_index / set_type | Set rows | Top, back-off, warm-up, other; preserve original ordering. |
| target_reps/load/RPE/RIR/%1RM/reference | If source contains them | Store independently; blanks remain null, not zero. Preserve imported units. |
| actual_reps/load/RPE/RIR/status | If source contains them | `completed`, `failed`, `skipped`, or no actual row (`unreported`). A zero-rep failed attempt is not skipped. |
| source coordinate/value | Every mapped record | Workbook/sheet/address, original text/display/value, parser and mapping version. |

## Mapping profile shape

For the supplied wide tracker, approved `sheet_mappings` select the two training tabs and their repeated week columns. A set with comma-separated limb values becomes two canonical set rows, in the coach-confirmed right-then-left order; a scalar value in that row applies to each limb. The shared Load column is used as actual load only when actual reps are present. Zero actual reps map to skipped for this source, with leftover performance cells retained only in raw lineage. Excel `d-m` formatted values in exercise target columns are interpreted as lower–upper ranges for Reps, RIR, or RPE, with the original cell retained. Other date formats require explicit `cell_overrides` by source coordinate. Training weeks use stable source week keys; dates may be assigned later.

Profiles are versioned JSON with `source_id`, `layout_fingerprint`, `worksheet_selectors`, `header_rows`, `row_regions`, `field_bindings`, `grouping_keys`, `unit_rules`, `exercise_aliases`, `missing_markers`, and `status_rules`. Each binding points to a column, cell pattern, named range or controlled expression from an allowlist (no arbitrary Python or formula execution). A layout fingerprint includes sheet names, header labels and relevant structural markers; change triggers preview/remap, not silent import.

Example mapping fragment (illustrative, not universal):

```json
{
  "worksheet_selectors": ["Week *"],
  "header_rows": [2],
  "row_regions": [{"start": 3, "stop_at_blank_key": "exercise"}],
  "field_bindings": {
    "exercise_label": {"column": "A"},
    "set_index": {"column": "B"},
    "target_reps": {"column": "C"},
    "actual_reps": {"column": "F"},
    "actual_rpe": {"column": "H"}
  },
  "grouping_keys": ["week", "session", "exercise_label", "set_index"],
  "unit_rules": {"load": "kg"},
  "missing_markers": ["", "-", "N/A"]
}
```

## Pipeline and idempotency

1. Snapshot file or fetched Sheet range and hash bytes/canonical cell values. Verify selected athlete/source identity.
2. Detect structure and suggest a mapping. Show sampled rows, converted values, confidence/ambiguity, warnings and blocking issues.
3. Coach approves a versioned profile. Commit requires matching source snapshot hash to prevent stale-preview commit.
4. Derive stable natural key from approved semantic keys (source + block/week/session/exercise/set type/index + record role); row address is lineage only. Hash normalized field values separately.
5. In one transaction, upsert unchanged records as no-ops; changed records create `record_revisions`, update canonical rows and invalidate affected metric snapshots. Deletions in a source snapshot are presented for review rather than silently deleting canonical history.
6. Queue bounded recalculation of affected athlete/week/exercise. Audit import ID, mapping version, source hash, counts and issues.

## Validation and exceptions

Blocking: unknown athlete/week, ambiguous exercise alias, duplicate semantic key, impossible unit conversion, malformed numeric fields, mismatched actual/prescription pairing, structural drift, or unexplained source deletion. Warning: missing actual, missing RPE, unrecognized note, sparse week, or unsupported optional field. Show cell coordinate and original value. Coach corrections are themselves versioned and never overwrite the raw source snapshot.

## Reference fixtures required before real-data sign-off

Two differently arranged workbooks; a wide and a long set layout; separate actual sheet; top plus back-off sets; percentage and RPE prescription; kg and lb; missing versus zero; failed versus skipped; inserted row; duplicate key; renamed sheet; changed RPE on re-import. Expected canonical rows and metric changes must be independently hand-checked with the coach.
