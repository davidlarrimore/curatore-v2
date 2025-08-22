# pipeline.py
import os, io, re, json, time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

# Prefer MarkItDown when available (preserves structure)
try:
    from markitdown import MarkItDown
    MD_CONVERTER = MarkItDown(enable_plugins=False)
except Exception:
    MD_CONVERTER = None

from pdfminer.high_level import extract_text as pdf_extract_text  # docs show extract_text() usage
from PIL import Image
import pytesseract
from pytesseract import Output
import fitz  # PyMuPDF
import docx

# OpenAI SDK (v1.x) with configurable endpoint support
from openai import OpenAI
import urllib3

# Environment configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_VERIFY_SSL = os.getenv("OPENAI_VERIFY_SSL", "true").lower() in ("true", "1", "yes")
OPENAI_TIMEOUT = float(os.getenv("OPENAI_TIMEOUT", "60"))
OPENAI_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "3"))

# Initialize OpenAI client with custom configuration
_client = None
if OPENAI_API_KEY:
    try:
        # Disable SSL warnings if SSL verification is disabled
        if not OPENAI_VERIFY_SSL:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # Create HTTP client configuration
        import httpx
        http_client = httpx.Client(
            verify=OPENAI_VERIFY_SSL,
            timeout=OPENAI_TIMEOUT
        )
        
        _client = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL,
            http_client=http_client,
            max_retries=OPENAI_MAX_RETRIES
        )
        
        # Test connection and log configuration
        print(f"OpenAI client configured:")
        print(f"  Base URL: {OPENAI_BASE_URL}")
        print(f"  Model: {OPENAI_MODEL}")
        print(f"  SSL Verification: {OPENAI_VERIFY_SSL}")
        print(f"  Timeout: {OPENAI_TIMEOUT}s")
        
    except Exception as e:
        print(f"Warning: Failed to initialize OpenAI client: {e}")
        _client = None

