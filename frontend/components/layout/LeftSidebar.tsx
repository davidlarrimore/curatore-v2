// components/layout/LeftSidebar.tsx
'use client'

import { useState, useEffect } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { Fragment } from 'react'
import { Dialog, Transition } from '@headlessui/react'
import {
  X,
  ChevronLeft,
  ChevronRight,
  FileText,
  Settings,
  Activity,
  Zap,
  Upload,
  Download,
  BarChart3,
  HelpCircle,
  Layers,
  Database,
  TestTube,
  PanelLeftOpen,
  PanelLeftClose
} from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { systemApi } from '@/lib/api'
import { QualityThresholds, OCRSettings } from '@/types'
import clsx from 'clsx'
import toast from 'react-hot-toast'

interface SystemStatus {
  health: string
  llmConnected: boolean
  isLoading: boolean
  supportedFormats: string[]
  maxFileSize: number
}

interface LeftSidebarProps {
  open: boolean
  collapsed: boolean
  onOpenChange: (open: boolean) => void
  onCollapsedChange: (collapsed: boolean) => void
  systemStatus: SystemStatus
  onStatusRefresh: () => void
}

interface NavItem {
  name: string
  href: string
  icon: React.ComponentType<{ className?: string }>
  badge?: string
  current?: boolean
}

