"""
Versioned models for API v1 — re-export shim.

All models have been moved to namespace-specific schema files:
- admin/schemas.py: auth, user, org, connection models
- data/schemas.py: asset, search, SAM, salesforce, forecast, scrape, metadata models
- ops/schemas.py: run, queue, job models
- cwr/schemas.py: function, procedure, pipeline models

This file re-exports everything for backward compatibility during migration.
It will be deleted once all routers are updated to import from their namespace schemas.
"""

# Re-export everything from namespace schemas
from app.api.v1.admin.schemas import *  # noqa: F401,F403
from app.api.v1.data.schemas import *  # noqa: F401,F403
from app.api.v1.ops.schemas import *  # noqa: F401,F403
from app.api.v1.cwr.schemas import *  # noqa: F401,F403
