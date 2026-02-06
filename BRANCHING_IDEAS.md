# Flow Control Functions — Requirements & YAML Specification
## Curatore Procedure Engine

**Date:** February 6, 2026  
**Scope:** Four new functions in the FunctionRegistry that enable branching, routing, parallelism, and iteration within procedures  

---

## 1. Context

Curatore's procedure engine executes YAML-defined workflows where every step calls a function from the FunctionRegistry. Functions are Python classes that extend `BaseFunction`, declare their parameters via `FunctionMeta` with `ParameterDoc` entries, and return a `FunctionResult`. The registry auto-discovers functions and exposes them through the API (`/api/v1/functions/`) and the frontend function browser (`/admin/functions`) with swagger-like documentation, YAML snippet generation, and test execution.

Today, every step in a procedure is a function call:

```yaml
- name: step_name
  function: function_name
  params: { ... }
  condition: "{{ expr }}"        # optional — skip if falsy
  foreach: "{{ expr }}"          # optional — iterate, {{ item }} in scope
  on_error: fail | skip | continue
```

The `ProcedureExecutor` walks the step list top-to-bottom. For each step it renders Jinja2 expressions in `params`, calls the function, stores the result in `context["steps"][step_name]`, and moves on.

This model has no way to express "do A *or* B", "do A *and* B at the same time", or "for each item, do A then B then C." Those patterns require flow control.

---

## 2. Design Principle: Flow Control as Functions

Flow control constructs will be **functions in the FunctionRegistry**, not special executor keywords. They live in a new `flow` category alongside the existing `llm`, `search`, `output`, `notify`, and `compound` categories:

```
backend/app/functions/
├── llm/           # generate, extract, summarize, classify, decide, route
├── search/        # search_assets, search_notices, get, get_content, query_model
├── output/        # update_metadata, create_artifact, generate_document
├── notify/        # send_email, webhook
├── compound/      # analyze_solicitation, generate_digest, enrich_assets
└── flow/          # if_branch, switch_branch, parallel, foreach
    ├── __init__.py
    ├── if_branch.py
    ├── switch_branch.py
    ├── parallel.py
    └── foreach.py
```

This means:

- Flow functions appear in `/admin/functions` under the **Flow** category with the same parameter docs, tags, and YAML output as every other function.
- Junior data staff discover branching the same way they discover `llm_summarize` or `send_email` — through the function browser.
- No new mental model. A procedure author already knows "every step calls a function." That remains true.

### How Flow Functions Work

A flow function evaluates its logic (checking a condition, matching a value, resolving an item list) and returns a `FlowResult` — a subclass of `FunctionResult` that tells the executor which **branches** to run. The step definition includes a `branches:` field containing named step lists. The executor reads the `FlowResult`, looks up the indicated branch(es), and executes them.

```
Step definition:
  function: if_branch
  params: { condition: "{{ expr }}" }
  branches:
    then: [ ...steps... ]
    else: [ ...steps... ]

Execution:
  1. Executor renders params → calls if_branch.execute()
  2. Function evaluates condition → returns FlowResult(branch_key="then")
  3. Executor finds branches["then"] → runs those steps sequentially
  4. Result of last step in the branch becomes the step's result
```

The function decides **what** to branch on. The executor handles **running** the branches. This keeps logging, error handling, and context scoping consistent across all flow functions without duplicating logic.

### The Unified Step Model

With this approach, every step in a procedure has a single consistent shape:

```yaml
- name: <string>                    # required — unique within scope
  function: <function_name>         # required — any function from the registry
  params: { ... }                   # optional — Jinja2-templated parameters
  branches: { ... }                 # optional — step lists for flow functions
  condition: "<jinja2 expr>"        # optional — skip this step entirely if falsy
  on_error: fail | skip | continue  # optional — default: fail
```

The `branches` field is simply ignored for non-flow functions.

---

## 3. Changes to Existing Code

