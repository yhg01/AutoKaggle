from html.parser import HTMLParser
from pathlib import Path

from autokaggle.lite_preview import render_preview


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.text = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def project():
    return {"id": "project-1", "title": "NetHack ascension", "setup": {"organizer_email": "private@example.org"},
            "lite": {"contract": {"objective": "Measure long-horizon credit assignment.", "task_kind": "environment",
                "artifact_type": "checkpoint", "metric": "success_rate", "evaluation_count": 100,
                "success_definition": "Ascension as reported by the pinned environment.", "inputs": "Standard NLE observations",
                "outputs": "One legal action", "evaluation_protocol": "Run a frozen policy on the fixed seeds.",
                "timeout_seconds": 300, "total_timeout_seconds": 21600, "max_steps": None,
                "answer_exposure": "environment_generated", "failure_policy": "zero", "training_policy": "No evaluation adaptation",
                "compute_budget": "A100 × 1 × 6 h", "allowed_data": "Declared training trajectories", "dependencies": "nle==1.3.0",
                "source_url": "https://github.com/NetHack-LE/nle", "source_revision": "a" * 40,
                "adapter_entrypoint": "gym_adapter:evaluate", "env_id": "NetHackScore-v0", "success_key": "is_ascended",
                "seed_method": "core_disp", "baseline": "Optional reference. No reproduction claim."},
            "sources": [{"kind": "repository", "url": "https://github.com/NetHack-LE/nle", "commit": "a" * 40}],
            "results": [{"version": "v1"}, {"version": "old-version"}]}}


def test_preview_uses_actual_contract_and_functional_local_actions():
    page = render_preview(project(), "# NetHack\n\n## Run\n\n1. Prepare a manifest.\n2. Run `python run.py`.", "v1")
    doc = Document(page)
    text = " ".join(" ".join(doc.text).split())
    assert "NetHack ascension" in text
    assert "Model checkpoint" in text and "Success rate" in text
    assert "100 episodes" in text
    assert "21600 seconds" in text and "No step limit; time limits still apply" in text
    assert "Standard NLE observations" in text and "is_ascended" in text
    assert "1 report" in text
    links = [attrs.get("href") for tag, attrs in doc.tags if tag == "a"]
    assert "/api/projects/project-1/lite/package" in links
    assert "/api/projects/project-1/lite/readme.md" in links
    assert "/lite?project=project-1#results" in links
    assert "private@example.org" not in page
    assert any(tag == "ol" for tag, _ in doc.tags)
    assert "## Run" not in text
    assert "Researcher-reported results" in text
    assert "Independent reproduction is not established" in text


def test_all_researcher_and_source_markup_stays_text():
    item = project()
    attack = '<img src=x onerror="alert(1)"><script>stolen()</script>'
    item["title"] = attack
    for field in ("objective", "inputs", "outputs", "success_definition", "dependencies", "baseline"):
        item["lite"]["contract"][field] = attack
    item["lite"]["sources"] = [{"kind": attack, "title": attack, "url": "javascript:alert(1)", "sha256": attack}]
    item["lite"]["contract"]["source_url"] = "javascript:alert(1)"
    doc = Document(render_preview(item, "# " + attack + "\n\n" + attack + "\n\n```html\n" + attack + "\n```", 'v1" onmouseover="attack()'))
    assert not any(tag in {"script", "iframe", "object", "embed"} for tag, _ in doc.tags)
    assert not any(key.startswith("on") or key == "style" for _, attrs in doc.tags for key in attrs)
    assert all(attrs.get("src") == "/static/bold-butterfly.svg" for tag, attrs in doc.tags if tag == "img")
    assert not any(attrs.get("href", "").startswith("javascript:") for _, attrs in doc.tags)
    assert attack in " ".join(doc.text)


def test_source_links_reject_credentials_and_control_characters():
    item = project()
    item["lite"]["sources"] = [{"kind": "paper", "url": value} for value in
        ["https://user:password@example.org/paper", "https://example.org/\npaper", "data:text/html,attack", "uploaded:paper.pdf"]]
    doc = Document(render_preview(item, "", "v1"))
    external = [a["href"] for tag, a in doc.tags if tag == "a" and a.get("href", "").startswith("http")]
    assert external == ["https://github.com/NetHack-LE/nle"]
    assert all(a.get("rel") == "noopener noreferrer" for tag, a in doc.tags if tag == "a" and a.get("target") == "_blank")


def test_identifier_cannot_escape_local_paths_or_html_attributes():
    item = project()
    item["id"] = 'other/../x" onclick="attack()'
    doc = Document(render_preview(item, "", "v1"))
    for tag, attrs in doc.tags:
        assert "onclick" not in attrs
        if tag == "a" and attrs.get("href", "").startswith("/api/projects/"):
            assert "/../" not in attrs["href"]
            assert "%22" in attrs["href"]


def test_batch_task_does_not_invent_environment_requirements():
    item = project()
    item["lite"]["contract"].update(task_kind="batch", artifact_type="predictions", metric="rmse", answer_exposure="visible", failure_policy="fail_run")
    text = " ".join(Document(render_preview(item, "", "v1")).text)
    assert "100 seeded runs" in text
    assert "Root mean squared error" in text
    assert "Answers are visible" in text
    assert "Mark the run incomplete" in text
    assert "Step limit" not in text


def test_markdown_html_and_links_are_not_executable_and_code_is_readable():
    readme = "# A safe title\n\n## Run\n\n- **Checkpoint:** `model.pt`\n\n[x](javascript:alert(1))\n\n```\n<script>not executable</script>\n"
    doc = Document(render_preview(project(), readme, "v1"))
    assert not any(tag == "script" for tag, _ in doc.tags)
    assert any(tag == "strong" for tag, _ in doc.tags)
    assert any(tag == "pre" for tag, _ in doc.tags)
    assert "[x](javascript:alert(1))" in " ".join(doc.text)
    assert "<script>not executable</script>" in " ".join(doc.text)


def test_preview_uses_csp_compatible_styles_and_responsive_document_layout():
    doc = Document(render_preview(project(), "", "v1"))
    assert not any(tag in {"script", "style"} for tag, _ in doc.tags)
    assert any(tag == "link" and a.get("href", "").startswith("/static/lite-preview.css") for tag, a in doc.tags)
    assert any(tag == "meta" and a.get("name") == "viewport" for tag, a in doc.tags)
    css = (Path(__file__).parents[1] / "static/lite-preview.css").read_text()
    assert "@media(max-width:700px)" in css
    assert ".layout{display:flex;flex-direction:column" in css
    assert "overflow-wrap:anywhere" in css
    assert "overflow:hidden" not in css
