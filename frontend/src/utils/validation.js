/**
 * Client-side validation for PDF uploads and user questions.
 */

import { MAX_QUESTION_LENGTH } from '../config/constants.js';
import { formatMiB } from './dom.js';

export function validatePdfFile(file, limits) {
  if (!file) {
    return { valid: false, message: 'Please choose a PDF file.' };
  }
  const name = typeof file.name === 'string' ? file.name.trim() : '';
  if (!name.toLowerCase().endsWith('.pdf')) {
    return { valid: false, message: 'Please choose a PDF file.' };
  }
  if (!file.size) {
    return { valid: false, message: 'This file is empty. Please choose another PDF.' };
  }
  if (limits?.max_upload_bytes && file.size > limits.max_upload_bytes) {
    return {
      valid: false,
      message: `The file is too large. The limit is ${formatMiB(limits.max_upload_bytes)}.`,
    };
  }
  return { valid: true };
}

export function validateQuestionText(rawText, maxLength = MAX_QUESTION_LENGTH) {
  const question = typeof rawText === 'string' ? rawText.trim() : '';
  if (!question) {
    return { valid: false, message: 'Enter a question about the uploaded PDF.' };
  }
  if (question.length > maxLength) {
    return {
      valid: false,
      message: `Question exceeds the ${maxLength}-character limit.`,
    };
  }
  return { valid: true, question };
}
