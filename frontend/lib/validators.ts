/**
 * Document ID validation utilities for Curatore v2 frontend.
 *
 * Provides client-side validation for document identifiers, supporting:
 * - Full UUID format (36 characters with hyphens)
 * - Legacy doc_* format (doc_ prefix + 12 hex characters)
 * - File path pattern detection and rejection
 *
 * Usage:
 *   import { validateDocumentId, isValidUuid } from '@/lib/validators';
 *
 *   try {
 *     const docId = validateDocumentId(userInput);
 *     // Use validated docId
 *   } catch (error) {
 *     if (error instanceof DocumentIdError) {
 *       console.error(error.message);
 *     }
 *   }
 */

/**
 * Custom error class for document ID validation failures.
 */
export class DocumentIdError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DocumentIdError';
  }
}

// Regex patterns
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const LEGACY_DOC_PATTERN = /^doc_[0-9a-f]{12}$/i;
const FILE_PATH_PATTERN = /[/\\]|\.\.|\.[a-z]{2,4}$/i;

/**
 * Check if a string is a valid UUID v4 format.
 *
 * @param value - String to validate
 * @returns True if valid UUID format (36 chars with hyphens), false otherwise
 *
 * @example
 *   isValidUuid("550e8400-e29b-41d4-a716-446655440000") // true
 *   isValidUuid("doc_abc123def456") // false
 *   isValidUuid("invalid") // false
 */
export function isValidUuid(value: string): boolean {
  if (!value || typeof value !== 'string') {
    return false;
  }

  if (value.length !== 36) {
    return false;
  }

  return UUID_PATTERN.test(value);
}

/**
 * Check if a string matches the legacy doc_* format.
 *
 * @param value - String to validate
 * @returns True if matches doc_{12 hex chars} format, false otherwise
 *
 * @example
 *   isLegacyDocumentId("doc_abc123def456") // true
 *   isLegacyDocumentId("550e8400-e29b-41d4-a716-446655440000") // false
 *   isLegacyDocumentId("doc_short") // false
 */
export function isLegacyDocumentId(value: string): boolean {
  if (!value || typeof value !== 'string') {
    return false;
  }

  if (value.length !== 16) {
    // "doc_" (4) + 12 hex chars
    return false;
  }

  return LEGACY_DOC_PATTERN.test(value);
}

/**
 * Check if a string is a valid document ID.
 *
 * Accepts both UUID format and legacy doc_* format (if allowLegacy=true).
 *
 * @param value - String to validate
 * @param allowLegacy - Whether to accept legacy doc_* format (default: true)
 * @returns True if valid document ID, false otherwise
 *
 * @example
 *   isValidDocumentId("550e8400-e29b-41d4-a716-446655440000") // true
 *   isValidDocumentId("doc_abc123def456") // true
 *   isValidDocumentId("doc_abc123def456", false) // false
 *   isValidDocumentId("invalid/path/file.pdf") // false
 */
export function isValidDocumentId(
  value: string,
  allowLegacy: boolean = true
): boolean {
  if (!value || typeof value !== 'string') {
    return false;
  }

  // Check UUID format first
  if (isValidUuid(value)) {
    return true;
  }

  // Check legacy format if allowed
  if (allowLegacy && isLegacyDocumentId(value)) {
    return true;
  }

  return false;
}

/**
 * Detect if a string looks like a file path.
 *
 * Checks for:
 * - Forward or backward slashes (/ or \)
 * - Parent directory references (..)
 * - Common file extensions (.pdf, .docx, etc.)
 *
 * @param value - String to check
 * @returns True if looks like a file path, false otherwise
 *
 * @example
 *   detectFilePathPattern("document.pdf") // true
 *   detectFilePathPattern("folder/file.docx") // true
 *   detectFilePathPattern("../etc/passwd") // true
 *   detectFilePathPattern("550e8400-e29b-41d4-a716-446655440000") // false
 */
export function detectFilePathPattern(value: string): boolean {
  if (!value || typeof value !== 'string') {
    return false;
  }

  return FILE_PATH_PATTERN.test(value);
}

