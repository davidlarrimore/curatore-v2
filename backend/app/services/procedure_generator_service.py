# backend/app/services/procedure_generator_service.py
"""
Procedure Generator Service - AI-powered procedure YAML generation.

This service leverages generative AI to create draft procedure definitions
based on natural language prompts. It dynamically builds context about:
- Available functions and their parameters (from the function registry)
- The Curatore procedure YAML schema
- Best practices for procedure design

The service includes automatic validation and retry logic to ensure
generated procedures are valid before returning them.

Usage:
    from app.services.procedure_generator_service import procedure_generator_service

    result = await procedure_generator_service.generate_procedure(
        prompt="Create a procedure that sends a daily email summary of new assets",
        organization_id=org_id,
    )

    if result["success"]:
        yaml_content = result["yaml"]
    else:
        error = result["error"]
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID
import asyncio

import yaml

from ..config import settings
from ..functions.registry import function_registry
from ..functions.base import FunctionCategory
from ..procedures.validator import validate_procedure, ValidationResult
from ..services.llm_service import llm_service

logger = logging.getLogger("curatore.services.procedure_generator")


class ProcedureGeneratorService:
    """
    AI-powered procedure generation service.

    Generates procedure YAML definitions from natural language prompts using
    a large language model. The service builds comprehensive context about
    available functions and the Curatore system to guide the AI.

    Features:
        - Dynamic function catalog built from the function registry
        - Automatic validation of generated procedures
        - Retry logic with error feedback (up to 10 attempts)
        - Warning review: If validation passes but has warnings (e.g., function
          mismatch), the LLM gets one chance to review and fix them

    Attributes:
        MAX_RETRIES: Maximum number of generation attempts (default: 10)

    Example:
        >>> service = ProcedureGeneratorService()
        >>> result = await service.generate_procedure(
        ...     prompt="Create a weekly digest of SAM.gov opportunities",
        ...     organization_id=org_id
        ... )
        >>> if result["success"]:
        ...     print(result["yaml"])
    """

    MAX_RETRIES = 10

    def __init__(self):
        """Initialize the procedure generator service."""
        self._function_registry = None

    def _get_function_registry(self):
        """Lazy load and initialize the function registry."""
        if self._function_registry is None:
            function_registry.initialize()
            self._function_registry = function_registry
        return self._function_registry

    def _build_function_catalog(self) -> str:
        """
        Build function catalog dynamically from the registry.

        Returns:
            str: Formatted function reference organized by category.
        """
        registry = self._get_function_registry()
        categories = registry.get_categories()
        all_functions = registry.list_all()

        # Category display names
        category_names = {
            "search": "DATA RETRIEVAL",
            "llm": "AI/LLM",
            "output": "OUTPUT",
            "notify": "NOTIFICATIONS",
            "compound": "COMPOUND OPERATIONS",
            "utility": "UTILITY",
            "logic": "LOGIC",
            "flow": "FLOW CONTROL",
        }

        lines = []

        for cat_key in ["search", "llm", "notify", "output", "compound", "flow"]:
            if cat_key not in categories:
                continue

            cat_name = category_names.get(cat_key, cat_key.upper())
            lines.append(f"\n## {cat_name} Functions\n")

            for func_name in sorted(categories[cat_key]):
                meta = registry.get_meta(func_name)
                if not meta:
                    continue

                lines.append(f"### {meta.name}")
                lines.append(f"{meta.description}")

                # Build parameter table
                if meta.parameters:
                    lines.append("| Parameter | Type | Required | Description |")
                    lines.append("|-----------|------|----------|-------------|")
                    for p in meta.parameters:
                        req = "Yes" if p.required else f"No (default: {p.default})"
                        desc = p.description
                        if p.enum_values:
                            desc += f" Options: {', '.join(p.enum_values)}"
                        lines.append(f"| {p.name} | {p.type} | {req} | {desc} |")

                # Include examples if available
                # Skip examples for flow functions - they require 'branches' which
                # the standard example format doesn't support. Flow functions are
                # documented in detail in the FLOW CONTROL section.
                if meta.examples and meta.category.value != "flow":
                    lines.append("")
                    lines.append("**Examples:**")
                    for ex in meta.examples:
                        desc = ex.get("description", "Example")
                        params = ex.get("params", {})
                        # Format params as YAML-like for readability
                        param_lines = []
                        for k, v in params.items():
                            if isinstance(v, list):
                                param_lines.append(f"      {k}: {v}")
                            elif isinstance(v, str):
                                param_lines.append(f'      {k}: "{v}"')
                            else:
                                param_lines.append(f"      {k}: {v}")
                        lines.append(f"- {desc}:")
                        lines.append("  ```yaml")
                        lines.append(f"  function: {meta.name}")
                        lines.append("  params:")
                        lines.extend(param_lines)
                        lines.append("  ```")
                elif meta.category.value == "flow":
                    lines.append("")
                    lines.append("**Note:** See FLOW CONTROL FUNCTIONS section for complete examples with `branches`.")

                lines.append("")

        return "\n".join(lines)

    def _build_system_prompt(self) -> str:
        """
        Build a comprehensive system prompt for procedure generation.

        Returns:
            str: Complete system prompt with context, schema, and function catalog.
        """
        function_catalog = self._build_function_catalog()

        return f"""You are an expert at generating Curatore procedure definitions in YAML format.

# CURATORE PROCEDURES

Procedures are automated workflows that execute a sequence of steps. Each step calls a function with parameters. Steps can reference outputs from previous steps using template syntax.

