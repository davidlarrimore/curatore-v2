// frontend/lib/api.ts
// Centralized API client and utilities for the frontend

/*
  Notes:
  - Targets API v1 paths by default. Adjust `API_PATH_VERSION` to switch.
  - Reads backend base from `NEXT_PUBLIC_API_URL` with a sensible default.
  - Wraps fetch with minimal error handling and exposes typed-ish helpers.
*/

import type {
  FileInfo,
  ProcessingResult,
  LLMConnectionStatus,
} from '@/types'

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
export const API_PATH_VERSION = 'v1' as const

const jsonHeaders: HeadersInit = { 'Content-Type': 'application/json' }

function apiUrl(path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`
  return `${API_BASE_URL}/api/${API_PATH_VERSION}${normalized}`
}

function httpError(res: Response, message?: string, detail?: any): never {
  const err = new Error(message || res.statusText || `Request failed with ${res.status}`)
  ;(err as any).status = res.status
  if (detail !== undefined) (err as any).detail = detail
  throw err
}

async function handleJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let body: any = undefined
    try { body = await res.json() } catch {}
    const msg = (body && (body.detail || body.message)) || res.statusText
    httpError(res, msg, body)
  }
  return res.json() as Promise<T>
}

async function handleBlob(res: Response): Promise<Blob> {
  if (!res.ok) {
    let text: string | undefined
    try { text = await res.text() } catch {}
    httpError(res, text)
  }
  return res.blob()
}

// -------------------- System API --------------------
export const systemApi = {
  async getHealth(): Promise<{ status: string; llm_connected: boolean; version: string } & Record<string, any>> {
    const res = await fetch(apiUrl('/health'), { cache: 'no-store' })
    return handleJson(res)
  },

  async getSupportedFormats(): Promise<{ supported_extensions: string[]; max_file_size: number }> {
    const res = await fetch(apiUrl('/config/supported-formats'), { cache: 'no-store' })
    return handleJson(res)
  },

  async getConfig(): Promise<{
    quality_thresholds: { conversion: number; clarity: number; completeness: number; relevance: number; markdown: number }
    ocr_settings: { language: string; psm: number }
    auto_optimize: boolean
  }> {
    const res = await fetch(apiUrl('/config/defaults'), { cache: 'no-store' })
    return handleJson(res)
  },

  async getLLMStatus(): Promise<LLMConnectionStatus> {
    const res = await fetch(apiUrl('/llm/status'), { cache: 'no-store' })
    return handleJson(res)
  },

  async resetSystem(): Promise<{ success: boolean; message?: string }> {
    const res = await fetch(apiUrl('/system/reset'), { method: 'POST' })
    return handleJson(res)
  },

  async getQueueHealth(): Promise<{ pending: number; running: number; processed: number; total: number } & Record<string, any>> {
    const res = await fetch(apiUrl('/system/queues'), { cache: 'no-store' })
    return handleJson(res)
  },

  async getQueueSummaryByJobs(jobIds: string[]): Promise<{ queued: number; running: number; done: number; total: number } & Record<string, any>> {
    const url = new URL(apiUrl('/system/queues/summary'))
    url.searchParams.set('job_ids', jobIds.join(','))
    const res = await fetch(url.toString(), { cache: 'no-store' })
    return handleJson(res)
  },

  async getQueueSummaryByBatch(batchId: string): Promise<{ queued: number; running: number; done: number; total: number } & Record<string, any>> {
    const url = new URL(apiUrl('/system/queues/summary'))
    url.searchParams.set('batch_id', batchId)
    const res = await fetch(url.toString(), { cache: 'no-store' })
    return handleJson(res)
  },

  async getComprehensiveHealth(): Promise<any> {
    const res = await fetch(apiUrl('/system/health/comprehensive'), { cache: 'no-store' })
    return handleJson(res)
  },

  async getComponentHealth(component: 'backend' | 'database' | 'redis' | 'celery' | 'extraction' | 'docling' | 'llm' | 'sharepoint'): Promise<any> {
    const res = await fetch(apiUrl(`/system/health/${component}`), { cache: 'no-store' })
    return handleJson(res)
  },
}

// -------------------- File API --------------------
export const fileApi = {
  async listUploadedFiles(): Promise<{ files: FileInfo[]; count: number }> {
    const res = await fetch(apiUrl('/documents/uploaded'), { cache: 'no-store' })
    return handleJson(res)
  },

  async listBatchFiles(): Promise<{ files: FileInfo[]; count: number }> {
    const res = await fetch(apiUrl('/documents/batch'), { cache: 'no-store' })
    return handleJson(res)
  },

  async uploadFile(file: File): Promise<{ document_id: string; filename: string; file_size: number; upload_time: string }> {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(apiUrl('/documents/upload'), { method: 'POST', body: form })
    return handleJson(res)
  },

  async downloadDocument(documentId: string): Promise<Blob> {
    const res = await fetch(apiUrl(`/documents/${encodeURIComponent(documentId)}/download`))
    return handleBlob(res)
  },

  async deleteDocument(documentId: string): Promise<{ success: boolean; message?: string }> {
    const res = await fetch(apiUrl(`/documents/${encodeURIComponent(documentId)}`), { method: 'DELETE' })
    return handleJson(res)
  },

  async downloadBulkDocuments(
    documentIds: string[],
    downloadType: 'individual' | 'combined' | 'rag_ready',
    zipName?: string,
    includeSummary: boolean = true,
  ): Promise<Blob> {
    // Align with BulkDownloadRequest while keeping backward compatibility
    // Model: { document_ids, download_type, include_summary, include_combined, custom_filename }
    // Some routers still reference `zip_name`, so send both.
    const body: Record<string, any> = {
      document_ids: documentIds,
      download_type: downloadType,
      include_summary: includeSummary,
      include_combined: downloadType === 'combined',
      custom_filename: zipName,
      zip_name: zipName,
    }
    const res = await fetch(apiUrl('/documents/download/bulk'), {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify(body),
    })
    return handleBlob(res)
  },

  async downloadRAGReadyDocuments(zipName?: string): Promise<Blob> {
    const url = new URL(apiUrl('/documents/download/rag-ready'))
    if (zipName) url.searchParams.set('zip_name', zipName)
    url.searchParams.set('include_summary', 'true')
    const res = await fetch(url.toString())
    return handleBlob(res)
  },
}

// -------------------- Processing API --------------------
export const processingApi = {
  async enqueueDocument(
    documentId: string,
    options: { auto_optimize?: boolean; quality_thresholds?: any } = {},
  ): Promise<{ job_id: string; document_id: string; status: string; enqueued_at?: string }>
  {
    const payload = mapOptionsToV1(options)
    const res = await fetch(apiUrl(`/documents/${encodeURIComponent(documentId)}/process`), {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    })
    return handleJson(res)
  },

  async processBatch(request: { document_ids: string[]; options?: any }): Promise<{ batch_id: string; jobs: any[]; conflicts: any[]; total: number }>
  {
    const payload = {
      document_ids: request.document_ids,
      options: request.options ? mapOptionsToV1(request.options) : undefined,
    }
    const res = await fetch(apiUrl('/documents/batch/process'), {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    })
    return handleJson(res)
  },

  async getProcessingResult(documentId: string): Promise<ProcessingResult> {
    const res = await fetch(apiUrl(`/documents/${encodeURIComponent(documentId)}/result`), { cache: 'no-store' })
    const raw = await handleJson<any>(res)
    return mapV1ResultToFrontend(raw)
  },

  async processDocument(
    documentId: string,
    options: { auto_optimize?: boolean; quality_thresholds?: any },
  ): Promise<ProcessingResult> {
    const v1Options = mapOptionsToV1(options)

    const res = await fetch(apiUrl(`/documents/${encodeURIComponent(documentId)}/process`), {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify(v1Options),
    })
    const raw = await handleJson<any>(res)
    return mapV1ResultToFrontend(raw)
  },

  // Optional helper (not currently used): export results in a simple JSON blob
  async downloadResults(results: ProcessingResult[], format: 'json' | 'zip' | string = 'json'): Promise<Blob> {
    if (format === 'json') {
      return new Blob([JSON.stringify(results, null, 2)], { type: 'application/json' })
    }
    // For other formats, default to generating a JSON blob. Real zip export is handled via fileApi.* helpers.
    return new Blob([JSON.stringify(results, null, 2)], { type: 'application/octet-stream' })
  },
}

// -------------------- Content API --------------------
export const contentApi = {
  async getDocumentContent(documentId: string): Promise<{ content: string }> {
    const res = await fetch(apiUrl(`/documents/${encodeURIComponent(documentId)}/content`), { cache: 'no-store' })
    return handleJson(res)
  },

  async updateDocumentContent(
    documentId: string,
    content: string,
  ): Promise<{ job_id: string; document_id: string; status: string; enqueued_at?: string }> {
    const res = await fetch(apiUrl(`/documents/${encodeURIComponent(documentId)}/content`), {
      method: 'PUT',
      headers: jsonHeaders,
      body: JSON.stringify({ content }),
    })
    return handleJson(res)
  },
}

// -------------------- Utility Functions --------------------
export const utils = {
  /**
   * Map v1 API response to frontend ProcessingResult type
   */
  mapV1ResultToFrontend: mapV1ResultToFrontend,

  /**
   * Map frontend options to v1 API format
   */
  mapOptionsToV1: mapOptionsToV1,

  /**
   * Create a download link for a blob and trigger download
   */
  downloadBlob(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  },

  /**
   * Remove hash prefix from filename and replace underscores with spaces
   * (e.g., "abc123_document_name.pdf" -> "document name.pdf")
   * Backend stores files as {hash}_{original_name}, but we should display just the original name
   */
  getDisplayFilename(filename: string): string {
    if (!filename) return filename;
    // Check if filename has hash prefix pattern (32 hex chars followed by underscore)
    const match = filename.match(/^[0-9a-f]{32}_(.+)$/i);
    const nameWithoutHash = match ? match[1] : filename;

    // Replace underscores with spaces, but preserve file extension
    const lastDotIndex = nameWithoutHash.lastIndexOf('.');
    if (lastDotIndex > 0) {
      const nameWithoutExt = nameWithoutHash.substring(0, lastDotIndex);
      const extension = nameWithoutHash.substring(lastDotIndex);
      return nameWithoutExt.replace(/_/g, ' ') + extension;
    }

    return nameWithoutHash.replace(/_/g, ' ');
  },

  /**
   * Format file size for display
   */
  formatFileSize(bytes: number): string {
    if (bytes === 0) return '0 Bytes'
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
  },

  /**
   * Format processing time for display
   */
  formatProcessingTime(seconds: number): string {
    if (seconds < 60) return `${seconds.toFixed(1)}s`
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}m ${remainingSeconds.toFixed(1)}s`
  },

  /**
   * Get score color based on threshold
   */
  getScoreColor(score: number, threshold: number): string {
    if (score >= threshold) return 'text-green-600'
    if (score >= threshold * 0.8) return 'text-yellow-600'
    return 'text-red-600'
  },

  /**
   * Format score with appropriate precision
   */
  formatScore(score: number, isPercentage: boolean = false): string {
    if (isPercentage) return `${score.toFixed(1)}%`
    return score.toFixed(1)
  },

  /**
   * Calculate statistics from processing results
   */
  calculateStats(results: ProcessingResult[]) {
    const total = results.length
    const successful = results.filter(r => r.success).length
    const failed = total - successful
    const ragReady = results.filter(r => r.pass_all_thresholds).length
    const optimized = results.filter(r => r.vector_optimized).length
    
    return { 
      total, 
      successful, 
      failed, 
      ragReady, 
      optimized 
    }
  },

  /**
   * Generate timestamp string for filenames
   */
  generateTimestamp(): string {
    const d = new Date()
    const pad = (n: number, l = 2) => n.toString().padStart(l, '0')
    return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
  },

  /**
   * Format duration in human readable format
   */
  formatDuration(seconds: number): string {
    if (!seconds && seconds !== 0) return '0s'
    const s = Math.floor(seconds % 60)
    const m = Math.floor((seconds / 60) % 60)
    const h = Math.floor(seconds / 3600)
    const pad = (n: number) => n.toString().padStart(2, '0')
    return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
  },
}

