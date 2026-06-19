/**
 * Minimal framework-agnostic toast store.
 *
 * Any module — including non-React ones like `lib/api.js` — can fire a toast
 * via `toast.error(msg)`. The <Toaster> component subscribes and renders them.
 * Kept dependency-free so it can be imported anywhere.
 */

let _id = 0;
const _toasts = [];
const _listeners = new Set();

function _emit() {
  const snapshot = [..._toasts];
  _listeners.forEach((fn) => {
    try { fn(snapshot); } catch { /* a bad listener must not break the bus */ }
  });
}

export function dismiss(id) {
  const i = _toasts.findIndex((t) => t.id === id);
  if (i >= 0) {
    _toasts.splice(i, 1);
    _emit();
  }
}

function push(type, message, ttl = 6000) {
  if (!message) return null;
  const id = ++_id;
  _toasts.push({ id, type, message });
  _emit();
  if (ttl > 0) setTimeout(() => dismiss(id), ttl);
  return id;
}

/** Subscribe to toast changes. Calls `fn` immediately with the current list.
 *  Returns an unsubscribe function. */
export function subscribe(fn) {
  _listeners.add(fn);
  fn([..._toasts]);
  return () => _listeners.delete(fn);
}

export const toast = {
  error: (message, ttl) => push("error", message, ttl),
  info: (message, ttl) => push("info", message, ttl),
  success: (message, ttl) => push("success", message, ttl),
};
