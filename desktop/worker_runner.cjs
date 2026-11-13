const http = require('http');
const https = require('https');
const path = require('path');
const { CryptoVerifier, resolveDefaultKeysDirectory } = require('./security/crypto_verifier.cjs');
const { executeAction } = require('./security/action_handlers.cjs');

let isLoopRunning = false;
let loopTimeout = null;
let currentGetWorkWindow = null;
let actionsSinceLastRecycle = 0;

let runnerDetails = {
  fase: 'reposo', // 'reposo' | 'autenticacion_requerida' | 'consultando' | 'ejecutando' | 'pausa_humana' | 'espera_cola' | 'error'
  accion_actual: 'Piloto automático en pausa / reposo',
  detalle_accion: 'Presiona Iniciar para reanudar el procesamiento de secuencias.',
  prospecto_actual: null,
  institucion_actual: null,
  tipo_accion: null,
  canal: null,
  cuenta_regresiva_hasta: null, // Unix timestamp en ms
  segundos_totales: null,
  pausa_inicio_ts: null,
  ultima_accion: null,
  requiere_autenticacion: false,
  error_autorizacion: false,
  dispositivo_revocado: false,
  tenant_id: null
};

let apiBase = process.env.API_BASE_URL || 'http://127.0.0.1:8000';

// Inicializar verificador criptográfico Ed25519 con claves persistentes en userData o storage
const defaultKeysDir = resolveDefaultKeysDirectory();
let cryptoVerifier = new CryptoVerifier(defaultKeysDir);
let isDeviceRegistered = false;
let registeredTenantId = null;
let registeredDeviceId = null;
let isServerKeySynced = false;

// Estado de sesión autenticada del runner (nunca utiliza un tenant fijo/hardcodeado)
let authSession = {
  sessionToken: null,
  requestedTenantId: null,
  verifiedUserId: null,
  verifiedTenantId: null,
  verifiedRole: null,
  verifiedAt: 0
};

let sessionProvider = null;
let customTransport = null;
let customActionExecutor = null;

/**
 * Configura o actualiza las credenciales de sesión autenticada del runner.
 * Nunca registra ni expone el token en logs ni en getStatus().
 */
function setAuthSession({ sessionToken = null, tenantId = null } = {}) {
  const cleanToken = typeof sessionToken === 'string' ? sessionToken.trim() : null;
  const cleanTenant = typeof tenantId === 'string' && tenantId.trim() ? tenantId.trim() : null;

  const tokenChanged = cleanToken !== authSession.sessionToken;
  const tenantChanged = cleanTenant !== authSession.requestedTenantId;

  authSession.sessionToken = cleanToken || null;
  authSession.requestedTenantId = cleanTenant || null;

  if (tokenChanged || tenantChanged) {
    authSession.verifiedUserId = null;
    authSession.verifiedTenantId = null;
    authSession.verifiedRole = null;
    authSession.verifiedAt = 0;
    isDeviceRegistered = false;
    registeredTenantId = null;
  }

  if (authSession.sessionToken) {
    runnerDetails.requiere_autenticacion = false;
    runnerDetails.error_autorizacion = false;
  }
}

/**
 * Limpia inmediatamente la sesión autenticada y detiene el bucle del runner.
 */
function clearAuthSession(reason = 'Sesión cerrada o expirada.') {
  authSession = {
    sessionToken: null,
    requestedTenantId: null,
    verifiedUserId: null,
    verifiedTenantId: null,
    verifiedRole: null,
    verifiedAt: 0
  };
  isDeviceRegistered = false;
  registeredTenantId = null;
  runnerDetails.ultima_accion = null;
  runnerDetails.dispositivo_revocado = false;
  runnerDetails.error_autorizacion = false;
  stopWorkerWithAuthRequired('🔒 Autenticación requerida', reason);
}

/**
 * Registra un proveedor asíncrono (ej. desde main.cjs) para recuperar el token activo
 * de la sesión autenticada cuando no fue inyectado aún en memoria.
 */
function setSessionProvider(providerFn) {
  sessionProvider = typeof providerFn === 'function' ? providerFn : null;
}

/**
 * Permite configurar dependencias en entornos de prueba aislados sin debilitar controles.
 */
