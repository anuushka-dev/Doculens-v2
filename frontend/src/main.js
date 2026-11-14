/**
 * DocuLens application entrypoint and coordinator.
 */

import { buildMarkdownTranscript, copyToClipboard } from './utils/dom.js';
import { validatePdfFile, validateQuestionText } from './utils/validation.js';
import { createStore } from './state/store.js';
import { createApiClient } from './services/apiClient.js';
import { createToastManager } from './components/toast.js';
import { createHeaderBar } from './components/headerBar.js';
import { createUploadSidebar } from './components/uploadSidebar.js';
import { createConversationView } from './components/conversation.js';
import { createComposer } from './components/composer.js';
import { createSourceModal } from './components/sourceModal.js';

export function createDocuLensApp({ doc = document, win = window, fetchImpl } = {}) {
  const store = createStore();
  const api = createApiClient({ fetchImpl, win });
  const toast = createToastManager(doc);

  let composer;
  let sidebar;
  let conversation;
  let modal;

  function setBusy(busy) {
    store.setState({ busy });
    sidebar.setBusy(busy);
    composer.setBusy(busy);
  }

  async function handleCopy(text) {
    const ok = await copyToClipboard(text, win);
    toast.show(ok ? 'Copied to clipboard.' : 'Clipboard copy is unavailable in this browser.', {
      error: !ok,
    });
  }

  async function refreshConnection() {
    header.setLoading(true);
    try {
      const data = await api.getStatus();
      store.setState({
        limits: data,
        connection: {
          model: data.model,
          modelReady: Boolean(data.model_ready),
          retrievalMode: data.retrieval_mode || 'hybrid',
          message: data.message,
          reachable: true,
        },
      });
      sidebar.renderLimits(data);
      header.renderConnection(store.getState().connection);
      if (!data.model_ready && !store.getState().session) {
        sidebar.setStatus(data.message);
      }
    } catch (error) {
      store.setState({
        connection: {
          ...store.getState().connection,
          reachable: false,
          modelReady: false,
        },
      });
      header.renderConnection(store.getState().connection);
      sidebar.setStatus(error.message, true);
    } finally {
      header.setLoading(false);
    }
  }

  async function upload(file) {
    const { busy, limits } = store.getState();
    if (!file || busy) return;

    const check = validatePdfFile(file, limits);
    if (!check.valid) {
      sidebar.setStatus(check.message, true);
      return;
    }

    const currentGeneration = store.getState().generation + 1;
    store.setState({ generation: currentGeneration });
    setBusy(true);
    sidebar.setStatus(
      'Reading pages and building the search index. The first upload may download the embedding model…',
    );

    try {
      const data = await api.uploadDocument(file);
      if (store.getState().generation !== currentGeneration) return;

      const prev = store.getState();
      if (prev.session) {
        api.deleteDocument(prev.session).catch(() => {});
      }
      if (prev.originalURL) {
        win.URL.revokeObjectURL(prev.originalURL);
      }

      const originalURL = win.URL.createObjectURL(new win.Blob([file], { type: 'application/pdf' }));
      const expiresAtMs = Date.now() + (data.expires_in_seconds || 3600) * 1000;

      store.setState({
        session: data,
        sessionExpired: false,
        expiresAtMs,
        originalURL,
        messages: [],
      });

      sidebar.renderSession(data, { expired: false, expiresAtMs });
      conversation.reset({ hasSession: true });
      composer.setValue('');
      composer.setSessionActive(true);

      const minutes = Math.round((data.expires_in_seconds || 3600) / 60);
      sidebar.setStatus(`Ready for questions. Session expires in ${minutes} minutes.`);
    } catch (error) {
      sidebar.setStatus(error.message, true);
    } finally {
      setBusy(false);
      sidebar.clearFileInput();
      if (store.getState().session) composer.focus();
    }
  }

  async function ask(rawQuestion) {
    const state = store.getState();
    if (!state.session || state.busy) return;

    const check = validateQuestionText(rawQuestion);
    if (!check.valid) return;

    const currentSession = state.session;
    const currentGeneration = state.generation;
    const userMessage = { role: 'user', text: check.question };

    const history = store
      .getState()
      .messages.slice(-6)
      .filter((msg) => msg && typeof msg.text === 'string' && msg.text.trim())
      .map((msg) => ({
        role: msg.role === 'user' ? 'user' : 'assistant',
        content: msg.text.trim().slice(0, 1200),
      }));

    composer.setValue('');
    conversation.appendUserMessage(check.question);
    setBusy(true);
    const pending = conversation.appendPendingAssistant();

    try {
      const data = await api.askQuestion(currentSession, check.question, history);
      if (store.getState().generation !== currentGeneration) return;

      pending.resolve(data);
      store.setState({
        messages: [
          ...store.getState().messages,
          userMessage,
          {
            role: 'assistant',
            text: data.answer,
            status: data.status,
            citations: data.citations || [],
            citedPages: data.cited_pages || [],
            resolvedQuestion: data.resolved_question || null,
          },
        ],
      });
    } catch (error) {
      pending.reject(error.message);
      if (error.status === 404) {
        handleSessionExpired();
      }
    } finally {
      setBusy(false);
      if (store.getState().session) composer.focus();
    }
  }

  function handleSessionExpired() {
    const { session } = store.getState();
    store.setState({ session: null, sessionExpired: true, expiresAtMs: null });
    sidebar.renderSession(session, { expired: true });
    sidebar.setStatus('Your session expired. Upload the PDF again.', true);
    composer.setSessionActive(false);
  }

  async function removeDocument() {
    const state = store.getState();
    if (state.busy) return;

    setBusy(true);
    try {
      if (state.session) {
        await api.deleteDocument(state.session);
      }
    } catch (error) {
      if (error.status !== 404) {
        sidebar.setStatus(error.message, true);
        setBusy(false);
        return;
      }
    }

    modal.close();
    if (state.originalURL) {
      win.URL.revokeObjectURL(state.originalURL);
    }

    store.setState({
      generation: state.generation + 1,
      session: null,
      sessionExpired: false,
      expiresAtMs: null,
      originalURL: null,
      messages: [],
    });

    sidebar.renderSession(null);
    composer.setValue('');
    composer.setSessionActive(false);
    conversation.reset({ hasSession: false });
    sidebar.setStatus('Document removed. Choose another PDF to continue.');
    setBusy(false);
  }

  function clearChat() {
    const { session, busy } = store.getState();
    if (busy) return;
    store.setState({ messages: [] });
    conversation.reset({ hasSession: Boolean(session) });
    if (session) composer.focus();
  }

  function exportChat() {
    const { session, messages } = store.getState();
    if (!messages.length) return;
    const markdown = buildMarkdownTranscript(session, messages);
    const blob = new win.Blob([markdown], { type: 'text/markdown;charset=utf-8' });
    const url = win.URL.createObjectURL(blob);
    const anchor = doc.createElement('a');
    anchor.href = url;
    const baseName = (session?.filename || 'doculens').replace(/\.pdf$/i, '');
    anchor.download = `${baseName}-transcript.md`;
    doc.body.append(anchor);
    anchor.click();
    anchor.remove();
    win.URL.revokeObjectURL(url);
    toast.show('Exported Markdown transcript.');
  }

  const header = createHeaderBar(doc, { onRefresh: refreshConnection });
  sidebar = createUploadSidebar(doc, {
    onFileSelected: upload,
    onRemove: removeDocument,
    onExpired: handleSessionExpired,
  });
  conversation = createConversationView(doc, {
    onSelectCitation: (citation) => {
      const { session, originalURL } = store.getState();
      modal.open({ citation, session, originalURL });
    },
    onStarterPrompt: (promptText) => ask(promptText),
    onCopyText: handleCopy,
    onClearChat: clearChat,
    onExportChat: exportChat,
  });
  composer = createComposer(doc, { onSubmit: ask });
  modal = createSourceModal(doc, {
    onFetchPage: (pageNumber) => {
      const { session } = store.getState();
      if (!session) throw new Error('Session unavailable.');
      return api.getSourcePage(session, pageNumber);
    },
    onCopyPage: handleCopy,
  });

  sidebar.renderLimits(store.getState().limits);
  composer.setSessionActive(false);
  const readyPromise = refreshConnection();

  function destroy() {
    sidebar.destroy();
    conversation.destroy();
    toast.destroy();
    const { originalURL } = store.getState();
    if (originalURL) win.URL.revokeObjectURL(originalURL);
  }

  return {
    store,
    api,
    readyPromise,
    refreshConnection,
    upload,
    ask,
    removeDocument,
    clearChat,
    exportChat,
    destroy,
  };
}

if (typeof window !== 'undefined' && typeof document !== 'undefined' && !window.__DOCULENS_TEST__) {
  createDocuLensApp({ doc: document, win: window });
}
