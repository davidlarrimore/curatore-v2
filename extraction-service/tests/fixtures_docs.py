import os
import io
import json
import zipfile
from pathlib import Path
from typing import Dict, List, Tuple


MARKERS = {
    "txt": "TXT_MARKER_Delta 101112",
    "md": "MD_MARKER_Epsilon 131415 and [link](https://example.com)",
    "docx": "DOCX_MARKER_Alpha 123",
    "xlsx": "XLSX_MARKER_Beta 456",
    "pdf": "PDF_MARKER_Gamma 789",
}


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def build_docx_bytes(text: str) -> bytes:
    # Minimal OOXML docx (document.xml + rels)
    content_types = (
        b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        b"<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"
        b"<Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>"
        b"<Default Extension='xml' ContentType='application/xml'/>"
        b"<Override PartName='/word/document.xml' ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'/>"
        b"</Types>"
    )
    rels = (
        b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        b"<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
        b"<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='word/document.xml'/>"
        b"</Relationships>"
    )
    doc_xml = (
        """
        <?xml version='1.0' encoding='UTF-8' standalone='yes'?>
        <w:document xmlns:wpc='http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas'
         xmlns:mc='http://schemas.openxmlformats.org/markup-compatibility/2006'
         xmlns:o='urn:schemas-microsoft-com:office:office'
         xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
         xmlns:m='http://schemas.openxmlformats.org/officeDocument/2006/math'
         xmlns:v='urn:schemas-microsoft-com:vml'
         xmlns:wp14='http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing'
         xmlns:wp='http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
         xmlns:w10='urn:schemas-microsoft-com:office:word'
         xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
         xmlns:w14='http://schemas.microsoft.com/office/word/2010/wordml'
         xmlns:wpg='http://schemas.microsoft.com/office/word/2010/wordprocessingGroup'
         xmlns:wpi='http://schemas.microsoft.com/office/word/2010/wordprocessingInk'
         xmlns:wne='http://schemas.microsoft.com/office/word/2006/wordml'
         xmlns:wps='http://schemas.microsoft.com/office/word/2010/wordprocessingShape'
         mc:Ignorable='w14 wp14'>
          <w:body>
            <w:p><w:r><w:t>__TEXT__</w:t></w:r></w:p>
            <w:sectPr/>
          </w:body>
        </w:document>
        """.strip()
        .replace("__TEXT__", text)
        .encode("utf-8")
    )
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc_xml)
    return bio.getvalue()


def build_xlsx_bytes(text: str) -> bytes:
    # Minimal OOXML xlsx with inlineStr in A1
    content_types = (
        b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        b"<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"
        b"<Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>"
        b"<Default Extension='xml' ContentType='application/xml'/>"
        b"<Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/>"
        b"<Override PartName='/xl/worksheets/sheet1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>"
        b"</Types>"
    )
    rels = (
        b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        b"<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
        b"<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='xl/workbook.xml'/>"
        b"</Relationships>"
    )
    wb_rels = (
        b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        b"<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
        b"<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet1.xml'/>"
        b"</Relationships>"
    )
    workbook = (
        b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        b"<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'>"
        b"<sheets><sheet name='Sheet1' sheetId='1' r:id='rId1' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'/></sheets>"
        b"</workbook>"
    )
    sheet1 = (
        """
        <?xml version='1.0' encoding='UTF-8' standalone='yes'?>
        <worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'>
          <sheetData>
            <row r='1'>
              <c r='A1' t='inlineStr'><is><t>__TEXT__</t></is></c>
            </row>
          </sheetData>
        </worksheet>
        """.strip().replace("__TEXT__", text).encode("utf-8")
    )
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/worksheets/sheet1.xml", sheet1)
    return bio.getvalue()


