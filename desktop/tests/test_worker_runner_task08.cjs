/**
 * Test Suite Automatizada TASK-08 (Node.js):
 * Verifica identidad, autenticación, tenant dinámico, verificación criptográfica Ed25519,
 * detención ante 401/403 sin bucles infinitos y confirmación del servidor en desktop/worker_runner.cjs.
 */

const assert = require('assert');
const crypto = require('crypto');
const path = require('path');
const fs = require('fs');
const os = require('os');
const workerRunner = require('../worker_runner.cjs');
const { canonicalizeJson } = require('../security/crypto_verifier.cjs');

function generateServerKeypair() {
  const { publicKey, privateKey } = crypto.generateKeyPairSync('ed25519');
  const spkiDer = publicKey.export({ type: 'spki', format: 'der' });
  const publicKeyRawB64 = spkiDer.subarray(12).toString('base64');
  return { publicKey, privateKey, publicKeyRawB64 };
}

function signServerCommand(serverPrivKey, cmdPayload) {
  const canonicalStr = canonicalizeJson(cmdPayload);
  const sig = crypto.sign(null, Buffer.from(canonicalStr, 'utf8'), serverPrivKey);
  return {
    ...cmdPayload,
    signature: sig.toString('base64')
  };
}

async function runTests() {
  console.log('==============================================================');
  console.log('INICIANDO TEST SUITE TASK-08: WORKER RUNNER AUTH & MULTI-TENANT');
  console.log('==============================================================');

  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'nexus_task08_node_'));
  const serverKeys = generateServerKeypair();

  try {
    // 0. Verificar que no exista ningún tenant hardcodeado en worker_runner.cjs
    const runnerSource = fs.readFileSync(path.join(__dirname, '..', 'worker_runner.cjs'), 'utf8');
    assert.strictEqual(runnerSource.includes('ten_superadmin'), false, 'No debe existir ten_superadmin en worker_runner.cjs');
    assert.strictEqual(runnerSource.includes('ten_default'), false, 'No debe existir ten_default en worker_runner.cjs');
    console.log('✓ 0. Verificación estática: sin tenant_id hardcodeado en desktop/worker_runner.cjs');

    // 1. Runner sin sesión no obtiene tareas ni hace polling a /api/worker/proxima-tarea
    let calls = [];
    let executedActions = [];
    workerRunner.stopWorker();
    workerRunner.clearAuthSession();
    workerRunner.configureRunner({
      keysDir: path.join(tmpDir, 'keys_1'),
      transport: async (method, url, headers, body) => {
        calls.push({ method, url, headers, body });
        return { statusCode: 401, ok: false, data: { detail: 'No autenticado' } };
      },
      actionExecutor: async (action, params) => {
        executedActions.push({ action, params });
        return { success: true, result: {} };
      }
    });

    workerRunner.startWorker(null);
    await new Promise((r) => setTimeout(r, 30));
    const st1 = workerRunner.getStatus();
    assert.strictEqual(st1.activo, false, 'Runner sin sesión debe detenerse inmediatamente');
    assert.strictEqual(st1.fase, 'autenticacion_requerida');
    assert.strictEqual(st1.requiere_autenticacion, true);
    assert.strictEqual(calls.some((c) => c.url.includes('/api/worker/proxima-tarea')), false, 'No debe consultar proxima-tarea sin sesión');
    console.log('✓ 1. Runner sin sesión se detiene en estado autenticacion_requerida sin consultar tareas.');

    // 2. Sesión expirada (401) detiene el runner sin bucle infinito ni ejecuciones
    calls = [];
    workerRunner.setAuthSession({ sessionToken: 'tok_expired' });
    workerRunner.startWorker(null);
    await new Promise((r) => setTimeout(r, 80));
    const st2 = workerRunner.getStatus();
    assert.strictEqual(st2.activo, false, 'Runner con sesión expirada debe detenerse');
    assert.strictEqual(st2.requiere_autenticacion, true);
    assert.strictEqual(calls.length, 1, 'Solo debe realizar 1 llamada a /api/auth/sesion sin entrar en bucle');
    assert.strictEqual(executedActions.length, 0);
    console.log('✓ 2. Sesión expirada (HTTP 401) detiene el runner inmediatamente sin bucles de reintento.');

    // 3. Manipulación de tenant (403) detiene el runner sin acceder a tareas ajenas ni entrar en bucle
    calls = [];
    workerRunner.configureRunner({
      transport: async (method, url, headers, body) => {
        calls.push({ method, url, headers, body });
        if (url.endsWith('/api/auth/sesion')) {
          return {
            statusCode: 200,
            ok: true,
            data: { autenticado: true, usuario: { id: 'usr_a', tenant_id: 'ten_a', rol: 'COMPANY_ADMIN' } }
          };
        }
        if (url.endsWith('/api/devices/server-public-key')) {
          return { statusCode: 200, ok: true, data: { ok: true, public_key_b64: serverKeys.publicKeyRawB64 } };
        }
        if (url.endsWith('/api/devices/register')) {
          // El usuario de ten_a intentó forzar tenant_id = ten_b -> backend responde 403
          if (body.tenant_id !== 'ten_a') {
            return { statusCode: 403, ok: false, data: { detail: 'No tiene permisos para operar sobre el tenant solicitado.' } };
          }
          return { statusCode: 200, ok: true, data: { ok: true, tenant_id: 'ten_a' } };
        }
        return { statusCode: 403, ok: false, data: { detail: 'Forbidden' } };
      }
    });
    workerRunner.setAuthSession({ sessionToken: 'tok_valid_a', tenantId: 'ten_b' });
    workerRunner.startWorker(null);
    await new Promise((r) => setTimeout(r, 80));
    const st3 = workerRunner.getStatus();
    assert.strictEqual(st3.activo, false, 'Debe detenerse ante HTTP 403 por tenant no autorizado');
    assert.strictEqual(st3.error_autorizacion, true);
    assert.strictEqual(calls.some((c) => c.url.includes('/api/worker/proxima-tarea')), false);
    console.log('✓ 3. Manipulación de tenant (ten_b con sesión de ten_a) recibe 403 y detiene el runner sin despachar tareas.');

    // 4. Dispositivo revocado detiene el runner inmediatamente
    calls = [];
    workerRunner.configureRunner({
      transport: async (method, url, headers, body) => {
        calls.push({ method, url, headers, body });
        if (url.endsWith('/api/auth/sesion')) {
          return {
            statusCode: 200,
            ok: true,
            data: { autenticado: true, usuario: { id: 'usr_a', tenant_id: 'ten_a', rol: 'COMPANY_ADMIN' } }
          };
        }
        if (url.endsWith('/api/devices/server-public-key')) {
          return { statusCode: 200, ok: true, data: { ok: true, public_key_b64: serverKeys.publicKeyRawB64 } };
        }
        if (url.endsWith('/api/devices/register')) {
          return { statusCode: 200, ok: true, data: { ok: true, tenant_id: 'ten_a' } };
        }
        if (url.includes('/api/worker/proxima-tarea')) {
          return { statusCode: 403, ok: false, data: { detail: 'Dispositivo no autorizado o revocado para este tenant (DEVICE_REVOKED).' } };
        }
        return { statusCode: 500, ok: false, data: {} };
      }
    });
    workerRunner.setAuthSession({ sessionToken: 'tok_valid_a', tenantId: 'ten_a' });
    workerRunner.startWorker(null);
    await new Promise((r) => setTimeout(r, 80));
    const st4 = workerRunner.getStatus();
    assert.strictEqual(st4.activo, false);
    assert.strictEqual(st4.dispositivo_revocado, true);
    console.log('✓ 4. Dispositivo revocado detiene el runner y marca dispositivo_revocado=true.');

    // 5. Firma inválida o comando de otro tenant es rechazado y NO ejecuta la acción
    executedActions = [];
    let reportedPayloads = [];
    workerRunner.configureRunner({
      transport: async (method, url, headers, body) => {
        if (url.endsWith('/api/auth/sesion')) {
          return {
            statusCode: 200,
            ok: true,
            data: { autenticado: true, usuario: { id: 'usr_a', tenant_id: 'ten_a', rol: 'COMPANY_ADMIN' } }
          };
        }
        if (url.endsWith('/api/devices/server-public-key')) {
          return { statusCode: 200, ok: true, data: { ok: true, public_key_b64: serverKeys.publicKeyRawB64 } };
        }
        if (url.endsWith('/api/devices/register')) {
          return { statusCode: 200, ok: true, data: { ok: true, tenant_id: 'ten_a' } };
        }
        if (url.includes('/api/worker/proxima-tarea')) {
          const devId = workerRunner.getStatus().device_id;
          const now = new Date();
          const exp = new Date(now.getTime() + 120000);
          // Comando con firma adulterada
          const tamperedCmd = {
            command_id: 'cmd_tampered_1',
            tenant_id: 'ten_a',
            device_id: devId,
            action: 'LI_VISIT_PROFILE',
            params: { lead_id: 'lead_a1', secuencia_id: 'seq_a', paso_id: 'step_1', profile_url: 'https://www.linkedin.com/in/alice' },
            nonce: 'nonce_t_1',
            issued_at: now.toISOString(),
            expires_at: exp.toISOString(),
            signature: Buffer.from('firma_falsa_invalida').toString('base64')
          };
          return {
            statusCode: 200,
            ok: true,
            data: {
              hay_tarea: true,
              comando: tamperedCmd,
              tarea: { id: 'cmd_tampered_1', command_id: 'cmd_tampered_1', tenant_id: 'ten_a', lead_id: 'lead_a1', secuencia_id: 'seq_a', paso_id: 'step_1', action: 'LI_VISIT_PROFILE' }
            }
          };
        }
        if (url.endsWith('/api/worker/reportar-resultado')) {
          reportedPayloads.push(body);
          return { statusCode: 200, ok: true, data: { ok: true, status: 'error' } };
        }
        return { statusCode: 200, ok: true, data: {} };
      }
    });
    workerRunner.setAuthSession({ sessionToken: 'tok_valid_a', tenantId: 'ten_a' });
    workerRunner.startWorker(null);
    await new Promise((r) => setTimeout(r, 50));
    workerRunner.stopWorker();
    assert.strictEqual(executedActions.length, 0, 'Nunca debe ejecutar un comando con firma inválida');
    assert.strictEqual(reportedPayloads.length, 1);
    assert.strictEqual(reportedPayloads[0].success, false);
    assert.ok(reportedPayloads[0].error.includes('RECHAZADO_POR_SEGURIDAD'));
    console.log('✓ 5. Comando con firma Ed25519 inválida es bloqueado antes de ejecutar y reporta rechazo firmado.');

    // 6. Resultado NO se marca como confirmado si el backend rechaza el reporte (HTTP 409/500)
    executedActions = [];
    workerRunner.configureRunner({
      transport: async (method, url, headers, body) => {
        if (url.endsWith('/api/auth/sesion')) {
          return {
            statusCode: 200,
            ok: true,
            data: { autenticado: true, usuario: { id: 'usr_a', tenant_id: 'ten_a', rol: 'COMPANY_ADMIN' } }
          };
        }
        if (url.endsWith('/api/devices/register')) {
          return { statusCode: 200, ok: true, data: { ok: true, tenant_id: 'ten_a' } };
        }
        if (url.includes('/api/worker/proxima-tarea')) {
          const devId = workerRunner.getStatus().device_id;
          const now = new Date();
          const exp = new Date(now.getTime() + 120000);
          const validCmd = signServerCommand(serverKeys.privateKey, {
            command_id: 'cmd_unconfirmed_1',
            tenant_id: 'ten_a',
            device_id: devId,
            action: 'LI_VISIT_PROFILE',
            params: { lead_id: 'lead_a1', secuencia_id: 'seq_a', paso_id: 'step_1', profile_url: 'https://www.linkedin.com/in/alice' },
            nonce: 'nonce_u_1',
            issued_at: now.toISOString(),
            expires_at: exp.toISOString()
          });
          return {
            statusCode: 200,
            ok: true,
            data: {
              hay_tarea: true,
              comando: validCmd,
              tarea: { id: 'cmd_unconfirmed_1', command_id: 'cmd_unconfirmed_1', tenant_id: 'ten_a', lead_id: 'lead_a1', secuencia_id: 'seq_a', paso_id: 'step_1', action: 'LI_VISIT_PROFILE', nombre_prospecto: 'Alice' }
            }
          };
        }
        if (url.endsWith('/api/worker/reportar-resultado')) {
          return { statusCode: 409, ok: false, data: { detail: 'INCOMPATIBLE_ENROLLMENT_STATE' } };
        }
        return { statusCode: 200, ok: true, data: {} };
      }
    });
    workerRunner.startWorker(null);
    await new Promise((r) => setTimeout(r, 50));
    const st6 = workerRunner.getStatus();
    workerRunner.stopWorker();
    assert.strictEqual(st6.ultima_accion, null, 'No debe registrar ultima_accion como confirmada si el backend rechazó el reporte');
    console.log('✓ 6. Si el backend no confirma el reporte (HTTP 409), la tarea no se marca como completada localmente.');

    // 7. Flujo legítimo completo: login -> verificación de sesión -> despacho -> firma -> confirmación del backend
    executedActions = [];
    reportedPayloads = [];
    workerRunner.configureRunner({
      transport: async (method, url, headers, body) => {
        assert.strictEqual(headers['Authorization'], 'Bearer tok_valid_a', 'Debe adjuntar Authorization Bearer en cada petición');
        if (url.endsWith('/api/auth/sesion')) {
          return {
            statusCode: 200,
            ok: true,
            data: { autenticado: true, usuario: { id: 'usr_a', tenant_id: 'ten_a', rol: 'COMPANY_ADMIN' } }
          };
        }
        if (url.endsWith('/api/devices/register')) {
          return { statusCode: 200, ok: true, data: { ok: true, tenant_id: 'ten_a' } };
        }
        if (url.includes('/api/worker/proxima-tarea')) {
          const devId = workerRunner.getStatus().device_id;
          const now = new Date();
          const exp = new Date(now.getTime() + 120000);
          const validCmd = signServerCommand(serverKeys.privateKey, {
            command_id: 'cmd_valid_ok_1',
            tenant_id: 'ten_a',
            device_id: devId,
            action: 'LI_VISIT_PROFILE',
            params: { lead_id: 'lead_a1', secuencia_id: 'seq_a', paso_id: 'step_1', profile_url: 'https://www.linkedin.com/in/alice' },
            nonce: 'nonce_valid_ok_1',
            issued_at: now.toISOString(),
            expires_at: exp.toISOString()
          });
          return {
            statusCode: 200,
            ok: true,
            data: {
              hay_tarea: true,
              comando: validCmd,
              tarea: { id: 'cmd_valid_ok_1', command_id: 'cmd_valid_ok_1', tenant_id: 'ten_a', lead_id: 'lead_a1', secuencia_id: 'seq_a', paso_id: 'step_1', action: 'LI_VISIT_PROFILE', nombre_prospecto: 'Alice Alpha', pausa_sugerida_seg: 60 }
            }
          };
        }
        if (url.endsWith('/api/worker/reportar-resultado')) {
          reportedPayloads.push(body);
          return {
            statusCode: 200,
            ok: true,
            data: { ok: true, status: 'ok', tarea_id: 'cmd_valid_ok_1', siguiente_paso_id: 'step_2' }
          };
        }
        return { statusCode: 200, ok: true, data: {} };
      }
    });
    workerRunner.startWorker(null);
    await new Promise((r) => setTimeout(r, 50));
    const st7 = workerRunner.getStatus();
    workerRunner.stopWorker();
    assert.strictEqual(executedActions.length, 1);
    assert.strictEqual(reportedPayloads.length, 1);
    assert.strictEqual(reportedPayloads[0].tenant_id, 'ten_a');
    assert.ok(reportedPayloads[0].device_signature);
    assert.ok(st7.ultima_accion);
    assert.strictEqual(st7.ultima_accion.confirmado_servidor, true);
    assert.strictEqual(st7.ultima_accion.tarea_id, 'cmd_valid_ok_1');
    console.log('✓ 7. Flujo legítimo de extremo a extremo completado y confirmado con firma Ed25519.');

    console.log('\n==============================================================');
    console.log('✓ TODOS LOS TESTS DE TASK-08 (NODE.JS) PASARON EXITOSAMENTE');
    console.log('==============================================================\n');
  } finally {
    workerRunner.stopWorker();
    if (fs.existsSync(tmpDir)) {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  }
}

runTests().catch((err) => {
  console.error('❌ FALLÓ EL TEST SUITE TASK-08 (NODE.JS):', err);
  process.exit(1);
});

