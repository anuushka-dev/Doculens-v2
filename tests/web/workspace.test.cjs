const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { JSDOM } = require('jsdom');

const root = path.join(__dirname, '../..');
const html = fs.readFileSync(path.join(root, 'frontend/index.html'), 'utf8');
const mainModuleUrl = pathToFileURL(path.join(root, 'frontend/src/main.js')).href;

const documentData = {
  document_id: 'doc-test',
  document_token: 'token-test',
  filename: 'policy.pdf',
  page_count: 3,
  chunk_count: 4,
  expires_in_seconds: 3600,
  warnings: [],
};
const citation = { page_number: 1, excerpt: 'Refunds take 14 days.' };
const supported = {
  answer: '“Refunds take 14 days.” (PDF page 1)',
  status: 'answered',
  citations: [citation],
};

async function until(predicate) {
  for (let i = 0; i < 120; i++) {
    if (predicate()) return;
    await new Promise((r) => setTimeout(r, 5));
  }
  throw new Error('UI did not reach the expected state');
}

async function setup({
  answer = supported,
  answerStatus = 200,
  uploadStatus = 201,
  uploadData = documentData,
} = {}) {
  const dom = new JSDOM(html, { url: 'http://localhost/' });
  const win = dom.window;
  const requests = [];

  win.URL.createObjectURL = () => 'blob:http://localhost/test';
  win.URL.revokeObjectURL = () => {};
  win.Element.prototype.scrollIntoView = () => {};
  win.HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  win.HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  win.navigator.clipboard = {
    writeText: async () => {},
  };

  win.fetch = async (url, opts = {}) => {
    requests.push({ url, opts });
    let data = {};
    let status = 200;
    if (url === '/api/status') {
      data = {
        model: 'test-model',
        model_ready: true,
        message: 'Test fixture',
        retrieval_mode: 'lexical',
        max_upload_bytes: 20971520,
        max_pdf_pages: 350,
      };
    } else if (url === '/api/documents') {
      data = uploadData;
      status = uploadStatus;
    } else if (opts.method === 'DELETE') {
      status = 204;
    } else if (url.endsWith('/ask')) {
      data = answer;
      status = answerStatus;
    } else if (url.includes('/pages/')) {
      const pageNum = Number(url.split('/').pop()) || 1;
      data = {
        page_number: pageNum,
        text:
          pageNum === 1
            ? 'Policy. Refunds take 14 days. Contact support.'
            : `Extracted text for PDF page ${pageNum}.`,
      };
    }
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => data,
    };
  };

  const { createDocuLensApp } = await import(mainModuleUrl);
  const app = createDocuLensApp({ doc: win.document, win, fetchImpl: win.fetch });
  await app.readyPromise;

  const get = (id) => win.document.getElementById(id);

  async function upload(name = 'policy.pdf', sizeBytes = 128) {
    const content = new Uint8Array(sizeBytes).fill(65);
    Object.defineProperty(get('file'), 'files', {
      value: [new win.File([content], name, { type: 'application/pdf' })],
      configurable: true,
    });
    get('file').dispatchEvent(new win.Event('change'));
    await until(() => !get('file').disabled && !get('document').hidden);
  }

  async function uploadExpectingError(name = 'policy.pdf') {
    Object.defineProperty(get('file'), 'files', {
      value: [new win.File(['pdf'], name)],
      configurable: true,
    });
    get('file').dispatchEvent(new win.Event('change'));
    await until(() => !get('file').disabled && get('upload-status').classList.contains('error'));
  }

  async function ask(text = 'How long do refunds take?') {
    get('question').value = text;
    get('question').dispatchEvent(new win.Event('input'));
    get('ask-form').dispatchEvent(new win.Event('submit', { cancelable: true }));
    await until(() => !get('conversation').querySelector('.pending'));
  }

  return {
    dom,
    win,
    app,
    get,
    requests,
    upload,
    uploadExpectingError,
    ask,
    close() {
      app.destroy();
      win.close();
    },
  };
}

