/**
 * Test Suite: Verificación de Almacenamiento y Migración de Llaves del Dispositivo en userData (Tarea 3)
 */
const assert = require('assert');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { CryptoVerifier, resolveDefaultKeysDirectory } = require('../security/crypto_verifier.cjs');

console.log('[TEST] Iniciando verificación de almacenamiento en userData...');

// 1. Probar fallback cuando no hay Electron activo
const defaultDir = resolveDefaultKeysDirectory();
assert.ok(typeof defaultDir === 'string' && defaultDir.length > 0, 'Debe retornar una ruta válida');
assert.ok(defaultDir.includes('device_keys'), 'La ruta debe contener device_keys');

// 2. Probar con variable de entorno NEXUS_DEVICE_KEYS_DIR
const tempTestDir = path.join(os.tmpdir(), 'nexus_test_keys_' + Date.now());
process.env.NEXUS_DEVICE_KEYS_DIR = tempTestDir;

const resolvedEnvDir = resolveDefaultKeysDirectory();
assert.strictEqual(resolvedEnvDir, tempTestDir, 'Debe respetar NEXUS_DEVICE_KEYS_DIR');

const verifier = new CryptoVerifier();
assert.ok(verifier.getDeviceId().startsWith('dev_'), 'Debe generar device_id válido');
assert.ok(fs.existsSync(path.join(tempTestDir, 'device_private.pem')), 'Debe crear device_private.pem');
assert.ok(fs.existsSync(path.join(tempTestDir, 'device_public.pem')), 'Debe crear device_public.pem');
assert.ok(fs.existsSync(path.join(tempTestDir, 'device_id.txt')), 'Debe crear device_id.txt');

// 3. Probar persistencia (reabrir en el mismo directorio debe mantener el mismo device_id)
const verifier2 = new CryptoVerifier(tempTestDir);
assert.strictEqual(verifier2.getDeviceId(), verifier.getDeviceId(), 'Debe persistir el mismo device_id');

// Limpieza
delete process.env.NEXUS_DEVICE_KEYS_DIR;
try {
  fs.rmSync(tempTestDir, { recursive: true, force: true });
} catch (e) {}

console.log('✅ [TEST PASSED] Gestión de almacenamiento seguro y resolución de llaves de dispositivo verificada exitosamente.');
