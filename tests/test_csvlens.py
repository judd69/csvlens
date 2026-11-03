"""CsvLens tests — standard library unittest only.

Run from the project root:  python3 -m unittest discover -s tests -v
"""

import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from csvlens.checks import run_checks
from csvlens.cli import main
from csvlens.parser import CsvError, parse_text
from csvlens.profiler import classify_value, profile
from csvlens.report import render_html, render_json, render_text
from csvlens.scoring import gate_failed, score_findings

NULLS = ("NULL", "N/A", "NA", "null", "none")


def parse(text, **kw):
    return parse_text(text.encode("utf-8"), **kw)


def findings_for(text, **kw):
    parsed = parse(text, **kw)
    profiles = profile(parsed, NULLS)
    return parsed, profiles, run_checks(parsed, profiles, NULLS)


def rules(findings):
    return {f["rule"] for f in findings}


class ParserTests(unittest.TestCase):
    def test_comma_default(self):
        p = parse("a,b\n1,2\n", has_header=True)
        self.assertEqual(p.headers, ["a", "b"])
        self.assertEqual(p.rows[0], ["1", "2"])

    def test_semicolon_sniffed(self):
        p = parse("a;b\n1;2\n", has_header=True)
        self.assertEqual(p.delimiter, ";")
        self.assertEqual(p.headers, ["a", "b"])

    def test_tab_sniffed(self):
        p = parse("a\tb\n1\t2\n", has_header=True)
        self.assertEqual(p.delimiter, "\t")

    def test_pipe_sniffed(self):
        p = parse("a|b\n1|2\n", has_header=True)
        self.assertEqual(p.delimiter, "|")

    def test_delimiter_override(self):
        p = parse("a;b\n1;2\n", delimiter=";", has_header=True)
        self.assertEqual(p.delimiter, ";")

    def test_bom_stripped(self):
        p = parse_text(b"\xef\xbb\xbfa,b\n1,2\n", has_header=True)
        self.assertEqual(p.headers, ["a", "b"])

    def test_latin1_fallback(self):
        # 0xE9 alone is invalid UTF-8; latin-1 decodes it as e-acute.
        p = parse_text(b"a,b\ncaf\xe9,2\n", has_header=True)
        self.assertEqual(p.encoding, "latin-1")
        self.assertEqual(p.rows[0][0], "caf\u00e9")

    def test_quoted_and_multiline_fields(self):
        p = parse('a,b\n"hello, world","line1\nline2"\n', has_header=True)
        self.assertEqual(p.rows[0], ["hello, world", "line1\nline2"])

    def test_header_detected_on_mixed_file(self):
        # Regression: Sniffer.has_header alone misses this header.
        p = parse("id,name,age\n1,Ada,28\n2,Bo,31\n")
        self.assertTrue(p.has_header)
        self.assertEqual(p.headers, ["id", "name", "age"])

    def test_no_header_invents_columns(self):
        p = parse("1,Ada\n2,Bo\n", has_header=False)
        self.assertEqual(p.headers, ["column_1", "column_2"])
        self.assertEqual(len(p.rows), 2)

    def test_ragged_rows_kept(self):
        p = parse("a,b,c\n1,2\n1,2,3,4\n", has_header=True)
        self.assertEqual(p.raw_lengths, [2, 4])

    def test_empty_file_is_error(self):
        with self.assertRaises(CsvError):
            parse("   \n")

    def test_header_only_is_error(self):
        with self.assertRaises(CsvError):
            parse("a,b\n", has_header=True)

    def test_null_tokens_case_insensitive(self):
        p = parse("a,b\nNULL,1\nnull,2\n", has_header=True)
        prof = profile(p, NULLS)
        self.assertEqual(prof[0].missing, 2)