export function LeftSidebar({
  open,
  collapsed,
  onOpenChange,
  onCollapsedChange,
  systemStatus,
  onStatusRefresh
}: LeftSidebarProps) {
  const router = useRouter()
  const pathname = usePathname()
  const [showSettings, setShowSettings] = useState(false)
  const [llmStatus, setLLMStatus] = useState<any>(null)
  const [isTestingLLM, setIsTestingLLM] = useState(false)

  // Settings state for quick settings panel
  const [settingsData, setSettingsData] = useState({
    qualityThresholds: {
      conversion: 70,
      clarity: 7,
      completeness: 7,
      relevance: 7,
      markdown: 7
    } as QualityThresholds,
    ocrSettings: {
      language: 'eng',
      psm: 3
    } as OCRSettings,
    autoOptimize: true
  })

  // Load settings when component mounts
  useEffect(() => {
    loadSettings()
  }, [])

  const loadSettings = async () => {
    try {
      const config = await systemApi.getConfig()
      setSettingsData({
        qualityThresholds: config.quality_thresholds,
        ocrSettings: config.ocr_settings,
        autoOptimize: config.auto_optimize
      })
    } catch (error) {
      console.error('Failed to load settings:', error)
    }
  }

  const testLLMConnection = async () => {
    setIsTestingLLM(true)
    try {
      const status = await systemApi.getLLMStatus()
      setLLMStatus(status)
      onStatusRefresh() // Refresh overall system status
      if (status.connected) {
        toast.success('LLM connection test successful')
      } else {
        toast.error('LLM connection test failed')
      }
    } catch (error) {
      console.error('Failed to test LLM connection:', error)
      toast.error('Failed to test LLM connection')
      setLLMStatus({
        connected: false,
        endpoint: 'Unknown',
        model: 'Unknown',
        error: 'Connection test failed',
        ssl_verify: true,
        timeout: 60
      })
    } finally {
      setIsTestingLLM(false)
    }
  }

  // Navigation items
  const navigation: NavItem[] = [
    {
      name: 'Process Documents',
      href: '/process',
      icon: FileText,
      current: pathname === '/process'
    },
    {
      name: 'Settings',
      href: '/settings', 
      icon: Settings,
      current: pathname === '/settings'
    }
  ]

  // Quick actions
  const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
  const { API_PATH_VERSION } = require('@/lib/api')
  const quickActions: NavItem[] = [
    { name: 'Upload Files', href: '/process', icon: Upload },
    { name: 'View Results', href: '/process', icon: BarChart3 },
    { name: 'API Documentation', href: `${apiBase}/api/${API_PATH_VERSION}/docs`, icon: HelpCircle }
  ]

  // Mobile sidebar component
  const MobileSidebar = () => (
    <Transition.Root show={open} as={Fragment}>
      <Dialog as="div" className="relative z-50 lg:hidden" onClose={onOpenChange}>
        <Transition.Child
          as={Fragment}
          enter="transition-opacity ease-linear duration-300"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="transition-opacity ease-linear duration-300"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 bg-gray-900/80" />
        </Transition.Child>

        <div className="fixed inset-0 flex">
          <Transition.Child
            as={Fragment}
            enter="transition ease-in-out duration-300 transform"
            enterFrom="-translate-x-full"
            enterTo="translate-x-0"
            leave="transition ease-in-out duration-300 transform"
            leaveFrom="translate-x-0"
            leaveTo="-translate-x-full"
          >
            <Dialog.Panel className="relative mr-16 flex w-full max-w-xs flex-1">
              <Transition.Child
                as={Fragment}
                enter="ease-in-out duration-300"
                enterFrom="opacity-0"
                enterTo="opacity-100"
                leave="ease-in-out duration-300"
                leaveFrom="opacity-100"
                leaveTo="opacity-0"
              >
                <div className="absolute left-full top-0 flex w-16 justify-center pt-5">
                  <button
                    type="button"
                    className="-m-2.5 p-2.5"
                    onClick={() => onOpenChange(false)}
                    aria-label="Close sidebar"
                  >
                    <X className="h-6 w-6 text-white" />
                  </button>
                </div>
              </Transition.Child>
              <SidebarContent />
            </Dialog.Panel>
          </Transition.Child>
        </div>
      </Dialog>
    </Transition.Root>
  )

  // Desktop sidebar component
  const DesktopSidebar = () => (
    <div className={clsx(
      'hidden lg:fixed lg:inset-y-0 lg:z-40 lg:flex lg:flex-col transition-all duration-300',
      collapsed ? 'lg:w-16' : 'lg:w-64'
    )}>
      <SidebarContent />
    </div>
  )

  // Shared sidebar content
  const SidebarContent = () => (
    <div className="flex grow flex-col gap-y-5 overflow-y-auto bg-white border-r border-gray-200 px-6 py-4">
      {/* Collapse button for desktop - Updated with sidebar icons */}
      {!open && (
        <div className="hidden lg:flex lg:justify-end">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onCollapsedChange(!collapsed)}
            className="p-1"
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? (
              <PanelLeftOpen className="w-4 h-4" />
            ) : (
              <PanelLeftClose className="w-4 h-4" />
            )}
          </Button>
        </div>
      )}

      {/* System Status */}
      <div className={clsx('space-y-2', collapsed && 'hidden')}>
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold text-gray-900 uppercase tracking-wide">
            System Status
          </h3>
          <Button
            variant="ghost"
            size="xs"
            onClick={onStatusRefresh}
            disabled={systemStatus.isLoading}
            title="Refresh status"
          >
            <Activity className={`w-3 h-3 ${systemStatus.isLoading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
        
        <div className="space-y-1">
          <div className="flex items-center justify-between py-1">
            <span className="text-sm text-gray-600 flex items-center">
              <Activity className="w-4 h-4 mr-2" />
              API Health
            </span>
            <Badge variant={systemStatus.health === 'healthy' ? 'success' : 'error'} className="text-xs">
              {systemStatus.health}
            </Badge>
          </div>
          <div className="flex items-center justify-between py-1">
            <span className="text-sm text-gray-600 flex items-center">
              <Zap className="w-4 h-4 mr-2" />
              LLM Connection
            </span>
            <Badge variant={systemStatus.llmConnected ? 'success' : 'error'} className="text-xs">
              {systemStatus.llmConnected ? 'Connected' : 'Disconnected'}
            </Badge>
          </div>
          
          {/* LLM Test Button */}
          <div className="pt-2">
            <Button
              variant="outline"
              size="sm"
              onClick={testLLMConnection}
              disabled={isTestingLLM}
              loading={isTestingLLM}
              className="w-full text-xs"
            >
              <TestTube className="w-3 h-3 mr-2" />
              Test LLM
            </Button>
          </div>

          {/* LLM Status Details */}
          {llmStatus && (
            <div className="mt-2 p-3 bg-gray-50 rounded-lg">
              <div className="text-xs space-y-1">
                <div className="flex justify-between">
                  <span className="text-gray-600">Endpoint:</span>
                  <span className="font-mono text-gray-900 truncate ml-2 max-w-32" title={llmStatus.endpoint}>
                    {llmStatus.endpoint.replace('https://', '').replace('http://', '')}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Model:</span>
                  <span className="font-mono text-gray-900">{llmStatus.model}</span>
                </div>
                {llmStatus.error && (
                  <div className="mt-2 text-red-600 text-xs">
                    Error: {llmStatus.error.substring(0, 50)}...
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Main Navigation */}
      <nav className="flex flex-1 flex-col">
        <ul role="list" className="flex flex-1 flex-col gap-y-7">
          <li>
            <div className={clsx('text-xs font-semibold text-gray-900 uppercase tracking-wide', collapsed && 'hidden')}>
              Navigation
            </div>
            <ul role="list" className="-mx-2 space-y-1 mt-2">
              {navigation.map((item) => (
                <li key={item.name}>
                  <button
                    onClick={() => {
                      router.push(item.href)
                      onOpenChange(false) // Close mobile sidebar
                    }}
                    className={clsx(
                      item.current
                        ? 'bg-blue-50 border-r-2 border-blue-500 text-blue-700'
                        : 'text-gray-700 hover:text-blue-700 hover:bg-gray-50',
                      'group flex gap-x-3 rounded-md p-2 text-sm leading-6 font-semibold w-full text-left transition-colors'
                    )}
                    title={collapsed ? item.name : undefined}
                  >
                    <item.icon
                      className={clsx(
                        item.current ? 'text-blue-500' : 'text-gray-400 group-hover:text-blue-500',
                        'h-5 w-5 shrink-0'
                      )}
                    />
                    {!collapsed && (
                      <>
                        {item.name}
                        {item.badge && (
                          <Badge variant="secondary" className="ml-auto text-xs">
                            {item.badge}
                          </Badge>
                        )}
                      </>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          </li>

          {/* Quick Actions */}
          <li>
            <div className={clsx('text-xs font-semibold text-gray-900 uppercase tracking-wide', collapsed && 'hidden')}>
              Quick Actions
            </div>
            <ul role="list" className="-mx-2 space-y-1 mt-2">
              {quickActions.map((item) => (
                <li key={item.name}>
                  <button
                    onClick={() => {
                      if (item.href.startsWith('http')) {
                        window.open(item.href, '_blank')
                      } else {
                        router.push(item.href)
                      }
                      onOpenChange(false)
                    }}
                    className="text-gray-700 hover:text-blue-700 hover:bg-gray-50 group flex gap-x-3 rounded-md p-2 text-sm leading-6 font-medium w-full text-left transition-colors"
                    title={collapsed ? item.name : undefined}
                  >
                    <item.icon className="text-gray-400 group-hover:text-blue-500 h-5 w-5 shrink-0" />
                    {!collapsed && item.name}
                  </button>
                </li>
              ))}
            </ul>
          </li>

          {/* Settings Panel */}
          {!collapsed && (
            <li className="mt-auto">
              <div className="border-t border-gray-200 pt-4">
                <button
                  onClick={() => setShowSettings(!showSettings)}
                  className="text-gray-700 hover:text-blue-700 hover:bg-gray-50 group flex gap-x-3 rounded-md p-2 text-sm leading-6 font-medium w-full text-left transition-colors"
                >
                  <Settings className="text-gray-400 group-hover:text-blue-500 h-5 w-5 shrink-0" />
                  Quick Settings
                  <ChevronRight className={clsx(
                    'ml-auto h-4 w-4 transition-transform',
                    showSettings && 'rotate-90'
                  )} />
                </button>

                {showSettings && (
                  <div className="mt-2 space-y-3 px-2">
                    {/* Auto-optimize toggle */}
                    <label className="flex items-center space-x-2 text-sm">
                      <input
                        type="checkbox"
                        checked={settingsData.autoOptimize}
                        onChange={(e) => {
                          const newValue = e.target.checked
                          setSettingsData(prev => ({
                            ...prev,
                            autoOptimize: newValue
                          }))
                          toast.success(`Vector DB optimization ${newValue ? 'enabled' : 'disabled'}`)
                        }}
                        className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                      />
                      <span className="text-gray-600">Auto-optimize for Vector DB</span>
                    </label>

                    {/* Quality threshold slider */}
                    <div className="space-y-2">
                      <label className="block text-xs font-medium text-gray-700">
                        Quality Threshold
                      </label>
                      <input
                        type="range"
                        min="50"
                        max="95"
                        value={settingsData.qualityThresholds.conversion}
                        onChange={(e) => {
                          const newValue = parseInt(e.target.value)
                          setSettingsData(prev => ({
                            ...prev,
                            qualityThresholds: {
                              ...prev.qualityThresholds,
                              conversion: newValue
                            }
                          }))
                        }}
                        className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer slider"
                      />
                      <div className="text-xs text-gray-500 text-center">
                        {settingsData.qualityThresholds.conversion}%
                      </div>
                    </div>

                    {/* OCR Language quick setting */}
                    <div className="space-y-2">
                      <label className="block text-xs font-medium text-gray-700">
                        OCR Language
                      </label>
                      <select
                        value={settingsData.ocrSettings.language}
                        onChange={(e) => {
                          const newValue = e.target.value
                          setSettingsData(prev => ({
                            ...prev,
                            ocrSettings: {
                              ...prev.ocrSettings,
                              language: newValue
                            }
                          }))
                          toast.success(`OCR language set to ${newValue}`)
                        }}
                        className="w-full px-2 py-1 border border-gray-300 rounded text-xs focus:outline-none focus:ring-blue-500 focus:border-blue-500"
                      >
                        <option value="eng">English</option>
                        <option value="eng+spa">English + Spanish</option>
                        <option value="fra">French</option>
                        <option value="deu">German</option>
                        <option value="chi_sim">Chinese (Simplified)</option>
                      </select>
                    </div>

                    <div className="flex space-x-2">
                      <Button
                        variant="outline"
                        size="xs"
                        onClick={() => router.push('/settings')}
                        className="flex-1"
                      >
                        Advanced Settings
                      </Button>
                      <Button
                        variant="ghost"
                        size="xs"
                        onClick={loadSettings}
                        title="Reload settings"
                      >
                        <Activity className="w-3 h-3" />
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </li>
          )}

          {/* Collapsed state indicators */}
          {collapsed && (
            <li className="mt-auto">
              <div className="space-y-2">
                <div className="flex justify-center">
                  <div className={`w-2 h-2 rounded-full ${
                    systemStatus.health === 'healthy' ? 'bg-green-500' : 'bg-red-500'
                  }`} title={`API Status: ${systemStatus.health}`} />
                </div>
                <div className="flex justify-center">
                  <div className={`w-2 h-2 rounded-full ${
                    systemStatus.llmConnected ? 'bg-green-500' : 'bg-red-500'
                  }`} title={`LLM Status: ${systemStatus.llmConnected ? 'Connected' : 'Disconnected'}`} />
                </div>
              </div>
            </li>
          )}
        </ul>
      </nav>
    </div>
  )

  return (
    <>
      <MobileSidebar />
      <DesktopSidebar />
    </>
  )
}
