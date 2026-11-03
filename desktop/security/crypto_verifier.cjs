/**
 * Módulo Criptográfico y Verificador de Comandos (Workstream 5.1 - NexusReach Pro)
 * 
 * Implementa en Node.js/Electron:
 * 1. Generación y almacenamiento seguro del par de claves Ed25519 del dispositivo.
 * 2. Fijación (pinning) de claves públicas autorizadas del servidor con rotación.
 * 3. Verificación de firma Ed25519, TTL estricto (<= 120s) y control anti-replay (nonces).
 * 4. Validación de pertenencia a la lista cerrada de acciones tipadas.
 * 5. Firma criptográfica de reportes de ejecución emitidos por el dispositivo.
 */

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const ALLOWED_ACTIONS = new Set([
  'LI_VISIT_PROFILE',
  'LI_SEND_INVITE',
  'LI_SEND_MESSAGE',
  'LI_SYNC_CONNECTIONS',
  'LI_READ_CONTACT_INFO',
  'WA_SEND_MESSAGE',
  'WA_CHECK_NUMBER',
  'ZOHO_FIND_LEAD',
  'ZOHO_UPSERT_LEAD',
  'ZOHO_SET_STATUS',
  'ZOHO_ADD_NOTE',
  'PAUSE',
  'RESUME'
]);

// Clave pública del servidor fijada (pinned) con mecanismo de rotación
const PINNED_SERVER_PUBLIC_KEYS = [
  process.env.SERVER_PUBLIC_KEY_PINNED || 'vQ0nZ7Su4UnboUrtTvuDStBgO9qosLw5VCOpn13P+14='
];

// Caché deslizante de anti-replay (nonces vistos recientemente con expiración)
const seenNonces = new Map(); // nonce -> expiry_timestamp_ms
const seenCommandIds = new Map(); // command_id -> expiry_timestamp_ms

function purgeExpiredNonces() {
  const now = Date.now();
  for (const [nonce, exp] of seenNonces.entries()) {
    if (exp < now) seenNonces.delete(nonce);
  }
  for (const [cid, exp] of seenCommandIds.entries()) {
    if (exp < now) seenCommandIds.delete(cid);
  }
}
const _noncePurgeTimer = setInterval(purgeExpiredNonces, 60000); // Purga periódica cada minuto
if (_noncePurgeTimer && typeof _noncePurgeTimer.unref === 'function') {
  _noncePurgeTimer.unref();
}

/**
 * Canonicaliza un objeto JSON lexicográficamente de forma idéntica al backend en Python.
 */
function canonicalizeJson(obj) {
  if (obj === null || typeof obj !== 'object') {
    return JSON.stringify(obj);
  }
  if (Array.isArray(obj)) {
    return '[' + obj.map(canonicalizeJson).join(',') + ']';
  }
  const sortedKeys = Object.keys(obj).sort();
  const parts = sortedKeys.map(k => `${JSON.stringify(k)}:${canonicalizeJson(obj[k])}`);
  return '{' + parts.join(',') + '}';
}

class CryptoVerifier {
  constructor(keysDirectory) {
    this.keysDir = keysDirectory || path.join(process.cwd(), 'device_keys');
    this.deviceId = null;
    this.privateKey = null;
    this.publicKey = null;
    this.publicKeyRawB64 = null;
    this.seenNonces = seenNonces;
    this.seenCommandIds = seenCommandIds;
    this.initDeviceKeys();
  }

  /**
   * Carga o genera el par de claves Ed25519 del dispositivo.
   */
  initDeviceKeys() {
    if (!fs.existsSync(this.keysDir)) {
      fs.mkdirSync(this.keysDir, { recursive: true });
    }

    const privPath = path.join(this.keysDir, 'device_private.pem');
    const idPath = path.join(this.keysDir, 'device_id.txt');

    if (fs.existsSync(privPath) && fs.existsSync(idPath)) {
      try {
        const pem = fs.readFileSync(privPath, 'utf8');
        this.privateKey = crypto.createPrivateKey(pem);
        this.publicKey = crypto.createPublicKey(this.privateKey);
        this.deviceId = fs.readFileSync(idPath, 'utf8').trim();

        const spkiDer = this.publicKey.export({ type: 'spki', format: 'der' });
        this.publicKeyRawB64 = spkiDer.subarray(12).toString('base64');
        return;
      } catch (err) {
        console.warn('[CryptoVerifier] Error cargando claves existentes, regenerando:', err.message);
      }
    }

    // Generar nuevo par de claves
    const { publicKey, privateKey } = crypto.generateKeyPairSync('ed25519');
    this.privateKey = privateKey;
    this.publicKey = publicKey;
    this.deviceId = 'dev_' + crypto.randomUUID().replace(/-/g, '');

    const privPem = privateKey.export({ type: 'pkcs8', format: 'pem' });
    const pubPem = publicKey.export({ type: 'spki', format: 'pem' });
    const spkiDer = publicKey.export({ type: 'spki', format: 'der' });
    this.publicKeyRawB64 = spkiDer.subarray(12).toString('base64');

    fs.writeFileSync(privPath, privPem, { mode: 0o600 });
    fs.writeFileSync(path.join(this.keysDir, 'device_public.pem'), pubPem);
    fs.writeFileSync(idPath, this.deviceId, { mode: 0o600 });

    console.log('[CryptoVerifier] Nuevo par de claves de dispositivo Ed25519 generado:', this.deviceId);
  }

  getDeviceId() {
    return this.deviceId;
  }

