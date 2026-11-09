from __future__ import annotations

import gzip
import io
import json
import zipfile

from fastapi.testclient import TestClient
import pytest

from autokaggle import documents
from autokaggle.app import create_app

WORD = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
MATH = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
SLIDE = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
SHEET = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
TEXT_NS = 'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
TABLE_NS = 'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'


def archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out:
        for name, content in files.items():
            out.writestr(name, content)
    return buffer.getvalue()


def docx():
    return archive({"word/document.xml": f"""<w:document {WORD} {MATH}><w:body>
        <w:p><w:r><w:t>Measurement notes</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Column</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Unit</w:t></w:r></w:p></w:tc></w:tr>
        <w:tr><w:tc><w:p><w:r><w:t>decay</w:t></w:r></w:p></w:tc><w:tc><w:p><m:oMath><m:r><m:t>ns</m:t></m:r></m:oMath></w:p></w:tc></w:tr></w:tbl>
        <w:sectPr/></w:body></w:document>"""})


def pdf(text="Readable portable document text"):
    # A minimal single page PDF with one text object.
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    body, offsets = b"%PDF-1.4\n", []
    for number, content in enumerate(objects, 1):
        offsets.append(len(body))
        body += str(number).encode() + b" 0 obj\n" + content + b"\nendobj\n"
    start = len(body)
    body += b"xref\n0 6\n0000000000 65535 f \n" + b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    return body + b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + str(start).encode() + b"\n%%EOF\n"


READABLE = {
    "notes.txt": (b"Plain notes about units.", "text", "Plain notes about units."),
    "run.log": (b"2026-11-06 INFO value=3\n", "text", "INFO value=3"),
    "weird.dat": (b"An unusual extension with text.", "text", "unusual extension"),
    "script.py": (b"print('never executed')\n", "text", "never executed"),
    "latin.txt": ("caf\u00e9 r\u00e9sum\u00e9 notes".encode("latin-1"), "text", "caf"),
    "chinese.txt": ("\u5355\u4f4d\u662f\u7eb3\u79d2".encode("gb18030"), "text", "\u7eb3\u79d2"),
    "bom.txt": ("\u5355\u4f4d".encode("utf-16"), "text", "\u5355\u4f4d"),
    "windows.log": ("Tool output line".encode("utf-16-le"), "text", "Tool output"),
    "page.html": (b"<html><script>steal()</script><body><h1>Title</h1><table><tr><td>a</td><td>b</td></tr></table></body></html>", "html", "Title"),
    "paper.rtf": (rb"{\rtf1{\fonttbl{\f0 Arial;}}\f0 Unit is \'b5J\par next line}", "rtf", "Unit is"),
    "analysis.ipynb": (json.dumps({"cells": [{"cell_type": "markdown", "source": ["# Units\n", "seconds"]}]}).encode(), "notebook", "seconds"),
    "notes.txt.gz": (gzip.compress(b"Compressed log text"), "text", "Compressed log text"),
}


@pytest.mark.parametrize("name", sorted(READABLE))
def test_text_like_files_are_read(name):
    body, kind, expected = READABLE[name]
    parsed = documents.extract(body, name)
    assert parsed["kind"] == kind and expected in parsed["text"]
    assert "steal" not in parsed["text"]


def test_word_tables_and_equations_keep_their_cells():
    parsed = documents.extract(docx(), "notes.docx")
    assert parsed["kind"] == "docx"
    assert "Column | Unit" in parsed["text"] and "decay | ns" in parsed["text"]


def test_slides_sheets_and_open_documents_are_read():
    slides = archive({"ppt/slides/slide2.xml": f"<p:sld xmlns:p='x' {SLIDE}><a:p><a:r><a:t>Second</a:t></a:r></a:p></p:sld>",
                      "ppt/slides/slide1.xml": f"<p:sld xmlns:p='x' {SLIDE}><a:p><a:r><a:t>First</a:t></a:r></a:p></p:sld>"})
    parsed = documents.extract(slides, "talk.pptx")
    assert parsed["kind"] == "pptx" and parsed["text"].index("First") < parsed["text"].index("Second")
    sheet = archive({"xl/sharedStrings.xml": f"<sst {SHEET}><si><t>unit</t></si></sst>",
                     "xl/worksheets/sheet1.xml": f'<worksheet {SHEET}><sheetData><row><c t="s"><v>0</v></c><c><v>4.5</v></c></row></sheetData></worksheet>'})
    assert "unit | 4.5" in documents.extract(sheet, "table.xlsx")["text"]
    odt = archive({"mimetype": "application/vnd.oasis.opendocument.text",
                   "content.xml": f"<doc {TEXT_NS} {TABLE_NS}><text:p>Paragraph</text:p><table:table-row><table:table-cell><text:p>A</text:p></table:table-cell><table:table-cell><text:p>B</text:p></table:table-cell></table:table-row></doc>"})
    parsed = documents.extract(odt, "notes.odt")
    assert "Paragraph" in parsed["text"] and "A | B" in parsed["text"]


