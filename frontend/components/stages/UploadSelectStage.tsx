// components/stages/UploadSelectStage.tsx
'use client'

import React, { useState, useRef, useCallback, useEffect, type FC } from 'react';
import { FileInfo, ProcessingOptions } from '@/types';
import { fileApi, utils } from '@/lib/api';
import { 
  FileText, 
  Image, 
  FileSpreadsheet, 
  File,
  Clock,
  Zap,
  Database,
  CheckCircle2,
  RefreshCw,
  Trash2,
  HelpCircle
} from 'lucide-react';

/**
 * Props for the UploadSelectStage component.
 */
interface UploadSelectStageProps {
  /** The source of files to display: 'local' for server-side batch files, 'upload' for user-uploaded files. */
  sourceType: 'local' | 'upload';
  /** Callback function to change the source type. */
  onSourceTypeChange: (type: 'local' | 'upload') => void;
  /** An array of currently selected files. */
  selectedFiles: FileInfo[];
  /** Callback function to update the list of selected files. */
  onSelectedFilesChange: (files: FileInfo[]) => void;
  /** Callback function to initiate the processing of selected files. */
  onProcess: (files: FileInfo[], options: ProcessingOptions) => void;
  /** An array of supported file format extensions (e.g., ['.pdf', '.docx']). */
  supportedFormats: string[];
  /** The maximum allowed file size in bytes. */
  maxFileSize: number;
  /** The current processing options. */
  processingOptions: ProcessingOptions;
  /** Callback function to update the processing options. */
  onProcessingOptionsChange: (options: ProcessingOptions) => void;
  /** A boolean indicating if a processing job is currently in progress. */
  isProcessing: boolean;
  /** Processing panel state for button positioning */
  processingPanelState?: 'hidden' | 'minimized' | 'normal' | 'fullscreen';
}

/**
 * A React component representing a stage in a workflow where users can select
 * files for processing. It supports selecting from pre-existing local (batch) files
 * or uploading new files, and allows configuration of processing settings.
 */
