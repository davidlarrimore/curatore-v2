'use client'

import { useState, useEffect } from 'react'
import { type FunctionParameter } from '@/lib/api'
import { AlertCircle, Check } from 'lucide-react'

interface JsonInputProps {
  param: FunctionParameter
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  value: Record<string, any> | undefined
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onChange: (value: Record<string, any> | undefined) => void
  disabled?: boolean
}

export function JsonInput({ param, value, onChange, disabled }: JsonInputProps) {
  const [textValue, setTextValue] = useState(() => {
    if (value !== undefined) {
      return JSON.stringify(value, null, 2)
    }
    if (param.example !== undefined) {
      return JSON.stringify(param.example, null, 2)
    }
    if (param.default !== undefined) {
      return JSON.stringify(param.default, null, 2)
    }
    return '{}'
  })
  const [error, setError] = useState<string | null>(null)
  const [isValid, setIsValid] = useState(true)

  // Validate JSON on change
  useEffect(() => {
    if (!textValue.trim()) {
      setError(null)
      setIsValid(true)
      return
    }

    try {
      JSON.parse(textValue)
      setError(null)
      setIsValid(true)
    } catch (e) {
      setError('Invalid JSON')
      setIsValid(false)
    }
  }, [textValue])

  const handleChange = (newValue: string) => {
    setTextValue(newValue)

    if (!newValue.trim()) {
      onChange(undefined)
      return
    }

    try {
      const parsed = JSON.parse(newValue)
      onChange(parsed)
    } catch {
      // Don't update parent if invalid JSON
    }
  }

  return (
    <div className="space-y-2">
      <div className="relative">
        <textarea
          value={textValue}
          onChange={(e) => handleChange(e.target.value)}
          disabled={disabled}
          rows={6}
          className={`
            w-full px-3 py-2 text-sm rounded-lg border bg-white dark:bg-gray-900 text-gray-900 dark:text-white
            placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:outline-none focus:ring-2
            disabled:opacity-50 disabled:cursor-not-allowed resize-y font-mono
            ${error ? 'border-red-300 dark:border-red-700 focus:ring-red-500' : 'border-gray-200 dark:border-gray-700 focus:ring-indigo-500'}
          `}
          placeholder={`{\n  "key": "value"\n}`}
        />
        <div className="absolute top-2 right-2">
          {isValid && textValue.trim() ? (
            <Check className="w-4 h-4 text-emerald-500" />
          ) : error ? (
            <AlertCircle className="w-4 h-4 text-red-500" />
          ) : null}
        </div>
      </div>

      {error && (
        <p className="text-xs text-red-600 dark:text-red-400 flex items-center gap-1">
          <AlertCircle className="w-3 h-3" />
          {error}
        </p>
      )}
    </div>
  )
}
