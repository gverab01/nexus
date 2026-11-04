const { app, BrowserWindow, session, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const workerRunner = require('./worker_runner.cjs');

const { isUrlAllowed, isSubresourceAllowed, isSilentlyBlocked } = require('./security/domain_guard.cjs');
const { 
  handleLinkedInExtractNetwork, 
  handleLinkedInEnrichProfile,
  handleLinkedInReadContactInfo,
  handleLinkedInSearchPeople
} = require('./security/action_handlers.cjs');

let mainWindow = null;
let linkedInWindow = null;
let whatsAppWindow = null;
let zohoWindow = null;
let zohoConsoleLogs = [];
let cachedWhatsAppSession = false;
const INTERNAL_PORT = 9099;

// Desactivar flags de automatización en Chromium y silenciar logs internos de depuración de Chromium (Hit debug scenario: 4 y handshake net_error -101)
app.commandLine.appendSwitch('disable-blink-features', 'AutomationControlled');
app.commandLine.appendSwitch('excludeSwitches', 'enable-automation');
app.commandLine.appendSwitch('log-level', '3'); // Silencia advertencias internas no críticas de Chromium
app.commandLine.appendSwitch('ignore-certificate-errors'); // Evita errores SSL net_error -101 en sockets/telemetría interna

const STEALTH_INJECTION_SCRIPT = `
  (() => {
    try {
      // 1. Eliminar rastro de automatización
      Object.defineProperty(navigator, 'webdriver', { get: () => undefined, configurable: true });
      
      // 2. Emular objeto window.chrome auténtico
      if (!window.chrome) {
        window.chrome = {};
      }
      window.chrome.runtime = window.chrome.runtime || {
        OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' },
        PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
        PlatformNaclArch: { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
        PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' }
      };
      window.chrome.loadTimes = window.chrome.loadTimes || function() { return {}; };
      window.chrome.csi = window.chrome.csi || function() { return {}; };
      window.chrome.app = window.chrome.app || { isInstalled: false };

      // 3. Emular idiomas consistentes con el locale del usuario
      Object.defineProperty(navigator, 'languages', {
        get: () => ['es-CL', 'es', 'en-US', 'en'],
        configurable: true
      });

      // 4. Emular Plugins estándar de Chromium/Chrome
      if (!navigator.plugins || navigator.plugins.length === 0) {
        const dummyPlugins = [
          { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
          { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
          { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' }
        ];
        Object.defineProperty(navigator, 'plugins', {
          get: () => dummyPlugins,
          configurable: true
        });
      }

      // 5. Normalizar consulta de permisos
      if (navigator.permissions && navigator.permissions.query) {
        const origQuery = navigator.permissions.query.bind(navigator.permissions);
        navigator.permissions.query = (parameters) => {
          if (parameters && parameters.name === 'notifications') {
            return Promise.resolve({ state: Notification.permission });
          }
          return origQuery(parameters);
        };
      }
    } catch (e) {}
  })()
`;

// Particiones persistentes e independientes por servicio (Workstream 5.1 - C-03)
const LI_PARTITION_NAME = 'persist:nexusreach_li_session';
const WA_PARTITION_NAME = 'persist:nexusreach_wa_session';
const ZOHO_PARTITION_NAME = 'persist:nexusreach_zoho_bridge';

/**
 * Migra de forma transparente los datos de sesión existentes (cookies, IndexedDB, etc.)
 * desde la partición histórica compartida hacia las particiones independientes por servicio.
 */
function migrateLegacyPartitions() {
  try {
    const partitionsDir = path.join(app.getPath('userData'), 'Partitions');
    if (!fs.existsSync(partitionsDir)) {
      fs.mkdirSync(partitionsDir, { recursive: true });
    }

    const legacyDirs = ['nexusreach_work_session', 'dripify_work_session'];
    let sourceLegacy = null;
    for (const legacy of legacyDirs) {
      const fullPath = path.join(partitionsDir, legacy);
      if (fs.existsSync(fullPath)) {
        sourceLegacy = fullPath;
        break;
      }
    }

    if (!sourceLegacy) return;

    const targets = ['nexusreach_li_session', 'nexusreach_wa_session', 'nexusreach_zoho_bridge'];
    for (const target of targets) {
      const targetPath = path.join(partitionsDir, target);
      if (!fs.existsSync(targetPath)) {
        console.log(`[Electron Sesion] Migrando partición persistente de ${path.basename(sourceLegacy)} a ${target}...`);
        try {
          fs.cpSync(sourceLegacy, targetPath, { recursive: true });
          console.log(`[Electron Sesion] Migración a ${target} completada exitosamente.`);
        } catch (copyErr) {
          console.warn(`[Electron Sesion] Error migrando partición a ${target}:`, copyErr.message);
        }
      }
    }
  } catch (err) {
    console.warn('[Electron Sesion] Excepción durante la migración de particiones:', err.message);
  }
}

async function checkWhatsAppWebSession(win) {
  if (!win || win.isDestroyed()) return false;
  try {
    const url = win.webContents.getURL();
    if (url.includes('web.whatsapp.com')) {
      const isAuth = await win.webContents.executeJavaScript(`
        Boolean(
          window.localStorage.getItem('last-wid') ||
          window.localStorage.getItem('WABrowserId') ||
          document.querySelector('#pane-side') ||
          document.querySelector('[data-testid="chat-list"]') ||
          (document.querySelector('#app') && !document.querySelector('canvas[aria-label]'))
        )
      `);
      if (isAuth) {
        cachedWhatsAppSession = true;
      }
      return isAuth;
    }
  } catch (err) {}
  return false;
}

/**
 * Configura los controles de Allowlist (DomainGuard) y listeners de sesión para cada partición aislada.
 */
function setupSessionGuardsAndListeners() {
  migrateLegacyPartitions();

  const cleanUserAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36';

  // 1. Partición LinkedIn
  const liSession = session.fromPartition(LI_PARTITION_NAME);
  liSession.setUserAgent(cleanUserAgent);
  liSession.webRequest.onBeforeRequest((details, callback) => {
    const u = details.url;
    if (u.startsWith('data:') || u.startsWith('blob:') || u.startsWith('devtools:') || u === 'about:blank') {
      return callback({ cancel: false });
    }
    // Sondeos de extensiones y píxeles publicitarios: se bloquean en silencio para no ensuciar la consola
    if (isSilentlyBlocked(u)) {
      return callback({ cancel: true });
    }
    const check = isSubresourceAllowed(u, false);
    if (!check.allowed || check.channel !== 'linkedin') {
      console.warn(`[DomainGuard LI] Petición bloqueada a dominio no autorizado: ${u}`);
      return callback({ cancel: true });
    }
    callback({ cancel: false });
  });
  liSession.cookies.on('changed', (event, cookie, cause, removed) => {
    if (cookie.name === 'li_at' && !removed) {
      console.log('[Electron Sesion] ¡Cookie de autenticación li_at guardada! Sesión de LinkedIn activa.');
    }
  });

  // 2. Partición WhatsApp
  const waSession = session.fromPartition(WA_PARTITION_NAME);
  waSession.setUserAgent(cleanUserAgent);
  waSession.webRequest.onBeforeRequest((details, callback) => {
    const u = details.url;
    if (u.startsWith('data:') || u.startsWith('blob:') || u.startsWith('devtools:') || u === 'about:blank') {
      return callback({ cancel: false });
    }
    if (isSilentlyBlocked(u)) {
      return callback({ cancel: true });
    }
    const check = isSubresourceAllowed(u, false);
    if (!check.allowed || check.channel !== 'whatsapp') {
      console.warn(`[DomainGuard WA] Petición bloqueada a dominio no autorizado: ${u}`);
      return callback({ cancel: true });
    }
    callback({ cancel: false });
  });
  waSession.cookies.on('changed', (event, cookie, cause, removed) => {
    if (cookie.domain && cookie.domain.includes('whatsapp.com') && !removed) {
      cachedWhatsAppSession = true;
    }
  });

  // 3. Partición Zoho Bridge (aislada y transitoria)
  const zohoSession = session.fromPartition(ZOHO_PARTITION_NAME);
  zohoSession.setUserAgent(cleanUserAgent);
  zohoSession.webRequest.onBeforeRequest((details, callback) => {
    const u = details.url;
    if (u.includes('MetaCachingSW') || isSilentlyBlocked(u)) {
      return callback({ cancel: true });
    }
    if (u.startsWith('data:') || u.startsWith('blob:') || u.startsWith('devtools:') || u === 'about:blank') {
      return callback({ cancel: false });
    }
    const check = isSubresourceAllowed(u, true);
    if (!check.allowed || check.channel !== 'zoho') {
      console.warn(`[DomainGuard Zoho] Petición bloqueada a dominio no autorizado: ${u}`);
      return callback({ cancel: true });
    }
    callback({ cancel: false });
  });
  zohoSession.clearStorageData({ storages: ['serviceworkers', 'cachestorage'] }).catch(() => {});
  zohoSession.cookies.on('changed', (event, cookie, cause, removed) => {
    if (cookie.domain && cookie.domain.includes('zoho.com') && !removed) {
      if (cookie.name === 'CSRF_TOKEN' || cookie.name === 'crmcsr') {
        console.log('[Electron Sesion] ¡Cookie de Zoho CRM detectada! Sesión activa.');
      }
    }
  });
}

/**
 * Crea o retorna la ventana de LinkedIn en Chromium con sesión aislada.
 */
function getOrCreateLinkedInWindow(shouldShow = false) {
  if (linkedInWindow && !linkedInWindow.isDestroyed()) {
    if (shouldShow && !linkedInWindow.isVisible()) {
      linkedInWindow.show();
      linkedInWindow.focus();
    } else if (shouldShow) {
      linkedInWindow.focus();
    }
    return linkedInWindow;
  }

  const liSession = session.fromPartition(LI_PARTITION_NAME);
  const cleanUserAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36';
  liSession.setUserAgent(cleanUserAgent);

  linkedInWindow = new BrowserWindow({
    width: 1200,
    height: 850,
    title: 'NexusReach Pro - LinkedIn Aislado',
    show: shouldShow,
    autoHideMenuBar: true,
    webPreferences: {
      session: liSession,
      contextIsolation: false,
      nodeIntegration: false,
      sandbox: false,
      webSecurity: true
    }
  });

  linkedInWindow.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault();
      linkedInWindow.hide();
    }
  });

  linkedInWindow.webContents.on('dom-ready', () => {
    linkedInWindow.webContents.executeJavaScript(STEALTH_INJECTION_SCRIPT).catch(() => {});
  });

  linkedInWindow.webContents.on('did-finish-load', () => {
    linkedInWindow.webContents.executeJavaScript(STEALTH_INJECTION_SCRIPT).catch(() => {});
  });

  return linkedInWindow;
}

