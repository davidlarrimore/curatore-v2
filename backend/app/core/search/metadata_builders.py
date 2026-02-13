# ============================================================================
# backend/app/services/metadata_builders.py
# ============================================================================
"""
Metadata Builder Registry for Curatore v2 - Standardized Namespaced Metadata

Provides a registry of metadata builders for all indexable source types.
Each builder produces namespaced JSONB metadata for the search_chunks table,
ensuring consistent structure across all source types.

Namespace convention:
    - "source"      -> common fields (storage_folder, uploaded_by)
    - "sharepoint"  -> SharePoint-specific fields
    - "sam"         -> SAM.gov notice/solicitation fields
    - "salesforce"  -> Salesforce CRM fields
    - "forecast"    -> Acquisition forecast fields
    - "custom"      -> LLM/function-generated metadata from AssetMetadata table

Adding a new source type:
    1. Subclass MetadataBuilder
    2. Implement build_content() and build_metadata()
    3. Register with metadata_builder_registry.register(MyBuilder())

Usage:
    from app.core.search.metadata_builders import metadata_builder_registry

    builder = metadata_builder_registry.get("sam_notice")
    content = builder.build_content(title="...", description="...")
    metadata = builder.build_metadata(sam_notice_id="...", ...)
"""

import logging
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("curatore.services.metadata_builders")


# =============================================================================
# BASE CLASS AND REGISTRY
# =============================================================================


@dataclass
class MetadataBuilder:
    """Base class for source-type metadata builders."""

    source_type: str    # e.g., "sam_notice", "asset_sharepoint", "salesforce_account"
    namespace: str      # primary namespace key in the metadata dict
    display_name: str   # human-readable label

    @abstractmethod
    def build_content(self, **kwargs) -> str:
        """Build the indexable content string from source fields."""

    @abstractmethod
    def build_metadata(self, **kwargs) -> Dict[str, Any]:
        """Build the namespaced metadata dict for search_chunks."""

    def build(self, **kwargs) -> Tuple[str, Dict[str, Any]]:
        """Build both content and metadata. Returns (content, metadata_dict)."""
        return self.build_content(**kwargs), self.build_metadata(**kwargs)

    def get_schema(self) -> Optional[Dict[str, List[str]]]:
        """Return {namespace: [field_names]} this builder writes, or None for dynamic builders."""
        return None


class MetadataBuilderRegistry:
    """Registry of metadata builders for all indexable source types."""

    def __init__(self):
        self._builders: Dict[str, MetadataBuilder] = {}

    def register(self, builder: MetadataBuilder):
        self._builders[builder.source_type] = builder

    def get(self, source_type: str) -> Optional[MetadataBuilder]:
        return self._builders.get(source_type)

    def list_builders(self) -> List[MetadataBuilder]:
        return list(self._builders.values())

    def build_metadata(self, source_type: str, **kwargs) -> Dict[str, Any]:
        builder = self._builders.get(source_type)
        if not builder:
            raise ValueError(f"No metadata builder for source_type: {source_type}")
        return builder.build_metadata(**kwargs)

    def build_content(self, source_type: str, **kwargs) -> str:
        builder = self._builders.get(source_type)
        if not builder:
            raise ValueError(f"No metadata builder for source_type: {source_type}")
        return builder.build_content(**kwargs)


# Singleton
metadata_builder_registry = MetadataBuilderRegistry()


# =============================================================================
# ASSET BUILDERS
# =============================================================================


class AssetPassthroughBuilder(MetadataBuilder):
    """
    Pass-through builder for all asset types.

    Since connectors now write namespaced source_metadata directly,
    asset builders simply return the source_metadata as-is for search indexing.
    """

    def __init__(self, source_type: str = "asset_default", display_name: str = "Asset"):
        super().__init__(
            source_type=source_type,
            namespace="source",
            display_name=display_name,
        )

    def build_content(self, *, extracted_markdown: str = "", **kwargs) -> str:
        return extracted_markdown

    def build_metadata(
        self,
        *,
        source_metadata: Optional[dict] = None,
        storage_folder: str = "",
        **kwargs,
    ) -> dict:
        """Return namespaced source_metadata directly. Ensures source.storage_folder is set."""
        sm = dict(source_metadata or {})
        # Ensure source namespace exists with storage_folder
        source = sm.get("source", {})
        if storage_folder and not source.get("storage_folder"):
            source["storage_folder"] = storage_folder
        if source:
            sm["source"] = source
        return sm


# =============================================================================
# SAM.GOV BUILDERS
# =============================================================================