### `functions/base.py`

Add `FLOW` to the `FunctionCategory` enum:

```python
class FunctionCategory(str, Enum):
    LLM = "llm"
    SEARCH = "search"
    OUTPUT = "output"
    NOTIFY = "notify"
    COMPOUND = "compound"
    FLOW = "flow"          # NEW
```

Add a `FlowResult` subclass:

```python
class FlowResult(FunctionResult):
    """Returned by flow control functions to direct the executor."""
    branch_key: str | None = None           # if_branch, switch_branch: which branch to run
    branches_to_run: list[str] | None = None  # parallel: list of branch names to run concurrently
    items_to_iterate: list[Any] | None = None  # foreach: the resolved item list
    skipped_indices: list[int] | None = None   # foreach: indices filtered by condition
```

### `functions/registry.py`

No structural changes. The registry's existing auto-discovery pattern registers flow functions the same way it registers any other category. Add imports from `flow/` in `_discover_functions()`.

### `procedures/base.py`

Add an optional `branches` field to `StepDefinition`:

```python
@dataclass
class StepDefinition:
    name: str
    function: str
    params: dict | None = None
    condition: str | None = None
    foreach: str | None = None      # legacy single-step iteration (unchanged)
    on_error: str = "fail"
    branches: dict | None = None    # NEW — map of branch_name → list[StepDefinition]
```

### `procedures/executor.py`

Add one method and one conditional check to the existing step execution flow:

```python
async def execute_step(self, step: StepDefinition, context: dict) -> Any:
    # 1. Evaluate condition (existing)
    if step.condition and not self._evaluate_condition(step.condition, context):
        return None

    # 2. Handle legacy foreach (existing)
    if step.foreach:
        return await self._execute_foreach_legacy(step, context)

    # 3. Call the function (existing)
    result = await self._call_function(step.function, step.params, context)

    # 4. NEW: If FlowResult and branches present, execute the indicated branches
    if isinstance(result, FlowResult) and step.branches:
        result = await self._execute_flow(result, step, context)

    return result
```

The `_execute_flow` method (~60 lines) handles the four flow patterns by inspecting the `FlowResult`:

- **`branch_key` set**: Run `branches[branch_key]` sequentially (if_branch, switch_branch)
- **`branches_to_run` set**: Run indicated branches concurrently (parallel)
- **`items_to_iterate` set**: Run `branches["each"]` once per item (foreach)

### `procedures/loader.py`

Add validation for `branches` when present on a step:

- If function is `if_branch`: require `branches.then` with ≥1 step; `branches.else` optional
- If function is `switch_branch`: require ≥1 named case in `branches`; `branches.default` optional
- If function is `parallel`: require ≥2 named branches, each with ≥1 step
- If function is `foreach`: require `branches.each` with ≥1 step
- Recursively validate all steps inside branches (they may themselves be flow functions)

### Frontend — No Changes Required

Flow functions auto-appear in `/admin/functions` through the existing API. The function browser, parameter documentation, YAML generator (`frontend/lib/yaml-generator.ts`), and category grouping all work without modification because flow functions use the same `FunctionMeta` structure as every other function.

---

## 4. Function Specifications

---

### 4.1 `if_branch`

**Purpose:** Execute one of two branches based on a condition.

**Location:** `backend/app/functions/flow/if_branch.py`

**FunctionMeta:**

| Field | Value |
|---|---|
| name | `if_branch` |
| category | `FunctionCategory.FLOW` |
| description | Evaluate a condition and execute one of two branches. If the condition is truthy, the `then` branch runs. If falsy, the `else` branch runs (if provided). |
| tags | `flow`, `branching`, `conditional`, `if`, `else` |
| requires_llm | `False` |

**Parameters:**

