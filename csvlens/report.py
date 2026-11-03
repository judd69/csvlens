"""Output formats: coloured text, JSON, and a self-contained HTML report.

The HTML report has NO external assets: no ``src=`` attributes, no
``<link>`` tags, no http(s) asset URLs — all CSS and JavaScript is inline.
Every value rendered into HTML is escaped, so a hostile cell such as
``<script>alert(1)</script>`` shows up as text, never as markup.
"""

from __future__ import annotations

import html
import json

from .scoring import WEIGHTS

RESET = "\033[0m"
COLORS = {"error": "\033[31m", "warning": "\033[33m", "info": "\033[36m",
          "score": "\033[32m", "bold": "\033[1m"}


def _paint(text, code, use_color):
    return f"{code}{text}{RESET}" if use_color else text


def build_result(path, parsed, profiles, findings, score, grade, verdict,
                 counts, top_n=5):
    """Assemble the shared result dict every format renders from."""
    return {
        "file": path,
        "rows": len(parsed.rows),
        "columns": len(parsed.headers),
        "delimiter": parsed.delimiter,
        "has_header": parsed.has_header,
        "encoding": parsed.encoding,
        "score": score,
        "grade": grade,
        "verdict": verdict,
        "counts": counts,
        "findings": findings,
        "columns_profile": [p.to_dict(top_n=top_n) for p in profiles],
    }


def render_text(result, use_color=True):
    """Coloured (unless disabled) plain-text report."""
    lines = []
    b = lambda t: _paint(t, COLORS["bold"], use_color)
    lines.append(b(f"CsvLens — {result['file']}"))
    lines.append(f"Rows: {result['rows']}  Columns: {result['columns']}  "
                 f"Delimiter: {result['delimiter']!r}  Encoding: {result['encoding']}")
    score_line = (f"Score: {result['score']}/100  Grade: {result['grade']}  "
                  f"Verdict: {result['verdict']}")
    lines.append(_paint(score_line, COLORS["score"], use_color))
    counts = result["counts"]
    lines.append(f"Findings: {counts.get('error', 0)} error(s), "
                 f"{counts.get('warning', 0)} warning(s), "
                 f"{counts.get('info', 0)} info")
    lines.append("")
    lines.append(b("Columns:"))
    for col in result["columns_profile"]:
        num = ""
        if col["numeric_min"] is not None:
            num = (f"  min {col['numeric_min']} max {col['numeric_max']} "
                   f"mean {col['numeric_mean']}")
        lines.append(
            f"  {col['name']}: {col['inferred_type']}, "
            f"missing {col['missing']} ({col['missing_pct']}%), "
            f"distinct {col['distinct']},{num} "
            f"length {col['min_length']}–{col['max_length']}")
        for top in col["top_values"]:
            lines.append(f"      {top['value']!r} x{top['count']}")
    lines.append("")
    lines.append(b("Issues:"))
    if not result["findings"]:
        lines.append("  No issues found.")
    else:
        for f in result["findings"]:
            label = _paint(f["severity"].upper(), COLORS[f["severity"]], use_color)
            col = f" [{f['column']}]" if f["column"] else ""
            lines.append(f"  {label} {f['rule']}{col}: {f['message']}")
    return "\n".join(lines) + "\n"


def render_json(result):
    return json.dumps(result, indent=2, ensure_ascii=False) + "\n"


def _esc(value):
    return html.escape(str(value), quote=True)


