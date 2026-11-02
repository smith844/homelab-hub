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

// Cytoscape uses the SVG Image's intrinsic dimensions as a drawImage source
// rectangle. Chromium can crop a viewBox-only SVG in that overload. Explicit
// image dimensions avoid the mismatch without rasterising or altering its art,
// viewBox, aspect ratio, animation or internal clipping paths.
export async function prepareGroupIcon(source) {
  const response = await fetch(source);
  if (!response.ok) throw new Error('Group icon could not be loaded');
  if (!response.headers.get('content-type')?.includes('image/svg+xml')) return source;
  const svg = new DOMParser().parseFromString(await response.text(), 'image/svg+xml');
  const root = svg.documentElement;
  if (root.localName !== 'svg' || svg.querySelector('parsererror')) throw new Error('Invalid SVG icon');
  if (!root.hasAttribute('viewBox')) return source; // Preserve absolute SVG coordinates.
  root.setAttribute('width', '96');
  root.setAttribute('height', '96');
  // This remains an isolated image resource, never injected into the page DOM.
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(new XMLSerializer().serializeToString(root))}`;
}
