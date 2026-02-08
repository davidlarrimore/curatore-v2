// components/layout/LeftSidebar.tsx
'use client'

import { usePathname } from 'next/navigation'
import { Fragment } from 'react'
import { Dialog, Transition } from '@headlessui/react'
import Link from 'next/link'
import {
  X,
  FileText,
  PanelLeftOpen,
  PanelLeftClose,
  Shield,
  HardDrive,
  Zap,
  ChevronRight,
  LayoutDashboard,
  Globe,
  Search,
  Building2,
  FolderSync,
  Activity,
  Code,
  Workflow,
  GitBranch,
  Database,
  TrendingUp,
  Tags,
} from 'lucide-react'
import { useAuth } from '@/lib/auth-context'
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
  gradient?: string
}

export function LeftSidebar({
  open,
  collapsed,
  onOpenChange,
  onCollapsedChange,
  systemStatus,
  onStatusRefresh
}: LeftSidebarProps) {
  const pathname = usePathname()
  const { user, isAuthenticated } = useAuth()

  // Navigation items with gradients for active states
  const navigation: NavItem[] = [
    {
      name: 'Dashboard',
      href: '/',
      icon: LayoutDashboard,
      current: pathname === '/',
      gradient: 'from-indigo-500 to-purple-600'
    },
    ...(isAuthenticated ? [
      {
        name: 'Assets',
        href: '/assets',
        icon: FileText,
        current: pathname?.startsWith('/assets'),
        gradient: 'from-indigo-500 to-blue-600'
      }
    ] : []),
    ...(isAuthenticated && user?.role === 'org_admin' ? [
      {
        name: 'Storage',
        href: '/storage',
        icon: HardDrive,
        current: pathname?.startsWith('/storage'),
        gradient: 'from-emerald-500 to-teal-500'
      }
    ] : []),
    ...(isAuthenticated ? [
      {
        name: 'Search',
        href: '/search',
        icon: Search,
        current: pathname?.startsWith('/search'),
        gradient: 'from-amber-500 to-orange-500'
      }
    ] : [])
  ]

  // Acquire section items
  const acquireNavigation: NavItem[] = isAuthenticated ? [
    {
      name: 'SharePoint Sync',
      href: '/sharepoint-sync',
      icon: FolderSync,
      current: pathname?.startsWith('/sharepoint-sync'),
      gradient: 'from-teal-500 to-cyan-600'
    },
    {
      name: 'Web Scraping',
      href: '/scrape',
      icon: Globe,
      current: pathname?.startsWith('/scrape'),
      gradient: 'from-indigo-500 to-purple-600'
    },
    {
      name: 'SAM.gov',
      href: '/sam',
      icon: Building2,
      current: pathname?.startsWith('/sam'),
      gradient: 'from-blue-500 to-indigo-600'
    },
    {
      name: 'Acquisition Forecasts',
      href: '/forecasts',
      icon: TrendingUp,
      current: pathname?.startsWith('/forecasts'),
      gradient: 'from-emerald-500 to-teal-600'
    },
    {
      name: 'Salesforce CRM',
      href: '/salesforce',
      icon: Database,
      current: pathname?.startsWith('/salesforce'),
      gradient: 'from-cyan-500 to-blue-600'
    }
  ] : []

  // Build section items
  const buildNavigation: NavItem[] = isAuthenticated && user?.role === 'org_admin' ? [
    {
      name: 'Functions',
      href: '/admin/functions',
      icon: Code,
      current: pathname === '/admin/functions',
      gradient: 'from-purple-500 to-indigo-600'
    },
    {
      name: 'Procedures',
      href: '/admin/procedures',
      icon: Workflow,
      current: pathname === '/admin/procedures',
      gradient: 'from-emerald-500 to-teal-600'
    },
    {
      name: 'Pipelines',
      href: '/admin/pipelines',
      icon: GitBranch,
      current: pathname === '/admin/pipelines',
      gradient: 'from-blue-500 to-indigo-600'
    }
  ] : []

  // Admin section items
  const adminNavigation: NavItem[] = isAuthenticated && user?.role === 'org_admin' ? [
    {
      name: 'Job Manager',
      href: '/admin/queue',
      icon: Activity,
      current: pathname === '/admin/queue',
      gradient: 'from-indigo-500 to-purple-600'
    },
    {
      name: 'Metadata',
      href: '/admin/metadata',
      icon: Tags,
      current: pathname === '/admin/metadata',
      gradient: 'from-teal-500 to-emerald-600'
    },
    {
      name: 'Admin Settings',
      href: '/settings-admin',
      icon: Shield,
      current: pathname === '/settings-admin',
      gradient: 'from-red-500 to-rose-600'
    }
  ] : []

  // Reusable NavLink component
  const NavLink = ({ item, isMobile = false }: { item: NavItem; isMobile?: boolean }) => (
    <Link
      href={item.href}
      onClick={isMobile ? () => onOpenChange(false) : undefined}
      className={clsx(
        "w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200",
        item.current
          ? "bg-gradient-to-r text-white shadow-lg"
          : "text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800",
        item.current && item.gradient,
        collapsed && !isMobile && "justify-center px-2"
      )}
      title={collapsed && !isMobile ? item.name : ''}
    >
      <item.icon
        className={clsx(
          "w-5 h-5 shrink-0",
          item.current ? "text-white" : "text-gray-400 dark:text-gray-500"
        )}
      />
      {(!collapsed || isMobile) && (
        <>
          <span className="flex-1 text-left">{item.name}</span>
          {item.current && (
            <ChevronRight className="w-4 h-4 text-white/70" />
          )}
          {item.badge && (
            <span className="px-1.5 py-0.5 text-xs font-medium bg-white/20 rounded-md">
              {item.badge}
            </span>
          )}
        </>
      )}
    </Link>
  )

  // Sidebar content (shared between mobile and desktop)
  const SidebarContent = ({ isMobile = false }: { isMobile?: boolean }) => (
    <div className="flex grow flex-col h-full bg-white dark:bg-gray-900">
      {/* Header */}
      <div className={clsx(
        "flex shrink-0 items-center justify-between px-4 border-b border-gray-100 dark:border-gray-800",
        collapsed && !isMobile ? "h-16 justify-center" : "h-16"
      )}>
        {(!collapsed || isMobile) && (
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/25">
              <Zap className="w-4 h-4 text-white" />
            </div>
            <div>
              <h1 className="text-base font-bold text-gray-900 dark:text-white">Curatorè</h1>
              <p className="text-[10px] text-gray-500 dark:text-gray-400 -mt-0.5">Data Platform</p>
            </div>
          </div>
        )}
        {!isMobile && (
          <button
            onClick={() => onCollapsedChange(!collapsed)}
            className={clsx(
              "p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors",
              collapsed && "mx-auto"
            )}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? (
              <PanelLeftOpen className="w-4 h-4" />
            ) : (
              <PanelLeftClose className="w-4 h-4" />
            )}
          </button>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-4 px-3">
        {(!collapsed || isMobile) && (
          <p className="px-3 mb-2 text-[10px] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider">
            Navigation
          </p>
        )}
        <ul className="space-y-1">
          {navigation.map((item) => (
            <li key={item.name}>
              <NavLink item={item} isMobile={isMobile} />
            </li>
          ))}
        </ul>

        {/* Acquire section */}
        {isAuthenticated && acquireNavigation.length > 0 && (
          <div className="mt-4 space-y-1">
            {(!collapsed || isMobile) && (
              <p className="px-3 mb-2 text-[10px] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider">
                Acquire
              </p>
            )}
            {acquireNavigation.map((item) => (
              <NavLink key={item.name} item={item} isMobile={isMobile} />
            ))}
          </div>
        )}

        {/* Build section */}
        {buildNavigation.length > 0 && (
          <div className="mt-4 space-y-1">
            {(!collapsed || isMobile) && (
              <p className="px-3 mb-2 text-[10px] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider">
                Build
              </p>
            )}
            {buildNavigation.map((item) => (
              <NavLink key={item.name} item={item} isMobile={isMobile} />
            ))}
          </div>
        )}
      </nav>

      {/* Bottom section - Admin */}
      {adminNavigation.length > 0 && (
        <div className="mt-auto border-t border-gray-100 dark:border-gray-800 p-3 space-y-2">
          {(!collapsed || isMobile) && (
            <p className="px-3 mb-1 text-[10px] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider">
              Admin
            </p>
          )}
          {adminNavigation.map((item) => (
            <NavLink key={item.name} item={item} isMobile={isMobile} />
          ))}
        </div>
      )}
    </div>
  )

  // Mobile sidebar
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
          <div className="fixed inset-0 bg-gray-900/80 backdrop-blur-sm" />
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
                    className="p-2 rounded-lg bg-white/10 hover:bg-white/20 transition-colors"
                    onClick={() => onOpenChange(false)}
                  >
                    <span className="sr-only">Close sidebar</span>
                    <X className="h-5 w-5 text-white" aria-hidden="true" />
                  </button>
                </div>
              </Transition.Child>

              <div className="flex grow flex-col overflow-y-auto bg-white dark:bg-gray-900 shadow-2xl">
                <SidebarContent isMobile={true} />
              </div>
            </Dialog.Panel>
          </Transition.Child>
        </div>
      </Dialog>
    </Transition.Root>
  )

  // Desktop sidebar
  const DesktopSidebar = () => (
    <div className={clsx(
      "hidden lg:fixed lg:inset-y-0 lg:z-10 lg:flex lg:flex-col transition-all duration-300 border-r border-gray-200 dark:border-gray-800",
      collapsed ? "lg:w-16" : "lg:w-64"
    )}>
      <SidebarContent isMobile={false} />
    </div>
  )

  return (
    <>
      <MobileSidebar />
      <DesktopSidebar />
    </>
  )
}