/**
 * Validate and normalize a document ID.
 *
 * @param value - Document ID to validate
 * @param allowLegacy - Whether to accept legacy doc_* format (default: true)
 * @param rejectFilePaths - Whether to reject strings that look like file paths (default: true)
 * @returns Validated document ID (normalized to lowercase for UUIDs)
 * @throws {DocumentIdError} If document ID is invalid
 *
 * @example
 *   validateDocumentId("550E8400-E29B-41D4-A716-446655440000")
 *   // Returns: "550e8400-e29b-41d4-a716-446655440000"
 *
 *   validateDocumentId("doc_ABC123DEF456")
 *   // Returns: "doc_abc123def456"
 *
 *   validateDocumentId("invalid/path.pdf")
 *   // Throws: DocumentIdError
 */
export function validateDocumentId(
  value: string,
  allowLegacy: boolean = true,
  rejectFilePaths: boolean = true
): string {
  if (!value || typeof value !== 'string') {
    throw new DocumentIdError('Document ID must be a non-empty string');
  }

  // Strip whitespace
  const trimmedValue = value.trim();

  if (!trimmedValue) {
    throw new DocumentIdError('Document ID must be a non-empty string');
  }

  // Check for file path patterns first
  if (rejectFilePaths && detectFilePathPattern(trimmedValue)) {
    throw new DocumentIdError(
      'Document ID appears to be a file path. Use the search endpoint to search by filename.'
    );
  }

  // Validate format
  if (!isValidDocumentId(trimmedValue, allowLegacy)) {
    if (allowLegacy) {
      throw new DocumentIdError(
        'Document ID must be a valid UUID (e.g., 550e8400-e29b-41d4-a716-446655440000) or legacy format (e.g., doc_abc123def456)'
      );
    } else {
      throw new DocumentIdError(
        'Document ID must be a valid UUID (e.g., 550e8400-e29b-41d4-a716-446655440000)'
      );
    }
  }

  // Normalize to lowercase
  return trimmedValue.toLowerCase();
}

/**
 * Generate a new document ID using UUID v4.
 *
 * Uses the browser's crypto.randomUUID() API for cryptographically secure random UUIDs.
 *
 * @returns New document ID as lowercase UUID string
 *
 * @example
 *   const docId = generateDocumentId();
 *   isValidUuid(docId) // true
 *   docId.length // 36
 */
export function generateDocumentId(): string {
  // Use browser's native UUID generation
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }

  // Fallback for environments without crypto.randomUUID
  // (e.g., older browsers or Node.js < 15)
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Extract document ID from an artifact storage key.
 *
 * Artifact keys follow the pattern:
 * - {org_id}/{document_id}/uploaded/{filename}
 * - {org_id}/{document_id}/processed/{filename}
 *
 * @param key - Storage key to parse
 * @returns Extracted document ID if found and valid, null otherwise
 *
 * @example
 *   extractDocumentIdFromArtifactKey(
 *     "org123/550e8400-e29b-41d4-a716-446655440000/uploaded/file.pdf"
 *   )
 *   // Returns: "550e8400-e29b-41d4-a716-446655440000"
 *
 *   extractDocumentIdFromArtifactKey("invalid/key")
 *   // Returns: null
 */
export function extractDocumentIdFromArtifactKey(
  key: string
): string | null {
  if (!key || typeof key !== 'string') {
    return null;
  }

  const parts = key.split('/');
  if (parts.length < 3) {
    return null;
  }

  // Document ID should be the second part (after org_id)
  const potentialDocId = parts[1];

  if (isValidDocumentId(potentialDocId, true)) {
    return potentialDocId.toLowerCase();
  }

  return null;
}

/**
 * Type guard to check if a value is a valid document ID.
 *
 * Can be used in TypeScript to narrow types.
 *
 * @param value - Value to check
 * @returns True if value is a valid document ID string
 *
 * @example
 *   function processDocument(id: unknown) {
 *     if (isDocumentId(id)) {
 *       // TypeScript knows id is a string here
 *       console.log(id.toUpperCase());
 *     }
 *   }
 */
export function isDocumentId(value: unknown): value is string {
  if (typeof value !== 'string') {
    return false;
  }
  return isValidDocumentId(value, true);
}
