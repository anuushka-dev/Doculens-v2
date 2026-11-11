const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const root = path.join(__dirname, '../..');
const html = fs.readFileSync(path.join(root, 'app/web/index.html'), 'utf8');
const script = fs.readFileSync(path.join(root, 'app/web/app.js'), 'utf8');
const documentData = {document_id:'doc-test',document_token:'token-test',filename:'policy.pdf',page_count:2,chunk_count:2,expires_in_seconds:3600,warnings:[]};
const citation = {page_number:1,excerpt:'Refunds take 14 days.'};
const supported = {answer:'“Refunds take 14 days.” (PDF page 1)', status:'answered',citations:[citation]};
async function until(predicate) {
  for (let i=0; i<100; i++) { if (predicate()) return; await new Promise(r=>setTimeout(r, 5)); }
  throw new Error('UI did not reach the expected state');
}
function setup({answer=supported, answerStatus=200, uploadStatus=201, uploadData=documentData}={}) {
  const dom = new JSDOM(html, {url:'http://localhost/',runScripts:'outside-only'});
  const win = dom.window, requests=[];
  win.URL.createObjectURL = () => 'blob:http://localhost/test';
  win.URL.revokeObjectURL = () => {};
  win.Element.prototype.scrollIntoView = () => {};
  win.HTMLDialogElement.prototype.showModal = function(){this.open=true;};
  win.HTMLDialogElement.prototype.close = function(){this.open=false;};
  win.fetch = async (url, opts={}) => {
    requests.push({url,opts}); let data={},status=200;
    if (url==='/api/status') data={model:'test',model_ready:true,message:'Test fixture',retrieval_mode:'lexical',max_upload_bytes:20971520};
    else if (url==='/api/documents') {data=uploadData;status=uploadStatus;}
    else if (opts.method==='DELETE') status=204;
    else if (url.endsWith('/ask')) {data=answer;status=answerStatus;}
    else if (url.includes('/pages/')) data={page_number:1,text:'Policy. Refunds take 14 days. Contact support.'};
    return {ok:status>=200&&status<300,status,json:async()=>data};
  };
  win.eval(script);
  const get=id=>win.document.getElementById(id);
  async function upload(name='policy.pdf') {
    Object.defineProperty(get('file'),'files',{value:[new win.File(['pdf'],name)], configurable:true});
    get('file').dispatchEvent(new win.Event('change'));
    await until(()=>!get('file').disabled);
  }
  async function ask(text='How long do refunds take?') {
    get('question').value=text;get('question').dispatchEvent(new win.Event('input'));
    get('ask-form').dispatchEvent(new win.Event('submit',{cancelable:true}));
    await until(()=>!get('conversation').querySelector('.pending'));
  }
  return {dom,win,get,requests,upload,ask};
}

test('upload enables asking; source card opens highlighted page and original PDF',async()=>{
  const ui=setup();
  try {
    assert.equal(ui.get('question').disabled,true);
    await ui.upload(); assert.equal(ui.get('question').disabled,false);
    await ui.ask();
    assert.match(ui.get('conversation').textContent,/14 days/);
    ui.get('conversation').querySelector('.evidence-card').click();
    await until(()=>ui.get('source-text').querySelector('mark'));
    assert.equal(ui.get('source-text').querySelector('mark').textContent,citation.excerpt);
    assert.equal(ui.get('source-dialog').open,true);
    ui.get('pdf-tab').click();assert.match(ui.get('pdf-frame').src,/#page=1$/);
    assert.equal(ui.requests.find(r=>r.url.endsWith('/ask')).opts.headers['X-Document-Token'],'token-test');
  } finally {ui.dom.window.close();}
});

test('unrelated question shows abstention without a citation card',async()=>{
  const ui=setup({answer:{answer:'Out of PDF content.',status:'insufficient_evidence',citations:[]}});
  try {
    await ui.upload();await ui.ask('Who won Wimbledon?');
    assert.match(ui.get('conversation').textContent,/Out of PDF content/);
    assert.equal(ui.get('conversation').querySelectorAll('.evidence-card').length,0);
  } finally {ui.dom.window.close();}
});

test('document text and filenames are rendered as text, never executable HTML',async()=>{
  const dangerous='<img src=x onerror="alert(1)">';
  const ui=setup({answer:{answer:dangerous,status:'answered',citations:[{...citation,excerpt:dangerous}]},uploadData:{...documentData,filename:dangerous+'.pdf'}});
  try {
    await ui.upload();await ui.ask();
    assert.match(ui.get('filename').textContent,/<img/);
    assert.match(ui.get('conversation').textContent,/<img/);
    assert.equal(ui.get('conversation').querySelectorAll('img').length,0);
    assert.equal(ui.get('filename').querySelectorAll('img').length,0);
  } finally {ui.dom.window.close();}
});

test('failed upload reports an error and keeps asking disabled',async()=>{
  const ui=setup({uploadStatus:422,uploadData:{detail:{message:'No selectable text was found.'}}});
  try {await ui.upload();assert.match(ui.get('upload-status').textContent,/No selectable/);assert.equal(ui.get('question').disabled,true);}
  finally {ui.dom.window.close();}
});

test('expired session disables asking and can still be cleared from the interface',async()=>{
  const ui=setup({answerStatus:404,answer:{detail:{message:'Session expired.'}}});
  try {
    await ui.upload();await ui.ask();assert.equal(ui.get('question').disabled,true);
    assert.match(ui.get('filedetails').textContent,/Session expired/);
    ui.get('remove').click();await until(()=>ui.get('document').hidden);
    assert.equal(ui.get('conversation').querySelectorAll('.message').length,0);
  } finally {ui.dom.window.close();}
});

test('removing a document clears the conversation and deletes its authorized session',async()=>{
  const ui=setup();
  try {
    await ui.upload();await ui.ask();ui.get('remove').click();await until(()=>ui.get('document').hidden);
    assert.equal(ui.get('question').disabled,true);
    assert.equal(ui.get('conversation').querySelectorAll('.message').length,0);
    assert.ok(ui.requests.some(r=>r.opts.method==='DELETE'&&r.opts.headers['X-Document-Token']==='token-test'));
  } finally {ui.dom.window.close();}
});
