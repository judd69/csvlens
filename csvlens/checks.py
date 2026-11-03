"""Data-quality rules CSV01–CSV14.

Families: structure (CSV02, CSV04, CSV05, CSV14), completeness (CSV03,
CSV06), consistency (CSV07, CSV08, CSV09, CSV10), content (CSV01, CSV11,
CSV12, CSV13). A finding is one dict: ``rule``, ``severity`` (``error`` /
``warning`` / ``info``), ``column`` (or ``None``), ``message`` and
``detail``. File-level emptiness is NOT a finding: an empty or
header-only file is a :class:`csvlens.parser.CsvError` (exit code 2).
"""

from __future__ import annotations

from collections import Counter

from .parser import is_missing
from .profiler import classify_value, is_other_date_shape


def _finding(rule, severity, message, column=None, detail=None):
    return {"rule": rule, "severity": severity, "column": column,
            "message": message, "detail": detail or {}}


def run_checks(parsed, profiles, null_tokens):
    """Run every rule; return findings in rule order."""
    findings = []
    rows, headers = parsed.rows, parsed.headers

    # CSV01 — duplicate rows (exact duplicates, beyond the first copy).
    seen, dup_rows = {}, 0
    for row in rows:
        key = tuple(row)
        if key in seen:
            dup_rows += 1
        else:
            seen[key] = True
    if dup_rows:
        findings.append(_finding(
            "CSV01", "warning",
            f"{dup_rows} duplicate row(s) found",
            detail={"duplicate_row_count": dup_rows}))

    # CSV02 — ragged rows (field count != header count), with line numbers.
    # A blank line is an empty row (CSV03), not a ragged row, so it is
    # excluded here even though its field count is 0.
    ragged = [ln for ln, ln_len, raw in zip(parsed.line_numbers,
                                            parsed.raw_lengths, parsed.raw_rows)
              if ln_len != len(headers)
              and not (len(raw) == 0 or all(v.strip() == "" for v in raw))]
    if ragged:
        findings.append(_finding(
            "CSV02", "error",
            f"{len(ragged)} ragged row(s): field count differs from the "
            f"{len(headers)} header columns",
            detail={"lines": ragged}))

    # CSV03 — empty rows (every field empty).
    empty_lines = [ln for row, ln in zip(parsed.rows, parsed.line_numbers)
                   if all(v.strip() == "" for v in row)]
    if empty_lines:
        findings.append(_finding(
            "CSV03", "warning",
            f"{len(empty_lines)} empty row(s)",
            detail={"lines": empty_lines}))

    # CSV04 — duplicate column names (exact match).
    counts = Counter(headers)
    dups = sorted(n for n, c in counts.items() if c > 1)
    if dups:
        findings.append(_finding(
            "CSV04", "error",
            f"duplicate column name(s): {', '.join(dups)}",
            detail={"columns": dups}))

    # CSV05 — blank column names.
    blank_idx = [i for i, h in enumerate(headers) if h.strip() == ""]
    if blank_idx:
        findings.append(_finding(
            "CSV05", "error",
            f"{len(blank_idx)} blank column name(s)",
            detail={"column_indexes": blank_idx}))

    id_checked = False
    for prof in profiles:
        name = prof.name or f"column_{prof.index + 1}"
        non_missing = prof.values
        # CSV06 — high-missing column (>50% missing, but not entirely empty;
        # entirely-empty columns get the stronger CSV14).
        if prof.total and 50.0 < prof.missing_pct < 100.0:
            findings.append(_finding(
                "CSV06", "warning",
                f"column '{name}' is {prof.missing_pct:.1f}% missing",
                column=name, detail={"missing_pct": round(prof.missing_pct, 1)}))
        # CSV14 — column entirely empty (100% missing).
        if prof.total and prof.missing_pct == 100.0:
            findings.append(_finding(
                "CSV14", "error",
                f"column '{name}' is entirely empty",
                column=name))
        if not non_missing:
            continue
        # CSV07 — mixed types: no single category reaches 80% of values.
        cats = Counter()
        for v in non_missing:
            kind = classify_value(v)
            cats["numeric" if kind in ("integer", "float") else kind] += 1
        dominant = max(cats.values()) / len(non_missing)
        if len(cats) > 1 and dominant < 0.8:
            findings.append(_finding(
                "CSV07", "error",
                f"column '{name}' mixes types: "
                + ", ".join(f"{k} ({c})" for k, c in sorted(cats.items())),
                column=name, detail={"type_counts": dict(cats)}))
        # CSV08 — inconsistent date formats: ISO dates plus other shapes.
        iso = sum(1 for v in non_missing if classify_value(v) == "date")
        other = sum(1 for v in non_missing if is_other_date_shape(v))
        if iso and other:
            findings.append(_finding(
                "CSV08", "warning",
                f"column '{name}' mixes ISO dates ({iso}) with other date "
                f"formats ({other})",
                column=name, detail={"iso_dates": iso, "other_dates": other}))
        # CSV09 — inconsistent casing in a categorical (string) column:
        # the same value lowercased appears in more than one case.
        if prof.inferred_type in ("string", "mixed"):
            by_lower = {}
            for v in non_missing:
                by_lower.setdefault(v.strip().lower(), set()).add(v.strip())
            cased = sorted(k for k, forms in by_lower.items() if len(forms) > 1)
            if cased:
                findings.append(_finding(
                    "CSV09", "warning",
                    f"column '{name}' has inconsistent casing for: "
                    + ", ".join(cased[:5]),
                    column=name, detail={"values": cased}))
        # CSV10 — leading/trailing whitespace in values.
        padded = sum(1 for v in non_missing if v != v.strip())
        if padded:
            findings.append(_finding(
                "CSV10", "info",
                f"column '{name}' has {padded} value(s) with leading or "
                "trailing whitespace",
                column=name, detail={"padded_count": padded}))
        # CSV11 — text stragglers in a mostly-numeric column (>=80%
        # numeric, with at least one non-numeric, non-missing value).
        numeric = sum(1 for v in non_missing
                      if classify_value(v) in ("integer", "float"))
        if numeric and numeric / len(non_missing) >= 0.8 \
                and numeric < len(non_missing):
            stragglers = sorted({v.strip() for v in non_missing
                                 if classify_value(v) not in ("integer", "float")})
            findings.append(_finding(
                "CSV11", "warning",
                f"column '{name}' is mostly numeric but contains text: "
                + ", ".join(stragglers[:5]),
                column=name, detail={"values": stragglers}))
        # CSV12 — constant column (exactly 1 distinct non-missing value).
        if prof.distinct == 1:
            findings.append(_finding(
                "CSV12", "info",
                f"column '{name}' is constant (every value is "
                f"'{non_missing[0].strip()}')",
                column=name, detail={"value": non_missing[0].strip()}))
        # CSV13 — duplicate values in a suspected ID column: the first
        # column whose name is "id" or ends in "_id" (later ID-like
        # columns are not re-checked; other rules still run for them).
        if not id_checked and (name.lower() == "id"
                               or name.lower().endswith("_id")):
            id_checked = True
            dup_ids = sorted(v for v, c in Counter(non_missing).items() if c > 1)
            if dup_ids:
                findings.append(_finding(
                    "CSV13", "error",
                    f"suspected ID column '{name}' has duplicate value(s): "
                    + ", ".join(dup_ids[:5]),
                    column=name, detail={"values": dup_ids}))
    return findings