function configureRunner(options = {}) {
  if (options.apiBase) {
    apiBase = options.apiBase;
  }
  if (options.keysDir) {
    cryptoVerifier = new CryptoVerifier(options.keysDir);
    isDeviceRegistered = false;
    registeredTenantId = null;
    registeredDeviceId = null;
    isServerKeySynced = false;
  }
  if (options.cryptoVerifier) {
    cryptoVerifier = options.cryptoVerifier;
    isDeviceRegistered = false;
    registeredTenantId = null;
    registeredDeviceId = null;
  }
  if (options.transport !== undefined) {
    customTransport = options.transport;
  }
  if (options.actionExecutor !== undefined) {
    customActionExecutor = options.actionExecutor;
  }
}

function buildAuthHeaders(extraHeaders = {}) {
  const headers = { ...extraHeaders };
  if (authSession.sessionToken) {
    headers['Authorization'] = `Bearer ${authSession.sessionToken}`;
    headers['X-Session-Token'] = authSession.sessionToken;
  }
  if (cryptoVerifier && cryptoVerifier.getDeviceId()) {
    headers['X-Device-Id'] = cryptoVerifier.getDeviceId();
  }
  return headers;
}

function defaultHttpRequest(method, url, headers = {}, data = null) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const client = u.protocol === 'https:' ? https : http;
    const body = data !== null && data !== undefined ? JSON.stringify(data) : null;
    const finalHeaders = { ...headers };
    if (body !== null) {
      finalHeaders['Content-Type'] = 'application/json';
      finalHeaders['Content-Length'] = Buffer.byteLength(body);
    }

    const req = client.request({
      hostname: u.hostname,
      port: u.port || (u.protocol === 'https:' ? 443 : 80),
      path: u.pathname + (u.search || ''),
      method,
      headers: finalHeaders
    }, (res) => {
      let raw = '';
      res.on('data', (c) => { raw += c; });
      res.on('end', () => {
        let parsed = raw;
        try {
          parsed = raw ? JSON.parse(raw) : {};
        } catch (e) {
          parsed = { detail: raw };
        }
        resolve({
          statusCode: res.statusCode || 500,
          ok: (res.statusCode || 500) >= 200 && (res.statusCode || 500) < 300,
          data: parsed
        });
      });
    });
    req.on('error', reject);
    if (body !== null) {
      req.write(body);
    }
    req.end();
  });
}

async function httpRequest(method, url, data = null, extraHeaders = {}) {
  const headers = buildAuthHeaders(extraHeaders);
  if (customTransport) {
    return await customTransport(method, url, headers, data);
  }
  return await defaultHttpRequest(method, url, headers, data);
}

function extractErrorDetail(data, fallbackMsg) {
  if (!data || typeof data !== 'object') return fallbackMsg;
  if (typeof data.detail === 'string') return data.detail;
  if (data.detail && typeof data.detail === 'object') {
    return data.detail.mensaje || data.detail.error || JSON.stringify(data.detail);
  }
  return data.motivo || data.error || data.mensaje || fallbackMsg;
}

function stopWorkerWithAuthRequired(title, detail) {
  isLoopRunning = false;
  if (loopTimeout) {
    clearTimeout(loopTimeout);
    loopTimeout = null;
  }
  runnerDetails.fase = 'autenticacion_requerida';
  runnerDetails.accion_actual = title || '🔒 Autenticación requerida';
  runnerDetails.detalle_accion = detail || 'Inicia sesión con una cuenta válida para ejecutar tareas.';
  runnerDetails.cuenta_regresiva_hasta = null;
  runnerDetails.segundos_totales = null;
  runnerDetails.prospecto_actual = null;
  runnerDetails.requiere_autenticacion = true;
  runnerDetails.tenant_id = null;
}

function stopWorkerWithAuthorizationError(title, detail, { revoked = false } = {}) {
  isLoopRunning = false;
  if (loopTimeout) {
    clearTimeout(loopTimeout);
    loopTimeout = null;
  }
  runnerDetails.fase = 'error';
  runnerDetails.accion_actual = title || '⛔ Acceso o Dispositivo No Autorizado';
  runnerDetails.detalle_accion = detail || 'El servidor rechazó la autorización del tenant o del dispositivo.';
  runnerDetails.cuenta_regresiva_hasta = null;
  runnerDetails.segundos_totales = null;
  runnerDetails.prospecto_actual = null;
  runnerDetails.error_autorizacion = true;
  runnerDetails.dispositivo_revocado = Boolean(revoked);
}

/**
 * Resuelve y verifica la sesión activa contra /api/auth/sesion en el backend.
 * Nunca utiliza un tenant fijo ni confía en valores locales sin validación del servidor.
 */
