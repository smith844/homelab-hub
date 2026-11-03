// One queue per document. Capture drafts at input time; never read the current
// selection from a delayed callback. Serial writes prevent older saves winning.
export function createDocumentSaves(write, notify = () => {}, delay = 800) {
  const entries = new Map();
  function entry(id) {
    if (!entries.has(id)) entries.set(id, { draft: null, version: 0, saved: 0, state: 'saved', timer: null, running: null });
    return entries.get(id);
  }
  function update(id, draft) {
    const e = entry(id);
    e.draft = { title: draft.title, content: draft.content };
    e.version++;
    e.state = 'pending';
    clearTimeout(e.timer);
    e.timer = setTimeout(() => flush(id), delay);
    notify();
  }
  async function flush(id) {
    const e = entry(id);
    clearTimeout(e.timer);
    if (e.running) return e.running;
    if (e.saved === e.version) return true;
    e.running = (async () => {
      while (e.saved < e.version) {
        const version = e.version, draft = { ...e.draft };
        e.state = 'saving'; notify();
        try { await write(id, draft); }
        catch { e.state = 'error'; notify(); return false; }
        e.saved = version;
      }
      e.state = 'saved'; notify(); return true;
    })();
    try { return await e.running; } finally { e.running = null; }
  }
  return {
    update, flush,
    draft: id => entries.get(id)?.draft,
    state: id => entries.get(id)?.state || 'saved',
    unsaved: () => [...entries].filter(([, e]) => e.saved < e.version).map(([id]) => id),
    forget(id) { clearTimeout(entries.get(id)?.timer); entries.delete(id); },
    flushAll: () => Promise.all([...entries.keys()].map(flush)),
  };
}