/**
 * Map v1 API response to frontend ProcessingResult format
 * Handles backward compatibility and field mapping
 */
function mapV1ResultToFrontend(raw: any): ProcessingResult {
  // Safely extract conversion score with fallback logic
  const conversion_score = raw.conversion_result?.conversion_score ?? 0
  const pass_all_thresholds = raw.pass_all_thresholds ?? raw.is_rag_ready ?? false
  const vector_optimized = raw.vector_optimized ?? false

  return {
    // Required core fields
    document_id: raw.document_id,
    filename: raw.filename,
    status: raw.status,
    success: raw.success ?? (raw.status === 'completed'),
    message: raw.message ?? raw.error_message,
    original_path: raw.original_path,
    markdown_path: raw.markdown_path,
    conversion_result: raw.conversion_result,
    llm_evaluation: raw.llm_evaluation,
    document_summary: raw.document_summary ?? raw.summary,
    conversion_score,
    pass_all_thresholds,
    vector_optimized,
    processing_time: raw.processing_time ?? 0,
    processed_at: raw.processed_at,
    thresholds_used: raw.thresholds_used,
  } as ProcessingResult
}

/**
 * Map frontend options to v1 API format
 * Aligns with backend V1ProcessingOptions: { auto_optimize, quality_thresholds: { conversion, clarity, completeness, relevance, markdown } }
 */