/**
 * Crea o retorna la ventana de WhatsApp Web en Chromium con sesión aislada.
 */
function getOrCreateWhatsAppWindow(shouldShow = false) {
  if (whatsAppWindow && !whatsAppWindow.isDestroyed()) {
    if (shouldShow && !whatsAppWindow.isVisible()) {
      whatsAppWindow.show();
      whatsAppWindow.focus();
    } else if (shouldShow) {
      whatsAppWindow.focus();
    }
    return whatsAppWindow;
  }

  const waSession = session.fromPartition(WA_PARTITION_NAME);
  const cleanUserAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36';
  waSession.setUserAgent(cleanUserAgent);

  whatsAppWindow = new BrowserWindow({
    width: 1100,
    height: 850,
    title: 'NexusReach Pro - WhatsApp Web Aislado',
    show: shouldShow,
    autoHideMenuBar: true,
    webPreferences: {
      session: waSession,
      contextIsolation: false,
      nodeIntegration: false,
      sandbox: false,
      webSecurity: true
    }
  });

  whatsAppWindow.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault();
      whatsAppWindow.hide();
    }
  });

  whatsAppWindow.webContents.on('dom-ready', () => {
    whatsAppWindow.webContents.executeJavaScript(STEALTH_INJECTION_SCRIPT).catch(() => {});
  });

  whatsAppWindow.webContents.on('did-finish-load', () => {
    whatsAppWindow.webContents.executeJavaScript(STEALTH_INJECTION_SCRIPT).catch(() => {});
    const u = whatsAppWindow.webContents.getURL();
    if (u.includes('web.whatsapp.com')) {
      checkWhatsAppWebSession(whatsAppWindow).then((isAuth) => {
        if (isAuth) console.log('[Electron Sesion] ¡Sesión de WhatsApp Web detectada y activa!');
      });
    }
  });

  // Si recién se crea, cargar automáticamente WhatsApp Web
  const currentUrl = whatsAppWindow.webContents.getURL();
  if (!currentUrl || currentUrl === 'about:blank') {
    whatsAppWindow.loadURL('https://web.whatsapp.com').catch(() => {});
  }

  return whatsAppWindow;
}