async function resolveVerifiedSession() {
  if (!authSession.sessionToken && sessionProvider) {
    try {
      const provided = await sessionProvider();
      if (provided && typeof provided === 'object' && provided.sessionToken) {
        setAuthSession({
          sessionToken: provided.sessionToken,
          tenantId: provided.tenantId || authSession.requestedTenantId
        });
      } else if (typeof provided === 'string' && provided.trim()) {
        setAuthSession({
          sessionToken: provided.trim(),
          tenantId: authSession.requestedTenantId
        });
      }
    } catch (e) {
      // No exponer detalles sensibles en consola
    }
  }

  if (!authSession.sessionToken) {
    stopWorkerWithAuthRequired(
      '🔒 Autenticación requerida',
      'No hay una sesión activa en el runner. Inicia sesión en NexusReach Pro para despachar tareas.'
    );
    return { ok: false, statusCode: 401, code: 'SESSION_MISSING' };
  }

  const sesRes = await httpRequest('GET', `${apiBase}/api/auth/sesion`);
  if (sesRes.statusCode === 401 || !sesRes.ok || !sesRes.data || !sesRes.data.autenticado || !sesRes.data.usuario) {
    authSession.sessionToken = null;
    authSession.verifiedTenantId = null;
    authSession.verifiedUserId = null;
    isDeviceRegistered = false;
    registeredTenantId = null;
    stopWorkerWithAuthRequired(
      '🔒 Sesión expirada o inválida',
      extractErrorDetail(sesRes.data, 'La sesión ha expirado. Vuelve a iniciar sesión para continuar.')
    );
    return { ok: false, statusCode: 401, code: 'SESSION_EXPIRED' };
  }

  const usuario = sesRes.data.usuario;
  const userTenantId = usuario.tenant_id || (usuario.tenant && usuario.tenant.id) || null;
  if (!userTenantId) {
    stopWorkerWithAuthorizationError(
      '⛔ Contexto de Tenant Inválido',
      'La sesión autenticada no tiene un tenant_id válido asignado en el servidor.'
    );
    return { ok: false, statusCode: 403, code: 'INVALID_USER_TENANT' };
  }

  authSession.verifiedUserId = usuario.id || null;
  authSession.verifiedTenantId = userTenantId;
  authSession.verifiedRole = usuario.rol || usuario.role || null;
  authSession.verifiedAt = Date.now();

  const effectiveTenantId = authSession.requestedTenantId || userTenantId;
  return {
    ok: true,
    userId: authSession.verifiedUserId,
    userTenantId,
    effectiveTenantId,
    role: authSession.verifiedRole
  };
}

async function syncServerPublicKeyIfNeeded() {
  if (isServerKeySynced) return;
  try {
    const keyRes = await httpRequest('GET', `${apiBase}/api/devices/server-public-key`);
    if (keyRes.ok && keyRes.data && keyRes.data.public_key_b64) {
      cryptoVerifier.addPinnedServerPublicKey(keyRes.data.public_key_b64);
      isServerKeySynced = true;
    }
  } catch (e) {
    // Continuar con las claves fijadas localmente si falla la consulta informativa
  }
}

/**
 * Registra y vincula el dispositivo Ed25519 bajo el tenant autenticado y autorizado por el backend.
 */
async function ensureDeviceRegistered(sessionCtx) {
  await syncServerPublicKeyIfNeeded();

  const currentDeviceId = cryptoVerifier.getDeviceId();
  const targetTenantId = sessionCtx.effectiveTenantId;

  if (
    isDeviceRegistered &&
    registeredTenantId === targetTenantId &&
    registeredDeviceId === currentDeviceId
  ) {
    return { ok: true, tenantId: targetTenantId, deviceId: currentDeviceId };
  }

  const regRes = await httpRequest('POST', `${apiBase}/api/devices/register`, {
    device_id: currentDeviceId,
    tenant_id: targetTenantId,
    public_key_ed25519: cryptoVerifier.getPublicKeyB64(),
    device_name: 'Electron Desktop Runner (Local)',
    client_version: '1.3.0'
  });

  if (regRes.statusCode === 401) {
    authSession.sessionToken = null;
    isDeviceRegistered = false;
    registeredTenantId = null;
    stopWorkerWithAuthRequired(
      '🔒 Sesión expirada al registrar dispositivo',
      extractErrorDetail(regRes.data, 'Autenticación requerida para emparejar el dispositivo.')
    );
    return { ok: false, statusCode: 401 };
  }

  if (regRes.statusCode === 403) {
    isDeviceRegistered = false;
    registeredTenantId = null;
    stopWorkerWithAuthorizationError(
      '⛔ Dispositivo o Tenant No Autorizado',
      extractErrorDetail(regRes.data, 'No tienes permisos para operar con este tenant o dispositivo.')
    );
    return { ok: false, statusCode: 403 };
  }

  if (!regRes.ok || !regRes.data || !regRes.data.ok) {
    return {
      ok: false,
      statusCode: regRes.statusCode || 500,
      error: extractErrorDetail(regRes.data, 'No se pudo registrar el dispositivo con el servidor.')
    };
  }

  // El backend devuelve el tenant_id efectivamente autorizado tras _resolve_permitted_tenants
  const resolvedTenant = regRes.data.tenant_id || targetTenantId;
  isDeviceRegistered = true;
  registeredTenantId = resolvedTenant;
  registeredDeviceId = currentDeviceId;
  runnerDetails.tenant_id = resolvedTenant;

  return { ok: true, tenantId: resolvedTenant, deviceId: currentDeviceId };
}

