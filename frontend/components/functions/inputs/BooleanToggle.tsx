'use client'

import { type FunctionParameter } from '@/lib/api'

interface BooleanToggleProps {
  param: FunctionParameter
  value: boolean | undefined
  onChange: (value: boolean) => void
  disabled?: boolean
}

export function BooleanToggle({ param, value, onChange, disabled }: BooleanToggleProps) {
  // Use default value if value is undefined
  const checked = value !== undefined ? value : (param.default === true)

  return (
    <label className="flex items-center gap-3 cursor-pointer">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`
          relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent
          transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2
          ${checked ? 'bg-indigo-600' : 'bg-gray-200 dark:bg-gray-700'}
          ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
        `}
      >
        <span
          aria-hidden="true"
          className={`
            pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0
            transition duration-200 ease-in-out
            ${checked ? 'translate-x-5' : 'translate-x-0'}
          `}
        />
      </button>
      <span className="text-sm text-gray-600 dark:text-gray-400">
        {checked ? 'True' : 'False'}
      </span>
    </label>
  )
}