# YAML SCHEMA

```yaml
name: string                    # Human-readable name (required)
slug: string                    # Unique identifier: lowercase, underscores/hyphens, starts with letter (required)
description: string             # One-sentence description of what this procedure does (required)

parameters:                     # Optional: Only include if values should be configurable at runtime
  - name: param_name            # Parameter name (used in templates as params.param_name)
    type: string                # Data type: string, integer, boolean, array, object
    description: string         # What this parameter is for
    required: false             # If false, must have a default value
    default: value              # Default value when not provided

steps:                          # List of steps to execute in order (required, minimum 1)
  - name: step_name             # Unique step identifier (required)
    function: function_name     # Function to call (required, must be from catalog below)
    params:                     # Parameters to pass to the function
      param1: "value"           # Static value
      param2: "{{{{ steps.previous_step }}}}"  # Reference previous step output
    on_error: fail              # Error handling: fail (default), skip, continue

on_error: fail                  # Procedure-level error handling (optional)
tags:                           # Categorization tags (optional)
  - tag1
  - tag2
```

# TEMPLATE SYNTAX

Use Jinja2 templates to reference dynamic values:

- `{{{{ steps.step_name }}}}` - Output from a previous step
- `{{{{ steps.step_name.field }}}}` - Access a field from step output
- `{{{{ steps.step_name | length }}}}` - Get list length
- `{{{{ steps.step_name | md_to_html }}}}` - Convert markdown to HTML (for email bodies)
- `{{{{ params.param_name }}}}` - Reference a procedure parameter
- `{{{{ today() }}}}` - Current date (YYYY-MM-DD)
- `{{{{ now() }}}}` - Current datetime

# AVAILABLE FUNCTIONS
{function_catalog}

# DESIGN GUIDELINES

1. **Use explicit values from the prompt**: If the user specifies "email to alice@example.com", use `to: "alice@example.com"` directly in the step params. Only use parameters when the user explicitly requests configurability.

2. **Keep it simple**: Use the minimum number of steps needed. Don't over-engineer.

3. **Name steps descriptively**: Use clear names like `search_notices`, `generate_summary`, `send_report`.

4. **Handle data flow**: Each step that needs data from a previous step must use template references.

# CRITICAL: SEARCH FUNCTION SELECTION

**Each data type has a SPECIFIC search function. Using the wrong function will return NO RESULTS.**

| Data Type | CORRECT Function | Description |
|-----------|------------------|-------------|
| Acquisition Forecasts | `search_forecasts` | AG, APFS, State Dept forecasts |
| SAM.gov Solicitations | `search_solicitations` | Grouped contract opportunities |
| SAM.gov Notices | `search_notices` | Individual federal notices |
| Salesforce Records | `search_salesforce` | Accounts, contacts, opportunities |
| Documents/Files | `search_assets` | Uploaded docs, SharePoint files |
| Scraped Web Pages | `search_scraped_assets` | Web scraping results |

## ❌ COMMON MISTAKES - DO NOT DO THIS:

- ❌ `function: search_assets` for forecasts → WRONG, will not find forecasts
- ❌ `function: search_assets` for SAM.gov data → WRONG, use search_solicitations/search_notices
- ❌ `function: search_solicitations` for forecasts → WRONG, solicitations ≠ forecasts
- ❌ `function: search_forecasts` for SAM notices → WRONG, forecasts ≠ notices

## ✅ CORRECT PATTERNS:

- ✅ "Search forecasts for AI" → `function: search_forecasts`
- ✅ "Find SAM.gov opportunities" → `function: search_solicitations`
- ✅ "Get recent contract notices" → `function: search_notices`
- ✅ "Search uploaded documents" → `function: search_assets`
- ✅ "Find Salesforce accounts" → `function: search_salesforce`

## Decision Tree:
1. Is it about federal acquisition FORECASTS (upcoming opportunities)? → `search_forecasts`
2. Is it about SAM.gov contract SOLICITATIONS? → `search_solicitations`
3. Is it about SAM.gov NOTICES? → `search_notices`
4. Is it about Salesforce CRM data? → `search_salesforce`
5. Is it about web scraping results? → `search_scraped_assets`
6. Is it about uploaded documents/files? → `search_assets`

# SEARCH RESULT SCHEMAS

Each search function returns a list of items. Use these EXACT field names in templates:

## search_assets (Documents/Files)
```yaml
{{% for doc in steps.search_results %}}
  {{{{ doc.title }}}}              # Full path/title (e.g., "Folder/SubFolder/file.pdf")
  {{{{ doc.original_filename }}}}  # Just the filename (e.g., "file.pdf")
  {{{{ doc.folder_path }}}}        # Folder path (e.g., "Folder/SubFolder")
  {{{{ doc.source_url }}}}         # Direct URL to file (SharePoint URL, etc.)
  {{{{ doc.content_type }}}}       # MIME type (e.g., "application/pdf")
  {{{{ doc.source_type }}}}        # Source: "sharepoint", "upload", "web_scrape", "sam_gov"
  {{{{ doc.score }}}}              # Relevance score
  {{{{ doc.snippet }}}}            # Text excerpt with highlights
{{% endfor %}}
```

