/**
 * Header connection badge and retrieval mode indicator.
 */

import { getById } from '../utils/dom.js';

export function createHeaderBar(doc, { onRefresh } = {}) {
  const connectionBtn = getById(doc, 'connection');
  const modePill = getById(doc, 'mode-pill');

  if (connectionBtn && onRefresh) {
    connectionBtn.addEventListener('click', onRefresh);
  }

  function setLoading(loading) {
    if (connectionBtn) connectionBtn.disabled = loading;
  }

  function renderConnection({ model, modelReady, retrievalMode, message, reachable }) {
    if (connectionBtn) {
      connectionBtn.classList.toggle('ready', Boolean(reachable && modelReady));
      const label = connectionBtn.querySelector('span');
      if (label) {
        if (!reachable) {
          label.textContent = 'Server unavailable';
        } else {
          label.textContent = modelReady ? `${model} · ready` : 'Model setup needed';
        }
      }
      connectionBtn.title = reachable
        ? `${message} Model: ${model}. Search: ${retrievalMode}. Click to refresh.`
        : 'Server unavailable. Click to retry connection.';
    }

    if (modePill) {
      if (!reachable) {
        modePill.hidden = true;
      } else {
        const lexical = retrievalMode === 'lexical';
        modePill.hidden = false;
        modePill.classList.toggle('lexical', lexical);
        modePill.textContent = lexical ? 'Lexical mode' : 'Hybrid search';
      }
    }
  }

  return { setLoading, renderConnection };
}
