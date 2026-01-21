'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth-context'
import { jobsApi } from '@/lib/api'
import { FileInfo, ProcessingOptions } from '@/types'
import toast from 'react-hot-toast'
import { X, ArrowLeft, ArrowRight, CheckCircle } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { FileSelector } from './FileSelector'
import { OptionsEditor } from './OptionsEditor'
import { getDefaultJobName } from '@/lib/job-naming'

interface CreateJobPanelProps {
  isOpen: boolean
  onClose: () => void
  onJobCreated?: (jobId: string) => void
}

type WizardStep = 'select' | 'configure' | 'review'

export function CreateJobPanel({ isOpen, onClose, onJobCreated }: CreateJobPanelProps) {
  const router = useRouter()
  const { accessToken } = useAuth()

  const [currentStep, setCurrentStep] = useState<WizardStep>('select')
  const [selectedFiles, setSelectedFiles] = useState<FileInfo[]>([])
  const [jobName, setJobName] = useState('')
  const [jobDescription, setJobDescription] = useState('')
  const [processingOptions, setProcessingOptions] = useState<ProcessingOptions>({
    quality_thresholds: {
      conversion_threshold: 70.0,
      clarity_threshold: 7.0,
      completeness_threshold: 8.0,
      relevance_threshold: 6.0,
      markdown_threshold: 7.0
    },
    ocr_settings: {
      enabled: true,
      language: 'eng',
      confidence_threshold: 0.8,
      psm: 3
    },
    processing_settings: {
      chunk_size: 1000,
      chunk_overlap: 200,
      max_retries: 3
    },
    auto_optimize: true,
    extraction_engine: '' // Will be set by OptionsEditor from available connections
  })
  const [isCreating, setIsCreating] = useState(false)

  if (!isOpen) return null

  const handleClose = () => {
    if (!isCreating) {
      onClose()
      // Reset state
      setCurrentStep('select')
      setSelectedFiles([])
      setJobName('')
      setJobDescription('')
    }
  }

  const handleNext = () => {
    if (currentStep === 'select') {
      if (selectedFiles.length === 0) {
        toast.error('Please select at least one document')
        return
      }
      if (!jobName.trim()) {
        setJobName(getDefaultJobName(selectedFiles))
      }
      setCurrentStep('configure')
    } else if (currentStep === 'configure') {
      setCurrentStep('review')
    }
  }

  const handleBack = () => {
    if (currentStep === 'configure') {
      setCurrentStep('select')
    } else if (currentStep === 'review') {
      setCurrentStep('configure')
    }
  }

  const handleCreateJob = async () => {
    if (!accessToken) {
      toast.error('Authentication required')
      return
    }

    if (selectedFiles.length === 0) {
      toast.error('No documents selected')
      return
    }

    setIsCreating(true)
    try {
      const documentIds = selectedFiles.map(f => f.document_id)

      const job = await jobsApi.createJob(accessToken, {
        document_ids: documentIds,
        options: processingOptions,
        name: jobName.trim() || getDefaultJobName(selectedFiles),
        description: jobDescription || undefined,
        start_immediately: true
      })

      toast.success(`Job created: ${job.name}`)

      if (onJobCreated) {
        onJobCreated(job.id)
      } else {
        router.push(`/jobs/${job.id}`)
      }

      onClose()
    } catch (error: any) {
      console.error('Failed to create job:', error)
      toast.error(`Failed to create job: ${error.message || 'Unknown error'}`)
    } finally {
      setIsCreating(false)
    }
  }

  const getStepTitle = () => {
    switch (currentStep) {
      case 'select':
        return 'Select Documents'
      case 'configure':
        return 'Configure Options'
      case 'review':
        return 'Review & Create'
      default:
        return ''
    }
  }

  const defaultJobName = getDefaultJobName(selectedFiles)

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
        onClick={handleClose}
      />

      {/* Panel */}
      <div className="flex min-h-full items-center justify-center p-4">
        <div className="relative bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between p-6 border-b border-gray-200">
            <div>
              <h2 className="text-2xl font-bold text-gray-900">Create Batch Job</h2>
              <p className="mt-1 text-sm text-gray-600">{getStepTitle()}</p>
            </div>
            <button
              onClick={handleClose}
              disabled={isCreating}
              className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
            >
              <X className="w-6 h-6" />
            </button>
          </div>

          {/* Progress Indicator */}
          <div className="px-6 pt-4">
            <div className="flex items-center justify-between">
              <div className={`flex items-center ${currentStep === 'select' ? 'text-blue-600' : 'text-gray-400'}`}>
                <div className={`w-8 h-8 rounded-full flex items-center justify-center border-2 ${
                  currentStep === 'select' ? 'border-blue-600 bg-blue-50' : 'border-gray-300'
                }`}>
                  1
                </div>
                <span className="ml-2 text-sm font-medium">Select</span>
              </div>

              <div className={`flex-1 h-0.5 mx-4 ${
                currentStep !== 'select' ? 'bg-blue-600' : 'bg-gray-300'
              }`} />

              <div className={`flex items-center ${currentStep === 'configure' ? 'text-blue-600' : 'text-gray-400'}`}>
                <div className={`w-8 h-8 rounded-full flex items-center justify-center border-2 ${
                  currentStep === 'configure' ? 'border-blue-600 bg-blue-50' :
                  currentStep === 'review' ? 'border-blue-600' : 'border-gray-300'
                }`}>
                  2
                </div>
                <span className="ml-2 text-sm font-medium">Configure</span>
              </div>

              <div className={`flex-1 h-0.5 mx-4 ${
                currentStep === 'review' ? 'bg-blue-600' : 'bg-gray-300'
              }`} />

              <div className={`flex items-center ${currentStep === 'review' ? 'text-blue-600' : 'text-gray-400'}`}>
                <div className={`w-8 h-8 rounded-full flex items-center justify-center border-2 ${
                  currentStep === 'review' ? 'border-blue-600 bg-blue-50' : 'border-gray-300'
                }`}>
                  3
                </div>
                <span className="ml-2 text-sm font-medium">Review</span>
              </div>
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto p-6">
            {currentStep === 'select' && (
              <div>
                <p className="text-sm text-gray-600 mb-4">
                  Select documents to include in this batch job. You can upload new files or choose from existing documents.
                </p>
                <FileSelector
                  selectedFiles={selectedFiles}
                  onSelectedFilesChange={setSelectedFiles}
                />
              </div>
            )}

            {currentStep === 'configure' && (
              <div>
                <div className="mb-6">
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Job Name *
                  </label>
                  <input
                    type="text"
                    value={jobName}
                    onChange={(e) => setJobName(e.target.value)}
                    placeholder={defaultJobName}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div className="mb-6">
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Description (Optional)
                  </label>
                  <textarea
                    value={jobDescription}
                    onChange={(e) => setJobDescription(e.target.value)}
                    placeholder="Add a description for this job..."
                    rows={3}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div className="border-t border-gray-200 pt-6">
                  <h3 className="text-lg font-semibold text-gray-900 mb-4">Processing Options</h3>
                  <OptionsEditor
                    options={processingOptions}
                    onChange={setProcessingOptions}
                  />
                </div>
              </div>
            )}

            {currentStep === 'review' && (
              <div>
                <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
                  <div className="flex items-center">
                    <CheckCircle className="w-5 h-5 text-blue-600 mr-2" />
                    <p className="text-sm text-blue-800">
                      Review your job configuration before creating
                    </p>
                  </div>
                </div>

                <div className="space-y-6">
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900 mb-2">Job Details</h3>
                    <div className="bg-gray-50 rounded-lg p-4 space-y-2">
                      <div className="flex justify-between">
                        <span className="text-sm text-gray-600">Name:</span>
                        <span className="text-sm font-medium text-gray-900">
                          {jobName.trim() || defaultJobName}
                        </span>
                      </div>
                      {jobDescription && (
                        <div className="flex justify-between">
                          <span className="text-sm text-gray-600">Description:</span>
                          <span className="text-sm font-medium text-gray-900 text-right max-w-md">
                            {jobDescription}
                          </span>
                        </div>
                      )}
                      <div className="flex justify-between">
                        <span className="text-sm text-gray-600">Documents:</span>
                        <span className="text-sm font-medium text-gray-900">
                          {selectedFiles.length} selected
                        </span>
                      </div>
                    </div>
                  </div>

                  <div>
                    <h3 className="text-lg font-semibold text-gray-900 mb-2">Processing Options</h3>
                    <div className="bg-gray-50 rounded-lg p-4 space-y-2">
                      <div className="flex justify-between">
                        <span className="text-sm text-gray-600">Conversion Threshold:</span>
                        <span className="text-sm font-medium text-gray-900">
                          {processingOptions.quality_thresholds.conversion_threshold}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-sm text-gray-600">Auto-optimize:</span>
                        <span className="text-sm font-medium text-gray-900">
                          {processingOptions.auto_optimize ? 'Enabled' : 'Disabled'}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-sm text-gray-600">Extraction Engine:</span>
                        <span className="text-sm font-medium text-gray-900">
                          {processingOptions.extraction_engine ?? 'extraction-service'}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-sm text-gray-600">OCR:</span>
                        <span className="text-sm font-medium text-gray-900">
                          {processingOptions.ocr_settings.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div>
                    <h3 className="text-lg font-semibold text-gray-900 mb-2">Selected Documents</h3>
                    <div className="bg-gray-50 rounded-lg p-4 max-h-60 overflow-y-auto">
                      {selectedFiles.length === 0 ? (
                        <p className="text-sm text-gray-500">No documents selected</p>
                      ) : (
                        <ul className="space-y-2">
                          {selectedFiles.map((file, index) => (
                            <li key={file.document_id} className="text-sm text-gray-700">
                              {index + 1}. {file.filename}
                              <span className="text-gray-400 ml-2">
                                ({(file.size / 1024).toFixed(1)} KB)
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between p-6 border-t border-gray-200">
            <Button
              variant="ghost"
              onClick={handleBack}
              disabled={currentStep === 'select' || isCreating}
            >
              <ArrowLeft className="w-4 h-4 mr-2" />
              Back
            </Button>

            <div className="flex gap-3">
              <Button
                variant="outline"
                onClick={handleClose}
                disabled={isCreating}
              >
                Cancel
              </Button>

              {currentStep !== 'review' ? (
                <Button onClick={handleNext}>
                  Next
                  <ArrowRight className="w-4 h-4 ml-2" />
                </Button>
              ) : (
                <Button
                  onClick={handleCreateJob}
                  disabled={isCreating || selectedFiles.length === 0}
                >
                  {isCreating ? 'Creating...' : 'Create Job'}
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
