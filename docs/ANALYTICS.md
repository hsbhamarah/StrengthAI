# Deterministic analytics specification

**Method version:** `metrics-0.1.0` provisional. All outputs include unit, period, sample count, evidence IDs, missingness and method version. Calculate only from validated canonical rows. Use decimal arithmetic or explicitly defined rounding at display only. Preserve full precision in storage.

## Metric definitions

| Key | Definition | Eligible records / caveat |
| --- | --- | --- |
| `completed_sets` | Count actual sets with `status=completed`. | Excludes failed, skipped and unreported. |
| `failed_sets` | Count actual sets with `status=failed`. | A zero-rep failed attempt counts; skipped does not. |
| `completion_rate` | Completed prescribed sets ÷ prescribed work sets with known actual status. | Exclude warm-ups by default; disclose denominator and unreported count. Null if denominator zero. |
| `volume_load_kg` | Sum `actual_reps × actual_load_kg` for completed sets. | Exclude warm-ups by default and sets missing reps/load; report excluded count. Failed zero-rep contributes zero only if load/reps known. |
| `mean_rpe_deviation` | Arithmetic mean of `actual_rpe − target_rpe` over matched comparable sets with both values. | Null if no pairs; positive = harder than prescribed. |
| `rep_target_hit_rate` | Matched completed/failed sets meeting or exceeding target reps ÷ matched sets with known target and actual reps. | Exclude skipped and unreported; failed zero-rep stays in denominator. |
| `e1rm_kg` | **Provisional** Epley `load_kg × (1 + reps/30)` for eligible completed working sets; show maximum eligible estimate per exercise/period. | Default eligibility 1–10 reps, load >0, non-warm-up, exact exercise variant. This is an estimate, not a measured max. Formula/eligibility need coach approval. |
| `weekly_workload_change_pct` | `100 × (current volume − previous volume) / previous volume`. | Same exercise group and comparable week scope, previous >0; otherwise null. No automatic safety conclusion. |
| `recovery_status` | Derived check-in state per `RECOVERY_SHEETS.md`. | Missing does not imply poor recovery. |

RIR and RPE are retained independently; no implicit conversion. Percent prescriptions retain percent and reference 1RM, even when a target load is also present. Never group squat variations for e1RM or trend unless the coach approves an equivalence rule.

Prescribed rep, RPE, and RIR ranges retain separate lower and upper bounds. The provisional `mean_rpe_deviation` uses only scalar target RPE values; range-target comparisons require a coach-approved rule and must not silently substitute either bound or midpoint. An athlete-wide e1RM summary is insufficient when eligible records span multiple exercises or sides.

## Rule candidates (configurable, provisional)

- `RPE_OVERSHOOT_REVIEW`: at least 3 comparable, matched working sets across at least 2 exposures in the selected period with mean deviation ≥1.0; flag review, cite all sets. Do not automatically reduce load.
- `MISSED_REPS_REVIEW`: at least 2 matched sets below target reps in the period; flag and cite.
- `RECOVERY_MISSING`: check-in pending/incomplete/late; qualify weekly review, not a negative physiological finding.
- `SYMPTOM_REVIEW`: any reported new/worsening pain or instability; flag coach review and suppress unqualified progression suggestion.
- Insufficient sample: output `insufficient`, explain which records/fields are missing, and do not turn absence into a trend claim.

Thresholds must be reviewed with the coach and tested against real histories before release. Rules are signals for review, not medical diagnoses or autonomous programming actions.

## Independent test vectors

| Test | Inputs | Expected |
| --- | --- | --- |
| M-01 | Completed 5×100 kg and 3×120 kg, both working sets | Volume = 860 kg; completed = 2. |
| M-02 | Target RPE 7, 8; actual 8, 8.5; third actual lacks RPE | Mean deviation = (1 + 0.5)/2 = 0.75; sample = 2; third excluded. |
| M-03 | One completed 5 reps, one failed 0 reps, one skipped, one no actual | Completed = 1; failed = 1; skipped = 1; unreported = 1. No zero imputation for missing. |
| M-04 | 100 kg × 5 eligible set | Epley e1RM = 116.666… kg; display rounding rule TBD. |
| M-05 | 100 kg × 11; 100 kg × 5 warm-up; 100 kg × 5 failed | None eligible for e1RM; value null/state insufficient. |
| M-06 | Previous 1000 kg, current 1200 kg | Workload change = +20%. Previous zero gives null. |
| M-07 | Two exposures with three matched sets, RPE deviations 1, 1.5, 0.5 | Mean = 1.0; review flag with three evidence IDs. |
| M-08 | RPE deviations 2, 2, 2 from one exposure only | No persistent overshoot flag; insufficient exposure count. |
| M-09 | Current week has training actuals but no recovery row | Training metrics calculated; recovery pending/incomplete; weekly review incomplete. |
| M-10 | Correct actual RPE from 9 to 8 for target 8 | Recalculated deviation becomes 0; old source value remains in revision history. |
| M-11 | Separate `competition_squat` and `tempo_squat` sets | No combined e1RM trend without approved equivalence. |

Unit tests should construct canonical records independently of the parser. Integration tests then assert the same outcomes through two differently mapped workbook fixtures. Golden expected values must be reviewed manually; do not generate expected values with the same production functions under test.
