# CsvLens

**Profile a CSV before you trust it.**

CsvLens is a zero-dependency Python CLI that profiles a CSV file: it sniffs
the delimiter, handles BOMs and encoding fallbacks, detects headers, infers
a type for every column, and checks the file against 14 data-quality rules —
then scores it 0–100 with a grade and a verdict. It exists because the same
CSV failures keep recurring in real data work: duplicate rows, ragged rows,
missing values, mixed types, dates written three different ways, and
"New York" vs "new york" in the same column. Analysts report spending most
of their time preparing data before analysis can start; CsvLens tells you
up front how much preparing a file actually needs.

## Install and run

Requires Python 3.8+ and nothing else — standard library only.

```bash
python3 -m csvlens data.csv
python3 -m csvlens data.csv --format json
python3 -m csvlens data.csv --format html > report.html
python3 -m csvlens data.csv --fail-on messy   # CI gate
```

## Flags

| Flag | Meaning |
| --- | --- |
| `file` (positional) | Path to the CSV file to profile |
| `--delimiter` | Force a delimiter instead of sniffing (`,`, `;`, tab, `\|` are sniffed) |
| `--no-header` | Treat the first row as data, not headers (headers become `column_1`, …) |
| `--null-values` | Comma-separated null tokens, replacing the defaults (`NULL`, `N/A`, `NA`, `null`, `none`); empty strings are always missing |
| `--format text\|json\|html` | Output format (default: `text`; text is coloured unless `--no-color` is given) |
| `--top N` | Number of top values shown per column (default: 5) |
| `--fail-on messy\|needs-work` | CI gate: exit 1 when the verdict is at least this bad |
| `--no-color` | Disable coloured text output |

## What it reports

Per column: inferred type (`integer`, `float`, ISO date, `boolean`, `string`,
`mixed`, `empty`), missing count and %, distinct count, top 5 values with
counts, numeric min/max/mean where applicable, and string min/max length.
Note: a column's inferred type is `mixed` whenever more than one type
category appears; rule CSV07 only fires when no single category reaches
80% of the column's values, while CSV11 covers the mostly-numeric case.

File level: row/column counts, detected delimiter and encoding, the
0–100 score, grade, verdict, and every finding.

## Scoring, grades, verdicts

Every finding deducts by severity: **error −10, warning −5, info −2**.
The score floors at 0. Grades: **A 90+, B 75+, C 60+, D 40+, F below 40**.
Verdicts follow the grade: **A/B = CLEAN, C/D = NEEDS WORK, F = MESSY**.

## Rules CSV01–CSV14

| Rule | Severity | What it flags |
| --- | --- | --- |
| CSV01 | warning | Duplicate rows (exact duplicates, beyond the first copy) |
| CSV02 | error | Ragged rows: field count differs from the header count, with line numbers (blank lines are CSV03, not ragged) |
| CSV03 | warning | Empty rows |
| CSV04 | error | Duplicate column names |
| CSV05 | error | Blank column names |
| CSV06 | warning | High-missing column: over 50% missing, but not entirely empty |
| CSV07 | error | Mixed types inside one column (no single type category reaches 80%) |
| CSV08 | warning | Inconsistent date formats in one column (ISO dates mixed with other date shapes) |
| CSV09 | warning | Inconsistent casing in a categorical column (same value lowercased appearing in multiple cases, e.g. USA vs usa) |
| CSV10 | info | Leading/trailing whitespace in values |
| CSV11 | warning | Text stragglers in a mostly-numeric column (at least 80% numeric, with non-numeric values) |
| CSV12 | info | Constant column (exactly 1 distinct non-missing value) |
| CSV13 | error | Duplicate values in a suspected ID column (the first column named `id` or ending in `_id`) |
| CSV14 | error | Column entirely empty (100% missing) |

An empty file and a header-only file are not findings — they are errors
(exit code 2, clean message, no traceback), because there is nothing to
profile.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Profiled OK (and any `--fail-on` gate passed) |
| 1 | `--fail-on` gate failed |
| 2 | Usage error, or the file is missing, unreadable, empty, or header-only |

## Example output

### `python3 -m csvlens --no-color examples/messy.csv`

