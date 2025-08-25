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
  Zap,
  AlertCircle
} from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { systemApi } from '@/lib/api'
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
}

export function TopNavigation({ 
  onMenuClick, 
  systemStatus, 
  onStatusRefresh 
}: TopNavigationProps) {
  const pathname = usePathname()
  const router = useRouter()
  const [isResetting, setIsResetting] = useState(false)
  const [showResetConfirm, setShowResetConfirm] = useState(false)

  const handleReset = async () => {
    setIsResetting(true)
    try {
      await systemApi.resetSystem()
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
      <header className="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
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

          {/* Logo and title */}
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg flex items-center justify-center">
              <span className="text-white font-bold text-sm">C</span>
            </div>
            <div>
              <h1 className="text-xl font-semibold text-gray-900">Curatore v2</h1>
              <p className="text-xs text-gray-500 hidden sm:block">RAG Document Processing</p>
            </div>
          </div>

          {/* Breadcrumbs */}
          <nav className="hidden md:flex items-center space-x-1 text-sm" aria-label="Breadcrumb">
            {breadcrumbs.map((breadcrumb, index) => (
              <div key={breadcrumb.href} className="flex items-center">
                {index > 0 && <span className="text-gray-400 mx-2">/</span>}
                <button
                  onClick={() => router.push(breadcrumb.href)}
                  className={`px-2 py-1 rounded hover:bg-gray-100 transition-colors ${
                    index === breadcrumbs.length - 1
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
          {/* System status indicators */}
          <div className="hidden md:flex items-center space-x-3">
            <Badge 
              variant={systemStatus.health === 'healthy' ? 'success' : 'error'}
              className="text-xs"
            >
              <Activity className="w-3 h-3 mr-1" />
              API
            </Badge>
            <Badge 
              variant={systemStatus.llmConnected ? 'success' : 'error'}
              className="text-xs"
            >
              <Zap className="w-3 h-3 mr-1" />
              LLM
            </Badge>
          </div>

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
          >
            <Settings className="w-4 h-4" />
          </Button>

          <Button
            variant="ghost"
            size="sm"
            title="Help & Documentation"
            aria-label="Help and documentation"
            onClick={() => window.open('http://localhost:8000/docs', '_blank')}
          >
            <HelpCircle className="w-4 h-4" />
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