| Name | Type | Required | Description | Example |
|---|---|---|---|---|
| `condition` | str (Jinja2 expression) | Yes | Expression evaluated against the execution context. Truthy → `then` branch. Falsy → `else` branch. Follows Python truthiness: `None`, `False`, `0`, `""`, `[]`, `{}` are falsy. | `{{ steps.search_results.total > 0 }}` |

**Returns:** `FlowResult` with `branch_key` set to `"then"` or `"else"`.

**YAML Schema:**

```yaml
- name: <string>
  function: if_branch
  params:
    condition: "<jinja2 expr>"
  branches:
    then:                            # required — runs when condition is truthy
      - name: ...
        function: ...
    else:                            # optional — runs when condition is falsy
      - name: ...
        function: ...
  on_error: fail | skip | continue
```

**Requirements:**

| ID | Requirement |
|----|-------------|
| IF-1 | `if_branch` is a `BaseFunction` subclass registered in the FunctionRegistry under category `FLOW`. |
| IF-2 | It appears in `/admin/functions` with parameter documentation, example YAML, and tags. |
| IF-3 | The `condition` parameter is required. The executor renders it via Jinja2 before passing the resolved value to the function (same as any other parameter). |
| IF-4 | The function evaluates the rendered value for truthiness using Python semantics. |
| IF-5 | Returns `FlowResult(status=SUCCESS, branch_key="then")` when truthy, `FlowResult(status=SUCCESS, branch_key="else")` when falsy. |
| IF-6 | The executor runs the step list under `branches[branch_key]`. |
| IF-7 | If `branch_key="else"` but no `else` branch is defined, the step is a no-op and result is `null`. |
| IF-8 | `branches.then` must contain at least one step. `branches.else` is optional. |
| IF-9 | Steps inside branches may call any function including other flow functions (nesting is supported). |
| IF-10 | Steps inside a branch can reference `{{ steps.* }}` from steps that ran before the `if_branch` step, and from earlier steps within the same branch. |
| IF-11 | The overall step result (`{{ steps.<step_name> }}`) is the result of the last step in whichever branch ran, or `null` if no branch ran. |
| IF-12 | `on_error` on the step governs failures within either branch. Steps inside branches may also have their own `on_error`. |

**Example — Conditional notification:**

```yaml
name: Conditional Notification
slug: conditional_notification
description: Send different notifications based on whether search found results

params:
  search_query:
    type: string
    required: true
  notify_email:
    type: string
    default: "team@amivero.com"

steps:
  - name: search_documents
    function: search_notices
    params:
      query: "{{ params.search_query }}"
      limit: 50

  - name: check_and_notify
    function: if_branch
    params:
      condition: "{{ steps.search_documents.total > 0 }}"
    branches:
      then:
        - name: summarize_results
          function: llm_summarize
          params:
            items: "{{ steps.search_documents.results }}"
            format: "executive_brief"

        - name: send_results_email
          function: send_email
          params:
            to: "{{ params.notify_email }}"
            subject: "Search Results: {{ params.search_query }}"
            body: "{{ steps.summarize_results.text }}"
      else:
        - name: send_empty_email
          function: send_email
          params:
            to: "{{ params.notify_email }}"
            subject: "No Results: {{ params.search_query }}"
            body: "No documents matched your search query."
```

**Example — Optional translation (no `else` branch):**

```yaml
steps:
  - name: extract_text
    function: extract_document_text
    params:
      asset_id: "{{ params.asset_id }}"

  - name: maybe_translate
    function: if_branch
    params:
      condition: "{{ steps.extract_text.language != 'en' }}"
    branches:
      then:
        - name: translate_to_english
          function: llm_translate
          params:
            text: "{{ steps.extract_text.content }}"
            target_language: "en"

  - name: generate_summary
    function: llm_summarize
    params:
      text: "{{ steps.maybe_translate.text | default(steps.extract_text.content) }}"
```

---

### 4.2 `switch_branch`

**Purpose:** Route execution to one of several named branches based on a value.

**Location:** `backend/app/functions/flow/switch_branch.py`

