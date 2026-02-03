'use client'

import { type FunctionParameter } from '@/lib/api'

interface TextareaInputProps {
  param: FunctionParameter
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  rows?: number
}

export function TextareaInput({ param, value, onChange, disabled, rows = 4 }: TextareaInputProps) {
  const placeholder = param.example !== undefined
    ? String(param.example)
    : param.default !== undefined
    ? String(param.default)
    : `Enter ${param.name}`

  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      disabled={disabled}
      rows={rows}
      className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed resize-y font-mono"
    />
  )
}
