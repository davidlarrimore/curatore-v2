'use client'

/**
 * Redirect to the unified maintenance page.
 *
 * Scheduled tasks are managed from /system/maintenance.
 */

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export default function SystemScheduledTasksPage() {
  const router = useRouter()

  useEffect(() => {
    router.replace('/system/maintenance')
  }, [router])

  return null
}
