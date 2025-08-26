// components/stages/UploadSelectStage.tsx
'use client'

import { useState, useRef, useCallback, useEffect, type FC } from 'react';
import { FileInfo, ProcessingOptions } from '@/types';
import { fileApi, utils } from '@/lib/api';

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
  isProcessing
}) => {
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
  // Ref for the hidden file input element to trigger it programmatically.
  const fileInputRef = useRef<HTMLInputElement>(null);

  /**
   * Effect to load the appropriate file list when the `sourceType` changes.
   */
  useEffect(() => {
    if (sourceType === 'upload') {
      loadUploadedFiles();
    } else {
      loadBatchFiles();
    }
  }, [sourceType]); // Dependencies are intentionally minimal for this effect.

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
          upload_time: new Date(uploadResult.upload_time).getTime(),
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
    if (checked) {
      onSelectedFilesChange([...selectedFiles, file]);
    } else {
      onSelectedFilesChange(selectedFiles.filter(f => f.document_id !== file.document_id));
    }
  };

  /**
   * Toggles the selection state for all files currently displayed.
   * @param files - The list of all files currently visible.
   * @param checked - The new checked state for all files.
   */
  const handleSelectAll = (files: FileInfo[], checked: boolean) => {
    if (checked) {
      const newFiles = files.filter(f => !selectedFiles.some(sf => sf.document_id === f.document_id));
      onSelectedFilesChange([...selectedFiles, ...newFiles]);
    } else {
      const fileIds = files.map(f => f.document_id);
      onSelectedFilesChange(selectedFiles.filter(f => !fileIds.includes(f.document_id)));
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
   * A helper function to get the current list of files based on the `sourceType`.
   * @returns An array of `FileInfo` objects.
   */
  const getCurrentFiles = () => {
    return sourceType === 'upload' ? uploadedFiles : batchFiles;
  };

  /**
   * Renders the list of files with selection controls.
   * @param files - The array of files to render.
   * @param title - The title to display above the file list.
   * @returns A JSX element representing the file list.
   */
  const renderFileList = (files: FileInfo[], title: string): JSX.Element => {
    const allSelected = files.length > 0 && files.every(f => 
      selectedFiles.some(sf => sf.document_id === f.document_id)
    );

    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-medium">{title} ({files.length})</h3>
          <div className="flex items-center space-x-2">
            {files.length > 0 && (
              <label className="flex items-center space-x-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(e) => handleSelectAll(files, e.target.checked)}
                  className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <span className="text-sm text-gray-600">Select All</span>
              </label>
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
              className="px-3 py-1 text-sm bg-gray-100 hover:bg-gray-200 rounded-md transition-colors disabled:opacity-50"
            >
              {isRefreshing ? '🔄' : '🔄'} Refresh
            </button>
          </div>
        </div>

        {files.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            <div className="text-4xl mb-2">📁</div>
            {sourceType === 'local' ? (
              <div>
                <p className="font-medium">No batch files found</p>
                <p className="text-sm mt-1">
                  Place files in the <code className="bg-gray-200 px-1 rounded">files/batch_files/</code> folder and refresh
                </p>
              </div>
            ) : (
              <p>No uploaded files found</p>
            )}
          </div>
        ) : (
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {files.map((file) => {
              const isSelected = selectedFiles.some(sf => sf.document_id === file.document_id);
              return (
                <div key={file.document_id} className="flex items-center space-x-3 p-3 border rounded-lg hover:bg-gray-50">
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={(e) => handleFileToggle(file, e.target.checked)}
                    className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  <div className="flex-1">
                    <p className="font-medium text-gray-900">{file.filename}</p>
                    <div className="flex items-center space-x-2 text-sm text-gray-500">
                      <span>{utils.formatFileSize(file.file_size)}</span>
                      <span>•</span>
                      <span>{new Date(file.upload_time).toLocaleDateString()}</span>
                      {sourceType === 'local' && (
                        <>
                          <span>•</span>
                          <span className="bg-blue-100 text-blue-800 px-2 py-0.5 rounded text-xs">Batch</span>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  };

  const currentFiles = getCurrentFiles(); // Memoization could be used here if performance becomes an issue.

  return (
    <div className="h-full flex flex-col">

      {/* Main Content Area - Two Column Layout */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-4 gap-6 min-h-0">
        {/* Left Panel - Processing Settings */}
        <div className="lg:col-span-1 space-y-6">
          <div className="bg-white rounded-lg border p-6 h-fit">
            <h3 className="text-lg font-medium mb-4 flex items-center">
              ⚙️ Processing Settings
            </h3>
            
            {/* Vector DB Optimization */}
            <div className="space-y-4">
              <label className="flex items-start space-x-3">
                <input
                  type="checkbox"
                  checked={processingOptions.auto_optimize}
                  onChange={(e) => onProcessingOptionsChange({
                    ...processingOptions,
                    auto_optimize: e.target.checked
                  })}
                  className="rounded border-gray-300 text-blue-600 focus:ring-blue-500 mt-0.5"
                />
                <div>
                  <span className="font-medium text-gray-900">🎯 Vector DB Optimization</span>
                  <p className="text-sm text-gray-600 mt-1">
                    Automatically restructure documents for better vector database performance and semantic search
                  </p>
                </div>
              </label>
            </div>

            {/* Quality Thresholds */}
            <div className="mt-6 pt-6 border-t border-gray-200">
              <div className="flex items-center justify-between mb-4">
                <h4 className="font-medium text-gray-900">📊 Quality Thresholds</h4>
                <span className="text-xs text-gray-500">All must be met for RAG readiness</span>
              </div>

              <div className="space-y-4">
                {/* Conversion Quality */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <label className="text-sm font-medium text-gray-700">Conversion Quality</label>
                    <span className="text-sm text-gray-600">{processingOptions.quality_thresholds.conversion_threshold}/100</span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    value={processingOptions.quality_thresholds.conversion_threshold}
                    onChange={(e) => onProcessingOptionsChange({
                      ...processingOptions,
                      quality_thresholds: {
                        ...processingOptions.quality_thresholds,
                        conversion_threshold: parseInt(e.target.value)
                      }
                    })}
                    className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                  />
                </div>

                {/* Clarity */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <label className="text-sm font-medium text-gray-700">Clarity</label>
                    <span className="text-sm text-gray-600">{processingOptions.quality_thresholds.clarity_threshold}/10</span>
                  </div>
                  <input
                    type="range"
                    min="1"
                    max="10"
                    value={processingOptions.quality_thresholds.clarity_threshold}
                    onChange={(e) => onProcessingOptionsChange({
                      ...processingOptions,
                      quality_thresholds: {
                        ...processingOptions.quality_thresholds,
                        clarity_threshold: parseInt(e.target.value)
                      }
                    })}
                    className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                  />
                </div>

                {/* Completeness */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <label className="text-sm font-medium text-gray-700">Completeness</label>
                    <span className="text-sm text-gray-600">{processingOptions.quality_thresholds.completeness_threshold}/10</span>
                  </div>
                  <input
                    type="range"
                    min="1"
                    max="10"
                    value={processingOptions.quality_thresholds.completeness_threshold}
                    onChange={(e) => onProcessingOptionsChange({
                      ...processingOptions,
                      quality_thresholds: {
                        ...processingOptions.quality_thresholds,
                        completeness_threshold: parseInt(e.target.value)
                      }
                    })}
                    className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                  />
                </div>

                {/* Relevance */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <label className="text-sm font-medium text-gray-700">Relevance</label>
                    <span className="text-sm text-gray-600">{processingOptions.quality_thresholds.relevance_threshold}/10</span>
                  </div>
                  <input
                    type="range"
                    min="1"
                    max="10"
                    value={processingOptions.quality_thresholds.relevance_threshold}
                    onChange={(e) => onProcessingOptionsChange({
                      ...processingOptions,
                      quality_thresholds: {
                        ...processingOptions.quality_thresholds,
                        relevance_threshold: parseInt(e.target.value)
                      }
                    })}
                    className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                  />
                </div>

                {/* Markdown Quality */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <label className="text-sm font-medium text-gray-700">Markdown Quality</label>
                    <span className="text-sm text-gray-600">{processingOptions.quality_thresholds.markdown_threshold}/10</span>
                  </div>
                  <input
                    type="range"
                    min="1"
                    max="10"
                    value={processingOptions.quality_thresholds.markdown_threshold}
                    onChange={(e) => onProcessingOptionsChange({
                      ...processingOptions,
                      quality_thresholds: {
                        ...processingOptions.quality_thresholds,
                        markdown_threshold: parseInt(e.target.value)
                      }
                    })}
                    className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                  />
                </div>
              </div>
            </div>

            {/* Advanced Settings Toggle */}
            <div className="mt-6 pt-6 border-t border-gray-200">
              <button
                type="button"
                onClick={() => setShowAdvancedSettings(!showAdvancedSettings)}
                className="flex items-center justify-between w-full text-left"
              >
                <span className="font-medium text-gray-900">🔧 Advanced Settings</span>
                <svg
                  className={`w-4 h-4 transition-transform ${showAdvancedSettings ? 'rotate-180' : ''}`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {showAdvancedSettings && (
                <div className="mt-4 space-y-4">
                  {/* OCR Language */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      OCR Language
                    </label>
                    <select
                      value={processingOptions.ocr_settings.language}
                      onChange={(e) => onProcessingOptionsChange({
                        ...processingOptions,
                        ocr_settings: {
                          ...processingOptions.ocr_settings,
                          language: e.target.value
                        }
                      })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-blue-500 focus:border-blue-500 text-sm"
                    >
                      <option value="en">English</option>
                      <option value="eng+spa">English + Spanish</option>
                      <option value="fra">French</option>
                      <option value="deu">German</option>
                      <option value="chi_sim">Chinese (Simplified)</option>
                    </select>
                  </div>
                </div>
              )}
            </div>

            {/* Configuration Tips */}
            <div className="mt-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
              <h5 className="font-medium text-blue-900 mb-2">💡 Configuration Tips</h5>
              <ul className="text-xs text-blue-800 space-y-1">
                <li>• Higher thresholds ensure better quality but may reject more documents</li>
                <li>• Vector optimization restructures content for semantic search</li>
                <li>• Adjust thresholds based on your quality requirements</li>
              </ul>
            </div>
          </div>
        </div>

        {/* Right Panel - File Selection */}
        <div className="lg:col-span-3 flex flex-col min-h-0">
          <div className="bg-white rounded-lg border p-6 flex-1 flex flex-col">
            {/* Source Type Switcher */}
            <div className="flex space-x-2 bg-gray-100 p-1 rounded-lg mb-6">
              <button
                type="button"
                onClick={() => onSourceTypeChange('local')}
                className={`flex-1 px-4 py-2 rounded-md transition-colors ${
                  sourceType === 'local'
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                📂 Local Documents
              </button>
              <button
                type="button"
                onClick={() => onSourceTypeChange('upload')}
                className={`flex-1 px-4 py-2 rounded-md transition-colors ${
                  sourceType === 'upload'
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                ⬆️ Upload Documents
              </button>
            </div>

            {/* Content based on source type */}
            <div className="flex-1 flex flex-col min-h-0">
              {sourceType === 'local' ? (
                <div className="flex-1 flex flex-col">
                  <div className="mb-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
                    <p className="text-sm text-blue-800">
                      <strong>Local Files:</strong> Place documents in the <code className="bg-blue-100 px-1 rounded">files/batch_files/</code> folder and click refresh.
                    </p>
                  </div>
                  <div className="flex-1 overflow-hidden">
                    {renderFileList(batchFiles, 'Local Files')}
                  </div>
                </div>
              ) : (
                <div className="flex-1 flex flex-col space-y-6">
                  {/* Upload Area */}
                  <div
                    className={`relative border-2 border-dashed rounded-xl p-8 text-center transition-colors flex-shrink-0 ${
                      dragActive
                        ? 'border-blue-400 bg-blue-50'
                        : 'border-gray-300 hover:border-gray-400'
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
                    
                    <div className="space-y-4">
                      <div className="text-6xl">📄</div>
                      <div>
                        <p className="text-lg font-medium text-gray-700">
                          {isUploading ? 'Uploading...' : 'Drop files here or click to browse'}
                        </p>
                        <p className="text-sm text-gray-500 mt-1">
                          Supported: {supportedFormats.join(', ')} • Max: {utils.formatFileSize(maxFileSize)}
                        </p>
                      </div>
                    </div>

                    {isUploading && (
                      <div className="absolute inset-0 bg-white bg-opacity-75 flex items-center justify-center">
                        <div className="flex items-center space-x-2">
                          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600"></div>
                          <span className="text-blue-600">Uploading files...</span>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Uploaded Files List */}
                  <div className="flex-1 overflow-hidden">
                    {renderFileList(uploadedFiles, 'Uploaded Files')}
                  </div>
                </div>
              )}
            </div>

            {/* Process Button */}
            <div className="border-t pt-6 mt-6 flex-shrink-0">
              <div className="flex items-center justify-between">
                <div>
                  {selectedFiles.length > 0 && (
                    <p className="text-sm text-gray-600">
                      {selectedFiles.length} file(s) selected for processing
                      {sourceType === 'local' && (
                        <span className="ml-2 text-blue-600">(from batch files)</span>
                      )}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={handleProcess}
                  disabled={selectedFiles.length === 0 || isProcessing}
                  className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium"
                >
                  {isProcessing ? (
                    <span className="flex items-center space-x-2">
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                      <span>Processing...</span>
                    </span>
                  ) : (
                    `🚀 Process ${selectedFiles.length} File(s)`
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};