**FunctionMeta:**

| Field | Value |
|---|---|
| name | `switch_branch` |
| category | `FunctionCategory.FLOW` |
| description | Route execution to one of several named branches based on a value. Evaluates the `value` parameter and matches it against the branch keys defined in `branches`. If no match is found, the `default` branch runs (if provided). |
| tags | `flow`, `branching`, `routing`, `switch`, `case` |
| requires_llm | `False` |

**Parameters:**

| Name | Type | Required | Description | Example |
|---|---|---|---|---|
| `value` | str (Jinja2 expression) | Yes | Expression that produces the routing value. The result is string-coerced and matched against branch keys (exact, case-sensitive). | `{{ steps.classify_document.category }}` |

**Returns:** `FlowResult` with `branch_key` set to the matching case key, `"default"`, or `null`.

**YAML Schema:**

```yaml
- name: <string>
  function: switch_branch
  params:
    value: "<jinja2 expr>"
  branches:
    <case_value>:                    # one or more named cases
      - name: ...
        function: ...
    <case_value>:
      - name: ...
        function: ...
    default:                         # optional — fallback
      - name: ...
        function: ...
  on_error: fail | skip | continue
```

**Requirements:**

| ID | Requirement |
|----|-------------|
| SW-1 | `switch_branch` is a `BaseFunction` subclass registered in the FunctionRegistry under category `FLOW`. |
| SW-2 | It appears in `/admin/functions` with parameter documentation, example YAML, and tags. |
| SW-3 | The `value` parameter is required. The executor renders it via Jinja2 before passing the resolved value. |
| SW-4 | The function string-coerces the rendered value and returns `FlowResult(branch_key=<matched_key>)`. |
| SW-5 | Matching is exact and case-sensitive. |
| SW-6 | If no case matches and a `default` branch exists, returns `FlowResult(branch_key="default")`. |
| SW-7 | If no case matches and no `default` branch exists, the step is a no-op (log a warning, result is `null`). |
| SW-8 | Only one branch runs per execution — no fall-through. |
| SW-9 | `branches` must contain at least one non-default entry. |
| SW-10 | Steps inside branches may call any function including other flow functions. |
| SW-11 | The overall step result is the result of the last step in whichever branch ran, or `null`. |

**Example — Route by document type:**

```yaml
name: Document Type Router
slug: doc_type_router
description: Process documents differently based on their classified type

params:
  asset_id:
    type: string
    required: true

steps:
  - name: classify_document
    function: llm_classify
    params:
      asset_id: "{{ params.asset_id }}"
      categories: ["contract", "invoice", "memo", "report"]

  - name: route_processing
    function: switch_branch
    params:
      value: "{{ steps.classify_document.category }}"
    branches:
      contract:
        - name: extract_clauses
          function: llm_extract
          params:
            asset_id: "{{ params.asset_id }}"
            extraction_type: "contract_clauses"
            fields: ["parties", "term", "value", "termination", "obligations"]

        - name: flag_risky_clauses
          function: llm_generate
          params:
            system_prompt: "Identify any unusual or risky clauses."
            user_prompt: "{{ steps.extract_clauses }}"

      invoice:
        - name: extract_line_items
          function: llm_extract
          params:
            asset_id: "{{ params.asset_id }}"
            extraction_type: "invoice_lines"
            fields: ["vendor", "amount", "date", "line_items"]

      memo:
        - name: summarize_memo
          function: llm_summarize
          params:
            asset_id: "{{ params.asset_id }}"
            format: "bullet_points"

      default:
        - name: generic_summary
          function: llm_summarize
          params:
            asset_id: "{{ params.asset_id }}"
            format: "general"

  - name: store_results
    function: save_extraction_result
    params:
      asset_id: "{{ params.asset_id }}"
      result: "{{ steps.route_processing }}"
      category: "{{ steps.classify_document.category }}"
```

