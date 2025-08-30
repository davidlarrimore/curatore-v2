// app/settings/page.tsx
'use client'

import { useRouter } from 'next/navigation'
import { Settings } from '@/components/Settings'

export default function SettingsPage() {
  const router = useRouter()

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white shadow-sm border-b">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">⚙️ Settings</h1>
              <p className="text-gray-600 mt-1">Manage system and connectivity settings</p>
            </div>
            <button
              type="button"
              onClick={() => router.push('/process')}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              📚 Back to Processing
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Settings />
      </div>
    </div>
  )
}
