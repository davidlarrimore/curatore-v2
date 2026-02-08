# Salesforce CRM Integration

Curatore imports Salesforce CRM data via manual data exports. Users export their Salesforce data as a ZIP file and upload it to Curatore for processing.

## Overview

The Salesforce integration allows users to:
- Import Salesforce data from Data Export ZIP files
- View and search accounts, contacts, and opportunities
- Track pipeline alongside government contracting data
- Link opportunities to SAM.gov solicitations

**Note:** This is a manual import workflow, not a live API connection. Data is imported from Salesforce's standard Data Export feature.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        SALESFORCE IMPORT WORKFLOW                                │
└─────────────────────────────────────────────────────────────────────────────────┘

  Salesforce                      Curatore                           Frontend
       │                              │                                  │
       ▼                              ▼                                  ▼
┌─────────────────┐           ┌─────────────────┐              ┌─────────────────┐
│ Data Export     │           │  Upload ZIP     │              │ /salesforce     │
│ (Setup menu)    │           │  to Curatore    │              │                 │
└─────────────────┘           └─────────────────┘              └─────────────────┘
       │                              │                                  │
       ▼                              ▼                                  ▼
┌─────────────────┐           ┌─────────────────┐              ┌─────────────────┐
│ Download ZIP    │───────────│ Import Service  │──────────────│ Accounts List   │
│ (Account.csv,   │           │ - Parse CSVs    │              │ Contacts List   │
│  Contact.csv,   │           │ - Upsert data   │              │ Opps List       │
│  Opportunity.csv│           │ - Link records  │              └─────────────────┘
└─────────────────┘           │ - Index search  │
                              └─────────────────┘
```

---

## Import Workflow

### Step 1: Export Data from Salesforce

1. In Salesforce, go to **Setup** → **Data** → **Data Export**
2. Click **Export Now** or schedule an export
3. Select objects to include:
   - Account
   - Contact
   - Opportunity
4. Wait for export to complete (you'll receive an email)
5. Download the ZIP file

### Step 2: Upload to Curatore

1. Navigate to `/salesforce` in Curatore
2. Click **Import Data**
3. Upload the ZIP file from Salesforce
4. Import processes automatically:
   - Parses Account.csv, Contact.csv, Opportunity.csv
   - Upserts records by Salesforce ID
   - Links contacts/opportunities to accounts
   - Indexes data for search

### Step 3: View Data

- Browse accounts at `/salesforce/accounts`
- Browse contacts at `/salesforce/contacts`
- Browse opportunities at `/salesforce/opportunities`

---

## Database Models

| Model | Purpose |
|-------|---------|
| `SalesforceAccount` | Account records from Salesforce |
| `SalesforceContact` | Contact records linked to accounts |
| `SalesforceOpportunity` | Opportunity records linked to accounts |

### Key Fields

**SalesforceAccount:**
- `salesforce_id` - 18-character Salesforce ID (unique)
- `name`, `account_type`, `industry`
- `billing_address`, `shipping_address` (JSONB)
- `small_business_flags` (SBA certifications: 8(a), HUBZone, WOSB, etc.)
- `parent_id` - Links to parent account

**SalesforceContact:**
- `salesforce_id` - 18-character Salesforce ID (unique)
- `first_name`, `last_name`, `email`, `title`
- `account_id` - Links to SalesforceAccount

**SalesforceOpportunity:**
- `salesforce_id` - 18-character Salesforce ID (unique)
- `name`, `stage_name`, `amount`, `close_date`
- `account_id` - Links to SalesforceAccount

---

## Key Service Files

| File | Purpose |
|------|---------|
| `backend/app/connectors/salesforce/salesforce_service.py` | CRUD operations for accounts, contacts, opportunities |
| `backend/app/connectors/salesforce/salesforce_import_service.py` | ZIP file parsing and data import |

---

## Import Processing Details

The import service handles:

1. **ZIP extraction** - Extracts CSV files from Salesforce export
2. **CSV parsing** - Handles Latin-1 encoding from Salesforce
3. **Field mapping** - Maps Salesforce field names to database columns
4. **Upsert logic** - Creates new records or updates existing by `salesforce_id`
5. **Relationship linking** - Links contacts/opportunities to accounts by `AccountId`
6. **Search indexing** - Adds records to pgvector search index

### Supported CSV Files

| File | Object |
|------|--------|
| `Account.csv` | SalesforceAccount |
| `Contact.csv` | SalesforceContact |
| `Opportunity.csv` | SalesforceOpportunity |

### Field Mappings

The import service maps standard Salesforce fields plus common custom fields:

**Account custom fields:**
- `Department__c` → department
- `SBA_8_a__c` → small business 8(a) flag
- `HubZone__c` → HUBZone certification
- `WOSB__c` → Women-Owned Small Business
- `SDVOSB__c` → Service-Disabled Veteran-Owned

**Contact custom fields:**
- `Current_Employee__c` → is_current_employee flag

---

## API Endpoints

```
# Import
POST   /api/v1/data/salesforce/import              # Upload and import ZIP file

# Accounts
GET    /api/v1/data/salesforce/accounts            # List accounts
GET    /api/v1/data/salesforce/accounts/{id}       # Get account detail
GET    /api/v1/data/salesforce/accounts/{id}/contacts      # Account contacts
GET    /api/v1/data/salesforce/accounts/{id}/opportunities # Account opportunities

# Contacts
GET    /api/v1/data/salesforce/contacts            # List contacts
GET    /api/v1/data/salesforce/contacts/{id}       # Get contact detail

# Opportunities
GET    /api/v1/data/salesforce/opportunities       # List opportunities
GET    /api/v1/data/salesforce/opportunities/{id}  # Get opportunity detail

# Dashboard
GET    /api/v1/data/salesforce/stats               # Dashboard statistics
```

---

## Frontend Pages

| Page | Path | Purpose |
|------|------|---------|
| Dashboard | `/salesforce` | Overview, import button, stats |
| Accounts | `/salesforce/accounts` | Account list and search |
| Account Detail | `/salesforce/accounts/{id}` | Account with contacts/opps |
| Contacts | `/salesforce/contacts` | Contact list and search |
| Contact Detail | `/salesforce/contacts/{id}` | Contact details |
| Opportunities | `/salesforce/opportunities` | Pipeline view |
| Opportunity Detail | `/salesforce/opportunities/{id}` | Opportunity details |

---

## Search Integration

Salesforce data is indexed for unified search:
- `source_type`: `salesforce_account`, `salesforce_contact`, `salesforce_opportunity`
- Searchable: name, description, industry, email, title

---

## Re-importing Data

When you import a new export:
- **Existing records** are updated (matched by `salesforce_id`)
- **New records** are created
- **Deleted records** in Salesforce are NOT automatically removed from Curatore

To refresh all data, import the latest export. The upsert logic ensures data stays in sync.

---

## Troubleshooting

### "No CSV files found in ZIP"
- Ensure you exported Account, Contact, and/or Opportunity objects
- Salesforce exports may include multiple ZIP files - use the one containing CSVs

### Import takes a long time
- Large exports (thousands of records) may take a few minutes
- Progress is tracked via Run records

### Missing relationships
- Contacts/Opportunities link to Accounts by `AccountId`
- If the Account wasn't included in the export, the link won't be established
- Re-import with Account.csv included to fix

### Custom field not imported
- Only mapped fields are imported (see Field Mappings above)
- Additional custom fields are stored in `raw_data` JSONB column
