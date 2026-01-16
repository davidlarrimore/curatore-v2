// types/index.ts
export interface FileInfo {
  document_id: string;
  filename: string;
  original_filename: string;
  file_size: number;
  upload_time: number;
  file_path: string;
}

export interface ProcessingResult {
  document_id: string;
  filename: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  success: boolean;
  message?: string;
  original_path?: string;
  markdown_path?: string;
  conversion_result?: ConversionResult;
  llm_evaluation?: LLMEvaluation;
  document_summary?: string;
  conversion_score: number;
  pass_all_thresholds: boolean;
  vector_optimized: boolean;
  processing_time?: number;
  processed_at?: number;
  thresholds_used?: QualityThresholds;
}

export interface ConversionResult {
  success: boolean;
  markdown_content?: string;
  conversion_score: number;
  conversion_feedback: string;
  conversion_note: string;
  extraction_engine?: string;
  extraction_attempts?: number;
}

export interface LLMEvaluation {
  clarity_score?: number;
  clarity_feedback?: string;
  completeness_score?: number;
  completeness_feedback?: string;
  relevance_score?: number;
  relevance_feedback?: string;
  markdown_score?: number;
  markdown_feedback?: string;
  overall_feedback?: string;
  pass_recommendation?: string;
}

export interface QualityThresholds {
  conversion: number;
  clarity: number;
  completeness: number;
  relevance: number;
  markdown: number;
}

export interface OCRSettings {
  language: string;
  psm: number;
}

export interface ProcessingOptions {
  auto_optimize: boolean;
  ocr_settings: OCRSettings;
  quality_thresholds: QualityThresholds;
  extraction_engine?: string;
}

export interface BatchProcessingRequest {
  document_ids: string[];
  options: ProcessingOptions;
}

export interface BatchProcessingResult {
  batch_id: string;
  total_files: number;
  successful: number;
  failed: number;
  rag_ready: number;
  results: ProcessingResult[];
  processing_time: number;
  started_at: string;
  completed_at?: string;
}

export interface LLMConnectionStatus {
  connected: boolean;
  endpoint: string;
  model: string;
  error?: string;
  response?: string;
  ssl_verify: boolean;
  timeout: number;
}

export interface SystemStatus {
  status: string;
  timestamp: string;
  version: string;
  llm_connected: boolean;
  storage_available: boolean;
}

export interface AppConfig {
  quality_thresholds: QualityThresholds;
  ocr_settings: OCRSettings;
  auto_optimize: boolean;
}

export type ProcessingStage = 'upload' | 'process' | 'review' | 'download';

export interface ProcessingState {
  currentStage: ProcessingStage;
  sourceType: 'local' | 'upload';
  selectedFiles: FileInfo[];
  processingResults: ProcessingResult[];
  processingComplete: boolean;
  selectedResult?: ProcessingResult;
  config: AppConfig;
}
