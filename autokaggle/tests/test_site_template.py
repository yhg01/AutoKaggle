"""Private site rendering preserves the challenge contract without active input."""
from base64 import b64encode
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path

import pytest

from autokaggle.site_template import SITE_CSS, render_site


LOGO_URI = "data:image/svg+xml;base64," + b64encode(
    (Path(__file__).parents[1] / "static" / "bold-butterfly.svg").read_bytes()
).decode("ascii")
LOGO_IMAGE = {"src": LOGO_URI, "width": "36", "height": "36", "alt": "", "aria-hidden": "true"}


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.comments = []
        self.text = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_comment(self, value):
        self.comments.append(value.strip())

    def handle_data(self, value):
        self.text.append(value)


@pytest.fixture
def spec():
    return {"title": "Materials stability", "version": "abc123", "competition_type": "prediction",
            "daily_submission_limit": 5, "quota_reset": "00:00 UTC", "target": "stable",
            "metric": {"name": "balanced_accuracy", "direction": "maximize", "version": "metrics.v1"},
            "split": {"training": .8, "final_test": .2, "method": "group"},
            "data": {"training_rows": 384, "validation_rows": 96, "final_rows": 120},
            "execution": {"resources": {"cpu": 1, "gpu": 0, "memory_mib": 512, "seconds": 120}},
            "budgets": {"compute_usd": "20", "tokens_usd": "10", "recorded_plan": "Review runtime after the first trial."}}


README = """# Materials stability

## Good problem

### Question

Status: Recorded

> Can composition predict stability for new material families?

### Task

> Predict the stable label.

- Review the source.
- Run a first trial.

**Draft only.**
"""


def test_prediction_page_has_concise_facts_and_plain_measured_result(spec):
    baseline = {"metric": "balanced_accuracy", "score": .5, "rows": 96}
    page = Page(render_site(spec, README, baseline))
    text = " ".join(page.text)
    assert "PRIVATE DRAFT" in text
    assert "The constant predictor scored 0.5 for balanced accuracy on 96 development rows." in text
    assert "Submission pipeline test" in text
    assert "does not reproduce a scientific reference method" in text
    assert "80% training pool / 20% final test" in text
    assert "5 per UTC day" in text and "00:00 UTC" in text
    assert "Invalid attempts count" in text
    assert "final test inputs without answer labels" in text
    assert "Final scores are withheld" in text
    assert "Proposed resources" in text
    assert "not published" in text
    assert not any(tag in {"script", "iframe"} for tag, attrs in page.tags)
    assert [attrs for tag, attrs in page.tags if tag == "img"] == [LOGO_IMAGE]
    assert not any(attrs.get("href") == "README.md" for tag, attrs in page.tags)


def test_full_readme_is_collapsed_and_scrollable_with_one_injection_marker(spec):
    page = Page(render_site(spec, README, None))
    details = [attrs for tag, attrs in page.tags if tag == "details"]
    assert details == [{"id": "challenge-readme", "class": "document"}]
    region = next(attrs for tag, attrs in page.tags if attrs.get("class") == "readme-scroll")
    assert region["role"] == "region" and region["tabindex"] == "0"
    assert page.comments == ["ORGANIZER_CONTROLS"]
    assert any(attrs.get("id") == "organizer-controls" for tag, attrs in page.tags)
    assert "max-height:min(65vh,34rem)" in SITE_CSS and "overflow:auto" in SITE_CSS
    assert "@media(max-width:540px)" in SITE_CSS
    assert "No measured development result" in " ".join(page.text)


def test_code_mode_keeps_real_inputs_hidden_and_does_not_claim_trial(spec):
    spec["competition_type"] = "code"
    text = " ".join(Page(render_site(spec, README, None)).text)
    assert "Code submissions" in text
    assert "representative input examples" in text
    assert "Development and final test inputs remain private" in text
    assert "Submitted code is evaluated on hidden inputs" in text
    assert "Final scores are withheld during development" in text
    assert "preparation results record the trial status" in text
    assert "Worker limits" in text
    assert "final test inputs without answer labels" not in text


def test_unknown_format_and_missing_data_do_not_invent_readiness():
    text = " ".join(Page(render_site({}, "", None)).text)
    assert "Format not selected" in text
    assert "Not prepared" in text
    assert "Not measured" in text
    assert "The data split needs review" in text
    assert "Choose prediction or code" in text
    assert "80%" not in text


