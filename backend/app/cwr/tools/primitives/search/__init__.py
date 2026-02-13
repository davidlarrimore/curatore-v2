# backend/app/functions/search/__init__.py
"""
Search functions for the Curatore Functions Framework.

Provides functions for searching and retrieving content:
- get: Get a single content item by type and ID (returns ContentItem)
- get_asset: Get a single asset by ID (returns dict with content)
- get_content: Get text content for multiple assets
- search_assets: Full-text and semantic search for assets
- search_collection: Search within a specific named collection
- search_solicitations: Search SAM.gov solicitations
- search_notices: Search SAM.gov notices
- search_scraped_assets: Search web scraped content
- search_salesforce: Search Salesforce CRM records
- query_model: Query any database model directly
"""

from .get import GetFunction
from .get_asset import GetAssetFunction
from .get_content import GetContentFunction
from .populate_collection import PopulateCollectionFunction
from .query_model import QueryModelFunction
from .search_assets import SearchAssetsFunction
from .search_collection import SearchCollectionFunction
from .search_notices import SearchNoticesFunction
from .search_salesforce import SearchSalesforceFunction
from .search_scraped_assets import SearchScrapedAssetsFunction
from .search_solicitations import SearchSolicitationsFunction

__all__ = [
    "GetFunction",
    "GetAssetFunction",
    "GetContentFunction",
    "PopulateCollectionFunction",
    "SearchAssetsFunction",
    "SearchCollectionFunction",
    "SearchSolicitationsFunction",
    "SearchNoticesFunction",
    "SearchScrapedAssetsFunction",
    "SearchSalesforceFunction",
    "QueryModelFunction",
]
