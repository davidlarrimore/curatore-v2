'use client'

import Link from 'next/link'
import { Button } from '@/components/ui/Button'
import {
  Building2,
  ExternalLink,
  Key,
  ArrowRight,
  Settings,
  CheckCircle,
} from 'lucide-react'

interface SamConnectionRequiredProps {
  className?: string
}

export default function SamConnectionRequired({ className = '' }: SamConnectionRequiredProps) {
  return (
    <div className={`min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950 ${className}`}>
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
        {/* Header */}
        <div className="text-center mb-12">
          <div className="mx-auto w-20 h-20 rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-xl shadow-blue-500/25 mb-6">
            <Building2 className="w-10 h-10 text-white" />
          </div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-3">
            SAM.gov API Connection Required
          </h1>
          <p className="text-lg text-gray-600 dark:text-gray-400 max-w-2xl mx-auto">
            To use SAM.gov features, you need to configure an API connection with your SAM.gov API key.
          </p>
        </div>

        {/* Steps */}
        <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-xl overflow-hidden mb-8">
          <div className="px-6 py-5 border-b border-gray-200 dark:border-gray-700 bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-900/20 dark:to-indigo-900/20">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              <Key className="w-5 h-5 text-blue-600 dark:text-blue-400" />
              Setup Instructions
            </h2>
          </div>

          <div className="p-6 space-y-6">
            {/* Step 1 */}
            <div className="flex gap-4">
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
                <span className="text-sm font-bold text-blue-600 dark:text-blue-400">1</span>
              </div>
              <div className="flex-1">
                <h3 className="text-base font-semibold text-gray-900 dark:text-white mb-2">
                  Get a SAM.gov API Key
                </h3>
                <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
                  Register for a free API key from the SAM.gov developer portal. You&apos;ll need a SAM.gov account.
                </p>
                <a
                  href="https://open.gsa.gov/api/sam-entity-management/#getting-started"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 text-sm font-medium text-blue-600 dark:text-blue-400 hover:underline"
                >
                  Visit SAM.gov API Portal
                  <ExternalLink className="w-4 h-4" />
                </a>
              </div>
            </div>

            {/* Step 2 */}
            <div className="flex gap-4">
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
                <span className="text-sm font-bold text-blue-600 dark:text-blue-400">2</span>
              </div>
              <div className="flex-1">
                <h3 className="text-base font-semibold text-gray-900 dark:text-white mb-2">
                  Create a SAM.gov Connection
                </h3>
                <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
                  Go to the Connections page and add a new SAM.gov connection with your API key.
                </p>
                <Link href="/connections">
                  <Button variant="secondary" className="gap-2">
                    <Settings className="w-4 h-4" />
                    Go to Connections
                    <ArrowRight className="w-4 h-4" />
                  </Button>
                </Link>
              </div>
            </div>

            {/* Step 3 */}
            <div className="flex gap-4">
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
                <span className="text-sm font-bold text-blue-600 dark:text-blue-400">3</span>
              </div>
              <div className="flex-1">
                <h3 className="text-base font-semibold text-gray-900 dark:text-white mb-2">
                  Test the Connection
                </h3>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  After adding the connection, test it to verify your API key works. Once verified, return here to start creating searches.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* What you can do with SAM.gov */}
        <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            What you can do with SAM.gov Integration
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="flex items-start gap-3">
              <CheckCircle className="w-5 h-5 text-emerald-500 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-gray-900 dark:text-white">Search Federal Opportunities</p>
                <p className="text-xs text-gray-500 dark:text-gray-400">Filter by NAICS, PSC, keywords, and more</p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <CheckCircle className="w-5 h-5 text-emerald-500 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-gray-900 dark:text-white">Automated Pulls</p>
                <p className="text-xs text-gray-500 dark:text-gray-400">Schedule hourly or daily syncs</p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <CheckCircle className="w-5 h-5 text-emerald-500 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-gray-900 dark:text-white">Download Attachments</p>
                <p className="text-xs text-gray-500 dark:text-gray-400">Automatically fetch SOWs and RFPs</p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <CheckCircle className="w-5 h-5 text-emerald-500 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-gray-900 dark:text-white">AI Summaries</p>
                <p className="text-xs text-gray-500 dark:text-gray-400">Generate summaries for quick review</p>
              </div>
            </div>
          </div>
        </div>

        {/* Note about API limits */}
        <div className="mt-6 p-4 bg-amber-50 dark:bg-amber-900/20 rounded-xl border border-amber-200 dark:border-amber-800">
          <p className="text-sm text-amber-800 dark:text-amber-200">
            <strong>Note:</strong> SAM.gov API has a daily rate limit of 10,000 requests. Curatore tracks your usage to help you stay within limits.
          </p>
        </div>
      </div>
    </div>
  )
}
