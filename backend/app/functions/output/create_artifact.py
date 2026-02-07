# backend/app/functions/output/create_artifact.py
"""
Create Artifact function - Save content to object storage.

Creates an artifact (file) in object storage.
"""

from typing import Any, Dict, Optional
from uuid import UUID, uuid4
from datetime import datetime
import json
import logging

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
    OutputFieldDoc,
    OutputSchema,
)
from ..context import FunctionContext

logger = logging.getLogger("curatore.functions.output.create_artifact")


class CreateArtifactFunction(BaseFunction):
    """
    Create an artifact (file) in object storage.

    Saves content to MinIO and optionally creates a database record.

    Example:
        result = await fn.create_artifact(ctx,
            content="Report content here...",
            filename="daily_digest.md",
            content_type="text/markdown",
        )
    """

    meta = FunctionMeta(
        name="create_artifact",
        category=FunctionCategory.OUTPUT,
        description="Create an artifact (file) in object storage",
        parameters=[
            ParameterDoc(
                name="content",
                type="str | bytes | dict",
                description="Content to save (str, bytes, or dict for JSON)",
                required=True,
            ),
            ParameterDoc(
                name="filename",
                type="str",
                description="Filename for the artifact",
                required=True,
            ),
            ParameterDoc(
                name="content_type",
                type="str",
                description="MIME type of the content",
                required=False,
                default="text/plain",
            ),
            ParameterDoc(
                name="folder",
                type="str",
                description="Folder path within the bucket",
                required=False,
                default="artifacts",
            ),
            ParameterDoc(
                name="bucket",
                type="str",
                description="Bucket to store in (default: processed bucket)",
                required=False,
                default=None,
            ),
        ],
        returns="dict: Artifact info with bucket, key, and URL",
        output_schema=OutputSchema(
            type="dict",
            description="Created artifact information with storage location",
            fields=[
                OutputFieldDoc(name="bucket", type="str",
                              description="MinIO bucket where artifact is stored"),
                OutputFieldDoc(name="object_key", type="str",
                              description="Full object key/path in the bucket"),
                OutputFieldDoc(name="filename", type="str",
                              description="Original filename of the artifact"),
                OutputFieldDoc(name="content_type", type="str",
                              description="MIME type of the content",
                              example="text/markdown"),
                OutputFieldDoc(name="size", type="int",
                              description="Size of the artifact in bytes"),
                OutputFieldDoc(name="download_url", type="str",
                              description="Presigned URL for downloading (valid for 1 hour)",
                              nullable=True),
            ],
        ),
        tags=["output", "storage", "artifact"],
        requires_llm=False,
        examples=[
            {
                "description": "Save markdown report",
                "params": {
                    "content": "# Daily Report\n\n...",
                    "filename": "report.md",
                    "content_type": "text/markdown",
                },
            },
            {
                "description": "Save JSON data",
                "params": {
                    "content": {"key": "value"},
                    "filename": "data.json",
                    "content_type": "application/json",
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Create artifact in object storage."""
        content = params["content"]
        filename = params["filename"]
        content_type = params.get("content_type", "text/plain")
        folder = params.get("folder", "artifacts")
        bucket = params.get("bucket")

        from ...config import settings

        try:
            # Prepare content
            if isinstance(content, dict):
                content_bytes = json.dumps(content, indent=2, default=str).encode("utf-8")
                if content_type == "text/plain":
                    content_type = "application/json"
            elif isinstance(content, str):
                content_bytes = content.encode("utf-8")
            else:
                content_bytes = content

            # Determine bucket
            if not bucket:
                bucket = settings.minio_bucket_processed

            # Build object key
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            artifact_id = uuid4().hex[:8]
            object_key = f"{ctx.organization_id}/{folder}/{timestamp}_{artifact_id}_{filename}"

            if ctx.dry_run:
                return FunctionResult.success_result(
                    data={
                        "bucket": bucket,
                        "object_key": object_key,
                        "size": len(content_bytes),
                    },
                    message="Dry run: would create artifact",
                )

            # Upload to MinIO
            minio = ctx.minio_service
            if not minio or not minio.enabled:
                return FunctionResult.failed_result(
                    error="Object storage not available",
                    message="MinIO service is not configured",
                )

            from io import BytesIO
            minio.put_object(
                bucket=bucket,
                key=object_key,
                data=BytesIO(content_bytes),
                length=len(content_bytes),
                content_type=content_type,
            )

            # Generate presigned URL (valid for 1 hour)
            try:
                download_url = minio.get_presigned_get_url(
                    bucket=bucket,
                    key=object_key,
                    expires_seconds=3600,
                )
            except Exception:
                download_url = None

            return FunctionResult.success_result(
                data={
                    "bucket": bucket,
                    "object_key": object_key,
                    "filename": filename,
                    "content_type": content_type,
                    "size": len(content_bytes),
                    "download_url": download_url,
                },
                message=f"Created artifact: {filename}",
                items_processed=1,
            )

        except Exception as e:
            logger.exception(f"Failed to create artifact: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Failed to create artifact",
            )
