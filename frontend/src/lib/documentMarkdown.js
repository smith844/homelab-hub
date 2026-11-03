import { getProcessor } from 'bytemd';
import gfm from '@bytemd/plugin-gfm';

const processor = getProcessor({ plugins: [gfm()] });
// ByteMD's existing pipeline parses Markdown and sanitises rendered HTML.
export function renderDocumentMarkdown(content = '') {
  return String(processor.processSync(content));
}