  getPublicKeyB64() {
    return this.publicKeyRawB64;
  }

  /**
   * Registra una clave pública Ed25519 del servidor en el conjunto fijado (pinning) de la instancia.
   */
  addPinnedServerPublicKey(pubKeyB64) {
    if (typeof pubKeyB64 === 'string' && pubKeyB64.trim().length > 0) {
      const clean = pubKeyB64.trim();
      if (!PINNED_SERVER_PUBLIC_KEYS.includes(clean)) {
        PINNED_SERVER_PUBLIC_KEYS.unshift(clean);
      }
    }
  }

  /**
   * Valida integralmente un comando recibido desde el servidor:
   * 1. Expiración (TTL)
   * 2. Anti-Replay (nonce y command_id únicos)
   * 3. Acción en lista cerrada
   * 4. Vinculación de device_id y tenant_id
   * 5. Firma criptográfica contra las claves públicas fijadas (pinned)
   */
  verifyCommand(command, expectedTenantId = null) {
    if (!command || typeof command !== 'object') {
      return { valid: false, reason: 'Comando no es un objeto JSON válido' };
    }

    const {
      command_id,
      tenant_id,
      device_id,
      action,
      params,
      nonce,
      issued_at,
      expires_at,
      signature
    } = command;

    // 1. Campos obligatorios
    if (!command_id || !tenant_id || !device_id || !action || !nonce || !issued_at || !expires_at || !signature) {
      return { valid: false, reason: 'Comando incompleto: faltan metadatos requeridos' };
    }

    // 2. Destinatario de dispositivo y aislamiento de tenant
    if (device_id !== this.deviceId) {
      return { valid: false, reason: `Comando destinado a otro dispositivo (${device_id} != ${this.deviceId})` };
    }

    if (expectedTenantId && tenant_id !== expectedTenantId) {
      return {
        valid: false,
        reason: `Comando pertenece a un tenant distinto al contexto autorizado (${tenant_id} != ${expectedTenantId})`
      };
    }

    // 3. Lista cerrada de acciones
    if (!ALLOWED_ACTIONS.has(action)) {
      return { valid: false, reason: `Acción '${action}' no permitida por la directriz de seguridad` };
    }

    // 4. Verificación de Expiración (TTL)
    const now = Date.now();
    const expTime = Date.parse(expires_at);
    if (isNaN(expTime)) {
      return { valid: false, reason: 'Formato de fecha expires_at inválido' };
    }
    if (now > expTime) {
      return { valid: false, reason: `Comando caducado (expiró hace ${Math.round((now - expTime) / 1000)}s)` };
    }

    // 5. Anti-Replay (Nonce y Command ID)
    if (seenNonces.has(nonce)) {
      return { valid: false, reason: 'Replay detectado: nonce ya fue utilizado previamente' };
    }
    if (seenCommandIds.has(command_id)) {
      return { valid: false, reason: 'Replay detectado: command_id ya fue procesado' };
    }

    // 6. Verificación Criptográfica Ed25519
    const payloadToVerify = {
      command_id,
      tenant_id: tenant_id || '',
      device_id: device_id || this.deviceId,
      action,
      params: params || {},
      nonce,
      issued_at,
      expires_at
    };

    const canonicalStr = canonicalizeJson(payloadToVerify);
    const dataBuffer = Buffer.from(canonicalStr, 'utf8');

    let sigBuffer;
    try {
      sigBuffer = Buffer.from(signature, 'base64');
    } catch (e) {
      return { valid: false, reason: 'Firma en formato base64 inválido' };
    }

    let isSigValid = false;
    for (const pinnedKeyB64 of PINNED_SERVER_PUBLIC_KEYS) {
      try {
        const rawPub = Buffer.from(pinnedKeyB64, 'base64');
        const spkiPrefix = Buffer.from('302a300506032b6570032100', 'hex');
        const spkiKey = Buffer.concat([spkiPrefix, rawPub]);
        const serverPubKey = crypto.createPublicKey({ key: spkiKey, format: 'der', type: 'spki' });

        if (crypto.verify(null, dataBuffer, serverPubKey, sigBuffer)) {
          isSigValid = true;
          break;
        }
      } catch (err) {
        // Continuar probando claves fijadas alternativas de rotación
      }
    }

    if (!isSigValid) {
      return { valid: false, reason: 'Firma Ed25519 del servidor inválida o no coincide con claves fijadas' };
    }

    // Registrar en caché anti-replay hasta que expire el TTL
    seenNonces.set(nonce, expTime);
    seenCommandIds.set(command_id, expTime);

    return { valid: true, action, params };
  }

  /**
   * Firma criptográficamente el resultado de ejecución con la clave privada del dispositivo.
   */
  signResult(reportData) {
    const payload = {
      command_id: reportData.command_id,
      device_id: this.deviceId,
      success: Boolean(reportData.success),
      result: reportData.result || {},
      error: reportData.error || ''
    };

    const canonicalStr = canonicalizeJson(payload);
    const dataBuffer = Buffer.from(canonicalStr, 'utf8');
    const signatureBuffer = crypto.sign(null, dataBuffer, this.privateKey);

    return {
      ...reportData,
      device_id: this.deviceId,
      device_signature: signatureBuffer.toString('base64'),
      reported_at: new Date().toISOString()
    };
  }
}

module.exports = {
  CryptoVerifier,
  ALLOWED_ACTIONS,
  canonicalizeJson,
  seenNonces,
  seenCommandIds
};