function mapOptionsToV1(options: any): any {
  const v1: any = {
    auto_optimize: options?.auto_optimize ?? true,
  }

  const qt = options?.quality_thresholds
  if (qt) {
    v1.quality_thresholds = {
      conversion: Math.round(qt.conversion ?? qt.conversion_quality ?? qt.conversion_threshold ?? 70),
      clarity: Math.round(qt.clarity ?? qt.clarity_score ?? qt.clarity_threshold ?? 7),
      completeness: Math.round(qt.completeness ?? qt.completeness_score ?? qt.completeness_threshold ?? 7),
      relevance: Math.round(qt.relevance ?? qt.relevance_score ?? qt.relevance_threshold ?? 7),
      markdown: Math.round(qt.markdown ?? qt.markdown_quality ?? qt.markdown_threshold ?? 7),
    }
  }

  return v1
}

// -------------------- Jobs API --------------------
export const jobsApi = {
  async getJob(jobId: string): Promise<any> {
    const res = await fetch(apiUrl(`/jobs/${encodeURIComponent(jobId)}`), { cache: 'no-store' })
    return handleJson(res)
  },

  async getJobByDocument(documentId: string): Promise<any> {
    const res = await fetch(apiUrl(`/jobs/by-document/${encodeURIComponent(documentId)}`), { cache: 'no-store' })
    return handleJson(res)
  },
}

