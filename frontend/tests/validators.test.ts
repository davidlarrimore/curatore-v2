/**
 * Tests for frontend document ID validators.
 *
 * Tests the validation utilities in lib/validators.ts to ensure proper
 * client-side validation of UUID and legacy document ID formats.
 */

import {
  isValidUuid,
  isLegacyDocumentId,
  isValidDocumentId,
  detectFilePathPattern,
  validateDocumentId,
  generateDocumentId,
  extractDocumentIdFromArtifactKey,
  DocumentIdError,
  isDocumentId,
} from '../lib/validators';

describe('isValidUuid', () => {
  it('should accept valid lowercase UUID', () => {
    expect(isValidUuid('550e8400-e29b-41d4-a716-446655440000')).toBe(true);
  });

  it('should accept valid uppercase UUID', () => {
    expect(isValidUuid('550E8400-E29B-41D4-A716-446655440000')).toBe(true);
  });

  it('should accept valid mixed-case UUID', () => {
    expect(isValidUuid('550e8400-E29B-41d4-A716-446655440000')).toBe(true);
  });

  it('should reject UUID without hyphens', () => {
    expect(isValidUuid('550e8400e29b41d4a716446655440000')).toBe(false);
  });

  it('should reject invalid length', () => {
    expect(isValidUuid('550e8400-e29b-41d4-a716')).toBe(false);
    expect(isValidUuid('550e8400-e29b-41d4-a716-446655440000-extra')).toBe(false);
  });

  it('should reject empty string', () => {
    expect(isValidUuid('')).toBe(false);
  });

  it('should reject non-UUID format', () => {
    expect(isValidUuid('not-a-uuid-format')).toBe(false);
  });
});

describe('isLegacyDocumentId', () => {
  it('should accept valid lowercase legacy format', () => {
    expect(isLegacyDocumentId('doc_abc123def456')).toBe(true);
  });

  it('should accept valid uppercase legacy format', () => {
    expect(isLegacyDocumentId('doc_ABC123DEF456')).toBe(true);
  });

  it('should accept valid mixed-case legacy format', () => {
    expect(isLegacyDocumentId('doc_AbC123DeF456')).toBe(true);
  });

  it('should reject wrong length', () => {
    expect(isLegacyDocumentId('doc_short')).toBe(false);
    expect(isLegacyDocumentId('doc_toolongvalue123')).toBe(false);
  });

  it('should reject wrong prefix', () => {
    expect(isLegacyDocumentId('file_abc123def456')).toBe(false);
    expect(isLegacyDocumentId('docdabc123def456')).toBe(false);
  });

  it('should reject no prefix', () => {
    expect(isLegacyDocumentId('abc123def456')).toBe(false);
  });

  it('should reject empty string', () => {
    expect(isLegacyDocumentId('')).toBe(false);
  });
});

describe('isValidDocumentId', () => {
  it('should accept valid UUID', () => {
    expect(isValidDocumentId('550e8400-e29b-41d4-a716-446655440000')).toBe(true);
  });

  it('should accept valid legacy with allowLegacy=true', () => {
    expect(isValidDocumentId('doc_abc123def456', true)).toBe(true);
  });

  it('should reject valid legacy with allowLegacy=false', () => {
    expect(isValidDocumentId('doc_abc123def456', false)).toBe(false);
  });

  it('should reject invalid format', () => {
    expect(isValidDocumentId('invalid-format')).toBe(false);
    expect(isValidDocumentId('123456')).toBe(false);
  });

  it('should reject file paths', () => {
    expect(isValidDocumentId('folder/file.pdf')).toBe(false);
    expect(isValidDocumentId('../etc/passwd')).toBe(false);
  });

  it('should reject empty string', () => {
    expect(isValidDocumentId('')).toBe(false);
  });
});

describe('detectFilePathPattern', () => {
  it('should detect forward slash', () => {
    expect(detectFilePathPattern('folder/file.pdf')).toBe(true);
  });

  it('should detect backward slash', () => {
    expect(detectFilePathPattern('folder\\file.pdf')).toBe(true);
  });

  it('should detect parent directory reference', () => {
    expect(detectFilePathPattern('../etc/passwd')).toBe(true);
  });

  it('should detect common file extensions', () => {
    expect(detectFilePathPattern('document.pdf')).toBe(true);
    expect(detectFilePathPattern('file.docx')).toBe(true);
    expect(detectFilePathPattern('data.txt')).toBe(true);
  });

  it('should not detect UUID as file path', () => {
    expect(detectFilePathPattern('550e8400-e29b-41d4-a716-446655440000')).toBe(false);
  });

  it('should not detect legacy format as file path', () => {
    expect(detectFilePathPattern('doc_abc123def456')).toBe(false);
  });

  it('should return false for empty string', () => {
    expect(detectFilePathPattern('')).toBe(false);
  });
});

