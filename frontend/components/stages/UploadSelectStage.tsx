// frontend/components/stages/UploadSelectStage.tsx
'use client'

import { useState, useRef, useCallback, useEffect } from 'react';
import { FileInfo, ProcessingOptions } from '@/types';
import { fileApi, utils } from '@/lib/api';

interface UploadSelectStageProps {
  sourceType: 'local' | 'upload';
  onSourceTypeChange: (type: 'local' | 'upload') => void;
  selectedFiles: FileInfo[];
  onSelectedFilesChange: (files: FileInfo[]) => void;
  onProcess: (files: FileInfo[], options: ProcessingOptions) => void;
  supportedFormats: string[];
  maxFileSize: number;
  processingOptions: ProcessingOptions;
  onProcessingOptionsChange: (options: ProcessingOptions) => void;
  isProcessing: boolean;
}

export function UploadSelectStage({
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
}: UploadSelectStageProps) {
  const [uploadedFiles, setUploadedFiles] = useState<FileInfo[]>([]);
  const [batchFiles, setBatchFiles] = useState<FileInfo[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load files when source type changes
  useEffect(() => {
    if (sourceType === 'upload') {
      loadUploadedFiles();
    } else {
      loadBatchFiles();
    }
  }, [sourceType]);

  // Load uploaded files
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

  // Load batch files
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

  // Handle file upload
  const handleFileUpload = async (files: File[]) => {
    setIsUploading(true);
    const uploadedFileIds: FileInfo[] = [];

    for (const file of files) {
      try {
        // Validate file
        if (!supportedFormats.includes('.' + file.name.split('.').pop()?.toLowerCase())) {
          alert(`Unsupported file type: ${file.name}`);
          continue;
        }

        if (file.size > maxFileSize) {
          alert(`File too large: ${file.name} (${utils.formatFileSize(file.size)})`);
          continue;
        }

        const result = await fileApi.uploadFile(file);
        uploadedFileIds.push({
          document_id: result.document_id,
          filename: result.filename,
          original_filename: result.filename,
          file_size: result.file_size,
          upload_time: new Date(result.upload_time).getTime(),
          file_path: ''
        });
      } catch (error) {
        console.error(`Failed to upload ${file.name}:`, error);
        const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred';
        alert(`Failed to upload ${file.name}: ${errorMessage}`);
      }
    }

    if (uploadedFileIds.length > 0) {
      await loadUploadedFiles();
      // Auto-select uploaded files
      onSelectedFilesChange([...selectedFiles, ...uploadedFileIds]);
    }

    setIsUploading(false);
  };

  // Drag and drop handlers
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    const files = Array.from(e.dataTransfer.files);
    handleFileUpload(files);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const files = Array.from(e.target.files);
      handleFileUpload(files);
    }
  };

  // File selection handlers
  const handleFileToggle = (file: FileInfo, checked: boolean) => {
    if (checked) {
      onSelectedFilesChange([...selectedFiles, file]);
    } else {
      onSelectedFilesChange(selectedFiles.filter(f => f.document_id !== file.document_id));
    }
  };

  const handleSelectAll = (files: FileInfo[], checked: boolean) => {
    if (checked) {
      const newFiles = files.filter(f => !selectedFiles.some(sf => sf.document_id === f.document_id));
      onSelectedFilesChange([...selectedFiles, ...newFiles]);
    } else {
      const fileIds = files.map(f => f.document_id);
      onSelectedFilesChange(selectedFiles.filter(f => !fileIds.includes(f.document_id)));
    }
  };

  const handleProcess = () => {
    if (selectedFiles.length === 0) {
      alert('Please select files to process');
      return;
    }
    onProcess(selectedFiles, processingOptions);
  };

  // Get current file list based on source type
  const getCurrentFiles = () => {
    return sourceType === 'upload' ? uploadedFiles : batchFiles;
  };

  // Render file list
  const renderFileList = (files: FileInfo[], title: string) => {
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

  const currentFiles = getCurrentFiles();

  return (
    <div className="space-y-6">
      {/* Source Type Switcher */}
      <div className="flex space-x-2 bg-gray-100 p-1 rounded-lg">
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
      {sourceType === 'local' ? (
        <div>
          <div className="mb-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
            <p className="text-sm text-blue-800">
              <strong>Local Files:</strong> Place documents in the <code className="bg-blue-100 px-1 rounded">files/batch_files/</code> folder and click refresh.
            </p>
          </div>
          {renderFileList(batchFiles, 'Local Files')}
        </div>
      ) : (
        <div className="space-y-6">
          {/* Upload Area */}
          <div
            className={`relative border-2 border-dashed rounded-xl p-8 text-center transition-colors ${
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
          {renderFileList(uploadedFiles, 'Uploaded Files')}
        </div>
      )}

      {/* Processing Options */}
      <div className="border-t pt-6">
        <h3 className="text-lg font-medium mb-4">⚙️ Processing Options</h3>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Auto Optimize */}
          <div>
            <label className="flex items-center space-x-3">
              <input
                type="checkbox"
                checked={processingOptions.auto_optimize}
                onChange={(e) => onProcessingOptionsChange({
                  ...processingOptions,
                  auto_optimize: e.target.checked
                })}
                className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <div>
                <span className="font-medium">🎯 Vector DB Optimization</span>
                <p className="text-sm text-gray-600">Automatically optimize for vector databases</p>
              </div>
            </label>
          </div>

          {/* Quality Thresholds */}
          <div>
            <h4 className="font-medium mb-2">📊 Quality Thresholds</h4>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div>
                <label className="block text-gray-600">Conversion</label>
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={processingOptions.quality_thresholds.conversion}
                  onChange={(e) => onProcessingOptionsChange({
                    ...processingOptions,
                    quality_thresholds: {
                      ...processingOptions.quality_thresholds,
                      conversion: parseInt(e.target.value) || 0
                    }
                  })}
                  className="w-full px-2 py-1 border border-gray-300 rounded"
                />
              </div>
              <div>
                <label className="block text-gray-600">Clarity</label>
                <input
                  type="number"
                  min="1"
                  max="10"
                  value={processingOptions.quality_thresholds.clarity}
                  onChange={(e) => onProcessingOptionsChange({
                    ...processingOptions,
                    quality_thresholds: {
                      ...processingOptions.quality_thresholds,
                      clarity: parseInt(e.target.value) || 1
                    }
                  })}
                  className="w-full px-2 py-1 border border-gray-300 rounded"
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Process Button */}
      <div className="border-t pt-6">
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
  );
}