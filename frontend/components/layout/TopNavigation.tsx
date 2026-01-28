// components/layout/TopNavigation.tsx
'use client'

import { useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import {
  Menu,
  RotateCcw,
  HelpCircle,
  Activity,
  AlertTriangle,
  Github,
  Link as LinkIcon,
  LogOut,
  User,
  ChevronRight,
  X
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
  sidebarCollapsed: boolean
}

export function TopNavigation({
  onMenuClick,
  systemStatus,
  onStatusRefresh,
  sidebarCollapsed
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

      const friendlyNames: Record<string, string> = {
        'process': 'Processing',
        'settings-admin': 'Admin Settings',
        'connections': 'Connections',
        'login': 'Login',
        'analytics': 'Analytics',
        'batch': 'Batch Processing',
        'jobs': 'Jobs',
        'storage': 'Storage'
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
      <header className={`bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 px-4 lg:px-6 py-3 flex items-center justify-between transition-all duration-300 ${
        sidebarCollapsed ? 'lg:ml-16' : 'lg:ml-64'
      }`}>
        <div className="flex items-center gap-4">
          {/* Mobile menu button */}
          <button
            onClick={onMenuClick}
            className="lg:hidden p-2 -ml-2 rounded-lg text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            aria-label="Open navigation menu"
          >
            <Menu className="w-5 h-5" />
          </button>

          {/* Logo and title */}
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 flex items-center justify-center">
              <Image
                src="/logo.png"
                alt="Curatore Logo"
                width={32}
                height={32}
                className="object-contain"
              />
            </div>
            <div className="hidden sm:block">
              <h1 className="text-lg font-semibold text-gray-900 dark:text-white">Curatorè</h1>
            </div>
          </div>

          {/* Breadcrumbs */}
          <nav className="hidden lg:flex items-center text-sm" aria-label="Breadcrumb">
            <div className="flex items-center">
              {breadcrumbs.slice(-2).map((breadcrumb, index, arr) => (
                <div key={`${breadcrumb.href}-${index}`} className="flex items-center">
                  {index > 0 && (
                    <ChevronRight className="w-4 h-4 text-gray-300 dark:text-gray-600 mx-1" />
                  )}
                  <button
                    type="button"
                    onClick={() => router.push(breadcrumb.href)}
                    className={`px-2 py-1 rounded-md transition-colors ${
                      index === arr.length - 1
                        ? 'text-gray-900 dark:text-white font-medium bg-gray-100 dark:bg-gray-800'
                        : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800'
                    }`}
                  >
                    {breadcrumb.name}
                  </button>
                </div>
              ))}
            </div>
          </nav>
        </div>

        {/* Right side controls */}
        <div className="flex items-center gap-1">
          {/* Status indicator */}
          <button
            onClick={onStatusRefresh}
            disabled={systemStatus.isLoading}
            className={`hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              systemStatus.health === 'healthy'
                ? 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-100 dark:hover:bg-emerald-900/30'
                : 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/30'
            }`}
            title="Click to refresh status"
          >
            <span className={`w-2 h-2 rounded-full ${
              systemStatus.health === 'healthy' ? 'bg-emerald-500' : 'bg-red-500'
            } ${systemStatus.isLoading ? 'animate-pulse' : ''}`}></span>
            <span className="hidden md:inline">
              {systemStatus.health === 'healthy' ? 'Healthy' : 'Unhealthy'}
            </span>
            <Activity className={`w-3.5 h-3.5 ${systemStatus.isLoading ? 'animate-spin' : ''}`} />
          </button>

          {/* Divider */}
          <div className="hidden sm:block w-px h-6 bg-gray-200 dark:bg-gray-700 mx-2"></div>

          {/* Quick actions */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => router.push('/connections')}
              className="p-2 rounded-lg text-gray-500 dark:text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
              title="Connections"
            >
              <LinkIcon className="w-4 h-4" />
            </button>

            <button
              onClick={() => setShowResetConfirm(true)}
              disabled={isResetting}
              className="p-2 rounded-lg text-gray-500 dark:text-gray-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
              title="Reset system"
            >
              <RotateCcw className={`w-4 h-4 ${isResetting ? 'animate-spin' : ''}`} />
            </button>

            <button
              onClick={() => {
                const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
                const { API_PATH_VERSION } = require('@/lib/api');
                window.open(`${apiBase}/api/${API_PATH_VERSION}/docs`, '_blank');
              }}
              className="hidden md:flex p-2 rounded-lg text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
              title="API Documentation"
            >
              <HelpCircle className="w-4 h-4" />
            </button>

            <button
              onClick={() => window.open('https://github.com/davidlarrimore/curatore-v2', '_blank', 'noopener,noreferrer')}
              className="p-2 rounded-lg text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
              title="View on GitHub"
            >
              <Github className="w-4 h-4" />
            </button>
          </div>

          {/* Divider */}
          <div className="hidden sm:block w-px h-6 bg-gray-200 dark:bg-gray-700 mx-2"></div>

          {/* Auth section */}
          {isAuthenticated ? (
            <div className="flex items-center gap-2">
              <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 bg-gray-100 dark:bg-gray-800 rounded-lg">
                <div className="w-6 h-6 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center">
                  <span className="text-xs font-medium text-white">
                    {user?.username?.charAt(0).toUpperCase() || 'U'}
                  </span>
                </div>
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300 max-w-[100px] truncate">
                  {user?.username}
                </span>
              </div>

              <button
                onClick={handleLogout}
                className="p-2 rounded-lg text-gray-500 dark:text-gray-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                title="Logout"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          ) : (
            <Button
              onClick={() => router.push('/login')}
              size="sm"
              className="hidden sm:flex gap-2 shadow-lg shadow-indigo-500/25"
            >
              <User className="w-4 h-4" />
              Login
            </Button>
          )}
        </div>
      </header>

      {/* Reset confirmation modal */}
      {showResetConfirm && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl max-w-md w-full overflow-hidden">
            {/* Modal header */}
            <div className="relative bg-gradient-to-r from-red-500 to-red-600 px-6 py-5">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-white/20 rounded-lg">
                  <AlertTriangle className="w-6 h-6 text-white" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-white">Reset System</h3>
                  <p className="text-sm text-red-100">This action cannot be undone</p>
                </div>
              </div>
              <button
                onClick={() => setShowResetConfirm(false)}
                className="absolute top-4 right-4 p-1 text-white/80 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal body */}
            <div className="p-6">
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-6">
                All uploaded files, processed documents, and session data will be permanently deleted.
                This is typically used for testing or to start fresh.
              </p>

              <div className="flex gap-3">
                <Button
                  variant="secondary"
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
                  className="flex-1 gap-2"
                >
                  {isResetting ? (
                    <>
                      <RotateCcw className="w-4 h-4 animate-spin" />
                      Resetting...
                    </>
                  ) : (
                    <>
                      <RotateCcw className="w-4 h-4" />
                      Reset System
                    </>
                  )}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
