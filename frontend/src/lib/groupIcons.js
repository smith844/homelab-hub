// Never interpret icon values as HTML or arbitrary CSS/URL schemes.
export function groupIcon(value) {
  const text = typeof value === 'string' ? value.trim() : '';
  if (/^https?:\/\//i.test(text)) {
    try {
      const url = new URL(text);
      if (!url.username && !url.password) return { image: url.href, text: '' };
    } catch { /* fall back to the folder glyph */ }
  }
  if (/^data:image\/(png|gif|jpeg|webp);base64,[a-z0-9+/=]+$/i.test(text)) {
    return { image: text, text: '' };
  }
  // Keep short emoji/symbol labels; never display a rejected URL or markup.
  if (text && [...text].length <= 8 && !/[<>:/\\]/.test(text)) return { image: '', text };
  return { image: '', text: '📁' };
}