---

### 4.3 `parallel`

**Purpose:** Execute multiple independent branches simultaneously.

**Location:** `backend/app/functions/flow/parallel.py`

**FunctionMeta:**

| Field | Value |
|---|---|
| name | `parallel` |
| category | `FunctionCategory.FLOW` |
| description | Execute multiple named branches simultaneously. Use when steps have no dependencies on each other and can safely run at the same time. All branches must complete before the procedure continues. |
| tags | `flow`, `parallel`, `concurrent`, `branching` |
| requires_llm | `False` |

**Parameters:**

| Name | Type | Required | Description | Example |
|---|---|---|---|---|
| `max_concurrency` | int | No | Maximum number of branches to run simultaneously. `0` or omitted = no limit. | `2` |

**Returns:** `FlowResult` with `branches_to_run` set to the list of all branch names.

**YAML Schema:**

```yaml
- name: <string>
  function: parallel
  params:
    max_concurrency: <int>          # optional — default: 0 (unlimited)
  branches:
    <branch_name>:
      - name: ...
        function: ...
    <branch_name>:
      - name: ...
        function: ...
  on_error: fail | skip | continue
```

**Requirements:**

| ID | Requirement |
|----|-------------|
| PA-1 | `parallel` is a `BaseFunction` subclass registered in the FunctionRegistry under category `FLOW`. |
| PA-2 | It appears in `/admin/functions` with parameter documentation, example YAML, and tags. |
| PA-3 | `branches` must contain at least two entries. |
| PA-4 | Each branch has a unique name and at least one step. |
| PA-5 | The function returns `FlowResult(branches_to_run=[...all branch names...])`. |
| PA-6 | The executor runs all indicated branches concurrently using `asyncio.gather()` (or `asyncio.Semaphore` when `max_concurrency` is set). |
| PA-7 | Steps *within* each branch execute sequentially, top-to-bottom. |
| PA-8 | Branches **cannot reference each other's step outputs**. Each branch sees only the shared context from before the parallel step, plus its own internal step outputs. |
| PA-9 | The parallel step completes when all branches have completed or failed. |
| PA-10 | `on_error: fail` (default): any branch failure cancels remaining branches (best-effort) and fails the step. |
| PA-11 | `on_error: continue`: failed branches are logged; other branches continue; the step still completes. |
| PA-12 | `on_error: skip`: same as `continue` — the step is considered successful even if branches failed. |
| PA-13 | The overall step result (`{{ steps.<step_name> }}`) is a dictionary keyed by branch name, where each value is the result of that branch's last step. Failed branches have `null` values. |
| PA-14 | Steps inside branches may call any function including other flow functions. |

**Example — Parallel enrichment:**

```yaml
name: Document Enrichment
slug: doc_enrichment
description: Run multiple AI analyses on a document simultaneously

params:
  asset_id:
    type: string
    required: true

steps:
  - name: get_document_text
    function: get_asset_content
    params:
      asset_id: "{{ params.asset_id }}"

  - name: enrich
    function: parallel
    on_error: continue
    branches:
      entities:
        - name: extract_entities
          function: llm_extract
          params:
            text: "{{ steps.get_document_text.content }}"
            extraction_type: "named_entities"
            fields: ["people", "organizations", "locations", "dates"]

      sentiment:
        - name: analyze_sentiment
          function: llm_generate
          params:
            system_prompt: "Analyze sentiment and tone. Return JSON: {sentiment, confidence, tone}."
            user_prompt: "{{ steps.get_document_text.content }}"

      classification:
        - name: classify_topics
          function: llm_classify
          params:
            text: "{{ steps.get_document_text.content }}"
            categories: ["procurement", "policy", "technical", "financial", "legal"]

        - name: classify_sensitivity
          function: llm_classify
          params:
            text: "{{ steps.get_document_text.content }}"
            categories: ["public", "internal", "sensitive", "confidential"]

  - name: save_enrichment
    function: save_extraction_result
    params:
      asset_id: "{{ params.asset_id }}"
      entities: "{{ steps.enrich.entities }}"
      sentiment: "{{ steps.enrich.sentiment }}"
      classification: "{{ steps.enrich.classification }}"
```

