'use client'

import { type FunctionParameter } from '@/lib/api'

interface NumberInputProps {
  param: FunctionParameter
  value: number | string
  onChange: (value: number | undefined) => void
  disabled?: boolean
}

export function NumberInput({ param, value, onChange, disabled }: NumberInputProps) {
  const isFloat = param.type === 'float'
  const placeholder = param.example !== undefined
    ? String(param.example)
    : param.default !== undefined
    ? String(param.default)
    : isFloat ? '0.0' : '0'

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value
    if (val === '') {
      onChange(undefined)
      return
    }
    const parsed = isFloat ? parseFloat(val) : parseInt(val, 10)
    if (!isNaN(parsed)) {
      onChange(parsed)
    }
  }

  return (
    <input
      type="number"
      value={value}
      onChange={handleChange}
      placeholder={placeholder}
      disabled={disabled}
      step={isFloat ? '0.1' : '1'}
      className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed"
    />
  )
}
