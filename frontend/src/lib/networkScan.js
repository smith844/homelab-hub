/** Session-scoped persistence for the Network Discovery scan lifecycle. */
export const SCAN_STORAGE_KEY = 'hlh.networkScan';
export const SCAN_EVENT = 'hlh:network-scan';

const TERMINAL = new Set(['completed', 'partial', 'failed']);

function defaultStorage() {
  try {
    return globalThis.sessionStorage || null;
  } catch (e) {
    return null;
  }
}

export function isScanActive(scan) {
  return Boolean(scan?.scan_id && scan?.status && !TERMINAL.has(scan.status));
}

export function isScanTerminal(scan) {
  return Boolean(scan?.status && TERMINAL.has(scan.status));
}

function notify() {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(SCAN_EVENT));
  }
}

function minimal(scan) {
  return {...scan, hosts: [], results: [], warnings: [], cached_truncated: true};
}

export function saveScanState(scan, storage = defaultStorage()) {
  if (!scan || typeof scan.scan_id !== 'string' || !scan.scan_id) return false;
  if (!storage) return false;
  const payload = {
    version: 1,
    saved_at: new Date().toISOString(),
    scan,
  };
  try {
    storage.setItem(SCAN_STORAGE_KEY, JSON.stringify(payload));
    notify();
    return true;
  } catch (e) {
    // Large scans can exceed sessionStorage; keep metadata so the page can
    // retrieve the authoritative result from the scanner after refresh.
    try {
      storage.setItem(SCAN_STORAGE_KEY, JSON.stringify({
        version: 1, saved_at: payload.saved_at, scan: minimal(scan),
      }));
      notify();
      return true;
    } catch (retryError) {
      return false;
    }
  }
}

export function loadScanState(storage = defaultStorage()) {
  if (!storage) return null;
  try {
    const value = JSON.parse(storage.getItem(SCAN_STORAGE_KEY) || 'null');
    const scan = value?.version === 1 ? value.scan : null;
    if (!scan || typeof scan.scan_id !== 'string' || !scan.scan_id) return null;
    if (typeof scan.status !== 'string') return null;
    return scan;
  } catch (e) {
    return null;
  }
}

export function clearScanState(storage = defaultStorage()) {
  if (!storage) return;
  try {
    storage.removeItem(SCAN_STORAGE_KEY);
  } catch (e) {
    // Ignore storage failures; in-memory state still clears.
  }
  notify();
}
