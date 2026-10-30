"""Static private challenge pages; all supplied text is treated as text."""
from __future__ import annotations

from base64 import b64encode
import html
from pathlib import Path
import math
import re


SITE_CSS = """
:root{--cream:#f8f9f4;--paper:#fff;--ink:#203c37;--text:#465953;--muted:#64756b;--line:#dfe6d9;--green:#265e52;--pale:#edf3e7;--amber:#80602b}
*{box-sizing:border-box}html{scroll-padding-top:24px}body{margin:0;background:var(--cream);color:var(--text);font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}a{color:var(--green);text-underline-offset:4px}button,input{font:inherit}button,a,summary{touch-action:manipulation}a:focus-visible,summary:focus-visible,button:focus-visible,input:focus-visible,[tabindex]:focus-visible{outline:3px solid #8cae8b;outline-offset:4px}h1,h2,h3,h4,p{margin:0}h1,h2,h3,h4{color:var(--ink);line-height:1.25}h1{font-size:clamp(30px,4vw,48px);letter-spacing:-1.4px;max-width:900px}h2{font-size:19px;letter-spacing:-.3px}h3{font-size:15px}h4{font-size:14px}.skip-link{position:absolute;left:16px;top:-80px;padding:10px 15px;background:var(--green);color:white;z-index:2}.skip-link:focus{top:12px}.site-header{border-bottom:1px solid var(--line);background:#fcfdf8}.header-inner{max-width:1180px;margin:auto;padding:22px 30px;display:flex;justify-content:space-between;align-items:center;gap:20px}.brand{display:inline-flex;align-items:center;gap:10px;font-size:19px;font-weight:750;letter-spacing:-.5px;color:var(--ink)}.brand img{display:block;width:36px;height:36px;flex-shrink:0}.site-nav{display:flex;gap:24px;flex-wrap:wrap;font-size:12px}.site-nav a{text-decoration:none}.site-nav a:hover{text-decoration:underline}main{max-width:1180px;margin:auto;padding:38px 30px 56px}section,article,details{min-width:0;scroll-margin-top:24px}.hero{padding:4px 0 28px}.draft-line{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-bottom:20px}.badge{display:inline-block;border-radius:20px;background:#e9edda;color:#526337;padding:5px 11px;font-size:11px;font-weight:650;letter-spacing:.5px}.version{color:var(--muted);font-size:11px;overflow-wrap:anywhere}.hero h1{overflow-wrap:anywhere}.hero-note{margin-top:16px;max-width:730px;font-size:14px}.overview{max-width:900px;margin-top:25px}.eyebrow{color:var(--green);font-size:10px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase}.overview p{margin-top:8px;font-size:17px;line-height:1.7;overflow-wrap:anywhere}.card-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:17px;margin:4px 0 20px}.card{background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:24px}.card h2{margin:9px 0 16px}.card p{font-size:13px;overflow-wrap:anywhere}.card .note{font-size:12px;color:var(--muted);margin-top:13px}.facts{margin:0}.facts>div{display:flex;justify-content:space-between;gap:16px;padding:8px 0;border-bottom:1px solid #eef1e9;font-size:13px}.facts>div:last-child{border-bottom:0}.facts dt{color:var(--muted)}.facts dd{margin:0;text-align:right;color:var(--ink);font-weight:600;overflow-wrap:anywhere;max-width:60%}.score{font-size:36px;line-height:1.2;color:var(--green);font-weight:650;letter-spacing:-.8px;margin:8px 0}.score.pending{font-size:21px;letter-spacing:-.4px}.metric-name{font-weight:650;color:var(--ink)}.policy-grid{display:grid;grid-template-columns:1.15fr 1fr;gap:17px;margin-bottom:20px}.policy-grid .card{background:#f1f5eb}.policy-grid h2{margin-top:0}.policy-list{padding-left:20px;margin:0;font-size:13px}.policy-list li+li{margin-top:9px}.resource-note{color:var(--amber);font-size:12px!important;margin-bottom:12px}.budget-note{margin-top:12px;max-height:9rem;overflow:auto;overscroll-behavior:contain;white-space:pre-wrap;padding-right:6px}.document{border:1px solid var(--line);border-radius:14px;background:var(--paper);overflow:hidden;margin-top:20px}.document>summary{padding:20px 24px;cursor:pointer;color:var(--ink);font-size:16px;font-weight:650}.document>summary::marker{color:var(--green)}.document>summary span{font-size:12px;color:var(--muted);font-weight:400;margin-left:12px}.readme-scroll{max-height:34rem;max-height:min(65vh,34rem);overflow:auto;overscroll-behavior:contain;scrollbar-width:thin;border-top:1px solid var(--line);padding:25px 28px;overflow-wrap:anywhere;font-size:13px}.readme-scroll h3{font-size:18px;margin:23px 0 12px}.readme-scroll h4{margin:20px 0 10px}.readme-scroll>:first-child{margin-top:0}.readme-scroll p{margin:10px 0}.readme-scroll ul{padding-left:22px;margin:12px 0}.readme-scroll li+li{margin-top:7px}.readme-scroll blockquote{margin:10px 0;padding:8px 15px;border-left:3px solid #c8d8bd;background:#f8faf4;white-space:pre-wrap}.readme-scroll pre{padding:15px;background:#f3f6ef;white-space:pre-wrap;overflow-wrap:anywhere}.readme-scroll code{font-size:.92em;background:#eff3e9;border-radius:3px;padding:1px 4px}.organizer-panel{border:1px solid var(--line);border-radius:14px;padding:24px;background:white;margin-top:20px;overflow-wrap:anywhere}.organizer-panel:empty{display:none}.organizer-panel h2{margin:18px 0 12px}.organizer-panel>h2:first-child{margin-top:0}.organizer-panel p{margin:10px 0;font-size:13px}.organizer-panel ul{max-height:20rem;overflow:auto;padding-left:22px;overscroll-behavior:contain;font-size:13px}.organizer-panel li+li{margin-top:8px}.organizer-panel input{max-width:100%;font-size:13px}.organizer-panel button{border:0;border-radius:7px;padding:10px 14px;background:var(--green);color:white;cursor:pointer;font-size:13px;min-height:42px}.organizer-panel button:disabled{opacity:.5;cursor:not-allowed}.organizer-panel pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:15rem;overflow:auto;font-size:12px}.site-footer{margin-top:27px;color:var(--muted);font-size:12px}
.facts .long-fact{max-height:8rem;overflow:auto;overscroll-behavior:contain;padding-right:5px}
@media(max-width:850px){.card-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.card-grid>.card:last-child{grid-column:1/-1}.policy-grid{grid-template-columns:1fr}.header-inner{padding:19px 24px}main{padding:28px 24px 40px}}
@media(max-width:540px){body{font-size:14px}.header-inner{padding:17px 18px;align-items:flex-start;flex-direction:column;gap:14px}.site-nav{gap:22px;font-size:12px}main{padding:25px 18px 35px}.hero{padding-bottom:22px}.hero h1{letter-spacing:-.8px}.hero-note{font-size:13px}.overview p{font-size:15px}.card-grid{grid-template-columns:1fr;gap:13px}.card-grid>.card:last-child{grid-column:auto}.card,.organizer-panel{padding:20px}.policy-grid{gap:13px}.document>summary{padding:18px 20px}.document>summary span{display:block;margin:5px 0 0 17px}.readme-scroll{padding:20px;max-height:60vh}.draft-line{gap:10px;margin-bottom:17px}.facts>div{gap:10px}.site-footer{font-size:11px}}
@media print{.site-header,.site-nav,.organizer-panel,.skip-link{display:none}main{max-width:none;padding:0}.card,.document{break-inside:avoid}.readme-scroll{max-height:none;overflow:visible}.site-footer{border-top:1px solid var(--line);padding-top:12px}}
""".strip()


