from .config import settings
from .storage import Storage
from .services.jobs import JobService
from .llm_client import LLMClient
from .services.processing import ProcessingService

_storage = Storage(settings)
_llm = LLMClient(settings)
_processing = ProcessingService(settings, _llm, _storage)
_jobs = JobService(_processing)

def get_storage() -> Storage:
    return _storage

def get_processing() -> ProcessingService:
    return _processing

def get_jobs() -> JobService:
    return _jobs

def get_llm() -> LLMClient:
    return _llm