/**
 * Utilities for parsing comma-separated values with quote support.
 */

// Quote character mappings (handles straight and curly/smart quotes)
// Using Unicode escapes to avoid parsing issues with curly quotes in source
const STRAIGHT_DOUBLE = '"'
const STRAIGHT_SINGLE = "'"
const CURLY_DOUBLE_OPEN = '\u201C' // "
const CURLY_DOUBLE_CLOSE = '\u201D' // "
const CURLY_SINGLE_OPEN = '\u2018' // '
const CURLY_SINGLE_CLOSE = '\u2019' // '

const OPENING_QUOTES = [
  STRAIGHT_DOUBLE,
  STRAIGHT_SINGLE,
  CURLY_DOUBLE_OPEN,
  CURLY_SINGLE_OPEN,
]

const CLOSING_QUOTES: Record<string, string> = {
  [STRAIGHT_DOUBLE]: STRAIGHT_DOUBLE,
  [STRAIGHT_SINGLE]: STRAIGHT_SINGLE,
  [CURLY_DOUBLE_OPEN]: CURLY_DOUBLE_CLOSE,
  [CURLY_SINGLE_OPEN]: CURLY_SINGLE_CLOSE,
}

/**
 * Parse comma-separated values, respecting quoted strings.
 * Handles both straight quotes ("/' ) and curly/smart quotes (""/''）
 *
 * @example
 * parseCommaSeparated('foo, bar, baz') // ['foo', 'bar', 'baz']
 * parseCommaSeparated('foo, "bar, baz", qux') // ['foo', 'bar, baz', 'qux']
 * parseCommaSeparated('"HOMELAND SECURITY, DEPARTMENT OF"') // ['HOMELAND SECURITY, DEPARTMENT OF']
 * parseCommaSeparated('"foo, bar", "baz, qux"') // ['foo, bar', 'baz, qux'] (curly quotes)
 */
export function parseCommaSeparated(input: string): string[] {
  const results: string[] = []
  let current = ''
  let closingQuote: string | null = null

  for (let i = 0; i < input.length; i++) {
    const char = input[i]

    if (closingQuote) {
      // Inside a quoted string - look for the matching closing quote
      if (char === closingQuote) {
        // End of quoted string
        closingQuote = null
      } else {
        current += char
      }
    } else {
      // Not inside a quoted string
      if (OPENING_QUOTES.includes(char)) {
        // Start of quoted string - determine the matching closing quote
        closingQuote = CLOSING_QUOTES[char] || char
      } else if (char === ',') {
        // Delimiter - save current value and reset
        const trimmed = current.trim()
        if (trimmed) {
          results.push(trimmed)
        }
        current = ''
      } else {
        current += char
      }
    }
  }

  // Don't forget the last value
  const trimmed = current.trim()
  if (trimmed) {
    results.push(trimmed)
  }

  return results
}

/**
 * Trim whitespace and quotes (straight and curly) from a string.
 */
export function trimQuotes(s: string): string {
  // Match straight and curly quotes: " ' " " ' '
  return s.trim().replace(/^["'\u201C\u201D\u2018\u2019]+|["'\u201C\u201D\u2018\u2019]+$/g, '')
}
