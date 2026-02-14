'use client'

import { type FunctionParameter } from '@/lib/api'

interface DateInputProps {
  param: FunctionParameter
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}

/**
 * Date input component for date parameters.
 * Outputs dates in YYYY-MM-DD format.
 * Includes a "Today" button for convenience.
 */
export function DateInput({ param, value, onChange, disabled }: DateInputProps) {
  const placeholder = param.example ? String(param.example) : 'YYYY-MM-DD or "today"'

  // Handle the special "today" value
  const isToday = value?.toLowerCase() === 'today'
  const displayValue = isToday ? '' : value || ''

  const handleDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange(e.target.value)
  }

  const handleTodayClick = () => {
    onChange('today')
  }

  const handleClear = () => {
    onChange('')
  }

  // Get today's date in YYYY-MM-DD format for the date input
  const todayDate = new Date().toISOString().split('T')[0]

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <input
          type="date"
          value={displayValue}
          onChange={handleDateChange}
          disabled={disabled || isToday}
          placeholder={placeholder}
          className={`
            flex-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
            bg-white dark:bg-gray-900 text-gray-900 dark:text-white
            focus:outline-none focus:ring-2 focus:ring-indigo-500
            disabled:opacity-50 disabled:cursor-not-allowed
            ${isToday ? 'opacity-50' : ''}
          `}
        />
        <button
          type="button"
          onClick={handleTodayClick}
          disabled={disabled}
          className={`
            px-3 py-2 text-sm font-medium rounded-lg transition-colors
            ${
              isToday
                ? 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 border border-indigo-300 dark:border-indigo-700'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 border border-gray-200 dark:border-gray-700 hover:bg-gray-200 dark:hover:bg-gray-700'
            }
            disabled:opacity-50 disabled:cursor-not-allowed
          `}
        >
          Today
        </button>
        {(value || isToday) && (
          <button
            type="button"
            onClick={handleClear}
            disabled={disabled}
            className="px-2 py-2 text-sm text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 disabled:opacity-50"
            title="Clear"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>
      {isToday && (
        <p className="text-xs text-indigo-600 dark:text-indigo-400">
          Using dynamic &quot;today&quot; value ({todayDate})
        </p>
      )}
    </div>
  )
}
