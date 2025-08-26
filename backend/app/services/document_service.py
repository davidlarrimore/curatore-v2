# backend/app/services/document_service.py
import io
import re
import time
import uuid
import shutil
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

# Import from v1 pipeline logic
try:
    from markitdown import MarkItDown
    MD_CONVERTER = MarkItDown(enable_plugins=False)
except Exception:
    MD_CONVERTER = None

from pdfminer.high_level import extract_text as pdf_extract_text
from PIL import Image
import pytesseract
from pytesseract import Output
import fitz  # PyMuPDF
import docx

from ..config import settings
from ..models import (
    ProcessingResult, ConversionResult, ProcessingStatus, LLMEvaluation,
    OCRSettings, QualityThresholds, ProcessingOptions
)
from .llm_service import llm_service
from ..utils.text_utils import clean_llm_response


class DocumentService:
    """Service for document processing operations."""
    
    SUPPORTED_EXTENSIONS = {".docx", ".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".md", ".txt"}
    
    def __init__(self):
        # Use absolute paths from settings - these should match Docker volume mount
        self.upload_dir = Path(settings.upload_dir)
        self.processed_dir = Path(settings.processed_dir)
        self.batch_dir = Path(settings.batch_dir)
        
        print(f"🔧 DocumentService initialized with:")
        print(f"   Upload dir: {self.upload_dir}")
        print(f"   Processed dir: {self.processed_dir}")
        print(f"   Batch dir: {self.batch_dir}")
        
        # Only ensure directories exist, don't create them if they don't
        self._ensure_directories()
    
    def _ensure_directories(self) -> None:
        """Ensure required directories exist - but only if the parent volume is mounted."""
        try:
            # Check if the main files directory exists (should be mounted from Docker)
            files_root = Path(settings.files_root)
            
            if not files_root.exists():
                print(f"⚠️  Main files directory doesn't exist: {files_root}")
                print("   This suggests the Docker volume mount may not be working correctly.")
                # Don't create it - this should be mounted from the host
                return
            
            # Only create subdirectories if the main directory exists
            dirs_to_ensure = [
                (self.upload_dir, "uploaded_files"),
                (self.processed_dir, "processed_files"), 
                (self.batch_dir, "batch_files")
            ]
            
            for dir_path, name in dirs_to_ensure:
                if not dir_path.exists():
                    dir_path.mkdir(parents=True, exist_ok=True)
                    print(f"📁 Created {name} directory: {dir_path}")
                else:
                    print(f"✅ {name} directory exists: {dir_path}")
                    
        except Exception as e:
            print(f"❌ Error ensuring directories: {e}")
            # Don't raise the exception - let the app continue
    
    def clear_all_files(self) -> Dict[str, int]:
        """Clear all uploaded and processed files. Returns count of deleted files."""
        deleted_counts = {
            "uploaded": 0,
            "processed": 0,
            "total": 0
        }
        
        try:
            # Clear uploaded files
            if self.upload_dir.exists():
                for file_path in self.upload_dir.glob("*"):
                    if file_path.is_file():
                        file_path.unlink()
                        deleted_counts["uploaded"] += 1
            
            # Clear processed files
            if self.processed_dir.exists():
                for file_path in self.processed_dir.glob("*"):
                    if file_path.is_file():
                        file_path.unlink()
                        deleted_counts["processed"] += 1
            
            deleted_counts["total"] = deleted_counts["uploaded"] + deleted_counts["processed"]
            print(f"✅ File cleanup complete: {deleted_counts['total']} files deleted")
            
        except Exception as e:
            print(f"⚠️ Error during file cleanup: {e}")
            raise
        
        return deleted_counts
    
    def list_batch_files(self) -> List[Dict[str, Any]]:
        """List all files in the batch_files directory."""
        files = []
        try:
            print(f"🔍 Listing batch files from: {self.batch_dir}")
            
            if not self.batch_dir.exists():
                print(f"⚠️ Batch directory does not exist: {self.batch_dir}")
                return files
            
            file_count = 0
            for file_path in self.batch_dir.glob("*"):
                file_count += 1
                if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                    try:
                        stat = file_path.stat()
                        
                        # Generate a temporary document_id for frontend compatibility
                        document_id = f"batch_{file_path.stem}"
                        
                        file_info = {
                            "document_id": document_id,
                            "filename": file_path.name,
                            "original_filename": file_path.name,
                            "file_size": stat.st_size,
                            "upload_time": stat.st_mtime * 1000,  # Convert to milliseconds
                            "file_path": str(file_path),
                            "source": "batch"  # Mark as batch file
                        }
                        files.append(file_info)
                    except Exception as e:
                        print(f"⚠️ Error processing file {file_path}: {e}")
                        continue
                else:
                    if file_path.is_file():
                        print(f"❌ Unsupported file type: {file_path.name}")
            
            print(f"✅ Found {len(files)} valid batch files out of {file_count} total files")
            
        except Exception as e:
            print(f"❌ Error listing batch files: {e}")
            import traceback
            traceback.print_exc()
        
        return files

    def find_batch_file(self, filename: str) -> Optional[Path]:
        """Find a specific file in the batch_files directory."""
        try:
            batch_file_path = self.batch_dir / filename
            if batch_file_path.exists() and batch_file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                return batch_file_path
            else:
                return None
        except Exception as e:
            print(f"❌ Error finding batch file {filename}: {e}")
            return None

    def copy_batch_to_upload(self, filename: str) -> Tuple[str, Path]:
        """Copy a batch file to the upload directory for processing."""
        try:
            batch_file_path = self.find_batch_file(filename)
            if not batch_file_path:
                raise FileNotFoundError(f"Batch file not found: {filename}")
            document_id = str(uuid.uuid4())
            target_path = self.upload_dir / f"{document_id}_{filename}"
            shutil.copy2(batch_file_path, target_path)
            print(f"📁 Copied batch file: {batch_file_path} -> {target_path}")
            
            return document_id, target_path
        except Exception as e:
            print(f"❌ Error copying batch file {filename}: {e}")
            raise
    
    def _pdf_pages_to_images(self, pdf_path: Path, dpi: int = 220) -> List[Image.Image]:
        """Convert PDF pages to images for OCR."""
        imgs = []
        with fitz.open(str(pdf_path)) as doc:
            mat = fitz.Matrix(dpi/72, dpi/72)
            for page in doc:
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
                imgs.append(img)
        return imgs
    
    def _ocr_image_with_tesseract(self, img: Image.Image, lang: str = "eng", psm: int = 3) -> Tuple[str, float]:
        """OCR image using Tesseract and return text with confidence."""
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
    
    def _score_conversion(self, markdown_text: str, original_text: Optional[str] = None) -> Tuple[int, str]:
        """
        Calculates a heuristic conversion score (0-100) based on content coverage,
        markdown structure markers (headings, lists), and basic legibility checks.
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

        # Legibility score
        if "" in markdown_text: # Check for replacement characters
            legibility_score = 0
        else:
            lines = markdown_text.splitlines() or [markdown_text]
            avg_len = sum(len(l) for l in lines) / len(lines) if lines else 0
            legibility_score = 20 if avg_len < 200 else 10

        # Combine scores with weighting
        total = int(0.5 * content_score + structure_score + legibility_score)
        total = min(total, 100)

        # Generate human-readable feedback
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

    def _convert_file_to_text(
        self,
        file_path: Path,
        ocr_settings: OCRSettings
    ) -> Tuple[Optional[str], str]:
        """
        Converts a document to text format using a prioritized chain of methods.
        Returns a tuple of (text_content, note_string).
        """
        ext = file_path.suffix.lower()
        note = ""
        md = None

        # 1) MD/TXT direct read
        if ext in {".md", ".txt"}:
            try:
                text = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = file_path.read_text(encoding="latin-1")
            md = text if ext == ".md" else f"```\n{text}\n```"
            note = "Loaded text/markdown directly."
            return md, note

        # 2) Try MarkItDown first (preserves structure for LLM)
        try:
            if MD_CONVERTER:
                res = MD_CONVERTER.convert(str(file_path))
                md = (res.text_content or "").strip()
                if md:
                    note = "Converted with MarkItDown."
                    return md, note
                note = "MarkItDown returned empty content; attempting fallbacks."
        except Exception as e:
            note = f"MarkItDown failed: {e}; attempting fallbacks."

        # 3) DOCX fallback using python-docx
        if ext == ".docx":
            try:
                d = docx.Document(str(file_path))
                parts = [p.text for p in d.paragraphs]
                md = "\n".join(parts).strip()
                note = "Converted DOCX via python-docx fallback."
                return md, note
            except Exception as e:
                note = f"DOCX fallback failed: {e}"
                return None, note

        # 4) PDF: try text layer first, otherwise rasterize and OCR
        if ext == ".pdf":
            try:
                text = pdf_extract_text(str(file_path)) or ""
                if text.strip():
                    note = "Extracted PDF text via pdfminer.six."
                    return text, note
                
                # If no text, fall back to OCR
                imgs = self._pdf_pages_to_images(file_path, dpi=220)
                if not imgs:
                    note = f"No pages to OCR. {note}"
                    return None, note
                
                all_text, confs = [], []
                for img in imgs:
                    t, c = self._ocr_image_with_tesseract(img, lang=ocr_settings.language, psm=ocr_settings.psm)
                    if t:
                        all_text.append(t)
                        confs.append(c)
                md = "\n\n".join(all_text).strip()
                avg_conf = (sum(confs)/len(confs)) if confs else 0.0
                note = f"PDF OCR via Tesseract; avg_conf={avg_conf:.2f}"
                return md, note
            except Exception as e:
                note = f"PDF OCR error: {e}"
                return None, note

        # 5) Images: OCR with Tesseract
        if ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
            try:
                img = Image.open(str(file_path)).convert("RGB")
                text, conf = self._ocr_image_with_tesseract(img, lang=ocr_settings.language, psm=ocr_settings.psm)
                note = f"Image OCR via Tesseract; avg_conf={conf:.2f}"
                return text, note
            except Exception as e:
                note = f"Image OCR error: {e}"
                return None, note

        return None, f"Unsupported or failed conversion. {note}"

    async def convert_to_markdown(
        self, 
        file_path: Path, 
        ocr_settings: OCRSettings
    ) -> ConversionResult:
        """Convert document to markdown format and score it."""
        try:
            markdown_content, note = self._convert_file_to_text(file_path, ocr_settings)
            
            if markdown_content is None:
                return ConversionResult(
                    success=False,
                    conversion_score=0,
                    conversion_feedback="Conversion failed to produce text.",
                    conversion_note=note
                )

            score, feedback = self._score_conversion(markdown_content)
            
            return ConversionResult(
                success=bool(markdown_content),
                markdown_content=markdown_content,
                conversion_score=score,
                conversion_feedback=feedback,
                conversion_note=note
            )
            
        except Exception as e:
            return ConversionResult(
                success=False,
                conversion_score=0,
                conversion_feedback=f"Conversion error: {e}",
                conversion_note=f"An unexpected error occurred during conversion: {e}"
            )
    
    def _meets_thresholds(
        self, 
        conversion_score: int, 
        llm_evaluation: Optional[LLMEvaluation], 
        thresholds: QualityThresholds
    ) -> bool:
        """Check if document meets quality thresholds."""
        if not llm_evaluation:
            return False
        
        try:
            return (
                conversion_score >= thresholds.conversion and
                (llm_evaluation.clarity_score or 0) >= thresholds.clarity and
                (llm_evaluation.completeness_score or 0) >= thresholds.completeness and
                (llm_evaluation.relevance_score or 0) >= thresholds.relevance and
                (llm_evaluation.markdown_score or 0) >= thresholds.markdown
            )
        except Exception:
            return False
    
    async def process_document(
        self, 
        document_id: str, 
        file_path: Path, 
        options: ProcessingOptions
    ) -> ProcessingResult:
        """Process a single document through the complete pipeline."""
        start_time = time.time()
        filename = file_path.name.split('_', 1)[-1] if '_' in file_path.name else file_path.name
        
        try:
            print(f"🔄 Processing document: {filename} (ID: {document_id})")
            
            # Step 1: Convert to markdown
            conversion_result = await self.convert_to_markdown(file_path, options.ocr_settings)
            
            if not conversion_result.success or not conversion_result.markdown_content:
                return ProcessingResult(
                    document_id=document_id,
                    filename=filename,
                    status=ProcessingStatus.FAILED,
                    success=False,
                    message=f"Conversion failed: {conversion_result.conversion_feedback}",
                    original_path=str(file_path),
                    conversion_result=conversion_result,
                    processing_time=time.time() - start_time,
                    thresholds_used=options.quality_thresholds
                )
            
            markdown_content = conversion_result.markdown_content
            print(f"✅ Conversion successful: {len(markdown_content)} characters")
            
            # Step 2: Generate document summary
            document_summary = None
            if llm_service.is_available:
                try:
                    summary = await llm_service.summarize_document(markdown_content, filename)
                    document_summary = clean_llm_response(summary)
                    print(f"📝 Summary generated: {document_summary[:100]}...")
                except Exception as e:
                    print(f"⚠️ Summary generation failed: {e}")
                    document_summary = f"Summary generation failed: {str(e)[:100]}..."
            
            # Step 3: Vector DB optimization (if enabled)
            vector_optimized = False
            optimization_note = ""
            if options.auto_optimize and llm_service.is_available:
                try:
                    optimized_content = await llm_service.optimize_for_vector_db(markdown_content)
                    if optimized_content and optimized_content.strip():
                        markdown_content = clean_llm_response(optimized_content)
                        markdown_content = optimized_content
                        vector_optimized = True
                        optimization_note = "Vector DB optimized. "
                        print("🎯 Vector optimization applied")
                    else:
                        optimization_note = "Vector optimization returned empty content. "
                        print("⚠️ Vector optimization returned empty content")
                except Exception as e:
                    optimization_note = f"Optimization failed ({str(e)[:50]}...). "
                    print(f"❌ Vector optimization failed: {e}")
            
            # Step 4: Save processed markdown
            output_path = self.processed_dir / f"{file_path.stem}_{document_id}.md"
            try:
                output_path.write_text(markdown_content, encoding="utf-8")
                print(f"💾 Saved processed content: {output_path}")
            except Exception as e:
                return ProcessingResult(
                    document_id=document_id,
                    filename=filename,
                    status=ProcessingStatus.FAILED,
                    success=False,
                    message=f"Failed to save processed content: {str(e)}",
                    original_path=str(file_path),
                    conversion_result=conversion_result,
                    processing_time=time.time() - start_time,
                    thresholds_used=options.quality_thresholds
                )
            
            # Update conversion result with any optimization notes
            conversion_result.conversion_note = f"{optimization_note}{conversion_result.conversion_note}"
            if vector_optimized:
                # Re-score after optimization
                conversion_result.conversion_score, conversion_result.conversion_feedback = self._score_conversion(markdown_content)
            
            # Step 5: LLM evaluation
            llm_evaluation = None
            if llm_service.is_available:
                try:
                    llm_evaluation = await llm_service.evaluate_document(markdown_content)
                    print("📊 LLM evaluation completed")
                except Exception as e:
                    print(f"⚠️ LLM evaluation failed for {filename}: {e}")
            
            # Step 6: Check quality thresholds
            passes_thresholds = self._meets_thresholds(
                conversion_result.conversion_score,
                llm_evaluation,
                options.quality_thresholds
            )
            status = "✅ PASS" if passes_thresholds else "❌ FAIL"
            print(f"🎯 Quality check: {status}")
            
            processing_time = time.time() - start_time
            print(f"⏱️ Processing completed in {processing_time:.2f}s")
            
            return ProcessingResult(
                document_id=document_id,
                filename=filename,
                status=ProcessingStatus.COMPLETED,
                success=True,
                original_path=str(file_path),
                markdown_path=str(output_path),
                conversion_result=conversion_result,
                llm_evaluation=llm_evaluation,
                document_summary=document_summary,
                conversion_score=conversion_result.conversion_score,
                pass_all_thresholds=passes_thresholds,
                vector_optimized=vector_optimized,
                processing_time=processing_time,
                processed_at=time.time(),
                thresholds_used=options.quality_thresholds
            )
            
        except Exception as e:
            print(f"❌ Processing error for {filename}: {e}")
            import traceback
            traceback.print_exc()
            
            return ProcessingResult(
                document_id=document_id,
                filename=filename,
                status=ProcessingStatus.FAILED,
                success=False,
                message=f"Processing error: {str(e)}",
                original_path=str(file_path),
                processing_time=time.time() - start_time,
                thresholds_used=options.quality_thresholds
            )
    
    async def process_batch(
        self, 
        document_ids: List[str], 
        options: ProcessingOptions
    ) -> List[ProcessingResult]:
        """Process multiple documents."""
        results = []
        
        for doc_id in document_ids:
            # Find the file for this document ID
            file_path = self._find_document_file(doc_id)
            if not file_path:
                results.append(ProcessingResult(
                    document_id=doc_id,
                    filename=f"unknown_{doc_id}",
                    status=ProcessingStatus.FAILED,
                    success=False,
                    message="Document file not found",
                    thresholds_used=options.quality_thresholds
                ))
                continue
            
            result = await self.process_document(doc_id, file_path, options)
            results.append(result)
        
        return results
    
    def _find_document_file(self, document_id: str) -> Optional[Path]:
        """Find the uploaded file for a document ID."""
        # Look for files that start with the document_id in upload directory
        for file_path in self.upload_dir.glob(f"{document_id}_*.*"):
            if file_path.is_file():
                return file_path
        
        # Look in batch files for batch_ prefixed IDs
        if document_id.startswith("batch_"):
            filename_stem = document_id.replace("batch_", "")
            for file_path in self.batch_dir.glob(f"{filename_stem}.*"):
                if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                    return file_path
        
        return None
    
    def get_supported_extensions(self) -> List[str]:
        """Get list of supported file extensions."""
        return list(self.SUPPORTED_EXTENSIONS)
    
    def is_supported_file(self, filename: str) -> bool:
        """Check if file is supported for processing."""
        return Path(filename).suffix.lower() in self.SUPPORTED_EXTENSIONS
    
    async def save_uploaded_file(self, filename: str, content: bytes) -> Tuple[str, Path]:
        """Save uploaded file and return document ID and file path."""
        document_id = str(uuid.uuid4())
        safe_filename = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
        file_path = self.upload_dir / f"{document_id}_{safe_filename}"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(file_path, "wb") as f:
                f.write(content)
            print(f"File saved successfully: {file_path}")
        except Exception as e:
            print(f"Error saving file {file_path}: {e}")
            raise
        
        return document_id, file_path
    
    def list_uploaded_files(self) -> List[Dict[str, Any]]:
        """List all uploaded files with metadata."""
        files = []
        try:
            for file_path in self.upload_dir.glob("*"):
                if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                    stat = file_path.stat()
                    parts = file_path.name.split('_', 1)
                    document_id = parts[0]
                    original_filename = parts[1] if len(parts) > 1 else file_path.name
                    
                    files.append({
                        "document_id": document_id,
                        "filename": original_filename,
                        "original_filename": file_path.name,
                        "file_size": stat.st_size,
                        "upload_time": stat.st_mtime * 1000,  # Convert to milliseconds
                        "file_path": str(file_path)
                    })
        except Exception as e:
            print(f"Error listing files: {e}")
        
        return files
    
    def get_processed_content(self, document_id: str) -> Optional[str]:
        """Get processed markdown content for a document."""
        for file_path in self.processed_dir.glob(f"*_{document_id}.md"):
            try:
                return file_path.read_text(encoding="utf-8")
            except Exception:
                continue
        return None
    
    async def update_document_content(
        self, 
        document_id: str, 
        content: str, 
        options: ProcessingOptions,
        improvement_prompt: Optional[str] = None,
        apply_vector_optimization: bool = False
    ) -> Optional[ProcessingResult]:
        """Update document content with optional LLM improvements and re-evaluate."""
        try:
            processed_file_path = next(self.processed_dir.glob(f"*_{document_id}.md"), None)
            if not processed_file_path:
                return None

            final_content = content
            vector_optimized = False
            if improvement_prompt and llm_service.is_available:
                final_content = await llm_service.improve_document(content, improvement_prompt)
            elif apply_vector_optimization and llm_service.is_available:
                final_content = await llm_service.optimize_for_vector_db(content)
                vector_optimized = True
            
            final_content = clean_llm_response(final_content)
            processed_file_path.write_text(final_content, encoding="utf-8")
            
            # Re-evaluate
            score, feedback = self._score_conversion(final_content)
            llm_evaluation = await llm_service.evaluate_document(final_content) if llm_service.is_available else None
            passes_thresholds = self._meets_thresholds(score, llm_evaluation, options.quality_thresholds)
            
            # Find original file to create a full result object
            original_file_path = self._find_document_file(document_id)
            filename = original_file_path.name.split('_', 1)[-1] if original_file_path else processed_file_path.stem.split('_', 1)[-1]

            return ProcessingResult(
                document_id=document_id,
                filename=filename,
                status=ProcessingStatus.COMPLETED,
                success=True,
                original_path=str(original_file_path) if original_file_path else None,
                markdown_path=str(processed_file_path),
                conversion_result=ConversionResult(
                    success=True,
                    markdown_content=final_content,
                    conversion_score=score,
                    conversion_feedback=feedback,
                    conversion_note="Content updated and re-evaluated."
                ),
                llm_evaluation=llm_evaluation,
                conversion_score=score,
                pass_all_thresholds=passes_thresholds,
                vector_optimized=vector_optimized,
                processing_time=0.0, # Not a full process
                processed_at=time.time(),
                thresholds_used=options.quality_thresholds
            )
            
        except Exception as e:
            print(f"Error updating document {document_id}: {e}")
            return None


# Global document service instance
document_service = DocumentService()