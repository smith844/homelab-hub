import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const theme = readFileSync(new URL('../src/theme.css', import.meta.url), 'utf8');
const mapPage = readFileSync(new URL('../src/pages/MapPage.svelte', import.meta.url), 'utf8');

test('theme exposes semantic control tokens for light and dark modes', () => {
  for (const token of [
    '--hlh-control-fg',
    '--hlh-control-muted',
    '--hlh-control-border',
    '--hlh-control-hover-bg',
    '--hlh-control-active-fg',
    '--hlh-control-active-bg',
    '--hlh-control-focus',
  ]) {
    assert.ok(theme.includes(`${token}:`), `missing theme token ${token}`);
  }
  assert.match(theme, /--hlh-control-fg:var\(--pico-contrast\)/);
});

test('map view selector uses theme control tokens instead of the button-local pico colour', () => {
  const base = mapPage.match(/\.view-toggle button\{([^}]*)\}/);
  assert.ok(base, 'view-toggle button rule not found');
  assert.match(base[1], /color:var\(--hlh-control-fg\)/);
  assert.doesNotMatch(base[1], /var\(--pico-color\)/);

  const active = mapPage.match(/\.view-toggle button\.active\{([^}]*)\}/);
  assert.ok(active, 'active state rule not found');
  assert.match(active[1], /color:var\(--hlh-control-active-fg\)/);

  assert.match(mapPage, /\.view-toggle button:hover:not\(\.active\)/);
  assert.match(mapPage, /\.view-toggle button:focus-visible/);
  assert.match(mapPage, /\.view-toggle button:disabled/);
});
