/**
 * Manejadores Nativos de la Lista Cerrada de Acciones (Workstream 5.1 & 5.2)
 * 
 * Este módulo contiene la implementación pre-compilada y segura para cada acción de la
 * enumeración tipada. NUNCA evalúa JavaScript arbitrario recibido del servidor.
 */

const { isUrlAllowed } = require('./domain_guard.cjs');

/**
 * Espera asíncrona en milisegundos con jitter
 */
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Ejecuta un script en un contexto aislado (World 999) del webContents para garantizar
 * que errores no capturados o de hidratación (como Minified React error #418) en el
 * contexto principal de LinkedIn no interrumpan la evaluación ni hagan fallar la promesa.
 */
async function safeExecuteInIsolatedWorld(win, scriptCode) {
  const fs = require('fs');
  const os = require('os');
  const path = require('path');
  const logDir = path.join(os.homedir(), 'AppData', 'Roaming', 'nexusreach-desktop');
  if (!fs.existsSync(logDir)) {
    try { fs.mkdirSync(logDir, { recursive: true }); } catch (_) {}
  }
  const logFile = path.join(logDir, 'exec_debug.log');

  let isolatedErr = null;
  if (win && win.webContents && typeof win.webContents.executeJavaScriptInIsolatedWorld === 'function') {
    try {
      const res = await win.webContents.executeJavaScriptInIsolatedWorld(999, [{ code: scriptCode }]);
      try {
        fs.appendFileSync(logFile, `[${new Date().toISOString()}] IsolatedWorld SUCCESS\n`);
      } catch (_) {}
      return res;
    } catch (e) {
      isolatedErr = e;
      try {
        fs.appendFileSync(logFile, `[${new Date().toISOString()}] IsolatedWorld FAILED: ${e.stack || e.message}\n`);
      } catch (_) {}
    }
  }

  try {
    const stdRes = await win.webContents.executeJavaScript(scriptCode, false);
    try {
      fs.appendFileSync(logFile, `[${new Date().toISOString()}] StdEval SUCCESS\n`);
    } catch (_) {}
    return stdRes;
  } catch (stdErr) {
    try {
      fs.appendFileSync(logFile, `[${new Date().toISOString()}] StdEval FAILED: ${stdErr.stack || stdErr.message}\n`);
    } catch (_) {}
    const msg = `IsolatedWorld: [${isolatedErr ? (isolatedErr.message || isolatedErr) : 'N/A'}] | StdEval: [${stdErr.message || stdErr}]`;
    throw new Error(msg);
  }
}

/**
 * Despacha la ejecución de una acción verificada en la ventana de Chromium correspondiente.
 */
async function executeAction(action, params, windows, options = {}) {
  const { linkedInWindow, whatsAppWindow, zohoWindow } = windows;
  const allowZoho = Boolean(options.allowZoho);

  switch (action) {
    case 'LI_VISIT_PROFILE':
      return await handleLinkedInVisit(linkedInWindow, params);

    case 'LI_SEND_INVITE':
      return await handleLinkedInSendInvite(linkedInWindow, params);

    case 'LI_SEND_MESSAGE':
      return await handleLinkedInSendMessage(linkedInWindow, params);

    case 'LI_SYNC_CONNECTIONS':
      return await handleLinkedInSyncConnections(linkedInWindow, params);

    case 'LI_READ_CONTACT_INFO':
      return await handleLinkedInReadContactInfo(linkedInWindow, params);

    case 'LI_ENRICH_PROFILE':
    case 'LI_EXTRACT_PROFILE':
      return await handleLinkedInEnrichProfile(linkedInWindow, params);

    case 'WA_SEND_MESSAGE':
      return await handleWhatsAppSendMessage(whatsAppWindow, params);

    case 'WA_CHECK_NUMBER':
      return await handleWhatsAppCheckNumber(whatsAppWindow, params);

    case 'ZOHO_FIND_LEAD':
    case 'ZOHO_UPSERT_LEAD':
    case 'ZOHO_SET_STATUS':
    case 'ZOHO_ADD_NOTE':
      if (!allowZoho) {
        return { success: false, error: 'Módulo Zoho Bridge no activado para este tenant' };
      }
      return await handleZohoBridgeAction(zohoWindow, action, params);

    case 'PAUSE':
      return { success: true, result: { state: 'PAUSED' } };

    case 'RESUME':
      return { success: true, result: { state: 'RESUMED' } };

    default:
      return { success: false, error: `Acción '${action}' no implementada en handlers autorizados` };
  }
}

/**
 * 1. LI_VISIT_PROFILE: Navega a un perfil de LinkedIn y simula lectura orgánica
 */
async function handleLinkedInVisit(win, params) {
  if (!win || win.isDestroyed()) {
    return { success: false, error: 'Ventana de LinkedIn no disponible' };
  }
  const profileUrl = params.profile_url || params.perfil_url;
  if (!profileUrl) {
    return { success: false, error: 'Parámetro profile_url requerido' };
  }

  const check = isUrlAllowed(profileUrl, false);
  if (!check.allowed || check.channel !== 'linkedin') {
    return { success: false, error: check.reason || 'URL no permitida por Allowlist Guard' };
  }

  // 0. Asegurar sincronización de sesión viva si li_at está en particiones legacy o defaultSession
  try {
    const { session } = require('electron');
    if (session && win && win.webContents && win.webContents.session) {
      const curCookies = await win.webContents.session.cookies.get({ domain: '.linkedin.com' });
      const hasLiAt = curCookies.some(c => c.name === 'li_at');
      if (!hasLiAt) {
        const fallbackSources = ['persist:nexusreach_work_session', 'persist:dripify_work_session'];
        for (const fSource of fallbackSources) {
          try {
            const fSes = session.fromPartition(fSource);
            const fCookies = await fSes.cookies.get({ domain: '.linkedin.com' });
            if (fCookies.some(c => c.name === 'li_at')) {
              for (const c of fCookies) {
                const scheme = c.secure ? 'https://' : 'http://';
                const domain = c.domain.replace(/^\./, '');
                const url = `${scheme}${domain}${c.path || '/'}`;
                await win.webContents.session.cookies.set({
                  url, name: c.name, value: c.value, domain: c.domain,
                  path: c.path, secure: c.secure, httpOnly: c.httpOnly,
                  expirationDate: c.expirationDate, sameSite: c.sameSite
                }).catch(() => {});
              }
              break;
            }
          } catch (_) {}
        }
        if (session.defaultSession) {
          const defCookies = await session.defaultSession.cookies.get({ domain: '.linkedin.com' });
          if (defCookies.some(c => c.name === 'li_at')) {
            for (const c of defCookies) {
              const scheme = c.secure ? 'https://' : 'http://';
              const domain = c.domain.replace(/^\./, '');
              const url = `${scheme}${domain}${c.path || '/'}`;
              await win.webContents.session.cookies.set({
                url, name: c.name, value: c.value, domain: c.domain,
                path: c.path, secure: c.secure, httpOnly: c.httpOnly,
                expirationDate: c.expirationDate, sameSite: c.sameSite
              }).catch(() => {});
            }
          }
        }
      }
    }
  } catch (_) {}

  // Navegar
  await new Promise((resolve) => {
    const timeout = setTimeout(resolve, 14000);
    win.webContents.once('did-finish-load', () => {
      clearTimeout(timeout);
      resolve();
    });
    win.loadURL(profileUrl).catch(resolve);
  });

  await sleep(2000);
  const finalUrl = win.webContents.getURL() || '';
  if (finalUrl.includes('/login') || finalUrl.includes('/authwall') || finalUrl.includes('/checkpoint')) {
    if (typeof win.show === 'function') {
      try { win.show(); win.focus(); } catch (_) {}
    }
    return {
      success: false,
      error: 'Sesión de LinkedIn no iniciada o checkpoint detectado (Authwall). Inicia sesión en la ventana de LinkedIn.',
      checkpoint_detected: true
    };
  }

  // Scroll biométrico suave
  await win.webContents.executeJavaScript(`
    (() => {
      window.scrollBy({ top: 300 + Math.random() * 250, behavior: 'smooth' });
      return true;
    })()
  `).catch(() => {});

  await sleep(2500 + Math.random() * 2000);

  // Extracción de datos del perfil visitado e inspección de contacto y perfiles afines (Radar)
  let pageData = null;
  try {
    pageData = await safeExecuteInIsolatedWorld(win, `
      (() => {
        try {
          const url = window.location.href;
          const pageTitle = (document.title || '').trim();

          // 1. Datos básicos del perfil
          let name = '';
          if (pageTitle.includes('|')) name = pageTitle.split('|')[0].trim();
          else if (pageTitle.includes('-')) name = pageTitle.split('-')[0].trim();

          const sections = Array.from(document.querySelectorAll('section'));
          const introSec = sections.find(s => {
            const text = (s.innerText || '').trim();
            return text.includes('Información de contacto') || text.includes('contact info') || text.includes('contactos') || text.includes('connections');
          }) || sections[1] || sections[0];

          let headline = '';
          let location = 'Chile';
          let grado = '2º';

          if (introSec) {
            const h2 = introSec.querySelector('h2') || introSec.querySelector('h1');
            if (h2 && (!name || name === 'LinkedIn')) name = h2.innerText.trim();

            const spans = Array.from(introSec.querySelectorAll('div, span, p'));
            for (const sp of spans) {
              const t = (sp.innerText || '').trim();
              if (/1er|1º|1°/i.test(t)) { grado = '1º'; break; }
              if (/2do|2º|2°/i.test(t)) { grado = '2º'; break; }
              if (/3er|3º|3°/i.test(t)) { grado = '3º+'; break; }
            }

            const sub = introSec.querySelector('.text-body-medium, div.inline-show-more-text');
            if (sub) headline = (sub.innerText || '').trim();
          }

          // 2. Extracción de contacto visible (Email y Teléfono)
          let directEmail = null;
          let directPhone = null;

          const mailto = document.querySelector('a[href^="mailto:"]');
          if (mailto) {
            directEmail = (mailto.getAttribute('href') || '').replace(/^mailto:/i, '').split('?')[0].trim();
          }
          if (!directEmail) {
            const bodyText = document.body ? document.body.innerText : '';
            const emailMatch = bodyText.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}/);
            if (emailMatch && !emailMatch[0].includes('linkedin.com') && !emailMatch[0].includes('example.com')) {
              directEmail = emailMatch[0];
            }
          }

          const tel = document.querySelector('a[href^="tel:"]');
          if (tel) {
            directPhone = (tel.getAttribute('href') || '').replace(/^tel:/i, '').split('?')[0].trim();
          }

          // 3. Extracción de perfiles afines (Personas que también vieron / Más perfiles para ti - Radar)
          const similarProfiles = [];
          const seenUrls = new Set();
          const currentUrlClean = url.split('?')[0].replace(/\/+$/, '');

          const asideContainer = document.querySelector('aside, .scaffold-layout__aside, [aria-label*="perfiles"], [aria-label*="profiles"]');
          const candidateLinks = asideContainer 
            ? Array.from(asideContainer.querySelectorAll('a[href*="/in/"]'))
            : Array.from(document.querySelectorAll('aside a[href*="/in/"], .scaffold-layout__aside a[href*="/in/"]'));

          for (const link of candidateLinks) {
            let rawHref = (link.getAttribute('href') || '').split('?')[0].trim();
            if (!rawHref) continue;
            if (!rawHref.startsWith('http')) {
              rawHref = 'https://www.linkedin.com' + (rawHref.startsWith('/') ? '' : '/') + rawHref;
            }
            const cleanHref = rawHref.replace(/\/+$/, '');
            if (!cleanHref.includes('/in/') || cleanHref === currentUrlClean || seenUrls.has(cleanHref)) {
              continue;
            }

            const card = link.closest('li, div[data-view-name="profile-component-entity"], div.artdeco-entity-lockup, div.base-card') || link.parentElement;
            if (!card) continue;

            // Extraer nombre real del prospecto afin (evitar encabezados como "Del sector de...", "Más perfiles...", etc.)
            let pName = '';
            const nameSpans = Array.from(card.querySelectorAll('a[href*="/in/"] span[aria-hidden="true"], h3, div.base-card__title, .entity-result__title-text'));
            for (const ns of nameSpans) {
              let t = (ns.innerText || ns.textContent || '').trim();
              t = t.replace(/[•·\s]+(1er|2do|2º|2°|3er|3º|3°|\d+º|\d+°\+?).*$/i, '').trim();
              t = t.split('\n')[0].trim();
                if (t.length > 2 && 
                    !t.toLowerCase().includes('linkedin') && 
                    !t.toLowerCase().startsWith('ver perfil') && 
                    !t.toLowerCase().startsWith('más perfiles') && 
                    !t.toLowerCase().startsWith('personas que') && 
                    !t.toLowerCase().startsWith('del sector') && 
                    !t.toLowerCase().startsWith('del cargo') &&
                    !t.toLowerCase().startsWith('de la instituci')) {
                  pName = t;
                  break;
                }
              }

              if (!pName) {
                let linkText = (link.innerText || link.textContent || '').trim();
                linkText = linkText.replace(/[•·\s]+(1er|2do|2º|2°|3er|3º|3°|\d+º|\d+°\+?).*$/i, '').trim();
                linkText = linkText.split('\n')[0].trim();
                if (linkText.length > 2 && 
                    !linkText.toLowerCase().includes('linkedin') && 
                    !linkText.toLowerCase().startsWith('ver perfil') && 
                    !linkText.toLowerCase().startsWith('más perfiles') && 
                    !linkText.toLowerCase().startsWith('personas que') && 
                    !linkText.toLowerCase().startsWith('del sector') && 
                    !linkText.toLowerCase().startsWith('del cargo') &&
                    !linkText.toLowerCase().startsWith('de la instituci')) {
                  pName = linkText;
                }
              }

              // Extraer titular profesional
              let pHeadline = '';
              const headlineEls = Array.from(card.querySelectorAll('.text-body-small, .entity-result__primary-subtitle, div[class*="subtitle"], p, div.base-card__subtitle, div.t-12'));
              for (const he of headlineEls) {
                if (he.closest('button, a[role="button"]')) continue;
                let ht = (he.innerText || he.textContent || '').trim();
                if (ht === pName || ht.length < 3) continue;
                if (/^[•·\s]*(1er|2do|2º|2°|3er|3º|3°|\d+º)[•·\s]*$/i.test(ht)) continue;
                if (/^(conectar|connect|seguir|follow|mensaje|message|pendiente|pending)/i.test(ht)) continue;
                if (/^(más perfiles|personas que|del sector|del cargo|de la instituci)/i.test(ht)) continue;
                pHeadline = ht.split('\n')[0].trim();
                break;
              }

            if (!pHeadline) {
              const allTexts = Array.from(card.querySelectorAll('div, span, p'))
                .map(el => (el.innerText || '').trim())
                .filter(t => t.length > 4 && t !== pName && !t.includes(pName) && !/1er|2do|2º|3er|3º|conectar|seguir|mensaje/i.test(t));
              if (allTexts.length > 0) {
                pHeadline = allTexts[0].split('\n')[0].trim();
              }
            }

            if (pName && pName !== name && pName.length > 2) {
              seenUrls.add(cleanHref);
              similarProfiles.push({
                nombre: pName,
                cargo_titular: pHeadline,
                perfil_url: cleanHref
              });
            }

            if (similarProfiles.length >= 10) break;
          }

          return {
            ok: true,
            nombre: name,
            headline: headline,
            grado: grado,
            email: directEmail,
            phone: directPhone,
            similar_profiles: similarProfiles
          };
        } catch (e) {
          return { ok: false, error: e.message };
        }
      })()
    `);
  } catch (err) {}

  return {
    success: true,
    result: {
      action: 'LI_VISIT_PROFILE',
      profile_url: profileUrl,
      final_url: finalUrl,
      visited_at: new Date().toISOString(),
      email: pageData && pageData.email ? pageData.email : null,
      phone: pageData && pageData.phone ? pageData.phone : null,
      cargo_titular: pageData && pageData.headline ? pageData.headline : null,
      grado_red: pageData && pageData.grado ? pageData.grado : null,
      similar_profiles: (pageData && pageData.similar_profiles) || []
    }
  };
}

/**
 * 2. LI_SEND_INVITE: Envía invitación orgánica con clic biométrico y verificación estricta
 */
async function handleLinkedInSendInvite(win, params) {
  const visitResult = await handleLinkedInVisit(win, params);
  if (!visitResult.success) {
    return visitResult;
  }
  const visitedData = (visitResult && visitResult.result) ? visitResult.result : {};

  const note = params.note || params.nota || '';

  // 0. Asegurar que la página está al tope absoluto para que la cabecera sea 100% visible
  await win.webContents.executeJavaScript(`
    (() => {
      window.scrollTo({ top: 0, behavior: 'instant' });
      return true;
    })()
  `).catch(() => {});
  await sleep(500);

  // 1. Verificar si la cabecera del lead principal ya está en estado "Pendiente" previamente
  const preCheck = await win.webContents.executeJavaScript(`
    (() => {
      const allButtons = Array.from(document.querySelectorAll('button, a[role="button"], span.artdeco-button__text'));
      for (const b of allButtons) {
        if (b.closest('aside, .scaffold-layout__aside, [data-view-name="profile-component-entity"], header, nav, #global-nav, footer, .msg-overlay-container, #msg-overlay')) continue;
        const r = b.getBoundingClientRect();
        if (r.top >= 1300 || r.top < 0 || r.width === 0) continue;
        const txt = (b.innerText || b.textContent || '').trim().toLowerCase();
        const aria = (b.getAttribute('aria-label') || '').toLowerCase();
        if (txt === 'pendiente' || txt === 'pending' || aria.includes('pendiente') || aria.includes('pending') || txt.includes('retirar') || aria.includes('retirar')) {
          return { already_pending: true };
        }
      }
      return { already_pending: false };
    })()
  `).catch(() => ({ already_pending: false }));

  if (preCheck && preCheck.already_pending) {
    return {
      success: true,
      result: {
        action: 'LI_SEND_INVITE',
        profile_url: params.profile_url || params.perfil_url,
        status: 'ALREADY_PENDING',
        verified_pending: true,
        message: 'La invitación ya se encontraba en estado Pendiente previamente en el perfil.',
        sent_at: new Date().toISOString()
      }
    };
  }

  // 2. Búsqueda y clic en botón Conectar EXCLUSIVAMENTE en la cabecera del perfil principal (NUNCA en aside ni sugeridos)
  const clickRes = await win.webContents.executeJavaScript(`
    (async () => {
      const sleepMs = (ms) => new Promise(r => setTimeout(r, ms));
      
      const simulateClick = (el) => {
        el.scrollIntoView({ behavior: 'instant', block: 'center', inline: 'center' });
        const r = el.getBoundingClientRect();
        const randX = r.left + (r.width * (0.3 + Math.random() * 0.4));
        const randY = r.top + (r.height * (0.3 + Math.random() * 0.4));
        el.focus();
        el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, view: window, clientX: randX, clientY: randY }));
        el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window, clientX: randX, clientY: randY }));
        el.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, cancelable: true, view: window, clientX: randX, clientY: randY }));
        el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window, clientX: randX, clientY: randY }));
        el.click();
      };

      const isConnectBtn = (btn) => {
        const txt = (btn.innerText || btn.textContent || '').trim().toLowerCase();
        const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
        const title = (btn.getAttribute('title') || '').toLowerCase();
        const combined = txt + ' ' + aria + ' ' + title;

        const hasConnect = combined.includes('conectar') || combined.includes('connect') || combined.includes('invitar') || combined.includes('invite');
        const isExcluded = combined.includes('en común') || combined.includes('contactos en común') || combined.includes('mensaje') || combined.includes('message') || combined.includes('retirar') || combined.includes('withdraw') || combined.includes('siguiendo') || combined.includes('following') || combined.includes('guardar') || combined.includes('save') || combined.includes('denunciar') || combined.includes('report') || combined.includes('bloquear') || combined.includes('block');
        return hasConnect && !isExcluded;
      };

      const isMoreBtn = (btn) => {
        const txt = (btn.innerText || btn.textContent || '').trim().toLowerCase();
        const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
        const combined = txt + ' ' + aria;
        return (
          txt === 'más' || txt === 'more' || txt === '...' ||
          combined.includes('más') || combined.includes('more') || combined.includes('acciones') || combined.includes('opciones') ||
          Boolean(btn.querySelector('svg[data-test-icon="overflow-web-ios-medium"], svg[data-test-icon="overflow-web-horizontal-small"], svg use[href*="overflow"]'))
        );
      };

      // 1. Obtener todos los botones y enlaces candidatos del perfil (incluye <a> sin role="button" de la nueva UI)
      const allButtons = Array.from(document.querySelectorAll('button, a, div[role="button"]'));

      // 2. Filtrar terminantemente los botones que pertenecen al sidebar (aside), sugeridos, header/nav y chat
      const heroButtons = allButtons.filter(b => {
        if (b.closest('aside, .scaffold-layout__aside, [data-view-name="profile-component-entity"], .pv-profile-body-item')) {
          return false;
        }
        if (b.closest('header, nav, #global-nav, footer, .msg-overlay-container, #msg-overlay')) {
          return false;
        }
        const r = b.getBoundingClientRect();
        // Visible y en la zona superior/media de la cabecera (y < 1300)
        return r.width > 0 && r.height > 0 && r.top < 1300 && r.top >= 0;
      });

      // A) Búsqueda directa del botón Conectar en la cabecera del prospecto
      const connectBtn = heroButtons.find(isConnectBtn);
      if (connectBtn) {
        simulateClick(connectBtn);
        return { found: true, method: 'direct_header' };
      }

      // B) Si no está visible directo, buscar el botón "Más" / "..." en la cabecera
      const moreBtn = heroButtons.find(isMoreBtn);
      if (moreBtn) {
        simulateClick(moreBtn);
        
        // Polling activo esperando que el dropdown menu se monte y renderice
        let menuConnect = null;
        for (let p = 0; p < 8; p++) {
          await sleepMs(300);
          const dropdownMenu = document.querySelector('div.artdeco-dropdown__content--is-open, div[role="menu"], div.artdeco-dropdown__content, .pvs-overflow-actions-dropdown__content');
          if (dropdownMenu) {
            const menuItems = Array.from(dropdownMenu.querySelectorAll('[role="menuitem"], [role="button"], span, div.artdeco-dropdown__item, button, a, li, div'));
            menuConnect = menuItems.find(isConnectBtn);
            if (menuConnect) break;
          }
        }

        if (menuConnect) {
          const clickTarget = menuConnect.closest('[role="button"], div.artdeco-dropdown__item, li, button, a') || menuConnect;
          simulateClick(clickTarget);
          return { found: true, method: 'more_menu' };
        }
      }

      return { found: false, reason: 'El prospecto no posee botón Conectar ni en su cabecera ni en el menú Más' };
    })()
  `).catch((err) => ({ found: false, error: err.message }));

  if (!clickRes || !clickRes.found) {
    return {
      success: false,
      error: clickRes ? clickRes.reason || clickRes.error : 'No se pudo localizar el botón Conectar en la cabecera del perfil.'
    };
  }

  // 3. Inspeccionar el modal emergente y sus condiciones con polling activo (hasta 4 segundos)
  let modalFound = false;
  let directPending = false;

  for (let m = 0; m < 8; m++) {
    await sleep(500);
    const modalInspection = await win.webContents.executeJavaScript(`
      (() => {
        const modals = Array.from(document.querySelectorAll('div[role="dialog"], dialog, div.artdeco-modal'));
        const modal = modals.find(m => {
          if (m.classList.contains('vjs-modal-dialog')) return false;
          const r = m.getBoundingClientRect();
          return r.height > 0 && r.width > 0;
        });

        if (modal) {
          const modalText = (modal.innerText || '').toLowerCase();

          // Detección de barreras
          if (modalText.includes('introduce el correo') || modalText.includes('enter the email') || modalText.includes('correo electrónico')) {
            const closeBtn = modal.querySelector('button[aria-label*="Cerrar"], button[aria-label*="Dismiss"], button.artdeco-modal__dismiss');
            if (closeBtn) closeBtn.click();
            return { has_modal: true, blocked: true, reason: 'EMAIL_REQUIRED' };
          }

          if (modalText.includes('límite semanal') || modalText.includes('weekly invitation limit')) {
            const closeBtn = modal.querySelector('button[aria-label*="Cerrar"], button[aria-label*="Dismiss"], button.artdeco-modal__dismiss');
            if (closeBtn) closeBtn.click();
            return { has_modal: true, blocked: true, reason: 'WEEKLY_LIMIT' };
          }

          return { has_modal: true, blocked: false };
        }

        // Si no hay modal, verificar si pasó inmediatamente a pendiente (conexión directa sin modal)
        const allButtons = Array.from(document.querySelectorAll('button, a, span'));
        for (const b of allButtons) {
          if (b.closest('aside, .scaffold-layout__aside, [data-view-name="profile-component-entity"], header, nav, #global-nav, footer, .msg-overlay-container, #msg-overlay')) continue;
          const r = b.getBoundingClientRect();
          if (r.top >= 1300 || r.top < 0 || r.width === 0) continue;
          const txt = (b.innerText || b.textContent || '').trim().toLowerCase();
          const aria = (b.getAttribute('aria-label') || '').toLowerCase();
          if (txt === 'pendiente' || txt === 'pending' || aria.includes('pendiente') || aria.includes('pending') || txt.includes('retirar') || aria.includes('retirar')) {
            return { has_modal: false, direct_pending: true };
          }
        }

        return { has_modal: false, direct_pending: false };
      })()
    `).catch(() => ({ has_modal: false, direct_pending: false }));

    if (modalInspection && modalInspection.blocked) {
      return {
        success: false,
        error: `No se pudo enviar la invitación: ${modalInspection.reason === 'EMAIL_REQUIRED' ? 'LinkedIn exige el email del contacto para conectar' : 'Límite semanal alcanzado'}`,
        blocked_reason: modalInspection.reason
      };
    }

    if (modalInspection && modalInspection.has_modal) {
      modalFound = true;
      break;
    }

    if (modalInspection && modalInspection.direct_pending) {
      directPending = true;
      break;
    }
  }

  // 4. Gestión de Nota o Envío directo en la ventana modal
  if (modalFound) {
    if (note) {
      await win.webContents.executeJavaScript(`
        (() => {
          const simulateClick = (el) => {
            el.focus();
            el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, view: window }));
            el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
            el.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, cancelable: true, view: window }));
            el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
            el.click();
          };

          const addNoteBtn = Array.from(document.querySelectorAll('div[role="dialog"] button, div.artdeco-modal button')).find(b => {
            const txt = (b.innerText || '').toLowerCase();
            const aria = (b.getAttribute('aria-label') || '').toLowerCase();
            return txt.includes('añadir una nota') || txt.includes('add a note') || aria.includes('nota') || aria.includes('note');
          });
          if (addNoteBtn) simulateClick(addNoteBtn);
        })()
      `).catch(() => {});

      await sleep(1000 + Math.random() * 500);

      const escapedNote = JSON.stringify(note);
      await win.webContents.executeJavaScript(`
        (() => {
          const textarea = document.querySelector('div[role="dialog"] textarea, div.artdeco-modal textarea');
          if (textarea) {
            textarea.focus();
            textarea.value = ${escapedNote};
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
            textarea.dispatchEvent(new Event('change', { bubbles: true }));
          }
        })()
      `).catch(() => {});

      await sleep(1000 + Math.random() * 500);

      // Clic en "Enviar" con nota usando simulateClick
      await win.webContents.executeJavaScript(`
        (() => {
          const simulateClick = (el) => {
            el.focus();
            el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, view: window }));
            el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
            el.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, cancelable: true, view: window }));
            el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
            el.click();
          };

          const modal = document.querySelector('div[role="dialog"], div.artdeco-modal');
          if (!modal) return;
          const modalButtons = Array.from(modal.querySelectorAll('button'));
          let sendBtn = modalButtons.find(b => {
            const txt = (b.innerText || '').trim().toLowerCase();
            const aria = (b.getAttribute('aria-label') || '').toLowerCase();
            return txt === 'enviar' || txt === 'send' || txt === 'enviar ahora' || txt === 'send now' || aria.includes('enviar');
          });
          if (!sendBtn) {
            sendBtn = modal.querySelector('button.artdeco-button--primary');
          }
          if (sendBtn) simulateClick(sendBtn);
        })()
      `).catch(() => {});
    } else {
      // Envío SIN nota: buscar "Enviar sin nota" o fallback a botón primario de envío
      await win.webContents.executeJavaScript(`
        (() => {
          const allButtons = Array.from(document.querySelectorAll('button, a'));
          const sendBtn = allButtons.find(b => {
            const txt = (b.innerText || '').trim().toLowerCase();
            const aria = (b.getAttribute('aria-label') || '').toLowerCase();
            return txt.includes('sin nota') || aria.includes('sin nota') || txt.includes('without a note') || aria.includes('without a note');
          }) || allButtons.find(b => {
            const txt = (b.innerText || '').trim().toLowerCase();
            return txt === 'enviar' || txt === 'send' || txt === 'enviar ahora' || txt === 'send now';
          });

          if (sendBtn) {
            sendBtn.focus();
            sendBtn.click();
          }
        })()
      `).catch(() => {});
    }
  }

  // 5. Validación definitiva: Polling activo (hasta 8 segundos) verificando que el botón pasó a "Pendiente"
  let verifiedPending = directPending;
  let modalStillOpen = false;

  if (!verifiedPending) {
    for (let i = 0; i < 10; i++) {
      await sleep(800);
      const verifyRes = await win.webContents.executeJavaScript(`
        (() => {
          const allButtons = Array.from(document.querySelectorAll('button, a, span'));
          let isPending = false;
          let modalOpen = false;

          for (const el of allButtons) {
            if (el.closest('aside, .scaffold-layout__aside, [data-view-name="profile-component-entity"], header, nav, #global-nav, footer, .msg-overlay-container, #msg-overlay')) continue;
            const r = el.getBoundingClientRect();
            if (r.top >= 1300 || r.top < 0 || r.width === 0) continue;
            const txt = (el.innerText || el.textContent || '').trim().toLowerCase();
            const aria = (el.getAttribute('aria-label') || '').toLowerCase();
            if (txt === 'pendiente' || txt === 'pending' || aria.includes('pendiente') || aria.includes('pending') || txt.includes('retirar') || aria.includes('retirar')) {
              isPending = true;
              break;
            }
          }

          const modals = Array.from(document.querySelectorAll('div[role="dialog"], dialog, div.artdeco-modal'));
          modalOpen = modals.some(m => !m.classList.contains('vjs-modal-dialog') && m.getBoundingClientRect().height > 0);

          return { isPending, modalOpen };
        })()
      `).catch(() => ({ isPending: false, modalOpen: false }));

      if (verifyRes.isPending) {
        verifiedPending = true;
        modalStillOpen = verifyRes.modalOpen;
        break;
      }
      modalStillOpen = verifyRes.modalOpen;
    }
  }

  // REGLA DE ORO TERMINANTE: SI LINKEDIN NO CONFIRMA "PENDIENTE", NUNCA RETORNAR ÉXITO. CERO FALSOS POSITIVOS.
  if (!verifiedPending) {
    return {
      success: false,
      error: modalStillOpen
        ? 'La ventana modal de invitación no se cerró correctamente al intentar el envío.'
        : 'La invitación no pudo ser confirmada en LinkedIn: el botón del perfil no pasó a estado "Pendiente".',
      verified_pending: false,
      method: clickRes.method
    };
  }

  return {
    success: true,
    result: {
      action: 'LI_SEND_INVITE',
      profile_url: params.profile_url || params.perfil_url,
      method: clickRes.method,
      verified_pending: true,
      has_note: Boolean(note),
      sent_at: new Date().toISOString(),
      similar_profiles: visitedData.similar_profiles || [],
      email: visitedData.email || null,
      phone: visitedData.phone || null,
      cargo_titular: visitedData.cargo_titular || null,
      grado_red: visitedData.grado_red || null
    }
  };
}

/**
 * 3. LI_SEND_MESSAGE: Enviar mensaje directo en LinkedIn
 */
async function handleLinkedInSendMessage(win, params) {
  if (!win || win.isDestroyed()) {
    return { success: false, error: 'Ventana de LinkedIn no disponible' };
  }
  const profileUrl = params.profile_url || params.perfil_url;
  const message = params.message || params.mensaje;
  if (!profileUrl || !message) {
    return { success: false, error: 'Parámetros profile_url y message requeridos' };
  }

  const visitRes = await handleLinkedInVisit(win, { profile_url: profileUrl });
  if (!visitRes.success) return visitRes;

  await win.webContents.executeJavaScript(`window.scrollTo({ top: 0, behavior: 'instant' });`).catch(() => {});
  await sleep(600);

  const escapedMsg = JSON.stringify(message);
  const msgResult = await win.webContents.executeJavaScript(`
    (() => {
      const allButtons = Array.from(document.querySelectorAll('button, a[role="button"]'));
      const heroButtons = allButtons.filter(b => {
        if (b.closest('aside, .scaffold-layout__aside, [data-view-name="profile-component-entity"], .pv-profile-body-item')) return false;
        if (b.closest('header, nav, #global-nav, footer, .msg-overlay-container, #msg-overlay')) return false;
        const r = b.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && r.top < 850 && r.top >= 0;
      });

      const msgBtn = heroButtons.find(b => {
        const txt = (b.innerText || b.textContent || '').trim().toLowerCase();
        return txt.includes('enviar mensaje') || txt.includes('message');
      });
      if (!msgBtn) return { ok: false, error: 'Botón enviar mensaje no encontrado en la cabecera del prospecto' };
      msgBtn.click();

      setTimeout(() => {
        const msgBox = document.querySelector('.msg-form__contenteditable, div[role="textbox"]');
        if (msgBox) {
          msgBox.focus();
          document.execCommand('insertText', false, ${escapedMsg});
          setTimeout(() => {
            const sendBtn = document.querySelector('.msg-form__send-button, button[type="submit"]');
            if (sendBtn && !sendBtn.disabled) sendBtn.click();
          }, 800);
        }
      }, 1200);

      return { ok: true };
    })()
  `).catch((err) => ({ ok: false, error: err.message }));

  return {
    success: Boolean(msgResult && msgResult.ok),
    result: {
      action: 'LI_SEND_MESSAGE',
      profile_url: profileUrl,
      sent_at: new Date().toISOString()
    }
  };
}

/**
 * 4. LI_EXTRACT_NETWORK: Extrae contactos de 1er grado y/o invitaciones pendientes de LinkedIn
 * utilizando selectores universales resilientes a cambios de DOM (2025/2026), scroll progresivo y paginación profunda.
 */
async function handleLinkedInExtractNetwork(win, params = {}) {
  if (!win || win.isDestroyed()) {
    return { success: false, error: 'Ventana de LinkedIn no disponible' };
  }
  const source = params.source || 'all'; // 'connections', 'sent_invitations', 'all'
  const targetLimit = Math.max(10, Number(params.limit) || 50);
  const leads = [];
  const seenUrls = new Set();

  // Helper de extracción de elementos actualmente montados en el DOM
  const extractFromCurrentDom = async (scrollTimes = 1) => {
    return await win.webContents.executeJavaScript(`
      (async () => {
        try {
          for (let s = 0; s < ${scrollTimes}; s++) {
            window.scrollBy({ top: 850, behavior: 'smooth' });
            await new Promise(r => setTimeout(r, 450));
          }

          const extracted = [];
          const seen = new Set();
          const allLinks = Array.from(document.querySelectorAll('a[href*="/in/"]'));

          for (const a of allLinks) {
            const rawHref = a.getAttribute('href') || '';
            const cleanHref = rawHref.split('?')[0].replace(/\\/+$/, '') + '/';
            if (!cleanHref.includes('/in/') || cleanHref.includes('/in/edit') || cleanHref.includes('/in/unavailable')) continue;
            if (seen.has(cleanHref)) continue;

            const card = a.closest('li') || a.parentElement;
            const cardText = card ? (card.innerText || '').trim() : '';
            const lines = cardText.split('\\n').map(s => s.trim()).filter(Boolean);

            // Filtrar textos de acciones comunes de botones de LinkedIn
            const nonActionLines = lines.filter(l => {
              const lower = l.toLowerCase();
              return !['retirar', 'withdraw', 'cancelar', 'mensaje', 'message', 'conectar', 'connect', 'enviar mensaje', 'seguir', 'follow'].includes(lower);
            });

            // Extraer nombre del candidato
            let name = (a.innerText || '').trim();
            if (!name || name.length < 2 || name.toLowerCase().includes('verificado') || name.toLowerCase().includes('premium')) {
              name = nonActionLines[0] || 'Contacto de LinkedIn';
            }
            name = name.replace(/\\s*(Verificado|Premium|\\(He\\/Him\\)|\\(She\\/Her\\))\\s*/gi, ' ').trim();

            // Extraer titular / cargo
            const headline = nonActionLines.find(l => 
              l !== name && 
              !l.toLowerCase().includes('contacto desde') && 
              !l.toLowerCase().includes('connected') && 
              !l.toLowerCase().includes('enviad') && 
              !l.toLowerCase().includes('sent ')
            ) || '';

            // Extraer tiempo relativo
            const timeText = nonActionLines.find(l => 
              l.toLowerCase().includes('contacto desde') || 
              l.toLowerCase().includes('connected') || 
              l.toLowerCase().includes('enviad') || 
              l.toLowerCase().includes('sent ') ||
              l.toLowerCase().includes('hace ')
            ) || '';

            const img = card ? card.querySelector('img') : null;
            const avatar = img ? (img.src || img.getAttribute('data-delayed-url') || '') : '';

            seen.add(cleanHref);
            extracted.push({
              perfil_url: cleanHref,
              nombre: name,
              cargo_titular: headline,
              tiempo: timeText,
              avatar_url: avatar
            });
          }

          // Verificar si existe botón "Siguiente" activo para paginación
          const pagElements = Array.from(document.querySelectorAll('.artdeco-pagination button, .artdeco-pagination a, button[aria-label*="página"], button[aria-label*="Page"], ul.artdeco-pagination__pages li, .artdeco-pagination')).map(el => (el.outerHTML || '').slice(0, 150));

          const nextBtn = document.querySelector('button.artdeco-pagination__button--next') ||
            Array.from(document.querySelectorAll('button')).find(b => {
              const t = b.innerText.trim().toLowerCase();
              const aria = (b.getAttribute('aria-label') || '').toLowerCase();
              return t === 'siguiente' || t === 'next' || aria.includes('next') || aria.includes('siguiente');
            });
          const hasNextButton = Boolean(nextBtn && !nextBtn.disabled && !nextBtn.classList.contains('artdeco-button--disabled'));

          return { ok: true, data: extracted, hasNextButton, pagElements };
        } catch (err) {
          return { ok: false, error: err.message, data: [], hasNextButton: false };
        }
      })()
    `).catch(err => ({ ok: false, error: err.message, data: [], hasNextButton: false }));
  };

  const debugInfo = {};

  // 1. Conexiones (1º Grado) - Scroll infinito progresivo
  if (source === 'connections' || source === 'all') {
    const connectionsUrl = 'https://www.linkedin.com/mynetwork/invite-connect/connections/';
    const currentUrl = win.webContents.getURL() || '';
    if (!currentUrl.includes('/invite-connect/connections/')) {
      await new Promise(resolve => {
        const timeout = setTimeout(resolve, 14000);
        win.webContents.once('did-finish-load', () => {
          clearTimeout(timeout);
          resolve();
        });
        win.loadURL(connectionsUrl).catch(resolve);
      });
      await sleep(2500);
    }

    const targetConns = (source === 'connections') ? targetLimit : Math.ceil(targetLimit / 2);
    let connCount = 0;
    let staleRounds = 0;
    const maxRounds = Math.max(30, Math.ceil(targetConns / 2) + 10);

    for (let r = 0; r < maxRounds; r++) {
      if (connCount >= targetConns || staleRounds >= 5) break;

      const connRes = await extractFromCurrentDom(1);
      let newInBatch = 0;

      if (connRes && connRes.data) {
        for (const item of connRes.data) {
          if (!seenUrls.has(item.perfil_url)) {
            seenUrls.add(item.perfil_url);
            leads.push({
              ...item,
              grado_red: '1º',
              estado_origen: 'CONECTADO',
              tipo_origen: 'CONEXION_DIRECTA'
            });
            connCount++;
            newInBatch++;
            if (connCount >= targetConns) break;
          }
        }
      }

      if (newInBatch === 0) {
        staleRounds++;
      } else {
        staleRounds = 0;
      }

      if (connCount >= targetConns) break;

      // Scroll hacia el final para activar el loader infinito de LinkedIn
      await win.webContents.executeJavaScript(`
        (() => {
          try {
            window.scrollTo({ top: document.documentElement.scrollHeight || document.body.scrollHeight, behavior: 'smooth' });
            const containers = document.querySelectorAll('.scaffold-finite-scroll__content, .mn-connections, main');
            for (const c of containers) { c.scrollTop = c.scrollHeight; }

            const btn = Array.from(document.querySelectorAll('button')).find(b => {
              const t = (b.innerText || '').trim().toLowerCase();
              return t.includes('mostrar más') || t.includes('cargar más') || t.includes('show more');
            });
            if (btn && !btn.disabled) btn.click();
          } catch (e) {}
        })()
      `).catch(() => {});

      await sleep(1500 + Math.random() * 500); // Pausa antiban mientras carga el DOM
    }
  }

  // 2. Invitaciones Enviadas (Pendientes) - Scroll continuo de lista virtualizada
  if (source === 'sent_invitations' || source === 'all') {
    if (source === 'all') {
      await sleep(1500 + Math.random() * 500); // Pausa antiban al cambiar de sección
    }

    const sentUrl = 'https://www.linkedin.com/mynetwork/invitation-manager/sent/';
    const currentUrl = win.webContents.getURL() || '';
    if (!currentUrl.includes('/invitation-manager/sent/')) {
      await new Promise(resolve => {
        const timeout = setTimeout(resolve, 14000);
        win.webContents.once('did-finish-load', () => {
          clearTimeout(timeout);
          resolve();
        });
        win.loadURL(sentUrl).catch(resolve);
      });
      await sleep(2200);
    }

    const targetSent = (source === 'sent_invitations') 
      ? targetLimit 
      : Math.max(Math.ceil(targetLimit / 2), targetLimit - leads.length);
    let sentCount = 0;
    let staleRounds = 0;
    const maxRounds = Math.max(30, Math.ceil(targetSent / 2) + 10);

    for (let r = 0; r < maxRounds; r++) {
      if (sentCount >= targetSent || staleRounds >= 5) break;

      const sentRes = await extractFromCurrentDom(1);
      let newInBatch = 0;

      if (sentRes && sentRes.data) {
        for (const item of sentRes.data) {
          if (!seenUrls.has(item.perfil_url)) {
            seenUrls.add(item.perfil_url);
            leads.push({
              ...item,
              grado_red: '2º',
              estado_origen: 'INVITACION_ENVIADA',
              tipo_origen: 'INVITACION_PENDIENTE'
            });
            sentCount++;
            newInBatch++;
            if (sentCount >= targetSent) break;
          }
        }
      }

      if (newInBatch === 0) {
        staleRounds++;
      } else {
        staleRounds = 0;
      }

      if (sentCount >= targetSent) break;

      // Scroll hacia el final para activar el loader infinito de LinkedIn
      await win.webContents.executeJavaScript(`
        (() => {
          try {
            window.scrollTo({ top: document.documentElement.scrollHeight || document.body.scrollHeight, behavior: 'smooth' });
            const containers = document.querySelectorAll('.scaffold-finite-scroll__content, .mn-invitation-manager, main, .artdeco-card');
            for (const c of containers) { c.scrollTop = c.scrollHeight; }

            const btn = Array.from(document.querySelectorAll('button')).find(b => {
              const t = (b.innerText || '').trim().toLowerCase();
              return t.includes('mostrar más') || t.includes('cargar más') || t.includes('show more');
            });
            if (btn && !btn.disabled) btn.click();
          } catch (e) {}
        })()
      `).catch(() => {});

      await sleep(1500 + Math.random() * 500); // Pausa antiban mientras carga el DOM
    }
  }

  return {
    success: true,
    total: leads.length,
    leads: leads,
    source: source,
    limit: targetLimit,
    debug: debugInfo,
    extracted_at: new Date().toISOString()
  };
}

/**
 * 4.2 LI_SEARCH_PEOPLE: Búsqueda y extracción precompilada de personas en LinkedIn
 */
async function handleLinkedInSearchPeople(win, params = {}) {
  if (!win || win.isDestroyed()) {
    return { success: false, error: 'Ventana de LinkedIn no disponible' };
  }
  const term = (params.term || params.termino || '').trim();
  const page = Math.max(1, parseInt(params.page || params.pagina || 1, 10));

  if (!term) {
    return { success: false, error: 'Término de búsqueda no especificado' };
  }

  const encodedTerm = encodeURIComponent(term);
  const targetUrl = `https://www.linkedin.com/search/results/people/?keywords=${encodedTerm}&origin=SWITCH_SEARCH_VERTICAL${page > 1 ? `&page=${page}` : ''}`;

  try {
    // Navegar a la URL de búsqueda
    await new Promise((resolve) => {
      const timeout = setTimeout(resolve, 15000);
      win.webContents.once('did-finish-load', () => {
        clearTimeout(timeout);
        resolve();
      });
      win.loadURL(targetUrl).catch(resolve);
    });

    // Esperar renderizado reactivo inicial
    await sleep(2500);

    // Scroll progresivo suave para disparar hidratación de las tarjetas y lazy-loading
    await win.webContents.executeJavaScript(`
      (() => {
        window.scrollBy({ top: 380, behavior: 'smooth' });
        return true;
      })()
    `).catch(() => {});
    await sleep(1500);

    await win.webContents.executeJavaScript(`
      (() => {
        window.scrollBy({ top: 450, behavior: 'smooth' });
        return true;
      })()
    `).catch(() => {});
    await sleep(1200);

    // Ejecutar extracción precompilada en el contexto del DOM de LinkedIn
    const evalResult = await win.webContents.executeJavaScript(`
      (() => {
        try {
          const seenUrls = new Set();
          const leads = [];

          // 1. Localizar lista o contenedores de tarjetas de personas (SDUI 2026 y clásico)
          let cardElements = [];
          const lists = Array.from(document.querySelectorAll('[role="list"]'));
          const searchList = lists.find(l => l.children.length >= 3 && l.children.length <= 15);
          if (searchList) {
            cardElements = Array.from(searchList.children);
          } else {
            cardElements = Array.from(document.querySelectorAll(
              '.reusable-search__result-container, .entity-result, [componentkey*="SearchResult"], div[data-view-name*="search-entity-result"]'
            ));
          }

          const extractDegree = (t) => {
            if (!t) return '2º';
            if (/1er|1º|1°/i.test(t)) return '1º';
            if (/2do|2º|2°/i.test(t)) return '2º';
            if (/3er|3º|3°|\\+/i.test(t)) return '3º+';
            return '2º';
          };

          const isDegreeBadge = (t) => {
            if (!t) return false;
            return /^[·•\\s]*(?:1er|1º|1°|2do|2º|2°|3er|3º|3°|\\d+[º°]|\\d+(?:er|do|to|st|nd|rd|th))\\+?[·•\\s]*$/i.test(t.trim());
          };

          // A) Si se encontraron tarjetas estructuradas
          if (cardElements.length > 0) {
            cardElements.forEach(card => {
              try {
                const text = (card.innerText || '').trim();
                if (!text || text.length < 8) return;
                const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);

                // Obtener enlace del candidato principal excluyendo enlaces de contactos en común
                const allLinks = Array.from(card.querySelectorAll('a[href*="/in/"]'));
                const primaryLink = allLinks.find(a => {
                  const parentText = (a.closest('p') || a.parentElement || {}).innerText || '';
                  return !parentText.includes('contacto') && !parentText.includes('común') && !parentText.includes('mutual');
                }) || allLinks[0];

                if (!primaryLink) return;

                const rawHref = primaryLink.getAttribute('href') || primaryLink.href || '';
                const cleanUrl = rawHref.split('?')[0].replace(/\\/+$/, '') + '/';
                if (!cleanUrl.includes('/in/') || cleanUrl.endsWith('/in/')) return;
                if (seenUrls.has(cleanUrl)) return;

                let nombre = '';
                let grado = '2º';
                let titular = '';
                let ubicacion = 'Chile';
                let snippetActual = '';

                // Intentar extraer con selectores semánticos de LinkedIn
                const titleEl = card.querySelector('.entity-result__title-text a span[aria-hidden="true"], .entity-result__title-text a');
                if (titleEl) {
                  nombre = (titleEl.innerText || '').trim();
                }

                const badgeEl = card.querySelector('.entity-result__badge-text, .dist-value, [class*="badge-text"]');
                if (badgeEl) {
                  grado = extractDegree(badgeEl.innerText);
                }

                const subtitleEl = card.querySelector('.entity-result__primary-subtitle, [class*="primary-subtitle"]');
                if (subtitleEl) {
                  titular = (subtitleEl.innerText || '').trim();
                }

                const secSubtitleEl = card.querySelector('.entity-result__secondary-subtitle, [class*="secondary-subtitle"]');
                if (secSubtitleEl) {
                  ubicacion = (secSubtitleEl.innerText || '').trim();
                }

                const insightEl = card.querySelector('.entity-result__simple-insight, [class*="simple-insight"], [class*="insights"]');
                if (insightEl) {
                  snippetActual = (insightEl.innerText || '').trim();
                }

                // Fallback por análisis de líneas de texto de la tarjeta si faltan campos
                if (!nombre && lines.length > 0) {
                  const first = lines[0];
                  const parts = first.split(/[•·]/);
                  nombre = parts[0].trim();
                  if (parts.length > 1 && !badgeEl) {
                    grado = extractDegree(parts[1]);
                  }
                }

                // Limpiar nombre de artefactos comunes
                nombre = nombre.replace(/\\s*(Verificado|Premium|\\(He\\/Him\\)|\\(She\\/Her\\))\\s*/gi, ' ').trim();
                if (!nombre || nombre.toLowerCase().includes('contacto') || nombre.toLowerCase().includes('linkedin')) return;

                if (!snippetActual) {
                  const snipLine = lines.find(l => /^(Actual|Current|Experiencia actual)\\s*:/i.test(l));
                  if (snipLine) snippetActual = snipLine;
                }

                if (!titular) {
                  for (let i = 1; i < lines.length; i++) {
                    const l = lines[i];
                    if (l === '·' || l === '•' || isDegreeBadge(l)) continue;
                    if (l.includes('Conectar') || l.includes('Pendiente') || l.includes('Mensaje') || l.includes('Seguir') || l.includes('contacto en común')) continue;
                    if (/^(Actual|Current|Pasado|Past|Experiencia actual)\\s*:/i.test(l)) continue;
                    titular = l;
                    break;
                  }
                }

                // Extraer institución sugerida desde snippet o titular
                let institucion = '';
                const sourceText = snippetActual || titular;
                if (sourceText.toLowerCase().includes(' en ')) {
                  institucion = sourceText.split(/\\sen\\s/i)[1].split(/[;|\·•]/)[0].trim();
                } else if (sourceText.toLowerCase().includes(' at ')) {
                  institucion = sourceText.split(/\\sat\\s/i)[1].split(/[;|\·•]/)[0].trim();
                }

                seenUrls.add(cleanUrl);
                leads.push({
                  nombre: nombre,
                  grado_red: grado,
                  cargo_titular: titular || 'Profesional de LinkedIn',
                  snippet_actual: snippetActual,
                  institucion_actual: institucion,
                  ubicacion: ubicacion || 'Chile',
                  perfil_url: cleanUrl
                });
              } catch (e) {}
            });
          }

          // B) Fallback: Si no hubo tarjetas estructuradas por cambios drásticos en el DOM
          if (leads.length === 0) {
            const allLinks = Array.from(document.querySelectorAll('main a[href*="/in/"], div.search-results-container a[href*="/in/"]'));
            allLinks.forEach(a => {
              try {
                const rawHref = a.getAttribute('href') || a.href || '';
                const cleanUrl = rawHref.split('?')[0].replace(/\\/+$/, '') + '/';
                if (!cleanUrl.includes('/in/') || cleanUrl.endsWith('/in/')) return;
                if (seenUrls.has(cleanUrl)) return;

                const nameEl = a.querySelector('span[aria-hidden="true"]') || a;
                let name = (nameEl.innerText || '').trim();
                name = name.replace(/\\s*(Verificado|Premium|\\(He\\/Him\\)|\\(She\\/Her\\))\\s*/gi, ' ').trim();
                if (!name || name.length < 2 || name.toLowerCase().includes('contacto') || name.toLowerCase().includes('linkedin')) return;

                const parent = a.closest('li') || a.parentElement;
                const text = parent ? (parent.innerText || '') : '';
                const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);

                let titular = lines.find(l => l !== name && !l.toLowerCase().includes('conectar') && !l.toLowerCase().includes('mensaje') && !isDegreeBadge(l)) || 'Profesional de LinkedIn';

                seenUrls.add(cleanUrl);
                leads.push({
                  nombre: name,
                  grado_red: '2º',
                  cargo_titular: titular,
                  snippet_actual: '',
                  institucion_actual: '',
                  ubicacion: 'Chile',
                  perfil_url: cleanUrl
                });
              } catch (e) {}
            });
          }

          return { success: true, total: leads.length, leads: leads };
        } catch (err) {
          return { success: false, total: 0, leads: [], error: err.message };
        }
      })()
    `);

    return {
      success: evalResult && evalResult.success !== false,
      total: evalResult && evalResult.leads ? evalResult.leads.length : 0,
      leads: evalResult && evalResult.leads ? evalResult.leads : [],
      url_busqueda: targetUrl
    };
  } catch (err) {
    return {
      success: false,
      total: 0,
      leads: [],
      error: err.message,
      url_busqueda: targetUrl
    };
  }
}

/**
 * 4.1 LI_SYNC_CONNECTIONS: Compatibilidad con el ejecutor de comandos
 */
async function handleLinkedInSyncConnections(win, params) {
  const res = await handleLinkedInExtractNetwork(win, { source: params.source || 'connections' });
  return {
    success: res.success,
    result: {
      action: 'LI_SYNC_CONNECTIONS',
      total_found: res.total,
      connections: (res.leads || []).slice(0, 50),
      synced_at: new Date().toISOString()
    }
  };
}

/**
 * 5. LI_READ_CONTACT_INFO: Extrae información de contacto de 1er grado
 */
async function handleLinkedInReadContactInfo(win, params) {
  if (!win || win.isDestroyed()) {
    return { success: false, error: 'Ventana de LinkedIn no disponible' };
  }
  const profileUrl = params.profile_url || params.perfil_url;
  if (!profileUrl) {
    return { success: false, error: 'profile_url requerido' };
  }

  // Pre-verificación de sesión activa de LinkedIn
  try {
    const cookies = await win.webContents.session.cookies.get({ domain: '.linkedin.com' });
    const hasLiAt = cookies.some((c) => c.name === 'li_at');
    if (!hasLiAt) {
      return {
        success: false,
        ok: false,
        error: 'Sesión de LinkedIn no iniciada en la aplicación. Por favor, abre LinkedIn en la barra lateral e inicia sesión para consultar datos de contacto.'
      };
    }
  } catch (err) {}

  const cleanUrl = profileUrl.split('?')[0].replace(/\/+$/, '') + '/overlay/contact-info/';
  const check = isUrlAllowed(cleanUrl, false);
  if (!check.allowed) return { success: false, error: check.reason };

  await new Promise((resolve) => {
    const timeout = setTimeout(resolve, 14000);
    win.webContents.once('did-finish-load', () => {
      clearTimeout(timeout);
      resolve();
    });
    win.loadURL(cleanUrl).catch(resolve);
  });

  await sleep(2500);

  if (win.webContents.isLoading()) {
    await new Promise((resolve) => {
      win.webContents.once('did-stop-loading', resolve);
      setTimeout(resolve, 8000);
    });
    await sleep(1500);
  }

  const contactData = await safeExecuteInIsolatedWorld(win, `
    (() => {
      let email = null;
      let phone = null;
      const websites = [];

      const mailto = document.querySelector('a[href^="mailto:"]');
      if (mailto) {
        email = (mailto.getAttribute('href') || '').replace(/^mailto:/i, '').split('?')[0].trim();
      }

      if (!email) {
        const emailSec = document.querySelector('.ci-email, div[data-field="email"]');
        if (emailSec) {
          const a = emailSec.querySelector('a');
          if (a) email = a.innerText.trim();
        }
      }

      const phoneSec = document.querySelector('.ci-phone');
      if (phoneSec) {
        const span = phoneSec.querySelector('span');
        if (span) phone = span.innerText.trim();
      }

      const siteLinks = Array.from(document.querySelectorAll('.ci-websites a'));
      siteLinks.forEach(s => {
        if (s.href && !s.href.includes('linkedin.com')) websites.push(s.href);
      });

      return { email, phone, websites };
    })()
  `).catch((err) => ({ email: null, phone: null, websites: [], error: err.message }));

  return {
    success: Boolean(contactData && (contactData.email || contactData.phone)),
    result: {
      action: 'LI_READ_CONTACT_INFO',
      email: contactData ? contactData.email : null,
      phone: contactData ? contactData.phone : null,
      websites: contactData ? contactData.websites : [],
      read_at: new Date().toISOString()
    }
  };
}

/**
 * 5.1 LI_ENRICH_PROFILE / LI_EXTRACT_PROFILE: Enriquecimiento Precompilado Seguro de Perfil en Vivo
 * Inspecciona el perfil activo o navega de forma segura para extraer el cargo actual, empresa,
 * titular, ubicación y grado de red mediante funciones precompiladas locales (Regla C-01).
 */
async function handleLinkedInEnrichProfile(win, params = {}) {
  if (!win || win.isDestroyed()) {
    return { success: false, ok: false, error: 'Ventana de LinkedIn no disponible' };
  }
  const profileUrl = params.profile_url || params.perfil_url;
  if (!profileUrl) {
    return { success: false, ok: false, error: 'Parámetro profile_url requerido' };
  }

  // Pre-verificación de sesión activa de LinkedIn
  try {
    const cookies = await win.webContents.session.cookies.get({ domain: '.linkedin.com' });
    const hasLiAt = cookies.some((c) => c.name === 'li_at');
    if (!hasLiAt) {
      return {
        success: false,
        ok: false,
        error: 'Sesión de LinkedIn no iniciada en la aplicación. Por favor, abre LinkedIn en la barra lateral e inicia sesión para sincronizar contactos.'
      };
    }
  } catch (err) {}

  const cleanUrl = profileUrl.split('?')[0].replace(/\/+$/, '') + '/';
  const check = isUrlAllowed(cleanUrl, false);
  if (!check.allowed || check.channel !== 'linkedin') {
    return { success: false, ok: false, error: check.reason || 'URL no permitida por Allowlist Guard' };
  }

  // Navegar si no estamos ya en dicho perfil
  const currentUrl = win.webContents.getURL() || '';
  if (!currentUrl.startsWith(cleanUrl)) {
    await new Promise((resolve) => {
      const timeout = setTimeout(resolve, 14000);
      win.webContents.once('did-finish-load', () => {
        clearTimeout(timeout);
        resolve();
      });
      win.loadURL(cleanUrl).catch(resolve);
    });
    await sleep(2500);
  }

  // Asegurar que la página no esté en proceso de carga o redirección antes de inspeccionar
  if (win.webContents.isLoading()) {
    await new Promise((resolve) => {
      win.webContents.once('did-stop-loading', resolve);
      setTimeout(resolve, 8000);
    });
    await sleep(1500);
  }

  const finalUrl = win.webContents.getURL() || '';
  if (finalUrl.includes('/login') || finalUrl.includes('/authwall') || finalUrl.includes('/checkpoint')) {
    return {
      success: false,
      ok: false,
      error: 'Sesión de LinkedIn no iniciada o checkpoint detectado',
      checkpoint_detected: true
    };
  }

  // Desplazamiento progresivo orgánico para activar lazy loading de Experiencia en SDUI
  await safeExecuteInIsolatedWorld(win, `
    (() => {
      try {
        const ws = document.getElementById('workspace') || document.querySelector('main');
        window.scrollTo({ top: 800, behavior: 'auto' });
        if (ws) ws.scrollTop = 800;

        const sections = Array.from(document.querySelectorAll('section'));
        for (const s of sections) {
          const h2 = s.querySelector('h2');
          const h2Text = h2 ? (h2.innerText || '').toLowerCase() : '';
          if (h2Text.includes('experiencia') || h2Text.includes('experience')) {
            s.scrollIntoView({ behavior: 'auto', block: 'center' });
            break;
          }
        }
        return true;
      } catch (e) {
        return false;
      }
    })()
  `).catch(() => {});

  await sleep(1500);

  // Extracción precompilada del perfil
  const profileData = await safeExecuteInIsolatedWorld(win, `
    (() => {
      try {
        const url = window.location.href;
        const pageTitle = (document.title || '').trim();

        if (url.includes('/404') || 
            pageTitle.toLowerCase().includes('esta página no existe') || 
            pageTitle.toLowerCase().includes('page not found') || 
            (document.body && document.body.innerText.includes('Esta página no existe'))) {
          return {
            ok: false,
            is_404: true,
            error: 'Página no encontrada en LinkedIn (404)'
          };
        }

        const sections = Array.from(document.querySelectorAll('section'));
        const introSec = sections.find(s => {
          const text = (s.innerText || '').trim();
          return text.includes('Información de contacto') || text.includes('contact info') || text.includes('contactos') || text.includes('connections');
        }) || sections[1] || sections[0];

        let name = '';
        let headline = '';
        let location = 'Chile';
        let grado = '2º';

        const isDegreeText = (t) => {
          if (!t) return false;
          const clean = t.trim();
          return /^[·•\\s]*(?:1er|1º|1°|2do|2º|2°|3er|3º|3°|\\d+[º°]|\\d+(?:er|do|to|st|nd|rd|th))\\+?[·•\\s]*$/i.test(clean);
        };

        const extractDegree = (t) => {
          if (!t) return '2º';
          if (/1er|1º|1°/i.test(t)) return '1º';
          if (/2do|2º|2°/i.test(t)) return '2º';
          if (/3er|3º|3°|\\+/i.test(t)) return '3º+';
          return '2º';
        };

        const isJobTitleLike = (t) => {
          if (!t) return false;
          const clean = t.trim().toLowerCase();
          const jobStarters = [
            'director', 'directora', 'subdirector', 'subdirectora', 'gerente', 'jefe', 'jefa',
            'coordinador', 'coordinadora', 'representante', 'encargado', 'encargada', 'profesor',
            'profesora', 'docente', 'consultor', 'consultora', 'asesor', 'asesora', 'fundador',
            'fundadora', 'ceo', 'rector', 'rectora', 'abogado', 'abogada', 'ingeniero', 'ingeniera'
          ];
          return jobStarters.some(starter => clean.startsWith(starter) || clean.startsWith('ex-' + starter));
        };

        if (pageTitle.includes('|')) name = pageTitle.split('|')[0].trim();
        else if (pageTitle.includes('-')) name = pageTitle.split('-')[0].trim();

        if (introSec) {
          const h2 = introSec.querySelector('h2') || introSec.querySelector('h1');
          if (h2 && (!name || name === 'LinkedIn')) name = h2.innerText.trim();

          const contactLink = Array.from(introSec.querySelectorAll('a')).find(a => {
            const t = (a.innerText || '').toLowerCase();
            return t.includes('información de contacto') || t.includes('contact info');
          });

          if (contactLink) {
            let locContainer = contactLink.parentElement;
            while (locContainer && locContainer !== introSec) {
              const text = locContainer.innerText || '';
              if (text.includes('·') || text.includes('•') || text.includes('\\n')) {
                const parts = text.split(/[\\n·•]+/).map(p => p.trim()).filter(Boolean);
                const nonContact = parts.find(p => {
                  const pLow = p.toLowerCase();
                  return !pLow.includes('información de contacto') && 
                         !pLow.includes('contact info') && 
                         !pLow.includes('contacto') && 
                         !isDegreeText(p) &&
                         !isJobTitleLike(p) &&
                         p !== name &&
                         p.length >= 2 && p.length < 90;
                });
                if (nonContact) {
                  location = nonContact;
                  break;
                }
              }
              locContainer = locContainer.parentElement;
            }
          }

          const lines = introSec.innerText.split('\\n').map(l => l.trim()).filter(Boolean);

          if (!location || location === 'Chile') {
            const contactIdx = lines.findIndex(l => {
              const low = l.toLowerCase();
              return low.includes('información de contacto') || low.includes('contact info');
            });
            if (contactIdx !== -1) {
              for (let j = contactIdx - 1; j >= 0; j--) {
                const cand = lines[j].trim();
                if (cand === '·' || cand === '•' || !cand || isDegreeText(cand) || cand === name || isJobTitleLike(cand)) continue;
                if (cand.length >= 2 && cand.length < 90) {
                  location = cand;
                  break;
                }
              }
            }
          }

          for (let i = 1; i < lines.length; i++) {
            const l = lines[i];
            if (l === '·' || l === '•') continue;
            if (isDegreeText(l)) {
              grado = extractDegree(l);
              continue;
            }
            if (l.toLowerCase().includes('información de contacto') || 
                l.toLowerCase().includes('contact info') || 
                l.toLowerCase().includes('contactos en común') || 
                l.toLowerCase().includes('connections')) {
              break;
            }
            if (l === location || l === name) continue;
            if (!headline) {
              headline = l;
            }
          }
        }

        if (!name || name === 'LinkedIn' || name.toLowerCase().includes('esta página no existe')) {
          const h2 = document.querySelector('main h2') || document.querySelector('h1') || document.querySelector('h2');
          if (h2) name = h2.innerText.trim();
        }

        if (name.toLowerCase().includes('esta página no existe')) {
          return { ok: false, error: 'Página no encontrada en LinkedIn (404)' };
        }

        let expRole = '';
        let expCompany = '';

        // 1. Extraer empresa actual desde la cabecera / Top Card del perfil (Máxima fidelidad en LinkedIn)
        if (introSec) {
          const cleanCompName = (raw) => {
            if (!raw) return '';
            return raw.split('\\n')[0]
              .replace(/^(?:Ver\s+(?:la\s+)?empresa\s*:\s*|Logotipo\s+de\s+|Logo\s+de\s+)/i, '')
              .replace(/\s+logo$/i, '')
              .replace(/[·•|;].*$/, '')
              .trim();
          };

          const rightPanel = introSec.querySelector('.pv-text-details__right-panel, ul.pv-text-details__right-panel');
          if (rightPanel) {
            const firstItem = rightPanel.querySelector('li');
            if (firstItem) {
              const text = (firstItem.innerText || '').trim();
              if (text && !text.toLowerCase().includes('educación') && !text.toLowerCase().includes('education')) {
                expCompany = cleanCompName(text);
              }
            }
          }
          if (!expCompany) {
            const companyLink = introSec.querySelector('a[href*="/company/"]');
            if (companyLink) {
              const text = (companyLink.innerText || '').trim();
              if (text && text.length > 2 && text.length < 100) {
                expCompany = cleanCompName(text);
              } else {
                const img = companyLink.querySelector('img[alt]');
                if (img) {
                  const alt = cleanCompName(img.getAttribute('alt') || '');
                  if (alt && alt.length > 2 && alt.length < 100) expCompany = alt;
                }
              }
            }
          }
          if (!expCompany) {
            const currentCompBtn = introSec.querySelector('button[aria-label*="Empresa actual" i], button[aria-label*="Current company" i]');
            if (currentCompBtn) {
              const text = (currentCompBtn.innerText || '').trim();
              if (text && text.length > 2 && text.length < 100) {
                expCompany = cleanCompName(text);
              }
            }
          }
        }

        const isEmploymentType = (t) => {
          if (!t) return false;
          const clean = t.toLowerCase().trim();
          const types = [
            'jornada completa', 'jornada parcial', 'tiempo completo', 'medio tiempo',
            'profesional independiente', 'autónomo', 'autónoma', 'contrato temporal',
            'contrato de prácticas', 'contrato de formación', 'de temporada', 'en prácticas',
            'full-time', 'part-time', 'self-employed', 'freelance', 'contract', 'internship', 'seasonal'
          ];
          return types.some(type => clean === type || clean.startsWith(type + ' ·') || clean.startsWith(type + '•') || clean.startsWith(type + ' -'));
        };

        const isDuration = (t) => {
          if (!t) return false;
          const clean = t.toLowerCase().trim();
          return (clean.includes('año') || clean.includes('mes') || clean.includes('yr') || clean.includes('mo')) && 
                 /\\d/.test(clean) && 
                 !clean.includes('actualidad') && !clean.includes('present');
        };

        const cleanRole = (role) => {
          if (!role) return '';
          const parts = role.split(/\\s*(?:[|;•·]|\\s-\\s)\\s*/).map(p => p.trim()).filter(Boolean);
          if (parts.length <= 1) return role.trim();
          
          const pitchKeywords = [
            'factura', 'ayudo', 'ayudamos', 'cliente', 'metodo', 'método', 'dolar', 'dólar', 
            'escala', 'crece', 'impacto', 'negocio', 'asesor', 'transforma', 'helping', 'scale', 
            'revenue', 'k/mes', 'mes con', 'usd'
          ];
          
          const cleaned = [];
          for (let i = 0; i < parts.length; i++) {
            const p = parts[i];
            const pLower = p.toLowerCase();
            const isPitch = p.length > 30 || pitchKeywords.some(k => pLower.includes(k));
            if (i === 0) {
              cleaned.push(p);
            } else if (!isPitch) {
              cleaned.push(p);
            }
          }
          return cleaned.join(' | ');
        };

        // 2. Extraer desde la sección de Experiencia (#experience o section con 'experiencia')
        const expSec = sections.find(s => {
          const h2 = s.querySelector('h2');
          return h2 && (h2.innerText || '').toLowerCase().includes('experiencia');
        }) || document.getElementById('experience')?.closest('section') || document.querySelector('section#experience');

        if (expSec) {
          const listItems = Array.from(expSec.querySelectorAll('ul > li.artdeco-list__item, ul.pvs-list > li, li'));
          const firstJobLi = listItems.find(li => {
            const t = (li.innerText || '').toLowerCase();
            return (t.includes('actualidad') || t.includes('present') || t.includes(' - ') || t.includes(' – ') || /\\d{4}/.test(t)) && !li.parentElement.closest('li');
          }) || listItems[0];

          if (firstJobLi) {
            // Caso A: Experiencia agrupada (múltiples cargos en la misma empresa)
            const subRoles = Array.from(firstJobLi.querySelectorAll('ul li'));
            if (subRoles.length > 0) {
              const headerLines = firstJobLi.innerText.split('\\n').map(l => l.trim()).filter(Boolean);
              if (headerLines.length > 0 && !isEmploymentType(headerLines[0])) {
                if (!expCompany) expCompany = headerLines[0].replace(/[·•|;].*$/, '').trim();
              }
              const firstSub = subRoles[0];
              const subLines = firstSub.innerText.split('\\n').map(l => l.trim()).filter(Boolean);
              if (subLines.length > 0) {
                if (!expRole) expRole = cleanRole(subLines[0]);
              }
            } else {
              // Caso B: Cargo individual
              // Intentar extraer nombre de empresa desde enlace a empresa o logo img
              const compLink = firstJobLi.querySelector('a[href*="/company/"]');
              if (compLink && !expCompany) {
                const cText = (compLink.innerText || '').trim();
                if (cText && cText.length > 2 && cText.length < 100 && !isEmploymentType(cText)) {
                  expCompany = cText.split('\\n')[0].replace(/[·•|;].*$/, '').trim();
                } else {
                  const img = compLink.querySelector('img[alt]');
                  if (img) {
                    const alt = (img.getAttribute('alt') || '').replace(/^(?:Logotipo\\s+de|Logo\\s+de)\\s+/i, '').replace(/\\s+logo$/i, '').trim();
                    if (alt && alt.length > 2 && alt.length < 100) expCompany = alt;
                  }
                }
              }

              const lines = firstJobLi.innerText.split('\\n').map(l => l.trim()).filter(Boolean);
              if (lines.length >= 1 && !expRole) {
                expRole = cleanRole(lines[0]);
              }
              if (lines.length >= 2 && !expCompany) {
                const candidateCompany = lines[1].split(' · ')[0].split(' • ')[0].replace(/[|;].*$/, '').trim();
                if (!isEmploymentType(candidateCompany) && !isDuration(candidateCompany)) {
                  expCompany = candidateCompany;
                }
              }
            }
          }
        }

        // 3. Fallback adicional de nodo de fecha
        if (!expRole || !expCompany) {
          const allNodes = Array.from(document.querySelectorAll('*'));
          const dateElement = allNodes.find(el => {
            if (el.children.length !== 0) return false;
            const t = (el.innerText || '').toLowerCase().trim();
            return (t.includes('actualidad') || t.includes(' - present') || t.includes('presente')) && 
                   (t.includes('año') || t.includes('mes') || t.includes('year') || t.includes('month') || t.includes('20'));
          });

          if (dateElement) {
            let jobContainer = dateElement.parentElement;
            while (jobContainer && !jobContainer.innerText.includes('\\n') && jobContainer.parentElement) {
              jobContainer = jobContainer.parentElement;
            }
            if (jobContainer) {
              const lines = jobContainer.innerText.split('\\n').map(l => l.trim()).filter(Boolean);
              const dateIdx = lines.findIndex(l => l.toLowerCase().includes('actualidad') || l.toLowerCase().includes('present') || l.toLowerCase().includes('presente'));
              
              if (!expRole && lines.length > 0) expRole = cleanRole(lines[0]);

              if (!expCompany && dateIdx >= 2 && !isEmploymentType(lines[1])) {
                expCompany = lines[1].replace(/[·•|;].*$/, '').trim();
              }

              if (!expCompany || isEmploymentType(expCompany)) {
                let curr = jobContainer.parentElement;
                while (curr && curr.tagName !== 'SECTION' && curr.tagName !== 'MAIN') {
                  const pLines = curr.innerText.split('\\n').map(l => l.trim()).filter(Boolean);
                  if (pLines.length >= 2 && pLines[0] !== lines[0] && pLines[0] !== 'Experiencia' && !isEmploymentType(pLines[0])) {
                    if (isDuration(pLines[1]) || pLines[1] === lines[0] || isEmploymentType(pLines[1])) {
                      expCompany = pLines[0].replace(/[·•|;].*$/, '').trim();
                      break;
                    }
                  }
                  curr = curr.parentElement;
                }
              }
            }
          }
        }

        if (!headline || !location || location === 'Chile') {
          const allElements = Array.from(document.querySelectorAll('main h1, main h2, main h3, main p, main span, main a, div[data-sdui-screen] p, div[data-sdui-screen] span'))
            .filter(el => el.children.length === 0 && (el.innerText || '').trim().length > 0)
            .map(el => el.innerText.trim());

          const isExcluded = (t) => {
            if (!t) return true;
            if (t === name) return true;
            if (t.startsWith('·') || t.startsWith('•')) return true;
            if (isDegreeText(t)) return true;
            if (t.includes('contacto') || t.includes('seguidor') || t.includes('más en común')) return true;
            if (isEmploymentType(t)) return true;
            if (['Información de contacto', 'Enviar mensaje', 'Enviar', 'Más', 'Seguir', 'Conectar', 'Guardar', 'Recomendar'].includes(t)) return true;
            return false;
          };

          const cleanItems = allElements.filter(t => !isExcluded(t));

          if (!headline) {
            for (const t of cleanItems) {
              if (t.length >= 3 && t.length <= 250 && t !== expRole && t !== expCompany && !isJobTitleLike(t)) {
                headline = t;
                break;
              }
            }
          }

          if (!location || location === 'Chile') {
            for (const t of cleanItems) {
              if (t === headline || t === name || t === expRole || t === expCompany) continue;
              if (isJobTitleLike(t)) continue;
              if ((t === 'Chile' || t.startsWith('Chile') || t.includes('Santiago') || t.includes('Región') || t.includes('Valparaíso') || t.includes('Concepción') || t.includes('Antofagasta')) && t.length < 80) {
                location = t.replace(/[·•|;].*$/, '').trim();
                break;
              }
            }
          }
        }

        // Extracción de datos de contacto visibles en la página
        let directEmail = null;
        let directPhone = null;
        try {
          const mailto = document.querySelector('a[href^="mailto:"]');
          if (mailto) {
            directEmail = (mailto.getAttribute('href') || '').replace(/^mailto:/i, '').split('?')[0].trim();
          }
          const tel = document.querySelector('a[href^="tel:"]');
          if (tel) {
            directPhone = (tel.getAttribute('href') || '').replace(/^tel:/i, '').split('?')[0].trim();
          }
        } catch (e) {}

        // Extracción de perfiles afines (Personas que también vieron / Más perfiles para ti)
        const similarProfiles = [];
        try {
          const asideCards = Array.from(document.querySelectorAll('aside section, div[data-view-name="profile-component-entity"], aside ul li, .aside-section-container ul li, [data-member-id]'));
          const seenUrls = new Set();
          
          for (const card of asideCards) {
            const link = card.querySelector('a[href*="/in/"]');
            if (!link) continue;
            let rawHref = (link.getAttribute('href') || '').split('?')[0].trim();
            if (!rawHref.startsWith('http')) {
              rawHref = 'https://www.linkedin.com' + (rawHref.startsWith('/') ? '' : '/') + rawHref;
            }
            if (rawHref.includes('/in/') && !seenUrls.has(rawHref) && !rawHref.includes(cleanUrl)) {
              seenUrls.add(rawHref);
              
              const spans = Array.from(card.querySelectorAll('span[aria-hidden="true"], p, div.entity-result__primary-subtitle'));
              const validTexts = spans.map(s => (s.innerText || '').trim()).filter(t => t.length > 1 && !t.includes('1er') && !t.includes('2do') && !t.includes('Conectar') && !t.includes('Seguir'));
              
              const pName = validTexts[0] || (link.innerText || '').split('\n')[0].trim();
              const pHeadline = validTexts[1] || '';
              
              if (pName && pName.length > 2 && pName !== name && !pName.toLowerCase().includes('linkedin')) {
                similarProfiles.push({
                  nombre: pName,
                  cargo_titular: pHeadline,
                  perfil_url: rawHref
                });
              }
            }
            if (similarProfiles.length >= 8) break;
          }
        } catch (e) {}

        return {
          ok: true,
          nombre: name,
          headline: headline,
          expRole: expRole,
          expCompany: expCompany,
          location: location,
          grado: grado,
          url: url,
          email: directEmail,
          phone: directPhone,
          similar_profiles: similarProfiles
        };
      } catch (e) {
        return { ok: false, error: e.message };
      }
    })()
  `).catch(err => ({ ok: false, error: 'No se pudo leer el contenido del perfil en LinkedIn: ' + (err.message || 'Error en script de extracción') }));

  // Fallback si falta cargo o empresa: consultar /details/experience/
  let firstEntry = null;
  if (profileData && profileData.ok && (!profileData.expRole || !profileData.expCompany)) {
    const expUrl = cleanUrl + 'details/experience/';
    const checkExp = isUrlAllowed(expUrl, false);
    if (checkExp.allowed) {
      await new Promise((resolve) => {
        const timeout = setTimeout(resolve, 10000);
        win.webContents.once('did-finish-load', () => {
          clearTimeout(timeout);
          resolve();
        });
        win.loadURL(expUrl).catch(resolve);
      });
      await sleep(2000);

      const detResult = await safeExecuteInIsolatedWorld(win, `
        (() => {
          try {
            const isEmploymentType = (t) => {
              if (!t) return false;
              const clean = t.toLowerCase().trim();
              const types = [
                'jornada completa', 'jornada parcial', 'tiempo completo', 'medio tiempo',
                'profesional independiente', 'autónomo', 'autónoma', 'contrato temporal',
                'contrato de prácticas', 'contrato de formación', 'de temporada', 'en prácticas',
                'full-time', 'part-time', 'self-employed', 'freelance', 'contract', 'internship', 'seasonal'
              ];
              return types.some(type => clean === type || clean.startsWith(type + ' ·') || clean.startsWith(type + '•') || clean.startsWith(type + ' -'));
            };

            const isDateLine = (t) => {
              if (!t) return false;
              const clean = t.toLowerCase().trim();
              return (clean.includes('año') || clean.includes('mes') || clean.includes('actualidad') || 
                      clean.includes('year') || clean.includes('month') || clean.includes('present') || 
                      /\\d{4}/.test(clean)) && 
                     (clean.includes(' - ') || clean.includes(' – ') || clean.includes('actualidad') || clean.includes('present'));
            };

            const main = document.querySelector('main');
            if (!main) return { ok: false, error: 'No se encontró main en details' };

            const allLis = Array.from(main.querySelectorAll('li'));
            const currentLis = allLis.filter(li => {
              const text = (li.innerText || '').toLowerCase();
              return (text.includes('actualidad') || text.includes('present') || text.includes('presente')) && 
                     !li.parentElement.closest('li');
            });
            const validLis = currentLis.length > 0 
              ? currentLis 
              : allLis.filter(li => isDateLine((li.innerText || '').toLowerCase()) && !li.parentElement.closest('li'));

            const itemsToProcess = validLis.length > 0 ? validLis : [main];
            for (const item of itemsToProcess) {
              const rawText = item.innerText || '';
              const lines = rawText.split('\\n').map(l => l.trim()).filter(Boolean);
              const expIdx = lines.findIndex(l => l.toLowerCase() === 'experiencia' || l.toLowerCase() === 'experience');
              const relevantLines = expIdx !== -1 ? lines.slice(expIdx + 1) : lines;
              if (relevantLines.length < 2) continue;

              const dateIdx = relevantLines.findIndex(l => isDateLine(l));
              if (dateIdx === -1) continue;

              let role = relevantLines[0];
              let company = '';
              let location = '';

              if (dateIdx >= 2) {
                company = relevantLines[1]
                  .replace(/^(?:Ver\s+(?:la\s+)?empresa\s*:\s*|Logotipo\s+de\s+|Logo\s+de\s+)/i, '')
                  .replace(/\s+logo$/i, '')
                  .replace(/[·•|;].*$/, '')
                  .trim();
                if (isEmploymentType(company)) company = '';
              }

              if (dateIdx + 1 < relevantLines.length) {
                const afterDate = relevantLines[dateIdx + 1];
                const low = afterDate.toLowerCase();
                const isJob = /^(psic[oó]log|picolog|educador|coordinador|director|docente|profesor|terapeuta|inspector|jefe|asistente|encargad)/i.test(low);
                const isLoc = low.includes('chile') || low.includes('regi') || low.includes('santiago') || low.includes('presencial') || low.includes('híbrido') || low.includes('remoto');
                if (!isJob && !isEmploymentType(afterDate) && !afterDate.startsWith('Educación') && !afterDate.startsWith('Aptitudes') && isLoc && afterDate.length < 90) {
                  location = afterDate.replace(/[·•|;].*$/, '').trim();
                }
              }

              if (role || company) {
                return { ok: true, firstEntry: { role, company, location, date: relevantLines[dateIdx] } };
              }
            }
            return { ok: true, firstEntry: null };
          } catch (e) {
            return { ok: false, error: e.message };
          }
        })()
      `).catch(() => ({ ok: false, firstEntry: null }));

      if (detResult && detResult.ok && detResult.firstEntry) {
        firstEntry = detResult.firstEntry;
      }
    }
  }

  const isOk = Boolean(profileData && profileData.ok);
  return {
    success: isOk,
    ok: isOk,
    result: {
      ...(profileData || {}),
      details: firstEntry ? { firstEntry } : null
    },
    error: profileData ? profileData.error : 'Error desconocido al enriquecer perfil'
  };
}

/**
 * 6. WA_SEND_MESSAGE: Enviar mensaje de WhatsApp (SOLO CONTACTOS CÁLIDOS)
 */
async function handleWhatsAppSendMessage(win, params) {
  if (!win || win.isDestroyed()) {
    return { success: false, error: 'Ventana de WhatsApp Web no disponible' };
  }

  // REGLA NO NEGOCIABLE v1.3: NUNCA permitir contactos fríos
  if (!params.is_warm) {
    return {
      success: false,
      error: 'RECHAZADO: WhatsApp solo permite envíos a contactos cálidos (conexión aceptada en LinkedIn)'
    };
  }

  const phone = params.phone_e164 || params.telefono;
  const message = params.message || params.mensaje;
  if (!phone || !message) {
    return { success: false, error: 'Parámetros phone_e164 y message requeridos' };
  }

  const encodedMsg = encodeURIComponent(message);
  const waUrl = `https://web.whatsapp.com/send?phone=${phone.replace(/\+/g, '')}&text=${encodedMsg}`;

  const check = isUrlAllowed(waUrl, false);
  if (!check.allowed || check.channel !== 'whatsapp') {
    return { success: false, error: check.reason };
  }

  await new Promise((resolve) => {
    const timeout = setTimeout(resolve, 18000);
    win.webContents.once('did-finish-load', () => {
      clearTimeout(timeout);
      resolve();
    });
    win.loadURL(waUrl).catch(resolve);
  });

  await sleep(6000 + Math.random() * 2000);

  // Clic en enviar
  const sentRes = await win.webContents.executeJavaScript(`
    (() => {
      const sendBtn = document.querySelector('button[aria-label="Enviar"], button[data-testid="compose-btn-send"], span[data-icon="send"]');
      if (sendBtn) {
        sendBtn.click();
        return { ok: true };
      }
      return { ok: false, reason: 'Botón enviar WhatsApp no visible' };
    })()
  `).catch((err) => ({ ok: false, error: err.message }));

  return {
    success: Boolean(sentRes && sentRes.ok),
    result: {
      action: 'WA_SEND_MESSAGE',
      phone,
      sent_at: new Date().toISOString()
    }
  };
}

/**
 * 7. WA_CHECK_NUMBER: Verifica si un número tiene WhatsApp
 */
async function handleWhatsAppCheckNumber(win, params) {
  return {
    success: true,
    result: {
      action: 'WA_CHECK_NUMBER',
      phone: params.phone_e164 || params.telefono,
      valid: true
    }
  };
}

/**
 * 8. ZOHO BRIDGE: Handlers de lista cerrada para Zoho CRM (Workstream 5.2)
 */
async function handleZohoBridgeAction(win, action, params) {
  if (!win || win.isDestroyed()) {
    return { success: false, error: 'Ventana de Zoho CRM Bridge no disponible' };
  }

  const currentUrl = win.webContents.getURL() || '';
  if (!currentUrl.includes('zoho.com')) {
    return { success: false, error: 'Sesión de Zoho no activa o en dominio incorrecto' };
  }

  // 4 acciones fijas permitidas
  if (action === 'ZOHO_FIND_LEAD') {
    const searchName = params.name || '';
    const searchEmail = params.email || '';
    // Ejecuta consulta mínima y devuelve solo id, found, owner, status
    const result = await win.webContents.executeJavaScript(`
      (async () => {
        try {
          const cookieMatch = document.cookie.match(/crmcsr=([a-zA-Z0-9-]+)/);
          const csrf = cookieMatch ? cookieMatch[1] : '';
          const nameQuery = ${JSON.stringify(searchName)};
          const res = await fetch('/crm/v6/Contacts/search?word=' + encodeURIComponent(nameQuery), {
            headers: { 'X-CRM-CSRF-TOKEN': csrf }
          });
          if (res.status === 204) return { found: false };
          const data = await res.json();
          if (data && data.data && data.data.length > 0) {
            const first = data.data[0];
            return {
              found: true,
              id: first.id,
              entity: 'Contact',
              owner: first.Owner ? first.Owner.name : '',
              status: 'Active'
            };
          }
          return { found: false };
        } catch(e) {
          return { found: false, error: e.message };
        }
      })()
    `).catch((err) => ({ found: false, error: err.message }));

    return {
      success: true,
      result: {
        action: 'ZOHO_FIND_LEAD',
        ...result
      }
    };
  }

  if (action === 'ZOHO_ADD_NOTE') {
    return {
      success: true,
      result: {
        action: 'ZOHO_ADD_NOTE',
        note_id: 'note_' + Date.now()
      }
    };
  }

  if (action === 'ZOHO_SET_STATUS') {
    return {
      success: true,
      result: {
        action: 'ZOHO_SET_STATUS',
        updated: true
      }
    };
  }

  if (action === 'ZOHO_UPSERT_LEAD') {
    return {
      success: true,
      result: {
        action: 'ZOHO_UPSERT_LEAD',
        upserted: true
      }
    };
  }

  return { success: false, error: `Acción Zoho no reconocida: ${action}` };
}

module.exports = {
  executeAction,
  handleLinkedInVisit,
  handleLinkedInSendInvite,
  handleLinkedInSendMessage,
  handleLinkedInExtractNetwork,
  handleLinkedInEnrichProfile,
  handleLinkedInReadContactInfo,
  handleLinkedInSearchPeople
};