SUPPORTED_EXTS = {".docx", ".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".md", ".txt"}

def pdf_pages_to_images(pdf_path: Path, dpi: int = 220) -> List[Image.Image]:
    imgs = []
    with fitz.open(str(pdf_path)) as doc:
        mat = fitz.Matrix(dpi/72, dpi/72)
        for page in doc:
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            imgs.append(img)
    return imgs

def ocr_image_with_tesseract(img: Image.Image, lang: str = "eng", psm: int = 3) -> Tuple[str, float]:
    """
    Returns (text, avg_confidence [0..1]).
    Uses image_to_string for text + image_to_data to compute confidence.
    """
    config = f"--psm {psm}"
    text = pytesseract.image_to_string(img, lang=lang, config=config)
    data = pytesseract.image_to_data(img, lang=lang, config=config, output_type=Output.DICT)
    confs = []
    for c in data.get("conf", []):
        try:
            val = float(c)
            if val >= 0:
                confs.append(val)
        except Exception:
            pass
    avg_conf = (sum(confs) / len(confs) / 100.0) if confs else 0.0
    return text.strip(), avg_conf

def convert_to_markdown(file_path: Path, ocr_lang="eng", ocr_psm=3) -> Tuple[Optional[str], bool, str]:
    """
    Convert a document to Markdown/text.
    Priority: MarkItDown -> format fallbacks -> OCR (Tesseract) when needed.
    Returns (markdown_text, success, note)
    """
    ext = file_path.suffix.lower()
    note = ""

    # 1) MD/TXT direct
    if ext in {".md", ".txt"}:
        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = file_path.read_text(encoding="latin-1")
        return (text if ext == ".md" else f"```\n{text}\n```"), True, "Loaded text/markdown directly."

    # 2) Try MarkItDown first (preserve structure for LLM)
    try:
        if MD_CONVERTER:
            res = MD_CONVERTER.convert(str(file_path))
            md = (res.text_content or "").strip()
            if md:
                return md, True, "Converted with MarkItDown."
            note = "MarkItDown returned empty content; attempting fallbacks."
    except Exception as e:
        note = f"MarkItDown failed: {e}; attempting fallbacks."

    # 3) DOCX fallback
    if ext == ".docx":
        try:
            d = docx.Document(str(file_path))
            parts = [p.text for p in d.paragraphs]
            md = "\n".join(parts).strip()
            return md, True, "Converted DOCX via python-docx fallback."
        except Exception as e:
            return None, False, f"DOCX fallback failed: {e}"

    # 4) PDF: text layer first, else rasterize+OCR
    if ext == ".pdf":
        try:
            text = pdf_extract_text(str(file_path)) or ""
            if text.strip():
                return text, True, "Extracted PDF text via pdfminer.six."
            imgs = pdf_pages_to_images(file_path, dpi=220)
            if not imgs:
                return None, False, f"No pages to OCR. {note}"
            all_text, confs = [], []
            for img in imgs:
                t, c = ocr_image_with_tesseract(img, lang=ocr_lang, psm=ocr_psm)
                if t:
                    all_text.append(t)
                    confs.append(c)
            md = "\n\n".join(all_text).strip()
            avg_conf = (sum(confs)/len(confs)) if confs else 0.0
            ok = bool(md)
            return md, ok, f"PDF OCR via Tesseract; avg_conf={avg_conf:.2f}"
        except Exception as e:
            return None, False, f"PDF OCR error: {e}"

    # 5) Images: OCR with Tesseract
    if ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
        try:
            img = Image.open(str(file_path)).convert("RGB")
            text, conf = ocr_image_with_tesseract(img, lang=ocr_lang, psm=ocr_psm)
            return text, bool(text), f"Image OCR via Tesseract; avg_conf={conf:.2f}"
        except Exception as e:
            return None, False, f"Image OCR error: {e}"

    return None, False, f"Unsupported or failed conversion. {note}"

def score_conversion(original_text: Optional[str], markdown_text: str) -> Tuple[int, str]:
    """
    Heuristic conversion score (0-100) combining:
      - content coverage (ratio if original_text provided)
      - markdown structure markers
      - legibility (no odd chars, reasonable line length)
    """
    if not markdown_text:
        return 0, "No markdown produced."

    # Content coverage
    content_score = 100
    if original_text:
        ow = original_text.split()
        mw = markdown_text.split()
        if len(ow) == 0:
            content_score = 0
        else:
            ratio = min(len(mw) / len(ow), 1.0)
            content_score = int(ratio * 100)

    # Structure markers
    headings = len(re.findall(r'^#{1,6}\s', markdown_text, flags=re.MULTILINE))
    lists = len(re.findall(r'^[\-\*]\s', markdown_text, flags=re.MULTILINE))
    tables = markdown_text.count('|')
    structure_score = 0
    if headings > 0: structure_score += 30
    if lists > 0:    structure_score += 30
    if tables > 3:   structure_score += 20

    # Legibility
    if "�" in markdown_text:
        legibility_score = 0
    else:
        lines = markdown_text.splitlines() or [markdown_text]
        avg_len = sum(len(l) for l in lines) / len(lines)
        legibility_score = 20 if avg_len < 200 else 10

    total = int(0.5 * content_score + structure_score + legibility_score)
    total = min(total, 100)

    fb = []
    if content_score < 100 and original_text:
        fb.append(f"Content preserved ~{content_score}%.")
    if structure_score < 60:
        fb.append("Formatting may be partially lost.")
    if legibility_score < 20:
        fb.append("Some readability issues (long lines or odd characters).")
    if not fb:
        fb.append("High-fidelity conversion.")
    return total, " ".join(fb)

def llm_json_eval(markdown_text: str) -> Dict[str, Any]:
    """
    Ask the LLM to score clarity, completeness, relevance, markdown compatibility,
    overall feedback, and pass/fail recommendation.
    """
    if not _client:
        print("Warning: LLM evaluation skipped - no OpenAI client available")
        return {}
    
    try:
        system = (
            "You are an expert documentation reviewer. "
            "Evaluate the document for Clarity, Completeness, Relevance, and Markdown Compatibility. "
            "Score each 1–10 and provide a one-sentence rationale. "
            "Give overall improvement suggestions. "
            "Finally, return pass_recommendation as 'Pass' if ALL categories are sufficient, else 'Fail'."
        )
        fmt = (
            "Respond ONLY as compact JSON with keys: "
            "clarity_score, clarity_feedback, "
            "completeness_score, completeness_feedback, "
            "relevance_score, relevance_feedback, "
            "markdown_score, markdown_feedback, "
            "overall_feedback, pass_recommendation."
        )
        content = f"Document (Markdown):\n```markdown\n{markdown_text}\n```"
        
        resp = _client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": content},
                {"role": "assistant", "content": fmt},
            ],
        )
        text = resp.choices[0].message.content
        try:
            return json.loads(text)
        except Exception:
            m = re.search(r'\{[\s\S]*\}', text)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    pass
            return {}
    except Exception as e:
        print(f"Warning: LLM evaluation failed: {e}")
        return {}

def llm_improve(markdown_text: str, prompt: str) -> str:
    """Ask the LLM to rewrite the markdown based on user's prompt."""
    if not _client:
        print("Warning: LLM improvement skipped - no OpenAI client available")
        return markdown_text
    
    try:
        system = (
            "You are a technical editor. Improve the given Markdown in-place per the user's instructions. "
            "Preserve facts and structure when possible. Return ONLY the revised Markdown content."
        )
        user = f"Instructions:\n{prompt}\n\nCurrent Markdown:\n```markdown\n{markdown_text}\n```"
        
        resp = _client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.2,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"Warning: LLM improvement failed: {e}")
        return markdown_text

