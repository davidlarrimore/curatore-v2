import time, uuid, asyncio
from pathlib import Path
from typing import Dict, Any, List
from ..storage import Storage
from ..config import settings
from ..models.schemas import Job, FileResult

class InMemoryJobStore:
    def __init__(self):
        self._jobs: Dict[str, Job] = {}

    def save(self, job: Job) -> None:
        self._jobs[job.id] = job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> List[Job]:
        return list(self._jobs.values())

class JobService:
    def __init__(self, processing):
        self.store = InMemoryJobStore()
        self.processing = processing

    def _now(self) -> float:
        return time.time()

    def _new_job(self) -> Job:
        ts = self._now()
        return Job(id=str(uuid.uuid4()), status="pending", created_ts=ts, updated_ts=ts, results=[], logs=[])

    async def create_and_run(self, filenames: List[str], *, auto_optimize: bool, thresholds: Dict[str, Any], ocr_lang: str, ocr_psm: int) -> Job:
        job = self._new_job()
        self.store.save(job)
        asyncio.create_task(self._run_job(job.id, filenames, auto_optimize, thresholds, ocr_lang, ocr_psm))
        return job

    async def _run_job(self, job_id: str, filenames: List[str], auto_optimize: bool, thresholds: Dict[str, Any], ocr_lang: str, ocr_psm: int):
        job = self.store.get(job_id)
        if not job: return
        job.status = "running"
        job.updated_ts = self._now()
        self.store.save(job)

        try:
            results = []
            for name in filenames:
                path = Path(settings.DATA_ROOT) / settings.UPLOADED_DIR / name
                job.logs.append(f"Processing {name} ...")
                job.updated_ts = self._now()
                self.store.save(job)

                r = await self.processing.process_file(path, ocr_lang=ocr_lang, ocr_psm=ocr_psm, auto_optimize=auto_optimize, thresholds=thresholds)
                results.append(FileResult(**r))

            job.results = results
            job.status = "completed"
        except Exception as e:
            job.logs.append(f"ERROR: {e}")
            job.status = "failed"
        finally:
            job.updated_ts = self._now()
            self.store.save(job)

    def get(self, job_id: str) -> Job | None:
        return self.store.get(job_id)

    def list(self) -> List[Job]:
        return self.store.list()