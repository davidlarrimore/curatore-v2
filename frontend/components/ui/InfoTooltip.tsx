'use client'

import { Fragment, ReactNode } from 'react'
import { Popover, Transition } from '@headlessui/react'
import { HelpCircle } from 'lucide-react'

interface InfoTooltipProps {
  children: ReactNode
  className?: string
  iconClassName?: string
  position?: 'top' | 'bottom' | 'left' | 'right'
}

/**
 * A popover tooltip triggered by a help icon.
 * Used to show additional information about form fields.
 */
export function InfoTooltip({
  children,
  className = '',
  iconClassName = '',
  position = 'top',
}: InfoTooltipProps) {
  // Position classes for the popover panel
  const positionClasses = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
    left: 'right-full top-1/2 -translate-y-1/2 mr-2',
    right: 'left-full top-1/2 -translate-y-1/2 ml-2',
  }

  // Arrow position classes
  const arrowClasses = {
    top: 'top-full left-1/2 -translate-x-1/2 border-t-gray-800 dark:border-t-gray-700 border-x-transparent border-b-transparent',
    bottom: 'bottom-full left-1/2 -translate-x-1/2 border-b-gray-800 dark:border-b-gray-700 border-x-transparent border-t-transparent',
    left: 'left-full top-1/2 -translate-y-1/2 border-l-gray-800 dark:border-l-gray-700 border-y-transparent border-r-transparent',
    right: 'right-full top-1/2 -translate-y-1/2 border-r-gray-800 dark:border-r-gray-700 border-y-transparent border-l-transparent',
  }

  return (
    <Popover className={`relative inline-flex ${className}`}>
      {({ open }) => (
        <>
          <Popover.Button
            className={`
              p-0.5 rounded-full text-gray-400 hover:text-gray-600 dark:hover:text-gray-300
              hover:bg-gray-100 dark:hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-500
              transition-colors ${iconClassName}
            `}
          >
            <HelpCircle className="w-4 h-4" />
          </Popover.Button>

          <Transition
            as={Fragment}
            enter="transition ease-out duration-200"
            enterFrom="opacity-0 scale-95"
            enterTo="opacity-100 scale-100"
            leave="transition ease-in duration-150"
            leaveFrom="opacity-100 scale-100"
            leaveTo="opacity-0 scale-95"
          >
            <Popover.Panel
              className={`
                absolute z-50 w-72 max-w-sm
                ${positionClasses[position]}
              `}
            >
              {/* Arrow */}
              <div
                className={`
                  absolute w-0 h-0 border-[6px]
                  ${arrowClasses[position]}
                `}
              />

              {/* Content */}
              <div className="rounded-lg bg-gray-800 dark:bg-gray-700 shadow-xl ring-1 ring-black/5 p-3 text-sm text-gray-100">
                {children}
              </div>
            </Popover.Panel>
          </Transition>
        </>
      )}
    </Popover>
  )
}

/**
 * Pre-styled content sections for parameter tooltips.
 */
export function TooltipSection({
  label,
  children,
  className = '',
}: {
  label: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={className}>
      <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
        {label}
      </span>
      <div className="mt-0.5 text-gray-200">{children}</div>
    </div>
  )
}

/**
 * Code block for showing examples or default values.
 */
export function TooltipCode({ children }: { children: ReactNode }) {
  return (
    <code className="px-1.5 py-0.5 rounded bg-gray-900 dark:bg-gray-800 text-indigo-300 font-mono text-xs">
      {children}
    </code>
  )
}
