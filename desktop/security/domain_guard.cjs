/**
 * Módulo de Control de Dominios Autorizados (Allowlist Guard)
 * (Workstream 5.1 - Requisito 5 de las Directrices de Ingeniería v1.3)
 * 
 * Garantiza que el navegador embebido solo pueda navegar o comunicarse con dominios
 * explícitamente permitidos (LinkedIn, WhatsApp Web y opcionalmente Zoho CRM Bridge).
 * Todo otro dominio es rechazado y bloqueado antes de emitir la petición.
 */

const ALLOWED_DOMAIN_PATTERNS = [
  // LinkedIn
  /^https?:\/\/([a-zA-Z0-9-]+\.)*linkedin\.com(\/.*)?$/i,
  /^https?:\/\/([a-zA-Z0-9-]+\.)*licdn\.com(\/.*)?$/i,

  // WhatsApp Web
  /^https?:\/\/web\.whatsapp\.com(\/.*)?$/i,
  /^https?:\/\/([a-zA-Z0-9-]+\.)*whatsapp\.com(\/.*)?$/i,
  /^https?:\/\/([a-zA-Z0-9-]+\.)*whatsapp\.net(\/.*)?$/i
];

const ZOHO_DOMAIN_PATTERNS = [
  // Zoho CRM del centro de datos EE. UU. (zoho.com) y sus CDNs de recursos estáticos
  /^https?:\/\/([a-zA-Z0-9-]+\.)*zoho\.com(\/.*)?$/i,
  /^https?:\/\/([a-zA-Z0-9-]+\.)*zohocdn\.com(\/.*)?$/i
];

/**
 * Valida si una URL pertenece a los dominios autorizados de la allowlist.
 * @param {string} url - URL a validar
 * @param {boolean} allowZoho - Si el tenant tiene activado el módulo Zoho Bridge
 * @returns {{ allowed: boolean, channel: string|null, reason?: string }}
 */
function isUrlAllowed(url, allowZoho = false) {
  if (!url || typeof url !== 'string') {
    return { allowed: false, channel: null, reason: 'URL vacía o no válida' };
  }

  // Permitir páginas internas vacías seguras
  if (url === 'about:blank') {
    return { allowed: true, channel: 'internal' };
  }

  let parsed;
  try {
    parsed = new URL(url);
  } catch (err) {
    return { allowed: false, channel: null, reason: 'URL malformada' };
  }

  // Solo protocolos HTTP y HTTPS permitidos
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return { allowed: false, channel: null, reason: `Protocolo no permitido: ${parsed.protocol}` };
  }

  // 1. LinkedIn
  const host = parsed.hostname.toLowerCase();
  if (host === 'linkedin.com' || host.endsWith('.linkedin.com') || host === 'licdn.com' || host.endsWith('.licdn.com')) {
    return { allowed: true, channel: 'linkedin' };
  }

  // 2. WhatsApp Web
  if (host === 'web.whatsapp.com' || host.endsWith('.whatsapp.com') || host.endsWith('.whatsapp.net')) {
    return { allowed: true, channel: 'whatsapp' };
  }

  // 3. Zoho CRM
  const isZohoHost = host === 'zoho.com' || host.endsWith('.zoho.com') ||
                     host === 'zohocdn.com' || host.endsWith('.zohocdn.com') ||
                     host === 'localzohocdn.com' || host.endsWith('.localzohocdn.com') ||
                     host === 'zohocorp.com' || host.endsWith('.zohocorp.com') ||
                     host === 'zurl.to' || host.endsWith('.zurl.to') ||
                     host.endsWith('.zohocloud.ca') || host.endsWith('.zoho.eu') ||
                     host.endsWith('.zoho.in') || host.endsWith('.zoho.com.au');
  if (isZohoHost) {
    if (!allowZoho) {
      return { 
        allowed: false, 
        channel: 'zoho', 
        reason: 'El módulo Zoho Bridge no está activado para este tenant o cuenta' 
      };
    }
    return { allowed: true, channel: 'zoho' };
  }

  return { 
    allowed: false, 
    channel: null, 
    reason: `Dominio '${host}' no figura en la lista de dominios permitidos (Allowlist Guard)` 
  };
}

/**
 * Dependencias de seguridad que la propia web de LinkedIn carga (captcha y sensor antibots).
 * Solo se admiten como sub-recursos de la sesión LinkedIn, nunca como destino de navegación.
 */
function isLinkedInSecurityDependency(parsed) {
  const host = parsed.hostname.toLowerCase();
  const path = parsed.pathname || '';
  if ((host === 'www.google.com' || host === 'www.gstatic.com') && path.startsWith('/recaptcha/')) {
    return true;
  }
  if (host === 'li.protechts.net') {
    return true;
  }
  return false;
}

/**
 * Validación para sub-recursos dentro de las sesiones embebidas (webRequest.onBeforeRequest).
 * Igual que isUrlAllowed, pero además:
 *  - Admite WebSocket seguro (wss:) hacia dominios ya permitidos (necesario para WhatsApp Web).
 *  - Admite las dependencias de seguridad de LinkedIn (reCAPTCHA y HUMAN/PerimeterX).
 * isUrlAllowed se mantiene estricto (solo http/https) para navegación y comandos.
 */
function isSubresourceAllowed(url, allowZoho = false) {
  if (!url || typeof url !== 'string') {
    return isUrlAllowed(url, allowZoho);
  }
  let parsed;
  try {
    parsed = new URL(url);
  } catch (err) {
    return isUrlAllowed(url, allowZoho);
  }

  if (parsed.protocol === 'wss:') {
    const asHttps = 'https:' + url.slice('wss:'.length);
    return isUrlAllowed(asHttps, allowZoho);
  }

  if (parsed.protocol === 'https:' && isLinkedInSecurityDependency(parsed)) {
    return { allowed: true, channel: 'linkedin' };
  }

  return isUrlAllowed(url, allowZoho);
}

// Publicidad / tracking / medición de terceros: se bloquean sin registrar en consola.
const SILENT_BLOCK_HOSTS = [
  'doubleclick.net',
  'adnxs.com',
  'bing.com',
  'ns1p.net',
  'googleadservices.com',
  'googlesyndication.com',
  'adsrvr.org'
];

/**
 * Indica si una petición debe cancelarse sin registrar advertencia (ruido esperado):
 * sondeos de extensiones chrome-extension:// y píxeles publicitarios conocidos.
 */
function isSilentlyBlocked(url) {
  if (!url || typeof url !== 'string') return false;
  if (url.startsWith('chrome-extension:')) return true;
  try {
    const host = new URL(url).hostname.toLowerCase();
    return SILENT_BLOCK_HOSTS.some(d => host === d || host.endsWith('.' + d));
  } catch (err) {
    return false;
  }
}

module.exports = {
  isUrlAllowed,
  isSubresourceAllowed,
  isSilentlyBlocked,
  ALLOWED_DOMAIN_PATTERNS,
  ZOHO_DOMAIN_PATTERNS
};