def test_pdf_text_is_read_with_page_markers():
    parsed = documents.extract(pdf(), "paper.pdf")
    assert parsed["kind"] == "pdf" and "[page 1]" in parsed["text"] and "Readable portable document text" in parsed["text"]


def test_ordinary_archives_list_files_and_read_text_without_nesting():
    inner = archive({"deep.txt": "Nested archive text"})
    parsed = documents.extract(archive({"readme.md": "Archive readme", "inner.zip": inner, "image.png": b"\x89PNG\r\n"}), "bundle.zip")
    assert parsed["kind"] == "archive" and "Archive readme" in parsed["text"] and "inner.zip" in parsed["text"]
    assert "Nested archive text" not in parsed["text"]


@pytest.mark.parametrize("body,reason", [
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64, "legacy Office"),
    (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image"),
    (bytes(range(256)) * 40, "no readable text"),
    (b"   \n\t  ", "no readable text"),
    (b"PK\x03\x04 damaged", "damaged"),
])
def test_unreadable_files_say_why(body, reason):
    with pytest.raises(ValueError, match=reason):
        documents.extract(body, "file.bin")


def test_an_archive_that_expands_too_far_is_refused():
    bomb = archive({f"part{i}.txt": b"0" * (20 * 1024 * 1024) for i in range(7)})
    with pytest.raises(ValueError, match="size limit"):
        documents.extract(bomb, "bomb.zip")


@pytest.fixture
def session(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/projects", json={"title": "Documents"})
        created.raise_for_status()
        root = "/api/projects/" + created.json()["id"]
        client.patch(root + "/setup", json={"organizer_email": "owner@example.org"}).raise_for_status()
        yield client, root, tmp_path / created.json()["id"]


def attach(client, root, name, body):
    return client.post(root + "/documents", files={"file": (name, body)})


def test_a_document_keeps_only_its_text_and_appears_in_the_conversation(session):
    client, root, directory = session
    response = attach(client, root, "../../notes.docx", docx())
    response.raise_for_status()
    record = response.json()["document"]
    assert record["name"] == "notes.docx" and record["kind"] == "docx"
    stored = list((directory / "documents").iterdir())
    assert [path.suffix for path in stored] == [".txt"] and "decay | ns" in stored[0].read_text(encoding="utf-8")
    view = client.get(root + "/conversation").json()
    assert view["documents"][0]["name"] == "notes.docx"
    assert "text" not in view["documents"][0] and "sha256" not in view["documents"][0]
    assert "_documents" not in client.get(root).json()


def test_attaching_the_same_file_twice_keeps_one_copy(session):
    client, root, _ = session
    first = attach(client, root, "a.txt", b"The same content.").json()["document"]
    second = attach(client, root, "b.txt", b"The same content.").json()
    assert second["document"]["id"] == first["id"] and len(second["documents"]) == 1


def test_an_unreadable_file_is_refused_with_its_reason(session):
    client, root, _ = session
    response = attach(client, root, "scan.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    assert response.status_code == 422 and "image" in response.json()["detail"]
    assert client.get(root + "/conversation").json()["documents"] == []


def test_documents_have_a_size_and_count_limit(session, monkeypatch):
    client, root, _ = session
    monkeypatch.setattr(documents, "MAX_DOCUMENT_BYTES", 10)
    assert attach(client, root, "big.txt", b"x" * 11).status_code == 422
    monkeypatch.setattr(documents, "MAX_DOCUMENT_BYTES", 1024)
    monkeypatch.setattr(documents, "MAX_DOCUMENTS", 1)
    attach(client, root, "one.txt", b"First document.").raise_for_status()
    refused = attach(client, root, "two.txt", b"Second document.")
    assert refused.status_code == 422 and "Remove one" in refused.json()["detail"]


def test_removing_a_document_deletes_its_text_and_lookup_excerpts(session):
    client, root, directory = session
    record = attach(client, root, "a.txt", b"Private measurement notes.").json()["document"]
    response = client.delete(f"{root}/documents/{record['id']}")
    response.raise_for_status()
    assert response.json()["documents"] == [] and not list((directory / "documents").iterdir())
    assert client.delete(f"{root}/documents/{record['id']}").status_code == 404


def test_documents_survive_dataset_erasure(session):
    client, root, directory = session
    attach(client, root, "a.txt", b"Context that stays out of the package.").raise_for_status()
    rows = "\n".join(f"{i},{i % 3},{i * 2}" for i in range(60))
    client.post(root + "/dataset", files={"file": ("data.csv", "id,group,target\n" + rows)}).raise_for_status()
    client.request("DELETE", root + "/dataset", json={"confirm": True}).raise_for_status()
    assert list((directory / "documents").iterdir())
    assert client.get(root + "/conversation").json()["documents"][0]["name"] == "a.txt"


def test_deleting_the_session_deletes_documents(session):
    client, root, directory = session
    attach(client, root, "a.txt", b"Private measurement notes.").raise_for_status()
    client.request("DELETE", root, json={"confirm": True}).raise_for_status()
    assert not directory.exists()
