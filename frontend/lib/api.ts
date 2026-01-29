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
    const res = await fetch(apiUrl('/health'), { cache: 'no-store', headers: authHeaders() })
    return handleJson(res)
  },

  async checkAvailability(): Promise<boolean> {
    try {
      const res = await fetch(apiUrl('/health'), { cache: 'no-store' })
      return res.ok || res.status === 401 || res.status === 403
    } catch {
      return false
    }
  },

  async getSupportedFormats(): Promise<{ supported_extensions: string[]; max_file_size: number }> {
    const res = await fetch(apiUrl('/config/supported-formats'), { cache: 'no-store', headers: authHeaders() })
    return handleJson(res)
  },

  async getConfig(): Promise<{
    ocr_settings: { language: string; psm: number }
  }> {
    const res = await fetch(apiUrl('/config/defaults'), { cache: 'no-store', headers: authHeaders() })
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
    const res = await fetch(apiUrl('/config/extraction-engines'), { cache: 'no-store', headers: authHeaders() })
    return handleJson(res)
  },

  async getLLMStatus(): Promise<LLMConnectionStatus> {
    const res = await fetch(apiUrl('/llm/status'), { cache: 'no-store', headers: authHeaders() })
    return handleJson(res)
  },

  async resetSystem(): Promise<{ success: boolean; message?: string }> {
    const res = await fetch(apiUrl('/system/reset'), { method: 'POST', headers: authHeaders() })
    return handleJson(res)
  },

  async getQueueHealth(): Promise<{ pending: number; running: number; processed: number; total: number } & Record<string, any>> {
    const res = await fetch(apiUrl('/system/queues'), { cache: 'no-store', headers: authHeaders() })
    return handleJson(res)
  },

  async getQueueSummaryByJobs(jobIds: string[]): Promise<{ queued: number; running: number; done: number; total: number } & Record<string, any>> {
    const url = new URL(apiUrl('/system/queues/summary'))
    url.searchParams.set('job_ids', jobIds.join(','))
    const res = await fetch(url.toString(), { cache: 'no-store', headers: authHeaders() })
    return handleJson(res)
  },

  async getQueueSummaryByBatch(batchId: string): Promise<{ queued: number; running: number; done: number; total: number } & Record<string, any>> {
    const url = new URL(apiUrl('/system/queues/summary'))
    url.searchParams.set('batch_id', batchId)
    const res = await fetch(url.toString(), { cache: 'no-store', headers: authHeaders() })
    return handleJson(res)
  },

  async getComprehensiveHealth(): Promise<any> {
    const res = await fetch(apiUrl('/system/health/comprehensive'), { cache: 'no-store', headers: authHeaders() })
    return handleJson(res)
  },

  async getComponentHealth(component: 'backend' | 'database' | 'redis' | 'celery' | 'extraction' | 'docling' | 'llm' | 'sharepoint'): Promise<any> {
    const res = await fetch(apiUrl(`/system/health/${component}`), { cache: 'no-store', headers: authHeaders() })
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

    // Fall back to filesystem-based endpoint
    const res = await fetch(apiUrl('/documents/uploaded'), { cache: 'no-store', headers: authHeaders() })
    return handleJson(res)
  },

  async listBatchFiles(): Promise<{ files: FileInfo[]; count: number }> {
    // Check if object storage is enabled
    const useObjectStorage = await objectStorageApi.isEnabled()

    if (useObjectStorage) {
      // With object storage, "batch files" don't really exist as a separate concept
      // Return empty list for now (batch processing would use uploaded files)
      return { files: [], count: 0 }
    }

    // Fall back to filesystem-based endpoint
    const res = await fetch(apiUrl('/documents/batch'), { cache: 'no-store', headers: authHeaders() })
    return handleJson(res)
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

    // Fall back to traditional upload (through backend)
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(apiUrl('/documents/upload'), { method: 'POST', body: form, headers: authHeaders() })
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

    // Check if object storage is enabled
    const useObjectStorage = await objectStorageApi.isEnabled()

    if (useObjectStorage) {
      // Use presigned URL flow (direct from storage)
      try {
        return await objectStorageApi.downloadFile(documentId, artifactType)
      } catch (e) {
        // If object storage download fails (e.g., file not in storage), fall back
        console.warn('Object storage download failed, falling back to backend:', e)
      }
    }

    // Fall back to traditional download (through backend)
    // Use path parameter with validated document ID
    let url = apiUrl(`/documents/${encodedDocId}/download`)
    if (jobId) {
      url += `?job_id=${encodeURIComponent(jobId)}`
    }
    const res = await fetch(url, { headers: authHeaders() })
    return handleBlob(res)
  },

  async deleteDocument(documentId: string): Promise<{ success: boolean; message?: string }> {
    const encodedDocId = validateAndEncodeDocumentId(documentId)
    const res = await fetch(apiUrl(`/documents/${encodedDocId}`), { method: 'DELETE', headers: authHeaders() })
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
      headers: { ...jsonHeaders, ...authHeaders() },
      body: JSON.stringify(body),
    })
    return handleBlob(res)
  },

  async downloadRAGReadyDocuments(zipName?: string): Promise<Blob> {
    const url = new URL(apiUrl('/documents/download/rag-ready'))
    if (zipName) url.searchParams.set('zip_name', zipName)
    url.searchParams.set('include_summary', 'true')
    const res = await fetch(url.toString(), { headers: authHeaders() })
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
    const job = await jobsApi.createJob(undefined, {
      document_ids: [documentId],
      options: payload,
      name: `Document ${documentId}`,
      description: 'Single document processing (job framework)',
      start_immediately: true,
    })

    return {
      job_id: job.id,
      document_id: documentId,
      status: job.status,
      enqueued_at: job.queued_at || job.created_at,
    }
  },

  async processBatch(request: { document_ids: string[]; options?: any }): Promise<{ job_id: string; document_ids: string[]; status: string }>
  {
    const payload = request.options ? mapOptionsToV1(request.options) : undefined
    const job = await jobsApi.createJob(undefined, {
      document_ids: request.document_ids,
      options: payload,
      name: `Batch job (${request.document_ids.length} documents)`,
      description: 'Batch processing (job framework)',
      start_immediately: true,
    })

    return {
      job_id: job.id,
      document_ids: request.document_ids,
      status: job.status,
    }
  },

  async getProcessingResult(documentId: string): Promise<ProcessingResult> {
    const encodedDocId = validateAndEncodeDocumentId(documentId)
    const res = await fetch(apiUrl(`/documents/${encodedDocId}/result`), { cache: 'no-store', headers: authHeaders() })
    const raw = await handleJson<any>(res)
    return mapV1ResultToFrontend(raw)
  },

  async processDocument(
    documentId: string,
    options: { auto_optimize?: boolean; quality_thresholds?: any },
  ): Promise<ProcessingResult> {
    await processingApi.enqueueDocument(documentId, options)
    const raw = await processingApi.getProcessingResult(documentId)
    return raw
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
    const res = await fetch(apiUrl('/organizations/me'), {
      cache: 'no-store',
      headers: authHeaders(token)
    })
    return handleJson(res)
  },
}

