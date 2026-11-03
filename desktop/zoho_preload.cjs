// Preload para la ventana de Zoho CRM en NexusReach Pro
// Desactiva el Service Worker experimental 'MetaCachingSW.js' de Zoho que genera errores 500 sintéticos en Chromium embebido.

try {
  if (typeof navigator !== 'undefined' && navigator.serviceWorker) {
    navigator.serviceWorker.register = function () {
      return Promise.reject(new Error('ServiceWorker deshabilitado para estabilidad de Zoho CRM'));
    };
  }
} catch (e) {}

try {
  let metaCacheVal = false;
  Object.defineProperty(window, 'isMetaCacheEnabled', {
    get: () => metaCacheVal,
    set: () => {},
    configurable: true
  });
} catch (e) {}
