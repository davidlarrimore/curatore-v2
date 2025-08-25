// app/process/page.tsx
'use client'

import { useState, useEffect } from 'react'
import toast from 'react-hot-toast'
import { 
  ProcessingStage, 
  ProcessingState, 
  FileInfo, 
  ProcessingResult, 
  ProcessingOptions 
} from '@/types'
import { systemApi } from '@/lib/api'
import { UploadSelectStage } from '@/components/stages/UploadSelectStage'
import { ProcessingPanel } from '@/components/ProcessingPanel'
import { ReviewStage } from '@/components/stages/ReviewStage'
import { DownloadStage } from '@/components/stages/DownloadStage'
import { Button } from '@/components/ui/Button'
import { 
  Upload, 
  Eye, 
  Download, 
  CheckCircle2,
  Zap
} from 'lucide-react'

type AppStage = 'upload' | 'review' | 'download'

export default function ProcessPage() {
  // Remove all the header and navigation JSX - AppLayout handles this now
  // Keep your existing state and logic, but simplify the JSX structure

  const [currentStage, setCurrentStage] = useState<AppStage>('upload')
  // ... keep all your existing state logic

  return (
    <div className="h-full flex flex-col">
      {/* Stage Header - moved inside the main content area */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Document Processing Pipeline</h1>
            <p className="text-sm text-gray-600 mt-1">
              Transform documents into RAG-ready, semantically optimized content
            </p>
          </div>

          {/* Quick stats if available */}
          {state.processingResults.length > 0 && (
            <div className="flex items-center space-x-4 text-sm">
              <div className="flex items-center space-x-1">
                <CheckCircle2 className="w-4 h-4 text-green-600" />
                <span>{state.processingResults.filter(r => r.success).length} successful</span>
              </div>
              <div className="flex items-center space-x-1">
                <Zap className="w-4 h-4 text-purple-600" />
                <span>{state.processingResults.filter(r => r.pass_all_thresholds).length} RAG-ready</span>
              </div>
            </div>
          )}
        </div>

        {/* Progress Indicator */}
        <div className="mt-6">
          <nav aria-label="Progress">
            <ol className="flex items-center">
              {/* Keep your existing stage progress indicator */}
            </ol>
          </nav>
        </div>
      </div>

      {/* Main Content Area - Full height with proper overflow */}
      <div className="flex-1 overflow-auto">
        <div className="max-w-7xl mx-auto px-6 py-6">
          {/* Keep your existing stage components */}
          {currentStage === 'upload' && (
            <UploadSelectStage
              // ... all your existing props
            />
          )}

          {currentStage === 'review' && (
            <ReviewStage
              // ... all your existing props
            />
          )}

          {currentStage === 'download' && (
            <DownloadStage
              // ... all your existing props
            />
          )}
        </div>
      </div>

      {/* Keep your existing ProcessingPanel */}
      <ProcessingPanel
        // ... all your existing props
      />
    </div>
  )
}