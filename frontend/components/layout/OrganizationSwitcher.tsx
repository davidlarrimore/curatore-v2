'use client'

/**
 * Organization Switcher component for system admins.
 *
 * Allows admins to switch between organizations or operate in system context.
 * Regular users see their organization name (non-clickable).
 *
 * Uses URL-based navigation for organization switching:
 * - System context: /system
 * - Organization context: /orgs/{orgSlug}
 */

import { Fragment, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { Menu, Transition } from '@headlessui/react'
import {
  ChevronDown,
  Building2,
  Settings,
  Check,
  Search,
  ExternalLink,
} from 'lucide-react'
import { useOrganization } from '@/lib/organization-context'
import { useAuth } from '@/lib/auth-context'

interface OrganizationSwitcherProps {
  isSystemMode?: boolean
}

export function OrganizationSwitcher({ isSystemMode = false }: OrganizationSwitcherProps) {
  const router = useRouter()
  const pathname = usePathname()
  const { user, isAdmin } = useAuth()
  const {
    currentOrganization,
    availableOrganizations,
    mode,
    isLoading,
    switchOrganization,
    switchToSystemContext,
  } = useOrganization()

  const [searchQuery, setSearchQuery] = useState('')

  // Check if we're currently in URL-based org routing
  const orgSlugMatch = pathname?.match(/^\/orgs\/([^\/]+)/)
  const currentUrlOrgSlug = orgSlugMatch ? orgSlugMatch[1] : null

  // Navigate to an organization using URL-based routing
  const navigateToOrg = (org: { id: string; slug: string }) => {
    if (org.slug) {
      // Set localStorage for API client compatibility
      if (typeof window !== 'undefined') {
        localStorage.setItem('curatore_org_context', org.id)
      }
      router.push(`/orgs/${org.slug}`)
    } else {
      // Fallback: use context-based switching
      switchOrganization(org.id)
    }
  }

  // Navigate to system context
  const navigateToSystem = () => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('curatore_org_context', 'system')
    }
    router.push('/system')
  }

  // If not authenticated, don't show anything
  if (!user) return null

  // Non-admin users: show org name (non-clickable) - only show when there's an org
  if (!isAdmin) {
    if (!user.organization_name) return null
    return (
      <div className={`flex items-center gap-2 px-3 py-2 text-sm font-medium ${
        isSystemMode ? 'text-white/90' : 'text-gray-700 dark:text-gray-300'
      }`}>
        <Building2 className="h-4 w-4" />
        <span className="truncate max-w-[160px]">
          {user.organization_name}
        </span>
      </div>
    )
  }

  // Admin users: show switcher dropdown
  const filteredOrgs = searchQuery
    ? availableOrganizations.filter(org =>
        org.display_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        org.name.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : availableOrganizations

  const displayText = mode === 'system'
    ? 'System'
    : currentOrganization?.display_name || 'Select Organization'

  return (
    <Menu as="div" className="relative">
      <Menu.Button className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
        isSystemMode
          ? 'text-white hover:bg-white/10'
          : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
      }`}>
        {mode === 'system' ? (
          <Settings className="h-4 w-4" />
        ) : (
          <Building2 className="h-4 w-4" />
        )}
        <span className="truncate max-w-[160px]">{displayText}</span>
        <ChevronDown className="h-4 w-4" />
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
        <Menu.Items className="absolute left-0 mt-2 w-72 origin-top-left rounded-lg bg-white shadow-lg ring-1 ring-black/5 focus:outline-none z-50">
          {/* Search input */}
          {availableOrganizations.length > 5 && (
            <div className="p-2 border-b border-slate-200">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <input
                  type="text"
                  placeholder="Search organizations..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-9 pr-3 py-1.5 text-sm border border-slate-200 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  onClick={(e) => e.stopPropagation()}
                />
              </div>
            </div>
          )}

          <div className="py-1">
            {/* System context option */}
            <div className="px-3 py-1.5">
              <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">
                System Administration
              </span>
            </div>
            <Menu.Item>
              {({ active }) => (
                <a
                  href="/system"
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={() => setSearchQuery('')}
                  className={`${
                    active ? 'bg-slate-100' : ''
                  } ${
                    mode === 'system' ? 'text-indigo-600 font-medium' : 'text-slate-700'
                  } flex w-full items-center gap-3 px-3 py-2 text-sm`}
                >
                  <Settings className="h-5 w-5" />
                  <span className="flex-1 text-left">System Context</span>
                  {mode === 'system' ? (
                    <Check className="h-4 w-4 text-indigo-600" />
                  ) : (
                    <ExternalLink className="h-3.5 w-3.5 text-slate-400" />
                  )}
                </a>
              )}
            </Menu.Item>

            {/* Divider */}
            <div className="my-1 border-t border-slate-200" />

            {/* Organizations list */}
            <div className="px-3 py-1.5">
              <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">
                Organizations
              </span>
            </div>

            <div className="max-h-60 overflow-y-auto">
              {isLoading ? (
                <div className="px-3 py-2 text-sm text-slate-500">Loading...</div>
              ) : filteredOrgs.length === 0 ? (
                <div className="px-3 py-2 text-sm text-slate-500">
                  {searchQuery ? 'No organizations found' : 'No organizations available'}
                </div>
              ) : (
                filteredOrgs.map((org) => {
                  // Check if this org is selected (by URL slug or context)
                  const isSelected = currentUrlOrgSlug === org.slug ||
                    (!currentUrlOrgSlug && currentOrganization?.id === org.id)

                  return (
                    <Menu.Item key={org.id}>
                      {({ active }) => (
                        <a
                          href={`/orgs/${org.slug}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={() => setSearchQuery('')}
                          className={`${
                            active ? 'bg-slate-100' : ''
                          } ${
                            isSelected ? 'text-indigo-600 font-medium' : 'text-slate-700'
                          } flex w-full items-center gap-3 px-3 py-2 text-sm`}
                        >
                          <Building2 className="h-5 w-5" />
                          <div className="flex-1 text-left truncate">
                            <div className="truncate">{org.display_name}</div>
                            {org.slug && (
                              <div className="text-xs text-slate-400">{org.slug}</div>
                            )}
                          </div>
                          {isSelected ? (
                            <Check className="h-4 w-4 text-indigo-600" />
                          ) : (
                            <ExternalLink className="h-3.5 w-3.5 text-slate-400" />
                          )}
                        </a>
                      )}
                    </Menu.Item>
                  )
                })
              )}
            </div>
          </div>
        </Menu.Items>
      </Transition>
    </Menu>
  )
}
