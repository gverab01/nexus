const { app, BrowserWindow, session, ipcMain } = require('electron');
const path = require('path');
const http = require('http');
const workerRunner = require('./worker_runner.cjs');

let mainWindow = null;
let workWindow = null;
const INTERNAL_PORT = 9099;

// Partición persistente para aislar las sesiones (LinkedIn, Gmail, etc.)
const WORK_PARTITION_NAME = 'persist:dripify_work_session';

/**
 * Crea o retorna la ventana de trabajo en Chromium con sesión aislada.
 */
function getOrCreateWorkWindow(shouldShow = false) {
  if (workWindow && !workWindow.isDestroyed()) {
    if (shouldShow && !workWindow.isVisible()) {
      workWindow.show();
      workWindow.focus();
    }
    return workWindow;
  }

  const workSession = session.fromPartition(WORK_PARTITION_NAME);

  // Configuración de User-Agent limpio de Chromium estándar
  const cleanUserAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36';
  workSession.setUserAgent(cleanUserAgent);

  workWindow = new BrowserWindow({
    width: 1200,
    height: 850,
    title: 'NexusReach Pro - Navegador de Trabajo',
    show: shouldShow,
    autoHideMenuBar: true,
    webPreferences: {
      session: workSession,
      contextIsolation: false,
      nodeIntegration: false,
      sandbox: false,
      webSecurity: true
    }
  });

  // Si el usuario cierra manualmente la ventana de trabajo, solo la ocultamos para no perder la sesión
  workWindow.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault();
      workWindow.hide();
    }
  });

  // Monitorear cuando se inicia sesión en LinkedIn
  workSession.cookies.on('changed', (event, cookie, cause, removed) => {
    if (cookie.name === 'li_at' && !removed) {
      console.log('[Electron Sesion] ¡Cookie de autenticación li_at guardada! Sesión de LinkedIn activa.');
    }
  });

  return workWindow;
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
      contextIsolation: true
    }
  });

  const appUrl = process.env.APP_URL || 'http://127.0.0.1:8000/';
  mainWindow.loadURL(appUrl).catch((err) => {
    console.error(`Error cargando URL principal (${appUrl}):`, err.message);
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
    app.isQuitting = true;
    if (workWindow && !workWindow.isDestroyed()) {
      workWindow.destroy();
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
          const win = getOrCreateWorkWindow(false);
          const currentUrl = win ? win.webContents.getURL() : '';
          const cookies = await session.fromPartition(WORK_PARTITION_NAME).cookies.get({ domain: '.linkedin.com' });
          const hasLiAt = cookies.some((c) => c.name === 'li_at');

          return sendJson(200, {
            ok: true,
            running: true,
            active: true,
            tipo: 'ELECTRON_CHROMIUM_ISOLATED',
            url: currentUrl,
            sesion_linkedin_activa: hasLiAt,
            total_cookies_guardadas: cookies.length,
            visible: win ? win.isVisible() : false
          });
        }

        // 2. Navegar a una URL
        if (urlPath === '/navigate' && req.method === 'POST') {
          const targetUrl = parsed.url;
          if (!targetUrl) return sendJson(400, { ok: false, error: 'Falta parametro url' });

          const win = getOrCreateWorkWindow(false);
          await new Promise((resolve, reject) => {
            const timeout = setTimeout(() => resolve(), 12000); // 12s max
            win.webContents.once('did-finish-load', () => {
              clearTimeout(timeout);
              resolve();
            });
            win.loadURL(targetUrl).catch((err) => {
              clearTimeout(timeout);
              resolve();
            });
          });

          return sendJson(200, {
            ok: true,
            url: win.webContents.getURL(),
            title: win.webContents.getTitle()
          });
        }

        // 3. Evaluar JavaScript en el navegador de trabajo
        if (urlPath === '/evaluate' && req.method === 'POST') {
          const script = parsed.script || parsed.code;
          if (!script) return sendJson(400, { ok: false, error: 'Falta parametro script' });

          const win = getOrCreateWorkWindow(false);
          try {
            // Si el script viene como función o IIFE
            let executable = script.trim();
            if (executable.startsWith('(') && executable.endsWith(')')) {
              // ya envuelto
            } else if (executable.startsWith('()') || executable.startsWith('function')) {
              executable = `(${executable})()`;
            }

            const result = await win.webContents.executeJavaScript(executable);
            return sendJson(200, { ok: true, result });
          } catch (evalErr) {
            console.warn('[Evaluate Warning]:', evalErr.message);
            return sendJson(200, { ok: false, error: evalErr.message });
          }
        }

        // 4. Mostrar el navegador de trabajo (para que el usuario inicie sesión)
        if (urlPath === '/show' && req.method === 'POST') {
          const win = getOrCreateWorkWindow(true);
          const cookies = await session.fromPartition(WORK_PARTITION_NAME).cookies.get({ domain: '.linkedin.com' });
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
            visible: true,
            url: win.webContents.getURL(),
            sesion_linkedin_activa: hasLiAt
          });
        }

        // 5. Ocultar el navegador de trabajo
        if (urlPath === '/hide' && req.method === 'POST') {
          if (workWindow && !workWindow.isDestroyed()) {
            workWindow.hide();
          }
          return sendJson(200, { ok: true, visible: false });
        }

        // 6. Clic biométrico nativo por coordenadas
        if (urlPath === '/click' && req.method === 'POST') {
          const { x, y } = parsed;
          const win = getOrCreateWorkWindow(false);
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
          workerRunner.startWorker(getOrCreateWorkWindow);
          return sendJson(200, { ok: true, status: workerRunner.getStatus() });
        }

        if (urlPath === '/worker/stop' && req.method === 'POST') {
          workerRunner.stopWorker();
          return sendJson(200, { ok: true, status: workerRunner.getStatus() });
        }

        if (urlPath === '/worker/status' && req.method === 'GET') {
          return sendJson(200, { ok: true, status: workerRunner.getStatus() });
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

// Inicialización de Electron
app.whenReady().then(() => {
  createMainWindow();
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
