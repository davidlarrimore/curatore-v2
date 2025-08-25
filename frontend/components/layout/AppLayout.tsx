// components/layout/AppLayout.tsx
'use client'

import { useState, useEffect } from 'react'
import { TopNavigation } from './TopNavigation'
import { LeftSidebar } from './LeftSidebar'
import { StatusBar } from './StatusBar'
import { systemApi } from '@/lib/api'
import toast, { Toaster } from 'react-hot-toast'

interface SystemStatus {
  health: string
  llmConnected: boolean
  isLoading: boolean
  supportedFormats: string[]
  maxFileSize: number
}

interface AppLayoutProps {
  children: React.ReactNode
}

export function AppLayout({ children }: AppLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [systemStatus, setSystemStatus] = useState<SystemStatus>({
    health: 'checking',
    llmConnected: false,
    isLoading: true,
    supportedFormats: [],
    maxFileSize: 52428800
  })

  // Load system status on mount and set up refresh interval
  useEffect(() => {
    loadSystemStatus()
    
    // Refresh system status every 30 seconds
    const interval = setInterval(loadSystemStatus, 30000)
    return () => clearInterval(interval)
  }, [])

  const loadSystemStatus = async () => {
    try {
      const [healthStatus, formatsData] = await Promise.all([
        systemApi.getHealth(),
        systemApi.getSupportedFormats()
      ])

      setSystemStatus({
        health: healthStatus.status,
        llmConnected: healthStatus.llm_connected,
        isLoading: false,
        supportedFormats: formatsData.supported_extensions,
        maxFileSize: formatsData.max_file_size
      })
    } catch (error) {
      console.error('Failed to load system status:', error)
      setSystemStatus(prev => ({ 
        ...prev, 
        isLoading: false,
        health: 'error'
      }))
      
      // Only show error toast on initial load failure, not on refresh failures
      if (prev => prev.health === 'checking') {
        toast.error('Failed to load system status')
      }
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
          case ',':
            e.preventDefault()
            // Navigate to settings
            window.location.href = '/settings'
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

  return (
    <div className="h-full flex flex-col">
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

      {/* Top Navigation */}
      <TopNavigation
        onMenuClick={() => setSidebarOpen(true)}
        systemStatus={systemStatus}
        onStatusRefresh={loadSystemStatus}
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

        {/* Main Content Area */}
        <main className={`flex-1 flex flex-col overflow-hidden transition-all duration-300 ${
          sidebarCollapsed ? 'lg:ml-16' : 'lg:ml-64'
        }`}>
          <div className="flex-1 overflow-auto">
            {children}
          </div>
        </main>
      </div>

      {/* Status Bar */}
      <StatusBar systemStatus={systemStatus} />
    </div>
  )
}

// Export keyboard shortcut help for documentation
export const keyboardShortcuts = [
  { key: 'Cmd/Ctrl + B', description: 'Toggle sidebar' },
  { key: 'Cmd/Ctrl + ,', description: 'Open settings' },
  { key: 'Cmd/Ctrl + K', description: 'Command palette (coming soon)' },
  { key: 'Escape', description: 'Close mobile sidebar' }
]