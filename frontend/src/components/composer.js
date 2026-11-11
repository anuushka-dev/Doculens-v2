/**
 * Question composer: textarea auto-sizing, character counter, keyboard submit, and busy lock.
 */

import { CHAR_WARNING_THRESHOLD, MAX_QUESTION_LENGTH } from '../config/constants.js';
import { getById } from '../utils/dom.js';

export function createComposer(doc, { onSubmit } = {}) {
  const form = getById(doc, 'ask-form');
  const input = getById(doc, 'question');
  const sendBtn = getById(doc, 'send');
  const charCountEl = getById(doc, 'char-count');

  let currentBusy = false;
  let hasActiveSession = false;

  function updateCounter() {
    if (!input || !charCountEl) return;
    const len = input.value.length;
    charCountEl.textContent = `${len} / ${MAX_QUESTION_LENGTH}`;
    charCountEl.classList.toggle('near-limit', len >= CHAR_WARNING_THRESHOLD);
  }

  function resizeTextarea() {
    if (!input || !input.style) return;
    input.style.height = 'auto';
    if (input.scrollHeight) {
      input.style.height = `${Math.min(150, Math.max(46, input.scrollHeight))}px`;
    }
  }

  function syncAvailability() {
    if (!input || !sendBtn) return;
    input.disabled = currentBusy || !hasActiveSession;
    sendBtn.disabled = currentBusy || !hasActiveSession || !input.value.trim();
    if (sendBtn.firstChild) {
      sendBtn.firstChild.textContent = currentBusy ? 'Working… ' : 'Ask DocuLens ';
    }
  }

  function setBusy(busy) {
    currentBusy = Boolean(busy);
    syncAvailability();
  }

  function setSessionActive(active) {
    hasActiveSession = Boolean(active);
    if (input) {
      input.placeholder = active
        ? 'Ask a specific question about this PDF…'
        : 'Upload a PDF to start asking questions…';
    }
    syncAvailability();
  }

  function getValue() {
    return input ? input.value : '';
  }

  function setValue(value) {
    if (!input) return;
    input.value = value;
    updateCounter();
    resizeTextarea();
    syncAvailability();
  }

  function focus() {
    input?.focus();
  }

  if (input) {
    input.addEventListener('input', () => {
      updateCounter();
      resizeTextarea();
      syncAvailability();
    });
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        if (!currentBusy && form) {
          form.requestSubmit();
        }
      }
    });
  }

  if (form) {
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      onSubmit?.(getValue());
    });
  }

  updateCounter();

  return {
    setBusy,
    setSessionActive,
    getValue,
    setValue,
    focus,
  };
}