```
CsvLens — examples/messy.csv
Rows: 25  Columns: 8  Delimiter: ','  Encoding: utf-8-sig
Score: 34/100  Grade: F  Verdict: MESSY
Findings: 3 error(s), 6 warning(s), 3 info

Columns:
  id: integer, missing 1 (4.0%), distinct 22,  min 1 max 23 mean 11.29 length 1–2
      '1' x3
      '2' x1
      '3' x1
      '4' x1
      '5' x1
  name: string, missing 1 (4.0%), distinct 23, length 10–14
      'Ada Example' x2
      'Bo Example' x1
      'Cy Example' x1
      'De Example' x1
      'Ev Example' x1
  city: string, missing 1 (4.0%), distinct 10, length 4–8
      'New York' x4
      'Paris' x3
      'Berlin' x3
      'Tokyo' x3
      'Rome' x3
  age: mixed, missing 1 (4.0%), distinct 17,  min 26 max 36 mean 30.22 length 2–12
      '28' x4
      '29' x3
      '31' x2
      '30' x2
      'thirty' x1
  score: mixed, missing 1 (4.0%), distinct 16,  min 78 max 95 mean 88.52 length 2–7
      '92' x3
      '90' x3
      '88' x2
      '91' x2
      '87' x2
  joined: mixed, missing 1 (4.0%), distinct 23, length 10–11
      '2024-01-15' x2
      '15/02/2024' x1
      '2024/03/10' x1
      '05-Mar-2024' x1
      '2024-04-02' x1
  plan: string, missing 1 (4.0%), distinct 1, length 4–4
      'free' x24
  notes: string, missing 20 (80.0%), distinct 4, length 5–12
      'first order' x2
      'repeat buyer' x1
      'extra' x1
      'loyal' x1

Issues:
  WARNING CSV01: 1 duplicate row(s) found
  ERROR CSV02: 1 ragged row(s): field count differs from the 8 header columns
  WARNING CSV03: 1 empty row(s)
  ERROR CSV13 [id]: suspected ID column 'id' has duplicate value(s): 1
  INFO CSV10 [name]: column 'name' has 1 value(s) with leading or trailing whitespace
  WARNING CSV09 [city]: column 'city' has inconsistent casing for: new york
  INFO CSV10 [city]: column 'city' has 1 value(s) with leading or trailing whitespace
  ERROR CSV07 [age]: column 'age' mixes types: numeric (18), string (6)
  WARNING CSV11 [score]: column 'score' is mostly numeric but contains text: pending
  WARNING CSV08 [joined]: column 'joined' mixes ISO dates (20) with other date formats (4)
  INFO CSV12 [plan]: column 'plan' is constant (every value is 'free')
  WARNING CSV06 [notes]: column 'notes' is 80.0% missing
```

### `python3 -m csvlens --no-color examples/clean.csv`

```
CsvLens — examples/clean.csv
Rows: 8  Columns: 7  Delimiter: ','  Encoding: utf-8-sig
Score: 100/100  Grade: A  Verdict: CLEAN
Findings: 0 error(s), 0 warning(s), 0 info

Columns:
  id: integer, missing 0 (0.0%), distinct 8,  min 1 max 8 mean 4.5 length 1–1
      '1' x1
      '2' x1
      '3' x1
      '4' x1
      '5' x1
  name: string, missing 0 (0.0%), distinct 8, length 10–11
      'Ada Example' x1
      'Bo Example' x1
      'Cy Example' x1
      'De Example' x1
      'Ev Example' x1
  city: string, missing 0 (0.0%), distinct 7, length 4–8
      'London' x2
      'New York' x1
      'Paris' x1
      'Berlin' x1
      'Tokyo' x1
  age: integer, missing 0 (0.0%), distinct 8,  min 26 max 34 mean 29.75 length 2–2
      '28' x1
      '31' x1
      '34' x1
      '29' x1
      '26' x1
  score: integer, missing 0 (0.0%), distinct 8,  min 78 max 92 mean 86.88 length 2–2
      '92' x1
      '85' x1
      '78' x1
      '88' x1
      '91' x1
  joined: date, missing 0 (0.0%), distinct 8, length 10–10
      '2024-01-15' x1
      '2024-02-10' x1
      '2024-03-05' x1
      '2024-04-02' x1
      '2024-05-20' x1
  plan: string, missing 0 (0.0%), distinct 3, length 3–7
      'starter' x3
      'pro' x3
      'team' x2

Issues:
  No issues found.
```

The messy example scores 34/100 (F, MESSY); the clean example scores
100/100 (A, CLEAN). Both outputs above are copied verbatim from real runs.
`docs/sample-report.html` is a real HTML report generated by CsvLens
itself from `examples/messy.csv`.

## Examples

`examples/messy.csv` (~25 rows, all values clearly fake — names like
"Ada Example", emails would use `@example.com`) is crafted with known
issues: a duplicate row, a ragged row, an empty row, a high-missing
column, a mixed-type column, inconsistent date formats, inconsistent
casing, whitespace-padded values, and a constant column.
`examples/clean.csv` has no findings.

## Layout

```
csvlens/
  __main__.py    # python3 -m csvlens entry point
  cli.py         # argument parsing, exit codes
  parser.py      # delimiter sniffing, BOM/encoding, header detection
  profiler.py    # type inference, per-column statistics
  checks.py      # rules CSV01-CSV14
  scoring.py     # score, grade, verdict, CI gate
  report.py      # text / JSON / self-contained HTML output
tests/test_csvlens.py   # unittest, standard library only
examples/messy.csv examples/clean.csv
docs/index.html docs/sample-report.html
```

## License

MIT — see `LICENSE`.
