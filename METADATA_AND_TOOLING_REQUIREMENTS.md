# Curatore Platform Evolution  
## Contract-Driven Tools, JSON-First Workflows, and Faceted Metadata Architecture  
### With AI Procedure Generator as First Integration

---

# Executive Summary

This document defines the next architectural evolution of the Curatore data platform:

1. Transform the current workflow engine into a standards-aligned, contract-driven tool system compatible with modern LLM tool-calling specifications.
2. Adopt JSON Schema as the canonical validation and interoperability layer while retaining YAML as a human-authoring format.
3. Mature metadata and asset management into a governed schema + facet architecture to support scalable cross-domain search and LLM-aware filtering.
4. Use the AI Procedure Generator as the first full integration of this architecture.

The objective is to build a platform that is:

- Deterministic and high-performance for cron/autonomous workflows  
- Agent-capable for interactive research and business automation  
- Vendor-agnostic and interoperable  
- Schema-driven and versioned  
- Safe and governable for enterprise usage  

---

# 1. Architectural Principles

The platform evolution is guided by the following principles:

1. **Schema First** — All tools and metadata must be governed by explicit JSON Schemas.
2. **Contracts Over Prompts** — LLM integrations must rely on machine-readable contracts, not prose descriptions.
3. **Deterministic Execution** — Autonomous workflows must not depend on runtime reasoning.
4. **Separation of Planning and Execution** — LLM planning generates structured plans; execution is deterministic.
5. **Facet-Based Search** — Cross-domain filtering must rely on canonical metadata vocabulary.
6. **Versioned and Observable** — All contracts and executions must be versioned and traceable.

---

# 2. Transforming the Workflow Engine into a Contract-Driven Tool System

## 2.1 Current State

Curatore’s function registry:

- Stores name, description, parameters  
- Is consumed by the YAML-based procedure engine  
- Is exposed via prompt context to LLMs  

Limitations:

- No machine-readable contract layer  
- No structured validation for LLM tool calling  
- Tight coupling to Curatore runtime  

---

## 2.2 Target State: Tool Contract Layer

Introduce a canonical Tool Contract model.

### Tool Contract Model

```pseudo
class ToolContract:
    name: string
    description: string
    input_schema: JSONSchema
    output_schema: JSONSchema
    schema_version: string
    side_effects: enum(none, email, db_write, external)
    capability_class: enum(read_only, internal_write, external_communication, high_risk)
    requires_approval: boolean
    idempotency: enum(idempotent, non_idempotent)
    retry_policy: enum(safe_retry, no_retry)
    rate_limit_group: string
````

This becomes the interoperability layer between Curatore and any LLM framework.

---

## 2.3 Alignment with OpenAI Tool Calling Specification

Tool contracts must map directly to the OpenAI structured tool calling format.

Tool definition:

```pseudo
{
  "type": "function",
  "function": {
    "name": "search_assets",
    "description": "...",
    "parameters": { JSON Schema }
  }
}
```

LLM response:

```pseudo
{
  "tool_calls": [
    {
      "function": {
        "name": "search_assets",
        "arguments": { ... }
      }
    }
  ]
}
```

Adapter:

```pseudo
function to_openai_tool(contract):
    return {
        type: "function",
        function: {
            name: contract.name,
            description: contract.description,
            parameters: contract.input_schema
        }
    }
```

This ensures compatibility with OpenAI, LlamaIndex, LangGraph, and future frameworks.

---

# 3. JSON Schema as the Canonical Execution Model

## 3.1 Problem

LLM → YAML generation today is:

* Fragile
* Hard to validate
* Retry-heavy
* Difficult to version

---

## 3.2 Target Architecture

JSON is the canonical execution model.
YAML is a human authoring layer only.

---

## 3.3 ProcedurePlan Model

```pseudo
class ProcedurePlan:
    name: string
    slug: string
    description: string
    parameters: array(Parameter)
    steps: array(Step)
    on_error: enum(fail, continue)
    execution_mode: enum(cron, interactive)
```

Validation:

```pseudo
validate(plan_json, ProcedurePlanSchema)
```

---

## 3.4 YAML Support

```pseudo
function yaml_to_plan(yaml_text):
    parsed = parse_yaml(yaml_text)
    validate(parsed, ProcedurePlanSchema)
    return parsed
