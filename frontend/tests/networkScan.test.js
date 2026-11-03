import test from 'node:test';
import assert from 'node:assert/strict';

import {
  SCAN_STORAGE_KEY,
  clearScanState,
  isScanActive,
  isScanTerminal,
  loadScanState,
  saveScanState,
} from '../src/lib/networkScan.js';

class FakeStorage {
  constructor() {
    this.values = new Map();
    this.failSet = false;
  }
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null; }
  setItem(key, value) {
    if (this.failSet) throw new Error('quota exceeded');
    this.values.set(key, value);
  }
  removeItem(key) { this.values.delete(key); }
}

const scan = {
  scan_id: '12345678-1234-1234-1234-123456789abc',
  target: '192.168.1.0/24',
  type: 'portscan',
  status: 'running',
  progress: 42,
  hosts: [{ip: '192.168.1.16'}],
  results: [{ip: '192.168.1.16', port: 80}],
  warnings: [],
};

test('saved scans preserve id, target and status across a storage reload', () => {
  const storage = new FakeStorage();
  assert.equal(saveScanState(scan, storage), true);
  assert.ok(storage.getItem(SCAN_STORAGE_KEY));
  const restored = loadScanState(storage);
  assert.equal(restored.scan_id, scan.scan_id);
  assert.equal(restored.target, scan.target);
  assert.equal(restored.status, 'running');
  assert.equal(restored.progress, 42);
  assert.deepEqual(restored.results, scan.results);
});

test('completed and partial scans are terminal and not active', () => {
  assert.equal(isScanActive(scan), true);
  assert.equal(isScanTerminal(scan), false);
  for (const status of ['completed', 'partial', 'failed']) {
    const value = {...scan, status};
    assert.equal(isScanActive(value), false);
    assert.equal(isScanTerminal(value), true);
  }
});

test('oversized scans fall back to metadata while retaining the scan id', () => {
  const storage = new FakeStorage();
  storage.failSet = true;
  storage.setItem = function (key, value) {
    if (this.failSet) {
      this.failSet = false;
      throw new Error('quota exceeded');
    }
    return FakeStorage.prototype.setItem.call(this, key, value);
  };
  assert.equal(saveScanState(scan, storage), true);
  const restored = loadScanState(storage);
  assert.equal(restored.scan_id, scan.scan_id);
  assert.equal(restored.target, scan.target);
  assert.equal(restored.cached_truncated, true);
  assert.deepEqual(restored.results, []);
});

test('malformed or missing storage values are ignored and clear removes state', () => {
  const storage = new FakeStorage();
  assert.equal(loadScanState(storage), null);
  storage.setItem(SCAN_STORAGE_KEY, '{invalid');
  assert.equal(loadScanState(storage), null);
  storage.setItem(SCAN_STORAGE_KEY, JSON.stringify({version: 1, scan: {status: 'running'}}));
  assert.equal(loadScanState(storage), null);
  saveScanState(scan, storage);
  clearScanState(storage);
  assert.equal(loadScanState(storage), null);
});
