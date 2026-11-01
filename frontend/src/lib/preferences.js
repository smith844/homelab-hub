import { writable } from "svelte/store";
export function readPreference(key, fallback) {
  try { const value = localStorage.getItem(key); return value === null ? fallback : JSON.parse(value); }
  catch { return fallback; }
}
export function savePreference(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; }
}
export const siteName = writable(readPreference("hlh.siteName", "Home Lab Hub"));
export const theme = writable(readPreference("hlh.theme", "light"));
siteName.subscribe(value => savePreference("hlh.siteName", value));
theme.subscribe(value => {
  savePreference("hlh.theme", value);
  document.documentElement.dataset.theme = value;
});