function formatTipoAccion(tipo) {
  switch (tipo) {
    case 'ENVIAR_INVITACION':
    case 'LI_SEND_INVITE':
      return 'Enviando invitación de conexión';
    case 'VISITAR_PERFIL':
    case 'LI_VISIT_PROFILE':
      return 'Visitando y analizando perfil';
    case 'ENVIAR_WHATSAPP_WEB':
    case 'WA_SEND_MESSAGE':
      return 'Enviando mensaje WhatsApp Web';
    case 'ENVIAR_MENSAJE_LINKEDIN':
    case 'LI_SEND_MESSAGE':
      return 'Enviando mensaje directo en LinkedIn';
    case 'CRUZAR_ZOHO_CRM':
    case 'SINCRONIZAR_ZOHO':
    case 'ZOHO_FIND_LEAD':
      return 'Sincronizando con Zoho CRM';
    default:
      return tipo ? tipo.replace(/_/g, ' ') : 'Ejecutando paso';
  }
}

/**
 * Bucle autónomo del Runner local en Electron con autenticación multi-tenant y verificación criptográfica
 */
async function runNextCycle(getWorkWindow) {
  if (!isLoopRunning) return;
  if (getWorkWindow) currentGetWorkWindow = getWorkWindow;

  try {
    // 1. Verificar sesión autenticada y resolver tenant autorizado (sin ningún valor hardcodeado)
    const sessionCtx = await resolveVerifiedSession();
    if (!sessionCtx.ok) {
      return;
    }

    // 2. Asegurar emparejamiento del dispositivo con el tenant autorizado
    const devReg = await ensureDeviceRegistered(sessionCtx);
    if (!devReg.ok) {
      if (devReg.statusCode === 401 || devReg.statusCode === 403) {
        return;
      }
      throw new Error(devReg.error || 'Error registrando el dispositivo con el servidor.');
    }

    const deviceId = devReg.deviceId;
    const effectiveTenantId = devReg.tenantId;

    runnerDetails.fase = 'consultando';
    runnerDetails.accion_actual = 'Consultando próximas órdenes a la nube...';
    runnerDetails.detalle_accion = 'Verificando comandos firmados, pausas estratégicas y cuotas de seguridad antiban.';
    runnerDetails.cuenta_regresiva_hasta = null;
    runnerDetails.segundos_totales = null;
    runnerDetails.prospecto_actual = null;

    const pollUrl = `${apiBase}/api/worker/proxima-tarea?device_id=${encodeURIComponent(deviceId)}&tenant_id=${encodeURIComponent(effectiveTenantId)}`;
    const pollRes = await httpRequest('GET', pollUrl);

    // Manejo sin bucle infinito ante HTTP 401 (sesión inválida/expirada)
    if (pollRes.statusCode === 401) {
      authSession.sessionToken = null;
      isDeviceRegistered = false;
      registeredTenantId = null;
      stopWorkerWithAuthRequired(
        '🔒 Sesión expirada',
        extractErrorDetail(pollRes.data, 'La sesión del worker expiró. Inicia sesión nuevamente.')
      );
      return;
    }

    // Manejo sin bucle infinito ante HTTP 403 (tenant no autorizado o dispositivo revocado/ajeno)
    if (pollRes.statusCode === 403) {
      const detail = extractErrorDetail(pollRes.data, 'Acceso denegado para este tenant o dispositivo.');
      const isRevoked = detail.toLowerCase().includes('revocado') || detail.toLowerCase().includes('dispositivo');
      stopWorkerWithAuthorizationError(
        isRevoked ? '⚠️ Dispositivo No Autorizado o Revocado' : '⛔ Tenant No Autorizado',
        detail,
        { revoked: isRevoked }
      );
      return;
    }

    if (!pollRes.ok) {
      throw new Error(extractErrorDetail(pollRes.data, `Error HTTP ${pollRes.statusCode} al consultar próxima tarea.`));
    }

    const response = pollRes.data || {};

    if (
      response.dispositivo_revocado ||
      response.error === 'UNAUTHORIZED_DEVICE' ||
      response.error === 'NO_ACTIVE_DEVICE'
    ) {
      stopWorkerWithAuthorizationError(
        '⚠️ Dispositivo Revocado',
        response.motivo || 'Este dispositivo ha sido revocado desde el servidor. El procesamiento está bloqueado.',
        { revoked: true }
      );
      return;
    }

    if (
      response.error === 'TENANT_REQUIRED' ||
      response.error === 'FORBIDDEN_SEQUENCE_TENANT'
    ) {
      stopWorkerWithAuthorizationError(
        '⛔ Contexto de Tenant No Autorizado',
        response.motivo || 'El servidor rechazó el ámbito del tenant solicitado.'
      );
      return;
    }

    if (!response.hay_tarea) {
      const espera = response.esperar_segundos ? response.esperar_segundos : 15;
      const motivo = response.motivo ? response.motivo : 'Sin tareas activas';
      const isDeepSleepMotivo = /horario|kill|pausad|l[ií]mite/i.test(motivo) || espera >= 120;
      const finalEspera = isDeepSleepMotivo ? Math.max(espera, 180) : espera;
      const targetTime = Date.now() + (finalEspera * 1000);

      runnerDetails.fase = 'espera_cola';
      runnerDetails.accion_actual = motivo;
      runnerDetails.detalle_accion = isDeepSleepMotivo
        ? `Modo reposo profundo antiban activo (${finalEspera}s). Navegador en hibernación para ahorrar recursos.`
        : `El despachador volverá a evaluar la cola de secuencias al finalizar el contador (${finalEspera}s).`;
      runnerDetails.cuenta_regresiva_hasta = targetTime;
      runnerDetails.segundos_totales = finalEspera;
      runnerDetails.pausa_inicio_ts = Date.now();
      runnerDetails.prospecto_actual = null;

      // Hibernar ventana de LinkedIn oculta durante reposo profundo (ahorro RAM/CPU + patrón humano)
      if (isDeepSleepMotivo && getWorkWindow) {
        try {
          const liWin = getWorkWindow(false, 'linkedin');
          if (liWin && !liWin.isDestroyed() && !liWin.isVisible()) {
            const curUrl = liWin.webContents.getURL() || '';
            if (curUrl && curUrl !== 'about:blank') {
              liWin.loadURL('about:blank').catch(() => {});
            }
            if (typeof liWin.webContents.setBackgroundThrottling === 'function') {
              liWin.webContents.setBackgroundThrottling(true);
            }
          }
        } catch (_) {}
      }

      if (isLoopRunning) {
        loopTimeout = setTimeout(() => runNextCycle(getWorkWindow), finalEspera * 1000);
      }
      return;
    }

    const tarea = response.tarea || {};
    const comando = response.comando;

    // 3. Exigir obligatoriamente comando firmado Ed25519 y verificar que coincida con el tenant y dispositivo autorizados
    if (!comando || typeof comando !== 'object') {
      runnerDetails.fase = 'error';
      runnerDetails.accion_actual = '⚠️ Comando Rechazado por Seguridad';
      runnerDetails.detalle_accion = 'El servidor devolvió una tarea sin comando firmado Ed25519.';
      if (isLoopRunning) {
        loopTimeout = setTimeout(() => runNextCycle(getWorkWindow), 15000);
      }
      return;
    }

    const verification = cryptoVerifier.verifyCommand(comando, effectiveTenantId);
    const bindingMismatch =
      (tarea.tenant_id && tarea.tenant_id !== effectiveTenantId) ||
      (comando.params && comando.params.lead_id && tarea.lead_id && String(comando.params.lead_id) !== String(tarea.lead_id)) ||
      (comando.params && comando.params.secuencia_id && tarea.secuencia_id && String(comando.params.secuencia_id) !== String(tarea.secuencia_id));

    if (!verification.valid || bindingMismatch) {
      const rejectReason = !verification.valid
        ? verification.reason
        : 'Inconsistencia entre los parámetros firmados del comando y los metadatos de la tarea.';
      console.error('[Worker Runner ALERTA DE SEGURIDAD]: Comando rechazado:', rejectReason);
      runnerDetails.fase = 'error';
      runnerDetails.accion_actual = '⚠️ Comando Rechazado por Seguridad';
      runnerDetails.detalle_accion = `Rechazo criptográfico: ${rejectReason}`;

      // Si el comando pertenece a nuestro dispositivo y tenant pero falló otra validación, notificar rechazo firmado
      if (comando.command_id && comando.device_id === deviceId && comando.tenant_id === effectiveTenantId) {
        const signedReject = cryptoVerifier.signResult({
          command_id: comando.command_id,
          tarea_id: comando.command_id,
          tenant_id: effectiveTenantId,
          lead_id: tarea.lead_id,
          secuencia_id: tarea.secuencia_id,
          paso_id: tarea.paso_id,
          action: comando.action,
          success: false,
          exito: false,
          result: {},
          error: `RECHAZADO_POR_SEGURIDAD: ${rejectReason}`
        });
        await httpRequest('POST', `${apiBase}/api/worker/reportar-resultado`, signedReject).catch(() => {});
      }

      if (isLoopRunning) {
        loopTimeout = setTimeout(() => runNextCycle(getWorkWindow), 15000);
      }
      return;
    }

    const actionToRun = comando.action || tarea.action || tarea.tipo;
    const canal = (actionToRun.includes('WA') || actionToRun.includes('WHATSAPP')) ? 'WhatsApp' :
                  (actionToRun.includes('ZOHO')) ? 'Zoho' : 'LinkedIn';
    const descAccion = formatTipoAccion(actionToRun);

    runnerDetails.fase = 'ejecutando';
    runnerDetails.prospecto_actual = tarea.nombre_prospecto || 'Prospecto';
    runnerDetails.institucion_actual = tarea.institucion || '';
    runnerDetails.tipo_accion = actionToRun;
    runnerDetails.canal = canal;
    runnerDetails.cuenta_regresiva_hasta = null;
    runnerDetails.segundos_totales = null;
    runnerDetails.accion_actual = `${descAccion} a ${runnerDetails.prospecto_actual}`;
    runnerDetails.detalle_accion = `Ejecutando acción autorizada con ${canal}...`;

    const executor = customActionExecutor || executeAction;
    let win = null;
    if (!customActionExecutor) {
      win = getWorkWindow ? getWorkWindow(false, canal) : null;
      if (!win) {
        throw new Error(`Navegador de trabajo no disponible para ${canal}`);
      }
    }

    // Ejecutar únicamente con los parámetros firmados dentro del comando verificado
    const execParams = comando.params || {};

    // Desactivar throttling solo durante la ejecución activa para precisión biométrica humana
    if (win && !win.isDestroyed() && win.webContents && typeof win.webContents.setBackgroundThrottling === 'function') {
      try { win.webContents.setBackgroundThrottling(false); } catch (_) {}
    }

    let execResult;
    try {
      execResult = await executor(
        actionToRun,
        execParams,
        {
          linkedInWindow: (canal === 'LinkedIn') ? win : null,
          whatsAppWindow: (canal === 'WhatsApp') ? win : null,
          zohoWindow: (canal === 'Zoho') ? win : null
        },
        { allowZoho: Boolean(response.zoho_activo) }
      );
    } finally {
      // Restaurar throttling en segundo plano apenas finaliza la acción
      if (win && !win.isDestroyed() && win.webContents && typeof win.webContents.setBackgroundThrottling === 'function') {
        try { win.webContents.setBackgroundThrottling(true); } catch (_) {}
      }
    }

    // 4. Firmar y reportar resultado al backend; exigir confirmación antes de dar por completada la tarea localmente
    runnerDetails.detalle_accion = 'Confirmando resultado firmado con el servidor y actualizando métricas...';
    const signedReport = cryptoVerifier.signResult({
      command_id: comando.command_id,
      tarea_id: comando.command_id,
      tenant_id: effectiveTenantId,
      lead_id: comando.params && comando.params.lead_id ? comando.params.lead_id : tarea.lead_id,
      secuencia_id: comando.params && comando.params.secuencia_id ? comando.params.secuencia_id : tarea.secuencia_id,
      paso_id: comando.params && comando.params.paso_id !== undefined ? comando.params.paso_id : tarea.paso_id,
      action: actionToRun,
      tipo: tarea.tipo,
      success: Boolean(execResult && execResult.success),
      exito: Boolean(execResult && execResult.success),
      result: (execResult && execResult.result) || {},
      error: (execResult && execResult.error) || ''
    });

    const reportRes = await httpRequest('POST', `${apiBase}/api/worker/reportar-resultado`, signedReport);

    if (reportRes.statusCode === 401) {
      authSession.sessionToken = null;
      isDeviceRegistered = false;
      stopWorkerWithAuthRequired(
        '🔒 Sesión expirada al reportar resultado',
        extractErrorDetail(reportRes.data, 'El servidor rechazó el reporte por sesión expirada.')
      );
      return;
    }

    if (reportRes.statusCode === 403) {
      stopWorkerWithAuthorizationError(
        '⛔ Reporte Rechazado por Autorización o Firma',
        extractErrorDetail(reportRes.data, 'El servidor rechazó la firma o autorización del reporte.')
      );
      return;
    }

    if (!reportRes.ok || !reportRes.data || reportRes.data.ok === false) {
      const errDetail = extractErrorDetail(reportRes.data, `Error HTTP ${reportRes.statusCode} al confirmar resultado.`);
      runnerDetails.fase = 'error';
      runnerDetails.accion_actual = `⚠️ Resultado no confirmado por el servidor`;
      runnerDetails.detalle_accion = errDetail;
      if (isLoopRunning) {
        loopTimeout = setTimeout(() => runNextCycle(getWorkWindow), 20000);
      }
      return;
    }

    // Solo tras la confirmación explícita del backend se registra la acción como confirmada localmente
    const pausa = tarea.pausa_sugerida_seg || 180;
    const segPausa = Math.round(pausa);
    const targetTime = Date.now() + (segPausa * 1000);

    // Reciclaje periódico del SPA de LinkedIn (cada 10 acciones) durante la pausa humana para liberar fugas de RAM
    actionsSinceLastRecycle += 1;
    if (canal === 'LinkedIn' && actionsSinceLastRecycle >= 10 && win && !win.isDestroyed() && !win.isVisible() && segPausa >= 60) {
      actionsSinceLastRecycle = 0;
      try {
        win.loadURL('about:blank').catch(() => {});
      } catch (_) {}
    }

    runnerDetails.fase = 'pausa_humana';
    runnerDetails.accion_actual = 'Pausa de seguridad humana antiban';
    runnerDetails.detalle_accion = 'Esperando simulación biométrica aleatoria antes del siguiente lead para proteger tu cuenta.';
    runnerDetails.cuenta_regresiva_hasta = targetTime;
    runnerDetails.segundos_totales = segPausa;
    runnerDetails.pausa_inicio_ts = Date.now();
    runnerDetails.ultima_accion = {
      tarea_id: comando.command_id,
      tipo: actionToRun,
      nombre_accion: descAccion,
      prospecto: runnerDetails.prospecto_actual,
      institucion: tarea.institucion || '',
      canal: canal,
      exito: Boolean(execResult && execResult.success),
      confirmado_servidor: true,
      siguiente_paso_id: reportRes.data.siguiente_paso_id || null,
      timestamp: Date.now()
    };

    if (isLoopRunning) {
      loopTimeout = setTimeout(() => runNextCycle(getWorkWindow), segPausa * 1000);
    }

  } catch (err) {
    console.error('[Worker Runner Error]:', err.message);
    const esperaError = 20;
    const targetTime = Date.now() + (esperaError * 1000);
    runnerDetails.fase = 'error';
    runnerDetails.accion_actual = `Error en ciclo: ${err.message}`;
    runnerDetails.detalle_accion = 'Reintentando conexión automáticamente tras la pausa de seguridad.';
    runnerDetails.cuenta_regresiva_hasta = targetTime;
    runnerDetails.segundos_totales = esperaError;
    runnerDetails.pausa_inicio_ts = Date.now();
    if (isLoopRunning) {
      loopTimeout = setTimeout(() => runNextCycle(getWorkWindow), esperaError * 1000);
    }
  }
}

