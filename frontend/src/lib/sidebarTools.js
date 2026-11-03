/** Sidebar Tools group persistence and route helpers. */
export const TOOLS_STORAGE_KEY = 'hlh.sidebarToolsOpen';
export const TOOLS_ROUTES = ['/network-discovery', '/reconciliation'];

function defaultStorage() {
  try {
    return globalThis.localStorage || null;
  } catch (e) {
    return null;
  }
}

export function isToolsRoute(path) {
  if (typeof path !== 'string') return false;
  return TOOLS_ROUTES.some(route => path === route || path.startsWith(`${route}/`));
}

export function loadToolsOpen(storage = defaultStorage()) {
  try {
    return storage?.getItem(TOOLS_STORAGE_KEY) !== 'false';
  } catch (e) {
    return true;
  }
}

export function saveToolsOpen(open, storage = defaultStorage()) {
  if (!storage) return false;
  try {
    storage.setItem(TOOLS_STORAGE_KEY, open ? 'true' : 'false');
    return true;
  } catch (e) {
    return false;
  }
}

/** Tools are always expanded while one of their pages is active. */
export function toolsOpenForRoute(path, storage = defaultStorage()) {
  return isToolsRoute(path) || loadToolsOpen(storage);
}
