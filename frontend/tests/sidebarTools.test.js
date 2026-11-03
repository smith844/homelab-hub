import test from 'node:test';
import assert from 'node:assert/strict';

import {
  TOOLS_STORAGE_KEY,
  isToolsRoute,
  loadToolsOpen,
  saveToolsOpen,
  toolsOpenForRoute,
} from '../src/lib/sidebarTools.js';

class FakeStorage {
  constructor() {
    this.values = new Map();
    this.failGet = false;
    this.failSet = false;
  }
  getItem(key) {
    if (this.failGet) throw new Error('storage unavailable');
    return this.values.has(key) ? this.values.get(key) : null;
  }
  setItem(key, value) {
    if (this.failSet) throw new Error('quota exceeded');
    this.values.set(key, value);
  }
}

test('tools default to expanded when no preference is stored', () => {
  const storage = new FakeStorage();
  assert.equal(loadToolsOpen(storage), true);
  assert.equal(toolsOpenForRoute('/', storage), true);
});

test('expanded and collapsed preferences round-trip', () => {
  const storage = new FakeStorage();
  assert.equal(saveToolsOpen(false, storage), true);
  assert.equal(storage.getItem(TOOLS_STORAGE_KEY), 'false');
  assert.equal(loadToolsOpen(storage), false);
  assert.equal(saveToolsOpen(true, storage), true);
  assert.equal(storage.getItem(TOOLS_STORAGE_KEY), 'true');
  assert.equal(loadToolsOpen(storage), true);
});

test('tools routes expand automatically even when collapsed', () => {
  assert.equal(toolsOpenForRoute('/network-discovery', new FakeStorage()), true);
  assert.equal(toolsOpenForRoute('/reconciliation', new FakeStorage()), true);
  const storage = new FakeStorage();
  saveToolsOpen(false, storage);
  assert.equal(loadToolsOpen(storage), false);
  assert.equal(toolsOpenForRoute('/network-discovery', storage), true);
  assert.equal(toolsOpenForRoute('/reconciliation', storage), true);
  assert.equal(toolsOpenForRoute('/settings', storage), false);
});

test('only exact tools routes and their subpaths are recognised', () => {
  for (const path of ['/network-discovery', '/reconciliation', '/reconciliation/host-1']) {
    assert.equal(isToolsRoute(path), true, path);
  }
  for (const path of ['/', '/inventory/reconciliation', '/network-discovery-archive', null]) {
    assert.equal(isToolsRoute(path), false, String(path));
  }
});

test('storage failures fall back safely', () => {
  const storage = new FakeStorage();
  storage.failGet = true;
  storage.failSet = true;
  assert.equal(loadToolsOpen(storage), true);
  assert.equal(saveToolsOpen(false, storage), false);
  assert.equal(loadToolsOpen(null), true);
  assert.equal(saveToolsOpen(false, null), false);
});