**Example — Rate-limited parallel search:**

```yaml
steps:
  - name: multi_source_search
    function: parallel
    params:
      max_concurrency: 2
    branches:
      sam_gov:
        - name: search_sam
          function: search_notices
          params:
            query: "{{ params.query }}"
      sharepoint:
        - name: search_sp
          function: search_sharepoint
          params:
            query: "{{ params.query }}"
      internal:
        - name: search_internal
          function: search_chunks
          params:
            query: "{{ params.query }}"
```

---

### 4.4 `foreach`

**Purpose:** Iterate over a list and execute a set of steps for each item, with concurrency control and per-item filtering.

**Location:** `backend/app/functions/flow/foreach.py`

**Backward Compatibility:** The existing single-step `foreach:` field on regular function steps continues to work unchanged. The `foreach` flow function is the upgrade path for multi-step iteration.

**FunctionMeta:**

| Field | Value |
|---|---|
| name | `foreach` |
| category | `FunctionCategory.FLOW` |
| description | Iterate over a list and execute a set of steps for each item. Supports concurrency control and per-item condition filtering. Inside the branch steps, `{{ item }}` is the current item and `{{ item_index }}` is the 0-based index. |
| tags | `flow`, `iteration`, `loop`, `foreach`, `batch` |
| requires_llm | `False` |

**Parameters:**

| Name | Type | Required | Description | Example |
|---|---|---|---|---|
| `items` | str (Jinja2 expression) | Yes | Expression that produces a list to iterate over. | `{{ steps.search_results.results }}` |
| `concurrency` | int | No | Max items to process in parallel. `1` = sequential (default). `0` = unlimited. `N` = up to N at a time. | `3` |
| `condition` | str (Jinja2 expression) | No | Per-item filter. Evaluated with `{{ item }}` and `{{ item_index }}` in scope. Items where this is falsy are skipped. | `{{ item.estimated_value > 100000 }}` |

**Returns:** `FlowResult` with `items_to_iterate` set to the resolved (and optionally filtered) list.

**YAML Schema:**

```yaml
- name: <string>
  function: foreach
  params:
    items: "<jinja2 expr>"
    concurrency: <int>              # optional — default: 1
    condition: "<jinja2 expr>"      # optional — per-item filter
  branches:
    each:                            # required — steps to run per item
      - name: ...
        function: ...
        params:
          something: "{{ item }}"
          index: "{{ item_index }}"
  on_error: fail | skip | continue
```

The branch key is always `each` for consistency with the other flow functions (the executor always reads branch names from the `FlowResult`). It runs once per item.

**Requirements:**

| ID | Requirement |
|----|-------------|
| FE-1 | `foreach` is a `BaseFunction` subclass registered in the FunctionRegistry under category `FLOW`. |
| FE-2 | It appears in `/admin/functions` with parameter documentation, example YAML, and tags. |
| FE-3 | The `items` parameter is required. It must evaluate to a list or iterable. If the result is not iterable, the step fails with a clear error message. |
| FE-4 | `branches.each` is required and must contain at least one step. |
| FE-5 | For each item, the entire `branches.each` step list executes sequentially. |
| FE-6 | `{{ item }}` (current item) and `{{ item_index }}` (0-based index) are injected into the Jinja2 context for the duration of each iteration. |
| FE-7 | `concurrency: 1` (default): items process sequentially. `concurrency: N` (N > 1): up to N items at a time via `asyncio.Semaphore`. `concurrency: 0`: unlimited parallelism. |
| FE-8 | When `condition` is present, it is evaluated per item with `{{ item }}` and `{{ item_index }}` in scope. Items where the condition is falsy are skipped. |
| FE-9 | `on_error: fail` (default): any iteration failure stops remaining items and fails the step. In-flight concurrent iterations are cancelled best-effort. |
| FE-10 | `on_error: continue`: the failed item is logged, its result is `null`, and remaining items continue. |
| FE-11 | `on_error: skip`: same as `continue`. |
| FE-12 | The overall step result (`{{ steps.<step_name> }}`) is a list of results, one per item in the original list. Each entry is the result of the last step in that item's iteration. Skipped/failed items have `null` entries. |
| FE-13 | Steps inside `branches.each` may call any function including other flow functions (nesting is supported). |
| FE-14 | Steps within an iteration can reference `{{ steps.* }}` from steps that ran before the foreach step (shared context), plus steps from earlier in the same iteration. |

