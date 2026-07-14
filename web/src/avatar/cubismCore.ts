/**
 * Loader for the Live2D Cubism Core script (`live2dcubismcore.min.js`).
 *
 * LICENSING (important): Cubism Core is proprietary — distributed under the
 * Live2D Proprietary Software License Agreement
 * (https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html).
 * We therefore do NOT vendor or bundle it: it is loaded at runtime from
 * Live2D's official CDN, which Live2D provides for exactly this use. Set
 * `VITE_CUBISM_CORE_URL` to point elsewhere (e.g. a self-hosted copy
 * obtained under the same agreement) if the CDN is unreachable in your
 * deployment.
 */

export const CUBISM_CORE_URL: string =
  import.meta.env.VITE_CUBISM_CORE_URL ??
  "https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js";

declare global {
  interface Window {
    Live2DCubismCore?: unknown;
  }
}

let pending: Promise<void> | null = null;

/** Idempotently load the Cubism Core script; rejects on CDN failure/timeout. */
export function loadCubismCore(timeoutMs = 15000): Promise<void> {
  if (window.Live2DCubismCore) return Promise.resolve();
  pending ??= new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    const timer = window.setTimeout(() => {
      pending = null;
      script.remove();
      reject(new Error(`Timed out loading Cubism Core from ${CUBISM_CORE_URL}`));
    }, timeoutMs);
    script.src = CUBISM_CORE_URL;
    script.async = true;
    script.onload = () => {
      window.clearTimeout(timer);
      if (window.Live2DCubismCore) {
        resolve();
      } else {
        pending = null;
        reject(new Error("Cubism Core script loaded but Live2DCubismCore is missing"));
      }
    };
    script.onerror = () => {
      window.clearTimeout(timer);
      pending = null;
      script.remove();
      reject(new Error(`Failed to load Cubism Core from ${CUBISM_CORE_URL}`));
    };
    document.head.append(script);
  });
  return pending;
}
