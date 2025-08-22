from fastapi import APIRouter, UploadFile, File, Depends
from typing import Dict, Any
from ..deps import get_storage
from ..pipeline_adapter import SUPPORTED_EXTS

router = APIRouter()

@router.get("/files")
def list_files(storage = Depends(get_storage)):
    files = [p.name for p in storage.uploaded_files()]
    return {"files": files}

@router.post("/files:upload")
async def upload_file(f: UploadFile = File(...), storage = Depends(get_storage)) -> Dict[str, Any]:
    if f.filename == "":
        return {"error": "No filename."}
    if f.filename and f.filename.lower().endswith(tuple(SUPPORTED_EXTS)):
        storage.save_upload(f.filename, await f.read())
        return {"ok": True, "filename": f.filename}
    return {"error": "Unsupported extension."}

@router.delete("/files")
def delete_all(storage = Depends(get_storage)):
    n = storage.delete(storage.uploaded_files())
    return {"deleted": n}