## search_solicitations / search_notices (SAM.gov)
```yaml
{{% for item in steps.search_results %}}
  {{{{ item.title }}}}             # Solicitation/notice title
  {{{{ item.solicitation_number }}}}  # SAM.gov solicitation number
  {{{{ item.notice_id }}}}         # SAM.gov notice ID
  {{{{ item.agency }}}}            # Agency name
  {{{{ item.posted_date }}}}       # Date posted
  {{{{ item.response_deadline }}}} # Response deadline
  {{{{ item.set_aside }}}}         # Set-aside type
  {{{{ item.naics_code }}}}        # NAICS code
  {{{{ item.detail_url }}}}        # Link to Curatore detail page
  {{{{ item.sam_url }}}}           # Link to SAM.gov
{{% endfor %}}
```

## search_forecasts (Acquisition Forecasts)
```yaml
{{% for forecast in steps.search_results %}}
  {{{{ forecast.title }}}}         # Forecast title/description
  {{{{ forecast.agency }}}}        # Agency name
  {{{{ forecast.source_type }}}}   # Source: "ag", "apfs", "state"
  {{{{ forecast.fiscal_year }}}}   # Fiscal year
  {{{{ forecast.naics_code }}}}    # NAICS code
  {{{{ forecast.estimated_value }}}} # Estimated contract value
  {{{{ forecast.detail_url }}}}    # Link to Curatore detail page
{{% endfor %}}
```

## search_salesforce (CRM Records)
```yaml
{{% for record in steps.search_results %}}
  {{{{ record.title }}}}           # Record name
  {{{{ record.type }}}}            # "account", "contact", "opportunity"
  {{{{ record.account_name }}}}    # Account name (for contacts/opportunities)
  {{{{ record.stage }}}}           # Opportunity stage
  {{{{ record.amount }}}}          # Opportunity amount
  {{{{ record.email }}}}           # Contact email
  {{{{ record.phone }}}}           # Contact phone
{{% endfor %}}
```

# HTML EMAIL FORMATTING

When the user requests HTML/formatted/styled emails, use `send_email` with `html: true`:

```yaml
- name: send_html_email
  function: send_email
  params:
    to: "recipient@example.com"
    subject: "Report"
    html: true  # REQUIRED for HTML content
    body: |
      <html>
      <body>
        <h1>Report Title</h1>
        <p>Content here...</p>
        {{% for item in steps.search_results %}}
        <div>{{{{ item.title }}}}</div>
        {{% endfor %}}
      </body>
      </html>
```

## IMPORTANT: LLM Output in HTML Emails

LLM functions (llm_generate, llm_summarize) return **markdown** by default.
When embedding LLM output in HTML emails, use the `md_to_html` filter to convert:

```yaml
- name: generate_summary
  function: llm_summarize
  params:
    text: "{{{{ steps.search_results }}}}"

- name: send_report
  function: send_email
  params:
    to: "team@company.com"
    subject: "Report"
    html: true
    body: |
      <html>
      <body>
        <h1>Summary</h1>
        <div>{{{{ steps.generate_summary | md_to_html }}}}</div>
      </body>
      </html>
```

- ✅ CORRECT: `{{{{ steps.llm_output | md_to_html }}}}` - Converts markdown headers, bold, lists to HTML
- ❌ WRONG: `{{{{ steps.llm_output | replace('\\n', '<br>') }}}}` - Only handles newlines, not markdown
- ❌ WRONG: `{{{{ steps.llm_output }}}}` directly in HTML - Shows raw markdown as text

## ❌ DO NOT use `generate_document` for email bodies

`generate_document` creates **files** (PDF, DOCX, CSV) - it does NOT support HTML and is NOT for email content.

- ❌ WRONG: `function: generate_document` with `format: html`
- ✅ CORRECT: `function: send_email` with `html: true`

# FLOW CONTROL FUNCTIONS

Flow control functions enable branching, routing, parallelism, and iteration within procedures.
They work by evaluating conditions/values and directing which `branches` to execute.

## Flow Function Reference

### if_branch
Execute one of two branches based on a condition.

```yaml
- name: check_results
  function: if_branch
  params:
    condition: "{{{{ steps.search.total > 0 }}}}"  # Jinja2 expression, truthy/falsy
  branches:
    then:                          # Required - runs when condition is truthy
      - name: process_results
        function: llm_summarize
        params:
          text: "{{{{ steps.search.results }}}}"
    else:                          # Optional - runs when condition is falsy
      - name: log_empty
        function: log
        params:
          message: "No results found"
```

### switch_branch
Route to one of several branches based on a value (like switch/case).

```yaml
- name: route_by_type
  function: switch_branch
  params:
    value: "{{{{ steps.classify.category }}}}"  # Value to match against branch names
  branches:
    contract:                      # Branch runs if value == "contract"
      - name: extract_clauses
        function: llm_extract
        params:
          extraction_type: "contract_clauses"
    invoice:                       # Branch runs if value == "invoice"
      - name: extract_line_items
        function: llm_extract
        params:
          extraction_type: "invoice_lines"
    default:                       # Optional - runs if no other branch matches
      - name: generic_summary
        function: llm_summarize
```

### parallel
Execute multiple branches simultaneously (for independent operations).

```yaml
- name: enrich_document
  function: parallel
  params:
    max_concurrency: 3             # Optional - limit concurrent branches (0 = unlimited)
  branches:
    entities:                      # All branches run concurrently
      - name: extract_entities
        function: llm_extract
        params:
          extraction_type: "named_entities"
    sentiment:
      - name: analyze_sentiment
        function: llm_generate
        params:
          prompt: "Analyze sentiment..."
    classification:
      - name: classify_topics
        function: llm_classify
# Results available as: steps.enrich_document.entities, steps.enrich_document.sentiment, etc.
```