describe('validateDocumentId', () => {
  it('should normalize UUID to lowercase', () => {
    const result = validateDocumentId('550E8400-E29B-41D4-A716-446655440000');
    expect(result).toBe('550e8400-e29b-41d4-a716-446655440000');
  });

  it('should normalize legacy to lowercase', () => {
    const result = validateDocumentId('doc_ABC123DEF456');
    expect(result).toBe('doc_abc123def456');
  });

  it('should strip whitespace', () => {
    const result = validateDocumentId('  550e8400-e29b-41d4-a716-446655440000  ');
    expect(result).toBe('550e8400-e29b-41d4-a716-446655440000');
  });

  it('should throw DocumentIdError for file path', () => {
    expect(() => validateDocumentId('folder/file.pdf')).toThrow(DocumentIdError);
    expect(() => validateDocumentId('folder/file.pdf')).toThrow(/file path/i);
  });

  it('should throw DocumentIdError for invalid format', () => {
    expect(() => validateDocumentId('invalid-format')).toThrow(DocumentIdError);
    expect(() => validateDocumentId('invalid-format')).toThrow(/valid UUID/i);
  });

  it('should throw DocumentIdError for empty string', () => {
    expect(() => validateDocumentId('')).toThrow(DocumentIdError);
    expect(() => validateDocumentId('')).toThrow(/non-empty string/i);
  });

  it('should reject legacy when allowLegacy=false', () => {
    expect(() => validateDocumentId('doc_abc123def456', false)).toThrow(DocumentIdError);
  });

  it('should allow file path when rejectFilePaths=false', () => {
    // Note: Should still fail due to invalid format, not file path detection
    expect(() => validateDocumentId('document.pdf', true, false)).toThrow(DocumentIdError);
  });
});

describe('generateDocumentId', () => {
  it('should generate valid UUID', () => {
    const docId = generateDocumentId();
    expect(isValidUuid(docId)).toBe(true);
  });

  it('should generate unique IDs', () => {
    const ids = new Set<string>();
    for (let i = 0; i < 100; i++) {
      ids.add(generateDocumentId());
    }
    expect(ids.size).toBe(100); // All should be unique
  });

  it('should generate lowercase IDs', () => {
    const docId = generateDocumentId();
    expect(docId).toBe(docId.toLowerCase());
  });

  it('should generate 36-character IDs', () => {
    const docId = generateDocumentId();
    expect(docId.length).toBe(36);
  });
});

describe('extractDocumentIdFromArtifactKey', () => {
  it('should extract UUID from valid key', () => {
    const key = 'org123/550e8400-e29b-41d4-a716-446655440000/uploaded/file.pdf';
    const result = extractDocumentIdFromArtifactKey(key);
    expect(result).toBe('550e8400-e29b-41d4-a716-446655440000');
  });

  it('should extract legacy from valid key', () => {
    const key = 'org123/doc_abc123def456/processed/output.md';
    const result = extractDocumentIdFromArtifactKey(key);
    expect(result).toBe('doc_abc123def456');
  });

  it('should normalize uppercase to lowercase', () => {
    const key = 'org123/550E8400-E29B-41D4-A716-446655440000/uploaded/file.pdf';
    const result = extractDocumentIdFromArtifactKey(key);
    expect(result).toBe('550e8400-e29b-41d4-a716-446655440000');
  });

  it('should return null for invalid key with too few parts', () => {
    expect(extractDocumentIdFromArtifactKey('org123/file.pdf')).toBeNull();
  });

  it('should return null for invalid document ID in key', () => {
    const key = 'org123/invalid-doc-id/uploaded/file.pdf';
    expect(extractDocumentIdFromArtifactKey(key)).toBeNull();
  });

  it('should return null for empty string', () => {
    expect(extractDocumentIdFromArtifactKey('')).toBeNull();
  });
});

describe('isDocumentId', () => {
  it('should return true for valid UUID string', () => {
    expect(isDocumentId('550e8400-e29b-41d4-a716-446655440000')).toBe(true);
  });

  it('should return true for valid legacy string', () => {
    expect(isDocumentId('doc_abc123def456')).toBe(true);
  });

  it('should return false for invalid string', () => {
    expect(isDocumentId('invalid-format')).toBe(false);
  });

  it('should return false for non-string types', () => {
    expect(isDocumentId(123)).toBe(false);
    expect(isDocumentId(null)).toBe(false);
    expect(isDocumentId(undefined)).toBe(false);
    expect(isDocumentId({})).toBe(false);
    expect(isDocumentId([])).toBe(false);
  });
});

describe('DocumentIdError', () => {
  it('should be instance of Error', () => {
    const error = new DocumentIdError('Test error');
    expect(error).toBeInstanceOf(Error);
  });

  it('should have correct name', () => {
    const error = new DocumentIdError('Test error');
    expect(error.name).toBe('DocumentIdError');
  });

  it('should have correct message', () => {
    const message = 'Invalid document ID format';
    const error = new DocumentIdError(message);
    expect(error.message).toBe(message);
  });

  it('should be catchable', () => {
    expect(() => {
      try {
        throw new DocumentIdError('Test error');
      } catch (error) {
        if (error instanceof DocumentIdError) {
          throw error;
        }
      }
    }).toThrow(DocumentIdError);
  });
});