**Example — Batch processing with concurrency:**

```yaml
name: Batch Document Summary
slug: batch_doc_summary
description: Summarize a list of documents with controlled concurrency

params:
  asset_ids:
    type: array
    items: { type: string }
    required: true

steps:
  - name: summarize_all
    function: foreach
    params:
      items: "{{ params.asset_ids }}"
      concurrency: 3
    on_error: continue
    branches:
      each:
        - name: get_content
          function: get_asset_content
          params:
            asset_id: "{{ item }}"

        - name: summarize
          function: llm_summarize
          params:
            text: "{{ steps.get_content.content }}"
            format: "executive_brief"

        - name: save_summary
          function: save_extraction_result
          params:
            asset_id: "{{ item }}"
            summary: "{{ steps.summarize.text }}"

  - name: send_completion_email
    function: send_email
    params:
      to: "team@amivero.com"
      subject: "Batch Summary Complete"
      body: "Summarized {{ steps.summarize_all | length }} documents."
```

**Example — Filter high-value opportunities:**

```yaml
steps:
  - name: fetch_notices
    function: search_notices
    params:
      posted_within_hours: 24

  - name: process_high_value
    function: foreach
    params:
      items: "{{ steps.fetch_notices.results }}"
      condition: "{{ item.estimated_value and item.estimated_value > 100000 }}"
      concurrency: 2
    branches:
      each:
        - name: deep_analysis
          function: llm_generate
          params:
            system_prompt: "Provide a detailed opportunity analysis for a government contractor."
            user_prompt: "Analyze: {{ item | tojson }}"

        - name: notify_bd_team
          function: slack_message
          params:
            channel: "#bd-opportunities"
            text: "🚨 High-value: {{ item.title }} (${{ item.estimated_value }})"
```

**Example — Nested flow control inside iteration:**

```yaml
steps:
  - name: process_documents
    function: foreach
    params:
      items: "{{ params.asset_ids }}"
      concurrency: 2
    branches:
      each:
        - name: classify
          function: llm_classify
          params:
            asset_id: "{{ item }}"
            categories: ["contract", "invoice", "other"]

        - name: route
          function: if_branch
          params:
            condition: "{{ steps.classify.category == 'contract' }}"
          branches:
            then:
              - name: extract_contract
                function: llm_extract
                params:
                  asset_id: "{{ item }}"
                  extraction_type: "contract_clauses"
            else:
              - name: basic_summary
                function: llm_summarize
                params:
                  asset_id: "{{ item }}"
```

---

## 5. End-to-End Example

This procedure uses all four flow functions together in a realistic Curatore workflow:

