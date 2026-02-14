// components/layout/TopNavigation.tsx
'use client'

/**
 * AWS Console-inspired top navigation.
 *
 * Layout: Logo | Page Title/Breadcrumbs | ... spacer ... | Org Switcher | User Menu
 */

import { useState, Fragment } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { Menu, Transition } from '@headlessui/react'
import {
  Menu as MenuIcon,
  ChevronDown,
  Settings,
  User,
  LogOut,
  HelpCircle,
  BookOpen,
  Building2,
} from 'lucide-react'
import { useAuth } from '@/lib/auth-context'
import { useOrganization } from '@/lib/organization-context'
import Image from 'next/image'
import toast from 'react-hot-toast'

interface TopNavigationProps {
  onMenuClick: () => void
  sidebarCollapsed: boolean
}

export function TopNavigation({
  onMenuClick,
  sidebarCollapsed
}: TopNavigationProps) {
  const pathname = usePathname()
  const router = useRouter()
  const { user, isAuthenticated, isAdmin, logout } = useAuth()
  const {
    currentOrganization,
    availableOrganizations,
    mode,
    isLoading: orgLoading,
  } = useOrganization()

  // Determine header styling based on system vs org mode
  const isSystemMode = isAdmin && mode === 'system'

  const handleLogout = () => {
    logout()
    router.push('/login')
    toast.success('Logged out successfully')
  }

  // Get current page title from pathname
  const getPageTitle = () => {
    const segments = pathname.split('/').filter(Boolean)
    if (segments.length === 0) return 'Dashboard'

    const friendlyNames: Record<string, string> = {
      'system': 'System Administration',
      'admin': 'Administration',
      'assets': 'Assets',
      'search': 'Search',
      'settings': 'Settings',
      'connections': 'Connections',
      'procedures': 'Procedures',
      'functions': 'Functions',
      'pipelines': 'Pipelines',
      'queue': 'Job Queue',
      'sam': 'SAM.gov',
      'salesforce': 'Salesforce',
      'forecasts': 'Forecasts',
      'sharepoint-sync': 'SharePoint',
      'scrape': 'Web Scraping',
      'organizations': 'Organizations',
      'users': 'Users',
      'services': 'Services',
      'maintenance': 'Maintenance',
      'metadata': 'Metadata',
    }

    // Get the last meaningful segment
    const lastSegment = segments[segments.length - 1]
    return friendlyNames[lastSegment] || lastSegment.charAt(0).toUpperCase() + lastSegment.slice(1)
  }

  // Get organization display info
  const getOrgDisplay = () => {
    if (mode === 'system') {
      return { name: 'System', icon: Settings }
    }
    if (currentOrganization) {
      return { name: currentOrganization.display_name, icon: Building2 }
    }
    return { name: 'Select Organization', icon: Building2 }
  }

  const orgDisplay = getOrgDisplay()
  const OrgIcon = orgDisplay.icon

  return (
    <header className={`h-14 flex items-center justify-between px-4 transition-all duration-300 ${
      sidebarCollapsed ? 'lg:ml-16' : 'lg:ml-64'
    } ${
      isSystemMode
        ? 'bg-slate-900 border-b border-slate-800'
        : 'bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800'
    }`}>
      {/* Left section: Mobile menu + Logo + Page title */}
      <div className="flex items-center gap-4">
        {/* Mobile menu button */}
        <button
          onClick={onMenuClick}
          className={`lg:hidden p-2 -ml-2 rounded-md transition-colors ${
            isSystemMode
              ? 'text-slate-400 hover:text-white hover:bg-slate-800'
              : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800'
          }`}
          aria-label="Open navigation menu"
        >
          <MenuIcon className="w-5 h-5" />
        </button>

        {/* Logo - visible on mobile only since sidebar has it on desktop */}
        <div className="lg:hidden flex items-center gap-2">
          <Image
            src="/logo.png"
            alt="Curatore"
            width={28}
            height={28}
            className="object-contain"
          />
          <span className={`text-base font-semibold ${
            isSystemMode ? 'text-white' : 'text-slate-900 dark:text-white'
          }`}>
            Curatore
          </span>
        </div>

        {/* Page title / breadcrumb */}
        <div className="hidden sm:flex items-center">
          <h1 className={`text-sm font-medium ${
            isSystemMode ? 'text-white' : 'text-slate-900 dark:text-white'
          }`}>
            {getPageTitle()}
          </h1>
        </div>
      </div>

      {/* Right section: Org Switcher + User Menu */}
      <div className="flex items-center gap-1">
        {/* Organization Switcher - AWS-style dropdown */}
        {isAuthenticated && (
          <Menu as="div" className="relative">
            <Menu.Button className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-sm transition-colors ${
              isSystemMode
                ? 'text-slate-300 hover:text-white hover:bg-slate-800'
                : 'text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800'
            }`}>
              <OrgIcon className="h-4 w-4" />
              <span className="hidden sm:inline max-w-[140px] truncate font-medium">
                {orgDisplay.name}
              </span>
              {isSystemMode && (
                <span className="hidden md:inline px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide bg-amber-500 text-white rounded">
                  System
                </span>
              )}
              <ChevronDown className="h-4 w-4 opacity-50" />
            </Menu.Button>

            <Transition
              as={Fragment}
              enter="transition ease-out duration-100"
              enterFrom="transform opacity-0 scale-95"
              enterTo="transform opacity-100 scale-100"
              leave="transition ease-in duration-75"
              leaveFrom="transform opacity-100 scale-100"
              leaveTo="transform opacity-0 scale-95"
            >
              <Menu.Items className="absolute right-0 mt-2 w-72 origin-top-right rounded-lg bg-white dark:bg-slate-800 shadow-lg ring-1 ring-black/5 dark:ring-white/10 focus:outline-none z-50 overflow-hidden">
                {/* Current context display */}
                <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700">
                  <p className="text-xs font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wide mb-1">
                    Current Context
                  </p>
                  <p className="text-sm font-semibold text-slate-900 dark:text-white flex items-center gap-2">
                    <OrgIcon className="h-4 w-4 text-slate-400" />
                    {orgDisplay.name}
                  </p>
                </div>

                {/* Admin: System context option */}
                {isAdmin && (
                  <>
                    <div className="py-1">
                      <Menu.Item>
                        {({ active }) => (
                          <a
                            href="/system"
                            className={`${
                              active ? 'bg-slate-50 dark:bg-slate-700' : ''
                            } ${
                              mode === 'system' ? 'text-amber-600 dark:text-amber-400' : 'text-slate-700 dark:text-slate-300'
                            } flex w-full items-center gap-3 px-4 py-2.5 text-sm`}
                          >
                            <Settings className="h-4 w-4" />
                            <span className="flex-1 text-left font-medium">System Administration</span>
                            {mode === 'system' && (
                              <span className="text-xs bg-amber-100 dark:bg-amber-900/50 text-amber-700 dark:text-amber-300 px-2 py-0.5 rounded font-medium">
                                Active
                              </span>
                            )}
                          </a>
                        )}
                      </Menu.Item>
                    </div>
                    <div className="border-t border-slate-100 dark:border-slate-700" />
                  </>
                )}

                {/* Organizations list */}
                <div className="py-1">
                  <p className="px-4 py-2 text-xs font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wide">
                    Organizations
                  </p>
                  <div className="max-h-48 overflow-y-auto">
                    {orgLoading ? (
                      <div className="px-4 py-3 text-sm text-slate-500">Loading...</div>
                    ) : availableOrganizations.length === 0 && !isAdmin ? (
                      <div className="px-4 py-3 text-sm text-slate-500">
                        {currentOrganization?.display_name || 'No organization'}
                      </div>
                    ) : availableOrganizations.length === 0 ? (
                      <div className="px-4 py-3 text-sm text-slate-500">No organizations</div>
                    ) : (
                      availableOrganizations.map((org) => (
                        <Menu.Item key={org.id}>
                          {({ active }) => (
                            <a
                              href={`/orgs/${org.slug}`}
                              className={`${
                                active ? 'bg-slate-50 dark:bg-slate-700' : ''
                              } ${
                                currentOrganization?.id === org.id && mode !== 'system'
                                  ? 'text-indigo-600 dark:text-indigo-400'
                                  : 'text-slate-700 dark:text-slate-300'
                              } flex w-full items-center gap-3 px-4 py-2.5 text-sm`}
                            >
                              <Building2 className="h-4 w-4 text-slate-400" />
                              <span className="flex-1 text-left truncate">{org.display_name}</span>
                              {currentOrganization?.id === org.id && mode !== 'system' && (
                                <span className="text-xs bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 px-2 py-0.5 rounded font-medium">
                                  Active
                                </span>
                              )}
                            </a>
                          )}
                        </Menu.Item>
                      ))
                    )}
                  </div>
                </div>

                {/* Admin: Manage organizations link */}
                {isAdmin && (
                  <>
                    <div className="border-t border-slate-100 dark:border-slate-700" />
                    <div className="py-1">
                      <Menu.Item>
                        {({ active }) => (
                          <a
                            href="/system/organizations"
                            className={`${
                              active ? 'bg-slate-50 dark:bg-slate-700' : ''
                            } text-slate-600 dark:text-slate-400 flex w-full items-center gap-3 px-4 py-2.5 text-sm`}
                          >
                            <Settings className="h-4 w-4" />
                            <span>Manage Organizations</span>
                          </a>
                        )}
                      </Menu.Item>
                    </div>
                  </>
                )}
              </Menu.Items>
            </Transition>
          </Menu>
        )}

        {/* Divider */}
        <div className={`w-px h-6 mx-2 ${
          isSystemMode ? 'bg-slate-700' : 'bg-slate-200 dark:bg-slate-700'
        }`} />

        {/* User Menu - AWS-style dropdown */}
        {isAuthenticated ? (
          <Menu as="div" className="relative">
            <Menu.Button className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-sm transition-colors ${
              isSystemMode
                ? 'text-slate-300 hover:text-white hover:bg-slate-800'
                : 'text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800'
            }`}>
              <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold ${
                isSystemMode
                  ? 'bg-slate-700 text-slate-300'
                  : 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-600 dark:text-indigo-400'
              }`}>
                {user?.username?.charAt(0).toUpperCase() || 'U'}
              </div>
              <span className="hidden sm:inline max-w-[100px] truncate font-medium">
                {user?.username || user?.email?.split('@')[0]}
              </span>
              <ChevronDown className="h-4 w-4 opacity-50" />
            </Menu.Button>

            <Transition
              as={Fragment}
              enter="transition ease-out duration-100"
              enterFrom="transform opacity-0 scale-95"
              enterTo="transform opacity-100 scale-100"
              leave="transition ease-in duration-75"
              leaveFrom="transform opacity-100 scale-100"
              leaveTo="transform opacity-0 scale-95"
            >
              <Menu.Items className="absolute right-0 mt-2 w-64 origin-top-right rounded-lg bg-white dark:bg-slate-800 shadow-lg ring-1 ring-black/5 dark:ring-white/10 focus:outline-none z-50 overflow-hidden">
                {/* User info header */}
                <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700">
                  <p className="text-sm font-semibold text-slate-900 dark:text-white">
                    {user?.full_name || user?.username}
                  </p>
                  <p className="text-xs text-slate-500 dark:text-slate-400 truncate">
                    {user?.email}
                  </p>
                  <div className="mt-2 flex items-center gap-2">
                    <span className={`inline-flex items-center px-2 py-0.5 text-xs font-medium rounded ${
                      user?.role === 'admin'
                        ? 'bg-amber-100 dark:bg-amber-900/50 text-amber-700 dark:text-amber-300'
                        : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400'
                    }`}>
                      {user?.role === 'admin' ? 'System Admin' : 'Member'}
                    </span>
                  </div>
                </div>

                {/* Menu items */}
                <div className="py-1">
                  <Menu.Item>
                    {({ active }) => (
                      <button
                        onClick={() => router.push(currentOrganization?.slug ? `/orgs/${currentOrganization.slug}/admin/settings` : '/system/settings')}
                        className={`${
                          active ? 'bg-slate-50 dark:bg-slate-700' : ''
                        } text-slate-700 dark:text-slate-300 flex w-full items-center gap-3 px-4 py-2.5 text-sm`}
                      >
                        <Settings className="h-4 w-4 text-slate-400" />
                        <span>Settings</span>
                      </button>
                    )}
                  </Menu.Item>
                  <Menu.Item>
                    {({ active }) => (
                      <button
                        onClick={() => {
                          const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
                          window.open(`${apiBase}/api/v1/docs`, '_blank')
                        }}
                        className={`${
                          active ? 'bg-slate-50 dark:bg-slate-700' : ''
                        } text-slate-700 dark:text-slate-300 flex w-full items-center gap-3 px-4 py-2.5 text-sm`}
                      >
                        <BookOpen className="h-4 w-4 text-slate-400" />
                        <span>API Documentation</span>
                      </button>
                    )}
                  </Menu.Item>
                  <Menu.Item>
                    {({ active }) => (
                      <button
                        onClick={() => window.open('https://github.com/davidlarrimore/curatore-v2', '_blank')}
                        className={`${
                          active ? 'bg-slate-50 dark:bg-slate-700' : ''
                        } text-slate-700 dark:text-slate-300 flex w-full items-center gap-3 px-4 py-2.5 text-sm`}
                      >
                        <HelpCircle className="h-4 w-4 text-slate-400" />
                        <span>Help & Support</span>
                      </button>
                    )}
                  </Menu.Item>
                </div>

                {/* Logout */}
                <div className="border-t border-slate-100 dark:border-slate-700 py-1">
                  <Menu.Item>
                    {({ active }) => (
                      <button
                        onClick={handleLogout}
                        className={`${
                          active ? 'bg-red-50 dark:bg-red-900/20' : ''
                        } text-red-600 dark:text-red-400 flex w-full items-center gap-3 px-4 py-2.5 text-sm`}
                      >
                        <LogOut className="h-4 w-4" />
                        <span>Sign out</span>
                      </button>
                    )}
                  </Menu.Item>
                </div>
              </Menu.Items>
            </Transition>
          </Menu>
        ) : (
          <button
            onClick={() => router.push('/login')}
            className="flex items-center gap-2 px-4 py-1.5 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 transition-colors"
          >
            <User className="w-4 h-4" />
            Sign in
          </button>
        )}
      </div>
    </header>
  )
}