### foreach
Iterate over a list with multiple steps per item.

```yaml
- name: process_each_notice
  function: foreach
  params:
    items: "{{{{ steps.search_notices.results }}}}"  # List to iterate
    concurrency: 3                 # Optional - process 3 items at a time (1 = sequential)
    condition: "{{{{ item.value > 100000 }}}}"  # Optional - filter items
  branches:
    each:                          # Required - steps to run for each item
      - name: summarize_item
        function: llm_summarize
        params:
          text: "{{{{ item.description }}}}"  # {{{{ item }}}} is current item
      - name: notify
        function: send_email
        params:
          to: "team@company.com"
          subject: "Notice: {{{{ item.title }}}}"
          body: "{{{{ steps.summarize_item }}}}"
# {{{{ item }}}} and {{{{ item_index }}}} available inside branches.each
```

## When to Use Flow Functions

| Scenario | Function |
|----------|----------|
| Do A or B based on a condition | `if_branch` |
| Route to different logic based on type/category | `switch_branch` |
| Run independent operations at the same time | `parallel` |
| Process a list with multi-step logic per item | `foreach` |

## Flow Control Best Practices

1. **Use if_branch** when you need different behavior based on results (e.g., empty vs non-empty)
2. **Use switch_branch** when routing by classification, type, or status
3. **Use parallel** only when branches are truly independent (no shared state)
4. **Use foreach** when you need multiple steps per item (for single-step iteration, use the legacy `foreach:` field)
5. **Nesting is supported**: You can put flow functions inside other flow function branches

# EXAMPLES

## Example 1: Search and Email Report

Prompt: "Find SAM.gov notices from today and email a summary to reports@company.com"

```yaml
name: Daily SAM Notice Report
slug: daily_sam_notice_report
description: Search for today's SAM.gov notices and email a summary report.

steps:
  - name: search_notices
    function: search_notices
    params:
      posted_within_days: 1
      limit: 100

  - name: generate_summary
    function: llm_generate
    params:
      system_prompt: "You are a government contracting analyst. Summarize the following federal contract notices, highlighting key opportunities."
      prompt: "Summarize these {{{{ steps.search_notices | length }}}} notices:\\n\\n{{{{ steps.search_notices }}}}"
      max_tokens: 1000

  - name: send_report
    function: send_email
    params:
      to: "reports@company.com"
      subject: "Daily SAM.gov Notice Summary - {{{{ today() }}}}"
      body: "{{{{ steps.generate_summary }}}}"

on_error: fail
tags:
  - sam
  - daily
  - email
```

## Example 2: Document Classification with Logging

Prompt: "Classify uploaded documents and log the results"

```yaml
name: Document Classifier
slug: document_classifier
description: Classify documents using AI and log classification results.

steps:
  - name: get_documents
    function: search_assets
    params:
      query: "*"
      limit: 50
      filters:
        created_within_days: 1

  - name: classify
    function: classify_document
    params:
      content: "{{{{ steps.get_documents }}}}"
      categories:
        - contract
        - proposal
        - report
        - correspondence
        - other

  - name: log_results
    function: log
    params:
      message: "Classified {{{{ steps.get_documents | length }}}} documents"
      level: INFO
      data: "{{{{ steps.classify }}}}"

on_error: continue
tags:
  - classification
  - documents
```

## Example 3: Acquisition Forecast HTML Email Report

Prompt: "Search for AI/ML acquisition forecasts and email a formatted HTML report"

```yaml
name: AI/ML Forecast HTML Report
slug: ai_ml_forecast_html_report
description: Search acquisition forecasts for AI/ML opportunities and email a styled HTML report.

steps:
  - name: search_forecasts
    function: search_forecasts
    params:
      query: "artificial intelligence machine learning"
      limit: 100

  - name: generate_summary
    function: llm_generate
    params:
      system_prompt: "You are a business development analyst. Create detailed summaries of these forecasts."
      prompt: "Summarize these {{{{ steps.search_forecasts | length }}}} forecasts:\\n\\n{{{{ steps.search_forecasts }}}}"
      max_tokens: 2000

  - name: send_html_report
    function: send_email
    params:
      to: "bd-team@company.com"
      subject: "AI/ML Acquisition Forecast Report - {{{{ today() }}}}"
      html: true
      body: |
        <html>
        <body style="font-family: Arial, sans-serif;">
          <h1>AI/ML Acquisition Forecast Opportunities</h1>
          <p>Found <strong>{{{{ steps.search_forecasts | length }}}}</strong> forecasts.</p>

          <h2>AI Analysis</h2>
          <div>{{{{ steps.generate_summary | md_to_html }}}}</div>

          <h2>Forecast Details</h2>
          {{% for forecast in steps.search_forecasts %}}
          <div style="border: 1px solid #ccc; padding: 10px; margin: 10px 0;">
            <h3>{{{{ forecast.title }}}}</h3>
            <p><strong>Source:</strong> {{{{ forecast.source_type }}}}</p>
            {{% if forecast.detail_url %}}
            <a href="http://localhost:3000{{{{ forecast.detail_url }}}}">View Details</a>
            {{% endif %}}
          </div>
          {{% endfor %}}

          <p><em>Generated: {{{{ now() }}}}</em></p>
        </body>
        </html>

on_error: fail
tags:
  - forecasts
  - ai-ml
  - html-email
```

## Example 4: Configurable Procedure with Parameters

