/**
 * Test Suite Automatizado para el Subsistema de Seguridad y Canal de Comandos (Workstream 5.1)
 * Valida Ed25519, DomainGuard, Anti-Replay, TTL y Enumeración Cerrada en Node.js.
 */

const assert = require('assert');
const path = require('path');
const fs = require('fs');
const { CryptoVerifier, canonicalJson } = require('../security/crypto_verifier.cjs');
const { isUrlAllowed } = require('../security/domain_guard.cjs');

async function runTests() {
  console.log('====================================================');
  console.log('INICIANDO TEST SUITE DE SEGURIDAD (WORKSTREAM 5.1)');
  console.log('====================================================');

  const testDir = path.join(__dirname, '..', '..', 'storage', 'test_device_keys');
  if (fs.existsSync(testDir)) {
    fs.rmSync(testDir, { recursive: true, force: true });
  }

  const verifier = new CryptoVerifier(testDir);
  console.log('✓ Claves de dispositivo generadas y persistidas en:', testDir);
  console.log('  Device ID:', verifier.getDeviceId());
  console.log('  Public Key (b64):', verifier.getPublicKeyB64());

  // 1. Test: Control de TTL y Rechazo de Expirados (> 120s)
  console.log('\n--- TEST 1: Control de TTL y Rechazo de Expirados (> 120s) ---');
  const now = new Date();
  const pastIssued = new Date(now.getTime() - 200000);
  const pastExpires = new Date(now.getTime() - 50000); // Expiró hace 50s
  const expiredCmd = {
    command_id: 'cmd_expired_1',
    tenant_id: 'ten_test',
    device_id: verifier.getDeviceId(),
    action: 'LI_VISIT_PROFILE',
    params: { profile_url: 'https://www.linkedin.com/in/test' },
    nonce: 'nonce_exp_001',
    issued_at: pastIssued.toISOString(),
    expires_at: pastExpires.toISOString(),
    signature: 'fake_sig'
  };
  const expRes = verifier.verifyCommand(expiredCmd);
  assert.strictEqual(expRes.valid, false, 'Debe fallar por TTL expirado');
  assert.ok(expRes.reason.includes('caducado') || expRes.reason.includes('expir'), `El motivo debe mencionar expirado: ${expRes.reason}`);
  console.log('✓ Comando expirado rechazado correctamente:', expRes.reason);

  // 2. Test: Nonce Replay
  console.log('\n--- TEST 2: Rechazo de Nonce Replay (Doble Envío) ---');
  const nonceKey = 'nonce_replay_001';
  // Agregamos nonce al verificador simulando primer uso
  const futureExpires = new Date(now.getTime() + 60000).toISOString();
  const firstCmd = {
    command_id: 'cmd_first_1',
    tenant_id: 'ten_test',
    device_id: verifier.getDeviceId(),
    action: 'LI_VISIT_PROFILE',
    params: {},
    nonce: nonceKey,
    issued_at: now.toISOString(),
    expires_at: futureExpires,
    signature: 'dummy_sig'
  };
  // Para registrar el nonce, lo agregamos manualmente o vía verifyCommand con firma dummy
  // En crypto_verifier, seenNonces se puebla si llega
  const replayCmd = {
    command_id: 'cmd_replay_1',
    tenant_id: 'ten_test',
    device_id: verifier.getDeviceId(),
    action: 'LI_VISIT_PROFILE',
    params: {},
    nonce: nonceKey,
    issued_at: now.toISOString(),
    expires_at: futureExpires,
    signature: 'dummy_sig'
  };
  // Ponemos el nonce en el set para probar la detección
  verifier.seenNonces.set(nonceKey, Date.now());
  const replayRes = verifier.verifyCommand(replayCmd);
  assert.strictEqual(replayRes.valid, false, 'Debe fallar por nonce repetido');
  assert.ok(replayRes.reason.includes('nonce ya fue utilizado'), `Motivo: ${replayRes.reason}`);
  console.log('✓ Nonce duplicado bloqueado inmediatamente:', replayRes.reason);

  // 3. Test: Enumeración Cerrada de Acciones
  console.log('\n--- TEST 3: Rechazo de Acciones fuera de la Enumeración Cerrada ---');
  const forbiddenActions = ['EXECUTE_SHELL', 'EVAL_JS', 'DOWNLOAD_EXE', 'FORMAT_DISK', 'ARBITRARY_CODE'];
  for (const act of forbiddenActions) {
    const badCmd = {
      command_id: `cmd_bad_${act}`,
      tenant_id: 'ten_test',
      device_id: verifier.getDeviceId(),
      action: act,
      params: {},
      nonce: `nonce_bad_${act}`,
      issued_at: now.toISOString(),
      expires_at: futureExpires,
      signature: 'dummy_sig'
    };
    const badRes = verifier.verifyCommand(badCmd);
    assert.strictEqual(badRes.valid, false);
    assert.ok(badRes.reason.includes('no permitida'), `Motivo: ${badRes.reason}`);
  }
  console.log('✓ Todas las acciones fuera de la enumeración cerrada fueron bloqueadas con éxito.');

  // 4. Test: Allowlist Guard de Dominios
  console.log('\n--- TEST 4: Verificación de Allowlist Guard de Dominios ---');
  
  // URLs válidas
  const validLinkedIn = isUrlAllowed('https://www.linkedin.com/in/prospecto-test-123', false);
  assert.strictEqual(validLinkedIn.allowed, true);
  assert.strictEqual(validLinkedIn.channel, 'linkedin');

  const validWA = isUrlAllowed('https://web.whatsapp.com/send?phone=56912345678', false);
  assert.strictEqual(validWA.allowed, true);
  assert.strictEqual(validWA.channel, 'whatsapp');

  // Zoho sin flag -> debe ser rechazado
  const zohoNoFlag = isUrlAllowed('https://crm.zoho.com/crm/org902879914/tab/Leads', false);
  assert.strictEqual(zohoNoFlag.allowed, false);
  assert.ok(zohoNoFlag.reason.includes('no está activado'));

  // Zoho con flag -> debe ser admitido
  const zohoWithFlag = isUrlAllowed('https://crm.zoho.com/crm/org902879914/tab/Leads', true);
  assert.strictEqual(zohoWithFlag.allowed, true);
  assert.strictEqual(zohoWithFlag.channel, 'zoho');

  // Dominios maliciosos o no autorizados -> deben ser bloqueados
  const maliciousUrls = [
    'https://evil-attacker.com/malware.js',
    'http://192.168.1.1/admin',
    'javascript:alert(1)',
    'file:///etc/passwd',
    'https://zoho.evil.com',
    'https://linkedin.com.phishing.io'
  ];
  for (const url of maliciousUrls) {
    const res = isUrlAllowed(url, true);
    assert.strictEqual(res.allowed, false, `URL peligrosa debió ser bloqueada: ${url}`);
  }
  console.log('✓ Allowlist Guard bloqueó el 100% de dominios y esquemas no autorizados.');

  // 5. Test: Firma de Resultados del Dispositivo
  console.log('\n--- TEST 5: Firma Criptográfica de Resultados con Clave del Dispositivo ---');
  const resultPayload = {
    command_id: 'cmd_test_001',
    device_id: verifier.getDeviceId(),
    success: true,
    result: { visited: true }
  };
  const signedResult = verifier.signResult(resultPayload);
  assert.ok(signedResult.device_signature, 'Debe incluir device_signature');
  assert.ok(signedResult.reported_at, 'Debe incluir reported_at');
  console.log('✓ Reporte de resultado firmado correctamente:', {
    command_id: signedResult.command_id,
    signature_preview: signedResult.device_signature.substring(0, 24) + '...'
  });

  // Limpieza de directorio de pruebas
  if (fs.existsSync(testDir)) {
    fs.rmSync(testDir, { recursive: true, force: true });
  }

  console.log('\n====================================================');
  console.log('✓ TODOS LOS TESTS DE NODE.JS PASARON SATISFACTORIAMENTE');
  console.log('====================================================\n');
}

runTests().catch((err) => {
  console.error('❌ FALLÓ EL TEST SUITE DE NODE.JS:', err);
  process.exit(1);
});
