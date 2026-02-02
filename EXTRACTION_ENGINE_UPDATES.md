Curatore v2 Extraction Engine Updates

Technical Requirements: High-Throughput, Quality-Aware Document Extraction to Markdown

⸻

1. Purpose and Scope

This document describes a proposed evolution of the Curatore v2 extraction subsystem to support high-throughput, multi-terabyte document processing while preserving high-quality Markdown output where it provides measurable value.

The proposal is explicitly incremental:
	•	Preserve the current Docker + FastAPI + Celery architecture
	•	Reuse existing queue throttling and recovery mechanisms
	•	Introduce a pre-extraction triage phase
	•	Narrow the scope of OCR and Docling usage
	•	Remove redundant or implicit technologies (e.g., Tesseract)

The intended audience is engineers responsible for extraction, performance, and reliability, not product or sales stakeholders.

⸻

2. Problem Statement (Engineering Perspective)

2.1 Current Extraction Behavior

In Curatore v2 today:
	1.	All supported files are routed to the extraction-service
	2.	MarkItDown attempts extraction
	3.	OCR may be invoked implicitly (via Tesseract) if extraction fails
	4.	Docling may optionally re-process the document as an enhancement

This produces correct results, but with suboptimal resource usage.

⸻

2.2 Identified Engineering Issues

Issue 1: OCR is implicit and opportunistic
	•	OCR is triggered deep inside MarkItDown
	•	The system does not know beforehand whether OCR is required
	•	OCR is CPU-heavy and IO-expensive

Issue 2: Docling is invoked too late
	•	Docling is treated as an enhancement rather than a primary engine
	•	Low-complexity documents still incur MarkItDown overhead
	•	High-complexity documents pay extraction cost twice

Issue 3: No fast-path extraction
	•	Simple PDFs and Office documents do not bypass heavyweight tooling
	•	Throughput is artificially constrained by worst-case paths

⸻

3. Design Principles
	1.	Decide early, extract once
	2.	OCR is explicit, never implicit
	3.	High-quality extraction is opt-in via triage
	4.	Markdown is the canonical internal representation
	5.	Engines are replaceable via abstraction
	6.	Queues represent cost domains, not features

⸻

4. Proposed Architecture Changes (Delta from v2)

4.1 New Phase: Pre-Extraction Triage

A new, lightweight triage step is introduced before any extraction engine is invoked.

Characteristics
	•	Runs synchronously inside extraction_orchestrator
	•	Sub-second execution
	•	No OCR
	•	No Docling
	•	No full document parsing

Output
A structured ExtractionPlan persisted alongside the Run.

⸻

4.2 ExtractionPlan Schema (Proposed)

class ExtractionPlan(BaseModel):
    file_type: str
    engine: Literal[
        "fast_pdf",
        "fast_office",
        "docling",
        "ocr_only"
    ]
    needs_ocr: bool
    needs_layout: bool
    complexity: Literal["low", "medium", "high"]


⸻

5. Triage Implementation Details

5.1 Frameworks Used for Triage

Purpose	Framework
MIME detection	python-magic
PDF probing	PyMuPDF
Image counting	PyMuPDF
Office probing	python-docx / python-pptx
File metadata	stdlib

No OCR engines are used in triage.

⸻

5.2 OCR Necessity Detection (PDF)

OCR is required only if a document lacks a usable text layer.

Heuristic (PDF):
	•	Sample first N pages (default: 3)
	•	Extract text via PyMuPDF
	•	Count extracted characters
	•	Count embedded images

def pdf_needs_ocr(pdf_path: str) -> bool:
    doc = fitz.open(pdf_path)
    pages = min(3, doc.page_count)

    total_text_chars = 0
    total_images = 0

    for i in range(pages):
        page = doc.load_page(i)
        total_text_chars += len(page.get_text("text").strip())
        total_images += len(page.get_images())

    if total_text_chars < 200 and total_images > 0:
        return True

    return False

This avoids OCR for:
	•	Digitally generated PDFs
	•	Office exports
	•	Text-heavy regulatory documents

⸻

5.3 Layout Complexity Detection (PDF)

Layout analysis is expensive and only valuable when structure matters.

def pdf_needs_layout(pdf_path: str) -> bool:
    doc = fitz.open(pdf_path)
    page = doc.load_page(0)

    blocks = page.get_text("blocks")
    images = page.get_images()

    if len(blocks) > 50 or len(images) > 3:
        return True

    return False


⸻