export const UploadSelectStage: FC<UploadSelectStageProps> = ({
  sourceType,
  onSourceTypeChange,
  selectedFiles,
  onSelectedFilesChange,
  onProcess,
  supportedFormats,
  maxFileSize,
  processingOptions,
  onProcessingOptionsChange,
  isProcessing,
  processingPanelState = 'hidden'
}) => {
  // Tooltip helpers
  const getThresholdTip = (label: string): string => {
    switch (label) {
      case 'Clarity':
        return 'Minimum readability/legibility score (1–10) a document must meet.';
      case 'Completeness':
        return 'Minimum coverage score (1–10) to ensure content is not missing key parts.';
      case 'Relevance':
        return 'Minimum on-topic score (1–10) to ensure content matches intent.';
      case 'Markdown':
        return 'Minimum formatting quality score (1–10) for clean Markdown output.';
      default:
        return '';
    }
  };
  // State for files fetched from the server's 'uploads' directory.
  const [uploadedFiles, setUploadedFiles] = useState<FileInfo[]>([]);
  // State for files fetched from the server's 'batch_files' directory.
  const [batchFiles, setBatchFiles] = useState<FileInfo[]>([]);
  // State to track if a file upload is in progress.
  const [isUploading, setIsUploading] = useState(false);
  // State to track if the file list is being refreshed.
  const [isRefreshing, setIsRefreshing] = useState(false);
  // State to manage the visual feedback for the drag-and-drop area.
  const [dragActive, setDragActive] = useState(false);
  // State to toggle the visibility of advanced processing settings.
  const [showAdvancedSettings, setShowAdvancedSettings] = useState(false);
  // State to track initial loading
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  // Ref for the hidden file input element to trigger it programmatically.
  const fileInputRef = useRef<HTMLInputElement>(null);

  /**
   * Effect to load the appropriate file list when the `sourceType` changes.
   */
  useEffect(() => {
    const loadFiles = async () => {
      setIsInitialLoading(true);
      if (sourceType === 'upload') {
        await loadUploadedFiles();
      } else {
        await loadBatchFiles();
      }
      setIsInitialLoading(false);
    };
    
    loadFiles();
  }, [sourceType]);

  // Load both file types on component mount
  useEffect(() => {
    const loadAllFiles = async () => {
      await Promise.all([
        loadUploadedFiles(),
        loadBatchFiles()
      ]);
    };
    
    loadAllFiles();
  }, []);
  /**
   * Fetches the list of already uploaded files from the API and updates the state.
   */
  const loadUploadedFiles = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const response = await fileApi.listUploadedFiles();
      setUploadedFiles(response.files);
    } catch (error) {
      console.error('Failed to load uploaded files:', error);
    } finally {
      setIsRefreshing(false);
    }
  }, []);

  /**
   * Fetches the list of local batch files from the API and updates the state.
   */
  const loadBatchFiles = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const response = await fileApi.listBatchFiles();
      setBatchFiles(response.files);
    } catch (error) {
      console.error('Failed to load batch files:', error);
      setBatchFiles([]);
    } finally {
      setIsRefreshing(false);
    }
  }, []);

  /**
   * Delete a single uploaded file by document ID, then refresh lists and selections.
   */
  const handleDeleteUploadedFile = useCallback(async (file: FileInfo) => {
    if (sourceType !== 'upload') return;
    const confirmed = confirm(`Delete uploaded file "${utils.getDisplayFilename(file.filename)}"? This cannot be undone.`);
    if (!confirmed) return;

    try {
      await fileApi.deleteDocument(file.document_id);
      // Remove from uploaded list immediately for responsiveness
      setUploadedFiles(prev => prev.filter(f => f.document_id !== file.document_id));
      // Remove from selected files if present
      onSelectedFilesChange(selectedFiles.filter(f => f.document_id !== file.document_id));
    } catch (error) {
      console.error('Failed to delete file:', error);
      alert('Failed to delete file. Please try again.');
    }
  }, [onSelectedFilesChange, selectedFiles, sourceType]);

  /**
   * Delete all uploaded files (bulk). Iterates over current uploaded files.
   */
  const handleDeleteAllUploadedFiles = useCallback(async () => {
    if (sourceType !== 'upload' || uploadedFiles.length === 0) return;
    const confirmed = confirm(`Delete ALL uploaded files (${uploadedFiles.length})? This cannot be undone.`);
    if (!confirmed) return;

    try {
      const deletions = await Promise.allSettled(
        uploadedFiles.map(f => fileApi.deleteDocument(f.document_id))
      );
      const failed = deletions.filter(r => r.status === 'rejected');
      if (failed.length > 0) {
        alert(`${failed.length} file(s) could not be deleted. Some items may remain.`);
      }
      // Refresh uploaded list and clear any selected that were uploaded
      await loadUploadedFiles();
      const uploadedIds = new Set(uploadedFiles.map(f => f.document_id));
      onSelectedFilesChange(selectedFiles.filter(f => !uploadedIds.has(f.document_id)));
    } catch (error) {
      console.error('Failed bulk delete:', error);
      alert('Failed to delete all files. Please try again.');
    }
  }, [loadUploadedFiles, onSelectedFilesChange, selectedFiles, sourceType, uploadedFiles]);

  /**
   * Handles the file upload process for an array of File objects.
   * Validates each file, uploads them in parallel via the API, and then refreshes the file list.
   */
  const handleFileUpload = async (files: File[]) => {
    setIsUploading(true);

    // First, filter out invalid files and alert the user for each.
    const validFiles = files.filter(file => {
      if (!supportedFormats.includes(`.${file.name.split('.').pop()?.toLowerCase()}`)) {
        alert(`Unsupported file type: ${file.name}`);
        return false;
      }
      if (file.size > maxFileSize) {
        alert(`File too large: ${file.name} (${utils.formatFileSize(file.size)})`);
        return false;
      }
      return true;
    });

    if (validFiles.length === 0) {
      setIsUploading(false);
      return;
    }

    // Create an array of upload promises to run them in parallel.
    const uploadPromises = validFiles.map(file => fileApi.uploadFile(file));
    
    // Use Promise.allSettled to wait for all uploads to complete, regardless of success or failure.
    const results = await Promise.allSettled(uploadPromises);

    const successfulUploads: FileInfo[] = [];
    results.forEach((result, index) => {
      const file = validFiles[index];
      if (result.status === 'fulfilled') {
        const uploadResult = result.value;
        successfulUploads.push({
          document_id: uploadResult.document_id,
          filename: uploadResult.filename,
          original_filename: uploadResult.filename,
          file_size: uploadResult.file_size,
          upload_time: uploadResult.upload_time ? new Date(uploadResult.upload_time).getTime() : Date.now(),
          file_path: ''
        });
      } else {
        // Handle failed uploads
        console.error(`Failed to upload ${file.name}:`, result.reason);
        const errorMessage = result.reason instanceof Error ? result.reason.message : 'Unknown error occurred';
        alert(`Failed to upload ${file.name}: ${errorMessage}`);
      }
    });

    // After all uploads are settled, update the UI.
    if (successfulUploads.length > 0) {
      await loadUploadedFiles();
      // Auto-select newly uploaded files.
      onSelectedFilesChange([...selectedFiles, ...successfulUploads]);
    }

    setIsUploading(false);
  };

  /**
   * Generic drag event handler to prevent default behavior and manage drag-active state.
   * @param e - The React drag event.
   */
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  /**
   * Handles the drop event, extracting files from the data transfer and initiating the upload.
   * @param e - The React drag event.
   */
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    const files = Array.from(e.dataTransfer.files);
    handleFileUpload(files);
  };

  /**
   * Handles file selection from the native file input dialog.
   * @param e - The React change event from the input element.
   */
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const files = Array.from(e.target.files);
      handleFileUpload(files);
    }
  };

  /**
   * Toggles the selection state of a single file.
   * @param file - The file to toggle.
   * @param checked - The new checked state.
   */
  const handleFileToggle = (file: FileInfo, checked: boolean) => {
    const keyOf = (f: FileInfo) => f.document_id || f.file_path || f.filename;
    if (checked) {
      onSelectedFilesChange([...selectedFiles, file]);
    } else {
      onSelectedFilesChange(selectedFiles.filter(f => keyOf(f) !== keyOf(file)));
    }
  };

  /**
   * Toggles the selection state for all files currently displayed.
   * @param files - The list of all files currently visible.
   * @param checked - The new checked state for all files.
   */
  const handleSelectAll = (files: FileInfo[], checked: boolean) => {
    const keyOf = (f: FileInfo) => f.document_id || f.file_path || f.filename;
    if (checked) {
      const newFiles = files.filter(f => !selectedFiles.some(sf => keyOf(sf) === keyOf(f)));
      onSelectedFilesChange([...selectedFiles, ...newFiles]);
    } else {
      const fileIds = files.map(f => keyOf(f));
      onSelectedFilesChange(selectedFiles.filter(f => !fileIds.includes(keyOf(f))));
    }
  };

  /**
   * Initiates the processing job by calling the `onProcess` prop with selected files and options.
   */
  const handleProcess = () => {
    if (selectedFiles.length === 0) {
      alert('Please select files to process');
      return;
    }
    onProcess(selectedFiles, processingOptions);
  };

  /**
   * Get file type icon and label based on extension
   */
  const getFileTypeInfo = (filename: string) => {
    const ext = filename.split('.').pop()?.toLowerCase() || '';
    
    switch (ext) {
      case 'pdf':
        return { icon: FileText, label: 'PDF Document', color: 'text-red-600 bg-red-50' };
      case 'docx':
      case 'doc':
        return { icon: FileText, label: 'Word Document', color: 'text-blue-600 bg-blue-50' };
      case 'txt':
      case 'md':
        return { icon: FileText, label: 'Text Document', color: 'text-gray-600 bg-gray-50' };
      case 'png':
      case 'jpg':
      case 'jpeg':
      case 'bmp':
      case 'tif':
      case 'tiff':
        return { icon: Image, label: 'Image File', color: 'text-green-600 bg-green-50' };
      case 'xlsx':
      case 'xls':
        return { icon: FileSpreadsheet, label: 'Spreadsheet', color: 'text-emerald-600 bg-emerald-50' };
      default:
        return { icon: File, label: 'Document', color: 'text-gray-600 bg-gray-50' };
    }
  };

  /**
   * Estimate token count based on file size (rough approximation)
   */
  const estimateTokens = (fileSize: number): string => {
    // Very rough estimation: ~4 characters per token, ~1 byte per character for text files
    // For images and other binary formats, tokens will be much lower after OCR
    const roughChars = fileSize;
    const estimatedTokens = Math.round(roughChars / 4);
    
    if (estimatedTokens > 1000000) {
      return `~${(estimatedTokens / 1000000).toFixed(1)}M`;
    } else if (estimatedTokens > 1000) {
      return `~${(estimatedTokens / 1000).toFixed(1)}k`;
    } else {
      return `~${estimatedTokens}`;
    }
  };

  /**
   * A helper function to get the current list of files based on the `sourceType`.
   * @returns An array of `FileInfo` objects.
   */
  const getCurrentFiles = () => {
    return sourceType === 'upload' ? uploadedFiles : batchFiles;
  };

  /**
   * Renders the list of files with selection controls in a compact table format.
   * @param files - The array of files to render.
   * @param title - The title to display above the file list.
   * @returns A JSX element representing the file list.
   */
  const renderFileList = (files: FileInfo[], title: string): React.JSX.Element => {
    const keyOf = (f: FileInfo) => f.document_id || f.file_path || f.filename;
    const allSelected = files.length > 0 && files.every(f => 
      selectedFiles.some(sf => keyOf(sf) === keyOf(f))
    );

    return (
      <div className="space-y-4 flex flex-col h-full">
        <div className="flex items-center justify-between flex-shrink-0">
          <div className="flex items-center space-x-4">
            <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
            <span className="px-3 py-1 bg-gray-100 text-gray-700 text-sm font-medium rounded-full">
              {files.length} files
            </span>
            {selectedFiles.length > 0 && (
              <span className="px-3 py-1 bg-blue-100 text-blue-700 text-sm font-medium rounded-full">
                {selectedFiles.length} selected
              </span>
            )}
          </div>
          
          <div className="flex items-center space-x-3">
            {files.length > 0 && (
              <label className="flex items-center space-x-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(e) => handleSelectAll(files, e.target.checked)}
                  className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <span className="text-sm font-medium text-gray-700">Select All</span>
              </label>
            )}
            {sourceType === 'upload' && files.length > 0 && (
              <button
                type="button"
                onClick={handleDeleteAllUploadedFiles}
                className="flex items-center space-x-2 px-3 py-2 text-sm font-medium bg-red-50 hover:bg-red-100 text-red-700 rounded-lg transition-colors"
              >
                <Trash2 className="w-4 h-4" />
                <span>Delete All</span>
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                if (sourceType === 'upload') {
                  loadUploadedFiles();
                } else {
                  loadBatchFiles();
                }
              }}
              disabled={isRefreshing}
              className="flex items-center space-x-2 px-3 py-2 text-sm font-medium bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {files.length === 0 ? (
          <div className="text-center py-12 text-gray-500 flex-shrink-0 border-2 border-dashed border-gray-200 rounded-xl">
            <div className="text-6xl mb-4">📂</div>
            <div>
              <p className="text-xl font-medium mb-2">No files found</p>
              <p className="text-sm">Upload files using the area above to get started</p>
            </div>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto min-h-0 border border-gray-200 rounded-lg">
            {/* Table Header */}
            <div className="bg-gray-50 border-b border-gray-200 px-6 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wider">
              <div className="grid grid-cols-12 gap-4 items-center">
                <div className="col-span-1">Select</div>
                <div className="col-span-4">File Name</div>
                <div className="col-span-2">Type</div>
                <div className="col-span-1">Size</div>
                <div className="col-span-1">Tokens</div>
                <div className="col-span-2">Modified</div>
                <div className="col-span-1">Source</div>
              </div>
            </div>

            {/* Table Body */}
            <div className="divide-y divide-gray-200">
              {files.map((file) => {
                const isSelected = selectedFiles.some(sf => keyOf(sf) === keyOf(file));
                const fileTypeInfo = getFileTypeInfo(file.filename);
                const IconComponent = fileTypeInfo.icon;
                const estimatedTokens = estimateTokens(file.file_size);

                return (
                  <div key={keyOf(file)} className={`px-6 py-3 hover:bg-gray-50 transition-colors ${isSelected ? 'bg-blue-50' : ''}`}>
                    <div className="grid grid-cols-12 gap-4 items-center text-sm">
                      {/* Checkbox */}
                      <div className="col-span-1">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={(e) => handleFileToggle(file, e.target.checked)}
                          className="rounded border-gray-300 text-blue-600 focus:ring-blue-500 focus:ring-offset-0"
                        />
                      </div>

                      {/* File Name */}
                      <div className="col-span-4">
                        <div className="flex items-center space-x-3">
                          <IconComponent className="w-5 h-5 text-gray-400 flex-shrink-0" />
                          <div className="min-w-0 flex-1">
                            <p className="font-medium text-gray-900 truncate" title={utils.getDisplayFilename(file.filename)}>
                              {utils.getDisplayFilename(file.filename)}
                            </p>
                          </div>
                        </div>
                      </div>

                      {/* File Type */}
                      <div className="col-span-2">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${fileTypeInfo.color}`}>
                          {fileTypeInfo.label}
                        </span>
                      </div>

                      {/* File Size */}
                      <div className="col-span-1">
                        <span className="text-gray-600 font-mono text-xs">
                          {utils.formatFileSize(file.file_size)}
                        </span>
                      </div>

                      {/* Estimated Tokens */}
                      <div className="col-span-1">
                        <div className="flex items-center space-x-1">
                          <Zap className="w-3 h-3 text-amber-500" />
                          <span className="text-gray-600 font-mono text-xs">
                            {estimatedTokens}
                          </span>
                        </div>
                      </div>

                      {/* Modified Date */}
                      <div className="col-span-2">
                        <div className="flex items-center space-x-1 text-gray-600">
                          <Clock className="w-3 h-3" />
                          <span className="text-xs">
                            {new Date(file.upload_time).toLocaleDateString('en-US', {
                              month: 'short',
                              day: 'numeric',
                              hour: '2-digit',
                              minute: '2-digit'
                            })}
                          </span>
                        </div>
                      </div>

                      {/* Source + Actions (for uploaded files) */}
                      <div className="col-span-1">
                        <div className="flex items-center justify-between">
                          {sourceType === 'local' ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-800">
                              <Database className="w-3 h-3 mr-1" />
                              Batch
                            </span>
                          ) : (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">
                              <CheckCircle2 className="w-3 h-3 mr-1" />
                              Upload
                            </span>
                          )}
                          {sourceType === 'upload' && (
                            <button
                              type="button"
                              title="Delete file"
                              onClick={() => handleDeleteUploadedFile(file)}
                              className="ml-2 p-1 rounded hover:bg-red-50 text-red-600"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    );
  };

  const currentFiles = getCurrentFiles();

  return (
    <div className="h-full flex flex-col space-y-6 pb-24">
      {/* Processing Settings - Enterprise Card Style */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center">
              <div className="p-1.5 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-lg mr-2">
                <Zap className="w-4 h-4 text-white" />
              </div>
              Processing Configuration
            </h3>
            
            {/* Vector DB Optimization and Quality Thresholds removed */}

            {/* Extraction Engine Selection */}
            <div className="flex items-center space-x-2">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300 relative inline-flex items-center group cursor-help">
                Extraction Engine
                <HelpCircle className="w-3 h-3 text-gray-400 dark:text-gray-500 ml-1" />
                <span className="absolute left-0 top-full mt-1 z-10 w-max max-w-xs px-2 py-1 text-[11px] rounded bg-gray-900 text-white opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-opacity">Choose which extractor to use for this job. The selected engine is used exclusively.</span>
              </span>
              <select
                value={processingOptions.extraction_engine ?? 'auto'}
                onChange={(e) => onProcessingOptionsChange({
                  ...processingOptions,
                  extraction_engine: e.target.value
                })}
                className="px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              >
                <option value="auto">Auto (Recommended)</option>
                <option value="fast_pdf">Fast PDF</option>
                <option value="markitdown">MarkItDown</option>
                <option value="docling">Docling</option>
              </select>
            </div>

            {/* OCR Language Quick Setting removed: use Advanced Language Code field */}
          </div>

          {/* Advanced Settings Toggle */}
          <button
            type="button"
            onClick={() => setShowAdvancedSettings(!showAdvancedSettings)}
            className="flex items-center space-x-2 px-3 py-2 text-sm font-medium text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
          >
            <span>Advanced Settings</span>
            <svg
              className={`w-4 h-4 transition-transform ${showAdvancedSettings ? 'rotate-180' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        </div>

        {/* Advanced Settings Panel */}
        {showAdvancedSettings && (
          <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
            {/* Detailed Quality Thresholds removed - not part of current options */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              {/* Processing Settings removed - not part of current options */}

              {/* OCR settings removed — backend auto-detects OCR now */}

              {/* System Info */}
              <div className="space-y-3">
                <h4 className="font-medium text-gray-900">System Limits</h4>
                <div className="space-y-1 text-xs text-gray-600">
                  <div className="flex items-center justify-between">
                    <span>Max File Size:</span>
                    <span className="font-mono">{utils.formatFileSize(maxFileSize)}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Supported Formats:</span>
                    <span className="font-mono">{supportedFormats.length} types</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Available Files:</span>
                    <span className="font-mono">{currentFiles.length} files</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Selected:</span>
                    <span className="font-mono text-blue-600">{selectedFiles.length} files</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Source Type Switcher - Enterprise Style Tabs */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm p-1.5">
        <div className="grid grid-cols-2 gap-1.5">
          <button
            type="button"
            onClick={() => onSourceTypeChange('local')}
            className={`flex items-center justify-center space-x-2 px-6 py-3 rounded-lg font-medium transition-all ${
              sourceType === 'local'
                ? 'bg-gradient-to-r from-indigo-600 to-purple-600 text-white shadow-lg shadow-indigo-500/25'
                : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800'
            }`}
          >
            <Database className="w-5 h-5" />
            <span>Local Batch Files</span>
            <span className={`px-2 py-1 rounded-full text-xs font-medium ${
              sourceType === 'local'
                ? 'bg-white/20 text-white'
                : 'bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400'
            }`}>
              {isInitialLoading && sourceType === 'local' ? '...' : batchFiles.length}
            </span>
          </button>
          <button
            type="button"
            onClick={() => onSourceTypeChange('upload')}
            className={`flex items-center justify-center space-x-2 px-6 py-3 rounded-lg font-medium transition-all ${
              sourceType === 'upload'
                ? 'bg-gradient-to-r from-indigo-600 to-purple-600 text-white shadow-lg shadow-indigo-500/25'
                : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800'
            }`}
          >
            <CheckCircle2 className="w-5 h-5" />
            <span>Uploaded Files</span>
            <span className={`px-2 py-1 rounded-full text-xs font-medium ${
              sourceType === 'upload'
                ? 'bg-white/20 text-white'
                : 'bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400'
            }`}>
              {isInitialLoading && sourceType === 'upload' ? '...' : uploadedFiles.length}
            </span>
          </button>
        </div>
      </div>

      {/* Main Content Area - Full width file browser */}
      <div className="flex-1 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm flex flex-col min-h-0">
        {sourceType === 'upload' && (
          /* Upload Area - Compact when files exist */
          <div className={`border-b border-gray-200 dark:border-gray-800 p-6 ${uploadedFiles.length > 0 ? '' : 'flex-1'}`}>
            <div
              className={`relative border-2 border-dashed rounded-xl transition-all ${
                uploadedFiles.length > 0 ? 'p-4' : 'p-12'
              } text-center ${
                dragActive
                  ? 'border-indigo-400 bg-indigo-50 dark:bg-indigo-900/20'
                  : 'border-gray-300 dark:border-gray-700 hover:border-indigo-400 dark:hover:border-indigo-500'
              }`}
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
            >
              <input
                ref={fileInputRef}
                type="file"
                multiple
                onChange={handleFileSelect}
                accept={supportedFormats.join(',')}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                disabled={isUploading}
              />

              <div className={`space-y-2 ${uploadedFiles.length > 0 ? 'text-sm' : ''}`}>
                <div className={`${uploadedFiles.length > 0 ? 'text-2xl' : 'text-5xl'}`}>
                  <FileText className={`mx-auto ${uploadedFiles.length > 0 ? 'w-8 h-8' : 'w-16 h-16'} text-gray-400 dark:text-gray-500`} />
                </div>
                <div>
                  <p className={`font-medium text-gray-700 dark:text-gray-300 ${uploadedFiles.length > 0 ? 'text-sm' : 'text-lg'}`}>
                    {isUploading ? 'Uploading files...' : uploadedFiles.length > 0 ? 'Drop more files or click to browse' : 'Drop files here or click to browse'}
                  </p>
                  <p className={`text-gray-500 dark:text-gray-400 mt-1 ${uploadedFiles.length > 0 ? 'text-xs' : 'text-sm'}`}>
                    {supportedFormats.join(', ')} • Max: {utils.formatFileSize(maxFileSize)}
                  </p>
                </div>
              </div>

              {isUploading && (
                <div className="absolute inset-0 bg-white/90 dark:bg-gray-900/90 flex items-center justify-center rounded-xl">
                  <div className="flex items-center space-x-3">
                    <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-indigo-600"></div>
                    <span className="text-indigo-600 dark:text-indigo-400 font-medium">Uploading files...</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* File List Area */}
        <div className="flex-1 p-6 min-h-0">
          {sourceType === 'local' ? (
            <div className="h-full">
              {renderFileList(batchFiles, 'Local Batch Files')}
            </div>
          ) : (
            <div className="h-full">
              {renderFileList(uploadedFiles, 'Uploaded Files')}
            </div>
          )}
        </div>
      </div>

      {/* Fixed Action Button - Bottom Right with Processing Panel Awareness */}
      {processingPanelState !== 'fullscreen' && (
        <div className={`fixed right-6 z-40 transition-all duration-300 ${
          processingPanelState === 'normal'
            ? 'bottom-[424px]'  // Above normal processing panel: 360px panel + 52px (status + gap) + 12px margin = 424px
            : processingPanelState === 'minimized'
            ? 'bottom-[92px]'   // Above minimized panel: 40px panel + 40px (status) + 12px margin = 92px
            : 'bottom-16'       // Above status bar only: 52px (status + gap) + 12px margin = 64px (bottom-16)
        }`}>
          <button
            type="button"
            onClick={handleProcess}
            disabled={selectedFiles.length === 0 || isProcessing}
            className={`px-6 py-3 rounded-full font-medium text-sm transition-all ${
              selectedFiles.length === 0 || isProcessing
                ? 'bg-gray-300 dark:bg-gray-700 text-gray-500 dark:text-gray-400 cursor-not-allowed'
                : 'bg-gradient-to-r from-indigo-600 to-purple-600 text-white shadow-lg shadow-indigo-500/25 hover:shadow-xl hover:shadow-indigo-500/30 hover:-translate-y-1'
            }`}
          >
            {isProcessing ? (
              <span className="flex items-center space-x-2">
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white/50"></div>
                <span>Processing {selectedFiles.length} files...</span>
              </span>
            ) : (
              <span className="flex items-center space-x-2">
                <Zap className="w-4 h-4" />
                <span>Process {selectedFiles.length} File{selectedFiles.length !== 1 ? 's' : ''}</span>
              </span>
            )}
          </button>
        </div>
      )}
    </div>
  );
};
