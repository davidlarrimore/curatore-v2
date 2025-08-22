import time, json
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from ..config import Settings
from ..llm_client import LLMClient
from ..storage import Storage
from ..pipeline_adapter import (
    SUPPORTED_EXTS, convert_to_markdown, score_conversion, llm_eval_prompt
)

class ProcessingService:
    def __init__(self, cfg: Settings, llm: LLMClient, storage: Storage):
        self.cfg = cfg
        self.llm = llm
        self.storage = storage

    def _meets_thresholds(self, conv_score: int, ev: Optional[Dict[str, Any]], th: Dict[str, Any]) -> bool:
        if conv_score < th["conversion_min"]: return False
        if not ev: return False
        return (
            ev.get("clarity_score", 0)   >= th["clarity_min"] and
            ev.get("completeness_score", 0) >= th["completeness_min"] and
            ev.get("relevance_score", 0) >= th["relevance_min"] and
            ev.get("markdown_score", 0)  >= th["markdown_min"]
        )

    async def process_file(self, path: Path, *, ocr_lang: str, ocr_psm: int, auto_optimize: bool, thresholds: Dict[str, Any]) -> Dict[str, Any]:
        md, used_ocr, note = convert_to_markdown(path, ocr_lang=ocr_lang, ocr_psm=ocr_psm)
        original_text = md  # we don't have separate "original" easily; parity with previous approach
        if md is None or not md.strip():
            return {
                "filename": path.name,
                "used_ocr": used_ocr,
                "conversion_score": 0,
                "conversion_feedback": "No markdown produced.",
                "note": note,
                "pass_all": False
            }
        # Optional vector optimization via LLM
        if auto_optimize:
            system = ("Reformat this document to be optimized for vector database storage and retrieval. "
                      "Use clear section headings, logical chunking, and context-rich phrasing. "
                      "Return ONLY the revised Markdown.")
            user = f"Document:\n```markdown\n{md}\n```"
            try:
                md = await self.llm.chat(
                    [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    temperature=0.2
                )
            except Exception:
                pass

        conv_score, conv_fb = score_conversion(md, original_text=original_text)

        # LLM JSON evaluation
        try:
            content = await self.llm.chat(
                [{"role": "system", "content": "Return JSON only."},
                 {"role": "user", "content": llm_eval_prompt(md)}],
                temperature=0.0
            )
            ev = json.loads(content)
        except Exception:
            ev = None

        # Save result markdown
        out_md = self.storage.processed / f"{path.stem}.md"
        out_md.write_text(md, encoding="utf-8")

        return {
            "filename": path.name,
            "markdown_path": str(out_md),
            "conversion_score": conv_score,
            "conversion_feedback": conv_fb,
            "eval": ev,
            "pass_all": self._meets_thresholds(conv_score, ev, thresholds),
            "used_ocr": used_ocr,
            "note": note
        }