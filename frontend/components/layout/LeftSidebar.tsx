// components/layout/LeftSidebar.tsx
'use client'

import { usePathname } from 'next/navigation'
import { Fragment } from 'react'
import { Dialog, Transition } from '@headlessui/react'
import Link from 'next/link'
import {
  X,
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
  Settings,
  Users,
  Plug,
  Server,
  Wrench,
  Calendar,
  Library,
} from 'lucide-react'
import { useAuth } from '@/lib/auth-context'
import { useOrganization } from '@/lib/organization-context'
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
  const { user, isAuthenticated, isAdmin } = useAuth()
  const { mode, currentOrganization } = useOrganization()

  // Determine if we're in system mode (admin with no org selected)
  const isSystemMode = isAdmin && mode === 'system'

  // Check if we're in a URL-based org route (/orgs/[orgSlug]/...)
  const orgSlugMatch = pathname?.match(/^\/orgs\/([^\/]+)/)
  const urlOrgSlug = orgSlugMatch ? orgSlugMatch[1] : null

  // Use URL-based org slug if available, otherwise fall back to context org slug
  const activeOrgSlug = urlOrgSlug || currentOrganization?.slug

  // Helper to generate org-scoped URLs
  const orgUrl = (path: string) => {
    if (isSystemMode) return path // System mode uses flat URLs
    if (activeOrgSlug) return `/orgs/${activeOrgSlug}${path}`
    return path // Fallback to flat URLs
  }

  // Check if path matches considering both old and new URL structures
  const isCurrentPath = (path: string, startsWithMatch = false) => {
    if (!pathname) return false
    // For org routes, we need to check both old and new URL patterns
    const normalizedPath = path.replace(/^\/orgs\/[^\/]+/, '')
    const normalizedPathname = pathname.replace(/^\/orgs\/[^\/]+/, '')
    if (startsWithMatch) {
      return normalizedPathname.startsWith(normalizedPath)
    }
    return normalizedPathname === normalizedPath || pathname === path
  }

  // Navigation items with gradients for active states
  const navigation: NavItem[] = [
    {
      name: 'Dashboard',
      href: orgUrl(''),
      icon: LayoutDashboard,
      current: isCurrentPath('') || isCurrentPath('/'),
      gradient: 'from-indigo-500 to-purple-600'
    },
    ...(isAuthenticated ? [
      {
        name: 'Storage Browser',
        href: orgUrl('/storage'),
        icon: HardDrive,
        current: isCurrentPath('/storage', true),
        gradient: 'from-emerald-500 to-teal-500'
      },
      {
        name: 'Search',
        href: orgUrl('/search'),
        icon: Search,
        current: isCurrentPath('/search', true),
        gradient: 'from-amber-500 to-orange-500'
      }
    ] : [])
  ]

  // Acquire section items (syncs in URL-based routing)
  const acquireNavigation: NavItem[] = isAuthenticated ? [
    {
      name: 'SharePoint Sync',
      href: orgUrl('/syncs/sharepoint'),
      icon: FolderSync,
      current: isCurrentPath('/syncs/sharepoint', true) || isCurrentPath('/sharepoint-sync', true),
      gradient: 'from-teal-500 to-cyan-600'
    },
    {
      name: 'Web Scraping',
      href: orgUrl('/syncs/scrape'),
      icon: Globe,
      current: isCurrentPath('/syncs/scrape', true) || isCurrentPath('/scrape', true),
      gradient: 'from-indigo-500 to-purple-600'
    },
    {
      name: 'SAM.gov',
      href: orgUrl('/syncs/sam'),
      icon: Building2,
      current: isCurrentPath('/syncs/sam', true) || isCurrentPath('/sam', true),
      gradient: 'from-blue-500 to-indigo-600'
    },
    {
      name: 'Acquisition Forecasts',
      href: orgUrl('/syncs/forecasts'),
      icon: TrendingUp,
      current: isCurrentPath('/syncs/forecasts', true) || isCurrentPath('/forecasts', true),
      gradient: 'from-emerald-500 to-teal-600'
    },
    {
      name: 'Salesforce CRM',
      href: orgUrl('/syncs/salesforce'),
      icon: Database,
      current: isCurrentPath('/syncs/salesforce', true) || isCurrentPath('/salesforce', true),
      gradient: 'from-cyan-500 to-blue-600'
    }
  ] : []

  // Build section items (org context only)
  const buildNavigation: NavItem[] = isAuthenticated && (user?.role === 'org_admin' || isAdmin) && !isSystemMode ? [
    {
      name: 'Functions',
      href: orgUrl('/admin/functions'),
      icon: Code,
      current: isCurrentPath('/admin/functions', true),
      gradient: 'from-purple-500 to-indigo-600'
    },
    {
      name: 'Procedures',
      href: orgUrl('/admin/procedures'),
      icon: Workflow,
      current: isCurrentPath('/admin/procedures', true),
      gradient: 'from-emerald-500 to-teal-600'
    },
    {
      name: 'Pipelines',
      href: orgUrl('/admin/pipelines'),
      icon: GitBranch,
      current: isCurrentPath('/admin/pipelines', true),
      gradient: 'from-blue-500 to-indigo-600'
    },
    {
      name: 'Collections',
      href: orgUrl('/collections'),
      icon: Library,
      current: isCurrentPath('/collections', true),
      gradient: 'from-indigo-500 to-purple-600'
    }
  ] : []

  // Admin section items (org context)
  const adminNavigation: NavItem[] = isAuthenticated && (user?.role === 'org_admin' || isAdmin) && !isSystemMode ? [
    {
      name: 'Job Manager',
      href: orgUrl('/jobs'),
      icon: Activity,
      current: isCurrentPath('/jobs', true),
      gradient: 'from-indigo-500 to-purple-600'
    },
    {
      name: 'Metadata Catalog',
      href: orgUrl('/admin/metadata'),
      icon: Tags,
      current: isCurrentPath('/admin/metadata', true),
      gradient: 'from-teal-500 to-emerald-600'
    },
    {
      name: 'Users',
      href: orgUrl('/admin/users'),
      icon: Users,
      current: isCurrentPath('/admin/users', true),
      gradient: 'from-blue-500 to-indigo-600'
    },
    {
      name: 'Org Settings',
      href: orgUrl('/admin/settings'),
      icon: Shield,
      current: isCurrentPath('/admin/settings', true),
      gradient: 'from-red-500 to-rose-600'
    }
  ] : []

  // System navigation (admin only, system mode)
  const systemNavigation: NavItem[] = isSystemMode ? [
    {
      name: 'System Dashboard',
      href: '/system',
      icon: LayoutDashboard,
      current: pathname === '/system',
      gradient: 'from-amber-500 to-orange-600'
    },
    {
      name: 'Organizations',
      href: '/system/organizations',
      icon: Building2,
      current: pathname?.startsWith('/system/organizations'),
      gradient: 'from-amber-500 to-orange-600'
    },
    {
      name: 'Job Manager',
      href: '/system/jobs',
      icon: Activity,
      current: pathname?.startsWith('/system/jobs'),
      gradient: 'from-amber-500 to-orange-600'
    }
  ] : []

  // System services navigation
  const systemServicesNavigation: NavItem[] = isSystemMode ? [
    {
      name: 'Services',
      href: '/system/services',
      icon: Server,
      current: pathname?.startsWith('/system/services'),
      gradient: 'from-amber-500 to-orange-600'
    },
    {
      name: 'Connections',
      href: '/system/connections',
      icon: Plug,
      current: pathname?.startsWith('/system/connections'),
      gradient: 'from-amber-500 to-orange-600'
    }
  ] : []

  // System admin navigation
  const systemAdminNavigation: NavItem[] = isSystemMode ? [
    {
      name: 'Maintenance',
      href: '/system/maintenance',
      icon: Wrench,
      current: pathname?.startsWith('/system/maintenance'),
      gradient: 'from-amber-500 to-orange-600'
    },
    {
      name: 'Scheduled Tasks',
      href: '/system/scheduled-tasks',
      icon: Calendar,
      current: pathname?.startsWith('/system/scheduled-tasks'),
      gradient: 'from-amber-500 to-orange-600'
    },
    {
      name: 'All Users',
      href: '/system/users',
      icon: Users,
      current: pathname?.startsWith('/system/users'),
      gradient: 'from-amber-500 to-orange-600'
    },
    {
      name: 'System Settings',
      href: '/system/settings',
      icon: Settings,
      current: pathname?.startsWith('/system/settings'),
      gradient: 'from-amber-500 to-orange-600'
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
    <div className={clsx(
      "flex grow flex-col h-full",
      isSystemMode ? "bg-amber-50 dark:bg-amber-950/20" : "bg-white dark:bg-gray-900"
    )}>
      {/* Header */}
      <div className={clsx(
        "flex shrink-0 items-center justify-between px-4 border-b",
        isSystemMode ? "border-amber-200 dark:border-amber-800/50" : "border-gray-100 dark:border-gray-800",
        collapsed && !isMobile ? "h-16 justify-center" : "h-16"
      )}>
        {(!collapsed || isMobile) && (
          <div className="flex items-center gap-3">
            <div className={clsx(
              "w-8 h-8 rounded-xl flex items-center justify-center shadow-lg",
              isSystemMode
                ? "bg-gradient-to-br from-amber-500 to-orange-600 shadow-amber-500/25"
                : "bg-gradient-to-br from-indigo-500 to-purple-600 shadow-indigo-500/25"
            )}>
              {isSystemMode ? (
                <Settings className="w-4 h-4 text-white" />
              ) : (
                <Zap className="w-4 h-4 text-white" />
              )}
            </div>
            <div>
              <h1 className="text-base font-bold text-gray-900 dark:text-white">
                {isSystemMode ? 'System' : 'Curatorè'}
              </h1>
              <p className={clsx(
                "text-[10px] -mt-0.5",
                isSystemMode ? "text-amber-600 dark:text-amber-400" : "text-gray-500 dark:text-gray-400"
              )}>
                {isSystemMode ? 'Administration' : (currentOrganization?.display_name || 'Data Platform')}
              </p>
            </div>
          </div>
        )}
        {!isMobile && (
          <button
            onClick={() => onCollapsedChange(!collapsed)}
            className={clsx(
              "p-1.5 rounded-lg transition-colors",
              isSystemMode
                ? "text-amber-500 hover:text-amber-700 hover:bg-amber-100 dark:hover:bg-amber-900/30"
                : "text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800",
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
        {/* System Mode Navigation */}
        {isSystemMode ? (
          <>
            {/* System navigation */}
            {(!collapsed || isMobile) && (
              <p className="px-3 mb-2 text-[10px] font-semibold text-amber-600 dark:text-amber-400 uppercase tracking-wider">
                System
              </p>
            )}
            <ul className="space-y-1">
              {systemNavigation.map((item) => (
                <li key={item.name}>
                  <NavLink item={item} isMobile={isMobile} />
                </li>
              ))}
            </ul>

            {/* Services section */}
            {systemServicesNavigation.length > 0 && (
              <div className="mt-4 space-y-1">
                {(!collapsed || isMobile) && (
                  <p className="px-3 mb-2 text-[10px] font-semibold text-amber-600 dark:text-amber-400 uppercase tracking-wider">
                    Infrastructure
                  </p>
                )}
                {systemServicesNavigation.map((item) => (
                  <NavLink key={item.name} item={item} isMobile={isMobile} />
                ))}
              </div>
            )}

            {/* System Admin section */}
            {systemAdminNavigation.length > 0 && (
              <div className="mt-4 space-y-1">
                {(!collapsed || isMobile) && (
                  <p className="px-3 mb-2 text-[10px] font-semibold text-amber-600 dark:text-amber-400 uppercase tracking-wider">
                    Administration
                  </p>
                )}
                {systemAdminNavigation.map((item) => (
                  <NavLink key={item.name} item={item} isMobile={isMobile} />
                ))}
              </div>
            )}
          </>
        ) : (
          <>
            {/* Organization Mode Navigation */}
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
          </>
        )}
      </nav>

      {/* Bottom section - Admin (org context only) */}
      {!isSystemMode && adminNavigation.length > 0 && (
        <div className="mt-auto border-t border-gray-100 dark:border-gray-800 p-3 space-y-2">
          {(!collapsed || isMobile) && (
            <p className="px-3 mb-1 text-[10px] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider">
              Org Admin
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
      "hidden lg:fixed lg:inset-y-0 lg:z-10 lg:flex lg:flex-col transition-all duration-300 border-r",
      isSystemMode ? "border-amber-200 dark:border-amber-800/50" : "border-gray-200 dark:border-gray-800",
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