/**
 * Crea o retorna la ventana de Zoho CRM en Chromium con sesión aislada y persistente.
 */
function getOrCreateZohoWindow(shouldShow = false) {
  if (zohoWindow && !zohoWindow.isDestroyed()) {
    if (shouldShow && !zohoWindow.isVisible()) {
      zohoWindow.show();
      zohoWindow.focus();
    } else if (shouldShow) {
      zohoWindow.focus();
    }
    return zohoWindow;
  }

  const zohoSession = session.fromPartition(ZOHO_PARTITION_NAME);
  const cleanUserAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36';
  zohoSession.setUserAgent(cleanUserAgent);

  zohoWindow = new BrowserWindow({
    width: 1280,
    height: 900,
    title: 'NexusReach Pro - Zoho CRM Aislado',
    show: shouldShow,
    autoHideMenuBar: true,
    webPreferences: {
      session: zohoSession,
      preload: path.join(__dirname, 'zoho_preload.cjs'),
      contextIsolation: false,
      nodeIntegration: false,
      sandbox: false,
      webSecurity: true
    }
  });

  zohoWindow.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault();
      zohoWindow.hide();
    }
  });

  zohoWindow.webContents.on('before-input-event', (event, input) => {
    if (input.key === 'F5' || (input.control && input.key.toLowerCase() === 'r')) {
      zohoWindow.reload();
    }
    if (input.control && input.shift && input.key.toLowerCase() === 'i') {
      zohoWindow.webContents.toggleDevTools();
    }
  });

  zohoWindow.webContents.on('console-message', (event, level, message, line, sourceId) => {
    zohoConsoleLogs.push({ level, message, line, sourceId });
    if (zohoConsoleLogs.length > 50) zohoConsoleLogs.shift();
  });

  const currentUrl = zohoWindow.webContents.getURL();
  if (!currentUrl || currentUrl === 'about:blank') {
    zohoSession.cookies.get({ domain: '.zoho.com' }).then((cookies) => {
      const hasCrmCsr = cookies.some((c) => c.name === 'crmcsr');
      const initialUrl = hasCrmCsr
        ? 'https://crm.zoho.com/crm/org902879914/tab/Home'
        : 'https://accounts.zoho.com/signin?servicename=ZohoCRM';
      if (zohoWindow && !zohoWindow.isDestroyed()) {
        zohoWindow.loadURL(initialUrl).catch(() => {});
      }
    }).catch(() => {
      if (zohoWindow && !zohoWindow.isDestroyed()) {
        zohoWindow.loadURL('https://accounts.zoho.com/signin?servicename=ZohoCRM').catch(() => {});
      }
    });
  }

  return zohoWindow;
}

