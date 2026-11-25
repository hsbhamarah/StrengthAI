"""Deterministic metrics over validated canonical set records."""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def compute(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def metric(key, value, unit, evidence):
        return {"key": key, "value": float(value) if value is not None else None, "unit": unit,
                "method_version": "metrics-0.1.0", "sample_count": len(evidence),
                "evidence_ids": evidence, "state": "valid" if value is not None else "insufficient"}

    completed = [r for r in rows if r.get("status") == "completed"]
    failed = [r for r in rows if r.get("status") == "failed"]
    work = [r for r in rows if r.get("set_type") != "warmup"]
    known = [r for r in work if r.get("status") in ("completed", "failed", "skipped")]
    volume_rows = [r for r in completed if r.get("set_type") != "warmup" and r.get("reps") is not None and r.get("load_kg") is not None]
    volume = sum((Decimal(str(r["reps"])) * Decimal(str(r["load_kg"])) for r in volume_rows), Decimal(0))
    rpe_rows = [r for r in rows if r.get("actual_rpe") is not None and r.get("target_rpe") is not None]
    deviation = sum((Decimal(str(r["actual_rpe"])) - Decimal(str(r["target_rpe"])) for r in rpe_rows), Decimal(0)) / len(rpe_rows) if rpe_rows else None
    eligible = [r for r in volume_rows if 1 <= r["reps"] <= 10 and r["load_kg"] > 0]
    comparable_groups = {(r.get("exercise_id"), r.get("side", "both")) for r in eligible}
    estimates = [(Decimal(str(r["load_kg"])) * (1 + Decimal(str(r["reps"])) / 30), r["id"]) for r in eligible] if len(comparable_groups) <= 1 else []
    best = max(estimates, default=None)
    return [
        metric("completed_sets", len(completed), "sets", [r["id"] for r in completed]),
        metric("failed_sets", len(failed), "sets", [r["id"] for r in failed]),
        metric("completion_rate", Decimal(len([r for r in known if r["status"] == "completed"])) / len(known) if known else None, "ratio", [r["id"] for r in known]),
        metric("volume_load_kg", volume, "kg", [r["id"] for r in volume_rows]),
        metric("mean_rpe_deviation", deviation, "RPE", [r["id"] for r in rpe_rows]),
        metric("e1rm_kg", best[0] if best else None, "kg", [best[1]] if best else []),
    ]