function startWorker(getWorkWindow, authOptions = null) {
  if (authOptions && typeof authOptions === 'object') {
    setAuthSession(authOptions);
  }
  if (isLoopRunning) return Promise.resolve();
  isLoopRunning = true;
  if (getWorkWindow) currentGetWorkWindow = getWorkWindow;
  runnerDetails.fase = 'consultando';
  runnerDetails.accion_actual = 'Iniciando piloto automático...';
  runnerDetails.detalle_accion = 'Verificando sesión autenticada y conectando con el despachador.';
  runnerDetails.cuenta_regresiva_hasta = null;
  runnerDetails.segundos_totales = null;
  return runNextCycle(getWorkWindow);
}

function stopWorker() {
  isLoopRunning = false;
  if (loopTimeout) {
    clearTimeout(loopTimeout);
    loopTimeout = null;
  }
  runnerDetails.fase = 'reposo';
  runnerDetails.accion_actual = 'Piloto automático en pausa';
  runnerDetails.detalle_accion = 'Secuencias pausadas. Haz clic en Activar para reanudar.';
  runnerDetails.cuenta_regresiva_hasta = null;
  runnerDetails.segundos_totales = null;
  runnerDetails.prospecto_actual = null;
}

function forceNextCycle(getWorkWindow, authOptions = null) {
  if (authOptions && typeof authOptions === 'object') {
    setAuthSession(authOptions);
  }
  if (getWorkWindow) currentGetWorkWindow = getWorkWindow;
  const winGetter = getWorkWindow || currentGetWorkWindow;

  if (loopTimeout) {
    clearTimeout(loopTimeout);
    loopTimeout = null;
  }

  isLoopRunning = true;
  runnerDetails.fase = 'consultando';
  runnerDetails.accion_actual = 'Adelantando pausa humana: solicitando siguiente tarea...';
  runnerDetails.detalle_accion = 'Ejecución manual disparada por el usuario.';
  runnerDetails.cuenta_regresiva_hasta = null;
  runnerDetails.segundos_totales = null;

  setImmediate(() => {
    runNextCycle(winGetter);
  });

  return { ok: true, mensaje: 'Pausa adelantada: solicitando próxima orden de inmediato' };
}

