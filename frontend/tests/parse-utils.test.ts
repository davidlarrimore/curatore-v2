/**
 * Tests for comma-separated value parsing utilities.
 *
 * Tests the parseCommaSeparated function to ensure it correctly handles:
 * - Simple comma-separated values
 * - Quoted strings with commas inside (straight and curly quotes)
 * - Mixed quoted and unquoted values
 * - Edge cases (empty input, unclosed quotes, etc.)
 */

import { parseCommaSeparated, trimQuotes } from '../lib/parse-utils'

describe('parseCommaSeparated', () => {
  describe('basic comma separation', () => {
    it('should split simple comma-separated values', () => {
      expect(parseCommaSeparated('foo, bar, baz')).toEqual(['foo', 'bar', 'baz'])
    })

    it('should handle values without spaces after commas', () => {
      expect(parseCommaSeparated('foo,bar,baz')).toEqual(['foo', 'bar', 'baz'])
    })

    it('should trim whitespace from values', () => {
      expect(parseCommaSeparated('  foo  ,  bar  ,  baz  ')).toEqual([
        'foo',
        'bar',
        'baz',
      ])
    })

    it('should handle single value', () => {
      expect(parseCommaSeparated('foo')).toEqual(['foo'])
    })

    it('should return empty array for empty string', () => {
      expect(parseCommaSeparated('')).toEqual([])
    })

    it('should return empty array for whitespace only', () => {
      expect(parseCommaSeparated('   ')).toEqual([])
    })

    it('should skip empty values between commas', () => {
      expect(parseCommaSeparated('foo,,bar')).toEqual(['foo', 'bar'])
      expect(parseCommaSeparated(',foo,bar,')).toEqual(['foo', 'bar'])
    })
  })

  describe('straight double quotes', () => {
    it('should keep commas inside double quotes', () => {
      expect(parseCommaSeparated('"foo, bar"')).toEqual(['foo, bar'])
    })

    it('should handle quoted value with surrounding unquoted values', () => {
      expect(parseCommaSeparated('aaa, "foo, bar", bbb')).toEqual([
        'aaa',
        'foo, bar',
        'bbb',
      ])
    })

    it('should handle multiple quoted values', () => {
      expect(parseCommaSeparated('"foo, bar", "baz, qux"')).toEqual([
        'foo, bar',
        'baz, qux',
      ])
    })

    it('should handle department name with comma (user reported issue)', () => {
      expect(parseCommaSeparated('"HOMELAND SECURITY, DEPARTMENT OF"')).toEqual([
        'HOMELAND SECURITY, DEPARTMENT OF',
      ])
    })

    it('should handle mixed quoted and unquoted departments', () => {
      expect(
        parseCommaSeparated(
          'DEPT OF DEFENSE, "HOMELAND SECURITY, DEPARTMENT OF", TREASURY'
        )
      ).toEqual([
        'DEPT OF DEFENSE',
        'HOMELAND SECURITY, DEPARTMENT OF',
        'TREASURY',
      ])
    })
  })

  describe('straight single quotes', () => {
    it('should keep commas inside single quotes', () => {
      expect(parseCommaSeparated("'foo, bar'")).toEqual(['foo, bar'])
    })

    it('should handle quoted value with surrounding unquoted values', () => {
      expect(parseCommaSeparated("aaa, 'foo, bar', bbb")).toEqual([
        'aaa',
        'foo, bar',
        'bbb',
      ])
    })

    it('should handle multiple single-quoted values', () => {
      expect(parseCommaSeparated("'foo, bar', 'baz, qux'")).toEqual([
        'foo, bar',
        'baz, qux',
      ])
    })
  })

  describe('curly/smart double quotes', () => {
    it('should keep commas inside curly double quotes', () => {
      expect(parseCommaSeparated('\u201Cfoo, bar\u201D')).toEqual(['foo, bar'])
    })

    it('should handle quoted value with surrounding unquoted values', () => {
      expect(parseCommaSeparated('aaa, \u201Cfoo, bar\u201D, bbb')).toEqual([
        'aaa',
        'foo, bar',
        'bbb',
      ])
    })

    it('should handle department name with curly quotes (user reported issue)', () => {
      expect(
        parseCommaSeparated('\u201CHOMELAND SECURITY, DEPARTMENT OF\u201D')
      ).toEqual(['HOMELAND SECURITY, DEPARTMENT OF'])
    })

    it('should handle multiple curly-quoted values', () => {
      expect(
        parseCommaSeparated('\u201Cfoo, bar\u201D, \u201Cbaz, qux\u201D')
      ).toEqual(['foo, bar', 'baz, qux'])
    })
  })

  describe('curly/smart single quotes', () => {
    it('should keep commas inside curly single quotes', () => {
      expect(parseCommaSeparated('\u2018foo, bar\u2019')).toEqual(['foo, bar'])
    })

    it('should handle quoted value with surrounding unquoted values', () => {
      expect(parseCommaSeparated('aaa, \u2018foo, bar\u2019, bbb')).toEqual([
        'aaa',
        'foo, bar',
        'bbb',
      ])
    })
  })

  describe('mixed quote styles', () => {
    it('should handle mix of straight and curly double quotes', () => {
      expect(
        parseCommaSeparated('"foo, bar", \u201Cbaz, qux\u201D')
      ).toEqual(['foo, bar', 'baz, qux'])
    })

    it('should handle mix of double and single quotes', () => {
      expect(parseCommaSeparated('"foo, bar", \'baz, qux\'')).toEqual([
        'foo, bar',
        'baz, qux',
      ])
    })
  })

  describe('edge cases', () => {
    it('should handle unclosed quote (treats rest of string as quoted)', () => {
      // Unclosed quote means everything after is part of the quoted string
      expect(parseCommaSeparated('"foo, bar')).toEqual(['foo, bar'])
    })

    it('should handle empty quoted string', () => {
      expect(parseCommaSeparated('""')).toEqual([])
      expect(parseCommaSeparated('foo, "", bar')).toEqual(['foo', 'bar'])
    })

    it('should handle stray quote in middle (treats as quote start)', () => {
      // A stray opening quote starts a quoted section, capturing everything after
      expect(parseCommaSeparated('foo", bar')).toEqual(['foo, bar'])
    })

    it('should handle consecutive commas with quoted values', () => {
      expect(parseCommaSeparated('"a, b",,"c, d"')).toEqual(['a, b', 'c, d'])
    })

    it('should preserve internal whitespace in quoted strings', () => {
      expect(parseCommaSeparated('"foo   bar"')).toEqual(['foo   bar'])
    })

    it('should handle real-world SAM.gov department examples', () => {
      // Real department names that contain commas
      expect(
        parseCommaSeparated(
          '"HEALTH AND HUMAN SERVICES, DEPARTMENT OF", "HOMELAND SECURITY, DEPARTMENT OF"'
        )
      ).toEqual([
        'HEALTH AND HUMAN SERVICES, DEPARTMENT OF',
        'HOMELAND SECURITY, DEPARTMENT OF',
      ])

      // Mix of simple and complex department names
      expect(
        parseCommaSeparated(
          'DEPT OF DEFENSE, "HEALTH AND HUMAN SERVICES, DEPARTMENT OF", TREASURY'
        )
      ).toEqual([
        'DEPT OF DEFENSE',
        'HEALTH AND HUMAN SERVICES, DEPARTMENT OF',
        'TREASURY',
      ])
    })
  })
})