_METRICS = {"accuracy": "Accuracy", "balanced_accuracy": "Balanced accuracy",
            "roc_auc": "Area under the ROC curve", "rmse": "Root mean squared error",
            "mae": "Mean absolute error"}


def _text(value):
    return html.escape(str(value), quote=True)


def _inline(value):
    """A small text-only Markdown subset. No HTML, images, or active links."""
    parts = re.split(r"(\*\*[^\n]+?\*\*|`[^`\n]+`)", value)
    return "".join("<strong>" + _text(p[2:-2]) + "</strong>" if p.startswith("**") and p.endswith("**")
                   else "<code>" + _text(p[1:-1]) + "</code>" if p.startswith("`") and p.endswith("`")
                   else _text(p) for p in parts)


def _readme_html(readme):
    blocks, paragraph, quoted, bullets, code = [], [], [], [], []
    in_code = False

    def flush():
        if paragraph:
            blocks.append("<p>" + _inline(" ".join(paragraph)) + "</p>")
            paragraph.clear()
        if quoted:
            blocks.append("<blockquote>" + _inline("\n".join(quoted)) + "</blockquote>")
            quoted.clear()
        if bullets:
            blocks.append("<ul>" + "".join("<li>" + _inline(line) + "</li>" for line in bullets) + "</ul>")
            bullets.clear()

    for raw in readme.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            flush()
            if in_code:
                blocks.append("<pre><code>" + _text("\n".join(code)) + "</code></pre>")
                code.clear()
            in_code = not in_code
        elif in_code:
            code.append(raw)
        elif not line:
            flush()
        elif re.match(r"^#{1,6}\s", line):
            flush()
            heading, content = line.split(" ", 1)
            tag = "h3" if len(heading) <= 2 else "h4"
            blocks.append(f"<{tag}>" + _inline(content) + f"</{tag}>")
        elif line.startswith("> ") or line == ">":
            if paragraph or bullets:
                flush()
            quoted.append(html.unescape(line[1:].lstrip()))
        elif line.startswith(("- ", "* ")):
            if paragraph or quoted:
                flush()
            bullets.append(line[2:])
        else:
            if quoted or bullets:
                flush()
            paragraph.append(line)
    flush()
    if code:
        blocks.append("<pre><code>" + _text("\n".join(code)) + "</code></pre>")
    return "\n".join(blocks) or "<p>No README has been recorded.</p>"


