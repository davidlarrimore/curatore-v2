# ============================================================================
# Curatore v2 - Document Service
# ============================================================================
#
# Responsibilities:
#   - Enforce canonical file layout via app.config.settings
#   - Handle uploads, listings, lookups
#   - Manage file metadata and storage
#   - Provide file information for frontend
#
# NOTE: Heavy document processing (OCR, conversion) has been moved to the
# extraction-service microservice. This service now focuses on file management.
#
# Canonical directories (inside the container):
#   /app/files/uploaded_files
#   /app/files/processed_files
#   /app/files/batch_files
#
# IMPORTANT:
# - Do not hardcode relative paths like "uploads" or "processed".
# - Use settings.*_path for all filesystem activity.
# - We create uploaded_files and processed_files if missing.
#   batch_files is operator-managed and may be just a bind mount.
# ============================================================================

import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..config import settings
from ..models import FileInfo

SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".txt", ".md", ".rtf",
    ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff",
    ".xlsx", ".xls", ".csv",
    ".odt", ".odp", ".ods"
}


class DocumentService:
    """
    Core document storage and file management service.
    
    Handles file upload, storage, retrieval, and metadata management.
    Document processing is delegated to the extraction-service microservice.
    
    Public API:
        - save_uploaded_file(filename, content) -> (document_id, path)
        - list_uploaded_files() -> [str]
        - list_batch_files() -> [str]
        - list_uploaded_files_with_metadata() -> [FileInfo]
        - list_batch_files_with_metadata() -> [FileInfo]
        - find_uploaded_file(document_id) -> Path | None
        - find_batch_file(filename) -> Path | None
        - delete_uploaded_file(document_id) -> bool
        - clear_all_files() -> None
    """

    def __init__(self) -> None:
        # Ensure canonical directories exist (except batch_files)
        settings.upload_path.mkdir(parents=True, exist_ok=True)
        settings.processed_path.mkdir(parents=True, exist_ok=True)
        # We do NOT create batch_path; it's managed externally (bind-mounted)

        print("[DocumentService] Using directories:")
        print(f"  uploads   -> {settings.upload_path}")
        print(f"  processed -> {settings.processed_path}")
        print(f"  batch     -> {settings.batch_path} (operator-managed)")

    # ------------------- File Type Support -------------------

    def get_supported_extensions(self) -> List[str]:
        """Get list of supported file extensions."""
        return sorted(SUPPORTED_EXTENSIONS)

    def is_supported_file(self, filename: str) -> bool:
        """Check if a file is supported based on its extension."""
        if not filename:
            return False
        ext = Path(filename).suffix.lower()
        return ext in SUPPORTED_EXTENSIONS

    # ------------------- File Listing with Metadata -------------------

    def list_uploaded_files_with_metadata(self) -> List[FileInfo]:
        """
        List all uploaded files with complete metadata.
        
        Returns a list of FileInfo objects containing document IDs, filenames,
        file sizes, timestamps, and paths for all uploaded files.
        
        Returns:
            List[FileInfo]: List of file metadata objects
        """
        file_infos = []
        
        if not settings.upload_path.exists():
            return file_infos
            
        for file_path in settings.upload_path.glob("*"):
            if not file_path.is_file():
                continue
                
            # Skip non-supported files
            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
                
            try:
                # Extract document_id from filename (format: {document_id}_{original_filename})
                filename_parts = file_path.stem.split('_', 1)
                if len(filename_parts) >= 2:
                    document_id = filename_parts[0]
                    original_filename = filename_parts[1] + file_path.suffix
                else:
                    # Legacy or malformed filename, use full filename as both ID and name
                    document_id = file_path.stem
                    original_filename = file_path.name
                
                # Get file metadata
                stat = file_path.stat()
                file_size = stat.st_size
                upload_time = int(stat.st_mtime)  # Unix timestamp
                
                # Create relative path
                relative_path = str(file_path.relative_to(settings.upload_path.parent))
                
                file_info = FileInfo(
                    document_id=document_id,
                    filename=original_filename,
                    original_filename=original_filename,
                    file_size=file_size,
                    upload_time=upload_time,
                    file_path=relative_path
                )
                
                file_infos.append(file_info)
                
            except Exception as e:
                # Log error but continue processing other files
                print(f"[DocumentService] Error processing uploaded file {file_path}: {e}")
                continue
                
        # Sort by upload time (newest first)
        file_infos.sort(key=lambda x: x.upload_time, reverse=True)
        return file_infos

    def list_batch_files_with_metadata(self) -> List[FileInfo]:
        """
        List all batch files with complete metadata.
        
        Returns a list of FileInfo objects containing filenames as document IDs,
        file sizes, timestamps, and paths for all batch files.
        
        Returns:
            List[FileInfo]: List of file metadata objects
        """
        file_infos = []
        
        if not settings.batch_path.exists():
            return file_infos
            
        for file_path in settings.batch_path.glob("*"):
            if not file_path.is_file():
                continue
                
            # Skip non-supported files
            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
                
            try:
                # For batch files, use filename as document_id since they don't have UUIDs
                filename = file_path.name
                
                # Get file metadata
                stat = file_path.stat()
                file_size = stat.st_size
                upload_time = int(stat.st_mtime)  # Unix timestamp
                
                # Create relative path
                relative_path = str(file_path.relative_to(settings.batch_path.parent))
                
                file_info = FileInfo(
                    document_id=filename,  # Use filename as ID for batch files
                    filename=filename,
                    original_filename=filename,
                    file_size=file_size,
                    upload_time=upload_time,
                    file_path=relative_path
                )
                
                file_infos.append(file_info)
                
            except Exception as e:
                # Log error but continue processing other files
                print(f"[DocumentService] Error processing batch file {file_path}: {e}")
                continue
                
        # Sort by filename alphabetically
        file_infos.sort(key=lambda x: x.filename.lower())
        return file_infos

    # ------------------- Legacy Methods (Backward Compatibility) -------------------

    def list_uploaded_files(self) -> List[str]:
        """Legacy method: List uploaded filenames only (backward compatibility)."""
        file_infos = self.list_uploaded_files_with_metadata()
        return [info.filename for info in file_infos]

    def list_batch_files(self) -> List[str]:
        """Legacy method: List batch filenames only (backward compatibility)."""
        file_infos = self.list_batch_files_with_metadata()
        return [info.filename for info in file_infos]

    # ------------------- Upload & Lookup -------------------

    async def save_uploaded_file(self, filename: str, content: bytes) -> Tuple[str, Path]:
        """
        Persist an upload into /app/files/uploaded_files with a UUID prefix.
        Returns (document_id, absolute_path).
        """
        document_id = str(uuid.uuid4())

        # sanitize filename (naive but effective)
        safe = filename.replace("../", "").replace("..\\", "")
        safe = safe.replace("/", "_").replace("\\", "_")

        out_path = settings.upload_path / f"{document_id}_{safe}"
        out_path.write_bytes(content)
        return document_id, out_path

    def find_uploaded_file(self, document_id: str) -> Optional[Path]:
        """Find the uploaded file by its UUID prefix."""
        for p in settings.upload_path.glob(f"{document_id}_*"):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
                return p
        # Legacy fallback: {name}_{uuid}.{ext}
        for p in settings.upload_path.glob("*"):
            if p.is_file() and p.stem.endswith(f"_{document_id}"):
                return p
        return None

    def find_batch_file(self, filename: str) -> Optional[Path]:
        """Locate a file inside /app/files/batch_files by exact filename."""
        if not settings.batch_path.exists():
            return None
        
        file_path = settings.batch_path / filename
        if file_path.is_file() and self.is_supported_file(filename):
            return file_path
        return None

    def delete_uploaded_file(self, document_id: str) -> bool:
        """
        Delete an uploaded file by its document ID.
        Returns True if file was found and deleted, False otherwise.
        """
        file_path = self.find_uploaded_file(document_id)
        if file_path and file_path.exists():
            try:
                file_path.unlink()
                return True
            except Exception as e:
                print(f"[DocumentService] Error deleting file {file_path}: {e}")
                return False
        return False

    # ------------------- File Management -------------------

    def clear_all_files(self) -> Dict[str, int]:
        """
        Clear all uploaded and processed files (development utility).
        Returns count of files cleared by category.
        """
        counts = {"uploaded": 0, "processed": 0}
        
        # Clear uploaded files
        if settings.upload_path.exists():
            for file_path in settings.upload_path.glob("*"):
                if file_path.is_file():
                    try:
                        file_path.unlink()
                        counts["uploaded"] += 1
                    except Exception as e:
                        print(f"[DocumentService] Error clearing uploaded file {file_path}: {e}")
        
        # Clear processed files
        if settings.processed_path.exists():
            for file_path in settings.processed_path.rglob("*"):
                if file_path.is_file():
                    try:
                        file_path.unlink()
                        counts["processed"] += 1
                    except Exception as e:
                        print(f"[DocumentService] Error clearing processed file {file_path}: {e}")
            
            # Remove empty directories
            for dir_path in settings.processed_path.glob("*"):
                if dir_path.is_dir():
                    try:
                        dir_path.rmdir()
                    except OSError:
                        pass  # Directory not empty, skip
        
        print(f"[DocumentService] Cleared {counts['uploaded']} uploaded files, {counts['processed']} processed files")
        return counts

    def get_file_count_summary(self) -> Dict[str, int]:
        """
        Get summary of file counts across all directories.
        Returns count by file category.
        """
        counts = {"uploaded": 0, "processed": 0, "batch": 0}
        
        # Count uploaded files
        if settings.upload_path.exists():
            counts["uploaded"] = len([f for f in settings.upload_path.glob("*") if f.is_file()])
        
        # Count processed files
        if settings.processed_path.exists():
            counts["processed"] = len([f for f in settings.processed_path.rglob("*") if f.is_file()])
        
        # Count batch files
        if settings.batch_path.exists():
            counts["batch"] = len([f for f in settings.batch_path.glob("*") if f.is_file()])
        
        return counts


# Global instance
document_service = DocumentService()