# Curatore v2 - User Guide

**Version**: 2.0.0
**Last Updated**: 2026-02-02

---

## Table of Contents

1. [Introduction](#introduction)
2. [Getting Started](#getting-started)
3. [Authentication](#authentication)
4. [Connection Management](#connection-management)
5. [Document Processing](#document-processing)
6. [SharePoint Integration](#sharepoint-integration)
7. [Batch Processing](#batch-processing)
8. [Quality Assessment](#quality-assessment)
9. [Organization Management](#organization-management)
10. [User Management](#user-management)
11. [API Keys](#api-keys)
12. [Storage Management](#storage-management)
13. [Troubleshooting](#troubleshooting)

---

## Introduction

Curatore v2 is a comprehensive document processing platform designed to convert documents into RAG-ready markdown format. It supports multiple file formats, provides quality assessment using LLMs, and offers intelligent optimization for vector databases.

### Key Features

- **Multi-Format Support**: PDF, DOCX, PPTX, TXT, Images
- **Intelligent Conversion**: Multiple extraction engines with automatic fallback
- **Quality Assessment**: LLM-based evaluation with configurable thresholds
- **Multi-Tenancy**: Organization-based isolation with role-based access
- **Runtime Configuration**: Dynamic connection management for external services
- **SharePoint Integration**: Direct file access from Microsoft SharePoint
- **Hierarchical Storage**: Organized file structure with content deduplication
- **Async Processing**: Scalable job processing with Redis and Celery

### System Requirements

- **Browser**: Modern web browser (Chrome, Firefox, Safari, Edge)
- **Network**: Internet connection for LLM services and SharePoint integration
- **Permissions**: User account with appropriate role (admin, member, or viewer)

---

## Getting Started

### Accessing Curatore

1. **Open your browser** and navigate to your Curatore instance
   - Development: `http://localhost:3000`
   - Production: Your organization's Curatore URL

2. **Login** with your credentials (if authentication is enabled)
   - Email address
   - Password

3. **Dashboard** - After login, you'll see the main dashboard with:
   - Document upload interface
   - Recent documents
   - Processing queue status
   - Quick actions

### Understanding the Interface

#### Navigation Menu

- **Dashboard**: Main document processing interface
- **Documents**: View and manage processed documents
- **Connections**: Configure external service connections (admin only)
- **Users**: Manage organization users (admin only)
- **Settings**: Organization and user settings
- **API Keys**: Generate keys for programmatic access

#### User Roles

| Role | Description | Permissions |
|------|-------------|-------------|
| **Admin** | Full administrative access | All operations including user/connection management |
| **Member** | Standard user access | Document processing, view connections |
| **Viewer** | Read-only access | View documents and results only |

---

## Authentication

### First-Time Login

1. **Navigate** to the login page
2. **Enter credentials** provided by your administrator
3. **Change password** on first login (recommended)
4. **Verify email** if required

### Email Verification

If email verification is enabled:

1. **Check your email** for verification link
2. **Click the link** to verify your email address
3. **Grace period**: You may have 7 days to verify before access is restricted

### Password Reset

If you forget your password:

1. **Click "Forgot Password"** on the login page
2. **Enter your email** address
3. **Check email** for reset link (expires in 1 hour)
4. **Click the link** and enter your new password
5. **Login** with your new password

### Changing Your Password

To change your password:

1. Go to **Settings** → **Profile**
2. Click **Change Password**
3. Enter **current password**
4. Enter **new password** (twice)
5. Click **Save**

**Password Requirements**:
- Minimum 8 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one number
- At least one special character

---

## Connection Management

Connections allow Curatore to integrate with external services like SharePoint, LLM providers, and extraction services. Administrators can configure these connections at runtime without modifying code or environment variables.

### Connection Types

#### SharePoint Connection

Connect to Microsoft SharePoint for direct file access.

**Required Information**:
- **Tenant ID**: Your Azure AD tenant GUID
- **Client ID**: Azure AD application client ID
- **Client Secret**: Azure AD application secret
- **Site URL**: SharePoint site URL (optional)

**Setup Steps**:

1. **Navigate** to **Connections** → **Add Connection**
2. **Select Type**: SharePoint
3. **Fill in details**:
   ```
   Name: Production SharePoint
   Tenant ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   Client ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   Client Secret: ********************************
   Site URL: https://yourcompany.sharepoint.com/sites/docs
   ```
4. **Test Connection** (optional but recommended)
5. **Set as Default** if this is your primary SharePoint
6. **Save**

**Azure AD Setup** (Administrator):
1. Register application in Azure AD
2. Grant API permissions: `Sites.Read.All` or `Files.Read.All`
3. Create client secret
4. Grant admin consent

#### LLM Connection

Connect to OpenAI or compatible LLM providers for document evaluation.

**Required Information**:
- **API Key**: Your LLM provider API key
- **Model**: Model name (e.g., `gpt-4o-mini`, `gpt-4o`)
- **Base URL**: API endpoint (default: OpenAI)
- **Timeout**: Request timeout in seconds

**Setup Steps**:

1. **Navigate** to **Connections** → **Add Connection**
2. **Select Type**: OpenAI/LLM
3. **Fill in details**:
   ```
   Name: OpenAI GPT-4
   API Key: sk-************************************************
   Model: gpt-4o-mini
   Base URL: https://api.openai.com/v1
   Timeout: 30
   ```
4. **Test Connection**
5. **Set as Default**
6. **Save**

**Supported Providers**:
- **OpenAI**: `https://api.openai.com/v1`
- **Azure OpenAI**: `https://{resource}.openai.azure.com/openai/deployments/{deployment}/`
- **Ollama**: `http://localhost:11434/v1`
- **OpenWebUI**: `http://localhost:3000/v1`
- **LM Studio**: `http://localhost:1234/v1`

#### Extraction Connection

Connect to external extraction services for document conversion.

**Required Information**:
- **Service URL**: Extraction service endpoint
- **API Key**: Service API key (if required)
- **Timeout**: Request timeout in seconds

### Managing Connections

#### Viewing Connections

1. **Navigate** to **Connections**
2. See list of all configured connections with:
   - Connection name and type
   - Status indicator (healthy/unhealthy)
   - Last tested timestamp
   - Default connection indicator

#### Testing Connections

To verify a connection is working:

1. **Find the connection** in the list
2. **Click "Test Connection"**
3. **View results**: Success or error message
4. **Check details**: Response time, service status

#### Editing Connections

1. **Click on connection** to view details
2. **Click "Edit"**
3. **Modify settings** as needed
4. **Test connection** after changes
5. **Save**

**Note**: Credentials are stored securely and cannot be viewed after initial creation.

#### Deleting Connections

1. **Click on connection**
2. **Click "Delete"**
3. **Confirm deletion**

**Warning**: Deleting a default connection may affect document processing. Set a new default connection before deleting.

#### Setting Default Connections

Each connection type can have one default connection:

1. **Find the connection** you want to make default
2. **Click "Set as Default"**
3. **Confirm** if replacing existing default

Default connections are automatically used for:
- Document processing (LLM)
- SharePoint file access
- Extraction operations

---

## Document Processing

### Uploading Documents

#### Single Document Upload

1. **Navigate** to **Dashboard**
2. **Click "Upload Document"** or drag and drop
3. **Select file** from your computer
4. **Wait for upload** to complete
5. **Document appears** in "Uploaded Documents" list

#### Supported Formats

| Format | Extension | Max Size | Notes |
|--------|-----------|----------|-------|
| PDF | `.pdf` | 50 MB | Best results with text-based PDFs |
| Word | `.docx` | 50 MB | Tables and images preserved |
| PowerPoint | `.pptx` | 50 MB | Slide content extracted |
| Text | `.txt` | 10 MB | Plain text processing |
| Images | `.png`, `.jpg`, `.jpeg` | 20 MB | OCR applied automatically |

### Processing Documents

After uploading, process the document:

1. **Click "Process"** on the uploaded document
2. **Configure options**:
   - **Optimize for RAG**: Enable content optimization
   - **Evaluate Quality**: Run LLM quality assessment
   - **Quality Thresholds**: Set minimum quality scores

3. **Click "Start Processing"**
4. **Monitor progress**:
   - 🟡 Pending: Waiting for worker
   - 🔵 Processing: Currently converting
   - 🟢 Complete: Processing successful
   - 🔴 Failed: Processing error

### Processing Options

#### Optimize for RAG

When enabled, Curatore optimizes the markdown output for RAG (Retrieval Augmented Generation) systems:

- **Section headers**: Ensures clear document structure
- **Table formatting**: Preserves table data in readable format
- **Image descriptions**: Adds context for images
- **Metadata extraction**: Pulls key information to the top
- **Chunk boundaries**: Optimizes for vector database chunking

**Recommendation**: Enable for documents that will be used with LLMs or vector databases.

#### Quality Evaluation

When enabled, Curatore uses an LLM to evaluate document quality across multiple dimensions:

- **Clarity** (1-10): How clear and well-structured is the content?
- **Completeness** (1-10): Is all content successfully extracted?
- **Relevance** (1-10): Is the content relevant and focused?
- **Markdown Quality** (1-10): How well-formatted is the markdown?

**Overall Quality Score**: 0-100 composite score

**Recommendation**: Enable for important documents or when quality matters.

#### Quality Thresholds

Set minimum acceptable scores:

- **Conversion Threshold** (0-100): Minimum overall quality
- **Clarity Threshold** (1-10): Minimum clarity score
- **Completeness Threshold** (1-10): Minimum completeness score

Documents below thresholds are flagged for review.

### Viewing Results

After processing completes:

1. **Click on document** to view details
2. **Tabs available**:
   - **Preview**: Rendered markdown preview
   - **Raw**: Raw markdown content
   - **Metadata**: Document metadata and statistics
   - **Quality**: Quality assessment results
   - **Processing Log**: Detailed processing logs

3. **Quality Assessment** shows:
   - Overall quality score with color coding:
     - 🟢 Green: 80-100 (Excellent)
     - 🟡 Yellow: 60-79 (Good)
     - 🟠 Orange: 40-59 (Fair)
     - 🔴 Red: 0-39 (Poor)
   - Individual dimension scores
   - LLM recommendations
   - Processing statistics

### Downloading Results

#### Download Markdown

1. **Click "Download"** button
2. **Select format**:
   - **Markdown (.md)**: Standard markdown file
   - **Text (.txt)**: Plain text version
   - **JSON (.json)**: Full result with metadata

#### Bulk Download

To download multiple documents:

1. **Select documents** using checkboxes
2. **Click "Download Selected"**
3. **Choose format**:
   - **Individual files**: Separate .md files in ZIP
   - **Combined**: Single merged markdown file
   - **RAG-ready**: Only documents meeting quality thresholds

---

## SharePoint Integration

### Overview

Curatore provides automatic synchronization with Microsoft SharePoint folders. Once configured, files are automatically imported, extracted, and indexed. The sync system supports efficient incremental updates using Microsoft Graph delta queries.

### Prerequisites

- Microsoft Graph API connection configured (admin) with SharePoint permissions
- Permissions to access target SharePoint site/folder
- SharePoint folder URL

### Setting Up a SharePoint Sync

1. **Navigate** to **SharePoint Sync** in the sidebar
2. **Click "New Sync Configuration"**
3. **Select a Microsoft Graph connection** (must have SharePoint permissions)
4. **Enter the SharePoint folder URL**:
   ```
   https://yourcompany.sharepoint.com/sites/docs/Shared Documents/Reports
   ```
5. **Configure sync settings**:
   - **Name**: Descriptive name for the sync configuration
   - **Description**: Optional description
   - **Sync Frequency**: Manual, Hourly, or Daily

6. **Click "Create"** to set up the sync configuration

### Sync Types

#### Full Sync

A full sync downloads and processes all files in the configured SharePoint folder:

- **When to use**: First-time sync, recovering from errors, or ensuring complete synchronization
- **How it works**: Enumerates all files in the folder and subfolders, downloads each file, and creates assets
- **Duration**: Depends on folder size; can take a long time for large folders
- **Result**: Establishes a delta token for future incremental syncs

#### Incremental Sync

An incremental sync only processes changes since the last sync:

- **When to use**: Regular ongoing synchronization (most common)
- **Requirement**: A full sync must complete first to establish a delta token
- **How it works**: Uses Microsoft Graph delta queries to detect only new, modified, or deleted files
- **Efficiency**: Much faster than full sync - only processes changes
- **UI Note**: The "Incremental Sync" button is disabled until a full sync completes

### Running a Sync

1. **Navigate** to your sync configuration detail page
2. **Choose sync type**:
   - **Full Sync**: Downloads all files (use for first sync or recovery)
   - **Incremental Sync**: Only processes changes (requires completed full sync)

3. **Monitor progress** in the Job Manager or on the sync configuration page
4. **View results**: Synced files appear as assets and are automatically extracted and indexed

### Sync Status and Monitoring

The sync configuration page shows:

- **Sync Status**: Active, Syncing, Archived, or Deleting
- **Last Sync**: When the last sync completed
- **Statistics**:
  - Total synced files
  - Deleted files detected
  - Failed files
  - Storage size

- **Sync History**: Recent sync jobs with status and duration

### Handling Long-Running Syncs

For large SharePoint folders, syncs may run for extended periods. The system includes:

- **Automatic Token Refresh**: Microsoft Graph tokens (1-hour expiry) are automatically refreshed during long syncs
- **Retry Logic**: Transient network errors (disconnects, timeouts) automatically retry with 30-second delays
- **Progress Tracking**: Real-time progress updates in the Job Manager
- **Cancellation**: Jobs can be cancelled from the Job Manager if needed

### File Change Detection

When using incremental sync, the system detects:

- **New files**: Automatically downloaded and processed
- **Modified files**: Re-downloaded and a new asset version created
- **Deleted files**: Marked as deleted (assets preserved for audit trail)
- **Moved/renamed files**: Detected and tracked appropriately

### Managing Sync Configurations

#### Enabling/Disabling Sync

- **Disable**: Pauses automatic syncs while preserving configuration and files
- **Enable**: Resumes sync capability

#### Archiving

- **Archive**: Stops syncing and removes files from search index
- **Archived files** remain accessible but won't appear in search results

#### Deleting

- **Delete**: Permanently removes sync configuration and all associated assets
- **Warning**: This action is irreversible

### SharePoint Sync Best Practices

- **Start with Full Sync**: Always run a full sync first to establish the delta token baseline
- **Use Incremental for Regular Syncs**: After the initial full sync, use incremental syncs for efficiency
- **Monitor Large Syncs**: For folders with thousands of files, monitor progress in Job Manager
- **Test with Small Folders**: Start with a small folder to verify configuration before large syncs
- **Use Appropriate Frequency**: Set sync frequency based on how often files change
- **Review Sync Errors**: Check failed files and sync errors in the configuration detail page

### Troubleshooting SharePoint Sync

#### Incremental Sync Button Disabled

**Cause**: No full sync has completed yet (no delta token)

**Solution**: Run a Full Sync first to establish the baseline

#### Sync Fails with Authentication Error

**Cause**: Token expired or connection permissions changed

**Solutions**:
1. Verify Microsoft Graph connection is still valid
2. Test the connection in Connection Management
3. Re-authorize if permissions were revoked

#### Sync Stuck or Taking Too Long

**Cause**: Large folder, network issues, or SharePoint throttling

**Solutions**:
1. Check Job Manager for progress updates
2. Cancel and retry if no progress for extended period
3. Check if SharePoint site has throttling limits
4. For very large folders, consider syncing subfolders separately

#### Files Not Appearing After Sync

**Cause**: Extraction still in progress or failed

**Solutions**:
1. Check the asset status in the sync configuration detail page
2. View extraction queue in Job Manager
3. Check for extraction errors on individual assets

---

## Batch Processing

### Overview

Batch processing allows you to process multiple documents simultaneously, ideal for large document collections.

### Creating a Batch

#### Option 1: Upload Multiple Files

1. **Navigate** to **Dashboard** → **Batch Upload**
2. **Drag and drop** multiple files or **click to browse**
3. **Select multiple files** (up to 100 at once)
4. **Upload** all files
5. **Batch created** automatically

#### Option 2: SharePoint Download

1. **List SharePoint files** (see SharePoint Integration)
2. **Download selected files**
3. **Batch created** automatically from downloads

#### Option 3: Manual Batch Directory

1. **Place files** in batch directory:
   ```
   /app/files/batch_files/
   ```
2. **System detects** files automatically
3. **Batch appears** in Batch Processing list

### Processing a Batch

1. **Navigate** to **Batch Processing**
2. **Find your batch** in the list
3. **Click "Process Batch"**
4. **Configure batch options**:
   - **Optimize for RAG**: Apply to all documents
   - **Evaluate Quality**: Assess all documents
   - **Quality Thresholds**: Same for all documents
   - **Parallel Workers**: Number of concurrent jobs

5. **Click "Start Processing"**
6. **Monitor progress**:
   - Overall completion percentage
   - Individual document status
   - Failed document count

### Monitoring Batch Progress

The batch view shows:

- **Progress Bar**: Visual completion indicator
- **Statistics**:
  - Total documents
  - Completed: ✅
  - Processing: 🔵
  - Failed: ❌
  - Pending: 🟡

- **Document List**:
  - File name
  - Status
  - Quality score (if evaluated)
  - Processing time

### Downloading Batch Results

After batch processing:

1. **Click "Download Batch Results"**
2. **Choose format**:
   - **All Files**: Every document in batch
   - **Successful Only**: Exclude failed documents
   - **High Quality Only**: Only documents meeting thresholds
   - **Combined**: Single merged document

3. **Select structure**:
   - **Individual Files**: Separate .md files in ZIP
   - **Organized**: Folder structure by quality/status

### Batch Processing Best Practices

- **Test with small batches** first (5-10 documents)
- **Set appropriate thresholds** for your use case
- **Monitor disk space** for large batches
- **Use parallel workers** wisely (default: 4)
- **Review failed documents** individually if needed
- **Clean up batches** after downloading results

---

## Quality Assessment

### Understanding Quality Scores

Curatore evaluates document quality across four dimensions:

#### 1. Clarity (1-10)

**Measures**: How clear and well-structured is the content?

- **10**: Perfectly clear, logical structure
- **7-9**: Clear with minor issues
- **4-6**: Moderately clear, some confusion
- **1-3**: Unclear, poorly structured

**Factors**:
- Section organization
- Heading hierarchy
- Paragraph structure
- Readability

#### 2. Completeness (1-10)

**Measures**: Is all content successfully extracted?

- **10**: All content extracted perfectly
- **7-9**: Minor content missing
- **4-6**: Some content missing
- **1-3**: Major content loss

**Factors**:
- Text extraction accuracy
- Table preservation
- Image capture
- Metadata extraction

#### 3. Relevance (1-10)

**Measures**: Is the content relevant and focused?

- **10**: Highly relevant, well-focused
- **7-9**: Mostly relevant
- **4-6**: Some irrelevant content
- **1-3**: Mostly irrelevant

**Factors**:
- Content quality
- Signal-to-noise ratio
- Topic consistency
- Information value

#### 4. Markdown Quality (1-10)

**Measures**: How well-formatted is the markdown?

- **10**: Perfect markdown formatting
- **7-9**: Minor formatting issues
- **4-6**: Some formatting problems
- **1-3**: Poor formatting

**Factors**:
- Syntax correctness
- Heading structure
- List formatting
- Table formatting
- Code block formatting

### Overall Quality Score (0-100)

Composite score combining all dimensions:

- **90-100**: Excellent - Ready for production use
- **80-89**: Very Good - Minor improvements may help
- **70-79**: Good - Usable with some limitations
- **60-69**: Fair - Review recommended
- **Below 60**: Poor - Manual review or reprocessing needed

### Setting Quality Thresholds

Configure minimum acceptable scores:

1. **Navigate** to **Settings** → **Quality Thresholds**
2. **Set thresholds**:
   ```
   Conversion Threshold: 70 (overall score)
   Clarity Threshold: 7
   Completeness Threshold: 7
   Relevance Threshold: 6
   Markdown Quality Threshold: 7
   ```
3. **Save settings**

**Use Cases**:

- **High-stakes content** (legal, medical): Set high thresholds (80+)
- **General purpose**: Medium thresholds (70+)
- **Exploratory**: Low thresholds (50+) to capture more documents

### Improving Quality Scores

If documents score low:

#### Low Clarity
- **Original file**: Improve source document structure
- **Processing**: Enable RAG optimization
- **Post-processing**: Manually edit markdown

#### Low Completeness
- **File format**: Try different format (e.g., DOCX instead of PDF)
- **Extraction engine**: Try Docling for complex documents
- **Source quality**: Ensure original isn't corrupted or image-based

#### Low Relevance
- **Content**: Verify source document is appropriate
- **Extraction**: May be extracting headers/footers/metadata
- **Processing**: Use preprocessing to remove boilerplate

#### Low Markdown Quality
- **Optimization**: Enable RAG optimization
- **Engine**: Try different extraction engine
- **Post-processing**: Clean up markdown manually

---

## Organization Management

**Note**: Admin-only functionality

### Viewing Organization Details

1. **Navigate** to **Settings** → **Organization**
2. **View information**:
   - Organization name
   - Organization slug
   - Created date
   - User count
   - Active connections
   - Storage usage

### Editing Organization Settings

1. **Click "Edit Organization"**
2. **Modify settings**:
   - Organization name
   - Display preferences
   - Default quality thresholds
   - Storage retention policies

3. **Save changes**

### Organization Settings

#### Default Quality Thresholds

Set default quality thresholds for all users:

```
Conversion Threshold: 70
Clarity Threshold: 7
Completeness Threshold: 7
Relevance Threshold: 7
Markdown Quality Threshold: 7
```

Users can override these per-document if needed.

#### Storage Retention Policies

Configure automatic file cleanup:

```
Uploaded Files: 30 days
Processed Files: 90 days
Batch Files: 60 days
Temporary Files: 1 day
```

Files older than retention period are automatically deleted.

#### Deduplication Settings

Configure content-based deduplication:

```
Enable Deduplication: Yes
Hash Algorithm: SHA-256
Auto-Dedupe on Upload: Yes
```

Duplicate files share storage, saving space.

---

## User Management

**Note**: Admin-only functionality

### Viewing Users

1. **Navigate** to **Users**
2. **See user list**:
   - Username and email
   - Role
   - Status (active/inactive)
   - Last login
   - Email verification status

### Inviting Users

1. **Click "Invite User"**
2. **Fill in details**:
   ```
   Email: newuser@example.com
   Username: newuser
   Full Name: New User
   Role: member
   ```
3. **Send Invitation**
4. **User receives email** with setup link

### Editing Users

1. **Click on user** to view details
2. **Click "Edit"**
3. **Modify**:
   - Full name
   - Role
   - Active status

4. **Save changes**

**Note**: Cannot change email after creation

### Deactivating Users

To temporarily disable a user:

1. **Click on user**
2. **Click "Deactivate"**
3. **Confirm**

User cannot login but data is preserved.

To reactivate:
1. **Click on user**
2. **Click "Reactivate"**

### Deleting Users

To permanently remove a user:

1. **Click on user**
2. **Click "Delete"**
3. **Confirm deletion**
4. **User data handling**:
   - User account removed
   - Documents remain (ownership transferred)
   - Audit logs preserved

### Resetting User Passwords

1. **Click on user**
2. **Click "Reset Password"**
3. **Choose method**:
   - **Send reset email**: User receives password reset link
   - **Set temporary password**: Generate temporary password to share with user

---

## API Keys

### Overview

API keys enable programmatic access to Curatore without requiring username/password authentication. Ideal for:

- Automation scripts
- CI/CD pipelines
- Integrations with other systems
- Batch processing scripts

### Creating API Keys

1. **Navigate** to **API Keys**
2. **Click "Create API Key"**
3. **Fill in details**:
   ```
   Name: Production Automation
   Description: CI/CD pipeline integration
   Expires: 90 days (or never)
   Permissions: Full access or restricted
   ```
4. **Create Key**
5. **Copy key immediately**: `cur_1234567890abcdefghijk`

**Important**: The full key is only shown once. Store it securely.

### Using API Keys

Include the API key in request headers:

```bash
curl -X GET http://localhost:8000/api/v1/documents \
  -H "Authorization: ApiKey cur_1234567890abcdefghijk"
```

### Managing API Keys

#### Viewing API Keys

List shows:
- Key name and description
- Key prefix (e.g., `cur_1234...`)
- Created and expiry dates
- Last used timestamp
- Active status

#### Revoking API Keys

To disable a key:

1. **Click on API key**
2. **Click "Revoke"**
3. **Confirm**

Key immediately stops working.

#### Deleting API Keys

To permanently remove:

1. **Click on API key**
2. **Click "Delete"**
3. **Confirm**

### API Key Best Practices

- **Unique keys**: Create separate keys for different purposes
- **Descriptive names**: Clear indication of key usage
- **Set expiration**: Use 90-day expiry for automation keys
- **Rotate regularly**: Create new keys, revoke old ones
- **Secure storage**: Store in secrets manager, not in code
- **Monitor usage**: Check last used date regularly
- **Revoke unused**: Delete keys that haven't been used in 90+ days
- **Minimal permissions**: Grant only necessary permissions

---

## Storage Management

### Viewing Storage Statistics

1. **Navigate** to **Settings** → **Storage**
2. **View statistics**:
   - Total files
   - Total size
   - Files by type
   - Storage by category
   - Deduplication savings

### Storage Categories

#### Uploaded Files
Original files uploaded by users before processing.

**Location**: `/app/files/organizations/{org_id}/batches/{batch_id}/uploaded/`
**Retention**: Configurable (default: 30 days)

#### Processed Files
Converted markdown files after processing.

**Location**: `/app/files/organizations/{org_id}/batches/{batch_id}/processed/`
**Retention**: Configurable (default: 90 days)

#### Batch Files
Operator-provided files for batch processing.

**Location**: `/app/files/batch_files/`
**Retention**: Configurable (default: 60 days)

#### Deduplicated Storage
Content-addressable storage for duplicate files.

**Location**: `/app/files/dedupe/{hash}/`
**Retention**: Deleted when no references remain

#### Temporary Files
Job-specific temporary files.

**Location**: `/app/files/temp/{job_id}/`
**Retention**: 1 day

### Deduplication

Curatore automatically detects duplicate files based on content (SHA-256 hash):

#### Viewing Duplicates

1. **Navigate** to **Storage** → **Duplicates**
2. **See duplicate groups**:
   - Content hash
   - Number of copies
   - Space saved
   - File locations

#### Deduplication Statistics

- **Unique Files**: Number of distinct file contents
- **Total References**: Total file instances
- **Space Saved**: Storage saved by deduplication
- **Deduplication Ratio**: Percentage of storage saved

**Example**:
- 150 files uploaded
- 100 unique contents
- 50 MB saved (33% reduction)

### Manual Cleanup

To manually clean up old files:

1. **Navigate** to **Storage** → **Cleanup**
2. **Select categories**:
   - Uploaded files older than X days
   - Processed files older than X days
   - Temporary files

3. **Preview** what will be deleted
4. **Confirm cleanup**
5. **View results**:
   - Files deleted
   - Space freed

### Automatic Cleanup

Curatore runs automatic cleanup daily:

- **Schedule**: 2:00 AM local time
- **Targets**: Files exceeding retention periods
- **Logs**: Available in system logs

Configure in **Settings** → **Storage** → **Retention Policies**

---

## Troubleshooting

### Login Issues

#### Cannot Login

**Symptoms**: Login fails with "Invalid credentials"

**Solutions**:
1. Verify email and password are correct
2. Check if account is active (contact admin)
3. Try password reset
4. Clear browser cache and cookies
5. Try incognito/private browsing mode

#### Email Not Verified

**Symptoms**: Login blocked due to unverified email

**Solutions**:
1. Check spam folder for verification email
2. Request new verification email (Settings → Profile)
3. Contact admin to manually verify email
4. Check grace period hasn't expired

### Document Processing Issues

#### Upload Fails

**Symptoms**: Document upload returns error

**Solutions**:
1. Check file size (max 50 MB for most formats)
2. Verify file format is supported
3. Check file isn't corrupted (open in native application)
4. Try renaming file (remove special characters)
5. Check network connection

#### Processing Stuck

**Symptoms**: Document stays in "Processing" status indefinitely

**Solutions**:
1. Wait 5 minutes (large documents take time)
2. Check queue health (Dashboard → Queue Status)
3. Cancel and retry processing
4. Try with different options (disable optimization)
5. Contact admin if persists

#### Low Quality Scores

**Symptoms**: Documents consistently score below threshold

**Solutions**:
1. Check original document quality
2. Try different file format (DOCX vs PDF)
3. Enable RAG optimization
4. Try different extraction engine (if available)
5. Lower quality thresholds if appropriate
6. Check if source is image-based (requires OCR)

#### Processing Fails

**Symptoms**: Processing completes with "FAILURE" status

**Solutions**:
1. Check processing logs for error details
2. Verify file isn't corrupted
3. Try smaller or simpler document first
4. Check if LLM service is available
5. Retry with different options

### Connection Issues

#### Connection Test Fails

**Symptoms**: Connection test returns error

**Solutions**:

**SharePoint**:
1. Verify credentials (Tenant ID, Client ID, Secret)
2. Check Azure AD app permissions granted
3. Verify admin consent given
4. Check site URL is correct
5. Test network connectivity to SharePoint

**LLM**:
1. Verify API key is valid
2. Check base URL is correct
3. Test with different model
4. Check API quota/rate limits
5. Verify network can reach API endpoint

**Extraction Service**:
1. Verify service URL is correct
2. Check service is running
3. Test network connectivity
4. Check service logs

#### Connection Unavailable During Processing

**Symptoms**: Processing fails with "Connection unavailable"

**Solutions**:
1. Test connection manually
2. Set working connection as default
3. Verify connection is active
4. Check service isn't under maintenance
5. Contact admin to check service status

### SharePoint Sync Issues

#### Sync Configuration Creation Fails

**Symptoms**: Cannot create new sync configuration

**Solutions**:
1. Verify Microsoft Graph connection is configured and active
2. Test the connection in Connection Management
3. Check folder URL format (must be valid SharePoint URL)
4. Verify permissions on SharePoint site
5. Check folder exists and is accessible

#### Sync Fails with Token Expiration

**Symptoms**: Sync fails after running for ~1 hour with 401 error

**Solutions**:
1. This should be handled automatically by token refresh
2. If persists, check Microsoft Graph connection validity
3. Re-authorize the connection if needed
4. Check if Azure AD app permissions changed

#### Incremental Sync Shows No Changes

**Symptoms**: Incremental sync completes but no files processed

**Solutions**:
1. This is normal if no files changed since last sync
2. Verify files were actually modified in SharePoint
3. Check if sync is looking at correct folder
4. Run a Full Sync to reset delta token if needed

#### Sync Cancellation

**Symptoms**: Need to stop a running sync

**Solutions**:
1. Go to Job Manager (/admin/queue)
2. Find the sync job and click Cancel
3. Or use the "Cancel Stuck" button on the sync config page

### Performance Issues

#### Slow Processing

**Symptoms**: Documents take longer than expected to process

**Solutions**:
1. Check document size and complexity
2. Verify LLM service response time
3. Check system resources (CPU, memory)
4. Reduce concurrent workers if system overloaded
5. Disable quality evaluation for faster processing

#### UI Slow or Unresponsive

**Symptoms**: Frontend interface lags or freezes

**Solutions**:
1. Clear browser cache
2. Close unused browser tabs
3. Try different browser
4. Check network connection
5. Check if backend is overloaded

### Getting Help

If you cannot resolve an issue:

1. **Check documentation**: Refer to this guide and API documentation
2. **View logs**: Check processing logs for error details
3. **Contact admin**: Report issue with details:
   - What you were trying to do
   - Error message received
   - Steps to reproduce
   - Browser and version (for UI issues)

4. **System Information**: Provide if requested:
   - User role and permissions
   - Document type and size
   - Connection types in use
   - Processing options selected

---

## Best Practices

### Document Preparation

1. **Use text-based PDFs** when possible (not scanned images)
2. **Clean source documents**: Remove unnecessary pages/content
3. **Consistent formatting**: Use styles in Word/PowerPoint
4. **Test first**: Process one document before batch processing
5. **Check compatibility**: Verify format is supported

### Quality Assessment

1. **Set appropriate thresholds** for your use case
2. **Review low-quality documents** manually
3. **Iterate**: Adjust thresholds based on results
4. **Document decisions**: Note why certain thresholds chosen
5. **Spot check**: Manually review sample of high-scoring documents

### Batch Processing

1. **Start small**: Test with 5-10 documents first
2. **Monitor progress**: Check periodically for errors
3. **Plan timing**: Run large batches during off-hours
4. **Organize files**: Use clear naming conventions
5. **Clean up**: Remove processed batches regularly

### Security

1. **Strong passwords**: Use password manager
2. **Enable 2FA**: If available in your deployment
3. **Secure API keys**: Store in secrets manager
4. **Regular reviews**: Check API key usage
5. **Report issues**: Notify admin of suspicious activity
6. **Logout**: When using shared computers

### Storage Management

1. **Download results**: Before automatic cleanup
2. **Monitor usage**: Check storage statistics regularly
3. **Use deduplication**: Enable to save space
4. **Appropriate retention**: Balance storage vs data needs
5. **Regular cleanup**: Run manual cleanup periodically

---

## Keyboard Shortcuts

| Action | Shortcut | Context |
|--------|----------|---------|
| Upload document | `Ctrl+U` | Dashboard |
| Search | `Ctrl+K` | Any page |
| Navigation menu | `Ctrl+\` | Any page |
| Refresh | `F5` | Any page |
| Settings | `Ctrl+,` | Any page |
| Help | `?` | Any page |

---

## Additional Resources

- **API Documentation**: [API_DOCUMENTATION.md](API_DOCUMENTATION.md)
- **Deployment Guide**: [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)
- **Development Guide**: [CLAUDE.md](CLAUDE.md)
- **Architecture**: [plan.md](plan.md)
- **Test Documentation**: [backend/tests/README_TESTS.md](backend/tests/README_TESTS.md)

---

**Version**: 2.0.0
**Last Updated**: 2026-02-02
**Maintained by**: Curatore Development Team
