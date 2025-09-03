// components/layout/LeftSidebar.tsx
'use client'

import { useState, useEffect } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { Fragment } from 'react'
import { Dialog, Transition } from '@headlessui/react'
import {
  X,
  FileText,
  Settings,
  PanelLeftOpen,
  PanelLeftClose
} from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { systemApi } from '@/lib/api'
import { QualityThresholds, OCRSettings } from '@/types'
import clsx from 'clsx'

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

  // Navigation items - ONLY existing routes
  const navigation: NavItem[] = [
    {
      name: 'Process Documents',
      href: '/process',
      icon: FileText,
      current: pathname === '/process'
    }
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
                  <button type="button" className="-m-2.5 p-2.5" onClick={() => onOpenChange(false)}>
                    <span className="sr-only">Close sidebar</span>
                    <X className="h-6 w-6 text-white" aria-hidden="true" />
                  </button>
                </div>
              </Transition.Child>
              
              {/* Mobile sidebar content */}
              <div className="flex grow flex-col gap-y-5 overflow-y-auto bg-white px-6 pb-2 ring-1 ring-white/10">
                <div className="flex h-16 shrink-0 items-center">
                  <h1 className="text-xl font-bold text-gray-900">Curatore</h1>
                </div>
                
                {/* Main Navigation */}
                <nav className="flex flex-1 flex-col">
                  <ul role="list" className="flex flex-1 flex-col gap-y-7">
                    <li>
                      <div className="text-xs font-semibold text-gray-900 uppercase tracking-wide">
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
                                  ? 'bg-gray-50 text-blue-600'
                                  : 'text-gray-700 hover:text-blue-600 hover:bg-gray-50',
                                'group flex gap-x-3 rounded-md p-2 text-sm leading-6 font-semibold w-full text-left'
                              )}
                            >
                              <item.icon
                                className={clsx(
                                  item.current ? 'text-blue-600' : 'text-gray-400 group-hover:text-blue-600',
                                  'h-6 w-6 shrink-0'
                                )}
                                aria-hidden="true"
                              />
                              {item.name}
                              {item.badge && (
                                <span className="ml-auto inline-block bg-gray-100 text-gray-600 text-xs px-1.5 py-0.5 rounded">
                                  {item.badge}
                                </span>
                              )}
                            </button>
                          </li>
                        ))}
                      </ul>
                    </li>
                  </ul>
                </nav>

                {/* Bottom action for mobile - only Settings (existing route) */}
                <div className="mt-auto space-y-2">
                  <Button
                    variant="outline"
                    onClick={() => router.push('/settings')}
                    className="w-full"
                  >
                    <Settings className="w-4 h-4 mr-2" />
                    Settings
                  </Button>
                </div>
              </div>
            </Dialog.Panel>
          </Transition.Child>
        </div>
      </Dialog>
    </Transition.Root>
  )

  // Desktop sidebar component
  const DesktopSidebar = () => (
    <div className={`hidden lg:fixed lg:inset-y-0 lg:z-10 lg:flex lg:flex-col transition-all duration-300 ${
      collapsed ? 'lg:w-16' : 'lg:w-64'
    }`}>
      {/* Sidebar component with proper spacing and styling */}
      <div className="flex grow flex-col gap-y-5 overflow-y-auto border-r border-gray-200 bg-white px-6 pb-4">
        <div className="flex h-16 shrink-0 items-center justify-between">
          {!collapsed && (
            <h1 className="text-xl font-bold text-gray-900">Curatore</h1>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onCollapsedChange(!collapsed)}
            className="ml-auto"
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? (
              <PanelLeftOpen className="w-4 h-4" />
            ) : (
              <PanelLeftClose className="w-4 h-4" />
            )}
          </Button>
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
                          ? 'bg-gray-50 text-blue-600'
                          : 'text-gray-700 hover:text-blue-600 hover:bg-gray-50',
                        'group flex gap-x-3 rounded-md p-2 text-sm leading-6 font-semibold w-full text-left',
                        collapsed && 'justify-center px-2'
                      )}
                      title={collapsed ? item.name : ''}
                    >
                      <item.icon
                        className={clsx(
                          item.current ? 'text-blue-600' : 'text-gray-400 group-hover:text-blue-600',
                          'h-6 w-6 shrink-0'
                        )}
                        aria-hidden="true"
                      />
                      {!collapsed && (
                        <>
                          {item.name}
                          {item.badge && (
                            <span className="ml-auto inline-block bg-gray-100 text-gray-600 text-xs px-1.5 py-0.5 rounded">
                              {item.badge}
                            </span>
                          )}
                        </>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            </li>

            {/* Bottom actions - Settings only */}
            <li className="mt-auto">
              <ul role="list" className="-mx-2 space-y-1">
                <li>
                  <button
                    onClick={() => router.push('/settings')}
                    className={clsx(
                      pathname === '/settings'
                        ? 'bg-gray-50 text-blue-600'
                        : 'text-gray-700 hover:text-blue-600 hover:bg-gray-50',
                      'group flex gap-x-3 rounded-md p-2 text-sm leading-6 font-semibold w-full text-left',
                      collapsed && 'justify-center px-2'
                    )}
                    title={collapsed ? 'Settings' : ''}
                  >
                    <Settings
                      className={clsx(
                        pathname === '/settings' ? 'text-blue-600' : 'text-gray-400 group-hover:text-blue-600',
                        'h-6 w-6 shrink-0'
                      )}
                      aria-hidden="true"
                    />
                    {!collapsed && 'Settings'}
                  </button>
                </li>
              </ul>
              
              {/* Minimal status indicators when collapsed */}
              {collapsed && (
                <div className="mt-4 flex flex-col items-center space-y-2 py-2">
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
              )}
            </li>
          </ul>
        </nav>
      </div>
    </div>
  )

  return (
    <>
      <MobileSidebar />
      <DesktopSidebar />
    </>
  )
}