"""Per-column profiling: type inference, missingness, top values, stats.

Type categories: ``integer``, ``float``, ``date`` (ISO YYYY-MM-DD only),
``boolean`` (true/false, any case), ``string``, ``mixed``, ``empty``.
Integer + float together count as numeric, not mixed: a column of
``1, 2.5, 3`` is a float column. Values are classified after stripping
whitespace, so a padded ``" 42 "`` still counts as numeric — the padding
itself is reported separately by rule CSV10.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date

from .parser import is_missing

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Non-ISO date shapes, used by rule CSV08 (inconsistent date formats).
OTHER_DATE_RES = [
    re.compile(r"^\d{2}/\d{2}/\d{4}$"),        # 15/02/2024 or 02/15/2024
    re.compile(r"^\d{4}/\d{2}/\d{2}$"),        # 2024/03/10
    re.compile(r"^\d{2}-[A-Za-z]{3}-\d{4}$"),  # 05-Mar-2024
    re.compile(r"^[A-Za-z]{3,9} \d{1,2},? \d{4}$"),  # Mar 5 2024
    re.compile(r"^\d{2}\.\d{2}\.\d{4}$"),      # 15.02.2024
    re.compile(r"^\d{2}-\d{2}-\d{4}$"),        # 15-02-2024
]
_BOOL_WORDS = {"true", "false"}


def classify_value(value):
    """Classify one stripped, non-missing value, or ``None``."""
    v = value.strip()
    if _INT_RE.match(v):
        return "integer"
    if _FLOAT_RE.match(v):
        return "float"
    if _ISO_DATE_RE.match(v):
        try:
            date(int(v[0:4]), int(v[5:7]), int(v[8:10]))
            return "date"
        except ValueError:
            return "string"
    if v.lower() in _BOOL_WORDS:
        return "boolean"
    return "string"


def is_other_date_shape(value):
    """True if the value looks like a date that is NOT ISO YYYY-MM-DD."""
    v = value.strip()
    if _ISO_DATE_RE.match(v):
        return False
    return any(rx.match(v) for rx in OTHER_DATE_RES)


def _category(kind):
    if kind in ("integer", "float"):
        return "numeric"
    return kind  # date, boolean, string


class ColumnProfile:
    def __init__(self, name, index):
        self.name = name
        self.index = index
        self.total = 0
        self.missing = 0
        self.distinct = 0
        self.top_values = []       # [(value, count)]
        self.inferred_type = "empty"
        self.type_counts = {}      # kind -> count (non-missing only)
        self.numeric_min = None
        self.numeric_max = None
        self.numeric_mean = None
        self.min_length = None
        self.max_length = None
        self.values = []           # raw non-missing values, for the checks

    @property
    def missing_pct(self):
        return (self.missing / self.total * 100.0) if self.total else 0.0

    def to_dict(self, top_n=5):
        return {
            "name": self.name,
            "index": self.index,
            "total": self.total,
            "missing": self.missing,
            "missing_pct": round(self.missing_pct, 1),
            "distinct": self.distinct,
            "inferred_type": self.inferred_type,
            "type_counts": self.type_counts,
            "top_values": [
                {"value": v, "count": c} for v, c in self.top_values[:top_n]
            ],
            "numeric_min": self.numeric_min,
            "numeric_max": self.numeric_max,
            "numeric_mean": self.numeric_mean,
            "min_length": self.min_length,
            "max_length": self.max_length,
        }


def profile(parsed, null_tokens, top_n=5):
    """Return a list of :class:`ColumnProfile`, one per header column."""
    profiles = []
    for idx, name in enumerate(parsed.headers):
        prof = ColumnProfile(name, idx)
        raw_values = [row[idx] if idx < len(row) else "" for row in parsed.rows]
        prof.total = len(raw_values)
        non_missing = []
        for value in raw_values:
            if is_missing(value, null_tokens):
                prof.missing += 1
            else:
                non_missing.append(value)
        prof.values = non_missing
        prof.distinct = len(set(non_missing))
        counter = Counter(non_missing)
        prof.top_values = counter.most_common(top_n)
        kinds = Counter(classify_value(v) for v in non_missing)
        prof.type_counts = dict(sorted(kinds.items()))
        cats = {_category(k) for k in kinds}
        if not non_missing:
            prof.inferred_type = "empty"
        elif cats == {"numeric"}:
            prof.inferred_type = "float" if "float" in kinds else "integer"
        elif len(cats) == 1:
            prof.inferred_type = next(iter(cats))
        else:
            prof.inferred_type = "mixed"
        numbers = []
        for v in non_missing:
            kind = classify_value(v)
            if kind in ("integer", "float"):
                try:
                    numbers.append(float(v.strip()))
                except ValueError:
                    pass
        if numbers:
            prof.numeric_min = min(numbers)
            prof.numeric_max = max(numbers)
            prof.numeric_mean = round(sum(numbers) / len(numbers), 2)
            # Present whole numbers without a trailing ".0".
            for attr in ("numeric_min", "numeric_max"):
                val = getattr(prof, attr)
                if val is not None and float(val).is_integer():
                    setattr(prof, attr, int(val))
        lengths = [len(v) for v in non_missing]
        if lengths:
            prof.min_length, prof.max_length = min(lengths), max(lengths)
        profiles.append(prof)
    return profiles