def build_pdf_bytes(text: str) -> bytes:
    # Tiny PDF generator: 1 page, Helvetica text
    # Returns a valid PDF with correct xref offsets.
    objs: List[bytes] = []
    def obj(n: int, body: str) -> bytes:
        return f"{n} 0 obj\n{body}\nendobj\n".encode("latin1")

    objs.append(obj(1, "<< /Type /Catalog /Pages 2 0 R >>"))
    objs.append(obj(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>"))
    page = "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
    objs.append(obj(3, page))
    stream = f"BT /F1 18 Tf 50 120 Td ({text}) Tj ET".encode("latin1", errors="ignore")
    content = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream\n"
    objs.append(b"4 0 obj\n" + content + b"endobj\n")
    objs.append(obj(5, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))

    # Assemble with xref table
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: List[int] = [0]  # xref requires index 0
    for b in objs:
        offsets.append(out.tell())
        out.write(b)
    xref_start = out.tell()
    count = len(objs) + 1
    out.write(f"xref\n0 {count}\n".encode("latin1"))
    out.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.write(f"{off:010} 00000 n \n".encode("latin1"))
    trailer = f"trailer << /Size {count} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n"
    out.write(trailer.encode("latin1"))
    return out.getvalue()


def make_corrupt_bytes(data: bytes, keep_ratio: float = 0.6) -> bytes:
    if keep_ratio <= 0.0:
        keep_ratio = 0.5
    k = max(16, int(len(data) * keep_ratio))
    return data[:k]  # truncate tail to corrupt


def create_all_docs(base_dir: Path) -> Dict[str, Path]:
    base_dir.mkdir(parents=True, exist_ok=True)

    paths: Dict[str, Path] = {}

    # Plain text and markdown
    _write(base_dir / "sample.txt", (MARKERS["txt"] + "\nMore plain text.").encode("utf-8"))
    _write(base_dir / "sample.md", (f"# Heading\n\n{MARKERS['md']}\n").encode("utf-8"))
    paths["sample.txt"] = base_dir / "sample.txt"
    paths["sample.md"] = base_dir / "sample.md"

    # DOCX
    docx_bytes = build_docx_bytes(MARKERS["docx"])
    _write(base_dir / "sample.docx", docx_bytes)
    _write(base_dir / "sample_corrupt.docx", make_corrupt_bytes(docx_bytes))
    paths["sample.docx"] = base_dir / "sample.docx"
    paths["sample_corrupt.docx"] = base_dir / "sample_corrupt.docx"

    # XLSX
    xlsx_bytes = build_xlsx_bytes(MARKERS["xlsx"])
    _write(base_dir / "sample.xlsx", xlsx_bytes)
    _write(base_dir / "sample_corrupt.xlsx", make_corrupt_bytes(xlsx_bytes))
    paths["sample.xlsx"] = base_dir / "sample.xlsx"
    paths["sample_corrupt.xlsx"] = base_dir / "sample_corrupt.xlsx"

    # PDF
    pdf_bytes = build_pdf_bytes(MARKERS["pdf"])
    _write(base_dir / "sample.pdf", pdf_bytes)
    _write(base_dir / "sample_corrupt.pdf", make_corrupt_bytes(pdf_bytes))
    paths["sample.pdf"] = base_dir / "sample.pdf"
    paths["sample_corrupt.pdf"] = base_dir / "sample_corrupt.pdf"

    return paths


def write_manifest(manifest_path: Path, doc_dir: Path) -> None:
    # Keep manifest in repo root of service for discoverability
    docs = [
        {
            "filename": "sample.txt",
            "should_parse": True,
            "expected_markers": [MARKERS["txt"]],
            "expect_method_any_of": ["text"],
        },
        {
            "filename": "sample.md",
            "should_parse": True,
            "expected_markers": ["Heading", MARKERS["md"].split(" and ")[0]],
            "expect_method_any_of": ["text"],
        },
        {
            "filename": "sample.docx",
            "should_parse": True,
            "expected_markers": [MARKERS["docx"]],
            "expect_method_any_of": ["markitdown"],
        },
        {
            "filename": "sample.xlsx",
            "should_parse": True,
            "expected_markers": [MARKERS["xlsx"]],
            "expect_method_any_of": ["markitdown", "pdfminer", "ocr"],
        },
        {
            "filename": "sample.pdf",
            "should_parse": True,
            "expected_markers": [MARKERS["pdf"]],
            "expect_method_any_of": ["pdfminer", "ocr", "pdfminer+ocr"],
        },
        {
            "filename": "sample_corrupt.docx",
            "should_parse": False,
            "expected_markers": [],
            "expect_method_any_of": ["markitdown", "error"],
        },
        {
            "filename": "sample_corrupt.xlsx",
            "should_parse": False,
            "expected_markers": [],
            "expect_method_any_of": ["markitdown", "error"],
        },
        {
            "filename": "sample_corrupt.pdf",
            "should_parse": False,
            "expected_markers": [],
            "expect_method_any_of": ["pdfminer", "ocr", "pdfminer+ocr", "error"],
        },
    ]
    manifest = {"documents": docs, "doc_dir": str(doc_dir)}
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

