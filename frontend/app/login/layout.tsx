// app/login/layout.tsx
/**
 * Minimal layout for the login page.
 *
 * This layout intentionally excludes navigation, sidebars, and other UI chrome
 * to provide a clean, focused login experience. It only includes the essential
 * HTML structure and global styles.
 *
 * Key features:
 * - No navigation bars or sidebars
 * - No authentication checks (allows unauthenticated access)
 * - Minimal styling for centered content
 * - Full-height layout for proper vertical centering
 */

import { ReactNode } from 'react'

interface LoginLayoutProps {
  children: ReactNode
}

export default function LoginLayout({ children }: LoginLayoutProps) {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {children}
    </div>
  )
}
