/**
 * Accessible toast notification region.
 */

import { createEl, getById } from '../utils/dom.js';

export function createToastManager(doc, { durationMs = 2600 } = {}) {
  const region = getById(doc, 'toast-region');
  const timers = new Set();

  function show(message, { error = false } = {}) {
    if (!region || !message) return;
    const toast = createEl(doc, 'div', {
      className: error ? 'toast error' : 'toast',
      text: message,
    });
    region.append(toast);
    const timer = setTimeout(() => {
      timers.delete(timer);
      toast.remove();
    }, durationMs);
    timer.unref?.();
    timers.add(timer);
  }

  function destroy() {
    for (const timer of timers) clearTimeout(timer);
    timers.clear();
    if (region) region.replaceChildren();
  }

  return { show, destroy };
}