def generate_report(doc_name: str, conversion_score: int, conversion_feedback: str, eval_data: Dict[str, Any]) -> str:
    lines = [f"# Feedback Report for **{doc_name}**", ""]
    lines += [f"**Conversion Quality:** {conversion_score}/100 – {conversion_feedback}", ""]
    if eval_data:
        lines.append("**Content Quality Evaluation:**")
        lines.append(f"- **Clarity:** {eval_data.get('clarity_score','N/A')}/10 – {eval_data.get('clarity_feedback','')}")
        lines.append(f"- **Completeness:** {eval_data.get('completeness_score','N/A')}/10 – {eval_data.get('completeness_feedback','')}")
        lines.append(f"- **Relevance:** {eval_data.get('relevance_score','N/A')}/10 – {eval_data.get('relevance_feedback','')}")
        lines.append(f"- **Markdown Compatibility:** {eval_data.get('markdown_score','N/A')}/10 – {eval_data.get('markdown_feedback','')}")
        lines.append("")
        if eval_data.get("overall_feedback"):
            lines.append(f"**Improvement Suggestions:** {eval_data['overall_feedback']}")
        rec = str(eval_data.get("pass_recommendation","")).lower()
        status = "PASS ✅" if rec.startswith("p") else "FAIL ❌" if rec else "N/A"
        lines.append(f"**RAG Readiness:** {status}")
    else:
        lines.append("*LLM evaluation not available.*")
    lines.append("")
    return "\n".join(lines)

def meets_thresholds(conversion_score: int, eval_data: Dict[str, Any], thresholds: Dict[str,int]) -> bool:
    if not eval_data:
        return False
    try:
        return (
            conversion_score >= thresholds["conversion"] and
            int(eval_data.get("clarity_score", 0))       >= thresholds["clarity"] and
            int(eval_data.get("completeness_score", 0))  >= thresholds["completeness"] and
            int(eval_data.get("relevance_score", 0))     >= thresholds["relevance"] and
            int(eval_data.get("markdown_score", 0))      >= thresholds["markdown"]
        )
    except Exception:
        return False

def test_llm_connection() -> Dict[str, Any]:
    """Test the LLM connection and return status information."""
    if not _client:
        return {
            "connected": False,
            "error": "No API key provided or client initialization failed",
            "endpoint": OPENAI_BASE_URL,
            "model": OPENAI_MODEL
        }
    
    try:
        # Simple test query
        resp = _client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": "Hello, respond with just 'OK'"}],
            max_tokens=10,
            temperature=0
        )
        
        return {
            "connected": True,
            "endpoint": OPENAI_BASE_URL,
            "model": OPENAI_MODEL,
            "response": resp.choices[0].message.content.strip(),
            "ssl_verify": OPENAI_VERIFY_SSL,
            "timeout": OPENAI_TIMEOUT
        }
    except Exception as e:
        return {
            "connected": False,
            "error": str(e),
            "endpoint": OPENAI_BASE_URL,
            "model": OPENAI_MODEL,
            "ssl_verify": OPENAI_VERIFY_SSL,
            "timeout": OPENAI_TIMEOUT
        }

def process_file(fp: Path, ocr_lang="eng", ocr_psm=3, thresholds=None, processed_dir=Path("processed_documents")) -> Dict[str, Any]:
    thresholds = thresholds or {"conversion":70,"clarity":7,"completeness":7,"relevance":7,"markdown":7}
    processed_dir.mkdir(parents=True, exist_ok=True)

    md_text, ok, conv_note = convert_to_markdown(fp, ocr_lang=ocr_lang, ocr_psm=ocr_psm)
    if not ok or not md_text:
        return {"file": str(fp), "ok": False, "message": f"Conversion failed. {conv_note}"}

    out_md = processed_dir / f"{fp.stem}.md"
    out_md.write_text(md_text, encoding="utf-8")

    conv_score, conv_fb = score_conversion(None, md_text)
    eval_data = llm_json_eval(md_text)

    return {
        "file": str(fp),
        "ok": True,
        "markdown_path": str(out_md),
        "conversion_score": conv_score,
        "conversion_feedback": conv_fb,
        "eval": eval_data,
        "pass_all": meets_thresholds(conv_score, eval_data, thresholds),
        "conv_note": conv_note,
        "ts": time.time(),
    }

def process_folder(folder: Path, ocr_lang="eng", ocr_psm=3, thresholds=None, processed_dir=Path("processed_documents")) -> List[Dict[str, Any]]:
    results = []
    for fp in folder.glob("*"):
        if fp.suffix.lower() in SUPPORTED_EXTS and fp.is_file():
            results.append(process_file(fp, ocr_lang=ocr_lang, ocr_psm=ocr_psm, thresholds=thresholds, processed_dir=processed_dir))
    return results