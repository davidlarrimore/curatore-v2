// components/layout/TopNavigation.tsx
'use client'

import { useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import {
  Menu,
  Settings,
  RotateCcw,
  HelpCircle,
  Activity,
  AlertCircle,
  Github,
  Heart,
  Link as LinkIcon,
  LogOut,
  User
} from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { systemApi } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import Image from 'next/image'
import toast from 'react-hot-toast'

interface SystemStatus {
  health: string
  llmConnected: boolean
  isLoading: boolean
}

interface TopNavigationProps {
  onMenuClick: () => void
  systemStatus: SystemStatus
  onStatusRefresh: () => void
  sidebarCollapsed: boolean // NEW: Track sidebar state
}

export function TopNavigation({ 
  onMenuClick, 
  systemStatus, 
  onStatusRefresh,
  sidebarCollapsed // NEW: Receive sidebar state
}: TopNavigationProps) {
  const pathname = usePathname()
  const router = useRouter()
  const { user, isAuthenticated, logout } = useAuth()
  const [isResetting, setIsResetting] = useState(false)
  const [showResetConfirm, setShowResetConfirm] = useState(false)

  const handleLogout = () => {
    logout()
    router.push('/login')
    toast.success('Logged out successfully')
  }

  const handleReset = async () => {
    setIsResetting(true)
    try {
      await systemApi.resetSystem()
      try { localStorage.removeItem('curatore:active_jobs') } catch {}
      toast.success('System reset successfully!')
      setShowResetConfirm(false)
      // Refresh the page to reset all state
      window.location.reload()
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Reset failed'
      toast.error(`Failed to reset system: ${errorMessage}`)
      console.error('Reset failed:', error)
    } finally {
      setIsResetting(false)
    }
  }

  // Generate breadcrumbs based on current path
  const generateBreadcrumbs = () => {
    const segments = pathname.split('/').filter(Boolean)
    const breadcrumbs = [{ name: 'Home', href: '/process' }]
    
    segments.forEach((segment, index) => {
      const href = '/' + segments.slice(0, index + 1).join('/')
      const name = segment.charAt(0).toUpperCase() + segment.slice(1)
      
      // Map common paths to friendly names
      const friendlyNames: Record<string, string> = {
        'process': 'Processing',
        'settings': 'Settings',
        'settings-admin': 'Admin Settings',
        'connections': 'Connections',
        'login': 'Login',
        'analytics': 'Analytics',
        'batch': 'Batch Processing'
      }
      
      breadcrumbs.push({ 
        name: friendlyNames[segment] || name, 
        href 
      })
    })

    return breadcrumbs
  }

  const breadcrumbs = generateBreadcrumbs()

  return (
    <>
      <header className={`bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between transition-all duration-300 ${
        // Adjust margin based on sidebar state - only on desktop
        `lg:ml-${sidebarCollapsed ? '16' : '64'}`
      }`}>
        <div className="flex items-center space-x-4">
          {/* Mobile menu button */}
          <Button
            variant="ghost"
            size="sm"
            onClick={onMenuClick}
            className="lg:hidden"
            aria-label="Open navigation menu"
          >
            <Menu className="w-5 h-5" />
          </Button>

          {/* Logo and title - hide on mobile when space is limited */}
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 flex items-center justify-center">
              <Image
            src="/logo.png" // The path starts from the `public` folder
            alt="Amivero Logo"
            width={120} // Desired width in pixels
            height={30} // Desired height in pixels
          />
            </div>
            <div className="hidden sm:block">
              <h1 className="text-xl font-semibold text-gray-900">Curatorè v2</h1>
              <p className="text-xs text-gray-500 hidden md:block">RAG Document Processing</p>
            </div>
          </div>

          {/* Breadcrumbs - simplified for space */}
          <nav className="hidden lg:flex items-center space-x-1 text-sm" aria-label="Breadcrumb">
            {breadcrumbs.slice(-2).map((breadcrumb, index, arr) => (
              <div key={`${breadcrumb.href}-${index}`} className="flex items-center">
                {index > 0 && <span className="text-gray-400 mx-2">/</span>}
                <button
                  type="button"
                  onClick={() => router.push(breadcrumb.href)}
                  className={`px-2 py-1 rounded hover:bg-gray-100 transition-colors ${
                    index === arr.length - 1
                      ? 'text-gray-900 font-medium'
                      : 'text-gray-500 hover:text-gray-700'
                  }`}
                >
                  {breadcrumb.name}
                </button>
              </div>
            ))}
          </nav>
        </div>

        {/* Right side controls */}
        <div className="flex items-center space-x-2">
          {/* Action buttons */}
          <Button
            variant="ghost"
            size="sm"
            onClick={onStatusRefresh}
            disabled={systemStatus.isLoading}
            title="Refresh system status"
            aria-label="Refresh system status"
          >
            <Activity className={`w-4 h-4 ${systemStatus.isLoading ? 'animate-spin' : ''}`} />
          </Button>

          <Button
            variant="ghost"
            size="sm"
            onClick={() => router.push('/connections')}
            title="Connections"
            aria-label="View connections"
            className={`${
              systemStatus.health === 'healthy'
                ? 'text-green-600 hover:text-green-700 hover:bg-green-50'
                : 'text-red-600 hover:text-red-700 hover:bg-red-50'
            }`}
          >
            <Heart className="w-4 h-4" />
          </Button>

          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowResetConfirm(true)}
            disabled={isResetting}
            title="Reset system"
            aria-label="Reset system"
            className="text-red-600 hover:text-red-700 hover:bg-red-50"
          >
            <RotateCcw className={`w-4 h-4 ${isResetting ? 'animate-spin' : ''}`} />
          </Button>

          <Button
            variant="ghost"
            size="sm"
            onClick={() => router.push('/settings')}
            title="Settings"
            aria-label="Open settings"
            className="hidden sm:flex"
          >
            <Settings className="w-4 h-4" />
          </Button>

          {/* Auth controls */}
          {isAuthenticated ? (
            <>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => router.push('/connections')}
                title="Manage Connections"
                aria-label="Manage connections"
                className="hidden sm:flex"
              >
                <LinkIcon className="w-4 h-4" />
              </Button>

              <div className="hidden sm:flex items-center space-x-2 px-3 py-1.5 bg-gray-100 dark:bg-gray-800 rounded-md">
                <User className="w-4 h-4 text-gray-600 dark:text-gray-400" />
                <span className="text-sm text-gray-700 dark:text-gray-300">
                  {user?.username}
                </span>
              </div>

              <Button
                variant="ghost"
                size="sm"
                onClick={handleLogout}
                title="Logout"
                aria-label="Logout"
                className="hidden sm:flex"
              >
                <LogOut className="w-4 h-4" />
              </Button>
            </>
          ) : (
            <Button
              variant="primary"
              size="sm"
              onClick={() => router.push('/login')}
              className="hidden sm:flex"
            >
              Login
            </Button>
          )}

          <Button
            variant="ghost"
            size="sm"
            title="Help & Documentation"
            aria-label="Help and documentation"
            onClick={() => {
              const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
              const { API_PATH_VERSION } = require('@/lib/api');
              window.open(`${apiBase}/api/${API_PATH_VERSION}/docs`, '_blank');
            }}
            className="hidden md:flex"
          >
            <HelpCircle className="w-4 h-4" />
          </Button>

          {/* GitHub repository link */}
          <Button
            variant="ghost"
            size="sm"
            title="View on GitHub"
            aria-label="View on GitHub"
            onClick={() => {
              window.open('https://github.com/davidlarrimore/curatore-v2', '_blank', 'noopener,noreferrer')
            }}
          >
            <Github className="w-4 h-4" />
          </Button>
        </div>
      </header>

      {/* Reset confirmation modal */}
      {showResetConfirm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4">
            <div className="flex items-center space-x-3 mb-4">
              <div className="w-10 h-10 bg-red-100 rounded-full flex items-center justify-center">
                <AlertCircle className="w-6 h-6 text-red-600" />
              </div>
              <div>
                <h3 className="text-lg font-semibold text-gray-900">Reset System?</h3>
                <p className="text-sm text-gray-600">This action cannot be undone</p>
              </div>
            </div>
            
            <p className="text-gray-600 mb-6 text-sm">
              All uploaded files, processed documents, and session data will be permanently deleted.
            </p>
            
            <div className="flex space-x-3">
              <Button
                variant="outline"
                onClick={() => setShowResetConfirm(false)}
                disabled={isResetting}
                className="flex-1"
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                onClick={handleReset}
                disabled={isResetting}
                loading={isResetting}
                className="flex-1"
              >
                {isResetting ? 'Resetting...' : 'Reset System'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
