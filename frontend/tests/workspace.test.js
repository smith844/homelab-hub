import test from 'node:test';
import assert from 'node:assert/strict';
import { isWorkspaceEscape } from '../src/lib/workspace.js';

test('Escape closes only the expanded workspace', () => {
  assert.equal(isWorkspaceEscape({ key: 'Escape' }), true);
  assert.equal(isWorkspaceEscape({ key: 'Enter' }), false);
  assert.equal(isWorkspaceEscape({ key: 'Esc' }), false);
  assert.equal(isWorkspaceEscape(null), false);
});
