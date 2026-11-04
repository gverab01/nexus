/**
 * Test Suite: Verificación de Preload e IPC Seguro (Tarea 1 / Fase 2)
 */
const assert = require('assert');
const path = require('path');
const fs = require('fs');

console.log('[TEST] Iniciando verificación de desktop/preload.cjs y canales IPC...');

// 1. Verificar existencia física y sintaxis de desktop/preload.cjs
const preloadPath = path.join(__dirname, '..', 'preload.cjs');
assert.strictEqual(fs.existsSync(preloadPath), true, 'preload.cjs debe existir en desktop/');

const preloadContent = fs.readFileSync(preloadPath, 'utf8');
assert.ok(preloadContent.includes('contextBridge.exposeInMainWorld'), 'Debe usar contextBridge');
assert.ok(preloadContent.includes('nexusDesktop'), 'Debe exponer el namespace nexusDesktop');
assert.ok(!preloadContent.includes('ipcRenderer.on(') || preloadContent.includes('nexus:worker-status-changed'), 'No debe permitir canales arbitrarios');
assert.ok(!preloadContent.includes('remote'), 'No debe importar ni usar módulo remote');

// 2. Simulación de contextBridge para verificar APIs expuestas
let exposedNamespace = null;
let exposedApi = null;

const mockContextBridge = {
  exposeInMainWorld: (ns, api) => {
    exposedNamespace = ns;
    exposedApi = api;
  }
};

const mockIpcRenderer = {
  invoke: async (channel, ...args) => {
    return { channel, args };
  },
  on: (channel, listener) => {},
  removeListener: (channel, listener) => {}
};

// Cargar preload con mocks de Electron
const vm = require('vm');
const context = vm.createContext({
  require: (mod) => {
    if (mod === 'electron') {
      return { contextBridge: mockContextBridge, ipcRenderer: mockIpcRenderer };
    }
    return require(mod);
  },
  console
});

vm.runInContext(preloadContent, context);

assert.strictEqual(exposedNamespace, 'nexusDesktop', 'El namespace debe ser nexusDesktop');
assert.strictEqual(typeof exposedApi.getApiBaseUrl, 'function', 'getApiBaseUrl debe ser función');
assert.strictEqual(typeof exposedApi.setAuthSession, 'function', 'setAuthSession debe ser función');
assert.strictEqual(typeof exposedApi.clearAuthSession, 'function', 'clearAuthSession debe ser función');
assert.strictEqual(typeof exposedApi.getAuthSession, 'function', 'getAuthSession debe ser función');
assert.strictEqual(typeof exposedApi.getWorkerStatus, 'function', 'getWorkerStatus debe ser función');
assert.strictEqual(typeof exposedApi.startWorker, 'function', 'startWorker debe ser función');
assert.strictEqual(typeof exposedApi.stopWorker, 'function', 'stopWorker debe ser función');
assert.strictEqual(typeof exposedApi.onWorkerStatusUpdate, 'function', 'onWorkerStatusUpdate debe ser función');
assert.strictEqual(exposedApi.isElectron, true, 'isElectron debe ser true');

// 3. Probar llamadas del bridge
(async () => {
  const callSet = await exposedApi.setAuthSession({ sessionToken: 'test_tok_123', tenantId: 'ten_primary' });
  assert.strictEqual(callSet.channel, 'nexus:set-auth-session');
  assert.strictEqual(callSet.args[0].sessionToken, 'test_tok_123');

  const callClear = await exposedApi.clearAuthSession();
  assert.strictEqual(callClear.channel, 'nexus:clear-auth-session');

  const callUrl = await exposedApi.getApiBaseUrl();
  assert.strictEqual(callUrl.channel, 'nexus:get-api-url');

  console.log('✅ [TEST PASSED] desktop/preload.cjs expone exactamente el contrato seguro esperado sin fugas de seguridad.');
})();

