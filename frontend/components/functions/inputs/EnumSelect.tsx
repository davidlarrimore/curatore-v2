'use client'

import { type FunctionParameter } from '@/lib/api'

interface EnumSelectProps {
  param: FunctionParameter
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}

/**
 * Parse enum option which may be in "value|label" format or just "value".
 * Returns { value, label } where label defaults to value if not specified.
 */
function parseEnumOption(option: string): { value: string; label: string } {
  const pipeIndex = option.indexOf('|')
  if (pipeIndex > -1) {
    return {
      value: option.substring(0, pipeIndex),
      label: option.substring(pipeIndex + 1),
    }
  }
  return { value: option, label: option }
}

export function EnumSelect({ param, value, onChange, disabled }: EnumSelectProps) {
  const rawOptions = param.enum_values || []
  const options = rawOptions.map(parseEnumOption)
  const defaultValue = param.default !== undefined ? String(param.default) : ''

  return (
    <select
      value={value || defaultValue}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {!param.required && (
        <option value="">Select {param.name}...</option>
      )}
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  )
}
