/**
 * NexusReach Pro — Script de Preload Seguro para Ventana Principal (mainWindow)
 * FASE 2 / Tarea 1: Puente IPC seguro con contextIsolation activo
 * 
 * Expone únicamente las funciones necesarias hacia el contexto de React (window.nexusDesktop)
 * sin filtrar el objeto ipcRenderer completo ni APIs internas de Node.js.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('nexusDesktop', {
  isElectron: true,

  /**
   * Obtiene la URL base configurada para el backend centralizado FastAPI.
   * @returns {Promise<string>} ej: "https://api.nexusreach.pro" o "http://127.0.0.1:8000"
   */
  getApiBaseUrl: () => ipcRenderer.invoke('nexus:get-api-url'),

  /**
   * Notifica a Electron que el usuario inició sesión en React.
   * Transfiere el token de sesión y tenantId de forma directa y segura al worker local.
   * @param {{ sessionToken: string, tenantId?: string, userEmail?: string }} sessionData
   * @returns {Promise<{ ok: boolean }>}
   */
  setAuthSession: (sessionData) => ipcRenderer.invoke('nexus:set-auth-session', sessionData),

  /**
   * Notifica a Electron que el usuario cerró sesión en React.
   * Invalida inmediatamente el token del worker y detiene cualquier ciclo pendiente.
   * @returns {Promise<{ ok: boolean }>}
   */
  clearAuthSession: () => ipcRenderer.invoke('nexus:clear-auth-session'),

  /**
   * Consulta el estado de autenticación actual del worker local (sin exponer el token en claro).
   * @returns {Promise<{ authenticated: boolean, tenantId: string|null, deviceId: string|null }>}
   */
  getAuthSession: () => ipcRenderer.invoke('nexus:get-auth-session'),

  /**
   * Obtiene el estado operativo detallado del worker local (fase, conteo, pausas antiban).
   * @returns {Promise<object>}
   */
  getWorkerStatus: () => ipcRenderer.invoke('nexus:get-worker-status'),

  /**
   * Inicia el bucle de automatización del worker local.
   * @param {object} opts
   * @returns {Promise<object>}
   */
  startWorker: (opts) => ipcRenderer.invoke('nexus:start-worker', opts),

  /**
   * Pausa o detiene el bucle de automatización del worker local.
   * @returns {Promise<object>}
   */
  stopWorker: () => ipcRenderer.invoke('nexus:stop-worker'),

  /**
   * Suscribe a la interfaz de React a eventos de cambio de estado del worker en tiempo real.
   * @param {(status: object) => void} callback
   * @returns {() => void} Función de limpieza (unsubscribe)
   */
  onWorkerStatusUpdate: (callback) => {
    if (typeof callback !== 'function') return () => {};
    const listener = (_event, status) => {
      try {
        callback(status);
      } catch (err) {
        console.error('[nexusDesktop] Error en callback de status de worker:', err);
      }
    };
    ipcRenderer.on('nexus:worker-status-changed', listener);
    return () => {
      ipcRenderer.removeListener('nexus:worker-status-changed', listener);
    };
  }
});
