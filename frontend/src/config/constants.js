/**
 * Shared frontend defaults, timeouts, and starter prompts.
 */

export const MAX_QUESTION_LENGTH = 2000;
export const EXPIRY_WARNING_SECONDS = 300;
export const CHAR_WARNING_THRESHOLD = 1750;

export const DEFAULT_LIMITS = Object.freeze({
  max_upload_bytes: 20 * 1024 * 1024,
  max_pdf_pages: 350,
  max_extracted_chars: 4_000_000,
  session_ttl_seconds: 3600,
});

export const REQUEST_TIMEOUTS_MS = Object.freeze({
  status: 8_000,
  upload: 120_000,
  ask: 300_000,
  page: 30_000,
  remove: 15_000,
});

export const STARTER_PROMPTS = Object.freeze([
  'What is the main purpose and scope of this document?',
  'What limits, thresholds, or deadlines are stated?',
  'What requirements or conditions apply?',
]);
