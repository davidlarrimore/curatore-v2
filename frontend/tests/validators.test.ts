/**
 * Tests for frontend document ID validators.
 *
 * Tests the validation utilities in lib/validators.ts to ensure proper
 * client-side validation of UUID document ID formats.
 */

import {
  isValidUuid,
  isValidDocumentId,
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

  it('should reject legacy doc_* format', () => {
    expect(isValidUuid('doc_abc123def456')).toBe(false);
  });
});

describe('isValidDocumentId', () => {
  it('should accept valid UUID', () => {
    expect(isValidDocumentId('550e8400-e29b-41d4-a716-446655440000')).toBe(true);
  });

  it('should accept valid uppercase UUID', () => {
    expect(isValidDocumentId('550E8400-E29B-41D4-A716-446655440000')).toBe(true);
  });

  it('should reject legacy doc_* format', () => {
    expect(isValidDocumentId('doc_abc123def456')).toBe(false);
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

describe('validateDocumentId', () => {
  it('should normalize UUID to lowercase', () => {
    const result = validateDocumentId('550E8400-E29B-41D4-A716-446655440000');
    expect(result).toBe('550e8400-e29b-41d4-a716-446655440000');
  });

  it('should strip whitespace', () => {
    const result = validateDocumentId('  550e8400-e29b-41d4-a716-446655440000  ');
    expect(result).toBe('550e8400-e29b-41d4-a716-446655440000');
  });

  it('should throw DocumentIdError for legacy doc_* format', () => {
    expect(() => validateDocumentId('doc_abc123def456')).toThrow(DocumentIdError);
  });

  it('should throw DocumentIdError for file path', () => {
    expect(() => validateDocumentId('folder/file.pdf')).toThrow(DocumentIdError);
  });

  it('should throw DocumentIdError for invalid format', () => {
    expect(() => validateDocumentId('invalid-format')).toThrow(DocumentIdError);
    expect(() => validateDocumentId('invalid-format')).toThrow(/valid UUID/i);
  });

  it('should throw DocumentIdError for empty string', () => {
    expect(() => validateDocumentId('')).toThrow(DocumentIdError);
    expect(() => validateDocumentId('')).toThrow(/non-empty string/i);
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

  it('should normalize uppercase to lowercase', () => {
    const key = 'org123/550E8400-E29B-41D4-A716-446655440000/uploaded/file.pdf';
    const result = extractDocumentIdFromArtifactKey(key);
    expect(result).toBe('550e8400-e29b-41d4-a716-446655440000');
  });

  it('should return null for legacy doc_* format in key', () => {
    const key = 'org123/doc_abc123def456/processed/output.md';
    expect(extractDocumentIdFromArtifactKey(key)).toBeNull();
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

  it('should return false for legacy doc_* format', () => {
    expect(isDocumentId('doc_abc123def456')).toBe(false);
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
