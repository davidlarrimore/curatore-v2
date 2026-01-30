'use client'

import { useRouter } from 'next/navigation'
import { Plus, Link2, Settings, FolderOpen, FileText, Search } from 'lucide-react'

interface QuickActionsCardProps {
  isAdmin: boolean
}

export function QuickActionsCard({ isAdmin }: QuickActionsCardProps) {
  const router = useRouter()

  const actions = [
    {
      name: 'Upload Files',
      description: 'Add documents to process',
      icon: Plus,
      href: '/assets',
      gradient: 'from-violet-500 to-purple-600',
      shadowColor: 'shadow-violet-500/25',
      primary: true,
    },
    {
      name: 'Browse Assets',
      description: 'View processed files',
      icon: FileText,
      href: '/assets',
      gradient: 'from-emerald-500 to-teal-500',
      shadowColor: 'shadow-emerald-500/25',
    },
    {
      name: 'Browse Storage',
      description: 'View uploaded files',
      icon: FolderOpen,
      href: '/storage',
      gradient: 'from-blue-500 to-cyan-500',
      shadowColor: 'shadow-blue-500/25',
      adminOnly: true,
    },
    {
      name: 'Connections',
      description: 'Manage integrations',
      icon: Link2,
      href: '/connections',
      gradient: 'from-indigo-500 to-purple-600',
      shadowColor: 'shadow-indigo-500/25',
    },
  ]

  const filteredActions = actions.filter(action => !action.adminOnly || isAdmin)

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
      <div className="p-5">
        {/* Header */}
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-white shadow-lg shadow-indigo-500/25">
            <Settings className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-gray-900 dark:text-white">Quick Actions</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">Common tasks and navigation</p>
          </div>
        </div>

        {/* Actions Grid */}
        <div className="grid grid-cols-2 gap-3">
          {filteredActions.map((action) => {
            const Icon = action.icon
            return (
              <button
                key={action.name}
                onClick={() => router.push(action.href)}
                className={`group flex flex-col items-center p-4 rounded-xl transition-all duration-200 ${
                  action.primary
                    ? `bg-gradient-to-br ${action.gradient} text-white shadow-lg ${action.shadowColor} hover:shadow-xl hover:scale-[1.02]`
                    : 'bg-gray-50 dark:bg-gray-900/50 hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300'
                }`}
              >
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center mb-2 transition-transform group-hover:scale-110 ${
                  action.primary
                    ? 'bg-white/20'
                    : `bg-gradient-to-br ${action.gradient} text-white shadow-lg ${action.shadowColor}`
                }`}>
                  <Icon className="w-5 h-5" />
                </div>
                <span className={`text-sm font-medium ${action.primary ? 'text-white' : 'text-gray-900 dark:text-white'}`}>
                  {action.name}
                </span>
                <span className={`text-xs mt-0.5 ${action.primary ? 'text-white/70' : 'text-gray-500 dark:text-gray-400'}`}>
                  {action.description}
                </span>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
