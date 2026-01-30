'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard,
  Settings,
  FileText,
  Building2,
} from 'lucide-react'

interface NavItem {
  href: string
  label: string
  icon: React.ElementType
  exact?: boolean
}

const navItems: NavItem[] = [
  { href: '/sam', label: 'Dashboard', icon: LayoutDashboard, exact: true },
  { href: '/sam/setup', label: 'Setup', icon: Settings },
  { href: '/sam/notices', label: 'Notices', icon: FileText },
  { href: '/sam/solicitations', label: 'Solicitations', icon: Building2 },
]

export default function SamNavigation() {
  const pathname = usePathname()

  const isActive = (item: NavItem) => {
    if (item.exact) {
      return pathname === item.href
    }
    return pathname.startsWith(item.href)
  }

  return (
    <div className="flex flex-wrap items-center gap-2 mb-6">
      {navItems.map((item) => {
        const Icon = item.icon
        const active = isActive(item)

        return (
          <Link
            key={item.href}
            href={item.href}
            className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              active
                ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 shadow-sm'
                : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white'
            }`}
          >
            <Icon className="w-4 h-4" />
            <span>{item.label}</span>
          </Link>
        )
      })}
    </div>
  )
}
