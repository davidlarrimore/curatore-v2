# Salesforce CRM Integration

Curatore integrates with Salesforce CRM to provide visibility into accounts, contacts, and opportunities. This document covers the integration architecture and usage.

## Overview

The Salesforce integration allows users to:
- Connect to Salesforce organizations via OAuth
- View and search accounts, contacts, and opportunities
- Link SAM.gov solicitations to Salesforce opportunities
- Track pipeline alongside government contracting data

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        SALESFORCE INTEGRATION ARCHITECTURE                       │
└─────────────────────────────────────────────────────────────────────────────────┘

  Salesforce Org                    Curatore Database                   Frontend
       │                                  │                                │
       ▼                                  ▼                                ▼
┌─────────────────┐              ┌─────────────────┐            ┌─────────────────┐
│ OAuth Connect   │──────────────│ SalesforceConnection │        │ /salesforce     │
│                 │              │ (credentials)   │            │                 │
└─────────────────┘              └─────────────────┘            └─────────────────┘
       │                                  │                                │
       ▼                                  ▼                                ▼
┌─────────────────┐              ┌─────────────────┐            ┌─────────────────┐
│ SOQL Queries    │──────────────│ Cache/Sync      │────────────│ Accounts List   │
│ (REST API)      │              │ (optional)      │            │ Contacts List   │
└─────────────────┘              └─────────────────┘            │ Opps List       │
                                                                └─────────────────┘
```

---

## Database Models

| Model | Purpose |
|-------|---------|
| `SalesforceConnection` | OAuth credentials and org info |
| `SalesforceAccount` | Cached account data (optional) |
| `SalesforceContact` | Cached contact data (optional) |
| `SalesforceOpportunity` | Cached opportunity data (optional) |

---

## Key Service Files

| File | Purpose |
|------|---------|
| `salesforce_service.py` | Salesforce API client and CRUD operations |
| `salesforce_import_service.py` | Bulk data import and sync |

---

## API Endpoints

```
# Connection Management
GET    /api/v1/salesforce/connections              # List connections
POST   /api/v1/salesforce/connections              # Create connection
GET    /api/v1/salesforce/connections/{id}         # Get connection
DELETE /api/v1/salesforce/connections/{id}         # Delete connection
POST   /api/v1/salesforce/connections/{id}/test    # Test connection

# Accounts
GET    /api/v1/salesforce/accounts                 # List accounts
GET    /api/v1/salesforce/accounts/{id}            # Get account detail
GET    /api/v1/salesforce/accounts/{id}/contacts   # Get account contacts
GET    /api/v1/salesforce/accounts/{id}/opportunities  # Get account opps

# Contacts
GET    /api/v1/salesforce/contacts                 # List contacts
GET    /api/v1/salesforce/contacts/{id}            # Get contact detail

# Opportunities
GET    /api/v1/salesforce/opportunities            # List opportunities
GET    /api/v1/salesforce/opportunities/{id}       # Get opportunity detail
```

---

## Frontend Pages

| Page | Path | Purpose |
|------|------|---------|
| Dashboard | `/salesforce` | Salesforce overview |
| Accounts | `/salesforce/accounts` | Account list and search |
| Account Detail | `/salesforce/accounts/{id}` | Account with contacts/opps |
| Contacts | `/salesforce/contacts` | Contact list and search |
| Contact Detail | `/salesforce/contacts/{id}` | Contact details |
| Opportunities | `/salesforce/opportunities` | Pipeline view |
| Opportunity Detail | `/salesforce/opportunities/{id}` | Opportunity details |

---

## Connection Setup

1. Navigate to `/salesforce` or `/connections`
2. Click "Connect Salesforce"
3. Authenticate via Salesforce OAuth
4. Connection credentials stored securely

### Required Salesforce Permissions

The connected user needs:
- Read access to Account, Contact, Opportunity objects
- API access enabled
- (Optional) Write access for future sync features

---

## Configuration

In `config.yml`:

```yaml
salesforce:
  enabled: true
  client_id: ${SALESFORCE_CLIENT_ID}
  client_secret: ${SALESFORCE_CLIENT_SECRET}
  # Optional: sync settings
  sync:
    enabled: false
    frequency: daily
```

Environment variables:
```bash
SALESFORCE_CLIENT_ID=your_connected_app_client_id
SALESFORCE_CLIENT_SECRET=your_connected_app_client_secret
```

---

## Data Model Notes

### Accounts
- Standard Salesforce Account fields
- Industry, type, annual revenue
- Linked contacts and opportunities

### Contacts
- Standard Salesforce Contact fields
- Associated account relationship

### Opportunities
- Standard Salesforce Opportunity fields
- Stage, close date, amount
- Can be linked to SAM.gov solicitations

---

## Integration with SAM.gov

Opportunities can be linked to SAM.gov solicitations:
- Match by solicitation number
- Track proposal status alongside opportunity stage
- View related SAM.gov notices from opportunity detail

---

## Search Integration

Salesforce data is indexed to the search system:
- `source_type`: `salesforce_account`, `salesforce_contact`, `salesforce_opportunity`
- Searchable content: name, description, industry
- Unified search across all data sources