/**
 * Router para obtener o crear la ventana de trabajo correspondiente según canal o URL.
 */
function getOrCreateWorkWindow(shouldShow = false, channel = null, url = null) {
  const isZoho = (channel && channel.toLowerCase().includes('zoho')) || 
                 (url && url.toLowerCase().includes('zoho'));
  if (isZoho) {
    return getOrCreateZohoWindow(shouldShow);
  }
  const isWA = (channel && channel.toLowerCase().includes('whatsapp')) || 
               (url && url.toLowerCase().includes('whatsapp'));
  if (isWA) {
    return getOrCreateWhatsAppWindow(shouldShow);
  }
  return getOrCreateLinkedInWindow(shouldShow);
}

/**
 * Pantalla de contingencia / reconexión cuando no es posible cargar la interfaz.
 */
function showConnectionErrorScreen(win, errorDetails) {
  if (!win || win.isDestroyed()) return;
  const safeError = String(errorDetails || 'No se pudo cargar la interfaz de usuario').replace(/[<>&"']/g, '');
  const errorHtml = `
    <!DOCTYPE html>
    <html lang="es" style="background:#090A0C;color:#f4f4f5;font-family:system-ui,-apple-system,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;">
    <head><meta charset="utf-8"><title>NexusReach Pro | Estado de Conexión</title></head>
    <body style="text-align:center;max-width:480px;padding:32px;">
      <div style="font-size:42px;margin-bottom:16px;">⚡</div>
      <h2 style="font-size:18px;font-weight:600;margin:0 0 8px;color:#fff;">NexusReach Pro</h2>
      <p style="font-size:13px;color:#a1a1aa;line-height:1.6;margin:0 0 20px;">
        No fue posible iniciar la interfaz de la aplicación.<br>
        <span style="font-size:11px;color:#71717a;">${safeError}</span>
      </p>
      <button onclick="window.location.reload()" style="background:#fff;color:#090A0C;border:none;padding:8px 20px;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;transition:opacity 0.2s;">
        Reintentar
      </button>
    </body>
    </html>
  `;
  win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(errorHtml)}`);
}

/**
 * Resuelve y carga la interfaz de usuario en mainWindow:
 * 1. Prioridad comercial: Carga la UI compilada de React localmente (dist-ui/index.html o static/dist/index.html).
 * 2. Si se especifica APP_URL o modo --dev, usa la URL remota / servidor Vite de desarrollo.
 * 3. Fallback: servidor FastAPI local http://127.0.0.1:8000/.
 */
function loadAppUi(win) {
  const isDevArg = process.argv.includes('--dev');
  const envAppUrl = process.env.APP_URL;

  if (envAppUrl || isDevArg) {
    const targetUrl = envAppUrl || 'http://localhost:5173';
    console.log(`[Electron UI] Modo desarrollo / URL externa activa: ${targetUrl}`);
    win.loadURL(targetUrl).catch((err) => {
      console.warn(`[Electron UI] Error cargando URL (${targetUrl}), intentando fallback local:`, err.message);
      loadLocalUi(win);
    });
    return;
  }

  loadLocalUi(win);
}

function loadLocalUi(win) {
  const candidatePaths = [
    path.join(__dirname, 'dist-ui', 'index.html'),
    path.join(__dirname, '..', 'static', 'dist', 'index.html'),
    path.join(app.getAppPath(), 'dist-ui', 'index.html'),
    path.join(app.getAppPath(), 'static', 'dist', 'index.html')
  ];

  let localIndexPath = null;
  for (const candidate of candidatePaths) {
    if (fs.existsSync(candidate)) {
      localIndexPath = candidate;
      break;
    }
  }

  if (localIndexPath) {
    console.log(`[Electron UI] Cargando interfaz React local desde: ${localIndexPath}`);
    win.loadFile(localIndexPath).catch((err) => {
      console.error(`[Electron UI] Error cargando archivo local (${localIndexPath}):`, err.message);
      showConnectionErrorScreen(win, err.message);
    });
  } else {
    const fallbackUrl = 'http://127.0.0.1:8000/';
    console.log(`[Electron UI] No se detectó build local en disco. Intentando servidor FastAPI: ${fallbackUrl}`);
    win.loadURL(fallbackUrl).catch((err) => {
      console.error(`[Electron UI] Fallback a servidor falló (${fallbackUrl}):`, err.message);
      showConnectionErrorScreen(win, `No se encontró la interfaz compilada local ni un backend activo en ${fallbackUrl}`);
    });
  }
}

/**
 * Crea la ventana principal del Dashboard de la aplicación.
 */
function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    title: 'NexusReach Pro | Suite de Prospección B2B',
    autoHideMenuBar: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.cjs')
    }
  });

  loadAppUi(mainWindow);

  mainWindow.on('closed', () => {
    mainWindow = null;
    app.isQuitting = true;
    if (linkedInWindow && !linkedInWindow.isDestroyed()) {
      linkedInWindow.destroy();
    }
    if (whatsAppWindow && !whatsAppWindow.isDestroyed()) {
      whatsAppWindow.destroy();
    }
    if (zohoWindow && !zohoWindow.isDestroyed()) {
      zohoWindow.destroy();
    }
    app.quit();
  });
}

/**
 * Servidor HTTP interno de automatización (puerto 9099).
 * Permite que el motor en Python ordene acciones de navegación, evaluación y clics.
 */
function startInternalServer() {
  const server = http.createServer(async (req, res) => {
    // Permitir CORS local
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
      res.writeHead(200);
      res.end();
      return;
    }

    const sendJson = (statusCode, data) => {
      res.writeHead(statusCode, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(data));
    };

    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', async () => {
      let parsed = {};
      try {
        if (body) parsed = JSON.parse(body);
      } catch (err) {
        // Ignorar error de parsing si no hay cuerpo JSON
      }

      const urlPath = req.url.split('?')[0];

      try {
        // 1. Estado del navegador embebido
        if (urlPath === '/status' && req.method === 'GET') {
          const liWin = getOrCreateLinkedInWindow(false);
          const waWin = getOrCreateWhatsAppWindow(false);
          const zoWin = zohoWindow && !zohoWindow.isDestroyed() ? zohoWindow : null;
          const liUrl = liWin ? liWin.webContents.getURL() : '';
          const waUrl = waWin ? waWin.webContents.getURL() : '';
          const zoUrl = zoWin ? zoWin.webContents.getURL() : '';
          const cookies = await session.fromPartition(LI_PARTITION_NAME).cookies.get({ domain: '.linkedin.com' });
          const hasLiAt = cookies.some((c) => c.name === 'li_at');

          const zohoCookies = await session.fromPartition(ZOHO_PARTITION_NAME).cookies.get({ domain: '.zoho.com' });
          const hasZoho = zohoCookies.some((c) => c.name === 'crmcsr');

          // Verificación de sesión de WhatsApp Web en el Chromium aislado
          let hasWhatsApp = cachedWhatsAppSession;
          if (!hasWhatsApp) {
            try {
              const partitionDir = 'nexusreach_wa_session';
              const waDbPath = path.join(app.getPath('userData'), 'Partitions', partitionDir, 'IndexedDB', 'https_web.whatsapp.com_0.indexeddb.leveldb');
              if (fs.existsSync(waDbPath)) {
                const entries = fs.readdirSync(waDbPath);
                if (entries.some((f) => f.endsWith('.ldb') || (f.startsWith('MANIFEST') && entries.length > 2))) {
                  hasWhatsApp = true;
                  cachedWhatsAppSession = true;
                }
              }
            } catch (e) {}
          }

          if (!hasWhatsApp && waWin && !waWin.isDestroyed()) {
            const isAuth = await checkWhatsAppWebSession(waWin);
            if (isAuth) hasWhatsApp = true;
          }

          return sendJson(200, {
            ok: true,
            running: true,
            active: true,
            tipo: 'ELECTRON_CHROMIUM_ISOLATED',
            url: liUrl || waUrl || zoUrl,
            linkedin_url: liUrl,
            whatsapp_url: waUrl,
            zoho_url: zoUrl,
            sesion_linkedin_activa: hasLiAt,
            sesion_whatsapp_activa: hasWhatsApp,
            sesion_zoho_activa: hasZoho,
            total_cookies_guardadas: cookies.length + zohoCookies.length,
            visible: Boolean((liWin && liWin.isVisible()) || (waWin && waWin.isVisible()) || (zoWin && zoWin.isVisible())),
            linkedin_visible: Boolean(liWin && liWin.isVisible()),
            whatsapp_visible: Boolean(waWin && waWin.isVisible()),
            zoho_visible: Boolean(zoWin && zoWin.isVisible())
          });
        }

        // 2. Navegar a una URL (validada por Allowlist DomainGuard)
        if (urlPath === '/navigate' && req.method === 'POST') {
          const targetUrl = parsed.url;
          if (!targetUrl) return sendJson(400, { ok: false, error: 'Falta parametro url' });

          const allowZoho = Boolean(parsed.allow_zoho || targetUrl.includes('zoho'));
          const check = isUrlAllowed(targetUrl, allowZoho);
          if (!check.allowed) {
            return sendJson(403, { ok: false, error: `Navegación bloqueada por Allowlist Guard: ${check.reason}` });
          }

          const channel = parsed.channel || check.channel || 'linkedin';
          const win = getOrCreateWorkWindow(false, channel, targetUrl);
          await new Promise((resolve) => {
            const timeout = setTimeout(() => resolve(), 12000); // 12s max
            win.webContents.once('did-finish-load', () => {
              clearTimeout(timeout);
              resolve();
            });
            win.loadURL(targetUrl).catch(() => {
              clearTimeout(timeout);
              resolve();
            });
          });

          return sendJson(200, {
            ok: true,
            channel: channel,
            url: win.webContents.getURL(),
            title: win.webContents.getTitle()
          });
        }

        // 3. Bloqueo de Evaluación Remota Arbitraria (C-01 Directrices v1.3)
        if (urlPath === '/evaluate' && req.method === 'POST') {
          return sendJson(403, {
            ok: false,
            error: 'ACCESO_DENEGADO (C-01): La evaluación remota arbitraria de JavaScript (/evaluate) ha sido revocada permanentemente. Utilice comandos firmados Ed25519 con funciones precompiladas locales.'
          });
        }

        // 4. Mostrar el navegador de trabajo (LinkedIn, WhatsApp Web o Zoho CRM)
        if (urlPath === '/show' && req.method === 'POST') {
          const channel = parsed.channel || (parsed.url && parsed.url.includes('zoho') ? 'zoho' : parsed.url && parsed.url.includes('whatsapp') ? 'whatsapp' : 'linkedin');

          if (channel === 'zoho') {
            const win = getOrCreateZohoWindow(true);
            const zohoCookies = await session.fromPartition(ZOHO_PARTITION_NAME).cookies.get({ domain: '.zoho.com' });
            const hasZoho = zohoCookies.some((c) => c.name === 'crmcsr');
            const currentUrl = win.webContents.getURL() || '';
            const isStuckOnSplash = currentUrl.includes('ShowHomePage.do') || (currentUrl.includes('crm.zoho.com') && !hasZoho);

            let targetUrl = parsed.url;
            if (!targetUrl) {
              if (hasZoho) {
                targetUrl = 'https://crm.zoho.com/crm/org902879914/tab/Home';
              } else {
                targetUrl = 'https://accounts.zoho.com/signin?servicename=ZohoCRM';
              }
            } else if (targetUrl.includes('crm.zoho.com') && !hasZoho) {
              // Si se solicitó CRM pero no hay sesión activa, abrir la pantalla oficial de login para evitar el bucle de "Cargando"
              targetUrl = 'https://accounts.zoho.com/signin?servicename=ZohoCRM';
            }

            if (targetUrl && (currentUrl !== targetUrl || isStuckOnSplash)) {
              win.loadURL(targetUrl).catch(() => {});
            }
            win.show();
            win.focus();
            return sendJson(200, {
              ok: true,
              channel: 'zoho',
              visible: true,
              url: win.webContents.getURL(),
              sesion_zoho_activa: hasZoho
            });
          } else if (channel === 'whatsapp') {
            const win = getOrCreateWhatsAppWindow(true);
            if (parsed.url) {
              win.loadURL(parsed.url).catch(() => {});
            } else {
              const currentUrl = win.webContents.getURL();
              if (!currentUrl || currentUrl === 'about:blank') {
                win.loadURL('https://web.whatsapp.com').catch(() => {});
              }
            }
            win.show();
            win.focus();
            return sendJson(200, {
              ok: true,
              channel: 'whatsapp',
              visible: true,
              url: win.webContents.getURL(),
              sesion_whatsapp_activa: cachedWhatsAppSession
            });
          } else {
            const win = getOrCreateLinkedInWindow(true);
            const cookies = await session.fromPartition(LI_PARTITION_NAME).cookies.get({ domain: '.linkedin.com' });
            const hasLiAt = cookies.some((c) => c.name === 'li_at');

            const targetUrl = parsed.url || (!hasLiAt ? 'https://www.linkedin.com/login' : null);
            if (targetUrl) {
              win.loadURL(targetUrl).catch(() => {});
            } else {
              const currentUrl = win.webContents.getURL();
              if (!currentUrl || currentUrl === 'about:blank') {
                win.loadURL('https://www.linkedin.com/feed/').catch(() => {});
              }
            }

            win.show();
            win.focus();
            return sendJson(200, {
              ok: true,
              channel: 'linkedin',
              visible: true,
              url: win.webContents.getURL(),
              sesion_linkedin_activa: hasLiAt,
              sesion_whatsapp_activa: cachedWhatsAppSession
            });
          }
        }

        // 5. Ocultar el navegador de trabajo
        if (urlPath === '/hide' && req.method === 'POST') {
          const channel = parsed.channel;
          if (!channel || channel === 'linkedin') {
            if (linkedInWindow && !linkedInWindow.isDestroyed()) linkedInWindow.hide();
          }
          if (!channel || channel === 'whatsapp') {
            if (whatsAppWindow && !whatsAppWindow.isDestroyed()) whatsAppWindow.hide();
          }
          if (!channel || channel === 'zoho') {
            if (zohoWindow && !zohoWindow.isDestroyed()) zohoWindow.hide();
          }
          return sendJson(200, { ok: true, visible: false });
        }

        // 5.1 Cerrar sesión y purgar cookies/caché de Zoho CRM
        if (urlPath === '/zoho/logout' && req.method === 'POST') {
          try {
            const zohoSession = session.fromPartition(ZOHO_PARTITION_NAME);
            const zohoCookies = await zohoSession.cookies.get({ domain: '.zoho.com' });
            for (const cookie of zohoCookies) {
              const prefix = cookie.secure ? 'https://' : 'http://';
              const domain = cookie.domain.replace(/^\./, '');
              const cookieUrl = `${prefix}${domain}${cookie.path}`;
              await zohoSession.cookies.remove(cookieUrl, cookie.name).catch(() => {});
            }

            await zohoSession.clearStorageData({
              origins: ['https://accounts.zoho.com', 'https://crm.zoho.com', 'https://zoho.com'],
              storages: ['cookies', 'localstorage', 'indexdb', 'serviceworkers', 'cachestorage']
            }).catch(() => {});

            const win = getOrCreateZohoWindow(true);
            await win.loadURL('https://accounts.zoho.com/logout').catch(() => {});
            await win.loadURL('https://accounts.zoho.com/signin?servicename=ZohoCRM').catch(() => {});
            win.show();
            win.focus();

            return sendJson(200, {
              ok: true,
              mensaje: 'Sesión de Zoho purgada exitosamente. Ventana reiniciada en pantalla de login.',
              sesion_zoho_activa: false,
              url: win.webContents.getURL()
            });
          } catch (logoutErr) {
            console.error('[Zoho Logout Error]:', logoutErr.message);
            return sendJson(500, { ok: false, error: logoutErr.message });
          }
        }

        // 5.2 Reiniciar la aplicación de Electron en caliente
        if (urlPath === '/restart' && req.method === 'POST') {
          app.relaunch();
          app.exit(0);
          return sendJson(200, { ok: true, mensaje: 'Reiniciando aplicación de escritorio...' });
        }

        // 6. Clic biométrico nativo por coordenadas
        if (urlPath === '/click' && req.method === 'POST') {
          const { x, y } = parsed;
          const channel = parsed.channel || 'linkedin';
          const win = getOrCreateWorkWindow(false, channel);
          if (typeof x === 'number' && typeof y === 'number') {
            win.webContents.sendInputEvent({ type: 'mouseMove', x, y });
            await new Promise((r) => setTimeout(r, 60));
            win.webContents.sendInputEvent({ type: 'mouseDown', x, y, button: 'left', clickCount: 1 });
            await new Promise((r) => setTimeout(r, 90));
            win.webContents.sendInputEvent({ type: 'mouseUp', x, y, button: 'left', clickCount: 1 });
            return sendJson(200, { ok: true, clicked: { x, y } });
          }
          return sendJson(400, { ok: false, error: 'Parametros x e y numericos requeridos' });
        }

        // 7. Control del Piloto Automático del Runner
        if (urlPath === '/worker/start' && req.method === 'POST') {
          const authOpts = {
            sessionToken: parsed.session_token || parsed.sessionToken || null,
            tenantId: parsed.tenant_id || parsed.tenantId || null
          };
          workerRunner.startWorker(getOrCreateWorkWindow, (authOpts.sessionToken || authOpts.tenantId) ? authOpts : null);
          return sendJson(200, { ok: true, status: workerRunner.getStatus() });
        }

        if (urlPath === '/worker/stop' && req.method === 'POST') {
          workerRunner.stopWorker();
          return sendJson(200, { ok: true, status: workerRunner.getStatus() });
        }

        if (urlPath === '/worker/session' && req.method === 'POST') {
          workerRunner.setAuthSession({
            sessionToken: parsed.session_token || parsed.sessionToken || null,
            tenantId: parsed.tenant_id || parsed.tenantId || null
          });
          return sendJson(200, { ok: true, status: workerRunner.getStatus() });
        }

        if (urlPath === '/worker/logout' && req.method === 'POST') {
          workerRunner.clearAuthSession('Sesión cerrada por el usuario.');
          return sendJson(200, { ok: true, status: workerRunner.getStatus() });
        }

        if (urlPath === '/worker/status' && req.method === 'GET') {
          return sendJson(200, { ok: true, status: workerRunner.getStatus() });
        }

        if (urlPath === '/worker/forzar-siguiente' && req.method === 'POST') {
          const authOpts = {
            sessionToken: parsed.session_token || parsed.sessionToken || null,
            tenantId: parsed.tenant_id || parsed.tenantId || null
          };
          const res = workerRunner.forceNextCycle(
            getOrCreateWorkWindow,
            (authOpts.sessionToken || authOpts.tenantId) ? authOpts : null
          );
          return sendJson(200, { ok: true, resultado: res, status: workerRunner.getStatus() });
        }

        // 8. Extracción Precompilada Segura de Red (Conexiones 1º Grado e Invitaciones)
        if (urlPath === '/extract/network' && req.method === 'POST') {
          const win = getOrCreateLinkedInWindow(false);
          const result = await handleLinkedInExtractNetwork(win, parsed);
          return sendJson(200, result);
        }

        // 9. Enriquecimiento / Extracción Precompilada Segura de Perfil en Vivo
        if (urlPath === '/extract/profile' && req.method === 'POST') {
          const win = getOrCreateLinkedInWindow(false);
          const result = await handleLinkedInEnrichProfile(win, parsed);
          return sendJson(200, result);
        }

        // 10. Extracción Precompilada Segura de Datos de Contacto 1º Grado (Overlay)
        if (urlPath === '/extract/contact-info' && req.method === 'POST') {
          const win = getOrCreateLinkedInWindow(false);
          const result = await handleLinkedInReadContactInfo(win, parsed);
          return sendJson(200, result);
        }

        // 11. Búsqueda y Extracción Precompilada Segura de Personas en LinkedIn
        if (urlPath === '/extract/search' && req.method === 'POST') {
          const win = getOrCreateLinkedInWindow(false);
          const result = await handleLinkedInSearchPeople(win, parsed);
          return sendJson(200, result);
        }

        return sendJson(404, { ok: false, error: 'Endpoint no encontrado' });
      } catch (err) {
        return sendJson(500, { ok: false, error: err.message });
      }
    });
  });

  server.listen(INTERNAL_PORT, '127.0.0.1', () => {
    console.log(`[Electron Core] Servidor interno de Chromium aislado activo en http://127.0.0.1:${INTERNAL_PORT}`);
  });
}

