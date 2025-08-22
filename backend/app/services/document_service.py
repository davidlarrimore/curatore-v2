# backend/app/services/document_service.py
import os
import io
import re
import time
import uuid
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
    ProcessingResult, ConversionResult, ProcessingStatus, 
    OCRSettings, QualityThresholds, ProcessingOptions
)
from .llm_service import llm_service


class DocumentService:
    """Service for document processing operations."""
    
    SUPPORTED_EXTENSIONS = {".docx", ".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".md", ".txt"}
    
    def __init__(self):
        # NEW DIRECTORY STRUCTURE
        self.files_root = Path(settings.files_root)
        self.upload_dir = Path(settings.upload_dir)
        self.processed_dir = Path(settings.processed_dir)
        self.batch_dir = Path(settings.batch_dir)
        self._ensure_directories()
    
    def _ensure_directories(self) -> None:
        """Ensure required directories exist."""
        self.files_root.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.batch_dir.mkdir(parents=True, exist_ok=True)
    
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
    
    async def convert_to_markdown(
        self, 
        file_path: Path, 
        ocr_settings: OCRSettings
    ) -> ConversionResult:
        """Convert document to markdown format."""
        start_time = time.time()
        filename = file_path.name
        extension = file_path.suffix.lower()
        
        try:
            if extension == ".pdf":
                return await self._convert_pdf_to_markdown(file_path, ocr_settings)
            elif extension == ".docx":
                return await self._convert_docx_to_markdown(file_path)
            elif extension in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
                return await self._convert_image_to_markdown(file_path, ocr_settings)
            elif extension in {".txt", ".md"}:
                return await self._convert_text_to_markdown(file_path)
            else:
                return ConversionResult(
                    filename=filename,
                    success=False,
                    error_message=f"Unsupported file format: {extension}",
                    conversion_time=time.time() - start_time
                )
        except Exception as e:
            return ConversionResult(
                filename=filename,
                success=False,
                error_message=f"Conversion error: {str(e)}",
                conversion_time=time.time() - start_time
            )
    
    async def _convert_pdf_to_markdown(self, file_path: Path, ocr_settings: OCRSettings) -> ConversionResult:
        """Convert PDF to markdown using text extraction + OCR fallback."""
        start_time = time.time()
        filename = file_path.name
        
        try:
            # Try MarkItDown first if available
            if MD_CONVERTER:
                try:
                    result = MD_CONVERTER.convert(str(file_path))
                    if result and result.text_content.strip():
                        return ConversionResult(
                            filename=filename,
                            success=True,
                            markdown_content=result.text_content,
                            method="MarkItDown",
                            conversion_time=time.time() - start_time,
                            conversion_score=85  # High score for successful text extraction
                        )
                except Exception:
                    pass
            
            # Fallback to pdfminer
            try:
                text = pdf_extract_text(str(file_path))
                if text and text.strip() and len(text.strip()) > 50:
                    return ConversionResult(
                        filename=filename,
                        success=True,
                        markdown_content=text,
                        method="PDFMiner Text Extraction",
                        conversion_time=time.time() - start_time,
                        conversion_score=80
                    )
            except Exception:
                pass
            
            # OCR fallback
            try:
                images = self._pdf_pages_to_images(file_path)
                if not images:
                    raise Exception("Could not convert PDF pages to images")
                
                ocr_texts = []
                total_confidence = 0
                
                for i, img in enumerate(images):
                    text, conf = self._ocr_image_with_tesseract(
                        img, 
                        ocr_settings.language, 
                        ocr_settings.page_segmentation_mode
                    )
                    if text:
                        ocr_texts.append(f"## Page {i+1}\n\n{text}")
                        total_confidence += conf
                
                if ocr_texts:
                    avg_confidence = total_confidence / len(images)
                    markdown_content = "\n\n".join(ocr_texts)
                    conversion_score = int(avg_confidence * 100)
                    
                    return ConversionResult(
                        filename=filename,
                        success=True,
                        markdown_content=markdown_content,
                        method="OCR",
                        ocr_confidence=avg_confidence,
                        conversion_time=time.time() - start_time,
                        conversion_score=conversion_score
                    )
            except Exception as e:
                pass
            
            return ConversionResult(
                filename=filename,
                success=False,
                error_message="All PDF conversion methods failed",
                conversion_time=time.time() - start_time
            )
            
        except Exception as e:
            return ConversionResult(
                filename=filename,
                success=False,
                error_message=f"PDF conversion error: {str(e)}",
                conversion_time=time.time() - start_time
            )
    
    async def _convert_docx_to_markdown(self, file_path: Path) -> ConversionResult:
        """Convert DOCX to markdown."""
        start_time = time.time()
        filename = file_path.name
        
        try:
            # Try MarkItDown first
            if MD_CONVERTER:
                try:
                    result = MD_CONVERTER.convert(str(file_path))
                    if result and result.text_content.strip():
                        return ConversionResult(
                            filename=filename,
                            success=True,
                            markdown_content=result.text_content,
                            method="MarkItDown",
                            conversion_time=time.time() - start_time,
                            conversion_score=90
                        )
                except Exception:
                    pass
            
            # Fallback to python-docx
            doc = docx.Document(str(file_path))
            paragraphs = []
            
            for paragraph in doc.paragraphs:
                text = paragraph.text.strip()
                if text:
                    paragraphs.append(text)
            
            if paragraphs:
                markdown_content = "\n\n".join(paragraphs)
                return ConversionResult(
                    filename=filename,
                    success=True,
                    markdown_content=markdown_content,
                    method="python-docx",
                    conversion_time=time.time() - start_time,
                    conversion_score=85
                )
            
            return ConversionResult(
                filename=filename,
                success=False,
                error_message="No text content found in DOCX file",
                conversion_time=time.time() - start_time
            )
            
        except Exception as e:
            return ConversionResult(
                filename=filename,
                success=False,
                error_message=f"DOCX conversion error: {str(e)}",
                conversion_time=time.time() - start_time
            )
    
    async def _convert_image_to_markdown(self, file_path: Path, ocr_settings: OCRSettings) -> ConversionResult:
        """Convert image to markdown using OCR."""
        start_time = time.time()
        filename = file_path.name
        
        try:
            img = Image.open(file_path).convert("RGB")
            text, confidence = self._ocr_image_with_tesseract(
                img, 
                ocr_settings.language, 
                ocr_settings.page_segmentation_mode
            )
            
            if text and text.strip():
                conversion_score = int(confidence * 100)
                return ConversionResult(
                    filename=filename,
                    success=True,
                    markdown_content=text,
                    method="OCR",
                    ocr_confidence=confidence,
                    conversion_time=time.time() - start_time,
                    conversion_score=conversion_score
                )
            
            return ConversionResult(
                filename=filename,
                success=False,
                error_message="No text detected in image",
                conversion_time=time.time() - start_time
            )
            
        except Exception as e:
            return ConversionResult(
                filename=filename,
                success=False,
                error_message=f"Image OCR error: {str(e)}",
                conversion_time=time.time() - start_time
            )
    
    async def _convert_text_to_markdown(self, file_path: Path) -> ConversionResult:
        """Convert text/markdown file."""
        start_time = time.time()
        filename = file_path.name
        
        try:
            content = file_path.read_text(encoding="utf-8")
            if content.strip():
                return ConversionResult(
                    filename=filename,
                    success=True,
                    markdown_content=content,
                    method="Direct Text Loading",
                    conversion_time=time.time() - start_time,
                    conversion_score=100
                )
            
            return ConversionResult(
                filename=filename,
                success=False,
                error_message="File is empty",
                conversion_time=time.time() - start_time
            )
            
        except Exception as e:
            return ConversionResult(
                filename=filename,
                success=False,
                error_message=f"Text file error: {str(e)}",
                conversion_time=time.time() - start_time
            )
    
    async def save_uploaded_file(self, filename: str, content: bytes) -> Tuple[str, Path]:
        """Save uploaded file and return document ID and file path."""
        # Generate unique document ID
        document_id = str(uuid.uuid4())
        
        # Sanitize filename
        safe_filename = filename.replace("../", "").replace("..\\", "")
        safe_filename = safe_filename.replace("/", "_").replace("\\", "_")
        
        # Create unique filename with document ID
        file_path = self.upload_dir / f"{document_id}_{safe_filename}"
        
        # Ensure directory exists
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        
        # Save file
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
            # Ensure upload directory exists
            self.upload_dir.mkdir(parents=True, exist_ok=True)
            
            for file_path in self.upload_dir.glob("*"):
                if file_path.is_file():
                    # Check if it's a supported file type
                    if file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                        try:
                            stat = file_path.stat()
                            
                            # Extract document_id from filename
                            # Format: {document_id}_{original_filename}
                            filename_parts = file_path.name.split('_', 1)
                            if len(filename_parts) >= 2:
                                document_id = filename_parts[0]
                                original_filename = filename_parts[1]
                            else:
                                # Fallback if filename doesn't follow expected format
                                document_id = file_path.stem
                                original_filename = file_path.name
                            
                            files.append({
                                "document_id": document_id,
                                "filename": original_filename,
                                "original_filename": file_path.name,
                                "file_size": stat.st_size,
                                "upload_time": stat.st_mtime * 1000,  # Convert to milliseconds for JS
                                "file_path": str(file_path)
                            })
                        except Exception as e:
                            print(f"Error processing file {file_path}: {e}")
                            continue
        except Exception as e:
            print(f"Error listing files in {self.upload_dir}: {e}")
            return []
        
        # Sort by upload time (newest first)
        files.sort(key=lambda x: x["upload_time"], reverse=True)
        return files
    
    def list_batch_files(self) -> List[Dict[str, Any]]:
        """List all batch files with metadata."""
        files = []
        try:
            # Ensure batch directory exists
            self.batch_dir.mkdir(parents=True, exist_ok=True)
            
            for file_path in self.batch_dir.glob("*"):
                if file_path.is_file():
                    # Check if it's a supported file type
                    if file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                        try:
                            stat = file_path.stat()
                            
                            # Use filename as document_id for batch files
                            document_id = file_path.stem
                            
                            files.append({
                                "document_id": document_id,
                                "filename": file_path.name,
                                "original_filename": file_path.name,
                                "file_size": stat.st_size,
                                "upload_time": stat.st_mtime * 1000,  # Convert to milliseconds for JS
                                "file_path": str(file_path)
                            })
                        except Exception as e:
                            print(f"Error processing batch file {file_path}: {e}")
                            continue
        except Exception as e:
            print(f"Error listing files in {self.batch_dir}: {e}")
            return []
        
        # Sort by upload time (newest first)
        files.sort(key=lambda x: x["upload_time"], reverse=True)
        return files
    
    def get_processed_content(self, document_id: str) -> Optional[str]:
        """Get processed markdown content for a document."""
        # Look for processed file
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
        improvement_prompt: Optional[str] = None,
        apply_vector_optimization: bool = False
    ) -> Optional[ProcessingResult]:
        """Update document content with optional LLM improvements."""
        try:
            start_time = time.time()
            
            # Apply improvements if requested
            if improvement_prompt or apply_vector_optimization:
                content = await self._apply_content_improvements(
                    content, improvement_prompt, apply_vector_optimization
                )
            
            # Save updated content
            processed_file = self.processed_dir / f"updated_{document_id}.md"
            processed_file.write_text(content, encoding="utf-8")
            
            # Re-evaluate quality
            quality_scores = await llm_service.evaluate_quality(content)
            
            # Get default thresholds (you might want to get these from settings)
            thresholds = QualityThresholds(
                conversion_threshold=settings.default_conversion_threshold,
                clarity_threshold=settings.default_clarity_threshold,
                completeness_threshold=settings.default_completeness_threshold,
                relevance_threshold=settings.default_relevance_threshold,
                markdown_threshold=settings.default_markdown_threshold
            )
            
            # Check if passes all thresholds
            passes_thresholds = (
                quality_scores.clarity >= thresholds.clarity_threshold and
                quality_scores.completeness >= thresholds.completeness_threshold and
                quality_scores.relevance >= thresholds.relevance_threshold and
                quality_scores.markdown_quality >= thresholds.markdown_threshold
            )
            
            return ProcessingResult(
                document_id=document_id,
                filename=f"updated_{document_id}.md",
                status=ProcessingStatus.COMPLETED,
                success=True,
                message="Content updated successfully",
                processed_path=str(processed_file),
                markdown_content=content,
                quality_scores=quality_scores,
                pass_all_thresholds=passes_thresholds,
                processing_time=time.time() - start_time,
                processed_at=time.time(),
                thresholds_used=thresholds
            )
            
        except Exception as e:
            print(f"Error updating content for {document_id}: {e}")
            return None
    
    async def _apply_content_improvements(
        self, 
        content: str, 
        improvement_prompt: Optional[str] = None,
        apply_vector_optimization: bool = False
    ) -> str:
        """Apply LLM-based improvements to content."""
        if apply_vector_optimization:
            content = await llm_service.optimize_for_vector_db(content)
        
        if improvement_prompt:
            content = await llm_service.improve_content(content, improvement_prompt)
        
        return content
    
    async def process_document(
        self, 
        document_id: str, 
        file_path: Path, 
        options: ProcessingOptions
    ) -> ProcessingResult:
        """Process a single document."""
        start_time = time.time()
        filename = file_path.name
        
        try:
            # Convert to markdown
            conversion_result = await self.convert_to_markdown(file_path, options.ocr_settings)
            
            if not conversion_result.success:
                return ProcessingResult(
                    document_id=document_id,
                    filename=filename,
                    status=ProcessingStatus.FAILED,
                    success=False,
                    message=conversion_result.error_message or "Conversion failed",
                    original_path=str(file_path),
                    processing_time=time.time() - start_time,
                    thresholds_used=options.quality_thresholds
                )
            
            markdown_content = conversion_result.markdown_content
            
            # Apply vector optimization if requested
            vector_optimized = False
            if options.vector_db_optimization:
                try:
                    markdown_content = await llm_service.optimize_for_vector_db(markdown_content)
                    vector_optimized = True
                except Exception as e:
                    print(f"Vector optimization failed: {e}")
            
            # Save processed content
            processed_file = self.processed_dir / f"{filename}_{document_id}.md"
            processed_file.write_text(markdown_content, encoding="utf-8")
            
            # Evaluate quality
            quality_scores = await llm_service.evaluate_quality(markdown_content)
            document_summary = await llm_service.generate_summary(markdown_content)
            
            # Check if passes all thresholds
            passes_thresholds = (
                conversion_result.conversion_score >= options.quality_thresholds.conversion_threshold and
                quality_scores.clarity >= options.quality_thresholds.clarity_threshold and
                quality_scores.completeness >= options.quality_thresholds.completeness_threshold and
                quality_scores.relevance >= options.quality_thresholds.relevance_threshold and
                quality_scores.markdown_quality >= options.quality_thresholds.markdown_threshold
            )
            
            return ProcessingResult(
                document_id=document_id,
                filename=filename,
                status=ProcessingStatus.COMPLETED,
                success=True,
                message="Processing completed successfully",
                original_path=str(file_path),
                processed_path=str(processed_file),
                markdown_content=markdown_content,
                quality_scores=quality_scores,
                document_summary=document_summary,
                conversion_score=conversion_result.conversion_score,
                pass_all_thresholds=passes_thresholds,
                vector_optimized=vector_optimized,
                processing_time=time.time() - start_time,
                processed_at=time.time(),
                thresholds_used=options.quality_thresholds
            )
            
        except Exception as e:
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
        """Find the uploaded or batch file for a document ID."""
        # Look in uploaded files first
        for file_path in self.upload_dir.glob(f"{document_id}_*"):
            if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                return file_path
        
        # Look in batch files
        for file_path in self.batch_dir.glob("*"):
            if (file_path.is_file() and 
                file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS and
                (file_path.stem == document_id or document_id in str(file_path.name))):
                return file_path
        
        # Fallback: look for any file that contains the document_id in upload dir
        for file_path in self.upload_dir.glob("*"):
            if (file_path.is_file() and 
                file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS and
                document_id in str(file_path.name)):
                return file_path
        
        return None
    
    def get_supported_extensions(self) -> List[str]:
        """Get list of supported file extensions."""
        return list(self.SUPPORTED_EXTENSIONS)
    
    def is_supported_file(self, filename: str) -> bool:
        """Check if file is supported for processing."""
        return Path(filename).suffix.lower() in self.SUPPORTED_EXTENSIONS


# Global service instance
document_service = DocumentService()