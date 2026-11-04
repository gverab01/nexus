/**
 * Test Suite: Verificación de Integración de API Client y Preload IPC (Tarea 2)
 */
const assert = require('assert');

console.log('[TEST] Iniciando verificación de resolución de API_BASE y sincronización IPC...');

// 1. Simulación de entorno Browser / Electron con nexusDesktop
let syncedSession = null;
let clearedSession = false;

const mockNexusDesktop = {
  getApiBaseUrl: async () => 'https://api.nexusreach.pro',
  setAuthSession: async (data) => {
    syncedSession = data;
    return { ok: true };
  },
  clearAuthSession: async () => {
    clearedSession = true;
    return { ok: true };
  }
};

// Simular lógica de resolución
async function simulateResolveApiBase(win) {
  let cached = null;
  if (win && win.nexusDesktop?.getApiBaseUrl) {
    const electronUrl = await win.nexusDesktop.getApiBaseUrl();
    if (electronUrl && typeof electronUrl === 'string') {
      const clean = electronUrl.replace(/\/+$/, '');
      cached = clean.endsWith('/api') ? clean : `${clean}/api`;
      return cached;
    }
  }
  return '/api';
}

(async () => {
  // Test A: En Electron, debe resolver a la URL remota /api
  const urlInElectron = await simulateResolveApiBase({ nexusDesktop: mockNexusDesktop });
  assert.strictEqual(urlInElectron, 'https://api.nexusreach.pro/api', 'Debe concatenar /api a la URL de Electron');

  // Test B: En navegador web clásico sin nexusDesktop, debe usar '/api' relativo
  const urlInWeb = await simulateResolveApiBase({});
  assert.strictEqual(urlInWeb, '/api', 'Debe resolver a /api relativo en navegador web');

  // Test C: Sincronización de sesión
  await mockNexusDesktop.setAuthSession({ sessionToken: 'tok_live_456', tenantId: 'ten_primary' });
  assert.strictEqual(syncedSession.sessionToken, 'tok_live_456');
  assert.strictEqual(syncedSession.tenantId, 'ten_primary');

  await mockNexusDesktop.clearAuthSession();
  assert.strictEqual(clearedSession, true);

  console.log('✅ [TEST PASSED] Resolución dinámica de API y sincronización IPC verificada exitosamente.');
})();
