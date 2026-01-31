'use client'

/**
 * Reusable confirmation dialog for destructive actions.
 *
 * Uses Headless UI Dialog for accessibility.
 */

import { Fragment, useState } from 'react'
import { Dialog, Transition } from '@headlessui/react'
import { AlertTriangle, Loader2, X } from 'lucide-react'
import { Button } from './Button'

interface ConfirmDeleteDialogProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: () => Promise<void>
  title: string
  itemName: string
  description?: string
  warningItems?: string[]
  confirmButtonText?: string
}

export function ConfirmDeleteDialog({
  isOpen,
  onClose,
  onConfirm,
  title,
  itemName,
  description,
  warningItems = [],
  confirmButtonText = 'Delete',
}: ConfirmDeleteDialogProps) {
  const [isDeleting, setIsDeleting] = useState(false)

  const handleConfirm = async () => {
    setIsDeleting(true)
    try {
      await onConfirm()
    } finally {
      setIsDeleting(false)
    }
  }

  const handleClose = () => {
    if (!isDeleting) {
      onClose()
    }
  }

  return (
    <Transition.Root show={isOpen} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={handleClose}>
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-300"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-200"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 bg-gray-900/80 backdrop-blur-sm transition-opacity" />
        </Transition.Child>

        <div className="fixed inset-0 z-10 overflow-y-auto">
          <div className="flex min-h-full items-end justify-center p-4 text-center sm:items-center sm:p-0">
            <Transition.Child
              as={Fragment}
              enter="ease-out duration-300"
              enterFrom="opacity-0 translate-y-4 sm:translate-y-0 sm:scale-95"
              enterTo="opacity-100 translate-y-0 sm:scale-100"
              leave="ease-in duration-200"
              leaveFrom="opacity-100 translate-y-0 sm:scale-100"
              leaveTo="opacity-0 translate-y-4 sm:translate-y-0 sm:scale-95"
            >
              <Dialog.Panel className="relative transform overflow-hidden rounded-xl bg-white dark:bg-gray-800 px-4 pb-4 pt-5 text-left shadow-2xl transition-all sm:my-8 sm:w-full sm:max-w-lg sm:p-6">
                {/* Close button */}
                <div className="absolute right-0 top-0 pr-4 pt-4">
                  <button
                    type="button"
                    className="rounded-lg p-1 text-gray-400 hover:text-gray-500 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    onClick={handleClose}
                    disabled={isDeleting}
                  >
                    <span className="sr-only">Close</span>
                    <X className="h-5 w-5" aria-hidden="true" />
                  </button>
                </div>

                <div className="sm:flex sm:items-start">
                  {/* Warning icon */}
                  <div className="mx-auto flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-full bg-red-100 dark:bg-red-900/30 sm:mx-0 sm:h-10 sm:w-10">
                    <AlertTriangle className="h-6 w-6 text-red-600 dark:text-red-400" aria-hidden="true" />
                  </div>

                  <div className="mt-3 text-center sm:ml-4 sm:mt-0 sm:text-left flex-1">
                    <Dialog.Title
                      as="h3"
                      className="text-lg font-semibold leading-6 text-gray-900 dark:text-white"
                    >
                      {title}
                    </Dialog.Title>

                    <div className="mt-2">
                      <p className="text-sm text-gray-500 dark:text-gray-400">
                        Are you sure you want to delete{' '}
                        <span className="font-medium text-gray-900 dark:text-white">
                          {itemName}
                        </span>
                        ?
                        {description && ` ${description}`}
                      </p>
                    </div>

                    {/* Warning items list */}
                    {warningItems.length > 0 && (
                      <div className="mt-4 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 p-3">
                        <p className="text-sm font-medium text-amber-800 dark:text-amber-200 mb-2">
                          This action will:
                        </p>
                        <ul className="space-y-1">
                          {warningItems.map((item, index) => (
                            <li
                              key={index}
                              className="text-sm text-amber-700 dark:text-amber-300 flex items-start gap-2"
                            >
                              <span className="w-1.5 h-1.5 rounded-full bg-amber-500 mt-1.5 flex-shrink-0" />
                              {item}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    <p className="mt-4 text-xs text-gray-500 dark:text-gray-400">
                      This action cannot be undone.
                    </p>
                  </div>
                </div>

                {/* Actions */}
                <div className="mt-5 sm:mt-4 sm:flex sm:flex-row-reverse gap-3">
                  <Button
                    variant="primary"
                    onClick={handleConfirm}
                    disabled={isDeleting}
                    className="w-full sm:w-auto bg-red-600 hover:bg-red-700 focus:ring-red-500"
                  >
                    {isDeleting ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin mr-2" />
                        Deleting...
                      </>
                    ) : (
                      confirmButtonText
                    )}
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={handleClose}
                    disabled={isDeleting}
                    className="mt-3 w-full sm:mt-0 sm:w-auto"
                  >
                    Cancel
                  </Button>
                </div>
              </Dialog.Panel>
            </Transition.Child>
          </div>
        </div>
      </Dialog>
    </Transition.Root>
  )
}
