/**
 * Upload sidebar: drag/drop, file picker, limits label, warnings, and session TTL timer.
 */

import { EXPIRY_WARNING_SECONDS } from '../config/constants.js';
import { createEl, formatCountdown, formatMiB, getById } from '../utils/dom.js';

export function createUploadSidebar(doc, { onFileSelected, onRemove, onExpired } = {}) {
  const dropzone = getById(doc, 'dropzone');
  const fileInput = getById(doc, 'file');
  const limitsEl = getById(doc, 'limits');
  const docCard = getById(doc, 'document');
  const filenameEl = getById(doc, 'filename');
  const detailsEl = getById(doc, 'filedetails');
  const expiryEl = getById(doc, 'session-expiry');
  const removeBtn = getById(doc, 'remove');
  const statusEl = getById(doc, 'upload-status');
  const warningsEl = getById(doc, 'warnings');

  let countdownTimer = null;

  function setStatus(text, isError = false) {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.classList.toggle('error', isError);
  }

  function setBusy(busy) {
    if (fileInput) fileInput.disabled = busy;
    if (dropzone) dropzone.classList.toggle('busy', busy);
    if (removeBtn) removeBtn.disabled = busy;
  }

  function renderLimits(limits) {
    if (!limitsEl || !limits) return;
    const sizeText = formatMiB(limits.max_upload_bytes);
    const pagesText = limits.max_pdf_pages ?? 350;
    limitsEl.textContent = `Selectable text · up to ${sizeText} · max ${pagesText} pages`;
  }

  function stopCountdown() {
    if (countdownTimer) {
      clearInterval(countdownTimer);
      countdownTimer = null;
    }
  }

  function updateCountdown(expiresAtMs) {
    if (!expiryEl || !expiresAtMs) return;
    const remainingSec = Math.max(0, Math.ceil((expiresAtMs - Date.now()) / 1000));
    if (remainingSec <= 0) {
      expiryEl.hidden = false;
      expiryEl.textContent = 'Session expired';
      expiryEl.className = 'session-expiry expired';
      stopCountdown();
      onExpired?.();
      return;
    }
    expiryEl.hidden = false;
    expiryEl.textContent = `Expires in ${formatCountdown(remainingSec)}`;
    expiryEl.className =
      remainingSec <= EXPIRY_WARNING_SECONDS
        ? 'session-expiry warning'
        : 'session-expiry';
  }

  function renderSession(session, { expired = false, expiresAtMs = null } = {}) {
    stopCountdown();
    if (!session && !expired) {
      if (docCard) docCard.hidden = true;
      if (warningsEl) {
        warningsEl.hidden = true;
        warningsEl.replaceChildren();
      }
      if (expiryEl) expiryEl.hidden = true;
      return;
    }

    if (docCard) docCard.hidden = false;
    if (session) {
      if (filenameEl) filenameEl.textContent = session.filename;
      if (detailsEl) {
        detailsEl.textContent = expired
          ? 'Session expired · upload again'
          : `${session.page_count} pages · ${session.chunk_count} passages · ready`;
      }
      if (warningsEl) {
        warningsEl.replaceChildren();
        for (const warning of session.warnings || []) {
          warningsEl.append(createEl(doc, 'p', { text: warning }));
        }
        warningsEl.hidden = !(session.warnings && session.warnings.length);
      }
    } else if (expired && detailsEl) {
      detailsEl.textContent = 'Session expired · upload again';
    }

    if (expired) {
      if (expiryEl) {
        expiryEl.hidden = false;
        expiryEl.textContent = 'Session expired';
        expiryEl.className = 'session-expiry expired';
      }
      return;
    }

    if (expiresAtMs) {
      updateCountdown(expiresAtMs);
      countdownTimer = setInterval(() => updateCountdown(expiresAtMs), 1000);
      countdownTimer.unref?.();
    }
  }

  function clearFileInput() {
    if (fileInput) fileInput.value = '';
  }

  if (fileInput) {
    fileInput.addEventListener('change', (event) => {
      onFileSelected?.(event.target.files?.[0]);
    });
  }

  if (dropzone) {
    dropzone.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        if (!fileInput?.disabled) fileInput?.click();
      }
    });
    for (const type of ['dragenter', 'dragover']) {
      dropzone.addEventListener(type, (event) => {
        event.preventDefault();
        dropzone.classList.add('dragging');
      });
    }
    for (const type of ['dragleave', 'drop']) {
      dropzone.addEventListener(type, (event) => {
        event.preventDefault();
        dropzone.classList.remove('dragging');
      });
    }
    dropzone.addEventListener('drop', (event) => {
      onFileSelected?.(event.dataTransfer?.files?.[0]);
    });
  }

  if (removeBtn) {
    removeBtn.addEventListener('click', () => onRemove?.());
  }

  return {
    setStatus,
    setBusy,
    renderLimits,
    renderSession,
    clearFileInput,
    destroy: stopCountdown,
  };
}
