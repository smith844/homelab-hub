const TOKEN_KEY = "hlh.adminToken";

export function getAdminToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || "";
  } catch (e) {
    return "";
  }
}

export function setAdminToken(token) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch (e) {
    // Storage may be unavailable; writes will fail with 401.
  }
}

export function adminHeaders() {
  const token = getAdminToken();
  return token ? { "X-Admin-Token": token } : {};
}