class SamNoticeBuilder(MetadataBuilder):
    """Builder for SAM.gov notices."""

    def __init__(self):
        super().__init__(
            source_type="sam_notice",
            namespace="sam",
            display_name="SAM Notice",
        )

    def get_schema(self) -> Optional[Dict[str, List[str]]]:
        return {"sam": ["notice_id", "solicitation_id", "notice_type", "agency", "posted_date", "response_deadline"]}

    def build_content(
        self,
        *,
        title: str = "",
        description: str = "",
        **kwargs,
    ) -> str:
        return f"{title}\n\n{description}"

    def build_metadata(
        self,
        *,
        sam_notice_id: str = "",
        solicitation_id: Optional[str] = None,
        notice_type: str = "",
        agency: Optional[str] = None,
        posted_date: Optional[str] = None,
        response_deadline: Optional[str] = None,
        **kwargs,
    ) -> dict:
        return {
            "sam": {
                "notice_id": sam_notice_id,
                "solicitation_id": solicitation_id,
                "notice_type": notice_type,
                "agency": agency,
                "posted_date": posted_date,
                "response_deadline": response_deadline,
            },
        }


class SamSolicitationBuilder(MetadataBuilder):
    """Builder for SAM.gov solicitations."""

    def __init__(self):
        super().__init__(
            source_type="sam_solicitation",
            namespace="sam",
            display_name="SAM Solicitation",
        )

    def get_schema(self) -> Optional[Dict[str, List[str]]]:
        return {"sam": ["solicitation_number", "agency", "office", "naics_code", "set_aside", "posted_date", "response_deadline"]}

    def build_content(
        self,
        *,
        title: str = "",
        description: str = "",
        agency: Optional[str] = None,
        **kwargs,
    ) -> str:
        content = f"{title}\n\n{description}"
        if agency:
            content = f"{agency}\n{content}"
        return content

    def build_metadata(
        self,
        *,
        solicitation_number: str = "",
        agency: Optional[str] = None,
        office: Optional[str] = None,
        naics_code: Optional[str] = None,
        set_aside: Optional[str] = None,
        posted_date: Optional[str] = None,
        response_deadline: Optional[str] = None,
        **kwargs,
    ) -> dict:
        return {
            "sam": {
                "solicitation_number": solicitation_number,
                "agency": agency,
                "office": office,
                "naics_code": naics_code,
                "set_aside": set_aside,
                "posted_date": posted_date,
                "response_deadline": response_deadline,
            },
        }


# =============================================================================
# FORECAST BUILDERS
# =============================================================================


class ForecastBuilder(MetadataBuilder):
    """Builder for acquisition forecasts (AG, APFS, State)."""

    def __init__(self, source_type: str = "forecast", display_name: str = "Forecast"):
        super().__init__(
            source_type=source_type,
            namespace="forecast",
            display_name=display_name,
        )

    def get_schema(self) -> Optional[Dict[str, List[str]]]:
        return {"forecast": ["source_type", "source_id", "agency_name", "naics_codes", "set_aside_type", "fiscal_year", "estimated_award_quarter"]}

    def build_content(
        self,
        *,
        title: str = "",
        description: Optional[str] = None,
        agency_name: Optional[str] = None,
        naics_codes: Optional[list] = None,
        **kwargs,
    ) -> str:
        content_parts = [title]
        if description:
            content_parts.append(description)
        if agency_name:
            content_parts.append(agency_name)
        if naics_codes:
            for nc in naics_codes:
                if isinstance(nc, dict):
                    code = nc.get("code", "")
                    desc = nc.get("description", "")
                    if code:
                        content_parts.append(code)
                    if desc:
                        content_parts.append(desc)
        return "\n\n".join(content_parts)

    def build_metadata(
        self,
        *,
        source_type: str = "",
        source_id: str = "",
        agency_name: Optional[str] = None,
        naics_codes: Optional[list] = None,
        set_aside_type: Optional[str] = None,
        fiscal_year: Optional[int] = None,
        estimated_award_quarter: Optional[str] = None,
        **kwargs,
    ) -> dict:
        return {
            "forecast": {
                "source_type": source_type,
                "source_id": source_id,
                "agency_name": agency_name,
                "naics_codes": naics_codes,
                "set_aside_type": set_aside_type,
                "fiscal_year": fiscal_year,
                "estimated_award_quarter": estimated_award_quarter,
            },
        }


# =============================================================================
# SALESFORCE BUILDERS
# =============================================================================


class SalesforceAccountBuilder(MetadataBuilder):
    """Builder for Salesforce accounts."""

    def __init__(self):
        super().__init__(
            source_type="salesforce_account",
            namespace="salesforce",
            display_name="Salesforce Account",
        )

    def get_schema(self) -> Optional[Dict[str, List[str]]]:
        return {"salesforce": ["salesforce_id", "account_type", "industry", "website", "account_name"]}

    def build_content(
        self,
        *,
        name: str = "",
        account_type: Optional[str] = None,
        industry: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs,
    ) -> str:
        parts = [name]
        if account_type:
            parts.append(f"Type: {account_type}")
        if industry:
            parts.append(f"Industry: {industry}")
        if description:
            parts.append(description)
        return "\n\n".join(parts)

    def build_metadata(
        self,
        *,
        salesforce_id: str = "",
        account_type: Optional[str] = None,
        industry: Optional[str] = None,
        website: Optional[str] = None,
        account_name: Optional[str] = None,
        **kwargs,
    ) -> dict:
        return {
            "salesforce": {
                "salesforce_id": salesforce_id,
                "account_type": account_type,
                "industry": industry,
                "website": website,
                "account_name": account_name,
            },
        }