function getStatus() {
  const now = Date.now();
  let segRestantes = null;
  if (runnerDetails.cuenta_regresiva_hasta && runnerDetails.cuenta_regresiva_hasta > now) {
    segRestantes = Math.max(0, Math.ceil((runnerDetails.cuenta_regresiva_hasta - now) / 1000));
  } else if (runnerDetails.cuenta_regresiva_hasta) {
    segRestantes = 0;
  }

  let estadoStr = runnerDetails.accion_actual;
  if (runnerDetails.fase === 'pausa_humana' && segRestantes !== null) {
    estadoStr = `Pausa humana: esperando ${segRestantes}s antes del próximo lead...`;
  } else if (runnerDetails.fase === 'ejecutando' && runnerDetails.prospecto_actual) {
    estadoStr = `${runnerDetails.accion_actual}`;
  } else if (!isLoopRunning && runnerDetails.fase === 'reposo') {
    estadoStr = 'Piloto automático en pausa';
  }

  return {
    activo: isLoopRunning,
    estado_actual: estadoStr,
    fase: isLoopRunning ? runnerDetails.fase : (
      runnerDetails.fase === 'autenticacion_requerida' || runnerDetails.fase === 'error'
        ? runnerDetails.fase
        : 'reposo'
    ),
    accion_actual: runnerDetails.accion_actual,
    detalle_accion: runnerDetails.detalle_accion,
    prospecto_actual: runnerDetails.prospecto_actual,
    institucion_actual: runnerDetails.institucion_actual,
    tipo_accion: runnerDetails.tipo_accion,
    canal: runnerDetails.canal,
    cuenta_regresiva_hasta: runnerDetails.cuenta_regresiva_hasta,
    segundos_totales: runnerDetails.segundos_totales,
    segundos_restantes: segRestantes,
    pausa_inicio_ts: runnerDetails.pausa_inicio_ts,
    ultima_accion: runnerDetails.ultima_accion,
    requiere_autenticacion: Boolean(runnerDetails.requiere_autenticacion),
    error_autorizacion: Boolean(runnerDetails.error_autorizacion),
    dispositivo_revocado: Boolean(runnerDetails.dispositivo_revocado),
    tenant_id: runnerDetails.tenant_id || authSession.verifiedTenantId || null,
    device_id: cryptoVerifier ? cryptoVerifier.getDeviceId() : null
  };
}

module.exports = {
  startWorker,
  stopWorker,
  forceNextCycle,
  getStatus,
  setAuthSession,
  clearAuthSession,
  setSessionProvider,
  configureRunner,
  runNextCycle
};
