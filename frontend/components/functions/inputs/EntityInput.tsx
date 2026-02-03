'use client'

import { useState } from 'react'
import { type FunctionParameter } from '@/lib/api'
import { Search, X, FileText, Briefcase, FolderOpen } from 'lucide-react'
import { AssetPickerDialog } from '../pickers/AssetPickerDialog'
import { SolicitationPickerDialog } from '../pickers/SolicitationPickerDialog'

interface EntityInputProps {
  param: FunctionParameter
  entityType: string
  value: string | string[] | undefined
  onChange: (value: string | string[] | undefined) => void
  disabled?: boolean
}

const ENTITY_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  asset: FileText,
  solicitation: Briefcase,
  collection: FolderOpen,
}

const ENTITY_LABELS: Record<string, string> = {
  asset: 'Asset',
  solicitation: 'Solicitation',
  collection: 'Collection',
}

export function EntityInput({ param, entityType, value, onChange, disabled }: EntityInputProps) {
  const [isPickerOpen, setIsPickerOpen] = useState(false)
  const isArray = param.type.includes('list') || param.type.includes('List') || param.name.endsWith('_ids')

  const Icon = ENTITY_ICONS[entityType] || Search
  const label = ENTITY_LABELS[entityType] || 'Entity'

  // Convert value to array for display
  const values = Array.isArray(value) ? value : value ? [value] : []

  const handleSelect = (selectedIds: string[]) => {
    if (isArray) {
      onChange(selectedIds)
    } else {
      onChange(selectedIds[0] || undefined)
    }
    setIsPickerOpen(false)
  }

  const handleRemove = (id: string) => {
    if (isArray) {
      onChange(values.filter((v) => v !== id))
    } else {
      onChange(undefined)
    }
  }

  const renderPicker = () => {
    switch (entityType) {
      case 'asset':
        return (
          <AssetPickerDialog
            isOpen={isPickerOpen}
            onClose={() => setIsPickerOpen(false)}
            onSelect={handleSelect}
            selectedIds={values}
            multiple={isArray}
          />
        )
      case 'solicitation':
        return (
          <SolicitationPickerDialog
            isOpen={isPickerOpen}
            onClose={() => setIsPickerOpen(false)}
            onSelect={handleSelect}
            selectedIds={values}
            multiple={isArray}
          />
        )
      default:
        return null
    }
  }

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => setIsPickerOpen(true)}
        disabled={disabled}
        className="w-full flex items-center gap-2 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-left"
      >
        <Icon className="w-4 h-4" />
        <span className="flex-1">
          {values.length > 0
            ? `${values.length} ${label}${values.length > 1 ? 's' : ''} selected`
            : `Select ${label}${isArray ? '(s)' : ''}...`}
        </span>
        <Search className="w-4 h-4" />
      </button>

      {values.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {values.map((id) => (
            <span
              key={id}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-mono bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 border border-gray-200 dark:border-gray-700"
            >
              <Icon className="w-3 h-3" />
              <span className="max-w-[150px] truncate">{id}</span>
              <button
                type="button"
                onClick={() => handleRemove(id)}
                disabled={disabled}
                className="ml-1 hover:text-red-600 dark:hover:text-red-400 disabled:opacity-50"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      {renderPicker()}
    </div>
  )
}
