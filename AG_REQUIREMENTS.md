# Acquisition Gateway Forecast API
## Reverse-Engineered Technical Whitepaper & Implementation Guide

**Audience:** Engineering, Data Platform, and Integration Teams  
**System:** Acquisition Gateway – Forecast Tool  
**API Status:** Undocumented, publicly accessible, observed-stable  
**Methodology:** Reverse-engineered via live network inspection and payload analysis

---

## 1. Executive Summary

This document defines the effective API contract for the **Acquisition Gateway Forecast API**, which provides access to forecasted federal contracting opportunities. Although not formally published by GSA, the API is stable, JSON-based, server-side filtered, and paginated.

The API supports:
- Deterministic pagination
- Multiple filter types (single-value, multi-value, ID-based, string-based)
- Clean separation between forecast data and frontend/UI metadata

This document serves as the authoritative internal reference until an official API is released.

---

## 2. Base Endpoint

```
GET https://ag-dashboard.acquisitiongateway.gov/api/v3.0/resources/forecast
```

**Notes:**
- No authentication required
- Responses are JSON
- `_gl` query parameter observed in browser traffic is Google Analytics noise and should be omitted

---

## 3. Pagination Model

Each response includes pagination metadata:

```json
"total": "577",
"count": 25
```

| Field | Meaning |
|-----|--------|
| `total` | Total records matching current filters |
| `count` | Records returned in this response (page size) |

Pagination is page-number based:

```
&page=<N>
```

- Page numbering is effectively **1-based**
- Page 1 is returned when `page` is omitted
- Page size is fixed server-side (observed: 25)

### Calculating Required Calls

```
total_pages = ceil(total / count)
```

**Example:**
- total = 577
- count = 25
- total_pages = 24

### Recommended Crawl Strategy

1. Request page 1
2. Read `total` and `count`
3. Calculate total pages
4. Iterate pages 1 → total_pages
5. Stop early if `count == 0` or `count < page_size`

---

## 4. Response Structure Overview

The response contains both **frontend metadata** and **forecast data**.

```
{
  banner: {...},        // UI only
  navigation: {...},    // UI only
  menu: {...},          // UI only
  filters: {...},       // filter metadata & taxonomy options
  listing: {
    data: {...},        // FORECAST RECORDS
    total: "...",
    count: 25
  }
}
```

Only `listing.data` should be treated as system-of-record data.

---

## 5. Forecast Record Data Model

Each forecasted opportunity appears under:

```
listing.data[<node_id>]
```

### Canonical Fields (Machine-Readable)

Located under:

```
listing.data[*].values
```

| Field | Description |
|------|------------|
| `nid` | Unique forecast record ID |
| `title` | Opportunity title |
| `body` | Opportunity description |
| `field_result_id` | Agency ID |
| `field_organization` | Contracting office |
| `field_place_of_performance` | Location |
| `field_naics_code` | NAICS taxonomy IDs |
| `field_estimated_award_fy` | Fiscal year |
| `field_estimated_contract_v_max` | Value range |
| `field_award_status` | Lifecycle stage |
| `field_contract_type` | Contract type |
| `field_acquisition_strategy` | Set-aside / strategy |
| `field_period_of_performance` | Date range |

### Rendered Fields (Ignore)

```
listing.data[*].render
```

Contains HTML/UI formatting only. Do not persist.

### 5.3 Forecast Record Schema (Normalized)

The following schema represents a **normalized, implementation-ready view** of a forecast record derived from `listing.data[*].values`. This schema intentionally excludes UI-only fields and rendered HTML.

```json
{
  "nid": "string",                      // Unique forecast record ID
  "title": "string",                    // Opportunity title
  "description": "string",              // Opportunity description (body)
  "agency": {
    "id": "integer",                    // Agency ID (field_result_id)
    "name": "string|null"               // Optional resolved agency name
  },
  "contracting_office": {
    "id": "integer|null",
    "name": "string|null"
  },
  "place_of_performance": {
    "country": "string|null",
    "state": "string|null"
  },
  "naics": [
    {
      "id": "integer",
      "code": "string|null",
      "description": "string|null"
    }
  ],
  "estimated_award": {
    "fiscal_year": "integer|null",
    "value_range_id": "integer|null"
  },
  "award_status": "string|null",         // e.g., 'Solicitation Issued'
  "contract_type": "string|null",
  "acquisition_strategies": [
    {
      "id": "integer",
      "name": "string|null"
    }
  ],
  "period_of_performance": {
    "start_date": "date|null",
    "end_date": "date|null"
  },
  "source": {
    "system": "Acquisition Gateway",
    "last_retrieved": "datetime"
  }
}
```