Prompt: "Create a procedure to search for solicitations with a configurable keyword and days"

```yaml
name: Custom Solicitation Search
slug: custom_solicitation_search
description: Search SAM.gov solicitations with configurable filters.

parameters:
  - name: keyword
    type: string
    description: Search keyword for solicitations
    required: false
    default: ""
  - name: days_back
    type: integer
    description: Number of days to search back
    required: false
    default: 7

steps:
  - name: search
    function: search_solicitations
    params:
      keyword: "{{{{ params.keyword }}}}"
      posted_within_days: "{{{{ params.days_back }}}}"
      limit: 50

  - name: format_results
    function: generate_digest
    params:
      title: "Solicitation Search Results"
      items: "{{{{ steps.search }}}}"
      format: markdown

on_error: fail
tags:
  - sam
  - search
  - configurable
```

## Example 5: Conditional Report with if_branch

Prompt: "Search for AI/ML forecasts and send different emails based on whether results were found"

```yaml
name: AI/ML Forecast Conditional Report
slug: ai_ml_forecast_conditional_report
description: Search AI/ML forecasts and send appropriate notification based on results.

steps:
  - name: search_forecasts
    function: search_forecasts
    params:
      query: "artificial intelligence machine learning"
      limit: 100

  - name: handle_results
    function: if_branch
    params:
      condition: "{{{{ steps.search_forecasts | length > 0 }}}}"
    branches:
      then:
        - name: generate_summary
          function: llm_generate
          params:
            system_prompt: "You are a BD analyst. Create an executive summary of these AI/ML forecasts."
            prompt: "Summarize these {{{{ steps.search_forecasts | length }}}} forecasts:\\n\\n{{{{ steps.search_forecasts }}}}"
            max_tokens: 2000

        - name: send_results_email
          function: send_email
          params:
            to: "bd-team@company.com"
            subject: "AI/ML Acquisition Forecast Report - {{{{ today() }}}}"
            html: true
            body: |
              <html>
              <body>
                <h1>AI/ML Forecast Opportunities</h1>
                <p>Found <strong>{{{{ steps.search_forecasts | length }}}}</strong> forecasts.</p>
                <div>{{{{ steps.generate_summary | md_to_html }}}}</div>
              </body>
              </html>

      else:
        - name: send_no_results_email
          function: send_email
          params:
            to: "bd-team@company.com"
            subject: "AI/ML Forecast Report - No Results"
            body: "No AI/ML acquisition forecasts were found in the current data."

on_error: fail
tags:
  - forecasts
  - ai-ml
  - conditional
```

## Example 6: Document Processing with foreach

Prompt: "Process a batch of documents - classify each one and summarize contracts"

```yaml
name: Batch Document Processor
slug: batch_document_processor
description: Process multiple documents with classification and conditional summarization.

parameters:
  - name: asset_ids
    type: array
    description: List of asset IDs to process
    required: true

steps:
  - name: process_documents
    function: foreach
    params:
      items: "{{{{ params.asset_ids }}}}"
      concurrency: 3
    on_error: continue
    branches:
      each:
        - name: get_content
          function: get_asset
          params:
            asset_id: "{{{{ item }}}}"

        - name: classify
          function: llm_classify
          params:
            text: "{{{{ steps.get_content.content }}}}"
            categories:
              - contract
              - proposal
              - report
              - other

        - name: conditional_summary
          function: if_branch
          params:
            condition: "{{{{ steps.classify.category == 'contract' }}}}"
          branches:
            then:
              - name: extract_contract_details
                function: llm_extract
                params:
                  text: "{{{{ steps.get_content.content }}}}"
                  extraction_type: "contract_clauses"
                  fields:
                    - parties
                    - term
                    - value
                    - obligations
            else:
              - name: basic_summary
                function: llm_summarize
                params:
                  text: "{{{{ steps.get_content.content }}}}"
                  format: "brief"

  - name: send_completion_report
    function: send_email
    params:
      to: "team@company.com"
      subject: "Document Processing Complete"
      body: "Processed {{{{ params.asset_ids | length }}}} documents."

on_error: fail
tags:
  - documents
  - classification
  - batch
```

## Example 7: Multi-Source Search with parallel

Prompt: "Search multiple data sources at once and combine results"

```yaml
name: Multi-Source Opportunity Search
slug: multi_source_opportunity_search
description: Search forecasts, SAM notices, and Salesforce in parallel.

parameters:
  - name: search_query
    type: string
    description: Search query
    required: false
    default: "cloud migration"

steps:
  - name: parallel_search
    function: parallel
    params:
      max_concurrency: 3
    on_error: continue
    branches:
      forecasts:
        - name: search_forecasts
          function: search_forecasts
          params:
            query: "{{{{ params.search_query }}}}"
            limit: 50

      sam_notices:
        - name: search_notices
          function: search_notices
          params:
            keyword: "{{{{ params.search_query }}}}"
            posted_within_days: 30
            limit: 50

      salesforce:
        - name: search_opportunities
          function: search_salesforce
          params:
            object_type: opportunity
            query: "{{{{ params.search_query }}}}"
            limit: 50

  - name: generate_combined_report
    function: llm_generate
    params:
      system_prompt: "Create a unified opportunity report combining results from multiple sources."
      prompt: |
        Combine these search results into a unified report:

        ACQUISITION FORECASTS ({{{{ steps.parallel_search.forecasts | length if steps.parallel_search.forecasts else 0 }}}}):
        {{{{ steps.parallel_search.forecasts }}}}

        SAM.GOV NOTICES ({{{{ steps.parallel_search.sam_notices | length if steps.parallel_search.sam_notices else 0 }}}}):
        {{{{ steps.parallel_search.sam_notices }}}}

        SALESFORCE OPPORTUNITIES ({{{{ steps.parallel_search.salesforce | length if steps.parallel_search.salesforce else 0 }}}}):
        {{{{ steps.parallel_search.salesforce }}}}
      max_tokens: 3000

  - name: send_report
    function: send_email
    params:
      to: "bd-team@company.com"
      subject: "Multi-Source Opportunity Report: {{{{ params.search_query }}}}"
      body: "{{{{ steps.generate_combined_report }}}}"

on_error: fail
tags:
  - multi-source
  - parallel
  - opportunities
```

