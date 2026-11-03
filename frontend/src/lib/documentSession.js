import { put } from './api.js';
import { createDocumentSaves } from './documentSaves.js';

// Keep failed drafts available when moving between SPA pages in this tab.
const listeners = new Set();
export const documentSaves = createDocumentSaves(
  (id, draft) => put(`/docs/${id}`, draft),
  () => listeners.forEach(listener => listener()),
);
export function subscribeDocumentSaves(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', event => {
    if (documentSaves.unsaved().length) { event.preventDefault(); event.returnValue = ''; }
  });
}
