# backend/app/functions/output/generate_document.py
"""
Generate Document function - Create PDF, DOCX, or CSV files.

This function wraps the document generation service to create documents
from markdown content or structured data.

Supported formats:
    - PDF: From markdown content (uses WeasyPrint)
    - DOCX: From markdown content (uses python-docx)
    - CSV: From list of dictionaries (uses Python csv)
"""

import base64
import logging

from ...base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from ...context import FunctionContext

logger = logging.getLogger("curatore.functions.output.generate_document")


class GenerateDocumentFunction(BaseFunction):
    """
    Generate a document (PDF, DOCX, or CSV) from content or data.

    This function creates documents that can be:
    - Returned as base64-encoded bytes
    - Saved to object storage via create_artifact
    - Attached to emails via send_email

    Example (PDF from markdown):
        result = await fn.generate_document(ctx,
            content="# Report\\n\\nThis is the report content.",
            format="pdf",
            title="Monthly Report",
        )

    Example (CSV from data):
        result = await fn.generate_document(ctx,
            format="csv",
            data=[
                {"name": "Alice", "score": 95},
                {"name": "Bob", "score": 87},
            ],
        )

    Example (DOCX with custom filename):
        result = await fn.generate_document(ctx,
            content="# Contract\\n\\n...",
            format="docx",
            title="Service Agreement",
            filename="contract_2024.docx",
        )
    """

    meta = FunctionMeta(
        name="generate_document",
        category=FunctionCategory.OUTPUT,
        description="Generate a document (PDF, DOCX, or CSV) from content or data",
        input_schema={
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "description": "Output format: pdf, docx, or csv",
                    "enum": ["pdf", "docx", "csv"],
                },
                "content": {
                    "type": "string",
                    "description": "Markdown content (required for pdf/docx)",
                },
                "data": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of dictionaries for CSV generation",
                },
                "title": {
                    "type": "string",
                    "description": "Document title (used in PDF header and DOCX properties)",
                },
                "filename": {
                    "type": "string",
                    "description": "Output filename (auto-generated if not provided)",
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Column order for CSV (auto-detected if not provided)",
                },
                "include_title_page": {
                    "type": "boolean",
                    "description": "Include a title page in PDF (default: false)",
                    "default": False,
                },
                "css": {
                    "type": "string",
                    "description": "Custom CSS for PDF styling",
                },
                "save_to_storage": {
                    "type": "boolean",
                    "description": "If true, saves to object storage and returns URL",
                    "default": False,
                },
                "folder": {
                    "type": "string",
                    "description": "Storage folder (when save_to_storage=true)",
                    "default": "generated_documents",
                },
            },
            "required": ["format"],
        },
        output_schema={
            "type": "object",
            "description": "Generated document with content and optional storage info",
            "properties": {
                "format": {
                    "type": "string",
                    "description": "Document format (pdf, docx, csv)",
                    "examples": ["pdf"],
                },
                "filename": {
                    "type": "string",
                    "description": "Generated filename",
                    "examples": ["report_20240115_123456.pdf"],
                },
                "content_type": {
                    "type": "string",
                    "description": "MIME type of the document",
                    "examples": ["application/pdf"],
                },
                "size": {
                    "type": "integer",
                    "description": "Size of the document in bytes",
                },
                "document_base64": {
                    "type": "string",
                    "description": "Base64-encoded document content",
                },
                "storage": {
                    "type": "object",
                    "description": "Storage info if save_to_storage=true (bucket, object_key, download_url)",
                    "nullable": True,
                },
            },
        },
        tags=["output", "document", "pdf", "docx", "csv", "generation"],
        requires_llm=False,
        side_effects=True,
        is_primitive=True,
        payload_profile="full",
        examples=[
            {
                "description": "Generate PDF from markdown",
                "params": {
                    "format": "pdf",
                    "content": "# Hello World\n\nThis is a test document.",
                    "title": "Test Document",
                },
            },
            {
                "description": "Generate CSV from data",
                "params": {
                    "format": "csv",
                    "data": [
                        {"name": "Item 1", "value": 100},
                        {"name": "Item 2", "value": 200},
                    ],
                    "columns": ["name", "value"],
                },
            },
            {
                "description": "Generate DOCX and save to storage",
                "params": {
                    "format": "docx",
                    "content": "# Contract\n\nTerms and conditions...",
                    "title": "Service Agreement",
                    "save_to_storage": True,
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Generate a document in the specified format."""
        format_type = params["format"].lower()
        content = params.get("content", "")
        data = params.get("data")
        title = params.get("title", "Document")
        filename = params.get("filename")
        columns = params.get("columns")
        include_title_page = params.get("include_title_page", False)
        css = params.get("css")
        save_to_storage = params.get("save_to_storage", False)
        folder = params.get("folder", "generated_documents")

        # Validate parameters
        if format_type in ("pdf", "docx") and not content:
            return FunctionResult.failed_result(
                error=f"'content' is required for {format_type.upper()} generation",
                message="Missing required parameter",
            )

        if format_type == "csv" and not data:
            return FunctionResult.failed_result(
                error="'data' is required for CSV generation",
                message="Missing required parameter",
            )

        # Auto-generate filename if not provided
        if not filename:
            from datetime import datetime
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            safe_title = "".join(
                c if c.isalnum() or c in "._-" else "_"
                for c in title.lower()
            )[:50]
            filename = f"{safe_title}_{timestamp}.{format_type}"

        try:
            # Import the document generation service
            from app.core.llm.document_generation_service import document_generation_service

            # Generate the document
            doc_bytes = await document_generation_service.generate(
                content=content,
                format=format_type,
                title=title,
                data=data,
                columns=columns,
                css=css,
                include_title_page=include_title_page,
            )

            # Determine content type
            content_types = {
                "pdf": "application/pdf",
                "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "csv": "text/csv",
            }
            content_type = content_types.get(format_type, "application/octet-stream")

            # Prepare result data
            result_data = {
                "format": format_type,
                "filename": filename,
                "content_type": content_type,
                "size": len(doc_bytes),
                "document_base64": base64.b64encode(doc_bytes).decode("utf-8"),
            }

            # Dry run mode
            if ctx.dry_run:
                return FunctionResult.success_result(
                    data={
                        "format": format_type,
                        "filename": filename,
                        "content_type": content_type,
                        "size": len(doc_bytes),
                        "would_save": save_to_storage,
                    },
                    message=f"Dry run: would generate {format_type.upper()}",
                )

            # Save to storage if requested
            if save_to_storage:
                minio = ctx.minio_service
                if not minio or not minio.enabled:
                    return FunctionResult.failed_result(
                        error="Object storage not available",
                        message="MinIO service is not configured",
                    )

                from datetime import datetime
                from io import BytesIO
                from uuid import uuid4

                from app.config import settings

                bucket = settings.minio_bucket_processed
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                artifact_id = uuid4().hex[:8]
                object_key = f"{ctx.organization_id}/{folder}/{timestamp}_{artifact_id}_{filename}"

                minio.put_object(
                    bucket=bucket,
                    key=object_key,
                    data=BytesIO(doc_bytes),
                    length=len(doc_bytes),
                    content_type=content_type,
                )

                # Generate presigned URL
                try:
                    download_url = minio.get_presigned_get_url(
                        bucket=bucket,
                        key=object_key,
                        expires_seconds=3600,
                    )
                except Exception:
                    download_url = None

                result_data["storage"] = {
                    "bucket": bucket,
                    "object_key": object_key,
                    "download_url": download_url,
                }

            return FunctionResult.success_result(
                data=result_data,
                message=f"Generated {format_type.upper()}: {filename}",
                items_processed=1,
            )

        except ValueError as e:
            return FunctionResult.failed_result(
                error=str(e),
                message="Invalid parameters",
            )
        except RuntimeError as e:
            logger.exception(f"Document generation failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Document generation failed",
            )
        except Exception as e:
            logger.exception(f"Unexpected error generating document: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message=f"Unexpected error: {type(e).__name__}",
            )
