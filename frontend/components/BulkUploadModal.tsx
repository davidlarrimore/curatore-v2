'use client'

import { useState, useRef, useEffect } from 'react'
import { Button } from './ui/Button'
import {
  X,
  Upload,
  FileText,
  CheckCircle,
  AlertTriangle,
  RefreshCw,
  Loader2,
  ArrowRight,
} from 'lucide-react'
import { assetsApi, type BulkUploadAnalysis } from '@/lib/api'

interface BulkUploadModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess?: () => void
  token: string | undefined
  preselectedFiles?: File[]
}

export default function BulkUploadModal({
  isOpen,
  onClose,
  onSuccess,
  token,
  preselectedFiles,
}: BulkUploadModalProps) {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [analysis, setAnalysis] = useState<BulkUploadAnalysis | null>(null)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [isApplying, setIsApplying] = useState(false)
  const [error, setError] = useState('')
  const [step, setStep] = useState<'select' | 'preview' | 'complete'>('select')
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Auto-analyze when preselected files are provided
  useEffect(() => {
    if (isOpen && preselectedFiles && preselectedFiles.length > 0) {
      setSelectedFiles(preselectedFiles)
      setIsAnalyzing(true)
      setError('')

      assetsApi.previewBulkUpload(token, preselectedFiles)
        .then(result => {
          setAnalysis(result)
          setStep('preview')
        })
        .catch((err: unknown) => {
          setError(err instanceof Error ? err.message : 'Failed to analyze upload')
          setStep('select')
        })
        .finally(() => {
          setIsAnalyzing(false)
        })
    }
  }, [isOpen, preselectedFiles, token])

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files
    if (files && files.length > 0) {
      setSelectedFiles(Array.from(files))
      setError('')
    }
  }

  const handleAnalyze = async () => {
    if (selectedFiles.length === 0) {
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
      setError(err instanceof Error ? err.message : 'Failed to analyze upload')
    } finally {
      setIsAnalyzing(false)
    }
  }

  const handleApply = async () => {
    if (!analysis || selectedFiles.length === 0) return

    setIsApplying(true)
    setError('')

    try {
      await assetsApi.applyBulkUpload(token, selectedFiles, 'upload', true)
      setStep('complete')
      setTimeout(() => {
        handleClose()
        onSuccess?.()
      }, 2000)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to apply upload')
    } finally {
      setIsApplying(false)
    }
  }

  const handleClose = () => {
    setSelectedFiles([])
    setAnalysis(null)
    setStep('select')
    setError('')
    onClose()
  }

  const handleBack = () => {
    setStep('select')
    setAnalysis(null)
  }

  const formatBytes = (bytes: number) => {
    const sizes = ['Bytes', 'KB', 'MB', 'GB']
    if (bytes === 0) return '0 Bytes'
    const i = Math.floor(Math.log(bytes) / Math.log(1024))
    return `${(bytes / Math.pow(1024, i)).toFixed(2)} ${sizes[i]}`
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
        <div className="relative bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-4xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          {/* Gradient Header */}
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
                <h2 className="text-2xl font-bold text-white">Upload Files</h2>
                <p className="text-indigo-100 text-sm mt-0.5">
                  {step === 'select' && 'Select files to upload'}
                  {step === 'preview' && 'Review changes before uploading'}
                  {step === 'complete' && 'Upload complete!'}
                </p>
              </div>
            </div>
          </div>

          {/* Content */}
          <div className="p-6">
            {/* Error Message */}
            {error && (
              <div className="mb-6 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/50 p-4">
                <div className="flex items-center gap-3">
                  <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
                    <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
                  </div>
                  <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
                </div>
              </div>
            )}

            {/* Step 1: Select Files */}
            {step === 'select' && (
              <div className="space-y-6">
                <div
                  onClick={() => fileInputRef.current?.click()}
                  className="relative overflow-hidden rounded-2xl border-2 border-dashed border-gray-300 dark:border-gray-600 hover:border-indigo-500 dark:hover:border-indigo-500 bg-gray-50 dark:bg-gray-900/50 px-6 py-12 text-center cursor-pointer transition-all group"
                >
                  <div className="relative">
                    <div className="mx-auto w-20 h-20 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-xl shadow-indigo-500/25 mb-4 group-hover:scale-110 transition-transform">
                      <Upload className="w-10 h-10 text-white" />
                    </div>
                    <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                      Select files to upload
                    </h3>
                    <p className="text-gray-500 dark:text-gray-400 max-w-md mx-auto text-sm">
                      Choose multiple files or a folder. Files will be analyzed for changes before uploading.
                    </p>
                  </div>
                </div>

                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  onChange={handleFileSelect}
                  className="hidden"
                  accept=".pdf,.doc,.docx,.txt,.md,.ppt,.pptx,.xls,.xlsx,.png,.jpg,.jpeg"
                />

                {selectedFiles.length > 0 && (
                  <div className="bg-gray-50 dark:bg-gray-900/50 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                    <div className="flex items-center justify-between mb-3">
                      <p className="text-sm font-medium text-gray-900 dark:text-white">
                        {selectedFiles.length} file{selectedFiles.length > 1 ? 's' : ''} selected
                      </p>
                      <button
                        onClick={() => setSelectedFiles([])}
                        className="text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300"
                      >
                        Clear
                      </button>
                    </div>
                    <div className="max-h-48 overflow-y-auto space-y-2">
                      {selectedFiles.map((file, index) => (
                        <div
                          key={index}
                          className="flex items-center gap-3 p-2 rounded-lg bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700"
                        >
                          <FileText className="w-4 h-4 text-indigo-600 dark:text-indigo-400 flex-shrink-0" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                              {file.name}
                            </p>
                            <p className="text-xs text-gray-500 dark:text-gray-400">
                              {formatBytes(file.size)}
                            </p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="flex items-center gap-3">
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
                        <ArrowRight className="w-4 h-4" />
                        Analyze Changes
                      </>
                    )}
                  </Button>
                </div>
              </div>
            )}

            {/* Step 2: Preview Changes */}
            {step === 'preview' && analysis && (
              <div className="space-y-6">
                {/* Summary Cards */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <CheckCircle className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                      <p className="text-sm font-medium text-emerald-900 dark:text-emerald-100">New</p>
                    </div>
                    <p className="text-3xl font-bold text-emerald-600 dark:text-emerald-400">
                      {analysis.counts.new}
                    </p>
                    <p className="text-xs text-emerald-700 dark:text-emerald-300 mt-1">
                      Will be created
                    </p>
                  </div>

                  <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <RefreshCw className="w-5 h-5 text-blue-600 dark:text-blue-400" />
                      <p className="text-sm font-medium text-blue-900 dark:text-blue-100">Updated</p>
                    </div>
                    <p className="text-3xl font-bold text-blue-600 dark:text-blue-400">
                      {analysis.counts.updated}
                    </p>
                    <p className="text-xs text-blue-700 dark:text-blue-300 mt-1">
                      New versions
                    </p>
                  </div>

                  <div className="bg-gray-50 dark:bg-gray-900/20 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <CheckCircle className="w-5 h-5 text-gray-600 dark:text-gray-400" />
                      <p className="text-sm font-medium text-gray-900 dark:text-gray-100">Unchanged</p>
                    </div>
                    <p className="text-3xl font-bold text-gray-600 dark:text-gray-400">
                      {analysis.counts.unchanged}
                    </p>
                    <p className="text-xs text-gray-700 dark:text-gray-300 mt-1">
                      No changes
                    </p>
                  </div>

                  <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400" />
                      <p className="text-sm font-medium text-amber-900 dark:text-amber-100">Missing</p>
                    </div>
                    <p className="text-3xl font-bold text-amber-600 dark:text-amber-400">
                      {analysis.counts.missing}
                    </p>
                    <p className="text-xs text-amber-700 dark:text-amber-300 mt-1">
                      Mark inactive
                    </p>
                  </div>
                </div>

                {/* Details */}
                {(analysis.new.length > 0 || analysis.updated.length > 0 || analysis.missing.length > 0) && (
                  <div className="bg-white dark:bg-gray-900/50 rounded-xl border border-gray-200 dark:border-gray-700 p-4 max-h-64 overflow-y-auto">
                    <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-3">Changes</h3>
                    <div className="space-y-2">
                      {analysis.new.map((file, index) => (
                        <div key={index} className="flex items-center gap-3 p-2 rounded-lg bg-emerald-50 dark:bg-emerald-900/10 border border-emerald-200 dark:border-emerald-800">
                          <CheckCircle className="w-4 h-4 text-emerald-600 dark:text-emerald-400 flex-shrink-0" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                              {file.filename}
                            </p>
                            <p className="text-xs text-emerald-700 dark:text-emerald-300">
                              New file · {formatBytes(file.file_size)}
                            </p>
                          </div>
                        </div>
                      ))}
                      {analysis.updated.map((file, index) => (
                        <div key={index} className="flex items-center gap-3 p-2 rounded-lg bg-blue-50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-800">
                          <RefreshCw className="w-4 h-4 text-blue-600 dark:text-blue-400 flex-shrink-0" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                              {file.filename}
                            </p>
                            <p className="text-xs text-blue-700 dark:text-blue-300">
                              Updated · {formatBytes(file.file_size)}
                            </p>
                          </div>
                        </div>
                      ))}
                      {analysis.missing.map((file, index) => (
                        <div key={index} className="flex items-center gap-3 p-2 rounded-lg bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800">
                          <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 flex-shrink-0" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                              {file.filename}
                            </p>
                            <p className="text-xs text-amber-700 dark:text-amber-300">
                              Missing from upload · Will be marked inactive
                            </p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="flex items-center gap-3">
                  <Button
                    variant="secondary"
                    onClick={handleBack}
                    disabled={isApplying}
                    className="flex-1"
                  >
                    Back
                  </Button>
                  <Button
                    onClick={handleApply}
                    disabled={isApplying || (analysis.counts.new === 0 && analysis.counts.updated === 0 && analysis.counts.missing === 0)}
                    className="flex-1 gap-2"
                  >
                    {isApplying ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Applying...
                      </>
                    ) : (
                      <>
                        <CheckCircle className="w-4 h-4" />
                        Apply Changes
                      </>
                    )}
                  </Button>
                </div>
              </div>
            )}

            {/* Step 3: Complete */}
            {step === 'complete' && (
              <div className="text-center py-8">
                <div className="mx-auto w-20 h-20 rounded-2xl bg-gradient-to-br from-emerald-500 to-emerald-600 flex items-center justify-center shadow-xl shadow-emerald-500/25 mb-6">
                  <CheckCircle className="w-10 h-10 text-white" />
                </div>
                <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
                  Upload Complete!
                </h3>
                <p className="text-gray-500 dark:text-gray-400">
                  Your files have been uploaded and are being processed.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
