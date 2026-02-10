'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useAuth } from '@/lib/auth-context'
import { metadataApi, FacetAutocompleteResult } from '@/lib/api'
import { Search, X, ChevronDown } from 'lucide-react'

interface FacetAutocompleteProps {
  facetName: string
  label: string
  selectedValues: string[]
  onSelectionChange: (values: string[]) => void
  placeholder?: string
  disabled?: boolean
}

export default function FacetAutocomplete({
  facetName,
  label,
  selectedValues,
  onSelectionChange,
  placeholder,
  disabled = false,
}: FacetAutocompleteProps) {
  const { token } = useAuth()
  const [inputValue, setInputValue] = useState('')
  const [suggestions, setSuggestions] = useState<FacetAutocompleteResult[]>([])
  const [isOpen, setIsOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Fetch suggestions with debounce
  const fetchSuggestions = useCallback(async (query: string) => {
    if (!token || query.length < 1) {
      setSuggestions([])
      return
    }

    setIsLoading(true)
    try {
      const results = await metadataApi.autocomplete(token, facetName, query, 10)
      // Filter out already-selected values
      const filtered = results.filter(
        r => !selectedValues.includes(r.canonical_value)
      )
      setSuggestions(filtered)
    } catch {
      setSuggestions([])
    } finally {
      setIsLoading(false)
    }
  }, [token, facetName, selectedValues])

  // Debounce input changes
  useEffect(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current)
    }

    if (inputValue.trim()) {
      debounceRef.current = setTimeout(() => {
        fetchSuggestions(inputValue.trim())
      }, 200)
    } else {
      setSuggestions([])
    }

    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current)
      }
    }
  }, [inputValue, fetchSuggestions])

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node) &&
        inputRef.current &&
        !inputRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleSelect = (result: FacetAutocompleteResult) => {
    onSelectionChange([...selectedValues, result.canonical_value])
    setInputValue('')
    setSuggestions([])
    setIsOpen(false)
  }

  const handleRemove = (value: string) => {
    onSelectionChange(selectedValues.filter(v => v !== value))
  }

  const formatMatchLabel = (result: FacetAutocompleteResult): string => {
    if (result.display_label && result.display_label !== result.canonical_value) {
      return `${result.display_label} — ${result.canonical_value}`
    }
    return result.canonical_value
  }

  return (
    <div className="relative">
      <span className="text-sm text-gray-500 dark:text-gray-400">{label}:</span>

      {/* Selected chips */}
      {selectedValues.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-1 mb-1.5">
          {selectedValues.map(value => (
            <span
              key={value}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400"
            >
              {value}
              <button
                onClick={() => handleRemove(value)}
                className="hover:text-indigo-900 dark:hover:text-indigo-200"
                disabled={disabled}
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="relative mt-1">
        <div className="absolute inset-y-0 left-0 pl-2.5 flex items-center pointer-events-none">
          <Search className="w-3.5 h-3.5 text-gray-400" />
        </div>
        <input
          ref={inputRef}
          type="text"
          value={inputValue}
          onChange={e => {
            setInputValue(e.target.value)
            setIsOpen(true)
          }}
          onFocus={() => {
            if (inputValue.trim()) setIsOpen(true)
          }}
          placeholder={placeholder || `Search ${label.toLowerCase()}...`}
          disabled={disabled}
          className="w-full pl-8 pr-8 py-1.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500"
        />
        {isLoading && (
          <div className="absolute inset-y-0 right-0 pr-2.5 flex items-center">
            <div className="w-3.5 h-3.5 border-2 border-gray-300 border-t-indigo-500 rounded-full animate-spin" />
          </div>
        )}
      </div>

      {/* Dropdown */}
      {isOpen && suggestions.length > 0 && (
        <div
          ref={dropdownRef}
          className="absolute z-50 w-full mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg max-h-60 overflow-y-auto"
        >
          {suggestions.map(result => (
            <button
              key={result.id}
              onClick={() => handleSelect(result)}
              className="w-full px-3 py-2 text-left text-sm hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors border-b border-gray-100 dark:border-gray-700/50 last:border-b-0"
            >
              <span className="font-medium text-gray-900 dark:text-white">
                {formatMatchLabel(result)}
              </span>
              {result.matched_on.startsWith('alias:') && (
                <span className="ml-2 text-xs text-gray-400 dark:text-gray-500">
                  matched: {result.matched_on.replace('alias:', '')}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
