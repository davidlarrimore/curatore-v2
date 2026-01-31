// components/layout/AppLayout.tsx
'use client'

/**
 * Main application layout wrapper.
 *
 * Provides the base layout structure for the application including:
 * - Top navigation bar
 * - Left sidebar with navigation
 * - Status bar at bottom
 * - System status monitoring
 * - Toast notifications
 *
 * Authentication-aware:
 * - Conditionally renders navigation/sidebars based on auth status
 * - Login page uses a minimal layout without chrome
 * - Protected pages get full navigation
 *
 * The layout adapts to:
 * - Current route (login vs app pages)
 * - Authentication state
 * - Screen size (responsive sidebar)
 */

import { useState, useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'
import { TopNavigation } from './TopNavigation'
import { LeftSidebar } from './LeftSidebar'
import { StatusBar } from './StatusBar'
import { systemApi } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import ProtectedRoute from '@/components/auth/ProtectedRoute'
import toast, { Toaster } from 'react-hot-toast'
import { HealthUnavailableOverlay } from '@/components/system/HealthUnavailableOverlay'

interface SystemStatus {
  health: string
  llmConnected: boolean
  isLoading: boolean
  supportedFormats: string[]
  maxFileSize: number
  backendVersion?: string
}

interface AppLayoutProps {
  children: React.ReactNode
}

export function AppLayout({ children }: AppLayoutProps) {
  const pathname = usePathname()
  const { isAuthenticated } = useAuth()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [systemStatus, setSystemStatus] = useState<SystemStatus>({
    health: 'checking',
    llmConnected: false,
    isLoading: true,
    supportedFormats: [],
    maxFileSize: 52428800
  })
  const hasShownHealthError = useRef(false)

  /**
   * Determine if the current page should show navigation.
   *
   * Navigation is hidden ONLY for:
   * - Login page (/login)
   *
   * All other pages show full navigation (ProtectedRoute handles auth).
   * This provides a clean, minimal experience for the login page only.
   */
  const showNavigation = pathname !== '/login'
  const isSystemUnavailable = !systemStatus.isLoading && systemStatus.health !== 'healthy'

  // Load system status on mount and set up refresh interval
  useEffect(() => {
    if (!isAuthenticated) return

    loadSystemStatus()

    // Refresh system status every 30 seconds
    const interval = setInterval(loadSystemStatus, 30000)
    return () => clearInterval(interval)
  }, [isAuthenticated])

  const loadSystemStatus = async () => {
    const [healthResult, formatsResult] = await Promise.allSettled([
      systemApi.getHealth(),
      systemApi.getSupportedFormats()
    ])

    if (healthResult.status === 'fulfilled' && formatsResult.status === 'fulfilled') {
      const healthStatus = healthResult.value
      const formatsData = formatsResult.value
      setSystemStatus({
        health: healthStatus.status,
        llmConnected: healthStatus.llm_connected,
        isLoading: false,
        supportedFormats: formatsData.supported_extensions,
        maxFileSize: formatsData.max_file_size,
        backendVersion: healthStatus.version
      })
      return
    }

    if (healthResult.status === 'rejected') {
      console.warn('Failed to load system health:', healthResult.reason)
    }
    if (formatsResult.status === 'rejected') {
      console.warn('Failed to load supported formats:', formatsResult.reason)
    }

    setSystemStatus(prev => ({
      ...prev,
      isLoading: false,
      health: 'error'
    }))

    // Only show the error toast once and never while the unavailable modal is visible
    if (!hasShownHealthError.current) {
      hasShownHealthError.current = true
      // Modal will be visible when health is unavailable, so skip toast in that case
    }
  }

  // Handle keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Only handle shortcuts when not typing in input fields
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return
      }

      if (e.metaKey || e.ctrlKey) {
        switch (e.key) {
          case 'b':
            e.preventDefault()
            setSidebarOpen(prev => !prev)
            break
          case 'j':
            e.preventDefault()
            // Navigate to assets page
            window.location.href = '/assets'
            break
          case 'p':
            e.preventDefault()
            // Navigate to queue admin page
            window.location.href = '/admin/queue'
            break
          case 'k':
            e.preventDefault()
            // Future: Open command palette
            toast('Command palette coming soon!', { icon: '⌘' })
            break
        }
      }
      
      // ESC to close mobile sidebar
      if (e.key === 'Escape') {
        setSidebarOpen(false)
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [])

  // Handle sidebar state persistence
  useEffect(() => {
    // Load saved sidebar state from localStorage
    const savedCollapsed = localStorage.getItem('sidebar-collapsed')
    if (savedCollapsed !== null) {
      setSidebarCollapsed(savedCollapsed === 'true')
    }
  }, [])

  const handleSidebarCollapsedChange = (collapsed: boolean) => {
    setSidebarCollapsed(collapsed)
    // Save state to localStorage
    localStorage.setItem('sidebar-collapsed', collapsed.toString())
  }

  // Handle window resize for responsive behavior
  useEffect(() => {
    const handleResize = () => {
      // Close mobile sidebar on large screen resize
      if (window.innerWidth >= 1024) {
        setSidebarOpen(false)
      }
    }

    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  /**
   * Render minimal layout for login/public pages.
   *
   * No navigation, sidebar, or status bar - just the content
   * with toast notifications for user feedback.
   */
  if (!showNavigation) {
    return (
      <div className="h-full flex flex-col">
        {/* Toast notifications */}
        <Toaster
          position="top-right"
          toastOptions={{
            duration: 4000,
            className: 'text-sm',
            style: {
              background: '#fff',
              border: '1px solid #e5e7eb',
              borderRadius: '0.5rem',
              boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)',
              maxWidth: '400px'
            },
            success: {
              iconTheme: {
                primary: '#10b981',
                secondary: '#fff',
              },
            },
            error: {
              iconTheme: {
                primary: '#ef4444',
                secondary: '#fff',
              },
            },
          }}
        />

        {/* Content only - no navigation chrome */}
        <main className="flex-1">
          {children}
        </main>
      </div>
    )
  }

  /**
   * Render full layout for authenticated pages.
   *
   * Includes top navigation, left sidebar, status bar,
   * and responsive behavior.
   */
  return (
    <ProtectedRoute>
      <div className="h-full flex flex-col" style={{
        '--sidebar-width': sidebarCollapsed ? '4rem' : '16rem'
      } as React.CSSProperties}>
        {/* Toast notifications with custom styling */}
        <Toaster
          position="top-right"
          toastOptions={{
            duration: 4000,
            className: 'text-sm',
            style: {
              background: '#fff',
              border: '1px solid #e5e7eb',
              borderRadius: '0.5rem',
              boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)',
              maxWidth: '400px'
            },
            success: {
              iconTheme: {
                primary: '#10b981',
                secondary: '#fff',
              },
            },
            error: {
              iconTheme: {
                primary: '#ef4444',
                secondary: '#fff',
              },
            },
            loading: {
              iconTheme: {
                primary: '#3b82f6',
                secondary: '#fff',
              },
            },
          }}
        />

        {/* Top Navigation - Pass sidebar state */}
        <TopNavigation
          onMenuClick={() => setSidebarOpen(true)}
          systemStatus={systemStatus}
          onStatusRefresh={loadSystemStatus}
          sidebarCollapsed={sidebarCollapsed} // Pass sidebar state
        />

        <div className="flex-1 flex overflow-hidden">
          {/* Left Sidebar */}
          <LeftSidebar
            open={sidebarOpen}
            collapsed={sidebarCollapsed}
            onOpenChange={setSidebarOpen}
            onCollapsedChange={handleSidebarCollapsedChange}
            systemStatus={systemStatus}
            onStatusRefresh={loadSystemStatus}
          />

          {/* Main Content Area - Adjust margin based on sidebar state */}
          <main className={`flex-1 flex flex-col overflow-hidden transition-all duration-300 ${
            sidebarCollapsed ? 'lg:ml-16' : 'lg:ml-64'
          }`}>
            <div className="flex-1 overflow-auto">
              {children}
            </div>
          </main>
        </div>

        {/* Status Bar - Higher z-index to stay above processing panel */}
        <StatusBar
          systemStatus={systemStatus}
          sidebarCollapsed={sidebarCollapsed}
        />

        <HealthUnavailableOverlay isVisible={isSystemUnavailable} />
      </div>
    </ProtectedRoute>
  )
}

// Export keyboard shortcut help for documentation
export const keyboardShortcuts = [
  { key: 'Cmd/Ctrl + B', description: 'Toggle sidebar' },
  { key: 'Cmd/Ctrl + J', description: 'Navigate to Assets page' },
  { key: 'Cmd/Ctrl + P', description: 'Navigate to Queue Admin' },
  { key: 'Cmd/Ctrl + ,', description: 'Open settings' },
  { key: 'Cmd/Ctrl + K', description: 'Command palette (coming soon)' },
  { key: 'Escape', description: 'Close mobile sidebar' }
]
