'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export default function ConnectionsPage() {
  const router = useRouter()

  useEffect(() => {
    // Redirect to the connections tab in settings-admin
    router.replace('/settings-admin?tab=connections')
  }, [router])

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      <div className="text-center">
        <div className="w-8 h-8 rounded-full border-4 border-gray-200 dark:border-gray-700 border-t-indigo-500 animate-spin mx-auto"></div>
        <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">Redirecting...</p>
      </div>
    </div>
  )
}
