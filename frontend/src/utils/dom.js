/**
 * Safe DOM helpers, formatting utilities, clipboard, and transcript export.
 * All dynamic text uses textContent to avoid XSS/HTML injection.
 */

export function getById(doc, id) {
  return doc.getElementById(id);
}

export function createEl(doc, tag, options = {}) {
  const node = doc.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = options.text;
  if (options.type) node.type = options.type;
  if (options.attributes) {
    for (const [key, value] of Object.entries(options.attributes)) {
      node.setAttribute(key, String(value));
    }
  }
  if (options.children) {
    node.append(...options.children);
  }
  return node;
}

export function formatMiB(bytes) {
  return `${Math.max(1, Math.floor(bytes / (1024 * 1024)))} MiB`;
}

export function formatCountdown(totalSeconds) {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const mins = Math.floor(safe / 60);
  const secs = safe % 60;
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

export async function copyToClipboard(text, win) {
  if (!text) return false;
  try {
    if (win?.navigator?.clipboard?.writeText) {
      await win.navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    return false;
  }
  return false;
}

export function buildMarkdownTranscript(session, messages) {
  const lines = [
    `# DocuLens Transcript — ${session?.filename || 'Document'}`,
    '',
    `- Document ID: \`${session?.document_id || 'unknown'}\``,
    `- Pages: ${session?.page_count ?? '-'}`,
    `- Passages indexed: ${session?.chunk_count ?? '-'}`,
    '',
  ];
  for (const item of messages) {
    if (item.role === 'user') {
      lines.push(`## Question`, '', item.text, '');
    } else {
      const label =
        item.status === 'answered'
          ? 'Verified PDF Excerpts'
          : item.status === 'insufficient_evidence'
            ? 'Insufficient Evidence'
            : 'Response';
      lines.push(`### ${label}`, '', item.text, '');
      if (item.citations?.length) {
        lines.push('**Citations:**', '');
        for (const citation of item.citations) {
          lines.push(`- **PDF page ${citation.page_number}:** ${citation.excerpt}`);
        }
        lines.push('');
      }
    }
  }
  return lines.join('\n');
}
