'use client'

import { type FunctionParameter } from '@/lib/api'

interface MultiEnumSelectProps {
  param: FunctionParameter
  value: string[]
  onChange: (value: string[]) => void
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

/**
 * Multi-select component for list parameters with enum values.
 * Displays checkboxes for each option.
 */
export function MultiEnumSelect({ param, value, onChange, disabled }: MultiEnumSelectProps) {
  const rawOptions = param.enum_values || []
  const options = rawOptions.map(parseEnumOption)
  const selectedValues = value || []

  const handleToggle = (optionValue: string) => {
    if (selectedValues.includes(optionValue)) {
      onChange(selectedValues.filter((v) => v !== optionValue))
    } else {
      onChange([...selectedValues, optionValue])
    }
  }

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-2">
        {options.map((option) => {
          const isSelected = selectedValues.includes(option.value)
          return (
            <label
              key={option.value}
              className={`
                inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border cursor-pointer transition-all
                ${
                  isSelected
                    ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300'
                    : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'
                }
                ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
              `}
            >
              <input
                type="checkbox"
                checked={isSelected}
                onChange={() => handleToggle(option.value)}
                disabled={disabled}
                className="sr-only"
              />
              <span
                className={`
                  w-4 h-4 rounded border flex items-center justify-center text-xs
                  ${
                    isSelected
                      ? 'border-indigo-500 bg-indigo-500 text-white'
                      : 'border-gray-300 dark:border-gray-600'
                  }
                `}
              >
                {isSelected && (
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                )}
              </span>
              <span className="text-sm">
                <span className="font-mono text-xs opacity-60">{option.value}</span>
                {option.label !== option.value && (
                  <span className="ml-1">{option.label}</span>
                )}
              </span>
            </label>
          )
        })}
      </div>
      {selectedValues.length > 0 && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {selectedValues.length} selected: {selectedValues.join(', ')}
        </p>
      )}
    </div>
  )
}
