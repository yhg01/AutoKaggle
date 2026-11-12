"""Full source preparation must retain consent, review, and import bounds."""
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from autokaggle import sources
from autokaggle.tests.test_source_imports import app, session, complete, fake_sources


def paper_bytes():
    writer = PdfWriter()
    page = writer.add_blank_page(width=500, height=600)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 30 Td (" + b"The molecular study predicts solubility from SMILES and reports RMSE. " * 4 + b") Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_uploaded_paper_is_reviewed_before_becoming_full_evidence(app, monkeypatch):
    fake_sources(monkeypatch)
    with TestClient(app) as client:
        root = session(client)
        before = client.get(root + "/conversation").json()
        uploaded = client.post(root + "/sources/paper", files={"file": ("molecules.pdf", paper_bytes(), "application/pdf")})
        assert uploaded.status_code == 200
        record = uploaded.json()["uploaded_paper"]
        assert record["url"] == "uploaded:molecules.pdf" and len(record["sha256"]) == 64
        assert "text" not in record
        assert client.get(root + "/conversation").json()["messages"] == before["messages"]
        response = client.post(root + "/sources", json={"repository_url": "https://github.com/example/research", "request_id": "pdf-import"})
        assert response.status_code == 200
        job = complete(client, root)
        assert job["status"] == "ready"
        assert job["sources"][0]["sha256"] == record["sha256"]
        assert job["sources"][1]["commit"] == "a" * 40
        assert not any(m["role"] == "user" for m in client.get(root + "/conversation").json()["messages"])
        approved = client.post(root + "/sources/apply", json={"brief": job["proposal"]["brief"], "request_id": "pdf-approved"})
        assert approved.status_code == 200 and approved.json()["entry_path"] == "speedrun"
        assert "lite" not in app.state.store.get(root.rsplit("/", 1)[1], client.cookies["autokaggle_owner"])
        client.delete(root + "/sources").raise_for_status()
        assert client.get(root + "/sources").json() == {"status": "not_started"}


def test_upload_needs_consent_and_ownership_before_extraction(app, monkeypatch):
    def forbidden(*args):
        pytest.fail("Unauthorized or unconsented PDF must not be parsed")
    monkeypatch.setattr(sources, "uploaded_paper", forbidden)
    with TestClient(app) as owner, TestClient(app) as stranger:
        identifier = owner.post("/api/projects", json={}).json()["id"]
        route = f"/api/projects/{identifier}/sources/paper"
        assert owner.post(route, files={"file": ("x.pdf", b"%PDF")}).status_code == 428
        assert stranger.post(route, files={"file": ("x.pdf", b"%PDF")}).status_code == 404


def test_paper_replacement_invalidates_old_proposal_and_keeps_import_allowance(app, monkeypatch):
    fake_sources(monkeypatch)
    with TestClient(app) as client:
        root = session(client)
        client.post(root + "/sources", json={"paper_url": "https://example.org/paper", "request_id": "first"}).raise_for_status()
        assert complete(client, root)["status"] == "ready"
        replaced = client.post(root + "/sources/paper", files={"file": ("new.pdf", paper_bytes())}).json()
        assert replaced["status"] == "not_started" and replaced["attempts"] == 1
        assert "proposal" not in replaced
        assert client.post(root + "/sources/apply", json={"brief": "Old brief", "request_id": "stale"}).status_code == 409


def test_pdf_rejects_bad_size_and_format(app, monkeypatch):
    with TestClient(app) as client:
        root = session(client)
        assert client.post(root + "/sources/paper", files={"file": ("x.pdf", b"text")}).status_code == 422
        monkeypatch.setattr(sources, "MAX_PAPER", 8)
        assert client.post(root + "/sources/paper", files={"file": ("x.pdf", b"%PDF-" + b"x" * 20)}).status_code == 422
        assert client.get(root + "/sources").json() == {"status": "not_started"}


def test_source_brief_preserves_longer_supported_protocol(app, monkeypatch):
    monkeypatch.setattr(sources.advisor, "configured", lambda: True)
    proposal = {"title": "Molecular protocol", "brief": "Supported source detail. " * 170, "open_questions": []}
    monkeypatch.setattr(sources.conversation, "_provider", lambda *args: proposal)
    assert sources.proposal({}, [], lambda _: None) == proposal
    assert sources.proposal_schema()["properties"]["brief"]["maxLength"] == 6000
    proposal["brief"] = "x" * 6001
    with pytest.raises(ValueError, match="valid starting brief"):
        sources.proposal({}, [], lambda _: None)


def test_rules_fallback_does_not_claim_a_website_repository_is_an_implementation(monkeypatch):
    monkeypatch.setattr(sources.advisor, "configured", lambda: False)
    result = sources.proposal({}, [{"url": "https://github.com/bold-lab-ai/nano-sigma"}], lambda _: None)
    assert "source reference" in result["brief"]
    assert "starting implementation" not in result["brief"]
    assert result["open_questions"]
