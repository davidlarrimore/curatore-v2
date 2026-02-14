# Facet Validator Service
"""Validates facet_filters against the metadata catalog."""

import logging
import time
from typing import Any, Dict, List, Optional, Set

from app.services.backend_client import backend_client

logger = logging.getLogger("mcp.services.facet_validator")


class FacetValidator:
    """Validates facets against the metadata catalog."""

    def __init__(self, cache_ttl: int = 600):
        self._cache_ttl = cache_ttl
        self._facet_cache: Dict[str, Set[str]] = {}  # cache_key -> set of valid facet names
        self._cache_timestamps: Dict[str, float] = {}

    def _cache_key(self, user_email: Optional[str] = None) -> str:
        """Build cache key from user_email (or '_global' for anonymous)."""
        return user_email or "_global"

    def _is_cache_valid(self, key: str) -> bool:
        """Check if cache is still valid."""
        if key not in self._cache_timestamps:
            return False
        return time.time() - self._cache_timestamps[key] < self._cache_ttl

    async def _load_facets(
        self,
        api_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> Set[str]:
        """Load facets from backend and cache them."""
        key = self._cache_key(user_email)
        try:
            facets = await backend_client.get_facets(
                api_key=api_key,
                correlation_id=correlation_id,
                user_email=user_email,
            )

            # Extract facet names
            facet_names = {f.get("name") for f in facets if f.get("name")}

            # Update cache
            self._facet_cache[key] = facet_names
            self._cache_timestamps[key] = time.time()

            logger.debug(f"Loaded {len(facet_names)} facets for {key}")
            return facet_names

        except Exception as e:
            logger.warning(f"Failed to load facets: {e}")
            # Return empty set on error - this will cause validation to pass
            # to avoid blocking operations when metadata service is down
            return set()

    async def get_valid_facets(
        self,
        api_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> Set[str]:
        """Get set of valid facet names."""
        key = self._cache_key(user_email)
        # Check cache first
        if self._is_cache_valid(key):
            return self._facet_cache.get(key, set())

        # Load from backend
        return await self._load_facets(api_key, correlation_id, user_email=user_email)

    async def validate_facets(
        self,
        facet_filters: Dict[str, Any],
        api_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> tuple[bool, List[str]]:
        """
        Validate facet_filters against the metadata catalog.

        Args:
            facet_filters: Facet filter dictionary
            api_key: API key for backend authentication
            correlation_id: Request correlation ID
            user_email: End-user email for delegated auth

        Returns:
            Tuple of (is_valid, list_of_invalid_facets)
        """
        if not facet_filters:
            return True, []

        valid_facets = await self.get_valid_facets(api_key, correlation_id, user_email=user_email)

        # If we couldn't load facets, allow all (fail open for availability)
        if not valid_facets:
            logger.warning("No valid facets loaded, allowing all facets")
            return True, []

        invalid_facets = []
        for facet_name in facet_filters.keys():
            if facet_name not in valid_facets:
                invalid_facets.append(facet_name)

        if invalid_facets:
            logger.warning(f"Invalid facets: {invalid_facets}")
            return False, invalid_facets

        return True, []

    def clear_cache(self, user_email: Optional[str] = None):
        """Clear facet cache."""
        if user_email:
            key = self._cache_key(user_email)
            self._facet_cache.pop(key, None)
            self._cache_timestamps.pop(key, None)
        else:
            self._facet_cache.clear()
            self._cache_timestamps.clear()


# Global facet validator instance
facet_validator = FacetValidator()
