"""Inert workbook inspection and explicit column mapping.

Only cached cell values are read. Formula text is never evaluated.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import date, time
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.cell import column_index_from_string, get_column_letter

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_SHEETS = 30
MAX_ROWS = 20000
MAX_COLUMNS = 200


class WorkbookLimitError(ValueError):
    pass

FIELDS = (
    "block", "week", "session", "exercise_label", "set_index", "set_type",
    "target_reps", "target_load", "target_rpe", "target_rir", "percent_1rm",
    "reference_1rm", "actual_reps", "actual_load", "actual_rpe", "actual_rir",
    "actual_status",
)
REQUIRED = {"block", "week", "session", "exercise_label", "set_index"}


def inspect_workbook(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_UPLOAD_BYTES:
        raise WorkbookLimitError("Workbook exceeds 10 MB")
    if not data[:4] == b"PK\x03\x04":
        raise ValueError("Only valid .xlsx archives are supported")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if len(archive.infolist()) > 1000 or sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024:
                raise WorkbookLimitError("Workbook archive exceeds the 100 MB expansion or 1,000-entry limit")
    except zipfile.BadZipFile:
        raise ValueError("Malformed workbook archive") from None
    book = load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
    if len(book.worksheets) > MAX_SHEETS:
        raise WorkbookLimitError(f"Workbook has more than {MAX_SHEETS} worksheets")
    sheets = []
    samples = []
    issues = []
    wide_sheets = []
    headers = []
    correction_cells = []
    for sheet_number, sheet in enumerate(book.worksheets, start=1):
        # Some producer workbooks omit worksheet dimension metadata. openpyxl
        # then reports None until it scans the sheet in read-only mode.
        if sheet.max_row is None or sheet.max_column is None:
            sheet.calculate_dimension(force=True)
        if sheet.max_row > MAX_ROWS or sheet.max_column > MAX_COLUMNS:
            raise WorkbookLimitError(f"Worksheet {sheet_number} has {sheet.max_row} rows and {sheet.max_column} columns; limits are {MAX_ROWS:,} rows and {MAX_COLUMNS} columns")
        sheets.append(sheet.title)
        top_rows = list(sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 16), values_only=True))
        first_row = top_rows[0] if top_rows else ()
        second_row = top_rows[1] if len(top_rows) > 1 else ()
        headers.append({"sheet": sheet.title, "row1": first_row, "row2": second_row})
        for header_index, row in enumerate(top_rows[:-1]):
            following = top_rows[header_index + 1]
            week_columns = [get_column_letter(index) for index, value in enumerate(row, start=1)
                            if isinstance(value, str) and re.fullmatch(r"week\s*\d+", value.strip(), re.IGNORECASE)
                            and index <= len(following) and str(following[index - 1]).strip().lower() == "sets"]
            if not week_columns:
                continue
            exercise_column = next((get_column_letter(index) for index, value in enumerate(following[:4], start=1)
                                    if isinstance(value, str) and value.strip().lower() == "exercise"), "B")
            day_column = next((get_column_letter(index) for sample in top_rows[header_index + 2:]
                               for index, value in enumerate(sample[:4], start=1)
                               if isinstance(value, str) and re.match(r"day\s*\d+\b", value.strip(), re.IGNORECASE)), "A")
            wide_sheets.append({"sheet": sheet.title, "week_columns": week_columns,
                                "week_header_row": header_index + 1, "header_row": header_index + 2,
                                "session_column": day_column, "exercise_column": exercise_column,
                                "set_index_mode": "row_order", "block_label": ""})
            break
        for row_number, row in enumerate(sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 12)), start=1):
            samples.append({"sheet": sheet.title, "row": row_number, "cells": {cell.coordinate: cell.value for cell in row if cell.value is not None}})
    if not sheets:
        issues.append({"severity": "blocking", "code": "empty_workbook", "location": "workbook", "message": "No worksheets found"})
    fingerprint = hashlib.sha256(json.dumps(headers, sort_keys=True, default=str).encode()).hexdigest()
    proposed = None
    if wide_sheets:
        proposed = {"layout": "wide_week_grid", "schema_version": 2, "sheet_mappings": wide_sheets,
                    "header_row": 2, "week_header_row": 1, "block_label": "",
                    "week_dates": {}, "exercise_aliases": {}, "load_unit": "kg",
                    "zero_actual_status": None, "cell_overrides": {}, "actual_status_overrides": {}}
        candidate_rows = extract_rows(data, {**proposed, "block_label": "preview"})
        proposed["exercise_aliases"] = {label: label for label in sorted({row["exercise_label"] for row in candidate_rows})}
        issues.append({"severity": "warning", "code": "wide_layout", "location": "workbook",
                       "message": "Repeated week grids detected. Approve their sheet mappings, week dates, block label, and exercise aliases before import."})
        ranged_reps = [row for row in candidate_rows if row.get("target_reps_min") is not None]
        ranged_targets = [row for row in candidate_rows if row.get("target_rpe_min") is not None]
        if ranged_reps or ranged_targets:
            issues.append({"severity": "warning", "code": "date_formatted_ranges", "location": "training grids",
                           "message": f"Recovered {len(ranged_reps)} rep ranges and {len(ranged_targets)} RPE ranges from d-m formatted cells; review the displayed bounds."})
        unresolved_dates = [(row, field, offset) for row in candidate_rows
                            for field, offset in (("target_reps", 1), ("target_rpe", 3), ("target_rir", 3))
                            if isinstance(row.get(field), (date, time))]
        if unresolved_dates:
            correction_cells = list({f"{row['_sheet']}!{row['_source_columns'][offset]}":
                                     {"location": f"{row['_sheet']}!{row['_source_columns'][offset]}", "raw_value": str(row[field])}
                                     for row, field, offset in unresolved_dates}.values())
            first, _, offset = unresolved_dates[0]
            issues.append({"severity": "blocking", "code": "unresolved_target_date", "location": f"{first['_sheet']}!{first['_source_columns'][offset]}",
                           "message": f"{len(correction_cells)} target cells contain date/time values without a supported range format; correct them before commit."})
        zero_reps = [row for row in candidate_rows if row.get("_zero_actual_was_skipped")]
        if zero_reps:
            issues.append({"severity": "warning", "code": "zero_actual_skipped", "location": f"{zero_reps[0]['_sheet']}!{zero_reps[0]['_source_columns'][4]}",
                           "message": f"{len(zero_reps)} zero-rep actuals are mapped to skipped under the coach-approved rule; original values remain in lineage."})
    return {
        "sheets": sheets, "sample_rows": samples, "issues": issues,
        "correction_cells": correction_cells,
        "layout_fingerprint": fingerprint,
        "proposed_mapping": proposed,
        "can_commit": False,
    }


def validate_mapping(mapping: dict[str, Any], sheets: list[str]) -> None:
    if mapping.get("schema_version", 1) not in (1, 2):
        raise ValueError("Unsupported mapping schema version")
    layout = mapping.get("layout", "row_per_set")
    if layout == "wide_week_grid":
        groups_by_sheet = mapping.get("sheet_mappings")
        if groups_by_sheet is None:
            groups_by_sheet = [{"sheet": mapping.get("sheet"), "week_columns": mapping.get("week_columns")}]
        if not isinstance(groups_by_sheet, list) or not groups_by_sheet:
            raise ValueError("Wide mapping requires sheet_mappings")
        for group in groups_by_sheet:
            if not isinstance(group, dict) or group.get("sheet") not in sheets:
                raise ValueError("Mapping worksheet is absent")
            columns = group.get("week_columns")
            if not isinstance(columns, list) or not columns or any(not isinstance(col, str) or not col.isalpha() or column_index_from_string(col.upper()) > MAX_COLUMNS for col in columns):
                raise ValueError("Wide mapping requires week_columns")
            for row_field in ("header_row", "week_header_row"):
                row_number = group.get(row_field, mapping.get(row_field, 1 if row_field == "week_header_row" else None))
                if not isinstance(row_number, int) or not 1 <= row_number <= MAX_ROWS:
                    raise ValueError(f"{row_field} must be a valid worksheet row")
            for column_field in ("session_column", "exercise_column"):
                column = group.get(column_field, "A" if column_field == "session_column" else "B")
                if not isinstance(column, str) or not column.isalpha() or column_index_from_string(column.upper()) > MAX_COLUMNS:
                    raise ValueError(f"{column_field} must be a valid worksheet column")
            block = group.get("block_label") or mapping.get("block_label")
            if not isinstance(block, str) or not block.strip():
                raise ValueError("Each training sheet needs an approved block label")
            if group.get("set_index_mode", "cell_index") not in ("cell_index", "row_order"):
                raise ValueError("Set index mode must be cell_index or row_order")
    elif layout == "row_per_set":
        if mapping.get("sheet") not in sheets:
            raise ValueError("Mapping worksheet is absent")
        if not REQUIRED.issubset(mapping.get("columns", {})):
            raise ValueError("Block, week, session, exercise and set index columns are required")
    else:
        raise ValueError("Unknown mapping layout")
    if not isinstance(mapping.get("header_row"), int) or mapping["header_row"] < 1:
        raise ValueError("header_row must be a positive integer")
    for field, column in mapping.get("columns", {}).items():
        if field not in FIELDS or not isinstance(column, str) or not column.isalpha() or len(column) > 2:
            raise ValueError(f"Invalid binding: {field}")
    if mapping.get("load_unit", "kg") not in ("kg", "lb"):
        raise ValueError("load_unit must be kg or lb")
    if mapping.get("zero_actual_status") not in (None, "skipped"):
        raise ValueError("Unsupported zero actual status rule")
    if not isinstance(mapping.get("cell_overrides", {}), dict):
        raise ValueError("cell_overrides must be an object")
    if not isinstance(mapping.get("actual_status_overrides", {}), dict) or any(
        status not in ("failed", "skipped", "unreported") for status in mapping.get("actual_status_overrides", {}).values()
    ):
        raise ValueError("actual_status_overrides must contain failed, skipped or unreported")
    if not isinstance(mapping.get("exercise_aliases", {}), dict):
        raise ValueError("exercise_aliases must be an object")


def extract_rows(data: bytes, mapping: dict[str, Any]) -> list[dict[str, Any]]:
    book = load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
    if mapping.get("layout") == "wide_week_grid":
        groups_by_sheet = mapping.get("sheet_mappings") or [{"sheet": mapping["sheet"], "week_columns": mapping["week_columns"]}]
        output = []
        for group in groups_by_sheet:
            sheet = book[group["sheet"]]
            if sheet.max_row is None or sheet.max_column is None:
                sheet.calculate_dimension(force=True)
            output.extend(_extract_wide_week_grid(sheet, {**mapping, **group, "block_label": group.get("block_label") or mapping.get("block_label")}))
        return output
    sheet = book[mapping["sheet"]]
    if sheet.max_row is None or sheet.max_column is None:
        sheet.calculate_dimension(force=True)
    columns = mapping["columns"]
    indices = {field: column_index_from_string(col.upper()) - 1 for field, col in columns.items()}
    output = []
    for row_number, row in enumerate(sheet.iter_rows(min_row=mapping["header_row"] + 1, max_row=min(sheet.max_row, MAX_ROWS), values_only=False), start=mapping["header_row"] + 1):
        values = {field: row[index].value if index < len(row) else None for field, index in indices.items()}
        if all(value is None for value in values.values()):
            continue
        values["_sheet"] = sheet.title
        values["_row"] = row_number
        values["_field_locations"] = {field: f"{get_column_letter(index + 1)}{row_number}" for field, index in indices.items()}
        for field, coordinate in values["_field_locations"].items():
            location = f"{sheet.title}!{coordinate}"
            if location in mapping.get("cell_overrides", {}):
                values[f"_raw_{field}"] = str(values[field])
                values[field] = mapping["cell_overrides"][location]
                if field == "actual_reps" and values[field] is None:
                    for actual_field in ("actual_load", "actual_rpe", "actual_rir"):
                        values[f"_raw_{actual_field}"] = values.get(actual_field)
                        values[actual_field] = None
            if field == "actual_reps" and location in mapping.get("actual_status_overrides", {}):
                status = mapping["actual_status_overrides"][location]
                values["actual_status"] = None if status == "unreported" else status
                if status in ("skipped", "unreported"):
                    for actual_field in ("actual_reps", "actual_load", "actual_rpe", "actual_rir"):
                        values[f"_raw_{actual_field}"] = values.get(actual_field)
                        values[actual_field] = None
        output.append(values)
    return output


def mapping_fingerprint(data: bytes, mapping: dict[str, Any], legacy_fingerprint: str) -> str:
    if mapping.get("schema_version", 1) < 2 or mapping.get("layout") != "wide_week_grid":
        return legacy_fingerprint
    book = load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
    structure = []
    for group in mapping["sheet_mappings"]:
        sheet = book[group["sheet"]]
        week_row = group.get("week_header_row", mapping.get("week_header_row", 1))
        set_row = group.get("header_row", mapping["header_row"])
        columns = [column_index_from_string(value.upper()) for value in group["week_columns"]]
        day_column = column_index_from_string(group.get("session_column", "A").upper())
        day_marker = next(((index, re.match(r"day\s*\d+", str(row[0].value).strip(), re.IGNORECASE).group(0).lower())
                           for index, row in enumerate(sheet.iter_rows(min_row=set_row + 1, max_row=min(set_row + 50, sheet.max_row or set_row + 50),
                                                                      min_col=day_column, max_col=day_column), start=set_row + 1)
                           if row[0].value is not None and re.match(r"day\s*\d+", str(row[0].value).strip(), re.IGNORECASE)), None)
        structure.append({"sheet": sheet.title, "week_row": week_row, "set_row": set_row,
                          "session_column": group.get("session_column", "A"), "exercise_column": group.get("exercise_column", "B"),
                          "weeks": [(sheet.cell(week_row, col).value, sheet.cell(set_row, col).value) for col in columns],
                          "exercise_header": sheet[f"{group.get('exercise_column', 'B')}{set_row}"].value,
                          "first_day_marker": day_marker})
    book.close()
    return hashlib.sha256(json.dumps(structure, sort_keys=True, default=str).encode()).hexdigest()


def _extract_wide_week_grid(sheet, mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten explicit week groups; leave ambiguous values for commit validation."""
    week_header_row = mapping.get("week_header_row", 1)
    session = None
    exercise = None
    session_index = column_index_from_string(mapping.get("session_column", "A").upper()) - 1
    exercise_index = column_index_from_string(mapping.get("exercise_column", "B").upper()) - 1
    output = []
    groups = []
    row_ordinals: dict[tuple[str, str, str], int] = {}
    for column in mapping["week_columns"]:
        index = column_index_from_string(column.upper())
        label = sheet.cell(week_header_row, index).value
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"Week label missing at {column}{week_header_row}")
        groups.append((index, label.strip()))
    max_col = max(max(index + 5 for index, _ in groups), session_index + 1, exercise_index + 1)
    for row_number, cells in enumerate(sheet.iter_rows(min_row=mapping["header_row"] + 1, max_row=min(sheet.max_row, MAX_ROWS), max_col=max_col, values_only=False), start=mapping["header_row"] + 1):
        section = cells[session_index].value
        movement = cells[exercise_index].value
        day = re.match(r"(day\s*\d+)\b", section.strip(), re.IGNORECASE) if isinstance(section, str) else None
        if day:
            session = day.group(1)
            exercise = None
        if isinstance(movement, str) and movement.strip() and not day:
            exercise = movement.strip()
        if not session or not exercise:
            continue
        for index, week in groups:
            set_label = cells[index - 1].value
            match = re.fullmatch(r"set\s*(\d+)", str(set_label).strip(), re.IGNORECASE) if set_label is not None else None
            numeric = int(set_label) if isinstance(set_label, (int, float)) and set_label > 0 and float(set_label).is_integer() else None
            if mapping.get("set_index_mode") == "row_order" and numeric is not None:
                ordinal_key = (week, session, exercise)
                set_index = row_ordinals.get(ordinal_key, 0) + 1
                row_ordinals[ordinal_key] = set_index
            else:
                set_index = numeric if numeric is not None else int(match.group(1)) if match else None
            if set_index is None:
                continue
            reps_cell = cells[index]
            target_cell = cells[index + 2]
            target = target_cell.value
            target_rpe, target_rir = target, None
            target_rir_min = target_rir_max = None
            if isinstance(target, str) and target.strip().upper().startswith("RIR"):
                target_rpe, target_rir = None, target.strip()[3:].strip()
                rir_range = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)", target_rir)
                if rir_range:
                    target_rir_min, target_rir_max = map(float, rir_range.groups())
                    target_rir = None
            reps_range = _date_formatted_range(reps_cell) or _numeric_range(reps_cell.value)
            rpe_range = _date_formatted_range(target_cell) or _numeric_range(target_cell.value)
            actual_reps = cells[index + 3].value
            load = cells[index + 1].value
            extracted = {
                "block": mapping["block_label"], "week": week, "session": session,
                "exercise_label": exercise, "set_index": set_index,
                "set_type": "other", "target_reps": None if reps_range else reps_cell.value,
                "target_reps_min": reps_range[0] if reps_range else None,
                "target_reps_max": reps_range[1] if reps_range else None,
                "target_load": load,
                "target_rpe": None if rpe_range else target_rpe, "target_rir": target_rir,
                "target_rpe_min": rpe_range[0] if rpe_range else None,
                "target_rpe_max": rpe_range[1] if rpe_range else None,
                "target_rir_min": target_rir_min, "target_rir_max": target_rir_max,
                "actual_reps": actual_reps,
                "actual_rpe": cells[index + 4].value,
                "actual_load": load if actual_reps is not None else None,
                "_sheet": sheet.title, "_row": row_number,
                "_source_columns": [f"{get_column_letter(index + offset)}{row_number}" for offset in range(6)],
            }
            if mapping.get("set_index_mode") == "row_order" and numeric is not None and numeric != 1:
                extracted["_set_count_issue"] = True
            if reps_range:
                extracted["_raw_target_reps"] = str(reps_cell.value)
            if rpe_range:
                extracted["_raw_target_rpe"] = str(target_cell.value)
            for field, offset in (("target_reps", 1), ("target_load", 2), ("target_rpe", 3),
                                  ("actual_reps", 4), ("actual_rpe", 5)):
                override_key = f"{sheet.title}!{get_column_letter(index + offset)}{row_number}"
                if override_key in mapping.get("cell_overrides", {}):
                    extracted[f"_raw_{field}"] = str(extracted[field])
                    extracted[field] = mapping["cell_overrides"][override_key]
                    if field == "target_load" and extracted["actual_reps"] is not None:
                        extracted["actual_load"] = extracted[field]
                    if field == "actual_reps" and extracted[field] is None:
                        extracted["_raw_actual_rpe"] = extracted["actual_rpe"]
                        extracted["actual_load"] = extracted["actual_rpe"] = None
            paired_fields = ("target_reps", "target_load", "target_rpe", "target_rir", "actual_reps", "actual_load", "actual_rpe")
            splits = {}
            for field in paired_fields:
                value = extracted[field]
                if isinstance(value, str) and "," in value:
                    pieces = [piece.strip() for piece in value.split(",")]
                    if len(pieces) == 2 and all(pieces):
                        splits[field] = pieces
            if splits:
                for ordinal, side in enumerate(("right", "left")):
                    side_row = dict(extracted)
                    side_row["side"] = side
                    for field, pieces in splits.items():
                        side_row[field] = pieces[ordinal]
                    _apply_zero_actual_rule(side_row, mapping)
                    output.append(side_row)
            else:
                extracted["side"] = "both"
                _apply_zero_actual_rule(extracted, mapping)
                output.append(extracted)
    return output


