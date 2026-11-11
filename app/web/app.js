'use strict';
const $ = (id) => document.getElementById(id);
let session = null, originalURL = null, busy = false, generation = 0, activePage = 1;
let limits = {max_upload_bytes: 20971520, max_pdf_pages: 350};

function status(text, error = false) {
  $('upload-status').textContent = text;
  $('upload-status').classList.toggle('error', error);
}
function setBusy(value) {
  busy = value;
  $('file').disabled = value;
  $('dropzone').classList.toggle('busy', value);
  $('remove').disabled = value;
  $('question').disabled = value || !session;
  $('send').disabled = value || !session || !$('question').value.trim();
  $('send').firstChild.textContent = value ? 'Working… ' : 'Ask DocuLens ';
}
async function request(path, options = {}) {
  let response;
  try { response = await fetch(path, options); }
  catch { throw new Error('Could not reach DocuLens. Check that the server is running.'); }
  let data = null;
  if (response.status !== 204) {
    try { data = await response.json(); } catch { /* A generic error is shown below. */ }
  }
  if (!response.ok) {
    const message = data?.detail?.message || (Array.isArray(data?.detail) ? 'Please check the question or PDF and try again.' : `Request failed (${response.status}). Please try again.`);
    const error = new Error(message); error.status = response.status; throw error;
  }
  return data;
}
function auth(s = session) { return {'X-Document-Token': s.document_token}; }
async function refreshConnection() {
  $('connection').disabled = true;
  try {
    const data = await request('/api/status'); limits = data;
    $('connection').classList.toggle('ready', data.model_ready);
    $('connection').querySelector('span').textContent = data.model_ready ? `${data.model} · ready` : 'Model setup needed';
    $('connection').title = `${data.message} Model: ${data.model}. Search: ${data.retrieval_mode}. Click to refresh.`;
    $('limits').textContent = `Selectable text · up to ${Math.floor(data.max_upload_bytes / 1048576)} MiB`;
    if (!data.model_ready && !session) status(data.message);
  } catch (error) {
    $('connection').classList.remove('ready');
    $('connection').querySelector('span').textContent = 'Server unavailable';
    status(error.message, true);
  } finally { $('connection').disabled = false; }
}
function resetConversation() {
  const welcome = $('welcome'); welcome.hidden = false;
  $('conversation').replaceChildren(welcome);
}
async function upload(file) {
  if (!file || busy) return;
  if (!file.name.toLowerCase().endsWith('.pdf')) return status('Please choose a PDF file.', true);
  if (!file.size) return status('This file is empty. Please choose another PDF.', true);
  if (file.size > limits.max_upload_bytes) return status(`The file is too large. The limit is ${Math.floor(limits.max_upload_bytes / 1048576)} MiB.`, true);
  const currentGeneration = ++generation;
  setBusy(true); status('Reading pages and building the search index. The first upload may download the embedding model…');
  const form = new FormData(); form.append('file', file);
  try {
    const data = await request('/api/documents', {method: 'POST', body: form});
    if (generation !== currentGeneration) return;
    const previous = session;
    if (previous) request(`/api/documents/${previous.document_id}`, {method:'DELETE', headers:auth(previous)}).catch(() => {});
    if (originalURL) URL.revokeObjectURL(originalURL);
    originalURL = URL.createObjectURL(new Blob([file], {type: 'application/pdf'})); session = data;
    $('filename').textContent = data.filename;
    $('filedetails').textContent = `${data.page_count} pages · ${data.chunk_count} passages · ready`;
    $('document').hidden = false;
    $('warnings').replaceChildren();
    for (const warning of data.warnings) { const p = document.createElement('p'); p.textContent = warning; $('warnings').append(p); }
    $('warnings').hidden = !data.warnings.length;
    $('question').value = '';
    $('question').placeholder = 'Ask a specific question about this PDF…';
    resetConversation();
    const minutes = Math.round(data.expires_in_seconds / 60);
    status(`Ready for questions. Session expires in ${minutes} minutes.`);
  } catch (error) { status(error.message, true); }
  finally { setBusy(false); $('file').value = ''; if (session) $('question').focus(); }
}
function message(role, text) {
  $('welcome').hidden = true;
  const node = document.createElement('article'); node.className = `message ${role}`;
  const label = document.createElement('div'); label.className = 'message-label'; label.textContent = role === 'user' ? 'YOU' : 'DOCULENS';
  const body = document.createElement('div'); body.className = 'message-body'; body.textContent = text;
  node.append(label, body); $('conversation').append(node);
  $('conversation').scrollTop = $('conversation').scrollHeight;
  return {node, body};
}
async function ask(event) {
  event.preventDefault();
  const question = $('question').value.trim(); if (!session || busy || !question) return;
  const current = session, currentGeneration = generation;
  message('user', question); $('question').value = ''; setBusy(true);
  const pending = message('assistant', 'Finding passages and checking the evidence…'); pending.body.classList.add('pending');
  try {
    const data = await request(`/api/documents/${current.document_id}/ask`, {
      method: 'POST', headers: {...auth(current), 'Content-Type':'application/json'}, body: JSON.stringify({question})
    });
    if (generation !== currentGeneration) return;
    pending.body.classList.remove('pending'); pending.body.textContent = data.answer;
    const badge = document.createElement('span'); badge.className = `answer-badge ${data.status === 'answered' ? '' : 'abstain'}`;
    badge.textContent = data.status === 'answered' ? '✓ Source excerpts verified' : 'Insufficient PDF evidence'; pending.body.before(badge);
    if (data.citations.length) {
      const grid = document.createElement('div'); grid.className = 'evidence-grid';
      for (const citation of data.citations) {
        const card = document.createElement('button'); card.type = 'button'; card.className = 'evidence-card';
        const page = document.createElement('span'); page.className = 'page'; page.textContent = `PDF PAGE ${citation.page_number}`;
        const quote = document.createElement('span'); quote.className = 'quote'; quote.textContent = citation.excerpt;
        const view = document.createElement('span'); view.className = 'view'; view.textContent = 'Read source page ↗';
        card.append(page, quote, view); card.addEventListener('click', () => viewSource(citation, current, currentGeneration)); grid.append(card);
      }
      pending.node.append(grid);
    }
  } catch (error) {
    pending.body.classList.remove('pending'); pending.body.textContent = error.message;
    if (error.status === 404) { status('Your session expired. Upload the PDF again.', true); $('filedetails').textContent = 'Session expired · upload again'; session = null; }
  } finally { setBusy(false); $('conversation').scrollTop = $('conversation').scrollHeight; if (session) $('question').focus(); }
}
function selectSourceTab(pdf) {
  $('source-text').hidden = pdf; $('pdf-frame').hidden = !pdf;
  $('text-tab').classList.toggle('active', !pdf); $('pdf-tab').classList.toggle('active', pdf);
  if (pdf && originalURL) $('pdf-frame').src = `${originalURL}#page=${activePage}`;
}
async function viewSource(citation, current, currentGeneration) {
  if (generation !== currentGeneration || !session) return;
  activePage = citation.page_number;
  $('source-title').textContent = `PDF page ${activePage} · ${current.filename}`;
  $('source-text').textContent = 'Loading the original extracted page…'; selectSourceTab(false);
  if (!$('source-dialog').open) $('source-dialog').showModal();
  try {
    const page = await request(`/api/documents/${current.document_id}/pages/${activePage}`, {headers:auth(current)});
    if (generation !== currentGeneration) return;
    const start = page.text.indexOf(citation.excerpt); $('source-text').replaceChildren();
    if (start >= 0) {
      const highlight = document.createElement('mark'); highlight.textContent = citation.excerpt;
      $('source-text').append(document.createTextNode(page.text.slice(0, start)), highlight, document.createTextNode(page.text.slice(start + citation.excerpt.length)));
      highlight.scrollIntoView({block:'center'});
    } else { $('source-text').textContent = page.text || 'No selectable text on this page.'; }
  } catch (error) { $('source-text').textContent = error.message; }
}
async function removeDocument() {
  if (busy) return;
  const current = session; setBusy(true);
  try { if (current) await request(`/api/documents/${current.document_id}`, {method:'DELETE', headers:auth(current)}); }
  catch (error) { if (error.status !== 404) { status(error.message, true); setBusy(false); return; } }
  generation++; session = null;
  $('source-dialog').close(); $('pdf-frame').removeAttribute('src');
  if (originalURL) URL.revokeObjectURL(originalURL); originalURL = null;
  $('document').hidden = true; $('warnings').hidden = true;
  $('question').value = ''; $('question').placeholder = 'Upload a PDF to start asking questions…';
  resetConversation(); status('Document removed. Choose another PDF to continue.'); setBusy(false);
}
$('file').addEventListener('change', (event) => upload(event.target.files[0]));
$('dropzone').addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); if (!busy) $('file').click(); } });
for (const type of ['dragenter', 'dragover']) $('dropzone').addEventListener(type, event => { event.preventDefault(); $('dropzone').classList.add('dragging'); });
for (const type of ['dragleave', 'drop']) $('dropzone').addEventListener(type, event => { event.preventDefault(); $('dropzone').classList.remove('dragging'); });
$('dropzone').addEventListener('drop', event => upload(event.dataTransfer.files[0]));
$('question').addEventListener('input', () => { $('send').disabled = busy || !session || !$('question').value.trim(); });
$('question').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); if (!busy) $('ask-form').requestSubmit(); } });
$('ask-form').addEventListener('submit', ask);
$('remove').addEventListener('click', removeDocument);
$('connection').addEventListener('click', refreshConnection);
$('close-source').addEventListener('click', () => $('source-dialog').close());
$('text-tab').addEventListener('click', () => selectSourceTab(false));
$('pdf-tab').addEventListener('click', () => selectSourceTab(true));
refreshConnection();
