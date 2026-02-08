# backend/app/cwr/procedures/compiler/context_builder.py
"""
Context Builder - Builds the v2 system prompt for AI procedure generation.

Replaces the v1 ~1190-line prose prompt with a structured, contract-pack-driven
prompt that instructs the LLM to emit Typed Plan JSON instead of raw YAML.

Sections:
1. Role + task (generate Typed Plan JSON)
2. Plan JSON Schema + reference syntax + examples
3. Tool Contract Pack as structured JSON
4. Search function selection decision tree
5. Efficiency patterns (thin -> materialize -> LLM)
6. Profile constraints
7. Data source context (SharePoint, SAM, Salesforce)
8. Metadata/facet catalog

Usage:
    from app.cwr.procedures.compiler.context_builder import ContextBuilder

    builder = ContextBuilder(contract_pack, profile)
    system_prompt = await builder.build_system_prompt(session, org_id)
"""

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.cwr.contracts.contract_pack import ToolContractPack
from app.cwr.governance.generation_profiles import GenerationProfile

logger = logging.getLogger("curatore.procedures.compiler.context_builder")


class ContextBuilder:
    """
    Builds the system prompt for the v2 AI procedure generator.

    The prompt instructs the LLM to emit a Typed Plan as JSON, using
    the contract pack to describe available tools.
    """

    def __init__(self, contract_pack: ToolContractPack, profile: GenerationProfile):
        self._pack = contract_pack
        self._profile = profile

    async def build_system_prompt(
        self,
        session: Optional[Any] = None,
        org_id: Optional[UUID] = None,
    ) -> str:
        """
        Build the complete v2 system prompt.

        Args:
            session: Optional database session for org-specific context
            org_id: Optional organization ID

        Returns:
            Complete system prompt string
        """
        sections = [
            self._build_role_section(),
            self._build_plan_schema_section(),
            self._build_tool_catalog_section(),
            self._build_search_decision_tree(),
            self._build_efficiency_patterns(),
            self._build_profile_constraints(),
        ]

        # Add org-specific context if session available
        if session and org_id:
            try:
                data_source_ctx = await self._build_data_source_context(session, org_id)
                if data_source_ctx:
                    sections.append(data_source_ctx)
            except Exception as e:
                logger.warning(f"Failed to build data source context: {e}")

            try:
                metadata_ctx = await self._build_metadata_context(session, org_id)
                if metadata_ctx:
                    sections.append(metadata_ctx)
            except Exception as e:
                logger.warning(f"Failed to build metadata context: {e}")

        sections.append(self._build_output_instructions())

        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Section 1: Role + Task
    # ------------------------------------------------------------------

    def _build_role_section(self) -> str:
        return """# ROLE

You are an expert Curatore procedure planner. Your task is to generate a **Typed Plan** as JSON that describes a procedure workflow.

The Typed Plan will be validated, compiled, and converted into a runnable Curatore procedure. You do NOT write YAML directly. You produce structured JSON that follows the schema below.

Key rules:
- Output ONLY valid JSON (no markdown fences, no commentary)
- Use the tools listed in the TOOL CATALOG section
- Reference previous step outputs and parameters using ref objects
- Follow the generation profile constraints"""

    # ------------------------------------------------------------------
    # Section 2: Plan JSON Schema
    # ------------------------------------------------------------------

    def _build_plan_schema_section(self) -> str:
        return """# TYPED PLAN JSON SCHEMA

```json
{
  "procedure": {
    "name": "Human-Readable Name",
    "description": "One-sentence description",
    "slug": "optional_slug_name",
    "tags": ["tag1", "tag2"]
  },
  "parameters": [
    {
      "name": "param_name",
      "type": "string",
      "description": "What this parameter is for",
      "required": false,
      "default": "default_value"
    }
  ],
  "steps": [
    {
      "name": "step_name",
      "tool": "tool_name",
      "description": "What this step does",
      "args": {
        "literal_arg": "static value",
        "ref_arg": {"ref": "steps.previous_step"},
        "ref_field": {"ref": "steps.previous_step.data"},
        "param_ref": {"ref": "params.param_name"},
        "template_arg": {"template": "{{ steps.data | length }} items found"}
      },
      "on_error": "fail",
      "condition": "steps.some_step",
      "foreach": {"ref": "steps.search_results"},
      "branches": {
        "each": [
          {"name": "sub_step", "tool": "generate", "args": {...}}
        ]
      }
    }
  ]
}
```

## Reference Syntax

Use ref objects to reference data from other parts of the plan:

- `{"ref": "steps.step_name"}` — Full output of a previous step
- `{"ref": "steps.step_name.field"}` — Specific field from step output
- `{"ref": "params.param_name"}` — A procedure parameter value

For complex expressions with filters or loops, use template objects:
- `{"template": "{{ steps.data | length }}"}` — Jinja2 expression
- `{"template": "{{ steps.data | md_to_html }}"}` — Markdown to HTML filter
- `{"template": "{{ steps.foreach_step | compact }}"}` — Filter nulls from foreach results
- `{"template": "{% for item in steps.results if item %}{{ item }}{% endfor %}"}` — Loop with null filtering

## Parameter Types

Valid types: `string`, `integer`, `boolean`, `array`, `object`, `number`

## on_error Policies

- `fail` (default) — Stop the procedure on error
- `skip` — Skip this step, continue to next
- `continue` — Continue despite error (log warning)

## Flow Control

For iteration and branching, use flow control tools with `branches`:

- **foreach**: Iterate over a list. Use `foreach` field + `branches.each`.
  Inside branches, `item` and `item_index` are available.
- **if_branch**: Conditional. Requires `branches.then`, optional `branches.else`.
  Use `condition` arg for the test expression.
- **switch_branch**: Multi-way. Named branches + optional `branches.default`.
- **parallel**: Concurrent. Requires at least 2 branches.

## Example Plan

```json
{
  "procedure": {
    "name": "Daily SAM.gov Digest",
    "description": "Search recent SAM.gov notices and email a summary",
    "tags": ["sam", "digest"]
  },
  "parameters": [
    {"name": "recipients", "type": "string", "description": "Email recipients", "required": false, "default": "team@example.com"},
    {"name": "max_notices", "type": "integer", "description": "Maximum notices", "required": false, "default": 50}
  ],
  "steps": [
    {
      "name": "search_notices",
      "tool": "search_notices",
      "description": "Find recent SAM.gov notices",
      "args": {
        "query": "*",
        "posted_within_days": 1,
        "limit": {"ref": "params.max_notices"}
      }
    },
    {
      "name": "summarize",
      "tool": "generate",
      "description": "Generate executive summary of notices",
      "args": {
        "prompt": {"template": "Summarize these {{ steps.search_notices | length }} SAM.gov notices:\\n\\n{{ steps.search_notices }}"},
        "max_tokens": 2000
      }
    },
    {
      "name": "send_digest",
      "tool": "send_email",
      "description": "Email the digest to recipients",
      "args": {
        "to": {"ref": "params.recipients"},
        "subject": {"template": "SAM.gov Daily Digest - {{ today() }}"},
        "body": {"ref": "steps.summarize"},
        "html": true
      }
    }
  ]
}
```"""

    # ------------------------------------------------------------------
    # Section 3: Tool Catalog
    # ------------------------------------------------------------------

    def _build_tool_catalog_section(self) -> str:
        tool_json = self._pack.to_prompt_json()
        return f"""# TOOL CATALOG

The following tools are available under the `{self._profile.name.value}` profile.
Each tool has a name, description, category, input_schema (JSON Schema for args), and governance metadata.

Use ONLY these tools in your plan. Any tool not listed here will be rejected.

```json
{tool_json}
```"""

    # ------------------------------------------------------------------
    # Section 4: Search Decision Tree
    # ------------------------------------------------------------------

    def _build_search_decision_tree(self) -> str:
        return """# SEARCH FUNCTION SELECTION

Choose the correct search function based on the data source:

- **Documents / SharePoint files** → `search_assets`
- **SAM.gov solicitations** (grouped by solicitation number) → `search_solicitations`
- **SAM.gov notices** (individual postings) → `search_notices`
- **Salesforce records** (accounts, contacts, opportunities) → `search_salesforce`
- **Acquisition forecasts** (AG, APFS, State Dept) → `search_forecasts`
- **Scraped web pages** → `search_scraped_assets`
- **Generic model query** (direct DB query) → `query_model`
- **Get full content by ID** → `get_content`
- **Get asset metadata by ID** → `get_asset`

IMPORTANT: Do not confuse these. Using `search_assets` for SAM.gov data will return zero results."""

    # ------------------------------------------------------------------
    # Section 5: Efficiency Patterns
    # ------------------------------------------------------------------

    def _build_efficiency_patterns(self) -> str:
        return """# EFFICIENCY PATTERNS

## Thin → Materialize → LLM

Search functions with `payload_profile: "thin"` (like `search_assets`, `search_scraped_assets`) return lightweight references (IDs, titles, scores) without full document text.

Before passing thin results to an LLM function, insert a `get_content` step to materialize full text:

```json
{"name": "search", "tool": "search_assets", "args": {"query": "proposal"}},
{"name": "get_full_text", "tool": "get_content", "args": {"items": {"ref": "steps.search"}}},
{"name": "summarize", "tool": "generate", "args": {"prompt": {"template": "Summarize: {{ steps.get_full_text }}"}}}
```

Search functions with `payload_profile: "full"` (solicitations, notices, forecasts, salesforce) return complete structured data and do NOT need get_content.

## Side Effects Last

Place side-effect tools (send_email, webhook, update_metadata, etc.) at the end of the workflow, after all data gathering and processing is complete.

## Null-Safe Foreach

When using foreach with `on_error: continue`, failed items return null. Use the compact filter:
`{"template": "{{ steps.foreach_step | compact }}"}`"""

    # ------------------------------------------------------------------
    # Section 6: Profile Constraints
    # ------------------------------------------------------------------

    def _build_profile_constraints(self) -> str:
        p = self._profile
        lines = [f"# GENERATION PROFILE: {p.name.value}", ""]
        lines.append(f"**Description**: {p.description}")
        lines.append(f"**Allowed categories**: {', '.join(sorted(p.allowed_categories))}")

        if p.blocked_tools:
            lines.append(f"**Blocked tools**: {', '.join(sorted(p.blocked_tools))}")
        else:
            lines.append("**Blocked tools**: none")

        lines.append(f"**Side effects allowed**: {'yes' if p.allow_side_effects else 'no'}")

        if p.require_side_effect_confirmation:
            lines.append("**IMPORTANT**: Side-effect steps MUST include `confirm_side_effects: true` in args.")

        lines.append(f"**Max search limit**: {p.max_search_limit}")
        lines.append(f"**Max LLM tokens**: {p.max_llm_tokens}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 7: Data Source Context (reused from v1)
    # ------------------------------------------------------------------

    async def _build_data_source_context(
        self,
        session: Any,
        organization_id: UUID,
    ) -> str:
        """Build context about available data sources for the organization."""
        from sqlalchemy import select
        from app.core.database.models import SharePointSyncConfig, SamSearch, SalesforceConnection

        sources: List[Dict[str, Any]] = []

        # SharePoint
        try:
            result = await session.execute(
                select(SharePointSyncConfig)
                .where(SharePointSyncConfig.organization_id == organization_id)
                .where(SharePointSyncConfig.is_active == True)
            )
            configs = result.scalars().all()
            for c in configs:
                sources.append({
                    "type": "sharepoint",
                    "name": c.name,
                    "id": str(c.id),
                    "description": (c.description or "")[:80],
                    "folder": c.folder_name or c.folder_url or "",
                })
        except Exception as e:
            logger.warning(f"Failed to fetch SharePoint configs: {e}")

        # SAM.gov Saved Searches
        try:
            result = await session.execute(
                select(SamSearch)
                .where(SamSearch.organization_id == organization_id)
                .where(SamSearch.is_active == True)
            )
            searches = result.scalars().all()
            for s in searches:
                sources.append({
                    "type": "sam_search",
                    "name": s.name,
                    "description": (s.description or "")[:80],
                })
        except Exception as e:
            logger.warning(f"Failed to fetch SAM searches: {e}")

        # Salesforce
        try:
            result = await session.execute(
                select(SalesforceConnection)
                .where(SalesforceConnection.organization_id == organization_id)
                .where(SalesforceConnection.is_active == True)
            )
            connections = result.scalars().all()
            for c in connections:
                sources.append({
                    "type": "salesforce",
                    "name": c.name,
                    "instance_url": c.instance_url or "",
                })
        except Exception as e:
            logger.warning(f"Failed to fetch Salesforce connections: {e}")

        if not sources:
            return ""

        sources_json = json.dumps(sources, indent=2)
        return f"""# AVAILABLE DATA SOURCES

The organization has these configured data sources. Use the specific IDs/names when the user references them.

```json
{sources_json}
```"""

    # ------------------------------------------------------------------
    # Section 8: Metadata / Facet Context (reused from v1)
    # ------------------------------------------------------------------

    async def _build_metadata_context(
        self,
        session: Any,
        organization_id: UUID,
    ) -> str:
        """Build context about available metadata facets and namespaces."""
        from app.core.search.pg_search_service import pg_search_service
        from app.core.metadata.registry_service import metadata_registry_service

        schema = await pg_search_service.get_metadata_schema(
            session, organization_id, max_sample_values=10,
        )

        namespaces = schema.get("namespaces", {})
        facets = metadata_registry_service.get_facet_definitions()

        if not namespaces and not facets:
            return ""

        ctx: Dict[str, Any] = {}

        if facets:
            facet_list = []
            for name, defn in facets.items():
                facet_list.append({
                    "name": name,
                    "display_name": defn.get("display_name", name),
                    "data_type": defn.get("data_type", "string"),
                    "operators": defn.get("operators", ["eq", "in"]),
                    "content_types": list(defn.get("mappings", {}).keys()),
                })
            ctx["facets"] = facet_list

        if namespaces:
            ns_list = []
            for ns_name, ns_info in namespaces.items():
                fields = ns_info.get("fields", {})
                if not fields:
                    continue
                ns_entry = {
                    "namespace": ns_name,
                    "display_name": ns_info.get("display_name", ns_name),
                    "doc_count": ns_info.get("doc_count", 0),
                    "fields": {
                        fname: {
                            "type": finfo.get("type", "string"),
                            "samples": finfo.get("sample_values", [])[:5],
                        }
                        for fname, finfo in fields.items()
                    },
                }
                ns_list.append(ns_entry)
            ctx["namespaces"] = ns_list

        if not ctx:
            return ""

        ctx_json = json.dumps(ctx, indent=2)
        return f"""# SEARCH FILTERS

Search tools accept `facet_filters` (preferred, cross-domain) and `metadata_filters` (advanced, raw JSONB).

```json
{ctx_json}
```

Use `facet_filters` when possible: `{{"agency": "GSA", "naics_code": "541512"}}`"""

    # ------------------------------------------------------------------
    # Output Instructions
    # ------------------------------------------------------------------

    def _build_output_instructions(self) -> str:
        return """# OUTPUT INSTRUCTIONS

Return ONLY valid JSON matching the Typed Plan schema above.

Do NOT include:
- Markdown code fences
- Explanations or commentary
- Multiple alternatives

Output the single best Typed Plan JSON for the request.

PRE-OUTPUT CHECKLIST:
1. Every step uses a tool from the TOOL CATALOG
2. All required args for each tool are provided
3. Refs only point to earlier steps or defined parameters
4. Flow control steps have correct branches (foreach→each, if_branch→then)
5. Side-effect tools appear late in the workflow
6. Search limit values respect profile max
7. Thin search results are materialized before LLM consumption"""
