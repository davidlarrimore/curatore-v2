## `backend/src/curatore_api/models/schemas.py`

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class Thresholds(BaseModel):
    conversion_min: int = 60
    clarity_min: int = 6
    completeness_min: int = 6
    relevance_min: int = 6
    markdown_min: int = 6

class LLMSettings(BaseModel):
    base_url: Optional[str] = None
    model: Optional[str] = None

class JobCreate(BaseModel):
    filenames: List[str]
    auto_optimize: bool = True
    thresholds: Thresholds = Thresholds()
    ocr_lang: Optional[str] = None
    ocr_psm: Optional[int] = None
    llm: Optional[LLMSettings] = None

class EvalResult(BaseModel):
    clarity_score: int
    completeness_score: int
    relevance_score: int
    markdown_score: int
    overall_feedback: Optional[str] = None
    pass_recommendation: bool

class FileResult(BaseModel):
    filename: str
    conversion_score: int
    conversion_feedback: str
    eval: Optional[EvalResult] = None
    used_ocr: bool = False
    note: Optional[str] = None
    markdown_path: Optional[str] = None
    pass_all: bool = False

class Job(BaseModel):
    id: str
    status: str
    created_ts: float
    updated_ts: float
    results: List[FileResult] = []
    logs: List[str] = []