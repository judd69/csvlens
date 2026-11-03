"""CSV parsing: delimiter sniffing, BOM/encoding fallback, header detection.

Only the standard library is used. ``csv.Sniffer`` is a heuristic, so every
sniffed result has a safe fallback: comma delimiter, header present.
"""

from __future__ import annotations

import csv
import io
import re

_HEADER_CELL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_ ]{0,30}$")

DEFAULT_NULL_TOKENS = ("NULL", "N/A", "NA", "null", "none")

_SNIFF_DELIMITERS = [",", ";", "\t", "|"]


class CsvError(Exception):
    """A clean, user-facing CSV problem (never a traceback in the CLI)."""


class ParsedCsv:
    """The result of parsing one file."""

    def __init__(self, headers, rows, line_numbers, delimiter, has_header,
                 encoding):
        self.headers = headers          # list[str]
        self.rows = rows                # list[list[str]] (data rows only)
        # 1-based file line where each data row *ends* (csv reader line_num).
        self.line_numbers = line_numbers
        self.delimiter = delimiter
        self.has_header = has_header
        self.encoding = encoding

    @property
    def column_count(self):
        return len(self.headers)


def _decode(raw: bytes):
    """Decode as UTF-8-SIG (strips a BOM); fall back to latin-1, which
    never fails, instead of crashing on a stray byte."""
    try:
        return raw.decode("utf-8-sig"), "utf-8-sig"
    except UnicodeDecodeError:
        return raw.decode("latin-1"), "latin-1"


def parse_file(path, delimiter=None, has_header=None, null_values=None):
    """Parse *path* and return a :class:`ParsedCsv`.

    ``delimiter`` overrides sniffing. ``has_header`` overrides detection
    (``False`` means: treat the first row as data and invent headers).
    Raises :class:`CsvError` for missing/unreadable/empty/header-only files.
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise CsvError(f"cannot read file: {path} ({exc.strerror or exc})") from None
    return parse_text(raw, delimiter=delimiter, has_header=has_header)


def parse_text(raw, delimiter=None, has_header=None):
    """Parse raw bytes (or a str) — the unit-testable core of parse_file."""
    if isinstance(raw, str):
        text, encoding = raw, "utf-8-sig"
        # Strip a literal BOM character if the caller passed one in a str.
        if text.startswith("\ufeff"):
            text = text[1:]
    else:
        text, encoding = _decode(raw)
    if not text.strip():
        raise CsvError("empty file: no content to profile")
    sample = text[:8192]
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=_SNIFF_DELIMITERS).delimiter
        except csv.Error:
            delimiter = ","
    if has_header is None:
        try:
            has_header = csv.Sniffer().has_header(sample)
        except csv.Error:
            has_header = True
        if not has_header:
            # Sniffer.has_header is unreliable on mixed-type files: it
            # missed the header in examples/messy.csv. Fall back to an
            # explicit heuristic — a first row of identifier-like words
            # followed by a row containing a number or ISO date is a header.
            try:
                peek = list(csv.reader(io.StringIO(sample),
                                       delimiter=delimiter))[:2]
            except csv.Error:
                peek = []
            if len(peek) == 2 and peek[0] and all(
                    _HEADER_CELL_RE.match(c.strip())
                    and c.strip().lower() not in ("true", "false")
                    for c in peek[0]):
                from .profiler import classify_value  # local import: no cycle
                if any(classify_value(c) in ("integer", "float", "date")
                       for c in peek[1]):
                    has_header = True
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    all_rows = []
    line_numbers = []
    for row in reader:
        # csv yields [] for a truly blank line; keep it so empty-row
        # detection (CSV03) can see it, with its line number.
        all_rows.append(row)
        line_numbers.append(reader.line_num)
    if not all_rows:
        raise CsvError("empty file: no content to profile")
    if has_header:
        headers = [h.strip() for h in all_rows[0]]
        data_rows, data_lines = all_rows[1:], line_numbers[1:]
    else:
        width = max((len(r) for r in all_rows), default=0)
        headers = [f"column_{i + 1}" for i in range(width)]
        data_rows, data_lines = all_rows, line_numbers
    if not data_rows:
        raise CsvError("header-only file: no data rows to profile")
    # Normalise ragged rows to header width for profiling; the original
    # lengths are still reported by the checks module via raw lengths.
    padded = []
    for row in data_rows:
        if len(row) < len(headers):
            row = row + [""] * (len(headers) - len(row))
        padded.append(row)
    parsed = ParsedCsv(headers, padded, data_lines, delimiter, has_header,
                       encoding)
    parsed.raw_lengths = [len(r) for r in data_rows]
    parsed.raw_rows = data_rows
    return parsed


def is_missing(value, null_tokens):
    """True for empty strings and configured null tokens (case-insensitive)."""
    stripped = value.strip()
    if stripped == "":
        return True
    return stripped.lower() in {t.lower() for t in null_tokens}