**Schema Notes:**
- All taxonomy-based fields (agency, NAICS, acquisition strategy) should store both the numeric ID and a resolved display value where available
- Arrays represent multi-value fields as supported by the API
- Nullable fields reflect optional or inconsistently populated data in source records
- This schema is suitable for relational storage, document databases, or downstream analytics

---

## 6. Filtering Model (Core)

Filters are applied via query parameters using Drupal-style semantics.

### 6.1 Agency Filtering (Single-Value, ID-Based)

```
filter[field_result_id_target_id]=<AGENCY_ID>
```

#### Observed Agency ID Mapping

| Agency | ID |
|-------|----|
| General Services Administration | 2 |
| Department of the Interior | 4 |
| Department of Labor | 5 |
| Small Business Administration | 6 |
| Office of Personnel Management | 7 |
| Department of Veterans Affairs | 8 |
| Department of Commerce | 13 |
| Social Security Administration | 14 |
| Department of Health and Human Services | 15 |
| Nuclear Regulatory Commission | 17 |
| Federal Communications Commission | 19 |
| Department of Transportation | 20 |
| Department of State | 21 |

**Source of truth:**  
IDs originate from the Forecast UI taxonomy. The HTML `id` attribute maps directly to the filter value.

---

### 6.2 NAICS Code Filtering (Multi-Value, ID-Based)

```
filter[field_naics_code_target_id][]=<NAICS_ID>
```

Example:
```
filter[field_naics_code_target_id][]=4685
filter[field_naics_code_target_id][]=679
```

**Behavior:**
- Multi-value **OR**
- Server-side
- Composable with all other filters

---

### 6.3 Award Status Filtering (Single-Value, String-Based)

```
filter[field_award_status_target_id]=<STATUS_VALUE>
```

Example:
```
filter[field_award_status_target_id]=Option%20Ended-Closed%20Out
```

#### Observed Values

| Status |
|-------|
| Awarded |
| Cancelled |
| Draft Solicitation |
| Evaluation Stage |
| Exercise of Option |
| Option Ended-Closed Out |
| Acquisition Planning |
| Solicitation Issued |

**Behavior:**
- Single-value only
- String-based (case- and spacing-sensitive)
- URL encoding required
- No `[]` support observed

---

### 6.4 Acquisition Strategy Filtering (Multi-Value, ID-Based)

```
filter[field_acquisition_strategy_target_id][]=<STRATEGY_ID>
```

Example:
```
filter[field_acquisition_strategy_target_id][]=5396
filter[field_acquisition_strategy_target_id][]=5397
```

#### Observed Strategy ID Mapping (Partial)

| ID | Strategy |
|----|---------|
| 5395 | 8(a) Competitive |
| 444 | 8(a) Sole Source |
| 5396 | 8(a) with HUB Zone Preference |
| 5397 | 8A Competed |
| 5398 | Buy Indian |
| 5399 | Combination HUBZone and 8(a) |
| 446 | EDWOSB |
| 5051 | HUBZone |
| 447 | HUBZone Sole Source |
| 5054 | Other Than Small Business |
| 462 | Small Business |
| 460 | Small Business Set Aside - Total |
| 466 | Women-owned Small Business (WOSB) |
| 4749 | To Be Determined |

**Behavior:**
- Multi-value **OR**
- Numeric ID-based
- Fully composable

---

## 7. Filter Semantics Summary

| Filter | Identifier | Multi-Value | Notes |
|------|------------|------------|------|
| Agency | Numeric ID | No | Entity reference |
| NAICS | Numeric ID | Yes | Entity reference |
| Award Status | String | No | Taxonomy label |
| Acquisition Strategy | Numeric ID | Yes | Taxonomy/entity |

---

## 8. Fields to Ignore Entirely

The following response sections are frontend-only:

- `banner`
- `menu`
- `navigation`
- `sidebar`
- `message`
- `search`
- `view`

---

## 9. Operational Guidance

- Treat as an internal, undocumented API
- Use conservative rate limits
- Cache taxonomy ID mappings
- Prefer scheduled batch ingestion
- Validate pagination using `total` and `count`

---

## 10. Conclusion

The Acquisition Gateway Forecast API provides a robust, well-structured backend data source for forecasted federal contracting opportunities. With deterministic pagination, composable filters, and clean data separation, it can be safely integrated into internal systems using the contract defined in this document.

This whitepaper represents the current best-known authoritative specification based on live system behavior.