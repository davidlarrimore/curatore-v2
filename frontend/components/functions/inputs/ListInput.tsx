'use client'

import { useState, KeyboardEvent } from 'react'
import { type FunctionParameter } from '@/lib/api'
import { Plus, X } from 'lucide-react'

interface ListInputProps {
  param: FunctionParameter
  value: string[]
  onChange: (value: string[]) => void
  disabled?: boolean
}

export function ListInput({ param, value, onChange, disabled }: ListInputProps) {
  const [inputValue, setInputValue] = useState('')

  const addItem = () => {
    const trimmed = inputValue.trim()
    if (trimmed && !value.includes(trimmed)) {
      onChange([...value, trimmed])
      setInputValue('')
    }
  }

  const removeItem = (item: string) => {
    onChange(value.filter((v) => v !== item))
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      addItem()
    }
  }

  const placeholder = param.example !== undefined
    ? Array.isArray(param.example) ? param.example[0] : String(param.example)
    : `Add item to ${param.name}`

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          className="flex-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed"
        />
        <button
          type="button"
          onClick={addItem}
          disabled={disabled || !inputValue.trim()}
          className="px-3 py-2 text-sm font-medium rounded-lg bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>

      {value.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {value.map((item) => (
            <span
              key={item}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300"
            >
              {item}
              <button
                type="button"
                onClick={() => removeItem(item)}
                disabled={disabled}
                className="ml-1 hover:text-indigo-900 dark:hover:text-indigo-100 disabled:opacity-50"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      {value.length === 0 && (
        <p className="text-xs text-gray-400 dark:text-gray-500">
          No items added. Type and press Enter or click + to add.
        </p>
      )}
    </div>
  )
}