class TypeInferenceTests(unittest.TestCase):
    def test_integer_float_date_boolean_string(self):
        self.assertEqual(classify_value("42"), "integer")
        self.assertEqual(classify_value("-3"), "integer")
        self.assertEqual(classify_value("2.5"), "float")
        self.assertEqual(classify_value("2024-01-15"), "date")
        self.assertEqual(classify_value("2024-02-30"), "string")  # invalid date
        self.assertEqual(classify_value("True"), "boolean")
        self.assertEqual(classify_value("false"), "boolean")
        self.assertEqual(classify_value("hello"), "string")

    def test_int_plus_float_is_float_column(self):
        p = parse("x\n1\n2.5\n3\n", has_header=True)
        self.assertEqual(profile(p, NULLS)[0].inferred_type, "float")

    def test_numeric_stats(self):
        p = parse("x\n10\n20\n30\n", has_header=True)
        prof = profile(p, NULLS)[0]
        self.assertEqual((prof.numeric_min, prof.numeric_max), (10, 30))
        self.assertEqual(prof.numeric_mean, 20.0)

    def test_missing_pct_and_top_values(self):
        p = parse("x\napple\napple\n\nbanana\n", has_header=True)
        prof = profile(p, NULLS)[0]
        self.assertEqual(prof.missing, 1)
        self.assertEqual(prof.missing_pct, 25.0)
        self.assertEqual(prof.top_values[0], ("apple", 2))

    def test_empty_column_type(self):
        p = parse("x,y\n,1\n,2\n", has_header=True)
        self.assertEqual(profile(p, NULLS)[0].inferred_type, "empty")

    def test_string_lengths(self):
        p = parse("x\nab\nabcd\n", has_header=True)
        prof = profile(p, NULLS)[0]
        self.assertEqual((prof.min_length, prof.max_length), (2, 4))


class RuleTests(unittest.TestCase):
    def test_csv01_duplicate_rows(self):
        _, _, f = findings_for("a,b\n1,2\n1,2\n3,4\n")
        self.assertIn("CSV01", rules(f))

    def test_csv02_ragged_with_line_numbers(self):
        _, _, f = findings_for("a,b\n1,2,3\n1,2\n")
        hit = [x for x in f if x["rule"] == "CSV02"][0]
        self.assertEqual(hit["detail"]["lines"], [2])

    def test_csv03_empty_rows(self):
        _, _, f = findings_for("a,b\n1,2\n\n3,4\n")
        self.assertIn("CSV03", rules(f))

    def test_csv04_duplicate_column_names(self):
        _, _, f = findings_for("a,a\n1,2\n3,4\n")
        self.assertIn("CSV04", rules(f))

    def test_csv05_blank_column_name(self):
        _, _, f = findings_for("a,,c\n1,2,3\n")
        self.assertIn("CSV05", rules(f))

    def test_csv06_high_missing(self):
        _, _, f = findings_for("a,b\n1,\n2,\n3,x\n4,\n")
        self.assertIn("CSV06", rules(f))

    def test_csv07_mixed_types(self):
        _, _, f = findings_for("a\n10\ntwenty\n30\nforty\n")
        self.assertIn("CSV07", rules(f))

    def test_csv08_inconsistent_date_formats(self):
        _, _, f = findings_for("d\n2024-01-15\n15/02/2024\n2024-03-10\n")
        self.assertIn("CSV08", rules(f))

    def test_csv09_inconsistent_casing(self):
        _, _, f = findings_for("city\nNew York\nnew york\nParis\n")
        self.assertIn("CSV09", rules(f))

    def test_csv10_whitespace(self):
        _, _, f = findings_for("a\n  padded  \nclean\n")
        self.assertIn("CSV10", rules(f))

    def test_csv11_text_stragglers(self):
        rows = "\n".join(["v"] + [str(i) for i in range(10)] + ["pending"])
        _, _, f = findings_for(rows + "\n")
        self.assertIn("CSV11", rules(f))
        self.assertNotIn("CSV07", rules(f))

    def test_csv12_constant_column(self):
        _, _, f = findings_for("a,b\nx,1\ny,2\n")
        # 'a' is not constant; use a dedicated constant column below.
        _, _, f2 = findings_for("plan,other\nfree,1\nfree,2\n")
        self.assertIn("CSV12", rules(f2))

    def test_csv13_id_duplicates(self):
        _, _, f = findings_for("user_id,name\n7,Ada\n7,Bo\n8,Cy\n")
        self.assertIn("CSV13", rules(f))

    def test_csv13_only_first_id_column_checked(self):
        _, _, f = findings_for("id,other_id\n1,9\n1,9\n2,9\n")
        hits = [x for x in f if x["rule"] == "CSV13"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["column"], "id")

    def test_csv14_entirely_empty_column(self):
        _, _, f = findings_for("a,b\n,1\n,2\n")
        self.assertIn("CSV14", rules(f))

    def test_clean_file_has_no_findings(self):
        _, _, f = findings_for("id,name\n1,Ada\n2,Bo\n")
        self.assertEqual(f, [])


