'use client'

/**
 * Create New Organization page.
 *
 * Allows system admins to create new organizations.
 */

import { useState, FormEvent } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, Building2 } from 'lucide-react'
import { organizationsApi } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import { Button } from '@/components/ui/Button'

export default function NewOrganizationPage() {
  const router = useRouter()
  const { token } = useAuth()
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')

  const [name, setName] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [slug, setSlug] = useState('')

  // Auto-generate slug from name
  const handleNameChange = (value: string) => {
    setName(value)
    // Generate slug: lowercase, replace spaces with hyphens, remove special chars
    const generatedSlug = value
      .toLowerCase()
      .replace(/[^a-z0-9\s-]/g, '')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-')
      .trim()
    setSlug(generatedSlug)
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!token) return

    setIsLoading(true)
    setError('')

    try {
      await organizationsApi.createOrganization(token, {
        name,
        display_name: displayName || name,
        slug,
      })

      router.push('/system/organizations')
    } catch (err: any) {
      setError(err.message || 'Failed to create organization')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="p-6 max-w-2xl mx-auto">
      {/* Back link */}
      <button
        onClick={() => router.back()}
        className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300 mb-6"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Organizations
      </button>

      {/* Header */}
      <div className="flex items-center gap-4 mb-8">
        <div className="p-3 bg-amber-100 dark:bg-amber-900/30 rounded-xl">
          <Building2 className="h-8 w-8 text-amber-600 dark:text-amber-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Create Organization
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Add a new organization to the system
          </p>
        </div>
      </div>

      {/* Form */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
        {error && (
          <div className="mb-6 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-4">
            <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-6">
          <div>
            <label
              htmlFor="name"
              className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2"
            >
              Organization Name *
            </label>
            <input
              id="name"
              type="text"
              value={name}
              onChange={(e) => handleNameChange(e.target.value)}
              required
              placeholder="Acme Corporation"
              className="w-full px-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent"
            />
            <p className="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
              The internal name for the organization
            </p>
          </div>

          <div>
            <label
              htmlFor="displayName"
              className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2"
            >
              Display Name
            </label>
            <input
              id="displayName"
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Acme Corp"
              className="w-full px-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent"
            />
            <p className="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
              Optional friendly name shown in the UI (defaults to organization name)
            </p>
          </div>

          <div>
            <label
              htmlFor="slug"
              className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2"
            >
              Slug *
            </label>
            <input
              id="slug"
              type="text"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              required
              placeholder="acme-corp"
              pattern="[a-z0-9-]+"
              className="w-full px-4 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent font-mono"
            />
            <p className="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
              URL-friendly identifier (lowercase letters, numbers, and hyphens only)
            </p>
          </div>

          <div className="flex items-center gap-3 pt-4 border-t border-gray-200 dark:border-gray-700">
            <Button type="submit" disabled={isLoading}>
              {isLoading ? 'Creating...' : 'Create Organization'}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => router.back()}
            >
              Cancel
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
