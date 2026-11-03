"""Command-line interface for CsvLens.

Exit codes: 0 = profiled OK (and any --fail-on gate passed),
1 = --fail-on gate failed, 2 = usage error or unreadable/empty file.
File problems print a clean one-line error to stderr, never a traceback.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .checks import run_checks
from .parser import DEFAULT_NULL_TOKENS, CsvError, parse_file
from .profiler import profile
from .report import build_result, render
from .scoring import gate_failed, score_findings


def build_parser():
    p = argparse.ArgumentParser(
        prog="csvlens",
        description="Profile a CSV before you trust it: types, missing "
                    "values, and 14 data-quality rules, scored 0-100.")
    p.add_argument("file", help="path to the CSV file to profile")
    p.add_argument("--delimiter", default=None,
                   help="force a delimiter instead of sniffing it")
    p.add_argument("--no-header", action="store_true",
                   help="treat the first row as data, not headers")
    p.add_argument("--null-values", default=None,
                   help="comma-separated null tokens (replaces the defaults: "
                        "NULL, N/A, NA, null, none; empty strings are always "
                        "missing)")
    p.add_argument("--format", choices=["text", "json", "html"],
                   default="text", help="output format (default: text)")
    p.add_argument("--top", type=int, default=5,
                   help="number of top values per column (default: 5)")
    p.add_argument("--fail-on", choices=["messy", "needs-work"], default=None,
                   help="CI gate: exit 1 when the verdict is at least this bad")
    p.add_argument("--no-color", action="store_true",
                   help="disable coloured text output")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    null_tokens = (tuple(t.strip() for t in args.null_values.split(",") if t.strip())
                   if args.null_values is not None else DEFAULT_NULL_TOKENS)
    try:
        parsed = parse_file(args.file, delimiter=args.delimiter,
                            has_header=None if not args.no_header else False)
    except CsvError as exc:
        print(f"csvlens: error: {exc}", file=sys.stderr)
        return 2
    profiles = profile(parsed, null_tokens, top_n=args.top)
    findings = run_checks(parsed, profiles, null_tokens)
    score, grade, verdict, counts = score_findings(findings)
    result = build_result(args.file, parsed, profiles, findings, score,
                          grade, verdict, counts, top_n=args.top)
    sys.stdout.write(render(result, args.format,
                            use_color=not args.no_color))
    if args.fail_on and gate_failed(verdict, args.fail_on):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
