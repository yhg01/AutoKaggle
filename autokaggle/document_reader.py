"""Bounded subprocess that turns one untrusted file into plain text.

It reads the file from standard input and prints JSON. It never runs file content.
Run it with `python -I`, so it uses only this file, the standard library, and pypdf.
"""
import gzip
from html.parser import HTMLParser
import io
import json
import re
import sys
import zipfile
from xml.etree import ElementTree

MAX_INPUT = 64 * 1024 * 1024
MAX_CHARS = 400_000
MAX_PDF_PAGES = 300
MAX_MEMBER = 32 * 1024 * 1024
MAX_MEMBERS_READ = 40
MAX_UNCOMPRESSED = 128 * 1024 * 1024

WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MATH = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
DRAWING = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
SHEET = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
ODF_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
ODF_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"

UNREADABLE = (
    (b"\xd0\xcf\x11\xe0", "This is a legacy Office file. Save it as .docx, .xlsx, .pptx, or PDF, then attach it again."),
    (b"\x89PNG", "This is an image, and images are not read. Attach a text or PDF version."),
    (b"\xff\xd8\xff", "This is an image, and images are not read. Attach a text or PDF version."),
    (b"GIF8", "This is an image, and images are not read. Attach a text or PDF version."),
    (b"RIFF", "This is an image or media file, and it is not read. Attach a text or PDF version."),
    (b"II*\x00", "This is an image, and images are not read. Attach a text or PDF version."),
    (b"MM\x00*", "This is an image, and images are not read. Attach a text or PDF version."),
)


def _mostly_text(text):
    sample = text[:65536]
    controls = sum(ord(char) < 32 and char not in "\t\n\r\f" for char in sample)
    return bool(sample) and controls * 20 < len(sample)


