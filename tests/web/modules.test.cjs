const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const root = path.join(__dirname, '../..');
const modUrl = (rel) => pathToFileURL(path.join(root, rel)).href;

test('validation module enforces PDF extension, non-empty size, upload byte limit, and question length', async () => {
  const { validatePdfFile, validateQuestionText } = await import(
    modUrl('frontend/src/utils/validation.js')
  );
  const limits = { max_upload_bytes: 1024, max_pdf_pages: 350 };

  assert.equal(validatePdfFile(null, limits).valid, false);
  assert.equal(validatePdfFile({ name: 'notes.txt', size: 10 }, limits).valid, false);
  assert.equal(validatePdfFile({ name: 'empty.pdf', size: 0 }, limits).valid, false);
  assert.equal(validatePdfFile({ name: 'big.pdf', size: 2048 }, limits).valid, false);
  assert.equal(validatePdfFile({ name: 'ok.pdf', size: 512 }, limits).valid, true);

  assert.equal(validateQuestionText('   ').valid, false);
  assert.equal(validateQuestionText('a'.repeat(2001)).valid, false);
  assert.deepEqual(validateQuestionText('  What is the limit?  '), {
    valid: true,
    question: 'What is the limit?',
  });
});

test('dom utils format sizes, countdowns, and markdown transcripts cleanly', async () => {
  const { formatMiB, formatCountdown, buildMarkdownTranscript } = await import(
    modUrl('frontend/src/utils/dom.js')
  );

  assert.equal(formatMiB(20 * 1024 * 1024), '20 MiB');
  assert.equal(formatCountdown(65), '01:05');
  assert.equal(formatCountdown(-3), '00:00');

  const md = buildMarkdownTranscript(
    { filename: 'spec.pdf', document_id: 'doc-1', page_count: 10, chunk_count: 14 },
    [
      { role: 'user', text: 'What is the limit?' },
      {
        role: 'assistant',
        status: 'answered',
        text: '“Max 350 pages.” (PDF page 2)',
        citations: [{ page_number: 2, excerpt: 'Max 350 pages.' }],
      },
    ],
  );
  assert.match(md, /# DocuLens Transcript — spec\.pdf/);
  assert.match(md, /PDF page 2:\*\* Max 350 pages\./);
});

test('store notifies subscribers and clears subscriptions cleanly', async () => {
  const { createStore } = await import(modUrl('frontend/src/state/store.js'));
  const store = createStore();
  assert.equal(store.getState().limits.max_pdf_pages, 350);

  let observed = null;
  const unsub = store.subscribe((s) => {
    observed = s.busy;
  });
  store.setState({ busy: true });
  assert.equal(observed, true);
  unsub();
  store.setState({ busy: false });
  assert.equal(observed, true);
});

test('apiClient maps HTTP errors and timeouts to ApiError', async () => {
  const { createApiClient, ApiError } = await import(
    modUrl('frontend/src/services/apiClient.js')
  );

  const clientErr = createApiClient({
    fetchImpl: async () => ({
      ok: false,
      status: 413,
      json: async () => ({ detail: { code: 'pdf_page_limit_exceeded', message: 'Too many pages.' } }),
    }),
  });
  await assert.rejects(
    () => clientErr.getStatus(),
    (err) => err instanceof ApiError && err.status === 413 && err.code === 'pdf_page_limit_exceeded',
  );

  const clientNetErr = createApiClient({
    fetchImpl: async () => {
      throw new TypeError('connect ECONNREFUSED');
    },
  });
  await assert.rejects(
    () => clientNetErr.getStatus(),
    (err) => err instanceof ApiError && err.code === 'NETWORK_ERROR',
  );
});