def _date_formatted_range(cell) -> tuple[int, int] | None:
    value = cell.value
    if not isinstance(value, date) or cell.number_format.lower().strip() != "d-m":
        return None
    low, high = value.day, value.month
    if low > high:
        return None
    return low, high


def _numeric_range(value) -> tuple[float, float] | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*", value)
    if not match:
        return None
    lower, upper = map(float, match.groups())
    return (lower, upper) if lower <= upper else None


def _apply_zero_actual_rule(row: dict[str, Any], mapping: dict[str, Any]) -> None:
    actual_location = f"{row['_sheet']}!{row['_source_columns'][4]}"
    status = mapping.get("actual_status_overrides", {}).get(actual_location)
    if status == "failed":
        row["actual_status"] = "failed"
    if status in ("skipped", "unreported") or status is None and row["actual_reps"] in (0, 0.0, "0") and mapping.get("zero_actual_status") == "skipped":
        row["_raw_actual_reps"] = row["actual_reps"]
        row["_raw_actual_rpe"] = row["actual_rpe"]
        row["_raw_actual_load"] = row["actual_load"]
        row["_zero_actual_was_skipped"] = True
        row["actual_status"] = "skipped" if status != "unreported" else None
        row["actual_reps"] = None
        row["actual_load"] = None
        row["actual_rpe"] = None
