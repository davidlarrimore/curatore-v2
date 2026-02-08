## 1. Purpose

This document defines the requirements for a redesigned **AI Procedure Generator v2** that:

* Lives in **curatore-backend** alongside CWR and procedure storage
* Leverages **tool contracts (JSON Schema)** as the canonical source of truth
* Uses an **agentic compilation loop** (plan → validate → repair → compile) to dramatically reduce retries and errors
* Understands and correctly uses **org-scoped metadata catalog + facets**
* Produces **static, deterministic stored procedures** that run efficiently as cron/event-driven workflows
* Does **not** depend on (or call) the MCP service

Primary objective: **increase correctness, reduce complexity in prompts, and improve scalability and reliability** of generated procedures.

---

## 2. Non-Goals

* The generator does not execute procedures as part of generation (no “agent runs tools” by default)
* The generator does not require LangGraph or MCP to function
* The generator does not add new connector capabilities
* The generator does not replace CWR execution semantics
* The generator does not create a “runtime agent” inside cron jobs

---

## 3. Definitions

* **CWR (Curatore Workflow Runtime)**: deterministic executor of stored procedures and pipelines
* **Tool Contract Pack (TCP)**: the complete set of CWR tool definitions with JSON Schema input/output, side-effect flags, and policy constraints
* **Metadata Catalog**: org-scoped definition of metadata namespaces/fields/facets used for searching/filtering assets
* **Facet**: a user-facing filter concept that maps to one or more underlying metadata fields across asset types
* **Typed Plan**: an intermediate structured representation produced by the LLM, validated before compiling to YAML

---

## 4. Key Design Principles

### 4.1 Contracts are the Source of Truth

The generator must never rely on hand-written prompt tables as the authoritative spec. It must build prompts and validations from the same **Tool Contract Pack** the runtime uses.

### 4.2 Agentic ≠ Runtime Tool-Calling

“Agentic” in this context means:

* iterative reasoning with structured intermediate artifacts
* constrained generation
* repair loops using validation feedback
* selection/routing decisions based on schemas/catalog

It does **not** mean:

* executing tools dynamically during generation
* a model-driven runtime

### 4.3 Procedures Remain Static and Deterministic

Outputs must be compatible with existing stored procedures:

* clear step ordering
* explicit function calls
* explicit dataflow via templates
* no implicit planning at runtime

---

## 5. Architecture Overview (Backend-Native)

### 5.1 High-Level Flow

```
User Prompt
  ↓
Context Builder (contracts + org catalog + data sources)
  ↓
LLM produces Typed Plan (JSON)
  ↓
Plan Validator (JSON Schema + catalog rules)
  ↓
Repair Loop (LLM receives validation errors)
  ↓
Compiler (Plan → Procedure YAML/JSON)
  ↓
Procedure Validator (existing validate_procedure + contract checks)
  ↓
Return Draft Procedure (YAML + diagnostics)
```

### 5.2 Where It Lives

All components run within **curatore-backend**:

* `backend/app/services/procedure_generator_service_v2.py` (new)
* shared modules under `backend/app/cwr/contracts/*` and `backend/app/data/metadata/*`

No dependency on MCP services.

---

## 6. Core Requirements

### R1 — Tool Contract Pack (TCP) Integration

The generator must load a machine-readable Tool Contract Pack that includes, per tool:

* `name`
* `description`
* `category`
* `side_effect: boolean`
* `input_schema: JSON Schema`
* `output_schema: JSON Schema`
* `examples` (optional)
* `policy_defaults` (optional; e.g., default limit caps)

**Requirement:** Generator prompt context and validation must be built from this TCP.

---

### R2 — Typed Plan as the Primary LLM Output

The generator must shift from “LLM emits YAML” to:

**LLM emits Typed Plan JSON** (or YAML that is converted into JSON).

This plan must be:

* schema-validatable
* easy to repair incrementally
* unambiguous about data flow and step intents

**Required Plan Sections**

* `procedure`: { name, slug, description, tags, triggers? }
* `parameters`: list (optional)
* `steps`: ordered list of step objects
* each step includes:

  * `name`
  * `tool` (contract tool name)
  * `args` (must validate against tool input schema)
  * `uses`: list of references (optional but encouraged)
  * `outputs`: optional explicit output hints (for compile and template mapping)
  * `on_error` strategy

**Plan must not contain** raw Jinja2 templates except in clearly typed reference objects (see R4).

---

### R3 — Plan Validation (Schema-First)

The generator must validate the Typed Plan before compiling:

Validation layers:

1. **Plan Schema Validation**

* validate the plan structure

2. **Tool Arg Schema Validation**

* for each step, validate `args` against tool input_schema

3. **Facet + Metadata Validation**

* validate any facet filters or metadata references against org catalog
* reject unknown facets/fields

4. **Side-Effect Policy**

* if generating in “safe mode,” reject side-effect tools
* if “admin mode,” allow but require explicit confirmation flags in the plan

---

### R4 — Explicit Reference Model (No Freeform Templates in Plan)

Instead of writing Jinja2 in the plan, the LLM uses typed references:

Example reference object:

* `{ "ref": "steps.search_assets" }`
* `{ "ref": "steps.search_assets.results" }`
* `{ "ref": "params.days_back" }`

Compiler converts reference objects into the correct templating syntax.

This makes:

* validation easier
* repair easier
* compilation deterministic

---

### R5 — Compilation Phase: Plan → Procedure Definition

After plan validation, compile into the current stored procedure format (YAML or JSON).

Compilation responsibilities:

* generate `slug` if missing
* ensure step names are unique and stable
* convert typed references to templates
* apply default policy clamps if not specified (e.g., search limits)
* produce correct procedure schema shape expected by CWR executor

---

### R6 — Procedure Validation (Existing + Contract-Enhanced)

Once compiled, validate with:

* existing `validate_procedure(...)`
* plus contract-driven checks:

  * unknown tool
  * missing required parameters
  * invalid parameter type
  * illegal side-effect usage in safe mode
  * illegal facet references

If procedure validation fails:

* return errors to repair loop

---

### R7 — Agentic Repair Loop (Targeted, Not Full Retries)

Replace “retry from scratch up to 10 times” with a structured loop:

1. LLM produces initial plan
2. validation errors are returned with exact paths (JSON pointer)
3. LLM returns a **patch** or corrected plan
4. revalidate
5. compile
6. validate procedure
7. if needed, return compiler/procedure errors for a second patch

**Max attempts** should be lower than current:

* Plan repair: up to 3
* Procedure repair: up to 2
* Total max: 5

Goal: correctness through constrained repair, not brute retries.

---

### R8 — Org Context & Data Source Awareness

The generator must include org-scoped context:

* available SharePoint sync config IDs
* available saved SAM searches
* available Salesforce connections
* allowed folder paths or storage roots (optional)
* metadata catalog and facet registry for the org

This context should be generated as structured JSON context (not just prose).

---

### R9 — “Generation Profiles” (Capability Modes)

The generator must support profiles that control what it is allowed to produce.

Required profiles:

1. **safe_readonly**

* search + summarize + digest
* no emails
* no updates
* no webhooks

2. **workflow_standard**

* allow notifications (email) but require explicit “to” fields
* allow artifact generation
* still disallow external side effects by default

3. **admin_full**

* allow metadata updates, webhooks, etc.
* require explicit confirmations in plan (e.g., `confirm_side_effects: true`)

Profiles can map to:

* tool allowlists
* policy clamps
* additional validation rules

---

### R10 — Runtime Efficiency Requirements (Generated Procedures)

Generated procedures must follow efficiency patterns:

* search returns thin results by default
* limit results (clamped)
* materialize full text only for top_k
* never pass huge raw results into LLM steps
* enforce batching/foreach only when needed
* prefer deterministic multi-step procedure vs agentic runtime planning

---

## 7. Required Supporting Features in CWR

### S1 — Contract Pack Endpoint & Library

Even though generator is backend-native, contracts should be accessible via:

* Internal library call: `get_tool_contract_pack(org_id, profile)`
* External endpoint (for UI/MCP clients): `GET /api/v1/cwr/contracts`

Generator uses the internal library path for speed and consistency.

---

### S2 — Metadata Catalog API and Library

Generator must load:

* Effective metadata catalog for org
* Facet registry for org

Prefer internal library calls with caching.

---

## 8. User-Facing Outputs (What the API Returns)

Generator API should return a structured result:

* `success: bool`
* `procedure_yaml: str` (or json)
* `plan_json: dict` (optional, for debugging)
* `validation_errors: []` (machine readable)
* `warnings: []`
* `profile_used`
* `attempts`
* `diagnostics` (tool choices, clamps applied)

---

## 9. API Endpoints (Backend)

Recommended endpoints:

* `POST /api/v1/cwr/procedures/drafts/generate`

  * input: { prompt, profile, org_id? }
  * output: draft procedure + diagnostics

* `POST /api/v1/cwr/procedures/drafts/refine`

  * input: { current_yaml or current_plan, change_request }
  * output: updated draft

* `POST /api/v1/cwr/procedures/drafts/validate`

  * input: yaml/json
  * output: errors/warnings

(Keep endpoints small; MVP can start with generate + validate.)

---

## 10. Observability Requirements

Log per generation:

* org_id
* profile
* tools referenced
* attempt counts
* validation error types
* compile time
* tokens / cost (if available)
* final success/failure

Goal: continuously improve generator prompts and constraints.

---

## 11. Testing Requirements

### Unit Tests

* tool contract validation
* typed plan schema validation
* reference compilation
* facet validation

### Integration Tests

* generate procedure for 5–10 canonical prompts
* verify compiled procedures run in CWR executor
* negative tests:

  * invalid facet names
  * missing required tool args
  * side-effect tool in safe profile

### Regression Suite

Keep a curated set of “gold prompts” to prevent quality regression.

---

## 12. Migration Plan from Current Generator

### Phase 1 — Dual Path

Keep existing generator (`procedure_generator_service.py`) but add v2 behind a feature flag.

### Phase 2 — Switch Default

Once v2 hits stability:

* make v2 default
* keep v1 as fallback

### Phase 3 — Deprecate v1

Once error rate drops and outputs are stable.

---

## 13. Success Criteria

The redesign is successful when:

* > 90% of prompts produce valid procedures in ≤2 attempts
* validation errors drop sharply (unknown function, missing params)
* generated procedures follow performance patterns (bounded search → top_k materialize → summarize)
* facet usage is correct and validated against org catalog
* stored procedures remain deterministic and CWR-compatible

---

## 14. Appendix: Example “Agentic” Behavior Without Runtime Tool-Calling

### Example prompt

“Email a weekly past performance write-up for CBP cloud migrations”

**Agentic generation behavior:**

1. choose correct search tool(s)
2. require facet filters (customer=CBP, doc_type=past_performance)
3. enforce limits + top_k materialize
4. generate summarize step with structured outputs
5. generate send_email step only if allowed by profile
6. produce deterministic procedure YAML

The “agentic” work happens during compilation time, not at cron runtime.
