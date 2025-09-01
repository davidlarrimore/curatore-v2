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
export const API_PATH_VERSION = 'v2' as const

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

  async downloadBulkDocuments(
    documentIds: string[],
    downloadType: 'individual' | 'combined' | 'rag_ready',
    zipName?: string,
    includeSummary: boolean = true,
  ): Promise<Blob> {
    // Align with v2 BulkDownloadRequest while keeping backward compatibility
    // v2 model: { document_ids, download_type, include_summary, include_combined, custom_filename }
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
    const payload = mapOptionsToV2(options)
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
      options: request.options ? mapOptionsToV2(request.options) : undefined,
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
    return mapV2ResultToFrontend(raw)
  },

  async processDocument(
    documentId: string,
    options: { auto_optimize?: boolean; quality_thresholds?: any },
  ): Promise<ProcessingResult> {
    const v2Options = mapOptionsToV2(options)

    const res = await fetch(apiUrl(`/documents/${encodeURIComponent(documentId)}/process`), {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify(v2Options),
    })
    const raw = await handleJson<any>(res)
    return mapV2ResultToFrontend(raw)
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
    const body = { content }
    const res = await fetch(apiUrl(`/documents/${encodeURIComponent(documentId)}/content`), {
      method: 'PUT',
      headers: jsonHeaders,
      body: JSON.stringify(body),
    })
    return handleJson(res)
  },
}

// -------------------- Utilities --------------------
export const utils = {
  generateTimestamp(): string {
    const d = new Date()
    const pad = (n: number, l = 2) => n.toString().padStart(l, '0')
    return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
  },

  downloadBlob(blob: Blob, filename: string) {
    if (typeof window === 'undefined') return
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  },

  formatDuration(seconds: number): string {
    if (!seconds && seconds !== 0) return '0s'
    const s = Math.floor(seconds % 60)
    const m = Math.floor((seconds / 60) % 60)
    const h = Math.floor(seconds / 3600)
    const pad = (n: number) => n.toString().padStart(2, '0')
    return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
  },

  formatFileSize(bytes: number): string {
    if (!Number.isFinite(bytes) || bytes < 0) return '0 B'
    if (bytes < 1024) return `${bytes} B`
    const units = ['KB', 'MB', 'GB', 'TB']
    let size = bytes / 1024
    let unitIndex = 0
    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024
      unitIndex++
    }
    return `${size.toFixed(1)} ${units[unitIndex]}`
  },

  calculateStats(results: ProcessingResult[]) {
    const total = results.length
    const successful = results.filter(r => r.success).length
    const failed = total - successful
    const ragReady = results.filter(r => r.pass_all_thresholds).length
    const optimized = results.filter(r => r.vector_optimized).length
    return { total, successful, failed, ragReady, optimized }
  },
}

// Note: default export placed after all const exports to avoid TDZ issues

// -------------------- Internal helpers --------------------
function mapV2ResultToFrontend(raw: any): ProcessingResult {
  // Preserve all fields and add compatibility aliases the app expects
  const conversion_score = raw.conversion_score ?? raw.conversion_result?.conversion_score ?? 0
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

function mapOptionsToV2(options: any): any {
  const v2: any = {
    auto_improve: options?.auto_optimize ?? true,
    vector_optimize: options?.auto_optimize ?? true,
  }
  const qt = options?.quality_thresholds
  if (qt) {
    v2.quality_thresholds = {
      conversion_quality: Math.round(qt.conversion_quality ?? qt.conversion ?? qt.conversion_threshold ?? 70),
      clarity_score: Math.round(qt.clarity_score ?? qt.clarity ?? qt.clarity_threshold ?? 7),
      completeness_score: Math.round(qt.completeness_score ?? qt.completeness ?? qt.completeness_threshold ?? 7),
      relevance_score: Math.round(qt.relevance_score ?? qt.relevance ?? qt.relevance_threshold ?? 7),
      markdown_quality: Math.round(qt.markdown_quality ?? qt.markdown ?? qt.markdown_threshold ?? 7),
    }
  }
  return v2
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

export default {
  API_BASE_URL,
  API_PATH_VERSION,
  systemApi,
  fileApi,
  processingApi,
  contentApi,
  jobsApi,
  utils,
}