def render_html(result, title="CsvLens report"):
    """Single self-contained interactive HTML report."""
    cols_html = []
    for col in result["columns_profile"]:
        tops = "".join(
            f"<li>{_esc(t['value'])} <span>×{t['count']}</span></li>"
            for t in col["top_values"])
        num = ""
        if col["numeric_min"] is not None:
            num = (f"<div class='stat'>min <b>{_esc(col['numeric_min'])}</b> "
                   f"max <b>{_esc(col['numeric_max'])}</b> "
                   f"mean <b>{_esc(col['numeric_mean'])}</b></div>")
        cols_html.append(f"""
        <article class='card' data-col='{ _esc(col['name']) }'>
          <h3>{_esc(col['name'])}</h3>
          <div class='type'>{_esc(col['inferred_type'])}</div>
          <div class='stat'>missing <b>{col['missing']} ({col['missing_pct']}%)</b>
            distinct <b>{col['distinct']}</b></div>
          <div class='stat'>length <b>{col['min_length']}–{col['max_length']}</b></div>
          {num}
          <ol class='top'>{tops}</ol>
        </article>""")
    issues_html = []
    for f in result["findings"]:
        col = f" · {_esc(f['column'])}" if f["column"] else ""
        issues_html.append(
            f"<li class='issue' data-sev='{_esc(f['severity'])}'>"
            f"<span class='sev {_esc(f['severity'])}'>{_esc(f['severity'])}</span> "
            f"<b>{_esc(f['rule'])}</b>{col}: {_esc(f['message'])}</li>")
    issues_block = ("\n".join(issues_html)
                    if issues_html else "<li class='issue'>No issues found.</li>")
    counts = result["counts"]
    return f"""<!DOCTYPE html>
<html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>{_esc(title)}</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
  background:#0f172a;color:#f1f5f9;margin:0;padding:24px}}
h1{{font-size:28px;margin:0 0 4px}} .muted{{color:#94a3b8}}
.score{{font-size:56px;font-weight:800;color:#10b981}}
.card{{background:#1e293b;border-radius:14px;padding:16px;margin:12px 0}}
.type{{display:inline-block;background:#10b98122;color:#10b981;
  border:1px solid #10b98155;border-radius:999px;padding:2px 10px;font-size:13px}}
.stat{{color:#94a3b8;margin-top:6px}} .stat b{{color:#f1f5f9}}
.top li span{{color:#94a3b8}}
.chip{{border:1px solid #334155;background:#1e293b;color:#f1f5f9;
  border-radius:999px;padding:6px 14px;cursor:pointer;margin-right:8px}}
.chip.active{{background:#10b981;color:#0f172a;border-color:#10b981}}
.issue{{background:#1e293b;border-radius:10px;padding:10px 14px;margin:8px 0;
  list-style:none}}
.sev{{border-radius:999px;padding:2px 9px;font-size:12px;text-transform:uppercase}}
.sev.error{{background:#ef444433;color:#f87171}}
.sev.warning{{background:#f59e0b33;color:#fbbf24}}
.sev.info{{background:#38bdf833;color:#38bdf8}}
ul{{padding:0}}
</style></head><body>
<h1>CsvLens report</h1>
<p class='muted'>{_esc(result['file'])} · {result['rows']} rows ·
{result['columns']} columns · delimiter {_esc(repr(result['delimiter']))}</p>
<div class='score'>{result['score']}<span style='font-size:24px'>/100</span></div>
<p>Grade <b>{_esc(result['grade'])}</b> · Verdict <b>{_esc(result['verdict'])}</b> ·
{counts.get('error', 0)} error(s), {counts.get('warning', 0)} warning(s),
{counts.get('info', 0)} info</p>
<h2>Columns</h2>
{''.join(cols_html)}
<h2>Issues</h2>
<div id='filters'>
<button class='chip active' data-filter='all'>All</button>
<button class='chip' data-filter='error'>Errors</button>
<button class='chip' data-filter='warning'>Warnings</button>
<button class='chip' data-filter='info'>Info</button>
</div>
<ul id='issues'>{issues_block}</ul>
<script>
document.querySelectorAll('#filters .chip').forEach(function(btn){{
  btn.addEventListener('click', function(){{
    document.querySelectorAll('#filters .chip').forEach(function(b){{
      b.classList.remove('active'); }});
    btn.classList.add('active');
    var f = btn.dataset.filter;
    document.querySelectorAll('#issues .issue').forEach(function(li){{
      li.style.display = (f === 'all' || li.dataset.sev === f) ? '' : 'none';
    }});
  }});
}});
</script>
</body></html>
"""


def render(result, fmt, use_color=True):
    if fmt == "json":
        return render_json(result)
    if fmt == "html":
        return render_html(result)
    return render_text(result, use_color=use_color)