// -------------------- Content API --------------------
export const contentApi = {
  /**
   * Get document content for viewing/editing.
   *
   * @param documentId - Document ID to retrieve
   * @param token - Optional auth token
   * @param jobId - Optional job ID to retrieve job-specific processed content
   */
  async getDocumentContent(documentId: string, token?: string, jobId?: string): Promise<{ content: string }> {
    // Validate and encode document ID
    const encodedDocId = validateAndEncodeDocumentId(documentId)

    // Use path parameter with validated document ID
    let url = apiUrl(`/documents/${encodedDocId}/content`)
    if (jobId) {
      url += `?job_id=${encodeURIComponent(jobId)}`
    }
    const res = await fetch(url, {
      cache: 'no-store',
      headers: authHeaders(token)
    })
    return handleJson(res)
  },

  async updateDocumentContent(
    documentId: string,
    content: string,
    token?: string,
  ): Promise<{ job_id: string; document_id: string; status: string; enqueued_at?: string }> {
    const encodedDocId = validateAndEncodeDocumentId(documentId)
    const res = await fetch(apiUrl(`/documents/${encodedDocId}/content`), {
      method: 'PUT',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify({ content }),
    })
    if (!res.ok) {
      let body: any = undefined
      try { body = await res.json() } catch {}
      const msg = (body && (body.detail || body.message)) || res.statusText
      // Preserve 409 status for conflict handling
      if (res.status === 409) {
        const err: any = new Error(msg)
        err.status = 409
        err.detail = body
        throw err
      }
      httpError(res, msg, body)
    }
    return res.json()
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

// -------------------- Jobs API --------------------
export const jobsApi = {
  /**
   * Create a new batch job for processing multiple documents
   */
  async createJob(token: string | undefined, data: {
    document_ids: string[]
    options?: Record<string, any>
    name?: string
    description?: string
    start_immediately?: boolean
  }): Promise<{
    id: string
    organization_id: string
    user_id?: string
    name: string
    status: string
    total_documents: number
    created_at: string
    queued_at?: string
  }> {
    const res = await fetch(apiUrl('/jobs'), {
      method: 'POST',
      headers: { ...jsonHeaders, ...authHeaders(token) },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  /**
   * Start a pending job
   */
  async startJob(token: string | undefined, jobId: string): Promise<{
    id: string
    status: string
    queued_at?: string
  }> {
    const res = await fetch(apiUrl(`/jobs/${encodeURIComponent(jobId)}/start`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  /**
   * Cancel a running job
   */
  async cancelJob(token: string | undefined, jobId: string): Promise<{
    job_id: string
    status: string
    tasks_revoked: number
    tasks_verified_stopped: number
    verification_timeout: boolean
    cancelled_at?: string
    message?: string
  }> {
    const res = await fetch(apiUrl(`/jobs/${encodeURIComponent(jobId)}/cancel`), {
      method: 'POST',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  /**
   * List jobs with pagination and filtering
   */
  async listJobs(token: string | undefined, params?: {
    status?: string
    page?: number
    page_size?: number
  }): Promise<{
    jobs: Array<{
      id: string
      name: string
      status: string
      total_documents: number
      completed_documents: number
      failed_documents: number
      created_at: string
      started_at?: string
      completed_at?: string
    }>
    total: number
    page: number
    page_size: number
    total_pages: number
  }> {
    const url = new URL(apiUrl('/jobs'))
    if (params?.status) url.searchParams.set('status', params.status)
    if (params?.page) url.searchParams.set('page', params.page.toString())
    if (params?.page_size) url.searchParams.set('page_size', params.page_size.toString())

    const res = await fetch(url.toString(), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  /**
   * Get detailed job information
   */
  async getJob(token: string | undefined, jobId: string): Promise<{
    id: string
    name: string
    status: string
    total_documents: number
    completed_documents: number
    failed_documents: number
    created_at: string
    queued_at?: string
    started_at?: string
    completed_at?: string
    documents: Array<{
      id: string
      document_id: string
      filename: string
      status: string
      conversion_score?: number
      error_message?: string
      started_at?: string
    }>
    recent_logs: Array<{
      id: string
      timestamp: string
      level: string
      message: string
    }>
    processing_options: Record<string, any>
    results_summary?: Record<string, any>
  }> {
    const res = await fetch(apiUrl(`/jobs/${encodeURIComponent(jobId)}`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  /**
   * Get job logs with pagination
   */
  async getJobLogs(token: string | undefined, jobId: string, params?: {
    page?: number
    page_size?: number
  }): Promise<Array<{
    id: string
    timestamp: string
    level: string
    message: string
    metadata?: Record<string, any>
  }>> {
    const url = new URL(apiUrl(`/jobs/${encodeURIComponent(jobId)}/logs`))
    if (params?.page) url.searchParams.set('page', params.page.toString())
    if (params?.page_size) url.searchParams.set('page_size', params.page_size.toString())

    const res = await fetch(url.toString(), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  /**
   * Get job documents with their processing status
   */
  async getJobDocuments(token: string | undefined, jobId: string): Promise<Array<{
    id: string
    document_id: string
    filename: string
    status: string
    conversion_score?: number
    quality_scores?: Record<string, any>
    is_rag_ready?: boolean
    error_message?: string
    processing_time_seconds?: number
  }>> {
    const res = await fetch(apiUrl(`/jobs/${encodeURIComponent(jobId)}/documents`), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  /**
   * Delete a job (admin only, terminal states only)
   */
  async deleteJob(token: string | undefined, jobId: string): Promise<void> {
    const res = await fetch(apiUrl(`/jobs/${encodeURIComponent(jobId)}`), {
      method: 'DELETE',
      headers: authHeaders(token),
    })
    if (!res.ok) {
      let body: any = undefined
      try { body = await res.json() } catch {}
      const msg = (body && (body.detail || body.message)) || res.statusText
      httpError(res, msg, body)
    }
  },

  /**
   * Get user's job statistics
   */
  async getUserStats(token: string | undefined): Promise<{
    active_jobs: number
    total_jobs_24h: number
    total_jobs_7d: number
    completed_jobs_24h: number
    failed_jobs_24h: number
  }> {
    const res = await fetch(apiUrl('/jobs/stats/user'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  /**
   * Get organization job statistics (admin only)
   */
  async getOrgStats(token: string | undefined): Promise<{
    organization_id: string
    active_jobs: number
    queued_jobs: number
    concurrency_limit: number
    total_jobs: number
    completed_jobs: number
    failed_jobs: number
    cancelled_jobs: number
    total_documents_processed: number
  }> {
    const res = await fetch(apiUrl('/jobs/stats/organization'), {
      headers: authHeaders(token),
      cache: 'no-store',
    })
    return handleJson(res)
  },

  // Legacy endpoints (backward compatibility)
  async getJobByDocument(documentId: string, token?: string): Promise<any> {
    const encodedDocId = validateAndEncodeDocumentId(documentId)
    const res = await fetch(apiUrl(`/jobs/by-document/${encodedDocId}`), {
      cache: 'no-store',
      headers: authHeaders(token)
    })
    if (!res.ok && res.status === 404) {
      // Document may not have an associated job
      return null
    }
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

  async extendSession(token: string): Promise<{
    access_token: string
    refresh_token: string
    token_type: string
  }> {
    const res = await fetch(apiUrl('/auth/extend-session'), {
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
    error?: string
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
    const res = await fetch(apiUrl('/connections/test-credentials'), {
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
    const res = await fetch(apiUrl('/organizations/me/settings'), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async updateOrganizationSettings(token: string, settings: Record<string, any>): Promise<{
    settings: Record<string, any>
  }> {
    const res = await fetch(apiUrl('/organizations/me/settings'), {
      method: 'PUT',
      headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
      body: JSON.stringify({ settings }),
    })
    return handleJson(res)
  },

  async getUserSettings(token: string): Promise<{
    settings: Record<string, any>
  }> {
    const res = await fetch(apiUrl('/users/me/settings'), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async updateUserSettings(token: string, settings: Record<string, any>): Promise<{
    settings: Record<string, any>
  }> {
    const res = await fetch(apiUrl('/users/me/settings'), {
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

// -------------------- Storage API (Filesystem) --------------------
// These methods handle filesystem-based storage operations
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

// -------------------- Object Storage API --------------------
// Direct access to S3/MinIO object storage via presigned URLs
export const objectStorageApi = {
  /**
   * Check if object storage is enabled
   */
  async isEnabled(): Promise<boolean> {
    try {
      const res = await fetch(apiUrl('/storage/health'), {
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
    const res = await fetch(apiUrl('/storage/health'), {
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

    const res = await fetch(apiUrl('/storage/upload/proxy'), {
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
   * Download a file proxied through backend (bypasses CORS)
   */
  async downloadFile(
    documentId: string,
    artifactType: 'uploaded' | 'processed' = 'processed'
  ): Promise<Blob> {
    const token = getAccessToken()
    if (!token) throw new Error('Authentication required')

    // Validate and encode document ID
    const encodedDocId = validateAndEncodeDocumentId(documentId)

    // Use proxy endpoint to bypass CORS issues with MinIO
    const url = new URL(apiUrl(`/storage/download/${encodedDocId}/proxy`))
    url.searchParams.set('artifact_type', artifactType)

    const res = await fetch(url.toString(), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })

    if (!res.ok) {
      const error = await res.text()
      throw new Error(`Download failed: ${error || res.statusText}`)
    }

    return res.blob()
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
    const res = await fetch(apiUrl(`/storage/artifacts/document/${encodedDocId}`), {
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
    const res = await fetch(apiUrl(`/storage/artifacts/${encodeURIComponent(artifactId)}`), {
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
    const res = await fetch(apiUrl(`/storage/artifacts/${encodeURIComponent(artifactId)}`), {
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
    const url = new URL(apiUrl('/storage/artifacts'))
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
    const res = await fetch(apiUrl('/storage/artifacts/bulk-delete'), {
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
    const res = await fetch(apiUrl('/storage/browse'), {
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
    }>
    is_protected: boolean
    parent_path: string | null
  }> {
    const url = new URL(apiUrl(`/storage/browse/${encodeURIComponent(bucket)}`))
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
    const res = await fetch(apiUrl('/storage/buckets/protected'), {
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
    const res = await fetch(apiUrl('/storage/folders'), {
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

    const res = await fetch(apiUrl('/storage/folders/upload'), {
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
    const url = new URL(apiUrl(`/storage/folders/${encodeURIComponent(bucket)}/${path}`))
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
    const res = await fetch(apiUrl(`/storage/files/${encodeURIComponent(bucket)}/${key}`), {
      method: 'DELETE',
      headers: authHeaders(token),
    })
    return handleJson(res)
  },

  /**
   * Download object proxied through backend (no presigned URLs needed)
   */
  async downloadObject(
    bucket: string,
    key: string,
    inline: boolean = false,
    token?: string
  ): Promise<Blob> {
    const url = new URL(apiUrl('/storage/object/download'))
    url.searchParams.set('bucket', bucket)
    url.searchParams.set('key', key)
    url.searchParams.set('inline', String(inline))

    const res = await fetch(url.toString(), {
      headers: authHeaders(token),
    })

    if (!res.ok) {
      throw new Error(`Download failed: ${res.statusText}`)
    }

    return await res.blob()
  },

  /**
   * Get presigned URL for any object (DEPRECATED - use downloadObject instead)
   * @deprecated Use downloadObject() for backend-proxied downloads
   */
  async getObjectPresignedUrl(
    bucket: string,
    key: string,
    inline: boolean = false,
    filename?: string,
    token?: string
  ): Promise<{
    download_url: string
    bucket: string
    key: string
    filename: string
    size: number | null
    content_type: string | null
    expires_in: number
  }> {
    const url = new URL(apiUrl('/storage/object/presigned'))
    url.searchParams.set('bucket', bucket)
    url.searchParams.set('key', key)
    url.searchParams.set('inline', String(inline))
    if (filename) {
      url.searchParams.set('filename', filename)
    }
    const res = await fetch(url.toString(), {
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
    const res = await fetch(apiUrl('/storage/files/move'), {
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
    const res = await fetch(apiUrl('/storage/files/rename'), {
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
    const res = await fetch(apiUrl('/organizations/me/users'), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    })
    return handleJson(res)
  },

  async getUser(token: string, userId: string): Promise<any> {
    const res = await fetch(apiUrl(`/organizations/me/users/${userId}`), {
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
    const res = await fetch(apiUrl('/organizations/me/users'), {
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
    const res = await fetch(apiUrl(`/organizations/me/users/${userId}`), {
      method: 'PUT',
      headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
      body: JSON.stringify(data),
    })
    return handleJson(res)
  },

  async deleteUser(token: string, userId: string): Promise<{
    message: string
  }> {
    const res = await fetch(apiUrl(`/organizations/me/users/${userId}`), {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    })
    return handleJson(res)
  },

  async changePassword(token: string, userId: string, newPassword: string): Promise<{
    message: string
  }> {
    const res = await fetch(apiUrl(`/organizations/me/users/${userId}/password`), {
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
}

export interface ExtractionResult {
  id: string
  asset_id: string
  run_id: string
  extractor_version: string
  status: string
  extracted_bucket: string | null
  extracted_object_key: string | null
  structure_metadata: Record<string, any> | null
  warnings: string[]
  errors: string[]
  extraction_time_seconds: number | null
  created_at: string
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
  created_by: string | null
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
  experimental: AssetMetadata[]
  total_canonical: number
  total_experimental: number
  metadata_types: string[]
}

export interface AssetMetadataCreateRequest {
  metadata_type: string
  metadata_content: Record<string, any>
  schema_version?: string
  is_canonical?: boolean
  producer_run_id?: string
}

export interface AssetMetadataPromoteResponse {
  promoted: AssetMetadata
  superseded: AssetMetadata | null
  message: string
}

export interface AssetMetadataCompareResponse {
  metadata_a: AssetMetadata
  metadata_b: AssetMetadata
  differences: {
    metadata_type: { a: string; b: string; same: boolean }
    is_canonical: { a: boolean; b: boolean }
    keys_only_in_a: string[]
    keys_only_in_b: string[]
    keys_in_both: string[]
    values_differ: string[]
  }
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

    const url = apiUrl(`/assets?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get asset by ID
   */
  async getAsset(token: string | undefined, assetId: string): Promise<Asset> {
    const url = apiUrl(`/assets/${assetId}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get asset with latest extraction result
   */
  async getAssetWithExtraction(token: string | undefined, assetId: string): Promise<AssetWithExtraction> {
    const url = apiUrl(`/assets/${assetId}/extraction`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get runs for an asset
   */
  async getAssetRuns(token: string | undefined, assetId: string): Promise<Run[]> {
    const url = apiUrl(`/assets/${assetId}/runs`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Trigger manual re-extraction for an asset
   */
  async reextractAsset(token: string | undefined, assetId: string): Promise<Run> {
    const url = apiUrl(`/assets/${assetId}/reextract`)
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get version history for an asset
   */
  async getAssetVersions(token: string | undefined, assetId: string): Promise<AssetVersionHistory> {
    const url = apiUrl(`/assets/${assetId}/versions`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get specific version of an asset
   */
  async getAssetVersion(token: string | undefined, assetId: string, versionNumber: number): Promise<AssetVersion> {
    const url = apiUrl(`/assets/${assetId}/versions/${versionNumber}`)
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

    const url = apiUrl(`/runs/${runId}/logs?${searchParams.toString()}`)
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

    const url = apiUrl(`/assets/bulk-upload/preview?source_type=${sourceType}`)
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

    const url = apiUrl(`/assets/bulk-upload/apply?source_type=${sourceType}&mark_missing_inactive=${markMissingInactive}`)
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
    const url = apiUrl('/assets/health')
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
    const url = apiUrl(`/assets/${assetId}/metadata?include_superseded=${includeSupersceded}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Create new metadata for an asset
   */
  async createAssetMetadata(token: string | undefined, assetId: string, request: AssetMetadataCreateRequest): Promise<AssetMetadata> {
    const url = apiUrl(`/assets/${assetId}/metadata`)
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
    const url = apiUrl(`/assets/${assetId}/metadata/${metadataId}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Promote experimental metadata to canonical
   */
  async promoteMetadata(token: string | undefined, assetId: string, metadataId: string): Promise<AssetMetadataPromoteResponse> {
    const url = apiUrl(`/assets/${assetId}/metadata/${metadataId}/promote`)
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Delete or deprecate metadata
   */
  async deleteMetadata(token: string | undefined, assetId: string, metadataId: string, hardDelete: boolean = false): Promise<{ message: string; metadata_id: string }> {
    const url = apiUrl(`/assets/${assetId}/metadata/${metadataId}?hard_delete=${hardDelete}`)
    const res = await fetch(url, {
      method: 'DELETE',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Compare two metadata records
   */
  async compareMetadata(token: string | undefined, assetId: string, metadataIdA: string, metadataIdB: string): Promise<AssetMetadataCompareResponse> {
    const url = apiUrl(`/assets/${assetId}/metadata/compare?metadata_id_a=${metadataIdA}&metadata_id_b=${metadataIdB}`)
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
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
  status: 'active' | 'paused' | 'archived'
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
  asset_subtype: 'page' | 'record'
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
}

export interface PathTreeNode {
  path: string
  name: string
  page_count: number
  record_count: number
  has_children: boolean
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

    const url = apiUrl(`/scrape/collections?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Create a new scrape collection
   */
  async createCollection(token: string | undefined, request: ScrapeCollectionCreateRequest): Promise<ScrapeCollection> {
    const url = apiUrl('/scrape/collections')
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
    const url = apiUrl(`/scrape/collections/${collectionId}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Update a collection
   */
  async updateCollection(token: string | undefined, collectionId: string, request: ScrapeCollectionUpdateRequest): Promise<ScrapeCollection> {
    const url = apiUrl(`/scrape/collections/${collectionId}`)
    const res = await fetch(url, {
      method: 'PUT',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(request),
    })
    return handleJson(res)
  },

  /**
   * Archive a collection
   */
  async deleteCollection(token: string | undefined, collectionId: string): Promise<void> {
    const url = apiUrl(`/scrape/collections/${collectionId}`)
    const res = await fetch(url, {
      method: 'DELETE',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    if (!res.ok) {
      const error = await res.text()
      throw new Error(error || res.statusText)
    }
  },

  // ========== Crawl Management ==========

  /**
   * Start a crawl for a collection
   */
  async startCrawl(token: string | undefined, collectionId: string, maxPages?: number): Promise<{ run_id: string; collection_id: string; status: string; message: string }> {
    const url = apiUrl(`/scrape/collections/${collectionId}/crawl`)
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
    const url = apiUrl(`/scrape/collections/${collectionId}/crawl/status`)
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

    const url = apiUrl(`/scrape/collections/${collectionId}/sources?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Add a source to a collection
   */
  async addSource(token: string | undefined, collectionId: string, url_source: string, sourceType: string = 'seed', crawlConfig?: Record<string, any>): Promise<ScrapeSource> {
    const url = apiUrl(`/scrape/collections/${collectionId}/sources`)
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
    const url = apiUrl(`/scrape/collections/${collectionId}/sources/${sourceId}`)
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

    const url = apiUrl(`/scrape/collections/${collectionId}/assets?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get a scraped asset
   */
  async getScrapedAsset(token: string | undefined, collectionId: string, scrapedAssetId: string): Promise<ScrapedAsset> {
    const url = apiUrl(`/scrape/collections/${collectionId}/assets/${scrapedAssetId}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Promote a page to record
   */
  async promoteToRecord(token: string | undefined, collectionId: string, scrapedAssetId: string): Promise<{ scraped_asset: ScrapedAsset; message: string }> {
    const url = apiUrl(`/scrape/collections/${collectionId}/assets/${scrapedAssetId}/promote`)
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
    const url = apiUrl(`/scrape/collections/${collectionId}/assets/${scrapedAssetId}/content`)
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

    const url = apiUrl(`/scrape/collections/${collectionId}/tree?${searchParams.toString()}`)
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

    const url = apiUrl(`/scheduled-tasks?${searchParams.toString()}`)
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

    const url = apiUrl(`/scheduled-tasks/stats?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get task details
   */
  async getTask(token: string | undefined, taskId: string): Promise<ScheduledTask> {
    const url = apiUrl(`/scheduled-tasks/${taskId}`)
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

    const url = apiUrl(`/scheduled-tasks/${taskId}/runs?${searchParams.toString()}`)
    const res = await fetch(url, {
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Enable a scheduled task
   */
  async enableTask(token: string | undefined, taskId: string): Promise<{ message: string; task_id: string; task_name: string; enabled: boolean; next_run_at: string | null }> {
    const url = apiUrl(`/scheduled-tasks/${taskId}/enable`)
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
    const url = apiUrl(`/scheduled-tasks/${taskId}/disable`)
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Trigger a scheduled task immediately
   */
  async triggerTask(token: string | undefined, taskId: string): Promise<{ message: string; task_id: string; task_name: string; run_id: string }> {
    const url = apiUrl(`/scheduled-tasks/${taskId}/trigger`)
    const res = await fetch(url, {
      method: 'POST',
      headers: { ...jsonHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },
}

// -------------------- Search API (Phase 6) --------------------

/**
 * Search request parameters
 */
export interface SearchRequest {
  query: string
  source_types?: string[]
  content_types?: string[]
  collection_ids?: string[]
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
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
}

/**
 * Index statistics response
 */
export interface IndexStatsResponse {
  enabled: boolean
  status: string
  index_name?: string
  document_count?: number
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
  index_prefix?: string
  endpoint?: string
  message?: string
}

export const searchApi = {
  /**
   * Search assets with full-text query
   */
  async search(token: string | undefined, request: SearchRequest): Promise<SearchResponse> {
    const url = apiUrl('/search')
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

    const url = apiUrl(`/search?${params.toString()}`)
    const res = await fetch(url, {
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Get search index statistics
   */
  async getStats(token: string | undefined): Promise<IndexStatsResponse> {
    const url = apiUrl('/search/stats')
    const res = await fetch(url, {
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    return handleJson(res)
  },

  /**
   * Trigger reindex of all assets (admin only)
   */
  async reindexAll(token: string | undefined): Promise<ReindexResponse> {
    const url = apiUrl('/search/reindex')
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
    const url = apiUrl('/search/health')
    const res = await fetch(url, {
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
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
  organizationsApi,
  settingsApi,
  storageApi,
  objectStorageApi,
  usersApi,
  assetsApi,
  scrapeApi,
  scheduledTasksApi,
  searchApi,
  utils,
}
