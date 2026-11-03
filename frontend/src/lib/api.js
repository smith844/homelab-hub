const BASE = "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    const error = new Error(err.error || res.statusText);
    error.status = res.status;
    throw error;
  }
  return res.json();
}

export function get(path, options = {}) {
  return request(path, options);
}

export function post(path, data, options = {}) {
  return request(path, { ...options, method: "POST", body: JSON.stringify(data) });
}

export function put(path, data, options = {}) {
  return request(path, { ...options, method: "PUT", body: JSON.stringify(data) });
}

export function patch(path, data, options = {}) {
  return request(path, { ...options, method: "PATCH", body: JSON.stringify(data) });
}

export function del(path, data, options = {}) {
  const init = { ...options, method: "DELETE" };
  if (data !== undefined) init.body = JSON.stringify(data);
  return request(path, init);
}