/**
 * Registra los manejadores IPC seguros para comunicación con React (vía preload.cjs).
 * Fase 2 / Tarea 1: Desacopla la sesión del worker de la URL de navegación.
 */
function setupIpcHandlers() {
  // 1. Obtener la URL base del backend centralizado
  ipcMain.handle('nexus:get-api-url', () => {
    return process.env.API_BASE_URL || process.env.APP_URL || 'http://127.0.0.1:8000';
  });

  // 2. Establecer sesión autenticada desde React (Login)
  ipcMain.handle('nexus:set-auth-session', async (_event, sessionData) => {
    if (!sessionData || typeof sessionData !== 'object') {
      return { ok: false, error: 'Datos de sesión inválidos' };
    }
    const token = typeof sessionData.sessionToken === 'string' ? sessionData.sessionToken.trim() : null;
    const tenantId = typeof sessionData.tenantId === 'string' ? sessionData.tenantId.trim() : null;

    if (!token) {
      return { ok: false, error: 'Token de sesión vacío' };
    }

    workerRunner.setAuthSession({ sessionToken: token, tenantId });
    console.log(`[Electron IPC] Sesión sincronizada con worker local (Tenant: ${tenantId || 'auto'}).`);
    return { ok: true };
  });

  // 3. Limpiar sesión al hacer logout en React
  ipcMain.handle('nexus:clear-auth-session', async () => {
    workerRunner.clearAuthSession('Sesión cerrada por el usuario en la interfaz.');
    console.log('[Electron IPC] Sesión de worker invalidada tras logout.');
    return { ok: true };
  });

  // 4. Consultar estado resumido de autenticación del worker (sin exponer el token en claro)
  ipcMain.handle('nexus:get-auth-session', async () => {
    const status = workerRunner.getStatus();
    return {
      authenticated: !status.requiere_autenticacion && !status.error_autorizacion,
      tenantId: status.tenant_id,
      fase: status.fase
    };
  });

  // 5. Estado detallado del worker local
  ipcMain.handle('nexus:get-worker-status', async () => {
    return workerRunner.getStatus();
  });

  // 6. Iniciar worker desde la interfaz
  ipcMain.handle('nexus:start-worker', async (_event, opts = {}) => {
    workerRunner.startWorker(getOrCreateLinkedInWindow, (opts.sessionToken || opts.tenantId) ? opts : null);
    return workerRunner.getStatus();
  });

  // 7. Detener worker desde la interfaz
  ipcMain.handle('nexus:stop-worker', async () => {
    workerRunner.stopWorker();
    return workerRunner.getStatus();
  });
}

// Inicialización de Electron
app.whenReady().then(() => {
  setupSessionGuardsAndListeners();
  setupIpcHandlers();
  createMainWindow();

  // Proveedor seguro de sesión desde el proceso principal (solo lee el token de mainWindow si está en el origen local de la app)
  workerRunner.setSessionProvider(async () => {
    if (!mainWindow || mainWindow.isDestroyed()) return null;
    try {
      const currentUrl = mainWindow.webContents.getURL() || '';
      const isAllowedOrigin = currentUrl.startsWith('file://') ||
                              currentUrl.startsWith('http://127.0.0.1:8000') ||
                              currentUrl.startsWith('http://localhost:8000') ||
                              currentUrl.startsWith('http://localhost:5173');
      if (!isAllowedOrigin) {
        return null;
      }
      const tok = await mainWindow.webContents.executeJavaScript(
        `window.sessionStorage ? window.sessionStorage.getItem('nexus_session_token') : null`
      );
      return tok ? { sessionToken: tok } : null;
    } catch (e) {
      return null;
    }
  });

  startInternalServer();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