def _overview(spec, readme):
    value = str(spec.get("overview") or "").strip()
    if not value:
        # New interviews use Research problem; saved older drafts use Question.
        for heading in ("Research problem", "Question"):
            match = re.search(r"^### " + re.escape(heading) + r"[ \t]*\r?\n(.*?)(?=^#{1,3} |\Z)", readme, re.MULTILINE | re.DOTALL)
            if match:
                value = " ".join(html.unescape(line[1:].strip()) for line in match[1].splitlines() if line.startswith(">"))
                if value:
                    break
    if not value:
        value = "The scientific question is still to be recorded. Review the README for the current statements and open decisions."
    if len(value) > 550:
        value = value[:547].rsplit(" ", 1)[0] + "…"
    return _text(value)


def _number(value, missing="Not recorded"):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.6g}"
    return missing


def _facts(rows):
    return '<dl class="facts">' + "".join("<div><dt>" + _text(label) + "</dt><dd" +
                                          (' class="long-fact" tabindex="0"' if len(str(value)) > 140 else "") +
                                          ">" + _text(value) + "</dd></div>" for label, value in rows) + "</dl>"


def render_site(spec, readme, baseline):
    """Render an inert review page; the caller supplies already-redacted text.

    The authenticated preview can replace ORGANIZER_CONTROLS. The packaged page
    needs only the adjacent site.css file and has no scripts or network embeds.
    """
    title = _text(spec.get("title") or "Challenge draft")
    logo = "data:image/svg+xml;base64," + b64encode((Path(__file__).parent / "static" / "bold-butterfly.svg").read_bytes()).decode("ascii")
    version = _text(spec.get("version") or "Not assigned")
    mode = spec.get("competition_type")
    mode_label = {"prediction": "Prediction submissions", "code": "Code submissions"}.get(mode, "Format not selected")
    metric = spec.get("metric") or {}
    metric_label = _METRICS.get(metric.get("name"), str(metric.get("name") or "Metric not selected"))
    direction = {"maximize": "Higher scores are better.", "minimize": "Lower scores are better."}.get(metric.get("direction"), "Score direction needs review.")
    data = spec.get("data") or {}
    split = spec.get("split") or {}
    training = split.get("training")
    final = split.get("final_test")
    split_note = "The data split needs review."
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1 for v in (training, final)):
        split_note = f"{training:.0%} training pool / {final:.0%} final test. Development rows come from the training pool."
    dataset_facts = _facts([("Training rows", _number(data.get("training_rows"), "Not prepared")),
                            ("Development rows", _number(data.get("validation_rows"), "Not prepared")),
                            ("Final test rows", _number(data.get("final_rows"), "Not prepared")),
                            ("Target", spec.get("target") or "Not selected")])
    score = _number((baseline or {}).get("score"), "Not measured")
    measured = score != "Not measured"
    score_class = "score" if measured else "score pending"
    baseline_metric = _METRICS.get((baseline or {}).get("metric"), str((baseline or {}).get("metric") or metric_label))
    result_note = (f"The constant predictor scored {score} for {baseline_metric.lower()} on {_number(baseline.get('rows'))} development rows. This tests the submission pipeline. It does not reproduce a scientific reference method."
                   if measured else "No measured development result is available for this draft.")
    quota = _number(spec.get("daily_submission_limit"), "Not confirmed")
    submission_facts = _facts([("Allowance per team", f"{quota} per UTC day"), ("Daily reset", spec.get("quota_reset") or "Not recorded")])
    if mode == "prediction":
        access = ["Researchers receive training data and development and final test inputs without answer labels.",
                  "Researchers submit a prediction for each input ID. Development submissions return a score.",
                  "Development and final test answers remain private. Final scores are withheld during development."]
    elif mode == "code":
        access = ["Researchers receive training data and representative input examples. Development and final test inputs remain private.",
                  "Submitted code is evaluated on hidden inputs. Test answer labels stay outside the submitted code.",
                  "Final scores are withheld during development.",
                  "Code execution requires a verified sandbox. The README preparation results record the trial status for this draft."]
    else:
        access = ["Choose prediction or code submissions before the access policy is confirmed.",
                  "Answer labels remain private. Final scores are withheld during development."]
    access_html = "".join("<li>" + _text(line) + "</li>" for line in access)
    execution = spec.get("execution") or {}
    resource_heading = "Worker limits" if mode == "code" else "Proposed resources"
    resource_note = (execution.get("resource_status") or "Review the worker limits before use.") if mode == "code" else "Initial limits and budgets need organizer review."
    resources = execution.get("resources") or {}
    resource_rows = [("CPU cores", _number(resources.get("cpu"))), ("GPU count", _number(resources.get("gpu"))),
                     ("Memory (MiB)", _number(resources.get("memory_mib"))), ("Program limit (seconds)", _number(resources.get("seconds")))]
    if "cpu_seconds" in resources:
        resource_rows.append(("CPU time (seconds)", _number(resources["cpu_seconds"])))
    if "job_deadline_seconds" in resources:
        resource_rows.append(("Job deadline (seconds)", _number(resources["job_deadline_seconds"])))
    resource_facts = _facts(resource_rows)
    budgets = spec.get("budgets") or {}
    budget_fallback = "See recorded plan" if budgets.get("recorded_plan") else "Not recorded"
    budget_facts = _facts([("Compute budget (USD)", budgets.get("compute_usd") or budget_fallback),
                          ("Token budget (USD)", budgets.get("tokens_usd") or budget_fallback)])
    plan = '<p class="budget-note" tabindex="0">' + _text(budgets["recorded_plan"]) + "</p>" if budgets.get("recorded_plan") else ""
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>{title} · BOLD AutoKaggle</title><link rel="icon" type="image/svg+xml" href="{logo}"><link rel="stylesheet" href="site.css"></head>
<body><a class="skip-link" href="#overview">Skip to challenge</a>
<header class="site-header"><div class="header-inner"><div class="brand"><img src="{logo}" width="36" height="36" alt="" aria-hidden="true">BOLD AutoKaggle</div><nav class="site-nav" aria-label="Challenge sections"><a href="#overview">Overview</a><a href="#challenge-data">Data &amp; scoring</a><a href="#challenge-readme">Full README</a></nav></div></header>
<main id="overview"><section class="hero" aria-labelledby="challenge-title"><div class="draft-line"><span class="badge">PRIVATE DRAFT</span><span class="version">Version {version}</span></div><h1 id="challenge-title">{title}</h1><p class="hero-note">Prepared for organizer review. This draft is not published. Review the recorded decisions and first results before release.</p><div class="overview"><h2 class="eyebrow">Scientific question · recorded statement</h2><p>{_overview(spec, readme)}</p></div></section>
<section id="challenge-data" class="card-grid" aria-label="Challenge summary">
<article class="card"><p class="eyebrow">Dataset</p><h2>Data at a glance</h2>{dataset_facts}<p class="note">{_text(split_note)}</p><p class="note">Split method: {_text(split.get('method') or 'Not selected')}.</p></article>
<article class="card"><p class="eyebrow">Submission pipeline test</p><h2>{_text(metric_label)}</h2><div class="{score_class}">{_text(score)}</div><p>{_text(result_note)}</p><p class="note">{_text(direction)} Final data were not scored for this result.</p><p class="note">Metric version: {_text(metric.get('version') or 'Not recorded')}.</p></article>
<article class="card"><p class="eyebrow">Submission policy</p><h2>{mode_label}</h2>{submission_facts}<p class="note">The allowance applies to each team. Invalid attempts count. Retry the same upload with the same request ID.</p><p class="note">Confirm the contract and first trial before public release.</p></article>
</section>
<section class="policy-grid" aria-label="Access and resources"><article class="card"><h2>What researchers can access</h2><ul class="policy-list">{access_html}</ul></article>
<article class="card"><h2>{_text(resource_heading)}</h2><p class="resource-note">{_text(resource_note)}</p>{resource_facts}{budget_facts}{plan}</article></section>
<details id="challenge-readme" class="document"><summary>Full challenge README <span>Recorded answers, open decisions, and preparation requirements</span></summary><div class="readme-scroll" role="region" aria-label="Full challenge README" tabindex="0">{_readme_html(readme)}</div></details>
<section id="organizer-controls" class="organizer-panel" aria-label="Organizer review tools"><!-- ORGANIZER_CONTROLS --></section>
<footer class="site-footer">BOLD AutoKaggle · Private review draft. This page does not grant publication approval or confirm email delivery.</footer>
</main></body></html>'''