def decode(data):
    """Return text for any byte string that reads as text, or None for binary content."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        attempts = ("utf-16",)
    elif data[:65536].count(b"\x00") * 4 > len(data[:65536]):
        attempts = ("utf-16-le", "utf-16-be")
    elif b"\x00" in data[:65536]:
        return None
    else:
        attempts = ("utf-8-sig", "gb18030", "latin-1")
    for encoding in attempts:
        try:
            text = data.decode(encoding)
        except UnicodeError:
            continue
        if _mostly_text(text):
            return text
    return None


class VisibleText(HTMLParser):
    HIDDEN = {"script", "style", "noscript", "template"}
    BLOCKS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.HIDDEN:
            self.hidden += 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in self.HIDDEN:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip() + " ")

    def text(self):
        return re.sub(r"\n\s*\n+", "\n\n", "".join(self.parts)).strip()


def html_text(text):
    parser = VisibleText()
    parser.feed(text)
    return parser.text()


def rtf_text(text):
    text = re.sub(r"\{\\(?:fonttbl|colortbl|stylesheet|info|\*)[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", "", text)
    text = re.sub(r"\\'([0-9a-fA-F]{2})", lambda match: bytes.fromhex(match[1]).decode("cp1252", "replace"), text)
    text = re.sub(r"\\u(-?\d+)\??", lambda match: chr(int(match[1]) % 65536), text)
    text = re.sub(r"\\(?:par|pard|line|row)\b ?", "\n", text)
    text = re.sub(r"\\cell\b ?", " | ", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", text)
    return re.sub(r"[{}\\]", "", text).strip()


def notebook_text(text):
    notebook = json.loads(text)
    parts = []
    for cell in notebook.get("cells", []):
        source = cell.get("source", "")
        parts.append(f"[{cell.get('cell_type', 'cell')}]\n" + ("".join(source) if isinstance(source, list) else str(source)))
    return "\n\n".join(parts)


def pdf_text(data):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("This PDF is encrypted. Attach a version without a password.")
    parts, length = [], 0
    for number, page in enumerate(list(reader.pages)[:MAX_PDF_PAGES], 1):
        text = page.extract_text() or ""
        parts.append(f"[page {number}]\n{text}")
        length += len(text)
        if length >= MAX_CHARS:
            break
    if not any(part.split("\n", 1)[1].strip() for part in parts):
        raise ValueError("This PDF has no text layer, for example scanned pages. Attach a version with text.")
    return "\n\n".join(parts)


def _member(archive, info):
    if info.file_size > MAX_MEMBER:
        raise ValueError("A file inside this archive is too large to read.")
    with archive.open(info) as stream:
        data = stream.read(MAX_MEMBER + 1)
    if len(data) > MAX_MEMBER:
        raise ValueError("A file inside this archive is too large to read.")
    return data


def _xml(archive, name):
    return ElementTree.fromstring(_member(archive, archive.getinfo(name)))


def _numbered(names, pattern):
    found = [(int(match[1]), name) for name in names if (match := re.fullmatch(pattern, name))]
    return [name for _, name in sorted(found)]


def _word_text(element):
    return "".join(node.text or "" for node in element.iter() if node.tag in {WORD + "t", MATH + "t"}).strip()


def _word_blocks(element):
    for child in element:
        if child.tag == WORD + "p":
            yield _word_text(child)
        elif child.tag == WORD + "tbl":
            for row in child.iter(WORD + "tr"):
                yield " | ".join(_word_text(cell) for cell in row.findall(WORD + "tc"))
        elif child.tag != WORD + "sectPr":
            yield from _word_blocks(child)


def docx_text(archive):
    lines = list(_word_blocks(_xml(archive, "word/document.xml").find(WORD + "body")))
    if "word/footnotes.xml" in archive.namelist():
        lines.extend(_word_text(note) for note in _xml(archive, "word/footnotes.xml"))
    return "\n".join(line for line in lines if line)


def pptx_text(archive):
    parts = []
    for number, name in enumerate(_numbered(archive.namelist(), r"ppt/slides/slide(\d+)\.xml"), 1):
        paragraphs = ("".join(node.text or "" for node in paragraph.iter(DRAWING + "t"))
                      for paragraph in _xml(archive, name).iter(DRAWING + "p"))
        parts.append(f"[slide {number}]\n" + "\n".join(line for line in paragraphs if line.strip()))
    return "\n\n".join(parts)


def xlsx_text(archive):
    shared = []
    if "xl/sharedStrings.xml" in archive.namelist():
        shared = ["".join(node.text or "" for node in item.iter(SHEET + "t"))
                  for item in _xml(archive, "xl/sharedStrings.xml").findall(SHEET + "si")]
    parts = []
    for number, name in enumerate(_numbered(archive.namelist(), r"xl/worksheets/sheet(\d+)\.xml"), 1):
        rows = []
        for row in _xml(archive, name).iter(SHEET + "row"):
            cells = []
            for cell in row.findall(SHEET + "c"):
                value = cell.find(SHEET + "v")
                if cell.get("t") == "s" and value is not None and value.text and value.text.isdigit() and int(value.text) < len(shared):
                    cells.append(shared[int(value.text)])
                elif cell.get("t") == "inlineStr":
                    cells.append("".join(node.text or "" for node in cell.iter(SHEET + "t")))
                else:
                    cells.append(value.text if value is not None and value.text else "")
            rows.append(" | ".join(cells))
        parts.append(f"[sheet {number}]\n" + "\n".join(rows))
    return "\n\n".join(parts)


def odf_text(archive):
    root = _xml(archive, "content.xml")
    rows = list(root.iter(ODF_TABLE + "table-row"))
    in_table = {id(node) for row in rows for node in row.iter()}
    lines = []
    for element in root.iter():
        if element.tag == ODF_TABLE + "table-row":
            lines.append(" | ".join("".join(cell.itertext()).strip() for cell in element.findall(ODF_TABLE + "table-cell")))
        elif element.tag in {ODF_TEXT + "p", ODF_TEXT + "h"} and id(element) not in in_table:
            lines.append("".join(element.itertext()))
    return "\n".join(line for line in lines if line.strip())


def archive_text(archive, depth):
    """Read the text files inside an ordinary archive, without opening nested archives."""
    files = [info for info in archive.infolist() if not info.is_dir()]
    parts = ["Files in this archive:\n" + "\n".join(info.filename for info in files[:200])]
    read = 0
    for info in files:
        if read >= MAX_MEMBERS_READ:
            parts.append("Further files in this archive were not read.")
            break
        if info.flag_bits & 1 or info.file_size > MAX_MEMBER:
            continue
        try:
            kind, text = extract_text(_member(archive, info), info.filename, "", depth + 1)
        except ValueError:
            continue
        read += 1
        parts.append(f"--- {info.filename} ({kind}) ---\n{text}")
    return "\n\n".join(parts)


def zip_text(data, depth):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("This archive is damaged.") from None
    with archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_UNCOMPRESSED:
            raise ValueError("This archive expands beyond the size limit.")
        names = set(archive.namelist())
        if "word/document.xml" in names:
            return "docx", docx_text(archive)
        if any(name.startswith("ppt/slides/") for name in names):
            return "pptx", pptx_text(archive)
        if any(name.startswith("xl/worksheets/") for name in names):
            return "xlsx", xlsx_text(archive)
        if "content.xml" in names and "mimetype" in names:
            return "opendocument", odf_text(archive)
        if depth > 0:
            raise ValueError("Nested archives are not read.")
        return "archive", archive_text(archive, depth)


def extract_text(data, name="", content_type="", depth=0):
    """Return (kind, text), or raise ValueError with a message for the researcher."""
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if data.startswith(b"%PDF"):
        return "pdf", pdf_text(data)
    if data.startswith(b"PK\x03\x04"):
        return zip_text(data, depth)
    if data.startswith(b"\x1f\x8b"):
        if depth > 0:
            raise ValueError("Nested archives are not read.")
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            inner = stream.read(MAX_MEMBER + 1)
        if len(inner) > MAX_MEMBER:
            raise ValueError("This compressed file expands beyond the size limit.")
        return extract_text(inner, name[:-3] if name.lower().endswith(".gz") else "", "", depth + 1)
    for magic, message in UNREADABLE:
        if data.startswith(magic):
            raise ValueError(message)
    text = decode(data)
    if text is None:
        raise ValueError("This file has no readable text. Attach a text, PDF, or Office version.")
    start = text.lstrip()[:200].lower()
    if text.lstrip().startswith("{\\rtf"):
        return "rtf", rtf_text(text)
    if suffix == "ipynb":
        try:
            return "notebook", notebook_text(text)
        except (ValueError, AttributeError):
            return "text", text
    if suffix in {"html", "htm", "xhtml"} or "html" in content_type.lower() or start.startswith(("<!doctype html", "<html")):
        return "html", html_text(text)
    return "text", text


def main():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    content_type = sys.argv[2] if len(sys.argv) > 2 else ""
    data = sys.stdin.buffer.read(MAX_INPUT + 1)
    try:
        if len(data) > MAX_INPUT:
            raise ValueError("This file is too large to read.")
        kind, text = extract_text(data, name, content_type)
        result = {"kind": kind, "text": text[:MAX_CHARS], "truncated": len(text) > MAX_CHARS}
    except ValueError as exc:
        result = {"error": str(exc)}
    except (ElementTree.ParseError, KeyError, EOFError, OSError, RuntimeError, IndexError):
        result = {"error": "This file is damaged or uses an unsupported layout. Attach a text or PDF version."}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
