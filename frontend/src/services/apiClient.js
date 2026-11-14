/**
 * HTTP client for DocuLens backend endpoints.
 */

import { REQUEST_TIMEOUTS_MS } from '../config/constants.js';

export class ApiError extends Error {
  constructor(message, { status = 0, code = 'REQUEST_FAILED' } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

export function createApiClient({ fetchImpl, win } = {}) {
  const fetcher = fetchImpl || ((url, opts) => win.fetch(url, opts));
  const AbortCtrl = win?.AbortController || globalThis.AbortController;

  async function request(path, options = {}, timeoutMs = 30_000) {
    let controller = null;
    let timer = null;
    const fetchOpts = { ...options };

    if (AbortCtrl && !fetchOpts.signal && timeoutMs > 0) {
      controller = new AbortCtrl();
      fetchOpts.signal = controller.signal;
      timer = setTimeout(() => controller.abort(), timeoutMs);
    }

    let response;
    try {
      response = await fetcher(path, fetchOpts);
    } catch (err) {
      if (err?.name === 'AbortError') {
        throw new ApiError('The request timed out. Please retry.', {
          status: 504,
          code: 'CLIENT_TIMEOUT',
        });
      }
      throw new ApiError(
        'Could not reach DocuLens. Check that the server is running.',
        { status: 0, code: 'NETWORK_ERROR' },
      );
    } finally {
      if (timer) clearTimeout(timer);
    }

    let data = null;
    if (response.status !== 204) {
      try {
        data = await response.json();
      } catch {
        data = null;
      }
    }

    if (!response.ok) {
      const detail = data?.detail;
      const message =
        detail?.message ||
        (Array.isArray(detail)
          ? 'Please check the question or PDF and try again.'
          : `Request failed (${response.status}). Please try again.`);
      throw new ApiError(message, {
        status: response.status,
        code: detail?.code || `HTTP_${response.status}`,
      });
    }

    return data;
  }

  function authHeaders(session) {
    return { 'X-Document-Token': session.document_token };
  }

  return {
    getStatus() {
      return request('/api/status', {}, REQUEST_TIMEOUTS_MS.status);
    },
    uploadDocument(file) {
      const form = new FormData();
      form.append('file', file);
      return request('/api/documents', { method: 'POST', body: form }, REQUEST_TIMEOUTS_MS.upload);
    },
    askQuestion(session, question, history = []) {
      const payload = history.length ? { question, history } : { question };
      return request(
        `/api/documents/${session.document_id}/ask`,
        {
          method: 'POST',
          headers: { ...authHeaders(session), 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
        REQUEST_TIMEOUTS_MS.ask,
      );
    },
    getSourcePage(session, pageNumber) {
      return request(
        `/api/documents/${session.document_id}/pages/${pageNumber}`,
        { headers: authHeaders(session) },
        REQUEST_TIMEOUTS_MS.page,
      );
    },
    deleteDocument(session) {
      return request(
        `/api/documents/${session.document_id}`,
        { method: 'DELETE', headers: authHeaders(session) },
        REQUEST_TIMEOUTS_MS.remove,
      );
    },
  };
}