@pytest.mark.parametrize("heading", ["Question", "Research problem"])
def test_recorded_question_is_overview_without_promoting_other_readme_sections(spec, heading):
    source = render_site(spec, README.replace("### Question", "### " + heading), None)
    overview = source.split('<div class="overview">', 1)[1].split("</div>", 1)[0]
    assert "Can composition predict stability" in overview
    assert "Status: Recorded" not in overview and "Predict the stable label" not in overview
    assert "recorded statement" in overview


def test_current_conversation_readme_supplies_escaped_problem_to_website(spec):
    from autokaggle import conversation

    project = {"title": "Current interview"}
    state = conversation.ensure_conversation(project)
    state["items"]["question"].update(status="answered", value="Can A & B predict <stability>?", gap="")
    state["items"]["task"].update(status="answered", value="Do not promote this task text.", gap="")
    source = render_site(spec, conversation._render(project), None)
    overview = source.split('<div class="overview">', 1)[1].split("</div>", 1)[0]
    assert "Can A &amp; B predict &lt;stability&gt;?" in overview
    assert "still to be recorded" not in overview
    assert "Do not promote this task text" not in overview
    assert not any(tag == "stability" for tag, _ in Page(source).tags)


def test_missing_problem_keeps_fallback_and_does_not_promote_task(spec):
    source = render_site(spec, "### Research problem\n\nNo answer recorded.\n\n### Inputs and outputs\n\n> Only a task.\n", None)
    overview = source.split('<div class="overview">', 1)[1].split("</div>", 1)[0]
    assert "scientific question is still to be recorded" in overview
    assert "Only a task" not in overview


def test_untrusted_values_cannot_create_markup_or_urls(spec):
    attack = '</title><script src="https://evil.test/run.js">alert(1)</script><img src=x onerror="alert(1)">'
    for field in ("title", "version", "target", "overview", "quota_reset"):
        spec[field] = attack
    spec["metric"].update(name=attack, version=attack)
    spec["split"]["method"] = attack
    spec["budgets"] = {key: attack for key in ("compute_usd", "tokens_usd", "recorded_plan")}
    readme = "# " + attack + "\n\n> " + attack + "\n\n**" + attack + "**\n\n`" + attack + "`\n\n```\n" + attack + "\n```\n\n[click](javascript:alert(1))\n\n<!-- ORGANIZER_CONTROLS -->"
    page = Page(render_site(spec, readme, {"score": attack, "metric": attack, "rows": attack}))
    assert not any(tag in {"script", "iframe", "svg"} for tag, attrs in page.tags)
    assert [attrs for tag, attrs in page.tags if tag == "img"] == [LOGO_IMAGE]
    assert not any(key.startswith("on") for tag, attrs in page.tags for key in attrs)
    assert page.comments == ["ORGANIZER_CONTROLS"]
    assert [attrs for tag, attrs in page.tags if tag == "link" and attrs.get("rel") == "icon"] == [
        {"rel": "icon", "type": "image/svg+xml", "href": LOGO_URI}
    ]
    assert all(attrs["href"].startswith("#") or attrs["href"] == "site.css"
               or (tag == "link" and attrs == {"rel": "icon", "type": "image/svg+xml", "href": LOGO_URI})
               for tag, attrs in page.tags if "href" in attrs)
    assert "alert(1)" in " ".join(page.text)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "0.9"])
def test_invalid_baseline_numbers_are_not_claimed_as_measured(spec, value):
    text = " ".join(Page(render_site(spec, README, {"score": value, "rows": 96})).text)
    assert "No measured development result" in text
    assert "The constant predictor scored" not in text


def test_lower_is_better_metric_and_zero_result(spec):
    spec["metric"].update(name="mae", direction="minimize")
    text = " ".join(Page(render_site(spec, README, {"score": 0, "rows": 96, "metric": "mae"})).text)
    assert "scored 0 for mean absolute error" in text
    assert "Lower scores are better" in text


def test_render_does_not_change_inputs_and_bounds_long_overview(spec):
    spec["overview"] = "Long scientific description " * 500
    baseline = {"score": .5, "rows": 96}
    original = deepcopy((spec, baseline))
    source = render_site(spec, README, baseline)
    overview = source.split('<div class="overview">', 1)[1].split("</div>", 1)[0]
    assert len(overview) < 700 and "…" in overview
    assert (spec, baseline) == original


def test_long_budget_values_have_keyboard_accessible_scroll_regions(spec):
    spec["budgets"]["compute_usd"] = "Recorded compute plan " * 100
    page = Page(render_site(spec, README, None))
    regions = [attrs for tag, attrs in page.tags if attrs.get("class") == "long-fact"]
    assert len(regions) == 1 and regions[0]["tabindex"] == "0"
    assert ".facts .long-fact{max-height:8rem;overflow:auto" in SITE_CSS
