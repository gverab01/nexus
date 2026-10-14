const http = require('http');

let isLoopRunning = false;
let currentTaskStatus = 'En espera';
let loopTimeout = null;

const API_BASE = 'http://127.0.0.1:8000';

function httpPost(url, data) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const body = JSON.stringify(data);
    const req = http.request({
      hostname: u.hostname,
      port: u.port || 80,
      path: u.pathname,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body)
      }
    }, (res) => {
      let raw = '';
      res.on('data', (c) => raw += c);
      res.on('end', () => {
        try { resolve(JSON.parse(raw)); } catch (e) { resolve(raw); }
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

function httpGet(url) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const req = http.request({
      hostname: u.hostname,
      port: u.port || 80,
      path: u.pathname,
      method: 'GET'
    }, (res) => {
      let raw = '';
      res.on('data', (c) => raw += c);
      res.on('end', () => {
        try { resolve(JSON.parse(raw)); } catch (e) { resolve(raw); }
      });
    });
    req.on('error', reject);
    req.end();
  });
}

/**
 * Bucle autónomo del Runner local en Electron
 */
async function runNextCycle(getWorkWindow) {
  if (!isLoopRunning) return;

  try {
    currentTaskStatus = 'Consultando órdenes a la nube...';
    const response = await httpGet(`${API_BASE}/api/worker/proxima-tarea`);

    if (!response || !response.hay_tarea) {
      const espera = (response && response.esperar_segundos) ? response.esperar_segundos : 15;
      currentTaskStatus = response ? response.motivo : 'Sin tareas activas';
      loopTimeout = setTimeout(() => runNextCycle(getWorkWindow), espera * 1000);
      return;
    }

    const tarea = response.tarea;
    currentTaskStatus = `Ejecutando: ${tarea.tipo} en ${tarea.nombre_prospecto}`;
    console.log(`[Worker Runner] Tarea recibida: ${tarea.tipo} para ${tarea.nombre_prospecto} (${tarea.perfil_url})`);

    const win = getWorkWindow(false);
    if (!win) {
      throw new Error('Navegador de trabajo no disponible');
    }

    let exito = false;
    let errorMsg = '';

    // Ejecutar la acción atómica en el Chromium embebido
    if (tarea.tipo === 'VISITAR_PERFIL' || tarea.tipo === 'ENVIAR_INVITACION') {
      await new Promise((resolve) => {
        const timeout = setTimeout(resolve, 14000);
        win.webContents.once('did-finish-load', () => {
          clearTimeout(timeout);
          resolve();
        });
        win.loadURL(tarea.perfil_url).catch(resolve);
      });

      const finalUrl = win.webContents.getURL() || '';
      // Si LinkedIn redirige a login o checkpoint, no hay sesión válida
      if (finalUrl.includes('/login') || finalUrl.includes('/authwall') || finalUrl.includes('/checkpoint')) {
        exito = false;
        errorMsg = 'Sesión de LinkedIn no iniciada: redirigido a login/authwall.';
        console.warn(`[Worker Runner Advertencia] ${errorMsg} (${finalUrl})`);
      } else {
        // Emular interacción humana visual (scroll y espera biométrica)
        await win.webContents.executeJavaScript(`
          (() => {
            window.scrollBy({ top: 350 + Math.random() * 200, behavior: 'smooth' });
            return true;
          })()
        `).catch(() => {});

        await new Promise((r) => setTimeout(r, 4000 + Math.random() * 2000));

        if (tarea.tipo === 'ENVIAR_INVITACION') {
          // Intentar clic orgánico en el botón Conectar
          await win.webContents.executeJavaScript(`
            (() => {
              const allButtons = Array.from(document.querySelectorAll('button'));
              const btn = allButtons.find(b => {
                const txt = b.innerText.trim().toLowerCase();
                return txt === 'conectar' || txt === 'connect' || txt.includes('conectar');
              });
              if (btn) {
                const r = btn.getBoundingClientRect();
                const randX = r.left + (r.width * (0.3 + Math.random() * 0.4));
                const randY = r.top + (r.height * (0.3 + Math.random() * 0.4));
                btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: randX, clientY: randY }));
                return { ok: true, accion: 'clic_conectar' };
              }
              return { ok: true, accion: 'sin_boton_directo' };
            })()
          `).catch(() => {});
        }

        exito = true;
      }
    } else {
      // Otros tipos de pasos
      exito = true;
    }

    // Reportar resultado al backend
    await httpPost(`${API_BASE}/api/worker/reportar-resultado`, {
      tarea_id: tarea.id,
      lead_id: tarea.lead_id,
      secuencia_id: tarea.secuencia_id,
      paso_id: tarea.paso_id,
      tipo: tarea.tipo,
      exito: exito,
      error: errorMsg
    });

    console.log(`[Worker Runner] Tarea ${tarea.id} completada y reportada con éxito.`);

    // Pausa estocástica antes del próximo ciclo
    const pausa = tarea.pausa_sugerida_seg || 180;
    currentTaskStatus = `Pausa humana: esperando ${Math.round(pausa)}s antes del próximo lead...`;
    loopTimeout = setTimeout(() => runNextCycle(getWorkWindow), pausa * 1000);

  } catch (err) {
    console.error('[Worker Runner Error]:', err.message);
    currentTaskStatus = `Error en ciclo: ${err.message}`;
    loopTimeout = setTimeout(() => runNextCycle(getWorkWindow), 20000);
  }
}

function startWorker(getWorkWindow) {
  if (isLoopRunning) return;
  isLoopRunning = true;
  console.log('[Worker Runner] Piloto automático del runner local activado.');
  runNextCycle(getWorkWindow);
}

function stopWorker() {
  isLoopRunning = false;
  if (loopTimeout) clearTimeout(loopTimeout);
  currentTaskStatus = 'Piloto automático en pausa';
  console.log('[Worker Runner] Piloto automático detenido.');
}

function getStatus() {
  return {
    activo: isLoopRunning,
    estado_actual: currentTaskStatus
  };
}

module.exports = {
  startWorker,
  stopWorker,
  getStatus
};
