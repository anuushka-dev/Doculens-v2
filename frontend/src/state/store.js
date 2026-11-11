/**
 * Centralized reactive store for DocuLens workspace state.
 */

import { DEFAULT_LIMITS } from '../config/constants.js';

export function createStore(initial = {}) {
  let state = {
    limits: { ...DEFAULT_LIMITS },
    connection: {
      model: null,
      modelReady: false,
      retrievalMode: 'hybrid',
      message: 'Checking model…',
      reachable: true,
    },
    session: null,
    sessionExpired: false,
    expiresAtMs: null,
    originalURL: null,
    busy: false,
    generation: 0,
    messages: [],
    activePage: 1,
    activeCitation: null,
    activeTab: 'text',
    ...initial,
  };

  const listeners = new Set();

  return {
    getState() {
      return state;
    },
    setState(patch) {
      state = { ...state, ...patch };
      for (const listener of listeners) {
        listener(state);
      }
      return state;
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