test('upload enables asking; source card opens highlighted page, stepper, and original PDF', async () => {
  const ui = await setup();
  try {
    assert.equal(ui.get('question').disabled, true);
    assert.match(ui.get('limits').textContent, /350 pages/);
    assert.equal(ui.get('mode-pill').textContent, 'Lexical mode');

    await ui.upload();
    assert.equal(ui.get('question').disabled, false);
    assert.equal(ui.get('starter-prompts').hidden, false);
    assert.match(ui.get('session-expiry').textContent, /^Expires in /);

    await ui.ask();
    assert.match(ui.get('conversation').textContent, /14 days/);
    assert.equal(ui.get('clear-chat').hidden, false);
    assert.equal(ui.get('export-chat').hidden, false);

    ui.get('conversation').querySelector('.evidence-card').click();
    await until(() => ui.get('source-text').querySelector('mark'));
    assert.equal(ui.get('source-text').querySelector('mark').textContent, citation.excerpt);
    assert.equal(ui.get('source-dialog').open, true);
    assert.equal(ui.get('page-indicator').textContent, 'Page 1 of 3');
    assert.equal(ui.get('prev-page').disabled, true);
    assert.equal(ui.get('next-page').disabled, false);

    ui.get('next-page').click();
    await until(() => /Extracted text for PDF page 2/.test(ui.get('source-text').textContent));
    assert.equal(ui.get('page-indicator').textContent, 'Page 2 of 3');
    assert.match(ui.get('source-text').textContent, /Extracted text for PDF page 2/);

    ui.get('pdf-tab').click();
    assert.match(ui.get('pdf-frame').src, /#page=2$/);
    assert.equal(
      ui.requests.find((r) => r.url.endsWith('/ask')).opts.headers['X-Document-Token'],
      'token-test',
    );
  } finally {
    ui.close();
  }
});

test('unrelated question shows abstention without a citation card', async () => {
  const ui = await setup({
    answer: {
      answer: 'Out of PDF content.',
      status: 'insufficient_evidence',
      citations: [],
    },
  });
  try {
    await ui.upload();
    await ui.ask('Who won Wimbledon?');
    assert.match(ui.get('conversation').textContent, /Out of PDF content/);
    assert.equal(ui.get('conversation').querySelectorAll('.evidence-card').length, 0);
  } finally {
    ui.close();
  }
});

test('document text and filenames are rendered as text, never executable HTML', async () => {
  const dangerous = '<img src=x onerror="alert(1)">';
  const ui = await setup({
    answer: {
      answer: dangerous,
      status: 'answered',
      citations: [{ ...citation, excerpt: dangerous }],
    },
    uploadData: { ...documentData, filename: `${dangerous}.pdf` },
  });
  try {
    await ui.upload();
    await ui.ask();
    assert.match(ui.get('filename').textContent, /<img/);
    assert.match(ui.get('conversation').textContent, /<img/);
    assert.equal(ui.get('conversation').querySelectorAll('img').length, 0);
    assert.equal(ui.get('filename').querySelectorAll('img').length, 0);
  } finally {
    ui.close();
  }
});

test('failed upload reports an error and keeps asking disabled', async () => {
  const ui = await setup({
    uploadStatus: 422,
    uploadData: { detail: { message: 'No selectable text was found.' } },
  });
  try {
    await ui.uploadExpectingError();
    assert.match(ui.get('upload-status').textContent, /No selectable/);
    assert.equal(ui.get('question').disabled, true);
  } finally {
    ui.close();
  }
});

test('expired session disables asking and can still be cleared from the interface', async () => {
  const ui = await setup({
    answerStatus: 404,
    answer: { detail: { message: 'Session expired.' } },
  });
  try {
    await ui.upload();
    await ui.ask();
    assert.equal(ui.get('question').disabled, true);
    assert.match(ui.get('filedetails').textContent, /Session expired/);
    ui.get('remove').click();
    await until(() => ui.get('document').hidden);
    assert.equal(ui.get('conversation').querySelectorAll('.message').length, 0);
  } finally {
    ui.close();
  }
});

test('removing a document clears the conversation and deletes its authorized session', async () => {
  const ui = await setup();
  try {
    await ui.upload();
    await ui.ask();
    ui.get('remove').click();
    await until(() => ui.get('document').hidden);
    assert.equal(ui.get('question').disabled, true);
    assert.equal(ui.get('conversation').querySelectorAll('.message').length, 0);
    assert.ok(
      ui.requests.some(
        (r) =>
          r.opts.method === 'DELETE' &&
          r.opts.headers['X-Document-Token'] === 'token-test',
      ),
    );
  } finally {
    ui.close();
  }
});

test('clear chat resets messages while retaining the indexed document', async () => {
  const ui = await setup();
  try {
    await ui.upload();
    await ui.ask();
    assert.equal(ui.get('conversation').querySelectorAll('.message').length, 2);
    ui.get('clear-chat').click();
    assert.equal(ui.get('conversation').querySelectorAll('.message').length, 0);
    assert.equal(ui.get('question').disabled, false);
    assert.equal(ui.get('starter-prompts').hidden, false);
  } finally {
    ui.close();
  }
});

test('follow-up question sends history, renders understood-as note, and page pills open source page', async () => {
  const multiPageAnswer = {
    answer: 'Max 350 pages per PDF.\n\nSource: PDF page 2',
    status: 'answered',
    citations: [{ page_number: 2, excerpt: 'Maximum PDF pages: 350.' }],
    cited_pages: [2],
    resolved_question: 'What is the maximum PDF page limit?',
  };
  const ui = await setup({ answer: multiPageAnswer });
  try {
    await ui.upload();
    await ui.ask('What is DocuLens?');
    await ui.ask('What about its limit?');

    const askCalls = ui.requests.filter((r) => r.url.endsWith('/ask'));
    assert.equal(askCalls.length, 2);
    const firstBody = JSON.parse(askCalls[0].opts.body);
    assert.equal(firstBody.history, undefined);
    const secondBody = JSON.parse(askCalls[1].opts.body);
    assert.equal(secondBody.history.length, 2);
    assert.equal(secondBody.history[0].role, 'user');
    assert.equal(secondBody.history[1].role, 'assistant');

    assert.match(
      ui.get('conversation').textContent,
      /Understood as: What is the maximum PDF page limit\?/,
    );
    const pagePill = ui.get('conversation').querySelector('.page-pill');
    assert.ok(pagePill);
    assert.equal(pagePill.textContent, 'PDF page 2');
    pagePill.click();
    await until(() => /Extracted text for PDF page 2/.test(ui.get('source-text').textContent));
    assert.equal(ui.get('source-dialog').open, true);
    assert.equal(ui.get('page-indicator').textContent, 'Page 2 of 3');
  } finally {
    ui.close();
  }
});
