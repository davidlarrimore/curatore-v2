"""
MinIO Storage Service.

Provides object storage operations using MinIO S3-compatible API.
Integrated directly into backend (no separate microservice needed).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from io import BytesIO
from typing import BinaryIO, Dict, List, Optional, Tuple
from functools import lru_cache

from minio import Minio
from minio.commonconfig import ENABLED
from minio.error import S3Error
from minio.lifecycleconfig import LifecycleConfig, Rule, Expiration

from app.config import settings
from app.core.shared.config_loader import config_loader

logger = logging.getLogger("curatore.minio")


# =============================================================================
# BUCKET CONFIGURATION
# =============================================================================

# Display names for system buckets (shown in UI)
# These can be customized via environment variables
BUCKET_DISPLAY_NAMES: Dict[str, str] = {
    settings.minio_bucket_uploads: settings.minio_bucket_uploads_display_name,
    settings.minio_bucket_processed: settings.minio_bucket_processed_display_name,
    settings.minio_bucket_temp: settings.minio_bucket_temp_display_name,
}

# Buckets that are protected (read-only for users, no folder creation/deletion)
PROTECTED_BUCKETS: set = {
    settings.minio_bucket_processed,
    settings.minio_bucket_temp,
}


@dataclass
class ObjectInfo:
    """Information about an object in storage."""
    key: str
    size: int
    content_type: Optional[str]
    etag: str
    last_modified: datetime
    is_folder: bool = False
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class BrowseResult:
    """Result of browsing a bucket/prefix."""
    bucket: str
    prefix: str
    folders: List[str]
    objects: List[ObjectInfo]
    is_protected: bool
    parent_prefix: Optional[str]


class MinIOService:
    """
    MinIO storage service implementation.

    Provides S3-compatible object storage operations including:
    - Object upload/download
    - Presigned URL generation
    - Bucket management
    - Lifecycle policy configuration

    Configuration Sources (priority order):
        1. config.yml (if present) via config_loader.get_minio_config()
        2. Environment variables via settings (backward compatibility)
    """

    def __init__(self):
        """
        Initialize MinIO clients and load configuration.

        Configuration is loaded from config.yml if available, otherwise
        falls back to environment variables from .env file.
        """
        self._client: Optional[Minio] = None
        self._presigned_client: Optional[Minio] = None
        self._load_config()

    def _load_config(self):
        """
        Load MinIO configuration from config.yml or environment variables.

        Configuration priority:
            1. config.yml via config_loader.get_minio_config()
            2. Environment variables via settings (backward compatibility)
        """
        # Try loading from config.yml first
        minio_config = config_loader.get_minio_config()

        if minio_config:
            logger.info("Loading MinIO configuration from config.yml")
            self.enabled = minio_config.enabled
            self.endpoint = minio_config.endpoint
            self.presigned_endpoint = minio_config.presigned_endpoint
            self.public_endpoint = minio_config.public_endpoint
            self.access_key = minio_config.access_key
            self.secret_key = minio_config.secret_key
            self.secure = minio_config.secure
            self.public_secure = minio_config.public_secure if minio_config.public_secure is not None else minio_config.secure
            self.bucket_uploads = minio_config.bucket_uploads
            self.bucket_processed = minio_config.bucket_processed
            self.bucket_temp = minio_config.bucket_temp
            self.presigned_expiry = minio_config.presigned_expiry
        else:
            # Fallback to environment variables
            logger.info("Loading MinIO configuration from environment variables")
            self.enabled = settings.use_object_storage
            self.endpoint = settings.minio_endpoint
            self.presigned_endpoint = settings.minio_presigned_endpoint
            self.public_endpoint = settings.minio_public_endpoint
            self.access_key = settings.minio_access_key
            self.secret_key = settings.minio_secret_key
            self.secure = settings.minio_secure
            self.public_secure = settings.minio_public_secure
            self.bucket_uploads = settings.minio_bucket_uploads
            self.bucket_processed = settings.minio_bucket_processed
            self.bucket_temp = settings.minio_bucket_temp
            self.presigned_expiry = settings.minio_presigned_expiry

    @property
    def client(self) -> Minio:
        """Get or create MinIO client for internal operations (lazy initialization)."""
        if self._client is None:
            self._client = Minio(
                endpoint=self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure,
            )
            logger.info(
                f"MinIO client initialized (endpoint={self.endpoint}, "
                f"secure={self.secure})"
            )
        return self._client

    @property
    def presigned_client(self) -> Minio:
        """
        Get or create MinIO client for presigned URL generation.

        Uses presigned_endpoint if configured (should be reachable from
        backend container), otherwise falls back to endpoint.

        The generated URLs will then be rewritten to use public_endpoint
        for external client access.
        """
        if self._presigned_client is None:
            # Use presigned endpoint if configured, otherwise fall back to internal
            endpoint = self.presigned_endpoint or self.endpoint
            secure = self.public_secure if self.presigned_endpoint else self.secure

            self._presigned_client = Minio(
                endpoint=endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=secure,
            )
            logger.info(
                f"MinIO presigned client initialized (endpoint={endpoint}, "
                f"secure={secure})"
            )
        return self._presigned_client

    def _rewrite_presigned_url(self, url: str) -> str:
        """
        Rewrite presigned URL to use public endpoint if configured.

        The presigned URL is generated using presigned_endpoint (for correct
        signature), but the URL hostname is replaced with public_endpoint
        (for external client access).

        Args:
            url: Original presigned URL

        Returns:
            URL with public endpoint if public_endpoint is set
        """
        public_endpoint = self.public_endpoint
        presigned_endpoint = self.presigned_endpoint or self.endpoint

        if not public_endpoint or public_endpoint == presigned_endpoint:
            return url

        # Build the presigned and public base URLs
        presigned_protocol = "https" if (self.public_secure if self.presigned_endpoint else self.secure) else "http"
        presigned_base = f"{presigned_protocol}://{presigned_endpoint}"

        public_protocol = "https" if self.public_secure else "http"
        public_base = f"{public_protocol}://{public_endpoint}"

        # Replace presigned endpoint with public endpoint
        return url.replace(presigned_base, public_base)

    # =========================================================================
    # HEALTH CHECK
    # =========================================================================

    def check_health(self) -> Tuple[bool, Optional[List[str]], Optional[str]]:
        """
        Check MinIO connection health.

        Returns:
            Tuple of (connected, buckets list, error message)
        """
        try:
            buckets = self.client.list_buckets()
            bucket_names = [b.name for b in buckets]
            return True, bucket_names, None
        except Exception as e:
            logger.error(f"MinIO health check failed: {e}")
            return False, None, str(e)

    # =========================================================================
    # BUCKET OPERATIONS
    # =========================================================================

    def ensure_bucket(self, bucket: str) -> bool:
        """
        Create bucket if it doesn't exist.

        Args:
            bucket: Bucket name

        Returns:
            True if bucket was created, False if it already existed
        """
        try:
            if not self.client.bucket_exists(bucket):
                self.client.make_bucket(bucket)
                logger.info(f"Created bucket: {bucket}")
                return True
            logger.debug(f"Bucket already exists: {bucket}")
            return False
        except S3Error as e:
            logger.error(f"Failed to create bucket {bucket}: {e}")
            raise

    def list_buckets(self) -> List[Dict]:
        """
        List all buckets.

        Returns:
            List of bucket information dicts
        """
        buckets = self.client.list_buckets()
        return [
            {"name": b.name, "creation_date": b.creation_date}
            for b in buckets
        ]

    def bucket_exists(self, bucket: str) -> bool:
        """
        Check if bucket exists.

        Args:
            bucket: Bucket name

        Returns:
            True if bucket exists
        """
        return self.client.bucket_exists(bucket)

    # =========================================================================
    # LIFECYCLE POLICIES
    # =========================================================================

    def set_bucket_lifecycle(self, bucket: str, rules: List[Dict]) -> bool:
        """
        Configure bucket lifecycle policy for automatic object expiration.

        Args:
            bucket: Bucket name
            rules: List of lifecycle rule dicts with keys:
                - rule_id: str
                - prefix: str (default "")
                - expiration_days: int
                - enabled: bool (default True)

        Returns:
            True if policy was set successfully
        """
        try:
            minio_rules = []
            for rule in rules:
                minio_rule = Rule(
                    rule_id=rule["rule_id"],
                    status=ENABLED if rule.get("enabled", True) else "Disabled",
                    rule_filter={"prefix": rule.get("prefix", "")} if rule.get("prefix") else None,
                    expiration=Expiration(days=rule["expiration_days"]),
                )
                minio_rules.append(minio_rule)

            config = LifecycleConfig(minio_rules)
            self.client.set_bucket_lifecycle(bucket, config)
            logger.info(
                f"Set lifecycle policy for {bucket}: "
                f"{len(rules)} rules configured"
            )
            return True
        except S3Error as e:
            logger.error(f"Failed to set lifecycle for {bucket}: {e}")
            raise

    def set_lifecycle_policy(self, bucket: str, expiration_days: int, prefix: str = "") -> bool:
        """
        Convenience method to set a simple expiration policy on a bucket.

        Args:
            bucket: Bucket name
            expiration_days: Number of days before objects expire
            prefix: Optional prefix to apply the policy to (default: all objects)

        Returns:
            True if policy was set successfully
        """
        rules = [
            {
                "rule_id": f"expire-after-{expiration_days}-days",
                "prefix": prefix,
                "expiration_days": expiration_days,
                "enabled": True,
            }
        ]
        return self.set_bucket_lifecycle(bucket, rules)

    # =========================================================================
    # PRESIGNED URL OPERATIONS
    # =========================================================================

    def get_presigned_put_url(
        self,
        bucket: str,
        key: str,
        expires_seconds: Optional[int] = None,
        content_type: Optional[str] = None,
    ) -> str:
        """
        Generate presigned URL for PUT (upload) operation.

        DEPRECATED: Use proxy upload endpoint instead (/storage/upload/proxy).
        Presigned URLs require environment-specific configuration and direct
        browser-to-MinIO communication. Proxy endpoints simplify setup.

        Args:
            bucket: Bucket name
            key: Object key
            expires_seconds: URL expiry in seconds (default from config)
            content_type: Content-Type header value

        Returns:
            Presigned URL string (using public endpoint if configured)

        Note:
            The URL is generated using the internal endpoint, then the hostname
            is replaced with the public endpoint for external access. This works
            because S3 presigned URLs don't include the host in the signature
            when using v4 signing.
        """
        logger.warning(
            "get_presigned_put_url() is deprecated. "
            "Use proxy upload endpoint (/storage/upload/proxy) instead."
        )
        expires = expires_seconds or self.presigned_expiry
        url = self.presigned_client.presigned_put_object(
            bucket_name=bucket,
            object_name=key,
            expires=timedelta(seconds=expires),
        )
        url = self._rewrite_presigned_url(url)
        logger.debug(f"Generated presigned PUT URL for {bucket}/{key}")
        return url

    def get_presigned_get_url(
        self,
        bucket: str,
        key: str,
        expires_seconds: Optional[int] = None,
        response_headers: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Generate presigned URL for GET (download) operation.

        DEPRECATED: Use proxy download endpoint instead (/storage/object/download).
        Presigned URLs require environment-specific configuration and direct
        browser-to-MinIO communication. Proxy endpoints simplify setup.

        Args:
            bucket: Bucket name
            key: Object key
            expires_seconds: URL expiry in seconds (default from config)
            response_headers: Override response headers (content-type, disposition)

        Returns:
            Presigned URL string (using public endpoint if configured)

        Note:
            The URL is generated using presigned_endpoint, then the hostname
            is replaced with public_endpoint for external access.
        """
        logger.warning(
            "get_presigned_get_url() is deprecated. "
            "Use proxy download endpoint (/storage/object/download) instead."
        )
        expires = expires_seconds or self.presigned_expiry
        url = self.presigned_client.presigned_get_object(
            bucket_name=bucket,
            object_name=key,
            expires=timedelta(seconds=expires),
            response_headers=response_headers,
        )
        url = self._rewrite_presigned_url(url)
        logger.debug(f"Generated presigned GET URL for {bucket}/{key}")
        return url

    # =========================================================================
    # OBJECT OPERATIONS
    # =========================================================================

    def object_exists(self, bucket: str, key: str) -> bool:
        """
        Check if an object exists.

        Args:
            bucket: Bucket name
            key: Object key

        Returns:
            True if object exists
        """
        try:
            self.client.stat_object(bucket, key)
            return True
        except S3Error as e:
            if e.code == "NoSuchKey":
                return False
            raise

    def get_object_info(self, bucket: str, key: str) -> Optional[Dict]:
        """
        Get object metadata without downloading content.

        Args:
            bucket: Bucket name
            key: Object key

        Returns:
            Object info dict or None if not found
        """
        try:
            stat = self.client.stat_object(bucket, key)
            return {
                "bucket": bucket,
                "key": key,
                "size": stat.size,
                "content_type": stat.content_type,
                "etag": stat.etag.strip('"'),
                "last_modified": stat.last_modified,
                "metadata": dict(stat.metadata) if stat.metadata else {},
            }
        except S3Error as e:
            if e.code == "NoSuchKey":
                return None
            raise

    def put_object(
        self,
        bucket: str,
        key: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Upload an object.

        Args:
            bucket: Bucket name
            key: Object key
            data: File-like object with content
            length: Content length in bytes
            content_type: MIME type
            metadata: User metadata

        Returns:
            Object ETag
        """
        result = self.client.put_object(
            bucket_name=bucket,
            object_name=key,
            data=data,
            length=length,
            content_type=content_type,
            metadata=metadata,
        )
        logger.info(f"Uploaded object {bucket}/{key} ({length} bytes)")
        return result.etag

    def get_object(self, bucket: str, key: str) -> BytesIO:
        """
        Download an object.

        Args:
            bucket: Bucket name
            key: Object key

        Returns:
            BytesIO with object content
        """
        response = None
        try:
            response = self.client.get_object(bucket, key)
            content = BytesIO(response.read())
            return content
        finally:
            if response:
                response.close()
                response.release_conn()

    def delete_object(self, bucket: str, key: str) -> bool:
        """
        Delete an object.

        Args:
            bucket: Bucket name
            key: Object key

        Returns:
            True if deleted (or didn't exist)
        """
        try:
            self.client.remove_object(bucket, key)
            logger.info(f"Deleted object {bucket}/{key}")
            return True
        except S3Error as e:
            if e.code == "NoSuchKey":
                return True  # Already gone
            raise

    def copy_object(
        self,
        source_bucket: str,
        source_key: str,
        dest_bucket: str,
        dest_key: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """
        Copy an object within or between buckets.

        Args:
            source_bucket: Source bucket name
            source_key: Source object key
            dest_bucket: Destination bucket name
            dest_key: Destination object key
            metadata: New metadata (if None, copies source metadata)

        Returns:
            ETag of copied object or None on failure
        """
        from minio.commonconfig import CopySource

        try:
            result = self.client.copy_object(
                bucket_name=dest_bucket,
                object_name=dest_key,
                source=CopySource(source_bucket, source_key),
                metadata=metadata,
            )
            logger.info(f"Copied {source_bucket}/{source_key} -> {dest_bucket}/{dest_key}")
            return result.etag
        except S3Error as e:
            logger.error(f"Failed to copy object: {e}")
            raise

    def list_objects(
        self,
        bucket: str,
        prefix: str = "",
        recursive: bool = True,
        max_keys: int = 1000,
    ) -> List[Dict]:
        """
        List objects in a bucket.

        Args:
            bucket: Bucket name
            prefix: Filter by prefix
            recursive: Include nested objects
            max_keys: Maximum objects to return

        Returns:
            List of object info dicts
        """
        objects = []
        count = 0

        for obj in self.client.list_objects(
            bucket, prefix=prefix, recursive=recursive
        ):
            if count >= max_keys:
                break
            objects.append({
                "bucket": bucket,
                "key": obj.object_name,
                "size": obj.size or 0,
                "content_type": None,  # Not available in list
                "etag": obj.etag.strip('"') if obj.etag else "",
                "last_modified": obj.last_modified or datetime.utcnow(),
                "metadata": {},
            })
            count += 1

        return objects

    # =========================================================================
    # FOLDER OPERATIONS (Virtual folders using prefixes)
    # =========================================================================

    def list_prefixes(
        self,
        bucket: str,
        prefix: str = "",
        delimiter: str = "/",
    ) -> List[str]:
        """
        List folder prefixes at a given level.

        S3 doesn't have real folders - this lists common prefixes that act
        like folders when using a delimiter.

        Args:
            bucket: Bucket name
            prefix: Parent prefix to list within
            delimiter: Delimiter for folder separation (usually "/")

        Returns:
            List of folder prefixes (e.g., ["folder1/", "folder2/"])
        """
        prefixes = []

        # Ensure prefix ends with delimiter if not empty
        if prefix and not prefix.endswith(delimiter):
            prefix = prefix + delimiter

        for obj in self.client.list_objects(
            bucket, prefix=prefix, recursive=False
        ):
            # Check if this is a prefix (folder)
            if obj.is_dir:
                prefixes.append(obj.object_name)

        return prefixes

    def browse_bucket(
        self,
        bucket: str,
        prefix: str = "",
        max_objects: int = 1000,
    ) -> BrowseResult:
        """
        Browse a bucket at a specific prefix level.

        Returns both folders (prefixes) and objects at the current level.
        Does not recurse into subfolders.

        Args:
            bucket: Bucket name
            prefix: Prefix to browse (e.g., "org_123/folder/")
            max_objects: Maximum objects to return

        Returns:
            BrowseResult with folders and objects at this level
        """
        folders: List[str] = []
        objects: List[ObjectInfo] = []

        # Normalize prefix
        if prefix and not prefix.endswith("/"):
            prefix = prefix + "/"
        if prefix == "/":
            prefix = ""

        # List objects at this level (non-recursive)
        count = 0
        for obj in self.client.list_objects(
            bucket, prefix=prefix, recursive=False
        ):
            if obj.is_dir:
                # This is a folder prefix
                folder_name = obj.object_name
                # Remove the parent prefix to get just the folder name
                if prefix:
                    folder_name = obj.object_name[len(prefix):]
                # Strip trailing slash and validate
                folder_name = folder_name.rstrip("/")
                # Skip empty or invalid folder names
                if folder_name and folder_name.strip():
                    folders.append(folder_name)
            else:
                if count < max_objects:
                    objects.append(ObjectInfo(
                        key=obj.object_name,
                        size=obj.size or 0,
                        content_type=None,
                        etag=obj.etag.strip('"') if obj.etag else "",
                        last_modified=obj.last_modified or datetime.utcnow(),
                        is_folder=False,
                    ))
                    count += 1

        # Calculate parent prefix for navigation
        parent_prefix = None
        if prefix:
            # Remove trailing slash, then find previous slash
            trimmed = prefix.rstrip("/")
            last_slash = trimmed.rfind("/")
            if last_slash >= 0:
                parent_prefix = trimmed[:last_slash + 1]
            else:
                parent_prefix = ""  # Root level

        return BrowseResult(
            bucket=bucket,
            prefix=prefix,
            folders=sorted(folders),
            objects=objects,
            is_protected=bucket in PROTECTED_BUCKETS,
            parent_prefix=parent_prefix,
        )

    def create_folder(self, bucket: str, path: str) -> bool:
        """
        Create a virtual folder by uploading a zero-byte object.

        S3/MinIO doesn't have real folders, so we create a marker object
        ending with "/" to represent the folder.

        Args:
            bucket: Bucket name
            path: Folder path (e.g., "org_123/my-folder/subfolder")

        Returns:
            True if folder was created successfully

        Raises:
            S3Error: If creation fails
            ValueError: If trying to create folder in protected bucket
        """
        if bucket in PROTECTED_BUCKETS:
            raise ValueError(f"Cannot create folders in protected bucket: {bucket}")

        # Ensure path ends with /
        if not path.endswith("/"):
            path = path + "/"

        # Create a zero-byte object as folder marker
        try:
            self.client.put_object(
                bucket_name=bucket,
                object_name=path,
                data=BytesIO(b""),
                length=0,
                content_type="application/x-directory",
            )
            logger.info(f"Created folder: {bucket}/{path}")
            return True
        except S3Error as e:
            logger.error(f"Failed to create folder {bucket}/{path}: {e}")
            raise

    def delete_folder(
        self,
        bucket: str,
        path: str,
        recursive: bool = False,
    ) -> Tuple[int, int]:
        """
        Delete a folder and optionally its contents.

        Args:
            bucket: Bucket name
            path: Folder path to delete
            recursive: If True, delete all contents. If False, fail if not empty.

        Returns:
            Tuple of (deleted_count, failed_count)

        Raises:
            ValueError: If folder is not empty and recursive=False
            ValueError: If trying to delete folder in protected bucket
        """
        if bucket in PROTECTED_BUCKETS:
            raise ValueError(f"Cannot delete folders in protected bucket: {bucket}")

        # Ensure path ends with /
        if not path.endswith("/"):
            path = path + "/"

        # List all objects with this prefix
        objects_to_delete = []
        for obj in self.client.list_objects(bucket, prefix=path, recursive=True):
            objects_to_delete.append(obj.object_name)

        if not recursive and len(objects_to_delete) > 1:
            # More than just the folder marker
            raise ValueError(f"Folder is not empty: {path}. Use recursive=True to delete contents.")

        if len(objects_to_delete) == 0:
            # Folder doesn't exist or is already empty
            return (0, 0)

        deleted = 0
        failed = 0

        for obj_key in objects_to_delete:
            try:
                self.client.remove_object(bucket, obj_key)
                deleted += 1
            except S3Error as e:
                logger.error(f"Failed to delete {bucket}/{obj_key}: {e}")
                failed += 1

        logger.info(f"Deleted folder {bucket}/{path}: {deleted} objects deleted, {failed} failed")
        return (deleted, failed)

    def move_object(
        self,
        bucket: str,
        source_key: str,
        dest_key: str,
    ) -> bool:
        """
        Move an object within a bucket (copy + delete).

        Args:
            bucket: Bucket name
            source_key: Source object key
            dest_key: Destination object key

        Returns:
            True if move was successful

        Raises:
            S3Error: If move fails
        """
        from minio.commonconfig import CopySource

        try:
            # Copy to destination
            self.client.copy_object(
                bucket_name=bucket,
                object_name=dest_key,
                source=CopySource(bucket, source_key),
            )

            # Delete source
            self.client.remove_object(bucket, source_key)

            logger.info(f"Moved {bucket}/{source_key} -> {bucket}/{dest_key}")
            return True
        except S3Error as e:
            logger.error(f"Failed to move object: {e}")
            raise

    def rename_object(
        self,
        bucket: str,
        old_key: str,
        new_key: str,
    ) -> bool:
        """
        Rename an object (move to new key in same location).

        Args:
            bucket: Bucket name
            old_key: Current object key
            new_key: New object key

        Returns:
            True if rename was successful
        """
        return self.move_object(bucket, old_key, new_key)

    # =========================================================================
    # BUCKET METADATA HELPERS
    # =========================================================================

    def get_bucket_display_name(self, bucket: str) -> str:
        """
        Get the display name for a bucket.

        Args:
            bucket: Bucket name

        Returns:
            Display name (or bucket name if no display name configured)
        """
        return BUCKET_DISPLAY_NAMES.get(bucket, bucket)

    def is_bucket_protected(self, bucket: str) -> bool:
        """
        Check if a bucket is protected (read-only for users).

        Args:
            bucket: Bucket name

        Returns:
            True if bucket is protected
        """
        return bucket in PROTECTED_BUCKETS

    def list_accessible_buckets(self) -> List[Dict]:
        """
        List all buckets with their metadata.

        Returns:
            List of bucket info dicts with name, display_name, is_protected, is_default
        """
        buckets = []
        default_bucket = self.bucket_uploads

        for b in self.client.list_buckets():
            buckets.append({
                "name": b.name,
                "display_name": self.get_bucket_display_name(b.name),
                "is_protected": self.is_bucket_protected(b.name),
                "is_default": b.name == default_bucket,
                "creation_date": b.creation_date,
            })

        return buckets


# =============================================================================
# SINGLETON SERVICE
# =============================================================================


@lru_cache()
def get_minio_service() -> Optional[MinIOService]:
    """
    Get singleton MinIO service instance if object storage is enabled.

    Checks both config.yml and environment variables to determine if
    object storage should be enabled.

    Returns:
        MinIOService if object storage is enabled, else None
    """
    # Check config.yml first
    minio_config = config_loader.get_minio_config()
    if minio_config:
        if not minio_config.enabled:
            return None
    else:
        # Fallback to environment variable
        if not settings.use_object_storage:
            return None

    return MinIOService()