```

Execution engine consumes only validated JSON.

---

## 3.5 Schema Versioning Strategy

All tool and metadata schemas must include:

* `schema_id`
* `schema_version`

Rules:

* Minor changes are backward-compatible
* Major changes require version bump
* Procedures bind to schema version at generation time
* Migration path must exist for breaking changes

---

# 4. Metadata and Facet Architecture

## 4.1 Problem

* Metadata is dynamic
* Asset types vary
* Cross-domain filtering is brittle
* LLM cannot reliably infer valid fields

---

## 4.2 Target Architecture

Introduce:

1. Metadata Schema Registry
2. Facet Registry
3. Facet Mapping Layer
4. Optional Materialized Facet Index

---

## 4.3 Metadata Schema Registry

```pseudo
class AssetMetadataSchema:
    schema_id: string
    asset_type: string
    version: integer
    json_schema: JSON
    status: enum(draft, active, deprecated)
```

Discovery:

```pseudo
get_asset_metadata_schema(asset_type) -> JSONSchema
```

---

## 4.4 Canonical Facet Registry

```pseudo
class FacetDefinition:
    facet_name: string
    value_type: enum(string, number, date, boolean, array)
    allowed_ops: array(eq, in, gte, lte, contains, exists)
    normalizer: string
    schema_version: string
```

---

## 4.5 Facet Mapping

```pseudo
class FacetMapping:
    asset_type: string
    facet_name: string
    json_path: string
    transform: optional
```

---

## 4.6 Search Contract

```pseudo
search_assets(
    asset_types: array[string],
    query: string,
    facet_filters: object,
    filters: object(optional),
    limit: integer
)
```

Example:

```pseudo
facet_filters = {
    customer_agency: { eq: "DHS" },
    contract_value: { gte: 5000000 }
}
```

---

## 4.7 Optional Phase 2: Materialized Facet Index

```pseudo
asset_facets(
    asset_id,
    facet_name,
    value_text,
    value_num,
    value_date,
    updated_at
)
```

Search uses indexed joins for performance.

---

# 5. Governance and Safety Model

Each tool must declare:

* capability_class
* requires_approval
* idempotency
* retry_policy

Execution enforcement:

```pseudo
if tool.requires_approval:
    pause_and_request_approval()

if tool.retry_policy == safe_retry:
    retry_on_failure()
```

---

# 6. Observability and Traceability

Each execution step records:

```pseudo
trace_id
procedure_id
tool_name
schema_version
input_payload
output_payload
duration_ms
status
error
token_cost
```

Supports:

* auditing
* debugging
* compliance
* cost tracking

---

# 7. Concurrency and Performance Model

Define:

* max_concurrency per procedure
* max_concurrency per tool category
* isolation boundaries
* transactional guarantees
* token budgets

```pseudo
if concurrent_calls(tool.rate_limit_group) > limit:
    queue()
```

---

# 8. AI Procedure Generator as First Integration

The AI Procedure Generator must be the first consumer of:

* Tool Contracts
* ProcedurePlanSchema
* Metadata Schema Registry
* Facet Registry

---

## 8.1 Planner Requirements

The generator must:

1. Consume ToolContract export dynamically
2. Output JSON conforming to ProcedurePlanSchema
3. Use facet_filters when applicable
4. Respect capability governance
5. Operate within bounded token budgets

---

## 8.2 Planner Flow

```pseudo
tools = export_tool_contracts()
facets = list_facets()
schema = get_asset_metadata_schema(asset_type)

plan_json = LLM.generate_structured(
    output_schema=ProcedurePlanSchema,
    context={
        tools,
        facets,
        schema
    }
)

validate(plan_json)
```

---

## 8.3 Deterministic Repair Loop

```pseudo
errors = validate(plan_json)

if errors:
    patch = build_structured_patch(errors)
    plan_json = LLM.apply_patch(plan_json, patch)
```

Avoid full regeneration when possible.

---

## 8.4 Metadata Promotion Workflow

If procedure introduces new metadata:

```pseudo
write_metadata(...)
upsert_metadata_schema(...)
upsert_facet_definition(...)
upsert_facet_mapping(...)
backfill_asset_facets(...)
```

---

# 9. Cost Governance

Each LLM step declares:

* cost_class
* max_tokens

Enforcement:

```pseudo
if token_usage > procedure_budget:
    fail()
```

---

# 10. Migration Strategy

## Phase 1

* ToolContract layer
* JSON-first ProcedurePlan
* Schema registry tables
* Facet registry tables
* search_assets supports facet_filters

## Phase 2

* Materialized facet index
* Structured LLM output enforcement
* Observability layer

## Phase 3

* Governance UI
* Metadata promotion UI
* Optional OpenAPI/MCP exposure

---

# Final State

Curatore becomes:

* Tool-contract compliant
* JSON Schema-driven
* Facet-enabled
* LLM interoperable
* Deterministic for automation
* Governed for enterprise
* Scalable for cross-domain search
* Framework-agnostic

The AI Procedure Generator validates and proves the architecture before wider adoption.