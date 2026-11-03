"""Score 0–100, grade, and verdict.

Weights (documented here and in the README): every finding deducts by
severity — ``error`` 10 points, ``warning`` 5 points, ``info`` 2 points.
The score floors at 0. Grades: A 90+, B 75+, C 60+, D 40+, F below 40.
Verdict follows the grade: A/B = CLEAN, C/D = NEEDS WORK, F = MESSY.
"""

from __future__ import annotations

WEIGHTS = {"error": 10, "warning": 5, "info": 2}


def score_findings(findings):
    """Return ``(score, grade, verdict, counts_by_severity)``."""
    score = 100
    counts = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
        score -= WEIGHTS.get(f["severity"], 0)
    score = max(0, score)
    if score >= 90:
        grade, verdict = "A", "CLEAN"
    elif score >= 75:
        grade, verdict = "B", "CLEAN"
    elif score >= 60:
        grade, verdict = "C", "NEEDS WORK"
    elif score >= 40:
        grade, verdict = "D", "NEEDS WORK"
    else:
        grade, verdict = "F", "MESSY"
    return score, grade, verdict, counts


def gate_failed(verdict, fail_on):
    """True if ``--fail-on`` should fail the run for this verdict."""
    if fail_on == "messy":
        return verdict == "MESSY"
    if fail_on == "needs-work":
        return verdict in ("NEEDS WORK", "MESSY")
    return False
