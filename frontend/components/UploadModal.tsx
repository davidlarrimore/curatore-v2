'use client'

import { useState, useRef, useCallback, DragEvent } from 'react'
import { Button } from './ui/Button'
import {
  X,
  Upload,
  FileText,
  CheckCircle,
  AlertTriangle,
  RefreshCw,
  Loader2,
  Trash2,
  FolderOpen,
} from 'lucide-react'
import { assetsApi, type BulkUploadAnalysis } from '@/lib/api'

interface UploadModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess?: () => void
  token: string | undefined
}

export default function UploadModal({
  isOpen,
  onClose,
  onSuccess,
  token,
}: UploadModalProps) {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [analysis, setAnalysis] = useState<BulkUploadAnalysis | null>(null)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState('')
  const [step, setStep] = useState<'select' | 'preview' | 'uploading' | 'complete'>('select')
  const [isDragOver, setIsDragOver] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const acceptedFormats = '.pdf,.doc,.docx,.txt,.md,.ppt,.pptx,.xls,.xlsx,.png,.jpg,.jpeg,.gif,.webp'

  const handleDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(false)
  }, [])

  const handleDrop = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(false)

    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) {
      addFiles(files)
    }
  }, [])

  const addFiles = (newFiles: File[]) => {
    setSelectedFiles(prev => {
      // Filter out duplicates by name
      const existingNames = new Set(prev.map(f => f.name))
      const uniqueNewFiles = newFiles.filter(f => !existingNames.has(f.name))
      return [...prev, ...uniqueNewFiles]
    })
    setError('')
  }

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files
    if (files && files.length > 0) {
      addFiles(Array.from(files))
    }
    // Reset input so same file can be selected again
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const removeFile = (index: number) => {
    setSelectedFiles(prev => prev.filter((_, i) => i !== index))
  }

  const clearAllFiles = () => {
    setSelectedFiles([])
    setAnalysis(null)
    setStep('select')
  }

  const handleAnalyze = async () => {
    if (selectedFiles.length === 0 || !token) {
      setError('Please select files to upload')
      return
    }

    setIsAnalyzing(true)
    setError('')

    try {
      const result = await assetsApi.previewBulkUpload(token, selectedFiles)
      setAnalysis(result)
      setStep('preview')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to analyze files. Please try again.')
    } finally {
      setIsAnalyzing(false)
    }
  }

  const handleUpload = async () => {
    if (!analysis || selectedFiles.length === 0 || !token) return

    setIsUploading(true)
    setStep('uploading')
    setError('')
    setUploadProgress(0)

    try {
      // Simulate progress for better UX
      const progressInterval = setInterval(() => {
        setUploadProgress(prev => Math.min(prev + 10, 90))
      }, 200)

      await assetsApi.applyBulkUpload(token, selectedFiles, 'upload', true)

      clearInterval(progressInterval)
      setUploadProgress(100)
      setStep('complete')

      // Auto-close after success
      setTimeout(() => {
        handleClose()
        onSuccess?.()
      }, 1500)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to upload files. Please try again.')
      setStep('preview')
    } finally {
      setIsUploading(false)
    }
  }

  const handleClose = () => {
    setSelectedFiles([])
    setAnalysis(null)
    setStep('select')
    setError('')
    setUploadProgress(0)
    onClose()
  }

  const handleBack = () => {
    setStep('select')
    setAnalysis(null)
    setError('')
  }

  const formatBytes = (bytes: number) => {
    const sizes = ['Bytes', 'KB', 'MB', 'GB']
    if (bytes === 0) return '0 Bytes'
    const i = Math.floor(Math.log(bytes) / Math.log(1024))
    return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${sizes[i]}`
  }

  const getTotalSize = () => {
    return selectedFiles.reduce((acc, file) => acc + file.size, 0)
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm transition-opacity"
        onClick={handleClose}
      />

      {/* Modal */}
      <div className="flex min-h-full items-center justify-center p-4">
        <div className="relative bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-2xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          {/* Header */}
          <div className="relative bg-gradient-to-r from-indigo-600 via-purple-600 to-indigo-600 px-6 py-5">
            <button
              onClick={handleClose}
              className="absolute top-4 right-4 p-2 rounded-lg text-white/80 hover:text-white hover:bg-white/10 transition-all"
            >
              <X className="w-5 h-5" />
            </button>
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-white/10 backdrop-blur-sm flex items-center justify-center">
                <Upload className="w-6 h-6 text-white" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-white">Upload Documents</h2>
                <p className="text-indigo-100 text-sm mt-0.5">
                  {step === 'select' && 'Drag and drop files or click to browse'}
                  {step === 'preview' && 'Review and confirm your upload'}
                  {step === 'uploading' && 'Uploading files...'}
                  {step === 'complete' && 'Upload complete!'}
                </p>
              </div>
            </div>
          </div>

          {/* Content */}
          <div className="p-6">
            {/* Error Message */}
            {error && (
              <div className="mb-4 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
                <div className="flex items-center gap-3">
                  <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0" />
                  <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
                </div>
              </div>
            )}

            {/* Step 1: Select Files */}
            {step === 'select' && (
              <div className="space-y-4">
                {/* Drop Zone */}
                <div
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                  className={`relative rounded-xl border-2 border-dashed transition-all cursor-pointer ${
                    isDragOver
                      ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                      : 'border-gray-300 dark:border-gray-600 hover:border-indigo-400 dark:hover:border-indigo-500 bg-gray-50 dark:bg-gray-900/50'
                  }`}
                >
                  <div className="px-6 py-10 text-center">
                    <div className={`mx-auto w-16 h-16 rounded-xl flex items-center justify-center mb-4 transition-all ${
                      isDragOver
                        ? 'bg-indigo-500 scale-110'
                        : 'bg-gradient-to-br from-indigo-500 to-purple-600'
                    }`}>
                      <Upload className="w-8 h-8 text-white" />
                    </div>
                    <p className="text-base font-medium text-gray-900 dark:text-white mb-1">
                      {isDragOver ? 'Drop files here' : 'Drag and drop files here'}
                    </p>
                    <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                      or click to browse from your computer
                    </p>
                    <div className="flex items-center justify-center gap-2 text-xs text-gray-400 dark:text-gray-500">
                      <FolderOpen className="w-4 h-4" />
                      <span>PDF, Word, PowerPoint, Excel, Images, Text</span>
                    </div>
                  </div>
                </div>

                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  onChange={handleFileSelect}
                  className="hidden"
                  accept={acceptedFormats}
                />

                {/* Selected Files List */}
                {selectedFiles.length > 0 && (
                  <div className="bg-white dark:bg-gray-900/50 rounded-xl border border-gray-200 dark:border-gray-700">
                    <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700">
                      <div className="flex items-center gap-3">
                        <span className="text-sm font-medium text-gray-900 dark:text-white">
                          {selectedFiles.length} file{selectedFiles.length !== 1 ? 's' : ''} selected
                        </span>
                        <span className="text-xs text-gray-500 dark:text-gray-400">
                          ({formatBytes(getTotalSize())})
                        </span>
                      </div>
                      <button
                        onClick={(e) => { e.stopPropagation(); clearAllFiles(); }}
                        className="text-xs text-gray-500 hover:text-red-600 dark:text-gray-400 dark:hover:text-red-400 transition-colors"
                      >
                        Clear all
                      </button>
                    </div>
                    <div className="max-h-48 overflow-y-auto p-2 space-y-1">
                      {selectedFiles.map((file, index) => (
                        <div
                          key={`${file.name}-${index}`}
                          className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 group"
                        >
                          <FileText className="w-4 h-4 text-indigo-600 dark:text-indigo-400 flex-shrink-0" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm text-gray-900 dark:text-white truncate">
                              {file.name}
                            </p>
                          </div>
                          <span className="text-xs text-gray-500 dark:text-gray-400">
                            {formatBytes(file.size)}
                          </span>
                          <button
                            onClick={(e) => { e.stopPropagation(); removeFile(index); }}
                            className="p-1 rounded text-gray-400 hover:text-red-600 dark:hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Actions */}
                <div className="flex items-center gap-3 pt-2">
                  <Button
                    variant="secondary"
                    onClick={handleClose}
                    className="flex-1"
                  >
                    Cancel
                  </Button>
                  <Button
                    onClick={handleAnalyze}
                    disabled={selectedFiles.length === 0 || isAnalyzing}
                    className="flex-1 gap-2"
                  >
                    {isAnalyzing ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Analyzing...
                      </>
                    ) : (
                      <>
                        <Upload className="w-4 h-4" />
                        Upload {selectedFiles.length > 0 ? `(${selectedFiles.length})` : ''}
                      </>
                    )}
                  </Button>
                </div>
              </div>
            )}

            {/* Step 2: Preview Changes */}
            {step === 'preview' && analysis && (
              <div className="space-y-4">
                {/* Summary Cards */}
                <div className="grid grid-cols-4 gap-3">
                  <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-lg p-3 text-center">
                    <p className="text-2xl font-bold text-emerald-600 dark:text-emerald-400">
                      {analysis.counts.new}
                    </p>
                    <p className="text-xs text-emerald-700 dark:text-emerald-300">New</p>
                  </div>
                  <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-3 text-center">
                    <p className="text-2xl font-bold text-blue-600 dark:text-blue-400">
                      {analysis.counts.updated}
                    </p>
                    <p className="text-xs text-blue-700 dark:text-blue-300">Updated</p>
                  </div>
                  <div className="bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-3 text-center">
                    <p className="text-2xl font-bold text-gray-600 dark:text-gray-400">
                      {analysis.counts.unchanged}
                    </p>
                    <p className="text-xs text-gray-600 dark:text-gray-400">Unchanged</p>
                  </div>
                  <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-3 text-center">
                    <p className="text-2xl font-bold text-amber-600 dark:text-amber-400">
                      {analysis.counts.missing}
                    </p>
                    <p className="text-xs text-amber-700 dark:text-amber-300">Missing</p>
                  </div>
                </div>

                {/* Changes List */}
                {(analysis.new.length > 0 || analysis.updated.length > 0) && (
                  <div className="bg-white dark:bg-gray-900/50 rounded-xl border border-gray-200 dark:border-gray-700 max-h-48 overflow-y-auto">
                    <div className="p-3 space-y-1">
                      {analysis.new.map((file, index) => (
                        <div key={index} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-emerald-50 dark:bg-emerald-900/10">
                          <CheckCircle className="w-4 h-4 text-emerald-600 dark:text-emerald-400 flex-shrink-0" />
                          <span className="text-sm text-gray-900 dark:text-white truncate flex-1">{file.filename}</span>
                          <span className="text-xs text-emerald-600 dark:text-emerald-400">New</span>
                        </div>
                      ))}
                      {analysis.updated.map((file, index) => (
                        <div key={index} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-blue-50 dark:bg-blue-900/10">
                          <RefreshCw className="w-4 h-4 text-blue-600 dark:text-blue-400 flex-shrink-0" />
                          <span className="text-sm text-gray-900 dark:text-white truncate flex-1">{file.filename}</span>
                          <span className="text-xs text-blue-600 dark:text-blue-400">Update</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* No changes message */}
                {analysis.counts.new === 0 && analysis.counts.updated === 0 && (
                  <div className="text-center py-6 text-gray-500 dark:text-gray-400">
                    <CheckCircle className="w-12 h-12 mx-auto mb-3 text-gray-300 dark:text-gray-600" />
                    <p className="text-sm">All files are already up to date.</p>
                  </div>
                )}

                {/* Actions */}
                <div className="flex items-center gap-3 pt-2">
                  <Button
                    variant="secondary"
                    onClick={handleBack}
                    className="flex-1"
                  >
                    Back
                  </Button>
                  <Button
                    onClick={handleUpload}
                    disabled={analysis.counts.new === 0 && analysis.counts.updated === 0}
                    className="flex-1 gap-2"
                  >
                    <CheckCircle className="w-4 h-4" />
                    Confirm Upload
                  </Button>
                </div>
              </div>
            )}

            {/* Step 3: Uploading */}
            {step === 'uploading' && (
              <div className="py-8 text-center">
                <div className="w-16 h-16 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin mx-auto mb-4"></div>
                <p className="text-sm font-medium text-gray-900 dark:text-white mb-2">
                  Uploading files...
                </p>
                <div className="w-48 h-2 bg-gray-200 dark:bg-gray-700 rounded-full mx-auto overflow-hidden">
                  <div
                    className="h-full bg-indigo-500 rounded-full transition-all duration-300"
                    style={{ width: `${uploadProgress}%` }}
                  ></div>
                </div>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">
                  {uploadProgress}% complete
                </p>
              </div>
            )}

            {/* Step 4: Complete */}
            {step === 'complete' && (
              <div className="py-8 text-center">
                <div className="mx-auto w-16 h-16 rounded-full bg-gradient-to-br from-emerald-500 to-emerald-600 flex items-center justify-center mb-4">
                  <CheckCircle className="w-8 h-8 text-white" />
                </div>
                <p className="text-lg font-semibold text-gray-900 dark:text-white mb-1">
                  Upload Complete!
                </p>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Your files are being processed.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