// -------------------- Auth API --------------------
export const authApi = {
  async login(emailOrUsername: string, password: string): Promise<{
    access_token: string
    refresh_token: string
    token_type: string
    user: {
      id: string
      email: string
      username: string
      full_name?: string
      role: string
      organization_id: string
    }
  }> {
    const res = await fetch(apiUrl('/auth/login'), {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ email_or_username: emailOrUsername, password }),
    })
    return handleJson(res)
  },

  async register(data: {
    email: string
    username: string
    password: string
    full_name?: string
    organization_name?: string
  }): Promise<{
    access_token: string
    refresh_token: string
    user: any
  }> {
    const res = await fetch(apiUrl('/auth/register'), {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async refreshToken(refreshToken: string): Promise<{
    access_token: string
    refresh_token: string
    token_type: string
  }> {
    const res = await fetch(apiUrl('/auth/refresh'), {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    return handleJson(res)
  },

  async getCurrentUser(token: string): Promise<{
    id: string
    email: string
    username: string
    full_name?: string
    role: string
    organization_id: string
    organization_name: string
    is_active: boolean
  }> {
    const res = await fetch(apiUrl('/auth/me'), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },
}

// -------------------- Connections API --------------------
export const connectionsApi = {
  async listConnections(token: string): Promise<{
    connections: Array<{
      id: string
      name: string
      connection_type: string
      config: Record<string, any>
      is_default: boolean
      is_active: boolean
      last_tested_at?: string
      health_status?: 'healthy' | 'unhealthy' | 'unknown'
      created_at: string
      updated_at: string
    }>
  }> {
    const res = await fetch(apiUrl('/connections'), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getConnection(token: string, connectionId: string): Promise<any> {
    const res = await fetch(apiUrl(`/connections/${connectionId}`), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async createConnection(token: string, data: {
    name: string
    connection_type: string
    config: Record<string, any>
    is_default?: boolean
    test_on_save?: boolean
  }): Promise<any> {
    const res = await fetch(apiUrl('/connections'), {
      method: 'POST',
      headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async updateConnection(token: string, connectionId: string, data: {
    name?: string
    config?: Record<string, any>
    is_active?: boolean
    test_on_save?: boolean
  }): Promise<any> {
    const res = await fetch(apiUrl(`/connections/${connectionId}`), {
      method: 'PUT',
      headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async deleteConnection(token: string, connectionId: string): Promise<{ message: string }> {
    const res = await fetch(apiUrl(`/connections/${connectionId}`), {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    })
    return handleJson(res)
  },

  async testConnection(token: string, connectionId: string): Promise<{
    success: boolean
    message?: string
    health_status?: 'healthy' | 'unhealthy'
    details?: any
  }> {
    const res = await fetch(apiUrl(`/connections/${connectionId}/test`), {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    return handleJson(res)
  },

  async setDefaultConnection(token: string, connectionId: string): Promise<{ message: string }> {
    const res = await fetch(apiUrl(`/connections/${connectionId}/set-default`), {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    return handleJson(res)
  },

  async listConnectionTypes(token?: string): Promise<{
    types: Array<{
      type: string
      display_name: string
      description: string
      config_schema: any
      example_config: Record<string, any>
    }>
  }> {
    const headers = token ? { Authorization: `Bearer ${token}` } : undefined
    const res = await fetch(apiUrl('/connections/types'), {
      headers,
      cache: 'no-store',
    })
    return handleJson(res)
  },
}

// -------------------- Settings API --------------------
export const settingsApi = {
  async getOrganizationSettings(token: string): Promise<{
    organization_id: string
    organization_name: string
    settings: Record<string, any>
  }> {
    const res = await fetch(apiUrl('/settings/organization'), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async updateOrganizationSettings(token: string, settings: Record<string, any>): Promise<{
    message: string
    settings: Record<string, any>
  }> {
    const res = await fetch(apiUrl('/settings/organization'), {
      method: 'PUT',
      headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
      body: JSON.stringify({ settings }),
    })
    return handleJson(res)
  },

  async getUserSettings(token: string): Promise<{
    user_id: string
    settings: Record<string, any>
  }> {
    const res = await fetch(apiUrl('/settings/user'), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async updateUserSettings(token: string, settings: Record<string, any>): Promise<{
    message: string
    settings: Record<string, any>
  }> {
    const res = await fetch(apiUrl('/settings/user'), {
      method: 'PUT',
      headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
      body: JSON.stringify({ settings }),
    })
    return handleJson(res)
  },

  async getSettingsSchema(token: string): Promise<{
    organization_schema: any
    user_schema: any
    merged_example: Record<string, any>
  }> {
    const res = await fetch(apiUrl('/settings/schema'), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },
}

// -------------------- Storage API --------------------
export const storageApi = {
  async getStats(token: string, organizationId?: string): Promise<{
    organization_id: string
    total_files: number
    total_size_bytes: number
    files_by_type: { uploaded: number; processed: number }
    deduplication: {
      unique_files: number
      total_references: number
      duplicate_references: number
      storage_used_bytes: number
      storage_saved_bytes: number
      savings_percentage: number
    }
  }> {
    const url = new URL(apiUrl('/storage/stats'))
    if (organizationId) url.searchParams.set('organization_id', organizationId)
    const res = await fetch(url.toString(), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async triggerCleanup(token: string, dryRun: boolean = true): Promise<{
    dry_run: boolean
    started_at: string
    completed_at: string
    duration_seconds: number
    total_expired: number
    deleted_count: number
    would_delete_count: number
    skipped_count: number
    error_count: number
    expired_batches: number
  }> {
    const url = new URL(apiUrl('/storage/cleanup'))
    url.searchParams.set('dry_run', String(dryRun))
    const res = await fetch(url.toString(), {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    return handleJson(res)
  },

  async getRetentionPolicy(token: string): Promise<{
    enabled: boolean
    retention_periods: {
      uploaded_days: number
      processed_days: number
      batch_days: number
      temp_hours: number
    }
    cleanup_schedule: string
    batch_size: number
    dry_run: boolean
  }> {
    const res = await fetch(apiUrl('/storage/retention'), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getDeduplicationStats(token: string, organizationId?: string): Promise<{
    organization_id: string
    enabled: boolean
    strategy: string
    min_file_size: number
    unique_files: number
    total_references: number
    duplicate_references: number
    storage_used_bytes: number
    storage_saved_bytes: number
    savings_percentage: number
  }> {
    const url = new URL(apiUrl('/storage/deduplication'))
    if (organizationId) url.searchParams.set('organization_id', organizationId)
    const res = await fetch(url.toString(), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async listDuplicates(token: string, organizationId?: string): Promise<{
    organization_id: string
    duplicate_groups: number
    total_storage_saved: number
    duplicates: Array<{
      hash: string
      file_count: number
      document_ids: string[]
      storage_saved: number
    }>
  }> {
    const url = new URL(apiUrl('/storage/duplicates'))
    if (organizationId) url.searchParams.set('organization_id', organizationId)
    const res = await fetch(url.toString(), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getDuplicateDetails(token: string, hash: string): Promise<{
    hash: string
    original_filename: string
    file_size: number
    created_at: string
    reference_count: number
    references: Array<{
      document_id: string
      organization_id: string
      created_at: string
    }>
  }> {
    const res = await fetch(apiUrl(`/storage/duplicates/${hash}`), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },
}

// -------------------- Users API --------------------
export const usersApi = {
  async listUsers(token: string): Promise<{
    users: Array<{
      id: string
      email: string
      username: string
      full_name?: string
      role: string
      organization_id: string
      is_active: boolean
      created_at: string
      last_login?: string
    }>
  }> {
    const res = await fetch(apiUrl('/users'), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getUser(token: string, userId: string): Promise<any> {
    const res = await fetch(apiUrl(`/users/${userId}`), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async inviteUser(token: string, data: {
    email: string
    role?: string
    full_name?: string
    send_email?: boolean
  }): Promise<{
    message: string
    user: any
    temporary_password?: string
  }> {
    const res = await fetch(apiUrl('/users/invite'), {
      method: 'POST',
      headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async updateUser(token: string, userId: string, data: {
    email?: string
    username?: string
    full_name?: string
    role?: string
    is_active?: boolean
  }): Promise<{
    message: string
    user: any
  }> {
    const res = await fetch(apiUrl(`/users/${userId}`), {
      method: 'PUT',
      headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async deleteUser(token: string, userId: string): Promise<{
    message: string
  }> {
    const res = await fetch(apiUrl(`/users/${userId}`), {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    })
    return handleJson(res)
  },

  async changePassword(token: string, userId: string, newPassword: string): Promise<{
    message: string
  }> {
    const res = await fetch(apiUrl(`/users/${userId}/password`), {
      method: 'PUT',
      headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
      body: JSON.stringify({ new_password: newPassword }),
    })
    return handleJson(res)
  },
}

// Default export with all API modules
export default {
  API_BASE_URL,
  API_PATH_VERSION,
  systemApi,
  fileApi,
  processingApi,
  contentApi,
  jobsApi,
  authApi,
  connectionsApi,
  settingsApi,
  usersApi,
  utils,
}
