from fastapi import APIRouter, UploadFile, File, Depends
from typing import Dict, Any
from ..deps import get_storage
from ..pipeline_adapter import SUPPORTED_EXTS

# Create a new APIRouter instance for organizing file-related endpoints.
router = APIRouter()

@router.get("/files")
def list_files(storage = Depends(get_storage)):
    """
    Lists the names of all files currently in the uploaded files directory.
    
    Args:
        storage: An instance of the storage service, injected by FastAPI.
        
    Returns:
        A dictionary containing a list of filenames.
    """
    files = [p.name for p in storage.uploaded_files()]
    return {"files": files}

@router.post("/files:upload")
async def upload_file(f: UploadFile = File(...), storage = Depends(get_storage)) -> Dict[str, Any]:
    """
    Handles file uploads. It validates the file extension, saves the file
    using the storage service, and returns a confirmation.
    """
    if f.filename == "":
        return {"error": "No filename."}
    if f.filename and f.filename.lower().endswith(tuple(SUPPORTED_EXTS)):
        storage.save_upload(f.filename, await f.read())
        return {"ok": True, "filename": f.filename}
    return {"error": "Unsupported extension."}

@router.delete("/files")
def delete_all(storage = Depends(get_storage)):
    """Deletes all files from the uploaded files directory."""
    n = storage.delete(storage.uploaded_files())
    return {"deleted": n}