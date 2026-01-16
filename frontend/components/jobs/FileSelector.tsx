'use client'

import { useState, useRef, useCallback, useEffect } from 'react'
import { FileInfo } from '@/types'
import { fileApi, utils } from '@/lib/api'
import { Upload, RefreshCw, FileText, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import toast from 'react-hot-toast'

interface FileSelectorProps {
  selectedFiles: FileInfo[]
  onSelectedFilesChange: (files: FileInfo[]) => void
  supportedFormats?: string[]
  maxFileSize?: number
}

export function FileSelector({
  selectedFiles,
  onSelectedFilesChange,
  supportedFormats = ['.pdf', '.docx', '.pptx', '.txt', '.png', '.jpg', '.jpeg'],
  maxFileSize = 52428800 // 50MB default
}: FileSelectorProps) {
  const [sourceType, setSourceType] = useState<'upload' | 'local'>('upload')
  const [uploadedFiles, setUploadedFiles] = useState<FileInfo[]>([])
  const [batchFiles, setBatchFiles] = useState<FileInfo[]>([])
  const [isUploading, setIsUploading] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Load files on mount and when source type changes
  useEffect(() => {
    loadFiles()
  }, [sourceType])

  const loadFiles = async () => {
    setIsRefreshing(true)
    try {
      if (sourceType === 'upload') {
        const response = await fileApi.listUploadedFiles()
        setUploadedFiles(response.files)
      } else {
        const response = await fileApi.listBatchFiles()
        setBatchFiles(response.files)
      }
    } catch (error) {
      console.error('Failed to load files:', error)
      toast.error('Failed to load files')
    } finally {
      setIsRefreshing(false)
    }
  }

  const handleFileUpload = async (files: File[]) => {
    setIsUploading(true)

    // Validate files
    const validFiles = files.filter(file => {
      const ext = `.${file.name.split('.').pop()?.toLowerCase()}`
      if (!supportedFormats.includes(ext)) {
        toast.error(`Unsupported file type: ${file.name}`)
        return false
      }
      if (file.size > maxFileSize) {
        toast.error(`File too large: ${file.name} (max ${utils.formatFileSize(maxFileSize)})`)
        return false
      }
      return true
    })

    if (validFiles.length === 0) {
      setIsUploading(false)
      return
    }

    // Upload files in parallel
    const uploadPromises = validFiles.map(file => fileApi.uploadFile(file))
    const results = await Promise.allSettled(uploadPromises)

    const successfulUploads: FileInfo[] = []
    results.forEach((result, index) => {
      if (result.status === 'fulfilled') {
        const uploadResult = result.value
        successfulUploads.push({
          document_id: uploadResult.document_id,
          filename: uploadResult.filename,
          original_filename: uploadResult.filename,
          file_size: uploadResult.file_size,
          upload_time: new Date(uploadResult.upload_time).getTime(),
          file_path: ''
        })
      } else {
        toast.error(`Failed to upload: ${validFiles[index].name}`)
      }
    })

    if (successfulUploads.length > 0) {
      toast.success(`Uploaded ${successfulUploads.length} file(s)`)
      // Auto-select newly uploaded files
      onSelectedFilesChange([...selectedFiles, ...successfulUploads])
      // Refresh file list
      await loadFiles()
    }

    setIsUploading(false)
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)

    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) {
      handleFileUpload(files)
    }
  }

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files && files.length > 0) {
      handleFileUpload(Array.from(files))
    }
    // Reset input value to allow re-selecting the same file
    e.target.value = ''
  }

  const handleFileSelect = (file: FileInfo) => {
    const isSelected = selectedFiles.some(f => f.document_id === file.document_id)
    if (isSelected) {
      onSelectedFilesChange(selectedFiles.filter(f => f.document_id !== file.document_id))
    } else {
      onSelectedFilesChange([...selectedFiles, file])
    }
  }

  const handleSelectAll = () => {
    const currentFiles = sourceType === 'upload' ? uploadedFiles : batchFiles
    onSelectedFilesChange(currentFiles)
  }

  const handleDeselectAll = () => {
    onSelectedFilesChange([])
  }

  const handleDeleteFile = async (file: FileInfo) => {
    if (sourceType !== 'upload') return

    const confirmed = window.confirm(`Delete ${file.filename}? This cannot be undone.`)
    if (!confirmed) return

    try {
      await fileApi.deleteDocument(file.document_id)
      toast.success('File deleted')
      // Remove from lists
      setUploadedFiles(prev => prev.filter(f => f.document_id !== file.document_id))
      onSelectedFilesChange(selectedFiles.filter(f => f.document_id !== file.document_id))
    } catch (error) {
      console.error('Failed to delete file:', error)
      toast.error('Failed to delete file')
    }
  }

  const currentFiles = sourceType === 'upload' ? uploadedFiles : batchFiles

  return (
    <div className="space-y-4">
      {/* Source Type Tabs */}
      <div className="flex gap-2 border-b border-gray-200">
        <button
          onClick={() => setSourceType('upload')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            sourceType === 'upload'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-600 hover:text-gray-900'
          }`}
        >
          Uploaded Files
        </button>
        <button
          onClick={() => setSourceType('local')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            sourceType === 'local'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-600 hover:text-gray-900'
          }`}
        >
          Batch Files
        </button>
      </div>

      {/* Upload Area (only for upload tab) */}
      {sourceType === 'upload' && (
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
            dragActive
              ? 'border-blue-500 bg-blue-50'
              : 'border-gray-300 hover:border-gray-400'
          }`}
        >
          <Upload className="w-12 h-12 mx-auto text-gray-400 mb-4" />
          <p className="text-sm text-gray-600 mb-2">
            Drag and drop files here, or click to browse
          </p>
          <p className="text-xs text-gray-400 mb-4">
            Supported formats: {supportedFormats.join(', ')}
            <br />
            Max size: {utils.formatFileSize(maxFileSize)}
          </p>
          <Button
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading}
          >
            {isUploading ? 'Uploading...' : 'Select Files'}
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={supportedFormats.join(',')}
            onChange={handleFileInputChange}
            className="hidden"
          />
        </div>
      )}

      {/* File List Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium text-gray-900">
            {sourceType === 'upload' ? 'Uploaded Files' : 'Batch Files'}
            <span className="ml-2 text-gray-500">
              ({currentFiles.length} available, {selectedFiles.length} selected)
            </span>
          </h3>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleSelectAll}
            disabled={currentFiles.length === 0}
          >
            Select All
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleDeselectAll}
            disabled={selectedFiles.length === 0}
          >
            Clear
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={loadFiles}
            disabled={isRefreshing}
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </div>

      {/* File List */}
      <div className="border border-gray-200 rounded-lg max-h-96 overflow-y-auto">
        {currentFiles.length === 0 ? (
          <div className="p-8 text-center text-gray-500">
            <FileText className="w-12 h-12 mx-auto text-gray-300 mb-2" />
            <p className="text-sm">
              {sourceType === 'upload'
                ? 'No uploaded files. Upload some files to get started.'
                : 'No batch files available.'}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-gray-200">
            {currentFiles.map((file) => {
              const isSelected = selectedFiles.some(f => f.document_id === file.document_id)
              return (
                <div
                  key={file.document_id}
                  className={`flex items-center gap-3 p-3 hover:bg-gray-50 transition-colors ${
                    isSelected ? 'bg-blue-50' : ''
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => handleFileSelect(file)}
                    className="w-4 h-4 text-blue-600 rounded focus:ring-2 focus:ring-blue-500"
                  />
                  <FileText className="w-5 h-5 text-gray-400 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {utils.getDisplayFilename(file.filename)}
                    </p>
                    <p className="text-xs text-gray-500">
                      {utils.formatFileSize(file.file_size)}
                      {file.upload_time && (
                        <> • {new Date(file.upload_time).toLocaleDateString()}</>
                      )}
                    </p>
                  </div>
                  {sourceType === 'upload' && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDeleteFile(file)
                      }}
                      className="text-gray-400 hover:text-red-600 transition-colors"
                      title="Delete file"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