class ScoringTests(unittest.TestCase):
    def test_weights_and_grades(self):
        score, grade, verdict, _ = score_findings([])
        self.assertEqual((score, grade, verdict), (100, "A", "CLEAN"))
        score, grade, verdict, counts = score_findings([
            {"severity": "error"}, {"severity": "warning"},
            {"severity": "info"}])
        self.assertEqual(score, 100 - 10 - 5 - 2)
        self.assertEqual(grade, "B")
        self.assertEqual(counts, {"error": 1, "warning": 1, "info": 1})

    def test_grade_boundaries(self):
        # Deduction combos: error 10, warning 5, info 2.
        cases = [
            (90, "A", [{"severity": "error"}]),
            (75, "B", [{"severity": "error"}] * 2 + [{"severity": "warning"}]),
            (60, "C", [{"severity": "error"}] * 4),
            (40, "D", [{"severity": "error"}] * 6),
            # 61 points off = 5 errors + 1 warning + 3 infos -> 39, grade F.
            (39, "F", [{"severity": "error"}] * 5 + [{"severity": "warning"}]
             + [{"severity": "info"}] * 3),
        ]
        for score_want, grade_want, findings in cases:
            score, grade, verdict, _ = score_findings(findings)
            self.assertEqual((score, grade), (score_want, grade_want))
        _, _, verdict, _ = score_findings([{"severity": "error"}] * 7)
        self.assertEqual(verdict, "MESSY")

    def test_gate(self):
        self.assertTrue(gate_failed("MESSY", "messy"))
        self.assertFalse(gate_failed("NEEDS WORK", "messy"))
        self.assertTrue(gate_failed("NEEDS WORK", "needs-work"))
        self.assertFalse(gate_failed("CLEAN", "needs-work"))