describe('trimQuotes', () => {
  describe('straight quotes', () => {
    it('should trim straight double quotes', () => {
      expect(trimQuotes('"foo"')).toBe('foo')
    })

    it('should trim straight single quotes', () => {
      expect(trimQuotes("'foo'")).toBe('foo')
    })

    it('should trim multiple quotes', () => {
      expect(trimQuotes('""foo""')).toBe('foo')
      expect(trimQuotes("''foo''")).toBe('foo')
    })
  })

  describe('curly quotes', () => {
    it('should trim curly double quotes', () => {
      expect(trimQuotes('\u201Cfoo\u201D')).toBe('foo')
    })

    it('should trim curly single quotes', () => {
      expect(trimQuotes('\u2018foo\u2019')).toBe('foo')
    })
  })

  describe('whitespace', () => {
    it('should trim whitespace', () => {
      expect(trimQuotes('  foo  ')).toBe('foo')
    })

    it('should trim whitespace and quotes together', () => {
      expect(trimQuotes('  "foo"  ')).toBe('foo')
    })
  })

  describe('edge cases', () => {
    it('should return empty string for empty input', () => {
      expect(trimQuotes('')).toBe('')
    })

    it('should return empty string for quotes only', () => {
      expect(trimQuotes('""')).toBe('')
      expect(trimQuotes("''")).toBe('')
    })

    it('should not trim quotes in the middle', () => {
      expect(trimQuotes('foo"bar')).toBe('foo"bar')
      expect(trimQuotes("foo'bar")).toBe("foo'bar")
    })
  })
})