class SalesforceContactBuilder(MetadataBuilder):
    """Builder for Salesforce contacts."""

    def __init__(self):
        super().__init__(
            source_type="salesforce_contact",
            namespace="salesforce",
            display_name="Salesforce Contact",
        )

    def get_schema(self) -> Optional[Dict[str, List[str]]]:
        return {"salesforce": ["salesforce_id", "first_name", "last_name", "email", "title", "account_name"]}

    def build_content(
        self,
        *,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        title: Optional[str] = None,
        account_name: Optional[str] = None,
        department: Optional[str] = None,
        email: Optional[str] = None,
        **kwargs,
    ) -> str:
        full_name = f"{first_name or ''} {last_name or ''}".strip() or "Unknown Contact"
        parts = [full_name]
        if title:
            parts.append(f"Title: {title}")
        if account_name:
            parts.append(f"Account: {account_name}")
        if department:
            parts.append(f"Department: {department}")
        if email:
            parts.append(f"Email: {email}")
        return "\n\n".join(parts)

    def build_metadata(
        self,
        *,
        salesforce_id: str = "",
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        email: Optional[str] = None,
        title: Optional[str] = None,
        account_name: Optional[str] = None,
        **kwargs,
    ) -> dict:
        return {
            "salesforce": {
                "salesforce_id": salesforce_id,
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "title": title,
                "account_name": account_name,
            },
        }


class SalesforceOpportunityBuilder(MetadataBuilder):
    """Builder for Salesforce opportunities."""

    def __init__(self):
        super().__init__(
            source_type="salesforce_opportunity",
            namespace="salesforce",
            display_name="Salesforce Opportunity",
        )

    def get_schema(self) -> Optional[Dict[str, List[str]]]:
        return {"salesforce": ["salesforce_id", "stage_name", "amount", "opportunity_type", "account_name", "close_date"]}

    def build_content(
        self,
        *,
        name: str = "",
        account_name: Optional[str] = None,
        stage_name: Optional[str] = None,
        opportunity_type: Optional[str] = None,
        amount: Optional[float] = None,
        description: Optional[str] = None,
        **kwargs,
    ) -> str:
        parts = [name]
        if account_name:
            parts.append(f"Account: {account_name}")
        if stage_name:
            parts.append(f"Stage: {stage_name}")
        if opportunity_type:
            parts.append(f"Type: {opportunity_type}")
        if amount:
            parts.append(f"Amount: ${amount:,.2f}")
        if description:
            parts.append(description)
        return "\n\n".join(parts)

    def build_metadata(
        self,
        *,
        salesforce_id: str = "",
        stage_name: Optional[str] = None,
        amount: Optional[float] = None,
        opportunity_type: Optional[str] = None,
        account_name: Optional[str] = None,
        close_date: Optional[str] = None,
        **kwargs,
    ) -> dict:
        return {
            "salesforce": {
                "salesforce_id": salesforce_id,
                "stage_name": stage_name,
                "amount": amount,
                "opportunity_type": opportunity_type,
                "account_name": account_name,
                "close_date": close_date,
            },
        }


# =============================================================================
# REGISTRATION
# =============================================================================


def _register_defaults():
    """Register all built-in metadata builders."""
    # Asset builders: pass-through (source_metadata is already namespaced by connectors)
    metadata_builder_registry.register(AssetPassthroughBuilder("asset_sharepoint", "SharePoint Asset"))
    metadata_builder_registry.register(AssetPassthroughBuilder("asset_upload", "Uploaded Asset"))
    metadata_builder_registry.register(AssetPassthroughBuilder("asset_web_scrape", "Web Scrape Asset"))
    metadata_builder_registry.register(AssetPassthroughBuilder("asset_web_scrape_document", "Web Scrape Document"))
    metadata_builder_registry.register(AssetPassthroughBuilder("asset_sam_gov", "SAM.gov Attachment"))
    metadata_builder_registry.register(AssetPassthroughBuilder("asset_default", "Asset"))
    metadata_builder_registry.register(AssetPassthroughBuilder("asset", "Asset"))
    # Entity builders: still produce namespaced metadata from typed model columns
    metadata_builder_registry.register(SamNoticeBuilder())
    metadata_builder_registry.register(SamSolicitationBuilder())
    metadata_builder_registry.register(ForecastBuilder("ag_forecast", "GSA AG Forecast"))
    metadata_builder_registry.register(ForecastBuilder("apfs_forecast", "DHS APFS Forecast"))
    metadata_builder_registry.register(ForecastBuilder("state_forecast", "State Dept Forecast"))
    metadata_builder_registry.register(SalesforceAccountBuilder())
    metadata_builder_registry.register(SalesforceContactBuilder())
    metadata_builder_registry.register(SalesforceOpportunityBuilder())


_register_defaults()
