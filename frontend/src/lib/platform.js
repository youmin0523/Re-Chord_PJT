/**
 * Platform shim — prefer native (Capacitor) APIs when running on iOS or
 * Android, fall back to web APIs otherwise. Components never check the
 * platform directly; they call helpers from this module.
 */

const _w = typeof window !== "undefined" ? window : {};
const _capacitor = _w?.Capacitor;


export function isNative() {
  return !!_capacitor?.isNativePlatform?.();
}

export function platformName() {
  if (!_capacitor) return "web";
  try { return _capacitor.getPlatform?.() ?? "web"; } catch { return "web"; }
}


/**
 * Download a blob (or remote URL) using the best available API.
 *
 *   web        → anchor click + revokeObjectURL
 *   native     → @capacitor/filesystem write to Documents/Re:Chord/
 *
 * Returns the destination string (URL or filesystem path) for the caller
 * to display in a toast.
 */
export async function saveFile(payload, suggestedName) {
  const { blob, dataUrl } = await _normalisePayload(payload);
  if (isNative()) {
    try {
      const { Filesystem, Directory } = await import("@capacitor/filesystem");
      const base64 = dataUrl.split(",")[1];
      const folder = "Re:Chord";
      await Filesystem.mkdir({
        path: folder, directory: Directory.Documents, recursive: true,
      }).catch(() => { /* dir exists */ });
      const dest = `${folder}/${suggestedName}`;
      await Filesystem.writeFile({
        path: dest, data: base64, directory: Directory.Documents,
      });
      return { kind: "native-fs", path: dest };
    } catch (e) {
      console.warn("native save failed, falling back to web", e);
    }
  }
  // Web fallback.
  const url = blob ? URL.createObjectURL(blob) : dataUrl;
  const a = document.createElement("a");
  a.href = url;
  a.download = suggestedName;
  a.click();
  if (blob) setTimeout(() => URL.revokeObjectURL(url), 1000);
  return { kind: "web", url };
}


/**
 * Native share when available, fall back to navigator.share or to a
 * copy-to-clipboard prompt.
 */
export async function share(title, text, url) {
  if (isNative()) {
    try {
      const { Share } = await import("@capacitor/share");
      await Share.share({ title, text, url, dialogTitle: title });
      return { kind: "native" };
    } catch (e) {
      console.warn("native share failed, fall back", e);
    }
  }
  if (navigator.share) {
    try {
      await navigator.share({ title, text, url });
      return { kind: "web-share-api" };
    } catch { /* user-cancelled */ }
  }
  try {
    await navigator.clipboard.writeText(url || text);
    return { kind: "clipboard" };
  } catch {
    return { kind: "failed" };
  }
}


/**
 * Light haptic feedback on supported platforms — soft pulse for button
 * presses, error pattern for failed validation. No-op on web.
 */
export async function haptic(kind = "light") {
  if (!isNative()) return;
  try {
    const { Haptics, ImpactStyle, NotificationType } = await import("@capacitor/haptics");
    if (kind === "light") return Haptics.impact({ style: ImpactStyle.Light });
    if (kind === "medium") return Haptics.impact({ style: ImpactStyle.Medium });
    if (kind === "heavy") return Haptics.impact({ style: ImpactStyle.Heavy });
    if (kind === "error") return Haptics.notification({ type: NotificationType.Error });
    if (kind === "success") return Haptics.notification({ type: NotificationType.Success });
  } catch { /* plugin not installed */ }
}


// ── private ────────────────────────────────────────────────────────────────

async function _normalisePayload(payload) {
  if (payload instanceof Blob) {
    return { blob: payload, dataUrl: await _blobToDataUrl(payload) };
  }
  if (typeof payload === "string") {
    if (payload.startsWith("data:")) return { blob: null, dataUrl: payload };
    // Treat as URL — fetch first.
    const r = await fetch(payload);
    const b = await r.blob();
    return { blob: b, dataUrl: await _blobToDataUrl(b) };
  }
  throw new Error("saveFile: payload must be Blob, data: URL, or http(s) URL");
}

function _blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result);
    fr.onerror = reject;
    fr.readAsDataURL(blob);
  });
}