```yaml
name: SAM.gov Smart Digest
slug: sam_smart_digest
description: >
  Pull recent SAM.gov notices, classify and route each one,
  run parallel enrichments, and send a categorized digest.

triggers:
  - type: cron
    cron_expression: "0 8 * * 1-5"
  - type: event
    event_name: sam_pull.group_completed

params:
  recipients:
    type: array
    items: { type: string }
    default: ["bd-team@amivero.com"]
  lookback_hours:
    type: integer
    default: 24

steps:
  - name: fetch_notices
    function: search_notices
    params:
      posted_within_hours: "{{ params.lookback_hours }}"
      include_text: true

  - name: check_results
    function: if_branch
    params:
      condition: "{{ steps.fetch_notices.results | length > 0 }}"
    branches:
      then:
        - name: process_notices
          function: foreach
          params:
            items: "{{ steps.fetch_notices.results }}"
            concurrency: 3
          on_error: continue
          branches:
            each:
              - name: classify
                function: llm_classify
                params:
                  text: "{{ item.description }}"
                  categories: ["services", "construction", "technology", "supplies"]

              - name: enrich
                function: parallel
                on_error: continue
                branches:
                  summary:
                    - name: summarize
                      function: llm_summarize
                      params:
                        text: "{{ item.description }}"
                        format: "two_sentence"
                  relevance:
                    - name: score_relevance
                      function: llm_generate
                      params:
                        system_prompt: >
                          Score 1-10 how relevant this opportunity is for a
                          WOSB 8(a) IT services contractor. Return JSON:
                          {score: int, reason: string}
                        user_prompt: "{{ item.description }}"

              - name: category_extras
                function: switch_branch
                params:
                  value: "{{ steps.classify.category }}"
                branches:
                  technology:
                    - name: extract_tech_reqs
                      function: llm_extract
                      params:
                        text: "{{ item.description }}"
                        extraction_type: "tech_requirements"
                        fields: ["certifications", "clearances", "platforms"]
                  services:
                    - name: extract_labor_cats
                      function: llm_extract
                      params:
                        text: "{{ item.description }}"
                        extraction_type: "labor_categories"
                        fields: ["roles", "experience_levels", "locations"]

        - name: build_digest
          function: llm_generate
          params:
            system_prompt: >
              Create an executive digest for a BD team at a WOSB 8(a) IT
              services contractor. Group by category. Highlight high-relevance.
            user_prompt: "{{ steps.process_notices | tojson }}"

        - name: send_digest
          function: send_email
          params:
            to: "{{ params.recipients }}"
            subject: "SAM.gov Smart Digest — {{ now_et().strftime('%B %d, %Y') }}"
            body: "{{ steps.build_digest.text }}"
            html: true

      else:
        - name: send_empty_notice
          function: send_email
          params:
            to: "{{ params.recipients }}"
            subject: "SAM.gov Smart Digest — No New Notices"
            body: "No new notices in the last {{ params.lookback_hours }} hours."
```

---

## 6. Validation Rules

The loader (`procedures/loader.py`) validates `branches` based on which function the step calls:

| Function | Required Branches | Validation |
|----------|------------------|------------|
| `if_branch` | `then` (required), `else` (optional) | `then` has ≥1 step |
| `switch_branch` | ≥1 named case, `default` (optional) | each case has ≥1 step |
| `parallel` | ≥2 named branches | each has unique name and ≥1 step |
| `foreach` | `each` (required) | `each` has ≥1 step |
| Any other function | N/A | `branches` field ignored if present |

All step types: `name` is required and must be unique within its scope (top-level or within a branch). Validation is recursive — steps inside branches are validated by the same rules.

---

## 7. Logging

Every flow function decision is logged as a `RunLogEvent` so execution paths are fully traceable:

```
[if_branch check_results] condition=True → branch=then
[switch_branch route] value="contract" → branch=contract
[switch_branch route] value="unknown_type" → no match, no default → no-op
[parallel enrich] running 3 branches: [entities, sentiment, classification]
[parallel enrich] branch "sentiment" failed: TimeoutError — continuing (on_error=continue)
[foreach process_notices] 12 items, concurrency=3, filtered to 10 (condition)
[foreach process_notices] item 4/10 failed: LLMError — continuing (on_error=continue)
[foreach process_notices] completed: 9 succeeded, 1 failed
```