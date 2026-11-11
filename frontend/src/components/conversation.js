/**
 * Conversation panel: welcome view, starter prompts, verified answer messages,
 * evidence cards, copy actions, and transcript export buttons.
 */

import { STARTER_PROMPTS } from '../config/constants.js';
import { createEl, getById } from '../utils/dom.js';

export function createConversationView(
  doc,
  { onSelectCitation, onStarterPrompt, onCopyText, onClearChat, onExportChat } = {},
) {
  const conversationEl = getById(doc, 'conversation');
  const welcomeEl = getById(doc, 'welcome');
  const starterEl = getById(doc, 'starter-prompts');
  const clearBtn = getById(doc, 'clear-chat');
  const exportBtn = getById(doc, 'export-chat');

  let pendingTimer = null;

  function renderStarterPrompts(visible) {
    if (!starterEl) return;
    starterEl.replaceChildren();
    starterEl.hidden = !visible;
    if (!visible) return;

    for (const promptText of STARTER_PROMPTS) {
      const chip = createEl(doc, 'button', {
        className: 'starter-chip',
        type: 'button',
        text: promptText,
      });
      chip.addEventListener('click', () => onStarterPrompt?.(promptText));
      starterEl.append(chip);
    }
  }

  function updateToolbar(hasMessages) {
    if (clearBtn) clearBtn.hidden = !hasMessages;
    if (exportBtn) exportBtn.hidden = !hasMessages;
  }

  function stopPendingTimer() {
    if (pendingTimer) {
      clearInterval(pendingTimer);
      pendingTimer = null;
    }
  }

  function scrollToBottom() {
    if (conversationEl) {
      conversationEl.scrollTop = conversationEl.scrollHeight;
    }
  }

  function reset({ hasSession = false } = {}) {
    stopPendingTimer();
    if (welcomeEl) welcomeEl.hidden = false;
    if (conversationEl && welcomeEl) {
      conversationEl.replaceChildren(welcomeEl);
    }
    renderStarterPrompts(hasSession);
    updateToolbar(false);
  }

  function appendUserMessage(text) {
    if (welcomeEl) welcomeEl.hidden = true;
    renderStarterPrompts(false);

    const article = createEl(doc, 'article', { className: 'message user' });
    const header = createEl(doc, 'div', {
      className: 'message-header',
      children: [createEl(doc, 'div', { className: 'message-label', text: 'YOU' })],
    });
    const body = createEl(doc, 'div', { className: 'message-body', text });
    article.append(header, body);
    conversationEl?.append(article);
    updateToolbar(true);
    scrollToBottom();
    return article;
  }

  function appendPendingAssistant() {
    if (welcomeEl) welcomeEl.hidden = true;
    const article = createEl(doc, 'article', { className: 'message assistant' });
    const header = createEl(doc, 'div', {
      className: 'message-header',
      children: [createEl(doc, 'div', { className: 'message-label', text: 'DOCULENS' })],
    });
    const baseText = 'Finding passages and checking the evidence…';
    const body = createEl(doc, 'div', {
      className: 'message-body pending',
      text: baseText,
    });
    article.append(header, body);
    conversationEl?.append(article);
    scrollToBottom();

    const startedAt = Date.now();
    stopPendingTimer();
    pendingTimer = setInterval(() => {
      const elapsedSec = Math.floor((Date.now() - startedAt) / 1000);
      if (elapsedSec >= 1) {
        body.textContent = `${baseText} (${elapsedSec}s)`;
      }
    }, 1000);
    pendingTimer.unref?.();

    return {
      resolve(data) {
        stopPendingTimer();
        body.classList.remove('pending');
        body.textContent = data.answer;

        const isAnswered = data.status === 'answered';
        const badge = createEl(doc, 'span', {
          className: `answer-badge ${isAnswered ? '' : 'abstain'}`.trim(),
          text: isAnswered ? '✓ Source excerpts verified' : 'Insufficient PDF evidence',
        });

        const copyAnswerBtn = createEl(doc, 'button', {
          className: 'copy-inline',
          type: 'button',
          text: 'Copy answer',
        });
        copyAnswerBtn.addEventListener('click', () => onCopyText?.(data.answer));

        const meta = createEl(doc, 'div', {
          className: 'answer-meta',
          children: [badge, copyAnswerBtn],
        });
        body.before(meta);

        if (data.citations?.length) {
          const grid = createEl(doc, 'div', { className: 'evidence-grid' });
          for (const citation of data.citations) {
            const card = createEl(doc, 'button', {
              className: 'evidence-card',
              type: 'button',
              children: [
                createEl(doc, 'span', {
                  className: 'page',
                  text: `PDF PAGE ${citation.page_number}`,
                }),
                createEl(doc, 'span', {
                  className: 'quote',
                  text: citation.excerpt,
                }),
                createEl(doc, 'span', {
                  className: 'view',
                  text: 'Read source page ↗',
                }),
              ],
            });
            card.addEventListener('click', () => onSelectCitation?.(citation));
            grid.append(card);
          }
          article.append(grid);
        }
        scrollToBottom();
      },
      reject(errorMessage) {
        stopPendingTimer();
        body.classList.remove('pending');
        body.textContent = errorMessage;
        scrollToBottom();
      },
    };
  }

  if (clearBtn) clearBtn.addEventListener('click', () => onClearChat?.());
  if (exportBtn) exportBtn.addEventListener('click', () => onExportChat?.());

  return {
    reset,
    renderStarterPrompts,
    appendUserMessage,
    appendPendingAssistant,
    stopPendingTimer,
    destroy: stopPendingTimer,
  };
}