# PRE-OUTPUT VERIFICATION

Before outputting, verify your procedure:

1. **Search function check**: For EACH search step, confirm the function matches the data type:
   - Searching forecasts? Must use `search_forecasts`
   - Searching SAM.gov? Must use `search_solicitations` or `search_notices`
   - Searching Salesforce? Must use `search_salesforce`
   - Searching documents? Must use `search_assets`

2. **Step name matches function**: If step is named "search_forecasts", function MUST be `search_forecasts`

3. **Required parameters**: Each function has required parameters - verify they're provided

4. **Flow control check**: If using flow functions, verify:
   - `if_branch`: Has `branches.then` with at least one step
   - `switch_branch`: Has at least one case branch (not counting `default`)
   - `parallel`: Has at least 2 branches
   - `foreach`: Has `branches.each` with at least one step

5. **Branch references**: Steps inside branches can only reference:
   - Steps that ran BEFORE the flow function step
   - Steps that ran earlier within the SAME branch
   - For `foreach`: `{{{{ item }}}}` and `{{{{ item_index }}}}` are available

# OUTPUT INSTRUCTIONS

Return ONLY the YAML procedure definition. Do not include:
- Markdown code fences (```)
- Explanations or commentary
- Multiple alternatives

Output the single best YAML procedure for the request."""

    async def _build_data_source_context(
        self,
        session: Any,
        organization_id: UUID,
    ) -> str:
        """
        Build context about available data sources for the organization.

        Fetches SharePoint sync configs, SAM searches, Salesforce connections, etc.
        so the AI knows what specific resources are available.

        Args:
            session: Database session
            organization_id: Organization UUID

        Returns:
            str: Formatted context string to append to system prompt
        """
        from sqlalchemy import select
        from ..database.models import SharePointSyncConfig, SamSearch, SalesforceConnection

        lines = ["\n# AVAILABLE DATA SOURCES\n"]
        lines.append("Use these specific IDs when the user references a data source by name.\n")

        # Fetch SharePoint sync configs
        try:
            result = await session.execute(
                select(SharePointSyncConfig)
                .where(SharePointSyncConfig.organization_id == organization_id)
                .where(SharePointSyncConfig.is_active == True)
            )
            sharepoint_configs = result.scalars().all()

            if sharepoint_configs:
                lines.append("## SharePoint Sync Configurations")
                lines.append("Use `sync_config_id` parameter in `search_assets` to search a specific SharePoint site.\n")
                lines.append("| Name | ID | Description | Folder |")
                lines.append("|------|-----|-------------|--------|")
                for config in sharepoint_configs:
                    desc = (config.description or "")[:50]
                    folder = config.folder_name or config.folder_url or ""
                    lines.append(f"| {config.name} | `{config.id}` | {desc} | {folder} |")
                lines.append("")
                lines.append("**Example - Search specific SharePoint site:**")
                lines.append("```yaml")
                lines.append("- name: search_growth_sharepoint")
                lines.append("  function: search_assets")
                lines.append("  params:")
                lines.append("    query: \"contract proposal\"")
                lines.append("    source_type: sharepoint")
                lines.append(f"    sync_config_id: \"{sharepoint_configs[0].id}\"  # {sharepoint_configs[0].name}")
                lines.append("```")
                lines.append("")
        except Exception as e:
            logger.warning(f"Failed to fetch SharePoint configs: {e}")

        # Fetch SAM searches
        try:
            result = await session.execute(
                select(SamSearch)
                .where(SamSearch.organization_id == organization_id)
                .where(SamSearch.is_active == True)
            )
            sam_searches = result.scalars().all()

            if sam_searches:
                lines.append("## SAM.gov Saved Searches")
                lines.append("These are pre-configured SAM.gov searches. Users may reference them by name.\n")
                lines.append("| Name | Description |")
                lines.append("|------|-------------|")
                for search in sam_searches:
                    desc = (search.description or "")[:60]
                    lines.append(f"| {search.name} | {desc} |")
                lines.append("")
        except Exception as e:
            logger.warning(f"Failed to fetch SAM searches: {e}")

        # Fetch Salesforce connections
        try:
            result = await session.execute(
                select(SalesforceConnection)
                .where(SalesforceConnection.organization_id == organization_id)
                .where(SalesforceConnection.is_active == True)
            )
            sf_connections = result.scalars().all()

            if sf_connections:
                lines.append("## Salesforce Connections")
                lines.append("| Name | Instance URL |")
                lines.append("|------|--------------|")
                for conn in sf_connections:
                    lines.append(f"| {conn.name} | {conn.instance_url or 'N/A'} |")
                lines.append("")
        except Exception as e:
            logger.warning(f"Failed to fetch Salesforce connections: {e}")

        if len(lines) <= 2:
            # No data sources found
            return ""

        return "\n".join(lines)

    def _build_error_feedback_message(
        self,
        validation_errors: List[Dict[str, Any]],
    ) -> str:
        """
        Build an error feedback message for the conversation history.

        Args:
            validation_errors: List of validation errors

        Returns:
            str: Error feedback message to add to conversation
        """
        error_descriptions = []
        for err in validation_errors:
            error_descriptions.append(
                f"- {err['code']} at `{err['path']}`: {err['message']}"
            )

        return f"""That YAML failed validation with the following errors:

{chr(10).join(error_descriptions)}

Please fix these errors and return the corrected YAML. Remember:
- UNKNOWN_FUNCTION: Use only functions from the catalog in the system prompt
- MISSING_REQUIRED_PARAM: Add the missing required parameter to the step
- INVALID_STEP_REFERENCE: Only reference steps that come BEFORE the current step
- INVALID_PARAM_REFERENCE: Only reference parameters defined in the procedure's parameters section
- CONTRADICTORY_PARAMETER: A parameter cannot have both `required: true` and a `default` value
- MISSING_REQUIRED_BRANCH: Flow functions require specific branches:
  * if_branch needs `branches.then`
  * foreach needs `branches.each`
- INSUFFICIENT_BRANCHES: parallel requires at least 2 branches, switch_branch needs at least 1 case
- EMPTY_BRANCH: Each branch must contain at least one step

Return ONLY the corrected YAML."""

    def _build_warning_feedback_message(
        self,
        warnings: List[Dict[str, Any]],
    ) -> str:
        """
        Build a warning feedback message for the conversation history.

        Unlike errors, warnings don't block validation but indicate potential issues.
        The LLM gets one chance to review and fix them.

        Args:
            warnings: List of validation warnings

        Returns:
            str: Warning feedback message to add to conversation
        """
        warning_descriptions = []
        for warn in warnings:
            details = warn.get("details", {})
            suggestion = details.get("suggestion", "")
            warning_descriptions.append(
                f"- {warn['code']} at `{warn['path']}`: {warn['message']}"
            )
            if suggestion:
                warning_descriptions.append(f"  Suggestion: {suggestion}")

        return f"""The YAML is valid but has the following warnings that may indicate issues:

{chr(10).join(warning_descriptions)}

These warnings suggest you may be using the wrong function for the task. Please review:

1. If the warnings are correct and you made a mistake, fix the YAML and return the corrected version.
2. If you intentionally chose this function and the warnings are false positives, return the YAML unchanged.

IMPORTANT: Only return the YAML, no explanations. If you're keeping it unchanged, return the exact same YAML."""

    async def generate_procedure(
        self,
        prompt: str,
        organization_id: Optional[UUID] = None,
        session: Optional[Any] = None,
        include_examples: bool = True,
        current_yaml: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate or refine a procedure YAML from a natural language prompt.

        **Generate mode** (current_yaml=None):
        Creates a new procedure definition based on the user's requirements.

        **Refine mode** (current_yaml provided):
        Modifies an existing procedure based on the user's change request.

        The generated YAML is automatically validated, and if validation fails,
        the service will retry with error feedback up to MAX_RETRIES times.

        Args:
            prompt: Natural language description of the desired procedure,
                    or description of changes to make (in refine mode)
            organization_id: Optional organization ID for LLM connection lookup
            session: Optional database session for LLM connection lookup
            include_examples: Whether to include example procedures in context
            current_yaml: Optional existing procedure YAML to refine

        Returns:
            Dict with keys:
                - success (bool): Whether generation succeeded
                - yaml (str): Generated/modified YAML content (if successful)
                - procedure (dict): Parsed procedure definition (if successful)
                - error (str): Error message (if failed)
                - attempts (int): Number of attempts made
                - validation_errors (list): Final validation errors (if failed)
                - validation_warnings (list): Any remaining warnings after LLM review

        Raises:
            No exceptions are raised; errors are returned in the result dict.

        Example (generate):
            >>> result = await service.generate_procedure(
            ...     prompt="Create a procedure that emails a weekly summary"
            ... )

        Example (refine):
            >>> result = await service.generate_procedure(
            ...     prompt="Add a logging step before the email",
            ...     current_yaml=existing_procedure_yaml
            ... )
        """
        if not llm_service.is_available:
            return {
                "success": False,
                "error": "LLM service is not available. Please configure an LLM connection.",
                "attempts": 0,
                "validation_errors": [],
            }

        # Build system prompt with function catalog
        system_prompt = self._build_system_prompt()

        # Add data source context if session and org_id are provided
        if session and organization_id:
            try:
                data_source_context = await self._build_data_source_context(
                    session, organization_id
                )
                if data_source_context:
                    system_prompt += data_source_context
            except Exception as e:
                logger.warning(f"Failed to build data source context: {e}")

        # Build user prompt based on mode (generate vs refine)
        if current_yaml:
            # Refine mode - modify existing procedure
            user_prompt = f"""Here is an existing procedure definition:

```yaml
{current_yaml}
```

Please modify this procedure according to the following instructions:

{prompt}

Return the complete modified YAML procedure. Keep all existing functionality unless the instructions specifically ask to remove or change it."""
            logger.info("Refine mode: modifying existing procedure")
        else:
            # Generate mode - create new procedure
            user_prompt = f"""Create a procedure YAML for the following requirement:

{prompt}"""
            logger.info("Generate mode: creating new procedure")

        # Initialize conversation history - maintains context across retries
        # This allows the LLM to see its previous attempts and the errors
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        attempt = 0
        last_yaml = ""
        last_errors: List[Dict[str, Any]] = []
        warnings_reviewed = False  # Track if we've already given LLM a chance to fix warnings

        while attempt < self.MAX_RETRIES:
            attempt += 1
            logger.info(f"Procedure generation attempt {attempt}/{self.MAX_RETRIES}")

            try:
                # Call LLM
                if llm_service._client is None:
                    return {
                        "success": False,
                        "error": "LLM client not initialized",
                        "attempts": attempt,
                        "validation_errors": [],
                    }

                # Get model from config
                model = llm_service._get_model()

                # Run LLM call in thread pool
                def _sync_generate():
                    return llm_service._client.chat.completions.create(
                        model=model,
                        messages=messages,
                        max_tokens=4000,
                        temperature=0.2,  # Low temperature for consistent, structured output
                    )

                response = await asyncio.to_thread(_sync_generate)
                generated_yaml = response.choices[0].message.content.strip()

                # Clean up response - remove markdown code fences if present
                generated_yaml = self._clean_yaml_response(generated_yaml)
                last_yaml = generated_yaml

                # Parse YAML
                try:
                    procedure_dict = yaml.safe_load(generated_yaml)
                except yaml.YAMLError as e:
                    last_errors = [{
                        "code": "INVALID_YAML_SYNTAX",
                        "path": "",
                        "message": f"YAML parsing error: {str(e)}",
                        "details": {},
                    }]
                    logger.warning(f"Attempt {attempt}: YAML parse error: {e}")
                    # Add failed attempt to conversation history for context
                    messages.append({"role": "assistant", "content": generated_yaml})
                    messages.append({"role": "user", "content": self._build_error_feedback_message(last_errors)})
                    continue

                if not isinstance(procedure_dict, dict):
                    last_errors = [{
                        "code": "INVALID_YAML_STRUCTURE",
                        "path": "",
                        "message": "Generated content is not a valid YAML dictionary",
                        "details": {},
                    }]
                    logger.warning(f"Attempt {attempt}: Not a dictionary")
                    # Add failed attempt to conversation history for context
                    messages.append({"role": "assistant", "content": generated_yaml})
                    messages.append({"role": "user", "content": self._build_error_feedback_message(last_errors)})
                    continue

                # Validate procedure
                validation_result = validate_procedure(procedure_dict)

                if validation_result.valid:
                    # Check for warnings - give LLM one chance to review and fix
                    if validation_result.warnings and not warnings_reviewed:
                        warnings_reviewed = True
                        last_warnings = [w.to_dict() for w in validation_result.warnings]
                        logger.info(
                            f"Attempt {attempt}: Valid but has {len(last_warnings)} warning(s), "
                            "giving LLM chance to review"
                        )
                        # Add to conversation for LLM to review
                        messages.append({"role": "assistant", "content": generated_yaml})
                        messages.append({"role": "user", "content": self._build_warning_feedback_message(last_warnings)})
                        continue  # Give LLM another attempt to fix warnings

                    # Success - either no warnings, or warnings already reviewed
                    logger.info(f"Procedure generated successfully after {attempt} attempt(s)")
                    return {
                        "success": True,
                        "yaml": generated_yaml,
                        "procedure": procedure_dict,
                        "attempts": attempt,
                        "validation_errors": [],
                        "validation_warnings": [w.to_dict() for w in validation_result.warnings],
                    }
                else:
                    # Validation failed - store errors for retry
                    last_errors = [e.to_dict() for e in validation_result.errors]
                    logger.warning(
                        f"Attempt {attempt}: Validation failed with {len(last_errors)} errors"
                    )
                    # Add failed attempt to conversation history for context
                    # This lets the LLM see what it tried and what went wrong
                    messages.append({"role": "assistant", "content": generated_yaml})
                    messages.append({"role": "user", "content": self._build_error_feedback_message(last_errors)})

            except Exception as e:
                logger.error(f"Attempt {attempt}: Generation error: {e}")
                last_errors = [{
                    "code": "GENERATION_ERROR",
                    "path": "",
                    "message": str(e),
                    "details": {},
                }]
                # For generation errors, still add context if we have yaml
                if last_yaml:
                    messages.append({"role": "assistant", "content": last_yaml})
                    messages.append({"role": "user", "content": self._build_error_feedback_message(last_errors)})

        # All retries exhausted
        logger.error(f"Procedure generation failed after {self.MAX_RETRIES} attempts")
        return {
            "success": False,
            "error": f"Failed to generate valid procedure after {self.MAX_RETRIES} attempts",
            "yaml": last_yaml,
            "attempts": attempt,
            "validation_errors": last_errors,
            "validation_warnings": [],
        }

    def _clean_yaml_response(self, response: str) -> str:
        """
        Clean up LLM response to extract pure YAML.

        Removes markdown code fences and other formatting that might
        be included in the LLM response.

        Args:
            response: Raw LLM response

        Returns:
            str: Cleaned YAML content
        """
        response = response.strip()

        # Check for ```yaml or ``` at start
        if response.startswith("```yaml"):
            response = response[7:]
        elif response.startswith("```"):
            response = response[3:]

        # Check for ``` at end
        if response.endswith("```"):
            response = response[:-3]

        return response.strip()


# Global service instance
procedure_generator_service = ProcedureGeneratorService()
