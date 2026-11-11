/**
 * Source evidence modal: extracted text highlighting, original PDF iframe, and page stepper.
 */

import { getById } from '../utils/dom.js';

export function createSourceModal(doc, { onFetchPage, onCopyPage } = {}) {
  const dialog = getById(doc, 'source-dialog');
  const titleEl = getById(doc, 'source-title');
  const closeBtn = getById(doc, 'close-source');
  const textTabBtn = getById(doc, 'text-tab');
  const pdfTabBtn = getById(doc, 'pdf-tab');
  const prevBtn = getById(doc, 'prev-page');
  const nextBtn = getById(doc, 'next-page');
  const pageIndicator = getById(doc, 'page-indicator');
  const copyPageBtn = getById(doc, 'copy-page');
  const matchInfoEl = getById(doc, 'source-match-info');
  const sourceTextEl = getById(doc, 'source-text');
  const pdfFrame = getById(doc, 'pdf-frame');

  let activePage = 1;
  let totalPages = 1;
  let activeFilename = '';
  let activeExcerpt = '';
  let activeOriginalUrl = null;
  let activePageText = '';
  let activeRequestSeq = 0;

  function selectTab(showPdf) {
    if (sourceTextEl) sourceTextEl.hidden = showPdf;
    if (pdfFrame) pdfFrame.hidden = !showPdf;
    if (textTabBtn) textTabBtn.classList.toggle('active', !showPdf);
    if (pdfTabBtn) pdfTabBtn.classList.toggle('active', showPdf);
    if (showPdf && pdfFrame && activeOriginalUrl) {
      pdfFrame.src = `${activeOriginalUrl}#page=${activePage}`;
    }
  }

  function updateStepper() {
    if (pageIndicator) {
      pageIndicator.textContent = `Page ${activePage} of ${totalPages}`;
    }
    if (prevBtn) prevBtn.disabled = activePage <= 1;
    if (nextBtn) nextBtn.disabled = activePage >= totalPages;
  }

  function renderHighlightedPage(pageText, excerpt) {
    if (!sourceTextEl) return;
    activePageText = pageText || '';
    sourceTextEl.replaceChildren();

    if (!pageText) {
      sourceTextEl.textContent = 'No selectable text on this page.';
      if (matchInfoEl) matchInfoEl.textContent = '';
      return;
    }

    const start = excerpt ? pageText.indexOf(excerpt) : -1;
    if (start >= 0) {
      const highlight = doc.createElement('mark');
      highlight.textContent = excerpt;
      sourceTextEl.append(
        doc.createTextNode(pageText.slice(0, start)),
        highlight,
        doc.createTextNode(pageText.slice(start + excerpt.length)),
      );
      highlight.scrollIntoView({ block: 'center' });
      if (matchInfoEl) matchInfoEl.textContent = 'Cited excerpt highlighted';
    } else {
      sourceTextEl.textContent = pageText;
      if (matchInfoEl) matchInfoEl.textContent = `${pageText.length.toLocaleString()} chars`;
    }
  }

  async function loadPage(pageNumber, excerptToHighlight = '') {
    activePage = pageNumber;
    const seq = ++activeRequestSeq;
    updateStepper();

    if (titleEl) titleEl.textContent = `PDF page ${activePage} · ${activeFilename}`;
    if (sourceTextEl) sourceTextEl.textContent = 'Loading the original extracted page…';
    if (matchInfoEl) matchInfoEl.textContent = '';
    if (pdfFrame && !pdfFrame.hidden && activeOriginalUrl) {
      pdfFrame.src = `${activeOriginalUrl}#page=${activePage}`;
    }

    try {
      const page = await onFetchPage(activePage);
      if (seq !== activeRequestSeq) return;
      renderHighlightedPage(page?.text || '', excerptToHighlight);
    } catch (error) {
      if (seq !== activeRequestSeq) return;
      if (sourceTextEl) sourceTextEl.textContent = error.message;
    }
  }

  async function open({ citation, session, originalURL }) {
    if (!session) return;
    activeFilename = session.filename;
    totalPages = Math.max(1, session.page_count || 1);
    activeExcerpt = citation?.excerpt || '';
    activeOriginalUrl = originalURL;
    selectTab(false);
    if (dialog && !dialog.open) dialog.showModal();
    await loadPage(citation.page_number, activeExcerpt);
  }

  function close() {
    activeRequestSeq++;
    if (dialog?.open) dialog.close();
    if (pdfFrame) pdfFrame.removeAttribute('src');
    activePageText = '';
  }

  if (closeBtn) closeBtn.addEventListener('click', close);
  if (textTabBtn) textTabBtn.addEventListener('click', () => selectTab(false));
  if (pdfTabBtn) pdfTabBtn.addEventListener('click', () => selectTab(true));
  if (prevBtn) {
    prevBtn.addEventListener('click', () => {
      if (activePage > 1) loadPage(activePage - 1, activeExcerpt);
    });
  }
  if (nextBtn) {
    nextBtn.addEventListener('click', () => {
      if (activePage < totalPages) loadPage(activePage + 1, activeExcerpt);
    });
  }
  if (copyPageBtn) {
    copyPageBtn.addEventListener('click', () => onCopyPage?.(activePageText));
  }

  return { open, close, selectTab };
}