6. Proposed Triage Routing Logic (Pseudo-Code)

def triage(file_path: str, mime_type: str) -> ExtractionPlan:
    if mime_type == "application/pdf":
        if pdf_needs_ocr(file_path):
            return ExtractionPlan(
                file_type="pdf",
                engine="docling",
                needs_ocr=True,
                needs_layout=True,
                complexity="high"
            )

        if pdf_needs_layout(file_path):
            return ExtractionPlan(
                file_type="pdf",
                engine="docling",
                needs_ocr=False,
                needs_layout=True,
                complexity="medium"
            )

        return ExtractionPlan(
            file_type="pdf",
            engine="fast_pdf",
            needs_ocr=False,
            needs_layout=False,
            complexity="low"
        )

    if mime_type in DOCX_TYPES:
        if office_is_complex(file_path):
            return ExtractionPlan(
                file_type="docx",
                engine="docling",
                needs_ocr=False,
                needs_layout=True,
                complexity="medium"
            )

        return ExtractionPlan(
            file_type="docx",
            engine="fast_office",
            needs_ocr=False,
            needs_layout=False,
            complexity="low"
        )

    if mime_type.startswith("image/"):
        return ExtractionPlan(
            file_type="image",
            engine="ocr_only",
            needs_ocr=True,
            needs_layout=False,
            complexity="medium"
        )

    raise UnsupportedFileType()


⸻

7. Extraction Engines by Route

7.1 Fast PDF Extraction

Aspect	Choice
Framework	PyMuPDF
OCR	None
Layout	Minimal
Output	Text-first Markdown

Used for the majority of PDFs.

⸻

7.2 Fast Office Extraction

File Type	Framework
DOCX	python-docx
PPTX	python-pptx
XLSX / CSV	pandas / openpyxl

Tables are rendered directly into Markdown.

⸻

7.3 High-Quality Layout Extraction

Aspect	Choice
Framework	Docling
OCR	Docling-native
Layout	Full
Output	Markdown

Docling is treated as a primary engine, not a post-process.

⸻

7.4 OCR-Only Extraction

OCR is isolated and explicit.

Technologies
	•	Docling OCR pipelines

Technologies Removed
	•	❌ Tesseract
	•	❌ pytesseract
	•	❌ pypdfium2 OCR fallback

Rationale:
	•	OCR is expensive
	•	Must be observable and tunable
	•	Docling already provides OCR where necessary

⸻

8. Queue and Worker Changes

8.1 Current Queues (Preserved)
	•	extraction
	•	enhancement

8.2 Proposed Queues

Queue	Purpose
triage	Fast routing decisions
fast_extract	Native parsing
layout_extract	Docling
ocr	OCR-only
postprocess	Markdown normalization

If operational simplicity is preferred, fast_extract and postprocess can be merged initially.

⸻

8.3 Worker Characteristics

Worker	Resource Profile
Triage	CPU, high concurrency
Fast extract	CPU, high concurrency
Docling	CPU/GPU, low concurrency
OCR	CPU/GPU, isolated
Postprocess	CPU, high concurrency

This prevents Docling and OCR from starving cheap jobs.

⸻

9. Technologies to Remove or De-emphasize

Technology	Action	Reason
Tesseract	Remove	Implicit OCR, CPU-heavy
pytesseract	Remove	Same
pypdfium2 OCR	Remove	OCR belongs in OCR lane
Enhancement-only Docling	Reframe	Docling should be primary when chosen


⸻

10. Post-Processing & Normalization

All extraction paths converge into a deterministic post-process:
	•	Normalize headings
	•	Normalize tables
	•	Inject metadata frontmatter
	•	Enforce consistent chunking boundaries

This step decouples:
	•	Extraction engine choice
	•	Indexing behavior
	•	Embedding strategy

⸻

11. Expected Engineering Outcomes

Metric	Impact
Extraction throughput	2–5× increase
OCR workload	Reduced by majority
Docling utilization	Focused on high-value docs
Failure modes	More predictable
Engine extensibility	Significantly improved


⸻

12. Summary

Curatore v2’s architecture is fundamentally sound. The primary inefficiency lies not in tooling, but in when and how extraction decisions are made.

By introducing a triage phase, isolating OCR, narrowing Docling usage, and adding a fast extraction lane, Curatore evolves into a system that is:
	•	Faster
	•	Cheaper
	•	Easier to reason about
	•	Easier to extend

This proposal requires no platform rewrite, only targeted, engineer-friendly changes aligned with the existing codebase.
