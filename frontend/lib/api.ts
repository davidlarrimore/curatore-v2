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
import { validateDocumentId, DocumentIdError } from './validators'

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
export const API_PATH_VERSION = 'v1' as const
const ACCESS_TOKEN_KEY = 'curatore_access_token'

const jsonHeaders: HeadersInit = { 'Content-Type': 'application/json' }

function apiUrl(path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`
  return `${API_BASE_URL}/api/${API_PATH_VERSION}${normalized}`
}

function getAccessToken(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem(ACCESS_TOKEN_KEY)
}

function authHeaders(token?: string): HeadersInit {
  const resolvedToken = token || getAccessToken()
  return resolvedToken ? { Authorization: `Bearer ${resolvedToken}` } : {}
}

function httpError(res: Response, message?: string, detail?: any): never {
  const err = new Error(message || res.statusText || `Request failed with ${res.status}`)
  ;(err as any).status = res.status
  if (detail !== undefined) (err as any).detail = detail
  if (res.status === 401 && typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('auth:unauthorized'))
  }
  throw err
}

async function handleJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let body: any = undefined
    try { body = await res.json() } catch {}
    let msg = res.statusText
    if (body) {
      const detail = body.detail || body.message
      if (typeof detail === 'string') {
        msg = detail
      } else if (Array.isArray(detail)) {
        // Pydantic validation errors - extract messages
        msg = detail.map((e: any) => e.msg || JSON.stringify(e)).join('; ')
      } else if (detail) {
        msg = JSON.stringify(detail)
      }
    }
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

/**
 * Validate and encode document ID for use in API paths.
 *
 * @param documentId - Document ID to validate and encode
 * @returns URL-encoded validated document ID
 * @throws {DocumentIdError} If document ID is invalid
 */
function validateAndEncodeDocumentId(documentId: string): string {
  // Validate format (throws DocumentIdError if invalid)
  const validated = validateDocumentId(documentId)

  // Encode for use in URL path
  return encodeURIComponent(validated)
}

// -------------------- System API --------------------
export const systemApi = {
  async getHealth(): Promise<{ status: string; llm_connected: boolean; version: string } & Record<string, any>> {
    const res = await fetch(apiUrl('/admin/system/health/comprehensive'), { cache: 'no-store', headers: authHeaders() })
    const data = await handleJson(res)
    return {
      ...data,
      status: data.overall_status ?? 'unknown',
      llm_connected: data.components?.llm?.status === 'healthy',
      version: data.components?.backend?.version ?? '',
    }
  },

  async checkAvailability(): Promise<boolean> {
    try {
      const res = await fetch(apiUrl('/admin/system/health/backend'), { cache: 'no-store' })
      return res.ok || res.status === 401 || res.status === 403
    } catch {
      return false
    }
  },

  async getBackendHealth(): Promise<{ status: string; version: string }> {
    const res = await fetch(apiUrl('/admin/system/health/backend'), { cache: 'no-store', headers: authHeaders() })
    const data = await handleJson(res)
    return { status: data.status ?? 'unknown', version: data.version ?? '' }
  },

  async getSupportedFormats(): Promise<{ supported_extensions: string[]; max_file_size: number }> {
    const res = await fetch(apiUrl('/admin/config/supported-formats'), { cache: 'no-store', headers: authHeaders() })
    return handleJson(res)
  },

  async getConfig(): Promise<{
    ocr_settings: { language: string; psm: number }
  }> {
    const res = await fetch(apiUrl('/admin/config/defaults'), { cache: 'no-store', headers: authHeaders() })
    return handleJson(res)
  },

  async getExtractionEngines(): Promise<{
    engines: Array<{
      id: string
      name: string
      display_name: string
      description: string
      engine_type: string
      service_url: string
      timeout: number
      is_default: boolean
      is_system: boolean
    }>
    default_engine: string | null
    default_engine_source: string | null
  }> {
    const res = await fetch(apiUrl('/admin/config/extraction-engines'), { cache: 'no-store', headers: authHeaders() })
    return handleJson(res)
  },

  async getLLMStatus(): Promise<LLMConnectionStatus> {
    const res = await fetch(apiUrl('/admin/system/health/llm'), { cache: 'no-store', headers: authHeaders() })
    const data = await handleJson(res)
    return {
      connected: data.status === 'healthy',
      endpoint: data.endpoint ?? '',
      model: data.model ?? '',
      error: data.status === 'unhealthy' ? data.message : undefined,
      ssl_verify: data.ssl_verify ?? false,
      timeout: data.timeout ?? 0,
    }
  },

  async resetSystem(): Promise<{ success: boolean; message?: string }> {
    const res = await fetch(apiUrl('/admin/system/reset'), { method: 'POST', headers: authHeaders() })
    return handleJson(res)
  },

  async getQueueHealth(): Promise<{ pending: number; running: number; processed: number; total: number } & Record<string, any>> {
    const res = await fetch(apiUrl('/admin/system/queues'), { cache: 'no-store', headers: authHeaders() })
    return handleJson(res)
  },

  async getQueueSummaryByJobs(jobIds: string[]): Promise<{ queued: number; running: number; done: number; total: number } & Record<string, any>> {
    const url = new URL(apiUrl('/admin/system/queues/summary'))
    url.searchParams.set('job_ids', jobIds.join(','))
    const res = await fetch(url.toString(), { cache: 'no-store', headers: authHeaders() })
    return handleJson(res)
  },

  async getQueueSummaryByBatch(batchId: string): Promise<{ queued: number; running: number; done: number; total: number } & Record<string, any>> {
    const url = new URL(apiUrl('/admin/system/queues/summary'))
    url.searchParams.set('batch_id', batchId)
    const res = await fetch(url.toString(), { cache: 'no-store', headers: authHeaders() })
    return handleJson(res)
  },

  async getComprehensiveHealth(): Promise<any> {
    const res = await fetch(apiUrl('/admin/system/health/comprehensive'), { cache: 'no-store', headers: authHeaders() })
    return handleJson(res)
  },

  async getComponentHealth(component: 'backend' | 'database' | 'redis' | 'celery' | 'extraction' | 'docling' | 'llm' | 'sharepoint'): Promise<any> {
    const res = await fetch(apiUrl(`/admin/system/health/${component}`), { cache: 'no-store', headers: authHeaders() })
    return handleJson(res)
  },

  async getSystemSettings(): Promise<Record<string, any>> {
    const res = await fetch(apiUrl('/admin/config/system-settings'), { cache: 'no-store', headers: authHeaders() })
    return handleJson(res)
  },
}

// -------------------- File API --------------------
export const fileApi = {
  async listUploadedFiles(): Promise<{ files: FileInfo[]; count: number }> {
    // Check if object storage is enabled
    const useObjectStorage = await objectStorageApi.isEnabled()

    if (useObjectStorage) {
      // Use object storage artifacts endpoint
      const artifacts = await objectStorageApi.listArtifacts('uploaded')
      const files: FileInfo[] = artifacts.map(artifact => ({
        document_id: artifact.document_id,
        filename: artifact.original_filename,
        original_filename: artifact.original_filename,
        file_size: artifact.file_size || 0,
        upload_time: new Date(artifact.created_at).getTime(),
        file_path: `${artifact.bucket}/${artifact.object_key}`,
      }))
      return { files, count: files.length }
    }

    // Filesystem fallback no longer available (documents router removed)
    return { files: [], count: 0 }
  },

  async listBatchFiles(): Promise<{ files: FileInfo[]; count: number }> {
    // Batch files are a legacy concept — always return empty
    return { files: [], count: 0 }
  },

  /**
   * Upload a file. Automatically uses object storage (presigned URLs) when enabled,
   * otherwise falls back to traditional backend upload.
   */
  async uploadFile(file: File): Promise<{ document_id: string; filename: string; file_size: number; upload_time?: string; artifact_id?: string }> {
    // Check if object storage is enabled
    const useObjectStorage = await objectStorageApi.isEnabled()

    if (useObjectStorage) {
      // Use presigned URL flow (direct to storage)
      const result = await objectStorageApi.uploadFile(file)
      return {
        document_id: result.document_id,
        filename: result.filename,
        file_size: result.file_size,
        artifact_id: result.artifact_id,
      }
    }

    // Fall back to proxy upload (through backend)
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(apiUrl('/data/storage/upload/proxy'), { method: 'POST', body: form, headers: authHeaders() })
    return handleJson(res)
  },

  /**
   * Download a document. Automatically uses object storage (presigned URLs) when enabled,
   * otherwise falls back to traditional backend download.
   *
   * @param documentId - Document ID to download
   * @param artifactType - Type of artifact ('uploaded' or 'processed')
   * @param jobId - Optional job ID to download job-specific processed file
   */
  async downloadDocument(documentId: string, artifactType: 'uploaded' | 'processed' = 'processed', jobId?: string): Promise<Blob> {
    // Validate document ID
    const encodedDocId = validateAndEncodeDocumentId(documentId)

    let url = apiUrl(`/data/assets/${encodedDocId}/download`)
    if (jobId) {
      url += `?job_id=${encodeURIComponent(jobId)}`
    }
    const res = await fetch(url, { headers: authHeaders() })
    return handleBlob(res)
  },

  async deleteDocument(documentId: string): Promise<{ success: boolean; message?: string }> {
    const encodedDocId = validateAndEncodeDocumentId(documentId)
    const res = await fetch(apiUrl(`/data/assets/${encodedDocId}`), { method: 'DELETE', headers: authHeaders() })
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
    const res = await fetch(apiUrl('/data/assets/download/bulk'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders() },
      body: JSON.stringify(body),
    })
    return handleBlob(res)
  },

  async downloadRAGReadyDocuments(zipName?: string): Promise<Blob> {
    const url = new URL(apiUrl('/data/assets/download/rag-ready'))
    if (zipName) url.searchParams.set('zip_name', zipName)
    url.searchParams.set('include_summary', 'true')
    const res = await fetch(url.toString(), { headers: authHeaders() })
    return handleBlob(res)
  },
}

// -------------------- Processing API --------------------
// REMOVED: processingApi was deprecated. Use assetsApi for extraction workflows.

// -------------------- Organizations API --------------------
export const organizationsApi = {
  async getCurrentOrganization(token?: string): Promise<{
    id: string
    name: string
    display_name: string
    slug: string
    is_active: boolean
    settings: Record<string, any>
    created_at: string
    updated_at: string
  }> {
    const res = await fetch(apiUrl('/admin/organizations/me'), {
      cache: 'no-store',
      headers: authHeaders(token)
    })
    return handleJson(res)
  },

  async updateOrganization(token: string, data: { display_name?: string; slug?: string }): Promise<{
    id: string
    name: string
    display_name: string
    slug: string
    is_active: boolean
    settings: Record<string, any>
    created_at: string
    updated_at: string
  }> {
    const res = await fetch(apiUrl('/admin/organizations/me'), {
      method: 'PUT',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },
}

// -------------------- Content API --------------------
// REMOVED: contentApi was unused. Use assetsApi for asset content access.

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

    return {
      total,
      successful,
      failed
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
    processing_time: raw.processing_time ?? 0,
    processed_at: raw.processed_at,
    thresholds_used: raw.thresholds_used,
  } as ProcessingResult
}

/**
 * Map frontend options to v1 API format
 * Aligns with backend V1ProcessingOptions: { auto_optimize, extraction_engine, quality_thresholds: { conversion, clarity, completeness, relevance, markdown } }
 */
function mapOptionsToV1(options: any): any {
  const v1: any = {
    auto_optimize: options?.auto_optimize ?? true,
  }

  if (options?.extraction_engine) {
    v1.extraction_engine = options.extraction_engine
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

// -------------------- Runs API --------------------
export interface RunStats {
  runs: {
    by_status: Record<string, number>
    by_type: Record<string, number>
    total: number
  }
  recent_24h: {
    by_status: Record<string, number>
    total: number
  }
  assets: {
    by_status: Record<string, number>
    total: number
  }
  queues: {
    processing_priority: number
    processing: number
    maintenance: number
  }
}

export const runsApi = {
  /**
   * Get run statistics for the organization
   */
  async getStats(token?: string): Promise<RunStats> {
    const res = await fetch(apiUrl('/ops/runs/stats'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  /**
   * List runs with optional filters
   */
  async listRuns(token?: string, params?: {
    run_type?: string
    status?: string
    origin?: string
    limit?: number
    offset?: number
  }): Promise<{
    items: any[]
    total: number
    limit: number
    offset: number
  }> {
    const query = new URLSearchParams()
    if (params?.run_type) query.set('run_type', params.run_type)
    if (params?.status) query.set('status', params.status)
    if (params?.origin) query.set('origin', params.origin)
    if (params?.limit) query.set('limit', String(params.limit))
    if (params?.offset) query.set('offset', String(params.offset))

    const queryStr = query.toString()
    const url = queryStr ? `/ops/runs?${queryStr}` : '/ops/runs'

    const res = await fetch(apiUrl(url), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  /**
   * Get a single run by ID
   */
  async getRun(runId: string, token?: string): Promise<Run> {
    const res = await fetch(apiUrl(`/ops/runs/${runId}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  /**
   * Get a run with all its log events
   */
  async getRunWithLogs(runId: string, token?: string, params?: {
    level?: string
    event_type?: string
    limit?: number
  }): Promise<{ run: Run; logs: RunLogEvent[] }> {
    const query = new URLSearchParams()
    if (params?.level) query.set('level', params.level)
    if (params?.event_type) query.set('event_type', params.event_type)
    if (params?.limit) query.set('limit', String(params.limit))

    const queryStr = query.toString()
    const url = queryStr ? `/ops/runs/${runId}/logs?${queryStr}` : `/ops/runs/${runId}/logs`

    const res = await fetch(apiUrl(url), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  /**
   * Retry a failed extraction run
   */
  async retryRun(runId: string, token?: string): Promise<Run> {
    const res = await fetch(apiUrl(`/ops/runs/${runId}/retry`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },
}

// -------------------- Queue Admin API --------------------
export interface ExtractionQueueStats {
  pending_count: number
  submitted_count: number
  running_count: number
  completed_count: number
  failed_count: number
  timed_out_count: number
  max_concurrent: number
  avg_extraction_time_seconds: number | null
  throughput_per_minute: number
  recent_24h: {
    completed: number
    failed: number
    timed_out: number
  }
}

/**
 * Unified queue statistics matching backend UnifiedQueueStatsResponse.
 */
export interface UnifiedQueueStats {
  extraction_queue: {
    pending: number
    submitted: number
    running: number
    max_concurrent: number
  }
  celery_queues: {
    processing_priority: number
    extraction: number
    sam: number
    scrape: number
    sharepoint: number
    maintenance: number
  }
  throughput: {
    per_minute: number
    avg_extraction_seconds: number | null
  }
  recent_5m: {
    completed: number
    failed: number
    timed_out: number
  }
  recent_24h: {
    completed: number
    failed: number
    timed_out: number
  }
  workers: {
    active: number
    tasks_running: number
  }
}

export interface ActiveExtraction {
  run_id: string
  asset_id: string
  filename: string
  source_type: string
  status: string
  queue_position: number | null
  queue_priority: number
  created_at: string
  submitted_at: string | null
  timeout_at: string | null
  extractor_version: string | null
}

export interface ActiveExtractionsResponse {
  items: ActiveExtraction[]
  total: number
}

export interface QueueConfig {
  max_concurrent: number
  submission_interval_seconds: number
  duplicate_cooldown_seconds: number
  timeout_buffer_seconds: number
  queue_enabled: boolean
}

// -------------------- Unified Job Manager Types --------------------

/**
 * Run types supported by the Job Manager
 */
export type RunType = 'extraction' | 'sam_pull' | 'scrape' | 'sharepoint_sync' | 'system_maintenance'

/**
 * Run status values
 */
export type RunStatus = 'pending' | 'submitted' | 'running' | 'completed' | 'failed' | 'timed_out' | 'cancelled'

/**
 * Queue definition from the registry
 */
export interface QueueDefinition {
  queue_type: string
  celery_queue: string
  label: string
  description: string
  icon: string
  color: string
  can_cancel: boolean
  can_retry: boolean
  max_concurrent: number | null
  timeout_seconds: number
  is_throttled: boolean
  enabled: boolean
}

/**
 * Queue registry response
 */
export interface QueueRegistryResponse {
  queues: Record<string, QueueDefinition>
  run_type_mapping: Record<string, string>
}

/**
 * Child job stats for parent jobs
 */
export interface ChildJobStats {
  total: number
  pending: number
  submitted: number
  running: number
  completed: number
  failed: number
  cancelled: number
  timed_out: number
}

/**
 * Active job item for unified Job Manager
 */
export interface ActiveJob {
  run_id: string
  run_type: string
  status: string
  queue_priority: number
  created_at: string
  started_at: string | null
  submitted_at: string | null
  completed_at: string | null
  timeout_at: string | null

  // Display fields
  display_name: string
  display_context: string | null

  // For extractions
  asset_id: string | null
  filename: string | null
  source_type: string | null
  extractor_version: string | null
  queue_position: number | null

  // For other job types
  config: Record<string, any> | null

  // Capabilities (computed from queue_registry)
  can_cancel: boolean
  can_retry: boolean

  // Parent-child job tracking
  is_parent_job: boolean
  group_id: string | null
  parent_run_id: string | null
  child_stats: ChildJobStats | null
}

/**
 * Active jobs response
 */
export interface ActiveJobsResponse {
  items: ActiveJob[]
  total: number
  run_types: string[]
}

export const queueAdminApi = {
  /**
   * Get extraction queue statistics (legacy endpoint)
   * @deprecated Use getUnifiedStats() instead
   */
  async getStats(token?: string): Promise<ExtractionQueueStats> {
    const res = await fetch(apiUrl('/ops/queue/stats'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  /**
   * Get unified queue statistics (canonical endpoint).
   * This is the preferred method for fetching queue stats.
   */
  async getUnifiedStats(token?: string): Promise<UnifiedQueueStats> {
    const res = await fetch(apiUrl('/ops/queue/unified'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  /**
   * List active extractions
   */
  async listActive(token?: string, params?: {
    limit?: number
    include_completed?: boolean
    status_filter?: string
  }): Promise<ActiveExtractionsResponse> {
    const query = new URLSearchParams()
    if (params?.limit) query.set('limit', String(params.limit))
    if (params?.include_completed) query.set('include_completed', 'true')
    if (params?.status_filter) query.set('status_filter', params.status_filter)

    const queryStr = query.toString()
    const url = queryStr ? `/ops/queue/active?${queryStr}` : '/ops/queue/active'

    const res = await fetch(apiUrl(url), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  /**
   * Cancel an extraction
   */
  async cancelExtraction(token: string | undefined, runId: string): Promise<{
    status: string
    run_id: string
    reason?: string
  }> {
    const res = await fetch(apiUrl(`/ops/queue/${runId}/cancel`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  /**
   * Cancel multiple extractions at once
   */
  async cancelExtractionsBulk(token: string | undefined, runIds: string[]): Promise<{
    cancelled: string[]
    failed: Array<{ run_id: string; error: string }>
    total_requested: number
    total_cancelled: number
  }> {
    const res = await fetch(apiUrl('/ops/queue/cancel-bulk'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ run_ids: runIds }),
    })
    return handleJson(res)
  },

  /**
   * Get queue configuration
   */
  async getConfig(token?: string): Promise<QueueConfig> {
    const res = await fetch(apiUrl('/ops/queue/config'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  // -------------------- Unified Job Manager Methods --------------------

  /**
   * Get queue registry with all queue definitions and capabilities
   */
  async getRegistry(token?: string): Promise<QueueRegistryResponse> {
    const res = await fetch(apiUrl('/ops/queue/registry'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  /**
   * List all active jobs across all queue types
   */
  async listJobs(token?: string, params?: {
    run_type?: string
    status_filter?: string
    include_completed?: boolean
    limit?: number
  }): Promise<ActiveJobsResponse> {
    const query = new URLSearchParams()
    if (params?.run_type) query.set('run_type', params.run_type)
    if (params?.status_filter) query.set('status_filter', params.status_filter)
    if (params?.include_completed) query.set('include_completed', 'true')
    if (params?.limit) query.set('limit', String(params.limit))

    const queryStr = query.toString()
    const url = queryStr ? `/ops/queue/jobs?${queryStr}` : '/ops/queue/jobs'

    const res = await fetch(apiUrl(url), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  /**
   * Cancel any job (checks queue_registry for cancellation support)
   */
  async cancelJob(token: string | undefined, runId: string): Promise<{
    status: string
    run_id: string
    reason?: string
  }> {
    const res = await fetch(apiUrl(`/ops/queue/jobs/${runId}/cancel`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  /**
   * Force-kill a stuck job (terminates database connections and revokes Celery task)
   */
  async forceKillJob(token: string | undefined, runId: string): Promise<{
    status: string
    run_id: string
    message: string
    connections_terminated: number
    celery_task_revoked: boolean
  }> {
    const res = await fetch(apiUrl(`/ops/queue/jobs/${runId}/force-kill`), {
      method: 'POST',
      headers: authHeaders(token),
    })
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
    const res = await fetch(apiUrl('/admin/auth/login'), {
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
    const res = await fetch(apiUrl('/admin/auth/register'), {
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
    const res = await fetch(apiUrl('/admin/auth/refresh'), {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    return handleJson(res)
  },

  async extendSession(token: string): Promise<{
    access_token: string
    refresh_token: string
    token_type: string
  }> {
    const res = await fetch(apiUrl('/admin/auth/extend-session'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
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
    const res = await fetch(apiUrl('/admin/auth/me'), {
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
    const res = await fetch(apiUrl('/admin/connections'), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getConnection(token: string, connectionId: string): Promise<any> {
    const res = await fetch(apiUrl(`/admin/connections/${connectionId}`), {
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
    const res = await fetch(apiUrl('/admin/connections'), {
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
    const res = await fetch(apiUrl(`/admin/connections/${connectionId}`), {
      method: 'PUT',
      headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async deleteConnection(token: string, connectionId: string): Promise<{ message: string }> {
    const res = await fetch(apiUrl(`/admin/connections/${connectionId}`), {
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
    error?: string
  }> {
    const res = await fetch(apiUrl(`/admin/connections/${connectionId}/test`), {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    return handleJson(res)
  },

  async setDefaultConnection(token: string, connectionId: string): Promise<{ message: string }> {
    const res = await fetch(apiUrl(`/admin/connections/${connectionId}/set-default`), {
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
    const res = await fetch(apiUrl('/admin/connections/types'), {
      headers,
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async testCredentials(token: string, data: {
    provider: string
    base_url: string
    api_key: string
    [key: string]: any
  }): Promise<{
    success: boolean
    models: string[]
    message?: string
    error?: string
    requires_manual_model?: boolean
  }> {
    const res = await fetch(apiUrl('/admin/connections/test-credentials'), {
      method: 'POST',
      headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },
}

// -------------------- Settings API --------------------
export const settingsApi = {
  async getOrganizationSettings(token: string): Promise<{
    settings: Record<string, any>
  }> {
    const res = await fetch(apiUrl('/admin/organizations/me/settings'), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async updateOrganizationSettings(token: string, settings: Record<string, any>): Promise<{
    settings: Record<string, any>
  }> {
    const res = await fetch(apiUrl('/admin/organizations/me/settings'), {
      method: 'PUT',
      headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
      body: JSON.stringify({ settings }),
    })
    return handleJson(res)
  },

  async getUserSettings(token: string): Promise<{
    settings: Record<string, any>
  }> {
    const res = await fetch(apiUrl('/admin/users/me/settings'), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async updateUserSettings(token: string, settings: Record<string, any>): Promise<{
    settings: Record<string, any>
  }> {
    const res = await fetch(apiUrl('/admin/users/me/settings'), {
      method: 'PUT',
      headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
      body: JSON.stringify({ settings }),
    })
    return handleJson(res)
  },

}

// -------------------- Storage API (Filesystem) --------------------
// REMOVED: storageApi referenced endpoints that never existed in the backend
// (/data/storage/stats, /data/storage/cleanup, /data/storage/deduplication, etc.)
// Use objectStorageApi for storage operations.

// -------------------- Object Storage API --------------------
// Direct access to S3/MinIO object storage via presigned URLs
export const objectStorageApi = {
  /**
   * Check if object storage is enabled
   */
  async isEnabled(): Promise<boolean> {
    try {
      const res = await fetch(apiUrl('/data/storage/health'), {
        headers: authHeaders(),
        cache: 'no-store',
      })
      const data = await handleJson<{ status: string; enabled: boolean }>(res)
      return data.enabled && data.status !== 'disabled'
    } catch {
      return false
    }
  },

  /**
   * Get storage health status
   */
  async getHealth(): Promise<{
    status: string
    enabled: boolean
    provider_connected: boolean | null
    buckets: string[] | null
    error: string | null
  }> {
    const res = await fetch(apiUrl('/data/storage/health'), {
      headers: authHeaders(),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  /**
   * Upload a file proxied through backend (bypasses CORS and network issues)
   */
  async uploadFile(file: File): Promise<{
    document_id: string
    artifact_id: string
    filename: string
    file_size: number
  }> {
    const token = getAccessToken()
    if (!token) throw new Error('Authentication required')

    // Upload file through backend proxy
    const formData = new FormData()
    formData.append('file', file)

    const res = await fetch(apiUrl('/data/storage/upload/proxy'), {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    })

    if (!res.ok) {
      const error = await res.text()
      throw new Error(`Upload failed: ${error || res.statusText}`)
    }

    const result = await res.json() as {
      document_id: string
      artifact_id: string
      status: string
      filename: string
      file_size: number
      etag: string | null
    }

    return {
      document_id: result.document_id,
      artifact_id: result.artifact_id,
      filename: result.filename,
      file_size: result.file_size,
    }
  },

  /**
   * List all artifacts for a document
   */
  async listDocumentArtifacts(documentId: string, token?: string): Promise<Array<{
    id: string
    organization_id: string
    document_id: string
    job_id: string | null
    artifact_type: string
    bucket: string
    object_key: string
    original_filename: string
    content_type: string | null
    file_size: number | null
    etag: string | null
    status: string
    created_at: string
    updated_at: string
    expires_at: string | null
  }>> {
    const encodedDocId = validateAndEncodeDocumentId(documentId)
    const res = await fetch(apiUrl(`/data/storage/artifacts/document/${encodedDocId}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  /**
   * Get artifact details by ID
   */
  async getArtifact(artifactId: string, token?: string): Promise<{
    id: string
    organization_id: string
    document_id: string
    job_id: string | null
    artifact_type: string
    bucket: string
    object_key: string
    original_filename: string
    content_type: string | null
    file_size: number | null
    etag: string | null
    status: string
    created_at: string
    updated_at: string
    expires_at: string | null
  }> {
    const res = await fetch(apiUrl(`/data/storage/artifacts/${encodeURIComponent(artifactId)}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  /**
   * Delete an artifact
   */
  async deleteArtifact(artifactId: string, token?: string): Promise<{
    deleted: boolean
    artifact_id: string
    document_id: string
  }> {
    const res = await fetch(apiUrl(`/data/storage/artifacts/${encodeURIComponent(artifactId)}`), {
      method: 'DELETE',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  /**
   * List artifacts for the current organization
   */
  async listArtifacts(
    artifactType?: string,
    limit: number = 100,
    offset: number = 0,
    token?: string
  ): Promise<Array<{
    id: string
    organization_id: string
    document_id: string
    job_id: string | null
    artifact_type: string
    bucket: string
    object_key: string
    original_filename: string
    content_type: string | null
    file_size: number | null
    etag: string | null
    status: string
    created_at: string
    updated_at: string
    expires_at: string | null
  }>> {
    const url = new URL(apiUrl('/data/storage/artifacts'))
    if (artifactType) {
      url.searchParams.set('artifact_type', artifactType)
    }
    url.searchParams.set('limit', limit.toString())
    url.searchParams.set('offset', offset.toString())

    const res = await fetch(url.toString(), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async bulkDeleteArtifacts(
    artifactIds: string[],
    token?: string
  ): Promise<{
    total: number
    succeeded: number
    failed: number
    results: Array<{
      artifact_id: string
      document_id: string | null
      success: boolean
      error: string | null
    }>
  }> {
    const res = await fetch(apiUrl('/data/storage/artifacts/bulk-delete'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify({ artifact_ids: artifactIds }),
    })
    return handleJson(res)
  },

  // ========== Storage Browsing API ==========

  /**
   * List all accessible storage buckets with metadata
   */
  async listBuckets(token?: string): Promise<{
    buckets: Array<{
      name: string
      display_name: string
      is_protected: boolean
      is_default: boolean
    }>
    default_bucket: string
  }> {
    const res = await fetch(apiUrl('/data/storage/browse'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  /**
   * Browse bucket contents at a specific path
   */
  async browse(bucket: string, prefix: string = '', token?: string): Promise<{
    bucket: string
    prefix: string
    folders: string[]
    files: Array<{
      key: string
      filename: string
      size: number
      content_type: string | null
      etag: string
      last_modified: string
      is_folder: boolean
      asset_id: string | null
    }>
    is_protected: boolean
    parent_path: string | null
  }> {
    const url = new URL(apiUrl(`/data/storage/browse/${encodeURIComponent(bucket)}`))
    if (prefix) {
      url.searchParams.set('prefix', prefix)
    }
    const res = await fetch(url.toString(), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  /**
   * Get list of protected bucket names
   */
  async getProtectedBuckets(token?: string): Promise<{
    protected_buckets: string[]
  }> {
    const res = await fetch(apiUrl('/data/storage/buckets/protected'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  // ========== Folder Management API ==========

  /**
   * Create a new folder in storage
   */
  async createFolder(bucket: string, path: string, token?: string): Promise<{
    success: boolean
    bucket: string
    path: string
  }> {
    const res = await fetch(apiUrl('/data/storage/folders'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify({ bucket, path }),
    })
    return handleJson(res)
  },

  /**
   * Upload a file directly to a folder
   */
  async uploadToFolder(bucket: string, prefix: string, file: File, token?: string): Promise<{
    success: boolean
    bucket: string
    prefix: string
    filename: string
    object_key: string
    file_size: number
  }> {
    const formData = new FormData()
    formData.append('bucket', bucket)
    formData.append('prefix', prefix)
    formData.append('file', file)

    const res = await fetch(apiUrl('/data/storage/folders/upload'), {
      method: 'POST',
      headers: authHeaders(token),
      body: formData,
    })
    return handleJson(res)
  },

  /**
   * Delete a folder from storage
   */
  async deleteFolder(bucket: string, path: string, recursive: boolean = false, token?: string): Promise<{
    success: boolean
    bucket: string
    path: string
    deleted_count: number
    failed_count: number
  }> {
    const url = new URL(apiUrl(`/data/storage/folders/${encodeURIComponent(bucket)}/${path}`))
    url.searchParams.set('recursive', String(recursive))
    const res = await fetch(url.toString(), {
      method: 'DELETE',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  /**
   * Delete a file from storage by bucket and key
   */
  async deleteFile(bucket: string, key: string, token?: string): Promise<{
    success: boolean
    bucket: string
    key: string
    artifact_deleted: boolean
  }> {
    const res = await fetch(apiUrl(`/data/storage/files/${encodeURIComponent(bucket)}/${key}`), {
      method: 'DELETE',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  // ========== File Operations API ==========

  /**
   * Move files to a different location
   */
  async moveFiles(
    artifactIds: string[],
    destinationBucket: string,
    destinationPrefix: string,
    token?: string
  ): Promise<{
    moved_count: number
    failed_count: number
    moved_artifacts: string[]
    failed_artifacts: string[]
  }> {
    const res = await fetch(apiUrl('/data/storage/files/move'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify({
        artifact_ids: artifactIds,
        destination_bucket: destinationBucket,
        destination_prefix: destinationPrefix,
      }),
    })
    return handleJson(res)
  },

  /**
   * Rename a file in storage
   */
  async renameFile(artifactId: string, newName: string, token?: string): Promise<{
    success: boolean
    artifact_id: string
    old_name: string
    new_name: string
    new_key: string
  }> {
    const res = await fetch(apiUrl('/data/storage/files/rename'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify({
        artifact_id: artifactId,
        new_name: newName,
      }),
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
    const res = await fetch(apiUrl('/admin/organizations/me/users'), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getUser(token: string, userId: string): Promise<any> {
    const res = await fetch(apiUrl(`/admin/organizations/me/users/${userId}`), {
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
    const res = await fetch(apiUrl('/admin/organizations/me/users'), {
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
    const res = await fetch(apiUrl(`/admin/organizations/me/users/${userId}`), {
      method: 'PUT',
      headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async deleteUser(token: string, userId: string): Promise<{
    message: string
  }> {
    const res = await fetch(apiUrl(`/admin/organizations/me/users/${userId}`), {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    })
    return handleJson(res)
  },

  async changePassword(token: string, userId: string, newPassword: string): Promise<{
    message: string
  }> {
    const res = await fetch(apiUrl(`/admin/organizations/me/users/${userId}/password`), {
      method: 'PUT',
      headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
      body: JSON.stringify({ new_password: newPassword }),
    })
    return handleJson(res)
  },
}

// ============================================================================
// Assets API (Phase 1)
// ============================================================================

export interface Asset {
  id: string
  organization_id: string
  source_type: string
  source_metadata: Record<string, any>
  original_filename: string
  content_type: string | null
  file_size: number | null
  file_hash: string | null
  raw_bucket: string
  raw_object_key: string
  status: string
  current_version_number: number | null
  created_at: string
  updated_at: string
  created_by: string | null
  // Extraction pipeline status fields
  extraction_tier: string | null
  indexed_at: string | null
}

export interface AssetVersion {
  id: string
  asset_id: string
  version_number: number
  raw_bucket: string
  raw_object_key: string
  file_size: number | null
  file_hash: string | null
  content_type: string | null
  is_current: boolean
  created_at: string
  created_by: string | null
  // Extraction info (permanent data)
  extraction_status?: string | null
  extraction_tier?: string | null
  extractor_version?: string | null
  extraction_time_seconds?: number | null
  extraction_created_at?: string | null
  extraction_run_id?: string | null
}

export interface ExtractionResult {
  id: string
  asset_id: string
  run_id: string
  extractor_version: string
  extraction_tier?: string | null
  status: string
  extracted_bucket: string | null
  extracted_object_key: string | null
  structure_metadata: Record<string, any> | null
  warnings: string[]
  errors: string[]
  extraction_time_seconds: number | null
  created_at: string
  // Triage fields (new extraction routing architecture)
  triage_engine?: 'fast_pdf' | 'fast_office' | 'docling' | 'ocr_only' | null
  triage_needs_ocr?: boolean | null
  triage_needs_layout?: boolean | null
  triage_complexity?: 'low' | 'medium' | 'high' | null
  triage_duration_ms?: number | null
}

export interface Run {
  id: string
  organization_id: string
  run_type: string
  origin: string
  status: string
  input_asset_ids: string[]
  config: Record<string, any>
  progress: Record<string, any> | null
  results_summary: Record<string, any> | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  last_activity_at: string | null
  created_by: string | null
  // Queue info (for pending runs)
  queue_position: number | null
  queue_priority: number | null
}

export interface RunLogEvent {
  id: string
  run_id: string
  level: string
  event_type: string
  message: string
  context: Record<string, any> | null
  created_at: string
}

export interface AssetWithExtraction {
  asset: Asset
  extraction: ExtractionResult | null
}

export interface AssetVersionHistory {
  asset: Asset
  versions: AssetVersion[]
  total_versions: number
}

export interface AssetQueueInfo {
  // Unified status from the backend status mapper
  unified_status: 'queued' | 'submitted' | 'processing' | 'completed' | 'failed' | 'timed_out' | 'cancelled'
  // Legacy status field (for backward compat)
  status?: 'not_found' | 'ready' | 'failed' | 'pending' | 'submitted' | 'running' | 'completed' | 'timed_out' | 'cancelled' | 'processing' | 'queued'
  asset_id: string
  run_id?: string
  run_status?: string
  in_queue: boolean
  queue_position?: number
  total_pending?: number
  estimated_wait_seconds?: number
  submitted_to_celery?: boolean
  timeout_at?: string
  submitted_at?: string
  celery_task_id?: string
  extractor_version?: string
  queue_stats?: {
    processing_priority: number
    processing: number
    maintenance: number
  }
  created_at?: string
  started_at?: string
  message?: string
}

// ======================================================================
// BULK UPLOAD INTERFACES (Phase 2)
// ======================================================================

export interface BulkUploadFileInfo {
  filename: string
  file_size: number
  file_hash: string
  asset_id?: string
  current_version?: number
  old_file_hash?: string
  status?: string
}

export interface BulkUploadAnalysis {
  unchanged: BulkUploadFileInfo[]
  updated: BulkUploadFileInfo[]
  new: BulkUploadFileInfo[]
  missing: BulkUploadFileInfo[]
  counts: {
    unchanged: number
    updated: number
    new: number
    missing: number
    total_uploaded: number
  }
}

export interface BulkUploadApplyResult {
  analysis: BulkUploadAnalysis
  created_assets: string[]
  updated_assets: string[]
  marked_inactive: string[]
  summary: {
    created_count: number
    updated_count: number
    marked_inactive_count: number
  }
}

export interface CollectionHealth {
  total_assets: number
  extraction_coverage: number
  status_breakdown: {
    ready: number
    pending: number
    failed: number
    inactive: number
  }
  version_stats: {
    multi_version_assets: number
    total_versions: number
  }
  last_updated: string | null
}

// ======================================================================
// ASSET METADATA INTERFACES (Phase 3)
// ======================================================================

export interface AssetMetadata {
  id: string
  asset_id: string
  metadata_type: string
  schema_version: string
  producer_run_id: string | null
  is_canonical: boolean
  status: string
  metadata_content: Record<string, any>
  metadata_object_ref: string | null
  created_at: string
  promoted_at: string | null
  superseded_at: string | null
  promoted_from_id: string | null
  superseded_by_id: string | null
}

export interface AssetMetadataList {
  canonical: AssetMetadata[]
  total_canonical: number
  metadata_types: string[]
}

export interface AssetMetadataCreateRequest {
  metadata_type: string
  metadata_content: Record<string, any>
  schema_version?: string
  is_canonical?: boolean
  producer_run_id?: string
}


export const assetsApi = {
  /**
   * List assets for the organization
   */
  async listAssets(token: string | undefined, params?: {
    source_type?: string
    status?: string
    limit?: number
    offset?: number
  }): Promise<{ items: Asset[]; total: number; limit: number; offset: number }> {
    const searchParams = new URLSearchParams()
    if (params?.source_type) searchParams.append('source_type', params.source_type)
    if (params?.status) searchParams.append('status', params.status)
    if (params?.limit) searchParams.append('limit', params.limit.toString())
    if (params?.offset) searchParams.append('offset', params.offset.toString())

    const url = apiUrl(`/data/assets?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get asset by ID
   */
  async getAsset(token: string | undefined, assetId: string): Promise<Asset> {
    const url = apiUrl(`/data/assets/${assetId}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get asset with latest extraction result
   */
  async getAssetWithExtraction(token: string | undefined, assetId: string): Promise<AssetWithExtraction> {
    const url = apiUrl(`/data/assets/${assetId}/extraction`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get runs for an asset
   */
  async getAssetRuns(token: string | undefined, assetId: string): Promise<Run[]> {
    const url = apiUrl(`/data/assets/${assetId}/runs`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Trigger manual re-extraction for an asset
   */
  async reextractAsset(token: string | undefined, assetId: string): Promise<Run> {
    const url = apiUrl(`/data/assets/${assetId}/reextract`)
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get queue position and extraction info for a pending asset
   */
  async getAssetQueueInfo(token: string | undefined, assetId: string): Promise<AssetQueueInfo> {
    const url = apiUrl(`/data/assets/${assetId}/queue-info`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get version history for an asset
   */
  async getAssetVersions(token: string | undefined, assetId: string): Promise<AssetVersionHistory> {
    const url = apiUrl(`/data/assets/${assetId}/versions`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get specific version of an asset
   */
  async getAssetVersion(token: string | undefined, assetId: string, versionNumber: number): Promise<AssetVersion> {
    const url = apiUrl(`/data/assets/${assetId}/versions/${versionNumber}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get run logs
   */
  async getRunLogs(token: string | undefined, runId: string, params?: {
    level?: string
    event_type?: string
    limit?: number
    offset?: number
  }): Promise<{ run: Run; logs: RunLogEvent[] }> {
    const searchParams = new URLSearchParams()
    if (params?.level) searchParams.append('level', params.level)
    if (params?.event_type) searchParams.append('event_type', params.event_type)
    if (params?.limit) searchParams.append('limit', params.limit.toString())
    if (params?.offset) searchParams.append('offset', params.offset.toString())

    const url = apiUrl(`/ops/runs/${runId}/logs?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Preview bulk upload changes (Phase 2)
   */
  async previewBulkUpload(token: string | undefined, files: File[], sourceType: string = 'upload'): Promise<BulkUploadAnalysis> {
    const formData = new FormData()
    files.forEach(file => formData.append('files', file))

    const url = apiUrl(`/data/assets/bulk-upload/preview?source_type=${sourceType}`)
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: formData,
    })
    return handleJson(res)
  },

  /**
   * Apply bulk upload changes (Phase 2)
   */
  async applyBulkUpload(
    token: string | undefined,
    files: File[],
    sourceType: string = 'upload',
    markMissingInactive: boolean = true
  ): Promise<BulkUploadApplyResult> {
    const formData = new FormData()
    files.forEach(file => formData.append('files', file))

    const url = apiUrl(`/data/assets/bulk-upload/apply?source_type=${sourceType}&mark_missing_inactive=${markMissingInactive}`)
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: formData,
    })
    return handleJson(res)
  },

  /**
   * Get collection health metrics (Phase 2)
   */
  async getCollectionHealth(token: string | undefined): Promise<CollectionHealth> {
    const url = apiUrl('/data/assets/health')
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  // ======================================================================
  // ASSET METADATA METHODS (Phase 3)
  // ======================================================================

  /**
   * Get all metadata for an asset (canonical + experimental)
   */
  async getAssetMetadata(token: string | undefined, assetId: string, includeSupersceded: boolean = false): Promise<AssetMetadataList> {
    const url = apiUrl(`/data/assets/${assetId}/metadata?include_superseded=${includeSupersceded}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Create new metadata for an asset
   */
  async createAssetMetadata(token: string | undefined, assetId: string, request: AssetMetadataCreateRequest): Promise<AssetMetadata> {
    const url = apiUrl(`/data/assets/${assetId}/metadata`)
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(request),
    })
    return handleJson(res)
  },

  /**
   * Get specific metadata by ID
   */
  async getSpecificMetadata(token: string | undefined, assetId: string, metadataId: string): Promise<AssetMetadata> {
    const url = apiUrl(`/data/assets/${assetId}/metadata/${metadataId}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Delete metadata
   */
  async deleteMetadata(token: string | undefined, assetId: string, metadataId: string): Promise<{ message: string; metadata_id: string }> {
    const url = apiUrl(`/data/assets/${assetId}/metadata/${metadataId}`)
    const res = await fetch(url, {
      method: 'DELETE',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Download the original uploaded file for an asset
   */
  async downloadOriginal(token: string, assetId: string, inline = false): Promise<Blob> {
    const url = new URL(apiUrl(`/data/assets/${assetId}/original`))
    url.searchParams.set('inline', String(inline))

    const res = await fetch(url.toString(), {
      headers: { Authorization: `Bearer ${token}` },
    })
    return handleBlob(res)
  },
}

// ============================================================================
// Scrape Collections API (Phase 4)
// ============================================================================

export interface ScrapeCollection {
  id: string
  organization_id: string
  name: string
  slug: string
  description: string | null
  collection_mode: 'snapshot' | 'record_preserving'
  root_url: string
  url_patterns: Array<{ type: 'include' | 'exclude'; pattern: string }>
  crawl_config: Record<string, any>
  status: 'active' | 'paused' | 'archived' | 'deleting'
  last_crawl_at: string | null
  last_crawl_run_id: string | null
  stats: Record<string, any>
  created_at: string
  updated_at: string
  created_by: string | null
}

export interface ScrapeSource {
  id: string
  collection_id: string
  url: string
  source_type: 'seed' | 'discovered' | 'manual'
  is_active: boolean
  crawl_config: Record<string, any> | null
  last_crawl_at: string | null
  last_status: string | null
  discovered_pages: number
  created_at: string
  updated_at: string
}

export interface ScrapedAsset {
  id: string
  asset_id: string
  collection_id: string
  source_id: string | null
  asset_subtype: 'page' | 'record' | 'document'
  url: string
  url_path: string | null
  parent_url: string | null
  crawl_depth: number
  crawl_run_id: string | null
  is_promoted: boolean
  promoted_at: string | null
  promoted_by: string | null
  scrape_metadata: Record<string, any>
  created_at: string
  updated_at: string
  original_filename: string | null
  asset_status: string | null
  title: string | null
}

export interface PathTreeNode {
  path: string
  name: string
  page_count: number
  record_count: number
  has_children: boolean
  is_directory: boolean
  child_count: number
}

export interface ScrapeCollectionCreateRequest {
  name: string
  root_url: string
  collection_mode?: 'snapshot' | 'record_preserving'
  description?: string
  url_patterns?: Array<{ type: 'include' | 'exclude'; pattern: string }>
  crawl_config?: Record<string, any>
}

export interface ScrapeCollectionUpdateRequest {
  name?: string
  description?: string
  collection_mode?: 'snapshot' | 'record_preserving'
  url_patterns?: Array<{ type: 'include' | 'exclude'; pattern: string }>
  crawl_config?: Record<string, any>
  status?: 'active' | 'paused' | 'archived'
}

export interface CrawlStatus {
  run_id: string
  status: string
  progress: Record<string, any> | null
  results_summary: Record<string, any> | null
  error_message: string | null
}

export const scrapeApi = {
  // ========== Collection Management ==========

  /**
   * List scrape collections
   */
  async listCollections(token: string | undefined, params?: {
    status?: 'active' | 'paused' | 'archived'
    limit?: number
    offset?: number
  }): Promise<{ collections: ScrapeCollection[]; total: number; limit: number; offset: number }> {
    const searchParams = new URLSearchParams()
    if (params?.status) searchParams.append('status', params.status)
    if (params?.limit) searchParams.append('limit', params.limit.toString())
    if (params?.offset) searchParams.append('offset', params.offset.toString())

    const url = apiUrl(`/data/scrape/collections?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Create a new scrape collection
   */
  async createCollection(token: string | undefined, request: ScrapeCollectionCreateRequest): Promise<ScrapeCollection> {
    const url = apiUrl('/data/scrape/collections')
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(request),
    })
    return handleJson(res)
  },

  /**
   * Get collection details
   */
  async getCollection(token: string | undefined, collectionId: string): Promise<ScrapeCollection> {
    const url = apiUrl(`/data/scrape/collections/${collectionId}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Update a collection
   */
  async updateCollection(token: string | undefined, collectionId: string, request: ScrapeCollectionUpdateRequest): Promise<ScrapeCollection> {
    const url = apiUrl(`/data/scrape/collections/${collectionId}`)
    const res = await fetch(url, {
      method: 'PUT',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(request),
    })
    return handleJson(res)
  },

  /**
   * Delete a collection (async with cleanup)
   * Returns immediately with a run_id to track the deletion progress
   */
  async deleteCollection(token: string | undefined, collectionId: string): Promise<{ message: string; run_id: string; status: string }> {
    const url = apiUrl(`/data/scrape/collections/${collectionId}`)
    const res = await fetch(url, {
      method: 'DELETE',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    if (!res.ok) {
      const error = await res.text()
      throw new Error(error || res.statusText)
    }
    return res.json()
  },

  // ========== Crawl Management ==========

  /**
   * Start a crawl for a collection
   */
  async startCrawl(token: string | undefined, collectionId: string, maxPages?: number): Promise<{ run_id: string; collection_id: string; status: string; message: string }> {
    const url = apiUrl(`/data/scrape/collections/${collectionId}/crawl`)
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: maxPages ? JSON.stringify({ max_pages: maxPages }) : '{}',
    })
    return handleJson(res)
  },

  /**
   * Get crawl status
   */
  async getCrawlStatus(token: string | undefined, collectionId: string): Promise<CrawlStatus> {
    const url = apiUrl(`/data/scrape/collections/${collectionId}/crawl/status`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  // ========== Source Management ==========

  /**
   * List sources for a collection
   */
  async listSources(token: string | undefined, collectionId: string, isActive?: boolean): Promise<{ sources: ScrapeSource[]; total: number }> {
    const searchParams = new URLSearchParams()
    if (isActive !== undefined) searchParams.append('is_active', isActive.toString())

    const url = apiUrl(`/data/scrape/collections/${collectionId}/sources?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Add a source to a collection
   */
  async addSource(token: string | undefined, collectionId: string, url_source: string, sourceType: string = 'seed', crawlConfig?: Record<string, any>): Promise<ScrapeSource> {
    const url = apiUrl(`/data/scrape/collections/${collectionId}/sources`)
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ url: url_source, source_type: sourceType, crawl_config: crawlConfig }),
    })
    return handleJson(res)
  },

  /**
   * Delete a source
   */
  async deleteSource(token: string | undefined, collectionId: string, sourceId: string): Promise<void> {
    const url = apiUrl(`/data/scrape/collections/${collectionId}/sources/${sourceId}`)
    const res = await fetch(url, {
      method: 'DELETE',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    if (!res.ok) {
      const error = await res.text()
      throw new Error(error || res.statusText)
    }
  },

  // ========== Scraped Assets ==========

  /**
   * List scraped assets
   */
  async listScrapedAssets(token: string | undefined, collectionId: string, params?: {
    asset_subtype?: 'page' | 'record'
    url_path_prefix?: string
    is_promoted?: boolean
    limit?: number
    offset?: number
  }): Promise<{ assets: ScrapedAsset[]; total: number; limit: number; offset: number }> {
    const searchParams = new URLSearchParams()
    if (params?.asset_subtype) searchParams.append('asset_subtype', params.asset_subtype)
    if (params?.url_path_prefix) searchParams.append('url_path_prefix', params.url_path_prefix)
    if (params?.is_promoted !== undefined) searchParams.append('is_promoted', params.is_promoted.toString())
    if (params?.limit) searchParams.append('limit', params.limit.toString())
    if (params?.offset) searchParams.append('offset', params.offset.toString())

    const url = apiUrl(`/data/scrape/collections/${collectionId}/assets?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get a scraped asset
   */
  async getScrapedAsset(token: string | undefined, collectionId: string, scrapedAssetId: string): Promise<ScrapedAsset> {
    const url = apiUrl(`/data/scrape/collections/${collectionId}/assets/${scrapedAssetId}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Promote a page to record
   */
  async promoteToRecord(token: string | undefined, collectionId: string, scrapedAssetId: string): Promise<{ scraped_asset: ScrapedAsset; message: string }> {
    const url = apiUrl(`/data/scrape/collections/${collectionId}/assets/${scrapedAssetId}/promote`)
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get extracted markdown content for a scraped asset
   */
  async getScrapedAssetContent(token: string | undefined, collectionId: string, scrapedAssetId: string): Promise<string> {
    const url = apiUrl(`/data/scrape/collections/${collectionId}/assets/${scrapedAssetId}/content`)
    const res = await fetch(url, {
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    if (!res.ok) {
      let text: string | undefined
      try { text = await res.text() } catch {}
      httpError(res, text)
    }
    return res.text()
  },

  // ========== Tree Browsing ==========

  /**
   * Get hierarchical path tree
   */
  async getPathTree(token: string | undefined, collectionId: string, pathPrefix: string = '/'): Promise<{ path_prefix: string; nodes: PathTreeNode[] }> {
    const searchParams = new URLSearchParams()
    searchParams.append('path_prefix', pathPrefix)

    const url = apiUrl(`/data/scrape/collections/${collectionId}/tree?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },
}

// -------------------- Scheduled Tasks API (Phase 5) --------------------

export interface ScheduledTask {
  id: string
  organization_id: string | null
  name: string
  display_name: string
  description: string | null
  task_type: string
  scope_type: string
  schedule_expression: string
  schedule_description: string
  enabled: boolean
  config: Record<string, any>
  last_run_id: string | null
  last_run_at: string | null
  last_run_status: string | null
  next_run_at: string | null
  created_at: string
  updated_at: string
}

export interface MaintenanceStats {
  total_tasks: number
  enabled_tasks: number
  disabled_tasks: number
  total_runs: number
  successful_runs: number
  failed_runs: number
  success_rate: number
  last_run_at: string | null
  last_run_status: string | null
  period_days: number
}

export interface TaskRun {
  id: string
  run_type: string
  origin: string
  status: string
  created_at: string
  started_at: string | null
  completed_at: string | null
  results_summary: Record<string, any> | null
  error_message: string | null
}

export const scheduledTasksApi = {
  /**
   * List scheduled tasks
   */
  async listTasks(token: string | undefined, enabledOnly?: boolean): Promise<{ tasks: ScheduledTask[]; total: number }> {
    const searchParams = new URLSearchParams()
    if (enabledOnly !== undefined) searchParams.append('enabled_only', enabledOnly.toString())

    const url = apiUrl(`/admin/scheduled-tasks?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get maintenance statistics
   */
  async getStats(token: string | undefined, days?: number): Promise<MaintenanceStats> {
    const searchParams = new URLSearchParams()
    if (days !== undefined) searchParams.append('days', days.toString())

    const url = apiUrl(`/admin/scheduled-tasks/stats?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get task details
   */
  async getTask(token: string | undefined, taskId: string): Promise<ScheduledTask> {
    const url = apiUrl(`/admin/scheduled-tasks/${taskId}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get task run history
   */
  async getTaskRuns(token: string | undefined, taskId: string, limit?: number, offset?: number): Promise<{ runs: TaskRun[]; total: number }> {
    const searchParams = new URLSearchParams()
    if (limit !== undefined) searchParams.append('limit', limit.toString())
    if (offset !== undefined) searchParams.append('offset', offset.toString())

    const url = apiUrl(`/admin/scheduled-tasks/${taskId}/runs?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Enable a scheduled task
   */
  async enableTask(token: string | undefined, taskId: string): Promise<{ message: string; task_id: string; task_name: string; enabled: boolean; next_run_at: string | null }> {
    const url = apiUrl(`/admin/scheduled-tasks/${taskId}/enable`)
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Disable a scheduled task
   */
  async disableTask(token: string | undefined, taskId: string): Promise<{ message: string; task_id: string; task_name: string; enabled: boolean; next_run_at: string | null }> {
    const url = apiUrl(`/admin/scheduled-tasks/${taskId}/disable`)
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Trigger a scheduled task immediately
   */
  async triggerTask(token: string | undefined, taskId: string, configOverrides?: Record<string, any>): Promise<{ message: string; task_id: string; task_name: string; run_id: string }> {
    const url = apiUrl(`/admin/scheduled-tasks/${taskId}/trigger`)
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(configOverrides ? { config_overrides: configOverrides } : {}),
    })
    return handleJson(res)
  },
}

// -------------------- Search API (Phase 6) --------------------

/**
 * Single bucket in a facet aggregation
 */
export interface FacetBucket {
  value: string
  count: number
}

/**
 * Facet aggregation result
 */
export interface Facet {
  field: string
  buckets: FacetBucket[]
  total_other: number
}

/**
 * Available facets in search response
 */
export interface SearchFacets {
  source_type?: Facet
  content_type?: Facet
}

/**
 * Search request parameters
 */
export interface SearchRequest {
  query: string
  search_mode?: 'keyword' | 'semantic' | 'hybrid'
  semantic_weight?: number
  source_types?: string[]
  content_types?: string[]
  collection_ids?: string[]
  sync_config_ids?: string[]
  date_from?: string
  date_to?: string
  metadata_filters?: Record<string, any>
  facet_filters?: Record<string, any>
  limit?: number
  offset?: number
  include_facets?: boolean
}

/**
 * Search result hit
 */
export interface SearchHit {
  asset_id: string
  score: number
  title?: string
  filename?: string
  source_type?: string
  content_type?: string
  url?: string
  created_at?: string
  highlights: Record<string, string[]>
  keyword_score?: number
  semantic_score?: number
}

/**
 * Search response
 */
export interface SearchResponse {
  total: number
  limit: number
  offset: number
  query: string
  hits: SearchHit[]
  facets?: SearchFacets
}

/**
 * Index statistics response
 */
export interface IndexStatsResponse {
  enabled: boolean
  status: string
  index_name?: string
  document_count?: number
  chunk_count?: number
  size_bytes?: number
  message?: string
}

/**
 * Reindex response
 */
export interface ReindexResponse {
  status: string
  message: string
  task_id?: string
}

/**
 * Search health response
 */
export interface SearchHealthResponse {
  enabled: boolean
  status: string
  backend?: string
  embedding_model?: string
  default_mode?: string
  message?: string
}

/**
 * Metadata field schema for a single field in a namespace
 */
export interface MetadataFieldSchema {
  type: string
  sample_values: any[]
  filterable: boolean
}

/**
 * Metadata namespace schema
 */
export interface MetadataNamespaceSchema {
  display_name: string
  source_types: string[]
  doc_count: number
  fields: Record<string, MetadataFieldSchema>
}

/**
 * Metadata schema discovery response
 */
export interface MetadataSchemaResponse {
  namespaces: Record<string, MetadataNamespaceSchema>
  total_indexed_docs: number
  cached_at?: string
}

export const searchApi = {
  /**
   * Search assets with full-text query
   */
  async search(token: string | undefined, request: SearchRequest): Promise<SearchResponse> {
    const url = apiUrl('/data/search')
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(request),
    })
    return handleJson(res)
  },

  /**
   * Search assets with simple GET query
   */
  async searchSimple(
    token: string | undefined,
    query: string,
    options?: {
      source_types?: string[]
      content_types?: string[]
      limit?: number
      offset?: number
    }
  ): Promise<SearchResponse> {
    const params = new URLSearchParams({ q: query })
    if (options?.source_types?.length) {
      params.set('source_types', options.source_types.join(','))
    }
    if (options?.content_types?.length) {
      params.set('content_types', options.content_types.join(','))
    }
    if (options?.limit !== undefined) {
      params.set('limit', options.limit.toString())
    }
    if (options?.offset !== undefined) {
      params.set('offset', options.offset.toString())
    }

    const url = apiUrl(`/data/search?${params.toString()}`)
    const res = await fetch(url, {
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get search index statistics
   */
  async getStats(token: string | undefined): Promise<IndexStatsResponse> {
    const url = apiUrl('/data/search/stats')
    const res = await fetch(url, {
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Trigger reindex of all assets (admin only)
   */
  async reindexAll(token: string | undefined): Promise<ReindexResponse> {
    const url = apiUrl('/data/search/reindex')
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Check search service health
   */
  async getHealth(token: string | undefined): Promise<SearchHealthResponse> {
    const url = apiUrl('/data/search/health')
    const res = await fetch(url, {
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get metadata schema for the organization's search index
   */
  async getMetadataSchema(token: string | undefined): Promise<MetadataSchemaResponse> {
    const url = apiUrl('/data/search/metadata-schema')
    const res = await fetch(url, {
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },
}

// ============================================================================
// Metadata Registry API (Data Core Governance)
// ============================================================================

/**
 * Metadata field definition from the registry
 */
export interface MetadataFieldDefinition {
  namespace: string
  field_name: string
  data_type: string
  indexed: boolean
  facetable: boolean
  applicable_content_types: string[]
  description?: string
  examples?: any[]
}

/**
 * Facet mapping to a JSON path within a content type
 */
export interface FacetMapping {
  content_type: string
  json_path: string
}

/**
 * Facet definition from the registry
 */
export interface FacetDefinition {
  facet_name: string
  display_name: string
  data_type: string
  description?: string
  operators: string[]
  mappings: FacetMapping[]
}

/**
 * Metadata namespace info
 */
export interface MetadataNamespace {
  namespace: string
  display_name: string
  description?: string
  fields: MetadataFieldDefinition[]
  doc_count: number
}

/**
 * Complete metadata catalog
 */
export interface MetadataCatalog {
  namespaces: MetadataNamespace[]
  facets: FacetDefinition[]
  total_indexed_docs: number
}

/**
 * Field statistics
 */
export interface MetadataFieldStats {
  namespace: string
  field_name: string
  sample_values: any[]
  doc_count: number
}

// -- Metadata Write Request Types --

export interface MetadataFieldCreateRequest {
  field_name: string
  data_type: string
  indexed?: boolean
  facetable?: boolean
  applicable_content_types?: string[]
  description?: string
  examples?: any[]
  sensitivity_tag?: string
}

export interface MetadataFieldUpdateRequest {
  indexed?: boolean
  facetable?: boolean
  applicable_content_types?: string[]
  description?: string
  examples?: any[]
  sensitivity_tag?: string
  status?: string
}

export interface FacetMappingCreateRequest {
  content_type: string
  json_path: string
}

export interface FacetCreateRequest {
  facet_name: string
  display_name: string
  data_type: string
  description?: string
  operators?: string[]
  mappings?: FacetMappingCreateRequest[]
}

export interface FacetUpdateRequest {
  display_name?: string
  description?: string
  operators?: string[]
  status?: string
}

export const metadataApi = {
  /**
   * Get the full metadata catalog (namespaces, fields, facets)
   */
  async getCatalog(token: string | undefined): Promise<MetadataCatalog> {
    const url = apiUrl('/data/metadata/catalog')
    const res = await fetch(url, {
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * List all namespaces with doc counts
   */
  async getNamespaces(token: string | undefined): Promise<MetadataNamespace[]> {
    const url = apiUrl('/data/metadata/namespaces')
    const res = await fetch(url, {
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get fields for a namespace
   */
  async getNamespaceFields(token: string | undefined, namespace: string): Promise<MetadataFieldDefinition[]> {
    const url = apiUrl(`/data/metadata/namespaces/${namespace}/fields`)
    const res = await fetch(url, {
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get statistics for a field
   */
  async getFieldStats(token: string | undefined, namespace: string, fieldName: string): Promise<MetadataFieldStats> {
    const url = apiUrl(`/data/metadata/fields/${namespace}/${fieldName}/stats`)
    const res = await fetch(url, {
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * List all facet definitions
   */
  async getFacets(token: string | undefined): Promise<FacetDefinition[]> {
    const url = apiUrl('/data/metadata/facets')
    const res = await fetch(url, {
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  // -- Write Operations --

  async createField(token: string | undefined, namespace: string, data: MetadataFieldCreateRequest): Promise<any> {
    const url = apiUrl(`/data/metadata/fields/${namespace}`)
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async updateField(token: string | undefined, namespace: string, fieldName: string, data: MetadataFieldUpdateRequest): Promise<any> {
    const url = apiUrl(`/data/metadata/fields/${namespace}/${fieldName}`)
    const res = await fetch(url, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async deleteField(token: string | undefined, namespace: string, fieldName: string): Promise<any> {
    const url = apiUrl(`/data/metadata/fields/${namespace}/${fieldName}`)
    const res = await fetch(url, {
      method: 'DELETE',
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  async createFacet(token: string | undefined, data: FacetCreateRequest): Promise<any> {
    const url = apiUrl('/data/metadata/facets')
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async updateFacet(token: string | undefined, facetName: string, data: FacetUpdateRequest): Promise<any> {
    const url = apiUrl(`/data/metadata/facets/${facetName}`)
    const res = await fetch(url, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async deleteFacet(token: string | undefined, facetName: string): Promise<any> {
    const url = apiUrl(`/data/metadata/facets/${facetName}`)
    const res = await fetch(url, {
      method: 'DELETE',
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  async addFacetMapping(token: string | undefined, facetName: string, data: FacetMappingCreateRequest): Promise<any> {
    const url = apiUrl(`/data/metadata/facets/${facetName}/mappings`)
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async removeFacetMapping(token: string | undefined, facetName: string, contentType: string): Promise<any> {
    const url = apiUrl(`/data/metadata/facets/${facetName}/mappings/${contentType}`)
    const res = await fetch(url, {
      method: 'DELETE',
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  async invalidateCache(token: string | undefined): Promise<any> {
    const url = apiUrl('/data/metadata/cache/invalidate')
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },
}

// ============================================================================
// SAM.gov API (Phase 7)
// ============================================================================

export interface SamSearch {
  id: string
  organization_id: string
  name: string
  slug: string
  description: string | null
  search_config: Record<string, any>
  status: 'active' | 'paused' | 'archived'
  is_active: boolean
  last_pull_at: string | null
  last_pull_status: string | null
  last_pull_run_id: string | null
  pull_frequency: 'manual' | 'hourly' | 'daily'
  created_at: string
  updated_at: string
  // Active pull tracking
  is_pulling: boolean
  current_pull_status: string | null  // pending, running, completed, failed
}

export interface SamPullHistoryItem {
  id: string
  run_type: string
  status: string
  started_at: string | null
  completed_at: string | null
  results_summary: {
    total_fetched?: number
    new_solicitations?: number
    updated_solicitations?: number
    new_notices?: number
    new_attachments?: number
    status?: string
  } | null
  error_message: string | null
}

export interface SamSolicitation {
  id: string
  organization_id: string
  notice_id: string
  solicitation_number: string | null
  title: string
  description: string | null
  notice_type: string
  naics_code: string | null
  psc_code: string | null
  set_aside_code: string | null
  status: string
  posted_date: string | null
  response_deadline: string | null
  ui_link: string | null
  contact_info: Record<string, any> | null
  // Organization hierarchy (parsed from fullParentPathName: AGENCY.BUREAU.OFFICE)
  agency_name: string | null
  bureau_name: string | null
  office_name: string | null
  full_parent_path: string | null
  notice_count: number
  attachment_count: number
  created_at: string
  updated_at: string
  // Phase 7.6: Auto-summary status
  summary_status?: 'pending' | 'generating' | 'ready' | 'failed' | 'no_llm' | null
  summary_generated_at?: string | null
  // Raw SAM.gov API response (for metadata tab)
  raw_data?: Record<string, any> | null
}

// Phase 7.6: Dashboard stats
export interface SamDashboardStats {
  total_notices: number
  total_solicitations: number
  recent_notices_7d: number
  new_solicitations_7d: number
  updated_solicitations_7d: number
  api_usage: SamApiUsage | null
}

// Phase 7.6: Notice with solicitation context for org-wide listing
export interface SamNoticeWithSolicitation {
  id: string
  solicitation_id: string | null  // Nullable for standalone notices (e.g., Special Notices)
  sam_notice_id: string
  notice_type: string
  version_number: number
  title: string | null
  description: string | null
  posted_date: string | null
  response_deadline: string | null
  changes_summary: string | null
  created_at: string
  // Solicitation context
  solicitation_number: string | null
  agency_name: string | null
  bureau_name: string | null
  office_name: string | null
}

// Phase 7.6: Notice list response
export interface SamNoticeListResponse {
  items: SamNoticeWithSolicitation[]
  total: number
  limit: number
  offset: number
}

// Phase 7.6: Notice filter params
export interface SamNoticeListParams {
  keyword?: string  // Search by title, description, or solicitation number
  agency?: string
  sub_agency?: string
  office?: string
  notice_type?: string
  posted_from?: string  // ISO date string
  posted_to?: string    // ISO date string
  limit?: number
  offset?: number
}

export interface SamNotice {
  id: string
  solicitation_id: string | null  // Nullable for standalone notices
  organization_id: string | null  // For standalone notices
  sam_notice_id: string
  notice_type: string
  version_number: number
  title: string | null
  description: string | null
  description_url: string | null  // SAM.gov API URL for full description
  posted_date: string | null
  response_deadline: string | null
  changes_summary: string | null
  created_at: string
  // Classification fields
  naics_code: string | null
  psc_code: string | null  // aka classification code
  set_aside_code: string | null
  // Agency hierarchy
  agency_name: string | null
  bureau_name: string | null
  office_name: string | null
  full_parent_path: string | null
  // UI link for standalone notices
  ui_link: string | null
  // Summary fields for standalone notices
  summary_status: string | null  // pending, generating, ready, failed, no_llm
  summary_generated_at: string | null
  // Is this a standalone notice?
  is_standalone: boolean
  // Raw SAM.gov API response (for metadata tab)
  raw_data?: Record<string, any> | null
}

export interface SamAttachment {
  id: string
  solicitation_id: string | null  // Nullable for standalone notice attachments
  notice_id: string | null
  asset_id: string | null
  resource_id: string
  filename: string
  file_type: string | null
  file_size: number | null
  description: string | null
  download_status: string
  downloaded_at: string | null
  created_at: string
}

export interface SamSummary {
  id: string
  solicitation_id: string
  summary_type: string
  is_canonical: boolean
  model: string
  summary: string
  key_requirements: Array<Record<string, any>> | null
  compliance_checklist: Array<Record<string, any>> | null
  confidence_score: number | null
  token_count: number | null
  created_at: string
  promoted_at: string | null
}

export interface SamApiUsage {
  date: string
  search_calls: number
  detail_calls: number
  attachment_calls: number
  total_calls: number
  daily_limit: number
  remaining_calls: number
  usage_percent: number
  reset_at: string
  is_over_limit: boolean
}

export interface SamQueueStats {
  pending: number
  processing: number
  completed: number
  failed: number
  ready_to_process: number
  total: number
}

export interface SamApiStatus {
  usage: SamApiUsage
  queue: SamQueueStats
  history: Array<Record<string, any>>
}

export interface SamPreviewResult {
  notice_id: string
  title: string
  solicitation_number: string | null
  notice_type: string
  naics_code: string | null
  psc_code: string | null
  set_aside: string | null
  posted_date: string | null
  response_deadline: string | null
  agency: string | null
  ui_link: string | null
  attachments_count: number
}

export interface SamAgency {
  id: string
  code: string
  name: string
  abbreviation: string | null
}

export const samApi = {
  // ========== Dashboard (Phase 7.6) ==========

  async getDashboardStats(token: string | undefined): Promise<SamDashboardStats> {
    const res = await fetch(apiUrl('/data/sam/dashboard'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async listAllNotices(
    token: string | undefined,
    params?: SamNoticeListParams
  ): Promise<SamNoticeListResponse> {
    const searchParams = new URLSearchParams()
    if (params?.keyword) searchParams.append('keyword', params.keyword)
    if (params?.agency) searchParams.append('agency', params.agency)
    if (params?.sub_agency) searchParams.append('sub_agency', params.sub_agency)
    if (params?.office) searchParams.append('office', params.office)
    if (params?.notice_type) searchParams.append('notice_type', params.notice_type)
    if (params?.posted_from) searchParams.append('posted_from', params.posted_from)
    if (params?.posted_to) searchParams.append('posted_to', params.posted_to)
    if (params?.limit) searchParams.append('limit', params.limit.toString())
    if (params?.offset) searchParams.append('offset', params.offset.toString())

    const url = apiUrl(`/data/sam/notices?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  // ========== Searches ==========

  async listSearches(token: string | undefined, params?: {
    status?: string
    is_active?: boolean
    limit?: number
    offset?: number
  }): Promise<{ items: SamSearch[]; total: number; limit: number; offset: number }> {
    const searchParams = new URLSearchParams()
    if (params?.status) searchParams.append('status', params.status)
    if (params?.is_active !== undefined) searchParams.append('is_active', String(params.is_active))
    if (params?.limit) searchParams.append('limit', params.limit.toString())
    if (params?.offset) searchParams.append('offset', params.offset.toString())

    const url = apiUrl(`/data/sam/searches?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getSearch(token: string | undefined, searchId: string): Promise<SamSearch> {
    console.log('[SAM API] getSearch - Request:', { searchId })
    const res = await fetch(apiUrl(`/data/sam/searches/${searchId}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    const result = await handleJson(res) as SamSearch
    console.log('[SAM API] getSearch - Response:', result)
    return result
  },

  async createSearch(token: string | undefined, data: {
    name: string
    description?: string
    search_config: Record<string, any>
    pull_frequency?: string
  }): Promise<SamSearch> {
    console.log('[SAM API] createSearch - Request:', data)
    const res = await fetch(apiUrl('/data/sam/searches'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(data),
    })
    const result = await handleJson(res) as SamSearch
    console.log('[SAM API] createSearch - Response:', result)
    return result
  },

  async updateSearch(token: string | undefined, searchId: string, data: {
    name?: string
    description?: string
    search_config?: Record<string, any>
    status?: string
    is_active?: boolean
    pull_frequency?: string
  }): Promise<SamSearch> {
    const res = await fetch(apiUrl(`/data/sam/searches/${searchId}`), {
      method: 'PATCH',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async deleteSearch(token: string | undefined, searchId: string): Promise<void> {
    const res = await fetch(apiUrl(`/data/sam/searches/${searchId}`), {
      method: 'DELETE',
      headers: authHeaders(token),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      httpError(res, body.detail || 'Delete failed', body)
    }
  },

  async triggerPull(token: string | undefined, searchId: string, params?: {
    max_pages?: number
    page_size?: number
  }): Promise<Record<string, any>> {
    console.log('[SAM API] triggerPull - Request:', { searchId, params })
    const res = await fetch(apiUrl(`/data/sam/searches/${searchId}/pull`), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(params || {}),
    })
    const result = await handleJson(res) as Record<string, any>
    console.log('[SAM API] triggerPull - Response:', result)
    return result
  },

  async getPullHistory(token: string | undefined, searchId: string, params?: {
    limit?: number
    offset?: number
  }): Promise<{ items: SamPullHistoryItem[]; total: number }> {
    console.log('[SAM API] getPullHistory - Request:', { searchId, params })
    const searchParams = new URLSearchParams()
    if (params?.limit) searchParams.append('limit', params.limit.toString())
    if (params?.offset) searchParams.append('offset', params.offset.toString())

    const url = apiUrl(`/data/sam/searches/${searchId}/pulls?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    type PullHistoryResponse = { items: SamPullHistoryItem[]; total: number }
    const result = await handleJson(res) as PullHistoryResponse
    console.log('[SAM API] getPullHistory - Response:', { total: result.total, itemCount: result.items?.length })
    return result
  },

  async previewSearch(token: string | undefined, data: {
    search_config: Record<string, any>
    limit?: number
  }): Promise<{
    success: boolean
    total_matching?: number
    sample_count?: number
    sample_results?: SamPreviewResult[]
    search_config?: Record<string, any>
    message: string
    error?: string
    remaining_calls?: number
  }> {
    console.log('[SAM API] previewSearch - Request:', data)
    const res = await fetch(apiUrl('/data/sam/searches/preview'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(data),
    })
    type PreviewResponse = {
      success: boolean
      total_matching?: number
      sample_count?: number
      sample_results?: SamPreviewResult[]
      search_config?: Record<string, any>
      message: string
      error?: string
      remaining_calls?: number
    }
    const result = await handleJson(res) as PreviewResponse
    console.log('[SAM API] previewSearch - Response:', result)
    return result
  },

  // ========== Solicitations ==========

  async listSolicitations(token: string | undefined, params?: {
    status?: string
    notice_type?: string
    naics_code?: string
    limit?: number
    offset?: number
  }): Promise<{ items: SamSolicitation[]; total: number; limit: number; offset: number }> {
    console.log('[SAM API] listSolicitations - Request params:', params)
    const searchParams = new URLSearchParams()
    if (params?.status) searchParams.append('status', params.status)
    if (params?.notice_type) searchParams.append('notice_type', params.notice_type)
    if (params?.naics_code) searchParams.append('naics_code', params.naics_code)
    if (params?.limit) searchParams.append('limit', params.limit.toString())
    if (params?.offset) searchParams.append('offset', params.offset.toString())

    const url = apiUrl(`/data/sam/solicitations?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    type ListResponse = { items: SamSolicitation[]; total: number; limit: number; offset: number }
    const result = await handleJson(res) as ListResponse
    console.log('[SAM API] listSolicitations - Response:', { total: result.total, itemCount: result.items?.length })
    return result
  },

  async getSolicitation(token: string | undefined, solicitationId: string): Promise<SamSolicitation> {
    const res = await fetch(apiUrl(`/data/sam/solicitations/${solicitationId}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getSolicitationNotices(token: string | undefined, solicitationId: string): Promise<SamNotice[]> {
    const res = await fetch(apiUrl(`/data/sam/solicitations/${solicitationId}/notices`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async refreshSolicitation(token: string | undefined, solicitationId: string, options?: {
    downloadAttachments?: boolean
  }): Promise<{
    run_id: string
    status: string
    solicitation_id: string
    download_attachments: boolean
  }> {
    const downloadAttachments = options?.downloadAttachments ?? true
    console.log('[SAM API] refreshSolicitation - Request:', { solicitationId, downloadAttachments })
    const params = new URLSearchParams()
    params.append('download_attachments', String(downloadAttachments))
    const res = await fetch(apiUrl(`/data/sam/solicitations/${solicitationId}/refresh?${params.toString()}`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    type RefreshResponse = {
      run_id: string
      status: string
      solicitation_id: string
      download_attachments: boolean
    }
    const result = await handleJson(res) as RefreshResponse
    console.log('[SAM API] refreshSolicitation - Response:', result)
    return result
  },

  async getSolicitationAttachments(token: string | undefined, solicitationId: string, params?: {
    download_status?: string
  }): Promise<SamAttachment[]> {
    const searchParams = new URLSearchParams()
    if (params?.download_status) searchParams.append('download_status', params.download_status)

    const url = apiUrl(`/data/sam/solicitations/${solicitationId}/attachments?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getSolicitationSummaries(token: string | undefined, solicitationId: string, params?: {
    summary_type?: string
  }): Promise<SamSummary[]> {
    const searchParams = new URLSearchParams()
    if (params?.summary_type) searchParams.append('summary_type', params.summary_type)

    const url = apiUrl(`/data/sam/solicitations/${solicitationId}/summaries?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async generateSummary(token: string | undefined, solicitationId: string, data: {
    summary_type?: string
    model?: string
    include_attachments?: boolean
  }): Promise<SamSummary> {
    const res = await fetch(apiUrl(`/data/sam/solicitations/${solicitationId}/summarize`), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  // Phase 7.6: Regenerate auto-summary
  async regenerateSummary(token: string | undefined, solicitationId: string): Promise<SamSolicitation> {
    const res = await fetch(apiUrl(`/data/sam/solicitations/${solicitationId}/regenerate-summary`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  async downloadAllAttachments(token: string | undefined, solicitationId: string): Promise<Record<string, any>> {
    const res = await fetch(apiUrl(`/data/sam/solicitations/${solicitationId}/download-attachments`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  // ========== Notices ==========

  async getNotice(token: string | undefined, noticeId: string, options?: {
    includeMetadata?: boolean
  }): Promise<SamNotice> {
    const params = new URLSearchParams()
    if (options?.includeMetadata) params.append('include_metadata', 'true')
    const url = apiUrl(`/data/sam/notices/${noticeId}${params.toString() ? '?' + params.toString() : ''}`)
    const res = await fetch(url, {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async generateNoticeChanges(token: string | undefined, noticeId: string): Promise<{
    notice_id: string
    changes_summary: string
  }> {
    const res = await fetch(apiUrl(`/data/sam/notices/${noticeId}/generate-changes`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  async refreshNotice(token: string | undefined, noticeId: string): Promise<{
    notice_id: string
    description_updated: boolean
    error?: string
  }> {
    console.log('[samApi.refreshNotice] Refreshing notice:', noticeId)
    const res = await fetch(apiUrl(`/data/sam/notices/${noticeId}/refresh`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    const result = await handleJson(res)
    console.log('[samApi.refreshNotice] Result:', result)
    return result as {
      notice_id: string
      description_updated: boolean
      error?: string
    }
  },

  async regenerateNoticeSummary(token: string | undefined, noticeId: string): Promise<{
    notice_id: string
    status: string
    message: string
  }> {
    const res = await fetch(apiUrl(`/data/sam/notices/${noticeId}/regenerate-summary`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  async downloadNoticeAttachments(token: string | undefined, noticeId: string): Promise<{
    total: number
    downloaded: number
    failed: number
    errors: Array<{ attachment_id: string; error: string }>
  }> {
    const res = await fetch(apiUrl(`/data/sam/notices/${noticeId}/download-attachments`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  async getNoticeAttachments(
    token: string | undefined,
    noticeId: string,
    downloadStatus?: string
  ): Promise<SamAttachment[]> {
    const params = new URLSearchParams()
    if (downloadStatus) params.append('download_status', downloadStatus)
    const url = apiUrl(`/data/sam/notices/${noticeId}/attachments?${params.toString()}`)
    const res = await fetch(url, {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getNoticeDescription(token: string | undefined, noticeId: string): Promise<{
    notice_id: string
    description: string | null
  }> {
    const res = await fetch(apiUrl(`/data/sam/notices/${noticeId}/description`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  // ========== Attachments ==========

  async getAttachment(token: string | undefined, attachmentId: string): Promise<SamAttachment> {
    const res = await fetch(apiUrl(`/data/sam/attachments/${attachmentId}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async downloadAttachment(token: string | undefined, attachmentId: string): Promise<{
    attachment_id: string
    asset_id?: string
    status: string
    error?: string
  }> {
    const res = await fetch(apiUrl(`/data/sam/attachments/${attachmentId}/download`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  // ========== Summaries ==========

  async getSummary(token: string | undefined, summaryId: string): Promise<SamSummary> {
    const res = await fetch(apiUrl(`/data/sam/summaries/${summaryId}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async promoteSummary(token: string | undefined, summaryId: string): Promise<SamSummary> {
    const res = await fetch(apiUrl(`/data/sam/summaries/${summaryId}/promote`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  async deleteSummary(token: string | undefined, summaryId: string): Promise<void> {
    const res = await fetch(apiUrl(`/data/sam/summaries/${summaryId}`), {
      method: 'DELETE',
      headers: authHeaders(token),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      httpError(res, body.detail || 'Delete failed', body)
    }
  },

  // ========== Agencies ==========

  async listAgencies(token: string | undefined): Promise<SamAgency[]> {
    const res = await fetch(apiUrl('/data/sam/agencies'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  // ========== API Usage ==========

  async getUsage(token: string | undefined): Promise<SamApiUsage> {
    const res = await fetch(apiUrl('/data/sam/usage'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getUsageHistory(token: string | undefined, days: number = 30): Promise<{
    items: Array<Record<string, any>>
    days: number
  }> {
    const res = await fetch(apiUrl(`/data/sam/usage/history?days=${days}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async estimateImpact(token: string | undefined, data: {
    search_config: Record<string, any>
    max_pages?: number
    page_size?: number
  }): Promise<{
    estimated_calls: number
    breakdown: Record<string, number>
    current_usage: number
    remaining_before: number
    remaining_after: number
    will_exceed_limit: boolean
    daily_limit: number
  }> {
    const res = await fetch(apiUrl('/data/sam/usage/estimate'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async getApiStatus(token: string | undefined, historyDays: number = 7): Promise<SamApiStatus> {
    const res = await fetch(apiUrl(`/data/sam/usage/status?history_days=${historyDays}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getQueueStats(token: string | undefined): Promise<SamQueueStats> {
    const res = await fetch(apiUrl('/data/sam/queue'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  // ========== Search (Phase 7.6) ==========

  async searchSam(token: string | undefined, params: {
    query: string
    source_types?: string[]  // 'notices' | 'solicitations'
    notice_types?: string[]
    agencies?: string[]
    date_from?: string
    date_to?: string
    limit?: number
    offset?: number
  }): Promise<{
    total: number
    limit: number
    offset: number
    query: string
    hits: Array<{
      asset_id: string
      score: number
      title: string | null
      filename: string | null  // Solicitation number
      source_type: string | null  // 'sam_notice' | 'sam_solicitation'
      content_type: string | null  // Notice type
      url: string | null
      created_at: string | null
      highlights: Record<string, string[]>
    }>
  }> {
    const res = await fetch(apiUrl('/data/search/sam'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(params),
    })
    return handleJson(res)
  },
}

// -------------------- SharePoint Sync API (Phase 8) --------------------

export interface SharePointSyncConfig {
  id: string
  organization_id: string
  connection_id: string | null
  connection_name: string | null
  name: string
  slug: string
  description: string | null
  folder_url: string
  folder_name: string | null
  folder_drive_id: string | null
  folder_item_id: string | null
  sync_config: Record<string, any>
  status: string
  is_active: boolean
  last_sync_at: string | null
  last_sync_status: string | null
  last_sync_run_id: string | null
  sync_frequency: string
  stats: Record<string, any>
  created_at: string
  updated_at: string
  created_by: string | null
  is_syncing: boolean
  current_sync_status: string | null
  // Delta sync fields
  delta_enabled: boolean
  has_delta_token: boolean
  last_delta_sync_at: string | null
}

export interface SharePointSyncedDocument {
  id: string
  asset_id: string
  sync_config_id: string
  sharepoint_item_id: string
  sharepoint_drive_id: string
  sharepoint_path: string | null
  sharepoint_web_url: string | null
  sharepoint_etag: string | null
  content_hash: string | null
  sharepoint_created_at: string | null
  sharepoint_modified_at: string | null
  sharepoint_created_by: string | null
  sharepoint_modified_by: string | null
  file_size: number | null
  sync_status: string
  last_synced_at: string | null
  last_sync_run_id: string | null
  deleted_detected_at: string | null
  sync_metadata: Record<string, any>
  created_at: string
  updated_at: string
  original_filename: string | null
  asset_status: string | null
}

export interface SharePointBrowseItem {
  id: string
  name: string
  type: 'file' | 'folder'
  size?: number
  web_url?: string
  mime?: string
  folder?: string
  created?: string
  modified?: string
  drive_id?: string
}

export const sharepointSyncApi = {
  // ========== Sync Configs ==========

  async listConfigs(
    token: string | undefined,
    params?: {
      status?: string
      limit?: number
      offset?: number
    }
  ): Promise<{
    configs: SharePointSyncConfig[]
    total: number
    limit: number
    offset: number
  }> {
    const searchParams = new URLSearchParams()
    if (params?.status) searchParams.append('status', params.status)
    if (params?.limit) searchParams.append('limit', params.limit.toString())
    if (params?.offset) searchParams.append('offset', params.offset.toString())

    const url = apiUrl(`/data/sharepoint-sync/configs?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getConfig(
    token: string | undefined,
    configId: string
  ): Promise<SharePointSyncConfig> {
    const res = await fetch(apiUrl(`/data/sharepoint-sync/configs/${configId}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async createConfig(
    token: string | undefined,
    data: {
      name: string
      description?: string
      connection_id?: string
      folder_url: string
      sync_config?: Record<string, any>
      sync_frequency?: string
    }
  ): Promise<SharePointSyncConfig> {
    const res = await fetch(apiUrl('/data/sharepoint-sync/configs'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async updateConfig(
    token: string | undefined,
    configId: string,
    data: {
      name?: string
      description?: string
      sync_config?: Record<string, any>
      status?: string
      is_active?: boolean
      sync_frequency?: string
      reset_existing_assets?: boolean
    }
  ): Promise<SharePointSyncConfig> {
    const res = await fetch(apiUrl(`/data/sharepoint-sync/configs/${configId}`), {
      method: 'PATCH',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async deleteConfig(token: string | undefined, configId: string): Promise<{
    message: string
    run_id: string
    status: string
  }> {
    const res = await fetch(apiUrl(`/data/sharepoint-sync/configs/${configId}`), {
      method: 'DELETE',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  async archiveConfig(token: string | undefined, configId: string): Promise<{
    message: string
    archive_stats: {
      search_removed: number
      errors: string[]
    }
  }> {
    const res = await fetch(apiUrl(`/data/sharepoint-sync/configs/${configId}/archive`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  // ========== Sync Execution ==========

  async triggerSync(
    token: string | undefined,
    configId: string,
    fullSync: boolean = false
  ): Promise<{
    sync_config_id: string
    run_id: string
    status: string
    message: string
  }> {
    const res = await fetch(apiUrl(`/data/sharepoint-sync/configs/${configId}/sync`), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify({ full_sync: fullSync }),
    })
    return handleJson(res)
  },

  async cancelStuckRuns(
    token: string | undefined,
    configId: string
  ): Promise<{
    message: string
    cancelled_count: number
    run_ids: string[]
  }> {
    const res = await fetch(apiUrl(`/data/sharepoint-sync/configs/${configId}/cancel-stuck`), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
    })
    return handleJson(res)
  },

  async getHistory(
    token: string | undefined,
    configId: string,
    params?: {
      limit?: number
      offset?: number
    }
  ): Promise<{
    runs: Array<{
      id: string
      organization_id: string
      run_type: string
      origin: string
      status: string
      config: Record<string, any>
      progress: Record<string, any> | null
      results_summary: Record<string, any> | null
      error_message: string | null
      created_at: string
      started_at: string | null
      completed_at: string | null
    }>
    total: number
  }> {
    const searchParams = new URLSearchParams()
    if (params?.limit) searchParams.append('limit', params.limit.toString())
    if (params?.offset) searchParams.append('offset', params.offset.toString())

    const url = apiUrl(`/data/sharepoint-sync/configs/${configId}/history?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  // ========== Synced Documents ==========

  async listDocuments(
    token: string | undefined,
    configId: string,
    params?: {
      sync_status?: string
      limit?: number
      offset?: number
    }
  ): Promise<{
    documents: SharePointSyncedDocument[]
    total: number
    limit: number
    offset: number
  }> {
    const searchParams = new URLSearchParams()
    if (params?.sync_status) searchParams.append('sync_status', params.sync_status)
    if (params?.limit) searchParams.append('limit', params.limit.toString())
    if (params?.offset) searchParams.append('offset', params.offset.toString())

    const url = apiUrl(`/data/sharepoint-sync/configs/${configId}/documents?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async cleanupDeleted(
    token: string | undefined,
    configId: string,
    deleteAssets: boolean = false
  ): Promise<{
    sync_config_id: string
    documents_removed: number
    assets_deleted: number
    message: string
  }> {
    const res = await fetch(apiUrl(`/data/sharepoint-sync/configs/${configId}/cleanup`), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify({ delete_assets: deleteAssets }),
    })
    return handleJson(res)
  },

  // ========== Browse and Import ==========

  async browseFolder(
    token: string | undefined,
    data: {
      connection_id?: string
      folder_url: string
      recursive?: boolean
      include_folders?: boolean
    }
  ): Promise<{
    folder_name: string
    folder_id: string
    folder_url: string
    drive_id: string
    items: SharePointBrowseItem[]
    total_items: number
  }> {
    const res = await fetch(apiUrl('/data/sharepoint-sync/browse'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async importFiles(
    token: string | undefined,
    data: {
      connection_id?: string
      folder_url: string
      selected_items: Array<{
        id: string
        name: string
        type?: string
        folder?: string
        drive_id?: string
        size?: number
        web_url?: string
        mime?: string
      }>
      sync_config_id?: string
      sync_config_name?: string
      sync_config_description?: string
      create_sync_config?: boolean
      sync_frequency?: string
    }
  ): Promise<{
    run_id: string
    sync_config_id: string | null
    status: string
    message: string
    selected_count: number
  }> {
    const res = await fetch(apiUrl('/data/sharepoint-sync/import'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async removeItems(
    token: string | undefined,
    configId: string,
    itemIds: string[],
    deleteAssets: boolean = true
  ): Promise<{
    sync_config_id: string
    documents_removed: number
    assets_deleted: number
    message: string
  }> {
    const res = await fetch(apiUrl(`/data/sharepoint-sync/configs/${configId}/remove-items`), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify({
        item_ids: itemIds,
        delete_assets: deleteAssets,
      }),
    })
    return handleJson(res)
  },
}

// =============================================================================
// FUNCTIONS API
// =============================================================================

export interface FunctionParameter {
  name: string
  type: string
  description: string
  required: boolean
  default?: any
  enum_values?: string[]
  example?: any
}

export interface OutputField {
  name: string
  type: string
  description: string
  example?: any
  nullable: boolean
}

export interface OutputSchema {
  type: string
  description: string
  fields: OutputField[]
  example?: any
}

export interface OutputVariant {
  mode: string
  condition: string
  schema: OutputSchema
}

export interface FunctionMeta {
  name: string
  description: string
  category: string
  parameters: FunctionParameter[]
  returns: string
  output_schema?: OutputSchema
  output_variants?: OutputVariant[]
  examples?: Array<Record<string, any>>
  tags: string[]
  is_async: boolean
  version: string
  requires_llm?: boolean
  requires_session?: boolean
  // Governance fields
  side_effects?: boolean
  is_primitive?: boolean
  payload_profile?: string
  exposure_profile?: Record<string, any>
}

export interface FunctionListResponse {
  functions: FunctionMeta[]
  categories: string[]
  total: number
}

export interface FunctionExecuteResult {
  status: string
  message?: string
  data?: any
  error?: string
  metadata?: Record<string, any>
  items_processed?: number
  items_failed?: number
  duration_ms?: number
}

export const functionsApi = {
  async listFunctions(token?: string): Promise<FunctionListResponse> {
    const res = await fetch(apiUrl('/cwr/functions/'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getCategories(token?: string): Promise<{ categories: Record<string, string[]> }> {
    const res = await fetch(apiUrl('/cwr/functions/categories'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getFunction(token: string | undefined, name: string): Promise<FunctionMeta> {
    const res = await fetch(apiUrl(`/cwr/functions/${name}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async executeFunction(
    token: string | undefined,
    name: string,
    params: Record<string, any> = {},
    dryRun: boolean = false
  ): Promise<FunctionExecuteResult> {
    const res = await fetch(apiUrl(`/cwr/functions/${name}/execute`), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify({ params, dry_run: dryRun }),
    })
    return handleJson(res)
  },
}

// =============================================================================
// TOOL CONTRACTS API
// =============================================================================

export interface ToolContract {
  name: string
  description: string
  category: string
  version: string
  input_schema: Record<string, any>
  output_schema: Record<string, any>
  side_effects: boolean
  is_primitive: boolean
  payload_profile: string
  exposure_profile: Record<string, any>
  requires_llm: boolean
  requires_session: boolean
  tags: string[]
}

export interface ToolContractListResponse {
  contracts: ToolContract[]
  total: number
}

export const contractsApi = {
  async listContracts(
    token?: string,
    filters?: { category?: string; side_effects?: boolean; payload_profile?: string }
  ): Promise<ToolContractListResponse> {
    const params = new URLSearchParams()
    if (filters?.category) params.set('category', filters.category)
    if (filters?.side_effects !== undefined) params.set('side_effects', String(filters.side_effects))
    if (filters?.payload_profile) params.set('payload_profile', filters.payload_profile)
    const qs = params.toString()
    const res = await fetch(apiUrl(`/cwr/contracts/${qs ? `?${qs}` : ''}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getContract(token: string | undefined, name: string): Promise<ToolContract> {
    const res = await fetch(apiUrl(`/cwr/contracts/${name}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getInputSchema(token: string | undefined, name: string): Promise<Record<string, any>> {
    const res = await fetch(apiUrl(`/cwr/contracts/${name}/input-schema`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getOutputSchema(token: string | undefined, name: string): Promise<Record<string, any>> {
    const res = await fetch(apiUrl(`/cwr/contracts/${name}/output-schema`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },
}

// =============================================================================
// PROCEDURES API
// =============================================================================

export interface ProcedureTrigger {
  id?: string
  trigger_type: string
  cron_expression?: string
  event_name?: string
  event_filter?: Record<string, any>
  is_active: boolean
  last_triggered_at?: string
  next_trigger_at?: string
}

export interface ProcedureListItem {
  id: string
  name: string
  slug: string
  description?: string
  version: number
  is_active: boolean
  is_system: boolean
  source_type: string
  trigger_count: number
  next_trigger_at?: string  // Soonest scheduled run time
  tags: string[]
  created_at: string
  updated_at: string
}

export interface Procedure {
  id: string
  name: string
  slug: string
  description?: string
  version: number
  is_active: boolean
  is_system: boolean
  source_type: string
  definition: Record<string, any>
  triggers: ProcedureTrigger[]
  created_at: string
  updated_at: string
}

export interface ProcedureRunResponse {
  run_id?: string
  status: string
  message?: string
  results?: Record<string, any>
}

export interface ProcedureStep {
  name: string
  function: string
  params: Record<string, any>
  on_error?: string
  condition?: string
  description?: string
  foreach?: string
  branches?: Record<string, ProcedureStep[]>
}

export interface ProcedureParameter {
  name: string
  type?: string
  description?: string
  required?: boolean
  default?: any
  enum_values?: string[]
}

export interface CreateProcedureRequest {
  name: string
  slug: string
  description?: string
  parameters?: ProcedureParameter[]
  steps: ProcedureStep[]
  on_error?: string
  tags?: string[]
}

export interface UpdateProcedureRequest {
  is_active?: boolean
  description?: string
  name?: string
  parameters?: ProcedureParameter[]
  steps?: ProcedureStep[]
  on_error?: string
  tags?: string[]
}

export interface ValidationError {
  code: string
  message: string
  path: string
  details: Record<string, any>
}

export interface ValidationResult {
  valid: boolean
  errors: ValidationError[]
  warnings: ValidationError[]
  error_count: number
  warning_count: number
}

export interface ProcedureValidationError {
  message: string
  validation: ValidationResult
}

export interface GenerationProfile {
  name: string
  description: string
  allowed_categories: string[]
  blocked_tools: string[]
  allow_side_effects: boolean
  require_side_effect_confirmation: boolean
  max_search_limit: number
  max_llm_tokens: number
}

export interface PlanDiagnostics {
  profile_used: string
  tools_available: number
  tools_referenced: string[]
  plan_attempts: number
  procedure_attempts: number
  total_attempts: number
  validation_error_types: string[]
  clamps_applied: string[]
  timing_ms: number
}

export const proceduresApi = {
  async listProcedures(
    token?: string,
    params?: { is_active?: boolean; tag?: string }
  ): Promise<{ procedures: ProcedureListItem[]; total: number }> {
    const searchParams = new URLSearchParams()
    if (params?.is_active !== undefined) searchParams.append('is_active', String(params.is_active))
    if (params?.tag) searchParams.append('tag', params.tag)

    const res = await fetch(apiUrl(`/cwr/procedures/?${searchParams.toString()}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getProcedure(token: string | undefined, slug: string): Promise<Procedure> {
    const res = await fetch(apiUrl(`/cwr/procedures/${slug}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async runProcedure(
    token: string | undefined,
    slug: string,
    params: Record<string, any> = {},
    dryRun: boolean = false,
    asyncExecution: boolean = true
  ): Promise<ProcedureRunResponse> {
    const res = await fetch(apiUrl(`/cwr/procedures/${slug}/run`), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify({ params, dry_run: dryRun, async_execution: asyncExecution }),
    })
    return handleJson(res)
  },

  async enableProcedure(token: string | undefined, slug: string): Promise<{ status: string; message: string }> {
    const res = await fetch(apiUrl(`/cwr/procedures/${slug}/enable`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  async disableProcedure(token: string | undefined, slug: string): Promise<{ status: string; message: string }> {
    const res = await fetch(apiUrl(`/cwr/procedures/${slug}/disable`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  async listTriggers(token: string | undefined, slug: string): Promise<ProcedureTrigger[]> {
    const res = await fetch(apiUrl(`/cwr/procedures/${slug}/triggers`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async createTrigger(
    token: string | undefined,
    slug: string,
    data: {
      trigger_type: string
      cron_expression?: string
      event_name?: string
      event_filter?: Record<string, any>
      trigger_params?: Record<string, any>
    }
  ): Promise<ProcedureTrigger> {
    const res = await fetch(apiUrl(`/cwr/procedures/${slug}/triggers`), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async deleteTrigger(token: string | undefined, slug: string, triggerId: string): Promise<{ status: string; message: string }> {
    const res = await fetch(apiUrl(`/cwr/procedures/${slug}/triggers/${triggerId}`), {
      method: 'DELETE',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  async createProcedure(token: string | undefined, data: CreateProcedureRequest): Promise<Procedure> {
    const res = await fetch(apiUrl('/cwr/procedures/'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(data),
    })
    if (res.status === 422) {
      const errorData = await res.json()
      const error = new Error(errorData.detail?.message || 'Validation failed') as Error & { validation?: ValidationResult }
      error.validation = errorData.detail?.validation
      throw error
    }
    return handleJson(res)
  },

  async updateProcedure(token: string | undefined, slug: string, data: UpdateProcedureRequest): Promise<Procedure> {
    const res = await fetch(apiUrl(`/cwr/procedures/${slug}`), {
      method: 'PUT',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(data),
    })
    if (res.status === 422) {
      const errorData = await res.json()
      const error = new Error(errorData.detail?.message || 'Validation failed') as Error & { validation?: ValidationResult }
      error.validation = errorData.detail?.validation
      throw error
    }
    return handleJson(res)
  },

  async deleteProcedure(token: string | undefined, slug: string): Promise<{ status: string; slug: string }> {
    const res = await fetch(apiUrl(`/cwr/procedures/${slug}`), {
      method: 'DELETE',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  async validateProcedure(token: string | undefined, data: CreateProcedureRequest): Promise<ValidationResult> {
    const res = await fetch(apiUrl('/cwr/procedures/validate'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async reloadProcedures(token: string | undefined): Promise<{ status: string; message: string; procedures_loaded: number; slugs: string[] }> {
    const res = await fetch(apiUrl('/cwr/procedures/reload'), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  /**
   * Generate or refine a procedure using AI.
   *
   * @param token - Auth token
   * @param prompt - Description of procedure to create, or changes to make (in refine mode)
   * @param currentYaml - Optional current procedure YAML to refine. If provided, prompt describes changes.
   * @param includeExamples - Whether to include examples in AI context
   * @param profile - Generation profile: safe_readonly, workflow_standard, admin_full
   * @param currentPlan - Optional current Typed Plan JSON to refine
   */
  async generateProcedure(
    token: string | undefined,
    prompt: string,
    currentYaml?: string,
    includeExamples: boolean = true,
    profile?: string,
    currentPlan?: Record<string, any>
  ): Promise<{
    success: boolean
    yaml?: string
    procedure?: Record<string, any>
    plan_json?: Record<string, any>
    error?: string
    attempts: number
    validation_errors: ValidationError[]
    validation_warnings?: ValidationError[]
    profile_used?: string
    diagnostics?: PlanDiagnostics
  }> {
    const body: Record<string, any> = {
      prompt,
      include_examples: includeExamples,
    }
    if (currentYaml) {
      body.current_yaml = currentYaml
    }
    if (profile) {
      body.profile = profile
    }
    if (currentPlan) {
      body.current_plan = currentPlan
    }
    const res = await fetch(apiUrl('/cwr/procedures/generate'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(body),
    })
    return handleJson(res)
  },

  async getGenerationProfiles(token?: string): Promise<GenerationProfile[]> {
    const res = await fetch(apiUrl('/cwr/procedures/profiles'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async validateDraft(
    token: string | undefined,
    plan: Record<string, any>,
    profile?: string
  ): Promise<ValidationResult> {
    const body: Record<string, any> = { plan }
    if (profile) {
      body.profile = profile
    }
    const res = await fetch(apiUrl('/cwr/procedures/drafts/validate'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(body),
    })
    return handleJson(res)
  },
}

// =============================================================================
// PIPELINES API
// =============================================================================

export interface PipelineStage {
  name: string
  type: string
  function: string
  description?: string
  batch_size: number
  on_error: string
}

export interface PipelineTrigger {
  id?: string
  trigger_type: string
  cron_expression?: string
  event_name?: string
  event_filter?: Record<string, any>
  is_active: boolean
  last_triggered_at?: string
  next_trigger_at?: string
}

export interface PipelineListItem {
  id: string
  name: string
  slug: string
  description?: string
  version: number
  is_active: boolean
  is_system: boolean
  source_type: string
  stage_count: number
  trigger_count: number
  tags: string[]
  created_at: string
  updated_at: string
}

export interface Pipeline {
  id: string
  name: string
  slug: string
  description?: string
  version: number
  is_active: boolean
  is_system: boolean
  source_type: string
  stages: PipelineStage[]
  triggers: PipelineTrigger[]
  created_at: string
  updated_at: string
}

export interface PipelineRun {
  id: string
  pipeline_id: string
  run_id?: string
  status: string
  current_stage: number
  items_processed: number
  stage_results?: Record<string, any>
  error_message?: string
  started_at?: string
  completed_at?: string
  created_at: string
}

export interface PipelineItemState {
  id: string
  item_type: string
  item_id: string
  stage_name: string
  status: string
  stage_data?: Record<string, any>
  error_message?: string
  started_at?: string
  completed_at?: string
}

export interface PipelineRunResponse {
  run_id?: string
  pipeline_run_id?: string
  status: string
  message?: string
  results?: Record<string, any>
}

export const pipelinesApi = {
  async listPipelines(
    token?: string,
    params?: { is_active?: boolean; tag?: string }
  ): Promise<{ pipelines: PipelineListItem[]; total: number }> {
    const searchParams = new URLSearchParams()
    if (params?.is_active !== undefined) searchParams.append('is_active', String(params.is_active))
    if (params?.tag) searchParams.append('tag', params.tag)

    const res = await fetch(apiUrl(`/cwr/pipelines/?${searchParams.toString()}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getPipeline(token: string | undefined, slug: string): Promise<Pipeline> {
    const res = await fetch(apiUrl(`/cwr/pipelines/${slug}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async runPipeline(
    token: string | undefined,
    slug: string,
    params: Record<string, any> = {},
    dryRun: boolean = false,
    asyncExecution: boolean = true
  ): Promise<PipelineRunResponse> {
    const res = await fetch(apiUrl(`/cwr/pipelines/${slug}/run`), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify({ params, dry_run: dryRun, async_execution: asyncExecution }),
    })
    return handleJson(res)
  },

  async listRuns(
    token: string | undefined,
    slug: string,
    params?: { status?: string; limit?: number; offset?: number }
  ): Promise<{ runs: PipelineRun[]; total: number }> {
    const searchParams = new URLSearchParams()
    if (params?.status) searchParams.append('status', params.status)
    if (params?.limit) searchParams.append('limit', String(params.limit))
    if (params?.offset) searchParams.append('offset', String(params.offset))

    const res = await fetch(apiUrl(`/cwr/pipelines/${slug}/runs?${searchParams.toString()}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getRunItems(
    token: string | undefined,
    slug: string,
    runId: string,
    params?: { status?: string; stage?: string; limit?: number; offset?: number }
  ): Promise<{ items: PipelineItemState[]; total: number; by_status: Record<string, number> }> {
    const searchParams = new URLSearchParams()
    if (params?.status) searchParams.append('status', params.status)
    if (params?.stage) searchParams.append('stage', params.stage)
    if (params?.limit) searchParams.append('limit', String(params.limit))
    if (params?.offset) searchParams.append('offset', String(params.offset))

    const res = await fetch(apiUrl(`/cwr/pipelines/${slug}/runs/${runId}/items?${searchParams.toString()}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async resumeRun(
    token: string | undefined,
    slug: string,
    runId: string,
    fromStage?: number
  ): Promise<PipelineRunResponse> {
    const res = await fetch(apiUrl(`/cwr/pipelines/${slug}/runs/${runId}/resume`), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify({ from_stage: fromStage }),
    })
    return handleJson(res)
  },

  async enablePipeline(token: string | undefined, slug: string): Promise<{ status: string; message: string }> {
    const res = await fetch(apiUrl(`/cwr/pipelines/${slug}/enable`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  async disablePipeline(token: string | undefined, slug: string): Promise<{ status: string; message: string }> {
    const res = await fetch(apiUrl(`/cwr/pipelines/${slug}/disable`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  async listTriggers(token: string | undefined, slug: string): Promise<PipelineTrigger[]> {
    const res = await fetch(apiUrl(`/cwr/pipelines/${slug}/triggers`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async createTrigger(
    token: string | undefined,
    slug: string,
    data: {
      trigger_type: string
      cron_expression?: string
      event_name?: string
      event_filter?: Record<string, any>
      trigger_params?: Record<string, any>
    }
  ): Promise<PipelineTrigger> {
    const res = await fetch(apiUrl(`/cwr/pipelines/${slug}/triggers`), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async deleteTrigger(token: string | undefined, slug: string, triggerId: string): Promise<{ status: string; message: string }> {
    const res = await fetch(apiUrl(`/cwr/pipelines/${slug}/triggers/${triggerId}`), {
      method: 'DELETE',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },
}

// ============================================================================
// SALESFORCE CRM API
// ============================================================================

export interface SalesforceStats {
  accounts: {
    total: number
    by_type: Array<{ type: string; count: number }>
  }
  contacts: {
    total: number
  }
  opportunities: {
    total: number
    total_value: number
    open: number
    open_value: number
    won: number
    won_value: number
    by_stage: Array<{ stage: string; count: number; value: number }>
  }
}

export interface SalesforceAccount {
  id: string
  salesforce_id: string
  name: string
  parent_salesforce_id: string | null
  account_type: string | null
  industry: string | null
  department: string | null
  description: string | null
  website: string | null
  phone: string | null
  billing_address: Record<string, any> | null
  shipping_address: Record<string, any> | null
  small_business_flags: Record<string, any> | null
  indexed_at: string | null
  created_at: string
  updated_at: string
  contact_count?: number
  opportunity_count?: number
}

export interface SalesforceContact {
  id: string
  salesforce_id: string
  account_id: string | null
  account_salesforce_id: string | null
  first_name: string | null
  last_name: string
  email: string | null
  title: string | null
  phone: string | null
  mobile_phone: string | null
  department: string | null
  is_current_employee: boolean | null
  mailing_address: Record<string, any> | null
  created_at: string
  updated_at: string
  account_name?: string
}

export interface SalesforceOpportunity {
  id: string
  salesforce_id: string
  account_id: string | null
  account_salesforce_id: string | null
  name: string
  stage_name: string | null
  amount: number | null
  probability: number | null
  close_date: string | null
  is_closed: boolean | null
  is_won: boolean | null
  opportunity_type: string | null
  role: string | null
  lead_source: string | null
  fiscal_year: string | null
  fiscal_quarter: string | null
  description: string | null
  custom_dates: Record<string, any> | null
  linked_sharepoint_folder_id: string | null
  linked_sam_solicitation_id: string | null
  indexed_at: string | null
  created_at: string
  updated_at: string
  account_name?: string
}

export interface SalesforceAccountListResponse {
  items: SalesforceAccount[]
  total: number
  limit: number
  offset: number
}

export interface SalesforceContactListResponse {
  items: SalesforceContact[]
  total: number
  limit: number
  offset: number
}

export interface SalesforceOpportunityListResponse {
  items: SalesforceOpportunity[]
  total: number
  limit: number
  offset: number
}

export interface FilterOptionsResponse {
  options: string[]
}

export const salesforceApi = {
  // ========== Import ==========

  async importData(token: string | undefined, file: File): Promise<{ run_id: string; status: string; message: string }> {
    const formData = new FormData()
    formData.append('file', file)

    const res = await fetch(apiUrl('/data/salesforce/import'), {
      method: 'POST',
      headers: authHeaders(token),
      body: formData,
    })
    return handleJson(res)
  },

  // ========== Statistics ==========

  async getStats(token: string | undefined): Promise<SalesforceStats> {
    const res = await fetch(apiUrl('/data/salesforce/stats'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  // ========== Accounts ==========

  async listAccounts(
    token: string | undefined,
    params?: {
      account_type?: string
      industry?: string
      keyword?: string
      limit?: number
      offset?: number
    }
  ): Promise<SalesforceAccountListResponse> {
    const searchParams = new URLSearchParams()
    if (params?.account_type) searchParams.append('account_type', params.account_type)
    if (params?.industry) searchParams.append('industry', params.industry)
    if (params?.keyword) searchParams.append('keyword', params.keyword)
    if (params?.limit) searchParams.append('limit', params.limit.toString())
    if (params?.offset) searchParams.append('offset', params.offset.toString())

    const url = apiUrl(`/data/salesforce/accounts?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getAccount(token: string | undefined, accountId: string): Promise<SalesforceAccount> {
    const res = await fetch(apiUrl(`/data/salesforce/accounts/${accountId}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getAccountContacts(
    token: string | undefined,
    accountId: string,
    params?: { limit?: number; offset?: number }
  ): Promise<SalesforceContactListResponse> {
    const searchParams = new URLSearchParams()
    if (params?.limit) searchParams.append('limit', params.limit.toString())
    if (params?.offset) searchParams.append('offset', params.offset.toString())

    const url = apiUrl(`/data/salesforce/accounts/${accountId}/contacts?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getAccountOpportunities(
    token: string | undefined,
    accountId: string,
    params?: { limit?: number; offset?: number }
  ): Promise<SalesforceOpportunityListResponse> {
    const searchParams = new URLSearchParams()
    if (params?.limit) searchParams.append('limit', params.limit.toString())
    if (params?.offset) searchParams.append('offset', params.offset.toString())

    const url = apiUrl(`/data/salesforce/accounts/${accountId}/opportunities?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  // ========== Contacts ==========

  async listContacts(
    token: string | undefined,
    params?: {
      account_id?: string
      keyword?: string
      current_only?: boolean
      limit?: number
      offset?: number
    }
  ): Promise<SalesforceContactListResponse> {
    const searchParams = new URLSearchParams()
    if (params?.account_id) searchParams.append('account_id', params.account_id)
    if (params?.keyword) searchParams.append('keyword', params.keyword)
    if (params?.current_only !== undefined) searchParams.append('current_only', String(params.current_only))
    if (params?.limit) searchParams.append('limit', params.limit.toString())
    if (params?.offset) searchParams.append('offset', params.offset.toString())

    const url = apiUrl(`/data/salesforce/contacts?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getContact(token: string | undefined, contactId: string): Promise<SalesforceContact> {
    const res = await fetch(apiUrl(`/data/salesforce/contacts/${contactId}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  // ========== Opportunities ==========

  async listOpportunities(
    token: string | undefined,
    params?: {
      account_id?: string
      stage_name?: string
      opportunity_type?: string
      is_open?: boolean
      keyword?: string
      limit?: number
      offset?: number
    }
  ): Promise<SalesforceOpportunityListResponse> {
    const searchParams = new URLSearchParams()
    if (params?.account_id) searchParams.append('account_id', params.account_id)
    if (params?.stage_name) searchParams.append('stage_name', params.stage_name)
    if (params?.opportunity_type) searchParams.append('opportunity_type', params.opportunity_type)
    if (params?.is_open !== undefined) searchParams.append('is_open', String(params.is_open))
    if (params?.keyword) searchParams.append('keyword', params.keyword)
    if (params?.limit) searchParams.append('limit', params.limit.toString())
    if (params?.offset) searchParams.append('offset', params.offset.toString())

    const url = apiUrl(`/data/salesforce/opportunities?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getOpportunity(token: string | undefined, opportunityId: string): Promise<SalesforceOpportunity> {
    const res = await fetch(apiUrl(`/data/salesforce/opportunities/${opportunityId}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  // ========== Filter Options ==========

  async getAccountTypes(token: string | undefined): Promise<FilterOptionsResponse> {
    const res = await fetch(apiUrl('/data/salesforce/filters/account-types'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getIndustries(token: string | undefined): Promise<FilterOptionsResponse> {
    const res = await fetch(apiUrl('/data/salesforce/filters/industries'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getStages(token: string | undefined): Promise<FilterOptionsResponse> {
    const res = await fetch(apiUrl('/data/salesforce/filters/stages'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getOpportunityTypes(token: string | undefined): Promise<FilterOptionsResponse> {
    const res = await fetch(apiUrl('/data/salesforce/filters/opportunity-types'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },
}

// ============================================================================
// FORECAST SYNC API (Acquisition Forecasts)
// ============================================================================

export interface ForecastSync {
  id: string
  organization_id: string
  name: string
  slug: string
  source_type: 'ag' | 'apfs' | 'state'
  status: 'active' | 'paused' | 'archived'
  is_active: boolean
  sync_frequency: 'manual' | 'hourly' | 'daily'
  filter_config: Record<string, any>
  automation_config: Record<string, any>
  last_sync_at: string | null
  last_sync_status: string | null
  last_sync_run_id: string | null
  forecast_count: number
  created_at: string
  updated_at: string
  is_syncing: boolean
  current_sync_status: string | null
}

export interface ForecastSyncListResponse {
  items: ForecastSync[]
  total: number
  limit: number
  offset: number
}

export interface ForecastSyncCreateRequest {
  name: string
  source_type: 'ag' | 'apfs' | 'state'
  filter_config?: Record<string, any>
  sync_frequency?: 'manual' | 'hourly' | 'daily'
  automation_config?: Record<string, any>
}

export interface ForecastSyncUpdateRequest {
  name?: string
  filter_config?: Record<string, any>
  status?: 'active' | 'paused' | 'archived'
  is_active?: boolean
  sync_frequency?: 'manual' | 'hourly' | 'daily'
  automation_config?: Record<string, any>
}

export interface Forecast {
  id: string
  organization_id: string
  sync_id: string
  source_type: 'ag' | 'apfs' | 'state'
  source_id: string
  title: string
  description: string | null
  agency_name: string | null
  naics_codes: Array<{ code?: string; description?: string }> | null
  acquisition_phase: string | null
  set_aside_type: string | null
  contract_type: string | null
  contract_vehicle: string | null
  estimated_solicitation_date: string | null
  fiscal_year: number | null
  estimated_award_quarter: string | null
  pop_start_date: string | null
  pop_end_date: string | null
  pop_city: string | null
  pop_state: string | null
  pop_country: string | null
  poc_name: string | null
  poc_email: string | null
  sbs_name: string | null
  sbs_email: string | null
  incumbent_contractor: string | null
  source_url: string | null
  first_seen_at: string
  last_updated_at: string
  indexed_at: string | null
  created_at: string
  updated_at: string
}

export interface ForecastListResponse {
  items: Forecast[]
  total: number
  limit: number
  offset: number
}

export interface ForecastStatsResponse {
  total_syncs: number
  active_syncs: number
  total_forecasts: number
  by_source: Record<string, number>
  recent_changes: number
  last_sync_at: string | null
}

export const forecastsApi = {
  // Sync configuration
  async listSyncs(
    token: string | undefined,
    params?: {
      status?: string
      source_type?: string
      limit?: number
      offset?: number
    }
  ): Promise<ForecastSyncListResponse> {
    const queryParams = new URLSearchParams()
    if (params?.status) queryParams.set('status', params.status)
    if (params?.source_type) queryParams.set('source_type', params.source_type)
    if (params?.limit) queryParams.set('limit', params.limit.toString())
    if (params?.offset) queryParams.set('offset', params.offset.toString())

    const url = queryParams.toString()
      ? `/data/forecasts/syncs?${queryParams.toString()}`
      : '/data/forecasts/syncs'
    const res = await fetch(apiUrl(url), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async createSync(
    token: string | undefined,
    data: ForecastSyncCreateRequest
  ): Promise<ForecastSync> {
    const res = await fetch(apiUrl('/data/forecasts/syncs'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async getSync(token: string | undefined, syncId: string): Promise<ForecastSync> {
    const res = await fetch(apiUrl(`/data/forecasts/syncs/${syncId}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async updateSync(
    token: string | undefined,
    syncId: string,
    data: ForecastSyncUpdateRequest
  ): Promise<ForecastSync> {
    const res = await fetch(apiUrl(`/data/forecasts/syncs/${syncId}`), {
      method: 'PATCH',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async deleteSync(token: string | undefined, syncId: string): Promise<void> {
    const res = await fetch(apiUrl(`/data/forecasts/syncs/${syncId}`), {
      method: 'DELETE',
      headers: authHeaders(token),
    })
    if (!res.ok) {
      const error = await res.json().catch(() => ({}))
      throw new Error(error.detail || 'Failed to delete sync')
    }
  },

  async triggerSyncPull(
    token: string | undefined,
    syncId: string
  ): Promise<{ run_id: string; sync_id: string; status: string; message: string }> {
    const res = await fetch(apiUrl(`/data/forecasts/syncs/${syncId}/pull`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  async clearSyncForecasts(
    token: string | undefined,
    syncId: string
  ): Promise<{ sync_id: string; deleted_count: number; message: string }> {
    const res = await fetch(apiUrl(`/data/forecasts/syncs/${syncId}/clear`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  // Forecasts (unified view)
  async listForecasts(
    token: string | undefined,
    params?: {
      source_type?: string
      sync_id?: string
      agency_name?: string
      naics_code?: string
      fiscal_year?: number
      search?: string
      sort_by?: string
      sort_direction?: 'asc' | 'desc'
      limit?: number
      offset?: number
    }
  ): Promise<ForecastListResponse> {
    const queryParams = new URLSearchParams()
    if (params?.source_type) queryParams.set('source_type', params.source_type)
    if (params?.sync_id) queryParams.set('sync_id', params.sync_id)
    if (params?.agency_name) queryParams.set('agency_name', params.agency_name)
    if (params?.naics_code) queryParams.set('naics_code', params.naics_code)
    if (params?.fiscal_year) queryParams.set('fiscal_year', params.fiscal_year.toString())
    if (params?.search) queryParams.set('search', params.search)
    if (params?.sort_by) queryParams.set('sort_by', params.sort_by)
    if (params?.sort_direction) queryParams.set('sort_direction', params.sort_direction)
    if (params?.limit) queryParams.set('limit', params.limit.toString())
    if (params?.offset) queryParams.set('offset', params.offset.toString())

    const url = queryParams.toString()
      ? `/data/forecasts?${queryParams.toString()}`
      : '/data/forecasts'
    const res = await fetch(apiUrl(url), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getForecastById(
    token: string | undefined,
    forecastId: string
  ): Promise<Forecast> {
    const res = await fetch(apiUrl(`/data/forecasts/${forecastId}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getStats(token: string | undefined): Promise<ForecastStatsResponse> {
    const res = await fetch(apiUrl('/data/forecasts/stats'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },
}

// -------------------- Metrics API --------------------
export const metricsApi = {
  async getProcedureMetrics(token?: string, days: number = 7): Promise<{
    period_days: number
    total_runs: number
    avg_duration_ms: number
    success_rate: number
    by_function: Record<string, { calls: number; avg_ms: number; errors: number }>
  }> {
    const url = new URL(apiUrl('/ops/metrics/procedures'))
    url.searchParams.set('days', String(days))
    const res = await fetch(url.toString(), {
      headers: authHeaders(token),
      cache: 'no-store',
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
  authApi,
  connectionsApi,
  organizationsApi,
  settingsApi,
  objectStorageApi,
  usersApi,
  assetsApi,
  runsApi,
  scrapeApi,
  scheduledTasksApi,
  searchApi,
  samApi,
  salesforceApi,
  forecastsApi,
  sharepointSyncApi,
  functionsApi,
  contractsApi,
  proceduresApi,
  pipelinesApi,
  metadataApi,
  metricsApi,
  utils,
}