class OutputTests(unittest.TestCase):
    def _result(self):
        parsed, profiles, findings = findings_for("id,name\n1,Ada\n1,Ada\n")
        score, grade, verdict, counts = score_findings(findings)
        from csvlens.report import build_result
        return build_result("x.csv", parsed, profiles, findings, score,
                            grade, verdict, counts)

    def test_text_format(self):
        out = render_text(self._result(), use_color=False)
        self.assertIn("Score:", out)
        self.assertIn("CSV01", out)
        self.assertNotIn("\x1b[", out)

    def test_text_color_can_be_disabled(self):
        out = render_text(self._result(), use_color=True)
        self.assertIn("\x1b[", out)

    def test_json_format_is_valid(self):
        data = json.loads(render_json(self._result()))
        self.assertEqual(data["verdict"], data["verdict"])
        self.assertIn("columns_profile", data)

    def test_html_self_contained(self):
        out = render_html(self._result())
        self.assertNotIn("src=", out)
        self.assertNotIn("<link", out)
        self.assertNotIn("http://", out)
        self.assertNotIn("https://", out)

    def test_html_escapes_hostile_cells(self):
        parsed, profiles, findings = findings_for(
            "note\n<script>alert(1)</script>\nhello\n")
        score, grade, verdict, counts = score_findings(findings)
        from csvlens.report import build_result
        result = build_result("x.csv", parsed, profiles, findings, score,
                              grade, verdict, counts)
        out = render_html(result)
        self.assertNotIn("<script>alert(1)</script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_html_has_filter_chips(self):
        out = render_html(self._result())
        self.assertIn("data-filter='error'", out)
        self.assertIn("data-filter='warning'", out)


class CliTests(unittest.TestCase):
    def _run(self, args):
        out, err = io.StringIO(), io.StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        try:
            sys.stdout, sys.stderr = out, err
            code = main(args)
        finally:
            sys.stdout, sys.stderr = old_out, old_err
        return code, out.getvalue(), err.getvalue()

    def _tmp_csv(self, text):
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        self.addCleanup(os.unlink, path)
        return path

    def test_missing_file_exits_2_without_traceback(self):
        code, _, err = self._run(["/definitely/not/here.csv"])
        self.assertEqual(code, 2)
        self.assertIn("error", err)
        self.assertNotIn("Traceback", err)

    def test_empty_file_exits_2(self):
        code, _, err = self._run([self._tmp_csv("")])
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)

    def test_clean_exits_0(self):
        code, out, _ = self._run(
            [self._tmp_csv("id,name\n1,Ada\n2,Bo\n"), "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("CLEAN", out)

    def test_fail_on_messy(self):
        messy = self._tmp_csv("id,name\n1,Ada\n1,Ada\n1,Ada\n1,Ada\n"
                              "1,Ada\n1,Ada\n1,Ada\n1,Ada\n")
        code, _, _ = self._run([messy, "--no-color", "--fail-on", "messy"])
        # Duplicate rows alone (warning x1) do not reach MESSY; gate passes.
        self.assertEqual(code, 0)

    def test_fail_on_needs_work_triggers(self):
        # Duplicate rows + ragged row + empty row + duplicate id +
        # constant plan = 68/100, NEEDS WORK, so the gate fails.
        path = self._tmp_csv("id,plan\n1,free\n1,free\n1,2,3\n\n")
        code, _, _ = self._run([path, "--no-color", "--fail-on", "needs-work"])
        self.assertEqual(code, 1)

    def test_fail_on_messy_triggers_on_truly_messy(self):
        # Hits nearly every rule at once: duplicates, ragged, empty,
        # mixed age, straggler score, mixed dates, casing, whitespace,
        # constant plan, high-missing notes, entirely-empty column.
        rows = ["id,name,city,age,score,joined,plan,notes,blank"]
        rows.append("1,Ada Example,New York,thirty,pending,15/02/2024,free,,")
        rows.append("1,Ada Example,New York,thirty,pending,15/02/2024,free,,")
        rows.append("1,Bo Example,new york,forty,pending,15/02/2024,free,,extra,EXTRA")
        rows.append("")
        rows.append('2,"  Cy Example  ",Paris,28,90,2024-01-15,free,,')
        rows.append("3,De Example,Berlin,29,91,2024-02-10,free,hi,")
        rows.append("4,Ev Example,Rome,31,92,2024-03-05,free,,")
        code, _, _ = self._run(
            [self._tmp_csv("\n".join(rows) + "\n"), "--no-color",
             "--fail-on", "messy"])
        self.assertEqual(code, 1)

    def test_json_flag(self):
        code, out, _ = self._run(
            [self._tmp_csv("id,name\n1,Ada\n2,Bo\n"), "--format", "json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["score"], 100)

    def test_html_flag_self_contained(self):
        code, out, _ = self._run(
            [self._tmp_csv("id,name\n1,Ada\n"), "--format", "html"])
        self.assertEqual(code, 0)
        self.assertNotIn("src=", out)

    def test_custom_null_values(self):
        code, out, _ = self._run(
            [self._tmp_csv("a\nMISSING\n1\n"), "--no-color",
             "--null-values", "MISSING"])
        self.assertEqual(code, 0)
        self.assertIn("missing 1 (50.0%)", out)

    def test_no_header_flag(self):
        code, out, _ = self._run(
            [self._tmp_csv("1,Ada\n2,Bo\n"), "--no-color", "--no-header"])
        self.assertEqual(code, 0)
        self.assertIn("column_1", out)


if __name__ == "__main__":
    unittest.main()
