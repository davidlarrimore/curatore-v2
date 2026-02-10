"""
Facet Reference Service — canonical values and alias resolution for facet dimensions.

Provides cross-source naming resolution so that searching for "DHS" automatically
expands to match "HOMELAND SECURITY, DEPARTMENT OF" (SAM.gov),
"Department of Homeland Security" (forecasts), and all other variants.

Singleton: ``facet_reference_service``

Key methods:
    resolve_aliases  — search hot-path: value → all matching aliases
    check_and_resolve_value — index-time: resolve + detect unmapped values
    autocomplete — prefix search across canonical values, labels, and aliases
    load_baseline — YAML → DB seeding (idempotent)
    discover_unmapped — find values in search_chunks not yet in reference data
    suggest_groupings — LLM-powered grouping of unmapped values
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import yaml
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Cache TTL in seconds
_CACHE_TTL = 300  # 5 minutes


class FacetReferenceService:
    """Manages canonical facet reference values and aliases."""

    def __init__(self) -> None:
        self._yaml_data: Dict[str, Any] = {}
        self._yaml_loaded = False

        # In-memory reverse index: (org_id_str, facet_name) → {alias_lower: [all_aliases_for_canonical]}
        self._cache: Dict[Tuple[str, str], Dict[str, List[str]]] = {}
        self._cache_ts: Dict[Tuple[str, str], float] = {}

    # =========================================================================
    # YAML Loading
    # =========================================================================

    def _ensure_yaml_loaded(self) -> None:
        if self._yaml_loaded:
            return
        yaml_path = Path(__file__).parent / "registry" / "reference_data.yaml"
        if yaml_path.exists():
            with open(yaml_path) as f:
                data = yaml.safe_load(f) or {}
            self._yaml_data = data.get("reference_data", {})
        else:
            self._yaml_data = {}
        self._yaml_loaded = True

    # =========================================================================
    # DB Seeding (idempotent)
    # =========================================================================

    async def load_baseline(self, session: AsyncSession) -> Dict[str, int]:
        """
        Load YAML reference data baseline into DB (idempotent).

        Seeds global records (organization_id=NULL). Skips if baseline
        already exists for a given facet.

        Returns dict with counts of seeded records.
        """
        self._ensure_yaml_loaded()

        from ..database.models import FacetReferenceAlias, FacetReferenceValue

        counts = {"values": 0, "aliases": 0}

        for facet_name, entries in self._yaml_data.items():
            # Check if baseline already seeded for this facet
            existing = await session.execute(
                select(FacetReferenceValue.id).where(
                    and_(
                        FacetReferenceValue.organization_id.is_(None),
                        FacetReferenceValue.facet_name == facet_name,
                    )
                ).limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                logger.debug(f"Reference data baseline already seeded for facet '{facet_name}', skipping")
                continue

            for idx, entry in enumerate(entries or []):
                canonical = entry.get("canonical")
                if not canonical:
                    continue

                ref_val = FacetReferenceValue(
                    organization_id=None,
                    facet_name=facet_name,
                    canonical_value=canonical,
                    display_label=entry.get("display_label"),
                    description=entry.get("description"),
                    sort_order=idx,
                    status="active",
                )
                session.add(ref_val)
                await session.flush()
                counts["values"] += 1

                # Always add the canonical value itself as an alias
                canon_alias = FacetReferenceAlias(
                    reference_value_id=ref_val.id,
                    alias_value=canonical,
                    alias_value_lower=canonical.lower(),
                    match_method="baseline",
                    status="active",
                )
                session.add(canon_alias)
                counts["aliases"] += 1

                for alias_entry in entry.get("aliases", []):
                    alias_val = alias_entry if isinstance(alias_entry, str) else alias_entry.get("value")
                    if not alias_val:
                        continue
                    source_hint = alias_entry.get("source_hint") if isinstance(alias_entry, dict) else None

                    # Skip if same as canonical (already added)
                    if alias_val.lower() == canonical.lower():
                        continue

                    alias_rec = FacetReferenceAlias(
                        reference_value_id=ref_val.id,
                        alias_value=alias_val,
                        alias_value_lower=alias_val.lower(),
                        source_hint=source_hint,
                        match_method="baseline",
                        status="active",
                    )
                    session.add(alias_rec)
                    counts["aliases"] += 1

            await session.flush()

        if counts["values"] > 0:
            logger.info(f"Seeded facet reference baseline: {counts}")
        return counts

    # =========================================================================
    # Cache Management
    # =========================================================================

    def _cache_key(self, org_id: Optional[UUID], facet_name: str) -> Tuple[str, str]:
        return (str(org_id) if org_id else "global", facet_name)

    def _cache_valid(self, key: Tuple[str, str]) -> bool:
        ts = self._cache_ts.get(key, 0)
        return (time.time() - ts) < _CACHE_TTL

    async def _build_cache(
        self, session: AsyncSession, org_id: Optional[UUID], facet_name: str
    ) -> Dict[str, List[str]]:
        """
        Build the reverse index for a facet: {alias_lower: [all aliases for same canonical]}.
        Merges global baseline + org-specific overrides.
        """
        from ..database.models import FacetReferenceAlias, FacetReferenceValue

        # Fetch all active canonical values for this facet (global + org)
        org_filter = or_(
            FacetReferenceValue.organization_id.is_(None),
            FacetReferenceValue.organization_id == org_id,
        ) if org_id else FacetReferenceValue.organization_id.is_(None)

        result = await session.execute(
            select(FacetReferenceValue)
            .where(
                and_(
                    FacetReferenceValue.facet_name == facet_name,
                    FacetReferenceValue.status == "active",
                    org_filter,
                )
            )
            .order_by(FacetReferenceValue.sort_order)
        )
        ref_values = result.scalars().all()

        if not ref_values:
            return {}

        ref_ids = [rv.id for rv in ref_values]

        # Fetch all active aliases for these canonical values
        alias_result = await session.execute(
            select(FacetReferenceAlias).where(
                and_(
                    FacetReferenceAlias.reference_value_id.in_(ref_ids),
                    FacetReferenceAlias.status == "active",
                )
            )
        )
        all_aliases = alias_result.scalars().all()

        # Group aliases by canonical value
        canonical_aliases: Dict[str, List[str]] = {}  # ref_id_str -> [alias_value, ...]
        for alias in all_aliases:
            rid = str(alias.reference_value_id)
            canonical_aliases.setdefault(rid, []).append(alias.alias_value)

        # Build reverse index: each alias_lower -> all aliases of the same canonical
        reverse_index: Dict[str, List[str]] = {}
        for rv in ref_values:
            rid = str(rv.id)
            all_vals = canonical_aliases.get(rid, [])
            for alias in all_vals:
                reverse_index[alias.lower()] = all_vals

        key = self._cache_key(org_id, facet_name)
        self._cache[key] = reverse_index
        self._cache_ts[key] = time.time()

        return reverse_index

    async def _get_reverse_index(
        self, session: AsyncSession, org_id: Optional[UUID], facet_name: str
    ) -> Dict[str, List[str]]:
        key = self._cache_key(org_id, facet_name)
        if key in self._cache and self._cache_valid(key):
            return self._cache[key]
        return await self._build_cache(session, org_id, facet_name)

    def invalidate_cache(self, org_id: Optional[UUID] = None) -> None:
        """Clear cached reference data."""
        if org_id is None:
            self._cache.clear()
            self._cache_ts.clear()
        else:
            keys_to_remove = [k for k in self._cache if k[0] == str(org_id) or k[0] == "global"]
            for k in keys_to_remove:
                self._cache.pop(k, None)
                self._cache_ts.pop(k, None)

    # =========================================================================
    # Resolve Aliases (Search Hot Path)
    # =========================================================================

    async def resolve_aliases(
        self,
        session: AsyncSession,
        org_id: Optional[UUID],
        facet_name: str,
        value: str,
    ) -> List[str]:
        """
        Resolve a facet value to all known aliases for the same canonical entity.

        Search hot path: "DHS" → ["Department of Homeland Security",
        "HOMELAND SECURITY, DEPARTMENT OF", "DHS", ...]

        Returns [value] unchanged if no reference data match exists.
        """
        index = await self._get_reverse_index(session, org_id, facet_name)
        if not index:
            return [value]

        aliases = index.get(value.lower())
        if aliases:
            return aliases

        return [value]

    # =========================================================================
    # Check and Resolve (Index-time Path)
    # =========================================================================

    async def check_and_resolve_value(
        self,
        session: AsyncSession,
        org_id: Optional[UUID],
        facet_name: str,
        value: str,
    ) -> Tuple[List[str], bool]:
        """
        Index-time resolution: resolve + detect if value is unmapped.

        Returns (aliases, is_mapped):
            - is_mapped=True: value found in reference data
            - is_mapped=False: value not found, may need auto-detection
        """
        index = await self._get_reverse_index(session, org_id, facet_name)
        if not index:
            return [value], True  # No reference data for this facet → treat as mapped

        aliases = index.get(value.lower())
        if aliases:
            return aliases, True

        return [value], False

    async def try_fuzzy_match(
        self,
        session: AsyncSession,
        org_id: Optional[UUID],
        facet_name: str,
        value: str,
        threshold: float = 0.90,
    ) -> Optional[Dict[str, Any]]:
        """
        Attempt fuzzy matching against cached aliases.

        Returns match info dict if a high-confidence match is found, else None.
        Uses rapidfuzz if available, falls back to difflib.
        """
        index = await self._get_reverse_index(session, org_id, facet_name)
        if not index:
            return None

        value_lower = value.lower()

        # Try rapidfuzz first (faster), fall back to difflib
        try:
            from rapidfuzz import fuzz
            best_score = 0.0
            best_key = None
            for alias_lower in index:
                score = fuzz.ratio(value_lower, alias_lower) / 100.0
                if score > best_score:
                    best_score = score
                    best_key = alias_lower
        except ImportError:
            from difflib import SequenceMatcher
            best_score = 0.0
            best_key = None
            for alias_lower in index:
                score = SequenceMatcher(None, value_lower, alias_lower).ratio()
                if score > best_score:
                    best_score = score
                    best_key = alias_lower

        if best_key and best_score >= threshold:
            return {
                "matched_alias": best_key,
                "confidence": best_score,
                "all_aliases": index[best_key],
            }

        return None

    async def auto_add_alias(
        self,
        session: AsyncSession,
        org_id: Optional[UUID],
        facet_name: str,
        value: str,
        matched_alias_lower: str,
        confidence: float,
        match_method: str = "auto_matched",
    ) -> bool:
        """
        Add a new alias to the canonical value that matched_alias belongs to.

        Returns True if alias was added, False if it already exists.
        """
        from ..database.models import FacetReferenceAlias, FacetReferenceValue

        # Find the reference value that owns the matched alias
        result = await session.execute(
            select(FacetReferenceAlias.reference_value_id).where(
                FacetReferenceAlias.alias_value_lower == matched_alias_lower
            ).limit(1)
        )
        ref_id = result.scalar_one_or_none()
        if not ref_id:
            return False

        # Check if alias already exists
        existing = await session.execute(
            select(FacetReferenceAlias.id).where(
                and_(
                    FacetReferenceAlias.reference_value_id == ref_id,
                    FacetReferenceAlias.alias_value_lower == value.lower(),
                )
            ).limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            return False

        alias = FacetReferenceAlias(
            reference_value_id=ref_id,
            alias_value=value,
            alias_value_lower=value.lower(),
            match_method=match_method,
            confidence=confidence,
            status="active" if match_method == "auto_matched" else "suggested",
        )
        session.add(alias)
        await session.flush()

        # Invalidate cache so new alias is picked up
        self.invalidate_cache(org_id)
        return True

    # =========================================================================
    # Autocomplete
    # =========================================================================

    async def autocomplete(
        self,
        session: AsyncSession,
        org_id: Optional[UUID],
        facet_name: str,
        prefix: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Case-insensitive prefix search across canonical values, display labels, and aliases.

        Uses a single JOIN query to avoid multiple round-trips.

        Returns list of {canonical_value, display_label, facet_name, matched_on}.
        """
        from ..database.models import FacetReferenceAlias, FacetReferenceValue

        prefix_lower = prefix.lower()

        org_filter = or_(
            FacetReferenceValue.organization_id.is_(None),
            FacetReferenceValue.organization_id == org_id,
        ) if org_id else FacetReferenceValue.organization_id.is_(None)

        # Single query: LEFT JOIN aliases, match on canonical/display_label/alias
        rows = await session.execute(
            select(
                FacetReferenceValue.id,
                FacetReferenceValue.canonical_value,
                FacetReferenceValue.display_label,
                FacetReferenceValue.facet_name,
                FacetReferenceValue.sort_order,
                FacetReferenceAlias.alias_value,
                FacetReferenceAlias.alias_value_lower,
            ).outerjoin(
                FacetReferenceAlias,
                and_(
                    FacetReferenceAlias.reference_value_id == FacetReferenceValue.id,
                    FacetReferenceAlias.status == "active",
                    FacetReferenceAlias.alias_value_lower.like(f"{prefix_lower}%"),
                ),
            ).where(
                and_(
                    FacetReferenceValue.facet_name == facet_name,
                    FacetReferenceValue.status == "active",
                    org_filter,
                    or_(
                        func.lower(FacetReferenceValue.canonical_value).like(f"{prefix_lower}%"),
                        func.lower(FacetReferenceValue.display_label).like(f"{prefix_lower}%"),
                        FacetReferenceAlias.alias_value_lower.like(f"{prefix_lower}%"),
                    ),
                )
            )
            .order_by(FacetReferenceValue.sort_order)
            .limit(limit * 3)  # Over-fetch since JOIN may produce duplicates
        )

        results = []
        seen_ids = set()

        for row in rows:
            rv_id, canonical, display_label, fn, sort_order, alias_val, alias_lower = row
            if rv_id in seen_ids:
                continue
            seen_ids.add(rv_id)

            # Determine what matched
            if display_label and display_label.lower().startswith(prefix_lower):
                matched_on = "display_label"
            elif canonical.lower().startswith(prefix_lower):
                matched_on = "canonical_value"
            elif alias_val:
                matched_on = f"alias:{alias_val}"
            else:
                matched_on = "canonical_value"

            results.append({
                "id": str(rv_id),
                "canonical_value": canonical,
                "display_label": display_label,
                "facet_name": fn,
                "matched_on": matched_on,
            })

            if len(results) >= limit:
                break

        return results

    # =========================================================================
    # Discovery and AI Suggestion
    # =========================================================================

    async def discover_unmapped(
        self,
        session: AsyncSession,
        org_id: Optional[UUID],
        facet_name: str,
    ) -> List[Dict[str, Any]]:
        """
        Find distinct facet values in search_chunks that are not yet mapped
        in reference data.

        Uses a single UNION ALL query across all content type mappings
        instead of N separate queries.

        Returns list of {value, count} sorted by count descending.
        """
        from .registry_service import metadata_registry_service

        mappings = metadata_registry_service.resolve_facet(facet_name)
        if not mappings:
            return []

        # Get all currently mapped alias values (lowercased)
        index = await self._get_reverse_index(session, org_id, facet_name)
        known_lower = set(index.keys()) if index else set()

        # Build a single UNION ALL query across all mappings
        org_clause = "AND organization_id = CAST(:org_id AS UUID)" if org_id else ""
        union_parts = []
        for content_type, json_path in mappings.items():
            parts = json_path.split(".", 1)
            if len(parts) != 2:
                continue
            ns, field = parts
            union_parts.append(
                f"SELECT metadata->'{ns}'->>'{field}' AS val "
                f"FROM search_chunks "
                f"WHERE metadata->'{ns}'->>'{field}' IS NOT NULL {org_clause}"
            )

        if not union_parts:
            return []

        combined_sql = text(f"""
            SELECT val, COUNT(*) AS cnt
            FROM ({' UNION ALL '.join(union_parts)}) sub
            GROUP BY val
            ORDER BY cnt DESC
            LIMIT 500
        """)
        params: Dict[str, Any] = {}
        if org_id:
            params["org_id"] = str(org_id)

        result = await session.execute(combined_sql, params)

        unmapped: List[Dict[str, Any]] = []
        for row in result:
            val = row[0]
            cnt = row[1]
            if val and val.lower() not in known_lower:
                unmapped.append({"value": val, "count": cnt})

        return unmapped

    async def suggest_groupings(
        self,
        session: AsyncSession,
        org_id: Optional[UUID],
        facet_name: str,
    ) -> Dict[str, Any]:
        """
        AI-powered suggestion: discover unmapped values, cluster them,
        and ask LLM to group into canonical entries.

        Returns dict with "suggestions" list and optional "error" string.
        """
        unmapped = await self.discover_unmapped(session, org_id, facet_name)
        if not unmapped:
            return {"suggestions": []}

        unmapped_values = [item["value"] for item in unmapped[:100]]  # Cap to avoid huge prompts

        # Pre-cluster with fuzzy matching to reduce LLM input
        clusters: List[List[str]] = []
        remaining = list(unmapped_values)

        try:
            from rapidfuzz import fuzz

            while remaining:
                seed = remaining.pop(0)
                cluster = [seed]
                still_remaining = []
                for val in remaining:
                    if fuzz.ratio(seed.lower(), val.lower()) > 70:
                        cluster.append(val)
                    else:
                        still_remaining.append(val)
                remaining = still_remaining
                clusters.append(cluster)
        except ImportError:
            # No rapidfuzz, send all values directly
            clusters = [[v] for v in remaining]

        # Build LLM prompt
        value_list = "\n".join(
            f"- {', '.join(c)}" if len(c) > 1 else f"- {c[0]}"
            for c in clusters
        )

        # Get existing canonical values for context
        from ..database.models import FacetReferenceValue

        org_filter = or_(
            FacetReferenceValue.organization_id.is_(None),
            FacetReferenceValue.organization_id == org_id,
        ) if org_id else FacetReferenceValue.organization_id.is_(None)

        existing_q = await session.execute(
            select(FacetReferenceValue.canonical_value, FacetReferenceValue.display_label).where(
                and_(
                    FacetReferenceValue.facet_name == facet_name,
                    FacetReferenceValue.status == "active",
                    org_filter,
                )
            )
        )
        existing_vals = [
            f"{row[0]} ({row[1]})" if row[1] else row[0]
            for row in existing_q
        ]

        prompt = f"""You are a data normalization expert. Group these raw values for the
"{facet_name}" dimension into canonical entries. Each group = same real-world entity.

EXISTING canonical values (do NOT duplicate these, but you may suggest new aliases for them):
{chr(10).join(f'- {v}' for v in existing_vals) if existing_vals else '(none)'}

UNMAPPED values to classify:
{value_list}

Return ONLY valid JSON array:
[{{
  "canonical_value": "Most formal/complete form",
  "display_label": "Common abbreviation",
  "confidence": 0.95,
  "aliases": ["variant1", "variant2"],
  "existing_canonical_match": null or "matching existing canonical if this is a new alias for an existing entry"
}}]

Rules:
- canonical_value = most formal/complete form
- display_label = common abbreviation (or null if not applicable)
- Only group values clearly referring to the same entity
- confidence: 0.0-1.0 based on how certain you are
- If a value matches an existing canonical, set existing_canonical_match to that canonical_value and put the new values in aliases
- Return empty array [] if no groupings can be made"""

        # Call LLM
        try:
            from ..llm.llm_service import llm_service

            if not llm_service.is_available:
                logger.warning("LLM service not available for facet suggestion")
                return {"suggestions": [], "error": "LLM service not available"}

            response = await llm_service.generate(
                prompt=prompt,
                system_prompt="You are a data normalization expert. Return only valid JSON.",
                temperature=0.1,
                max_tokens=4000,
            )

            if response.get("error"):
                return {"suggestions": [], "error": response["error"]}

            import json
            # Extract JSON from response
            response_text = response.get("content", "") if isinstance(response, dict) else str(response)
            # Try to find JSON array in response
            start = response_text.find("[")
            end = response_text.rfind("]") + 1
            if start >= 0 and end > start:
                suggestions = json.loads(response_text[start:end])
            else:
                logger.warning("No JSON array found in LLM response")
                return {"suggestions": [], "error": "LLM returned invalid response format"}

        except Exception as e:
            logger.error(f"LLM suggestion failed for facet '{facet_name}': {e}")
            return {"suggestions": [], "error": f"LLM suggestion failed: {str(e)}"}

        # Store suggestions in DB
        from ..database.models import FacetReferenceAlias, FacetReferenceValue

        stored = []
        for suggestion in suggestions:
            canonical = suggestion.get("canonical_value")
            if not canonical:
                continue

            existing_match = suggestion.get("existing_canonical_match")
            confidence = suggestion.get("confidence", 0.5)

            if existing_match:
                # Add aliases to existing canonical value
                existing_rv = await session.execute(
                    select(FacetReferenceValue).where(
                        and_(
                            FacetReferenceValue.facet_name == facet_name,
                            FacetReferenceValue.canonical_value == existing_match,
                            FacetReferenceValue.status == "active",
                            org_filter,
                        )
                    ).limit(1)
                )
                rv = existing_rv.scalars().first()
                if rv:
                    for alias_val in suggestion.get("aliases", []):
                        await self.auto_add_alias(
                            session, org_id, facet_name, alias_val,
                            existing_match.lower(), confidence,
                            match_method="ai_suggested",
                        )
                    stored.append(suggestion)
                continue

            # Check if this canonical already exists (from a previous run)
            existing_canon = await session.execute(
                select(FacetReferenceValue).where(
                    and_(
                        FacetReferenceValue.facet_name == facet_name,
                        func.lower(FacetReferenceValue.canonical_value) == canonical.lower(),
                        org_filter,
                    )
                ).limit(1)
            )
            if existing_canon.scalars().first() is not None:
                logger.debug(f"Skipping duplicate suggested canonical '{canonical}' for facet '{facet_name}'")
                continue

            # Use savepoint so a single failure doesn't corrupt the whole batch
            try:
                async with session.begin_nested():
                    # Create new suggested canonical
                    ref_val = FacetReferenceValue(
                        organization_id=org_id,
                        facet_name=facet_name,
                        canonical_value=canonical,
                        display_label=suggestion.get("display_label"),
                        status="suggested",
                    )
                    session.add(ref_val)
                    await session.flush()

                    # Add canonical as alias
                    canon_alias = FacetReferenceAlias(
                        reference_value_id=ref_val.id,
                        alias_value=canonical,
                        alias_value_lower=canonical.lower(),
                        match_method="ai_suggested",
                        confidence=confidence,
                        status="suggested",
                    )
                    session.add(canon_alias)

                    # De-duplicate aliases by lowercased value
                    seen_lower = {canonical.lower()}
                    for alias_val in suggestion.get("aliases", []):
                        alias_lower = alias_val.lower()
                        if alias_lower in seen_lower:
                            continue
                        seen_lower.add(alias_lower)
                        alias_rec = FacetReferenceAlias(
                            reference_value_id=ref_val.id,
                            alias_value=alias_val,
                            alias_value_lower=alias_lower,
                            match_method="ai_suggested",
                            confidence=confidence,
                            status="suggested",
                        )
                        session.add(alias_rec)

                    await session.flush()
                stored.append(suggestion)

            except Exception as e:
                logger.warning(f"Failed to store suggestion '{canonical}': {e}")
                continue

        self.invalidate_cache(org_id)
        return {"suggestions": stored}

    async def classify_single_value(
        self,
        session: AsyncSession,
        org_id: Optional[UUID],
        facet_name: str,
        value: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Ask LLM to classify a single unmapped value against existing canonicals.

        Used in the slow path of on-ingest auto-detection.
        Returns {"match": "canonical_value" or None, "confidence": float}.
        """
        from ..database.models import FacetReferenceValue

        org_filter = or_(
            FacetReferenceValue.organization_id.is_(None),
            FacetReferenceValue.organization_id == org_id,
        ) if org_id else FacetReferenceValue.organization_id.is_(None)

        existing_q = await session.execute(
            select(FacetReferenceValue.canonical_value).where(
                and_(
                    FacetReferenceValue.facet_name == facet_name,
                    FacetReferenceValue.status == "active",
                    org_filter,
                )
            )
        )
        existing_vals = [row[0] for row in existing_q]

        if not existing_vals:
            return None

        prompt = f"""Given existing canonical values for "{facet_name}":
{chr(10).join(f'- {v}' for v in existing_vals)}

Is "{value}" a variant of an existing value, or a new entity?
Return ONLY valid JSON: {{"match": "canonical_value_or_null", "confidence": 0.9}}"""

        try:
            from ..llm.llm_service import llm_service

            if not llm_service.is_available:
                return None

            response = await llm_service.generate(
                prompt=prompt,
                system_prompt="Return only valid JSON.",
                temperature=0.0,
                max_tokens=200,
            )

            import json
            response_text = response.get("content", "") if isinstance(response, dict) else str(response)
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response_text[start:end])

        except Exception as e:
            logger.error(f"LLM single-value classification failed: {e}")

        return None

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    async def list_values(
        self,
        session: AsyncSession,
        org_id: Optional[UUID],
        facet_name: str,
        include_suggested: bool = False,
        include_aliases: bool = True,
    ) -> List[Dict[str, Any]]:
        """List canonical values for a facet with their aliases."""
        from ..database.models import FacetReferenceAlias, FacetReferenceValue

        org_filter = or_(
            FacetReferenceValue.organization_id.is_(None),
            FacetReferenceValue.organization_id == org_id,
        ) if org_id else FacetReferenceValue.organization_id.is_(None)

        status_filter = FacetReferenceValue.status.in_(["active", "suggested"]) if include_suggested else FacetReferenceValue.status == "active"

        result = await session.execute(
            select(FacetReferenceValue).where(
                and_(
                    FacetReferenceValue.facet_name == facet_name,
                    status_filter,
                    org_filter,
                )
            ).order_by(FacetReferenceValue.sort_order, FacetReferenceValue.canonical_value)
        )
        ref_values = result.scalars().all()

        if not ref_values:
            return []

        # Batch-fetch all aliases in ONE query instead of N+1
        ref_ids = [rv.id for rv in ref_values]
        aliases_by_ref: Dict[str, List[Dict[str, Any]]] = {str(rid): [] for rid in ref_ids}

        if include_aliases:
            alias_result = await session.execute(
                select(FacetReferenceAlias).where(
                    FacetReferenceAlias.reference_value_id.in_(ref_ids)
                ).order_by(FacetReferenceAlias.alias_value)
            )
            for a in alias_result.scalars().all():
                aliases_by_ref[str(a.reference_value_id)].append({
                    "id": str(a.id),
                    "alias_value": a.alias_value,
                    "source_hint": a.source_hint,
                    "match_method": a.match_method,
                    "confidence": a.confidence,
                    "status": a.status,
                })

        values = []
        for rv in ref_values:
            entry: Dict[str, Any] = {
                "id": str(rv.id),
                "facet_name": rv.facet_name,
                "canonical_value": rv.canonical_value,
                "display_label": rv.display_label,
                "description": rv.description,
                "sort_order": rv.sort_order,
                "status": rv.status,
            }
            if include_aliases:
                entry["aliases"] = aliases_by_ref.get(str(rv.id), [])
            values.append(entry)

        return values

    async def create_canonical(
        self,
        session: AsyncSession,
        org_id: Optional[UUID],
        facet_name: str,
        canonical_value: str,
        display_label: Optional[str] = None,
        description: Optional[str] = None,
        aliases: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a new canonical reference value."""
        from ..database.models import FacetReferenceAlias, FacetReferenceValue

        ref_val = FacetReferenceValue(
            organization_id=org_id,
            facet_name=facet_name,
            canonical_value=canonical_value,
            display_label=display_label,
            description=description,
            status="active",
        )
        session.add(ref_val)
        await session.flush()

        # Add canonical itself as alias
        canon_alias = FacetReferenceAlias(
            reference_value_id=ref_val.id,
            alias_value=canonical_value,
            alias_value_lower=canonical_value.lower(),
            match_method="manual",
            status="active",
        )
        session.add(canon_alias)

        if aliases:
            for alias_val in aliases:
                if alias_val.lower() == canonical_value.lower():
                    continue
                alias_rec = FacetReferenceAlias(
                    reference_value_id=ref_val.id,
                    alias_value=alias_val,
                    alias_value_lower=alias_val.lower(),
                    match_method="manual",
                    status="active",
                )
                session.add(alias_rec)

        await session.flush()
        self.invalidate_cache(org_id)

        return {
            "id": str(ref_val.id),
            "facet_name": facet_name,
            "canonical_value": canonical_value,
            "display_label": display_label,
            "status": "active",
        }

    async def add_alias(
        self,
        session: AsyncSession,
        reference_value_id: UUID,
        alias_value: str,
        source_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add a manual alias to a canonical value."""
        from ..database.models import FacetReferenceAlias

        # Check for existing alias with same lowercased value
        existing = await session.execute(
            select(FacetReferenceAlias).where(
                and_(
                    FacetReferenceAlias.reference_value_id == reference_value_id,
                    FacetReferenceAlias.alias_value_lower == alias_value.lower(),
                )
            ).limit(1)
        )
        existing_alias = existing.scalars().first()
        if existing_alias:
            # If it exists but inactive/suggested, reactivate it
            if existing_alias.status != "active":
                existing_alias.status = "active"
                existing_alias.source_hint = source_hint or existing_alias.source_hint
                await session.flush()
                self.invalidate_cache()
            return {
                "id": str(existing_alias.id),
                "alias_value": existing_alias.alias_value,
                "source_hint": existing_alias.source_hint,
                "status": existing_alias.status,
            }

        alias_rec = FacetReferenceAlias(
            reference_value_id=reference_value_id,
            alias_value=alias_value,
            alias_value_lower=alias_value.lower(),
            source_hint=source_hint,
            match_method="manual",
            status="active",
        )
        session.add(alias_rec)
        await session.flush()
        self.invalidate_cache()

        return {
            "id": str(alias_rec.id),
            "alias_value": alias_value,
            "source_hint": source_hint,
            "status": "active",
        }

    async def approve(
        self, session: AsyncSession, reference_value_id: UUID, org_id: Optional[UUID] = None,
    ) -> bool:
        """Approve a suggested canonical value (and all its aliases)."""
        from ..database.models import FacetReferenceAlias, FacetReferenceValue

        result = await session.execute(
            select(FacetReferenceValue).where(FacetReferenceValue.id == reference_value_id)
        )
        rv = result.scalars().first()
        if not rv:
            return False

        rv.status = "active"

        # Approve all its suggested aliases
        await session.execute(
            text("""
                UPDATE facet_reference_aliases
                SET status = 'active'
                WHERE reference_value_id = :ref_id AND status = 'suggested'
            """),
            {"ref_id": str(reference_value_id)},
        )

        await session.flush()
        self.invalidate_cache(org_id)
        return True

    async def reject(
        self, session: AsyncSession, reference_value_id: UUID, org_id: Optional[UUID] = None,
    ) -> bool:
        """Reject a suggested canonical value (sets to inactive)."""
        from ..database.models import FacetReferenceValue

        result = await session.execute(
            select(FacetReferenceValue).where(FacetReferenceValue.id == reference_value_id)
        )
        rv = result.scalars().first()
        if not rv:
            return False

        rv.status = "inactive"
        await session.flush()
        self.invalidate_cache(org_id)
        return True

    async def update_canonical(
        self,
        session: AsyncSession,
        reference_value_id: UUID,
        org_id: Optional[UUID] = None,
        canonical_value: Optional[str] = None,
        display_label: Optional[str] = None,
        description: Optional[str] = None,
        sort_order: Optional[int] = None,
        status: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update a canonical reference value."""
        from ..database.models import FacetReferenceValue

        result = await session.execute(
            select(FacetReferenceValue).where(FacetReferenceValue.id == reference_value_id)
        )
        rv = result.scalars().first()
        if not rv:
            return None

        if canonical_value is not None:
            rv.canonical_value = canonical_value
        if display_label is not None:
            rv.display_label = display_label
        if description is not None:
            rv.description = description
        if sort_order is not None:
            rv.sort_order = sort_order
        if status is not None:
            rv.status = status

        await session.flush()
        self.invalidate_cache(org_id)

        return {
            "id": str(rv.id),
            "facet_name": rv.facet_name,
            "canonical_value": rv.canonical_value,
            "display_label": rv.display_label,
            "status": rv.status,
        }

    async def delete_alias(
        self, session: AsyncSession, alias_id: UUID, org_id: Optional[UUID] = None,
    ) -> bool:
        """Remove an alias."""
        from ..database.models import FacetReferenceAlias

        result = await session.execute(
            select(FacetReferenceAlias).where(FacetReferenceAlias.id == alias_id)
        )
        alias = result.scalars().first()
        if not alias:
            return False

        await session.delete(alias)
        await session.flush()
        self.invalidate_cache(org_id)
        return True

    async def get_pending_suggestion_count(
        self, session: AsyncSession, org_id: Optional[UUID],
    ) -> Dict[str, int]:
        """Count pending suggestions per facet (for admin badge)."""
        from ..database.models import FacetReferenceValue

        org_filter = or_(
            FacetReferenceValue.organization_id.is_(None),
            FacetReferenceValue.organization_id == org_id,
        ) if org_id else FacetReferenceValue.organization_id.is_(None)

        result = await session.execute(
            select(
                FacetReferenceValue.facet_name,
                func.count(FacetReferenceValue.id),
            ).where(
                and_(
                    FacetReferenceValue.status == "suggested",
                    org_filter,
                )
            ).group_by(FacetReferenceValue.facet_name)
        )

        counts = {}
        total = 0
        for row in result:
            counts[row[0]] = row[1]
            total += row[1]

        return {"facets": counts, "total": total}

    # =========================================================================
    # Reference Data Summary (for AI context)
    # =========================================================================

    async def get_reference_summary(
        self, session: AsyncSession, org_id: Optional[UUID],
    ) -> Dict[str, List[str]]:
        """
        Get a compact summary of active reference data for AI prompts.

        Returns {facet_name: [display_labels or canonical values]}.
        """
        from ..database.models import FacetReferenceValue

        org_filter = or_(
            FacetReferenceValue.organization_id.is_(None),
            FacetReferenceValue.organization_id == org_id,
        ) if org_id else FacetReferenceValue.organization_id.is_(None)

        result = await session.execute(
            select(
                FacetReferenceValue.facet_name,
                FacetReferenceValue.canonical_value,
                FacetReferenceValue.display_label,
            ).where(
                and_(
                    FacetReferenceValue.status == "active",
                    org_filter,
                )
            ).order_by(FacetReferenceValue.facet_name, FacetReferenceValue.sort_order)
        )

        summary: Dict[str, List[str]] = {}
        for row in result:
            facet = row[0]
            label = row[2] if row[2] else row[1]
            summary.setdefault(facet, []).append(label)

        return summary


# Singleton
facet_reference_service = FacetReferenceService()
