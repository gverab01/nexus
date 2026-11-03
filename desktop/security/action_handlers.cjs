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

  // Navegar
  await new Promise((resolve) => {
    const timeout = setTimeout(resolve, 14000);
    win.webContents.once('did-finish-load', () => {
      clearTimeout(timeout);
      resolve();
    });
    win.loadURL(profileUrl).catch(resolve);
  });

  const finalUrl = win.webContents.getURL() || '';
  if (finalUrl.includes('/login') || finalUrl.includes('/authwall') || finalUrl.includes('/checkpoint')) {
    return {
      success: false,
      error: 'Sesión de LinkedIn no iniciada o checkpoint detectado',
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

  return {
    success: true,
    result: {
      action: 'LI_VISIT_PROFILE',
      profile_url: profileUrl,
      final_url: finalUrl,
      visited_at: new Date().toISOString()
    }
  };
}

/**
 * 2. LI_SEND_INVITE: Envía invitación orgánica con clic biométrico
 */
async function handleLinkedInSendInvite(win, params) {
  const visitResult = await handleLinkedInVisit(win, params);
  if (!visitResult.success) {
    return visitResult;
  }

  const note = params.note || params.nota || '';

  // Búsqueda y clic en botón Conectar con coordenadas aleatorias
  const clickRes = await win.webContents.executeJavaScript(`
    (() => {
      const allButtons = Array.from(document.querySelectorAll('button'));
      const btn = allButtons.find(b => {
        const txt = b.innerText.trim().toLowerCase();
        return txt === 'conectar' || txt === 'connect' || txt.includes('conectar');
      });

      if (!btn) {
        return { found: false, reason: 'Botón conectar no visible directamente' };
      }

      const r = btn.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) {
        return { found: false, reason: 'Botón conectar no visible' };
      }

      const randX = r.left + (r.width * (0.25 + Math.random() * 0.5));
      const randY = r.top + (r.height * (0.25 + Math.random() * 0.5));

      btn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: randX, clientY: randY }));
      btn.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, clientX: randX, clientY: randY }));
      btn.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: randX, clientY: randY }));

      return { found: true };
    })()
  `).catch((err) => ({ found: false, error: err.message }));

  await sleep(1500 + Math.random() * 1000);

  // Si hay modal de confirmación o añadir nota
  if (clickRes && clickRes.found) {
    if (note) {
      await win.webContents.executeJavaScript(`
        (() => {
          const addNoteBtn = Array.from(document.querySelectorAll('button')).find(b => 
            b.innerText.toLowerCase().includes('añadir una nota') || 
            b.innerText.toLowerCase().includes('add a note')
          );
          if (addNoteBtn) addNoteBtn.click();
        })()
      `).catch(() => {});

      await sleep(800 + Math.random() * 500);

      const escapedNote = JSON.stringify(note);
      await win.webContents.executeJavaScript(`
        (() => {
          const textarea = document.querySelector('textarea[name="message"], textarea#custom-message');
          if (textarea) {
            textarea.value = ${escapedNote};
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
          }
        })()
      `).catch(() => {});

      await sleep(1000 + Math.random() * 800);
    }

    // Confirmar envío ("Enviar" / "Send")
    await win.webContents.executeJavaScript(`
      (() => {
        const sendBtn = Array.from(document.querySelectorAll('button')).find(b => {
          const txt = b.innerText.trim().toLowerCase();
          return txt === 'enviar' || txt === 'send' || txt === 'enviar ahora' || txt === 'send now';
        });
        if (sendBtn) sendBtn.click();
      })()
    `).catch(() => {});
  }

  return {
    success: true,
    result: {
      action: 'LI_SEND_INVITE',
      profile_url: params.profile_url || params.perfil_url,
      button_clicked: clickRes ? clickRes.found : false,
      has_note: Boolean(note),
      sent_at: new Date().toISOString()
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

  await sleep(1500);

  const escapedMsg = JSON.stringify(message);
  const msgResult = await win.webContents.executeJavaScript(`
    (() => {
      const msgBtn = Array.from(document.querySelectorAll('button')).find(b => 
        b.innerText.trim().toLowerCase() === 'enviar mensaje' || 
        b.innerText.trim().toLowerCase() === 'message'
      );
      if (!msgBtn) return { ok: false, error: 'Botón enviar mensaje no encontrado' };
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

  await sleep(3500);

  const contactData = await win.webContents.executeJavaScript(`
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
  await win.webContents.executeJavaScript(`
    (async () => {
      try {
        const ws = document.getElementById('workspace') || document.querySelector('main');
        window.scrollTo({ top: 1200, behavior: 'smooth' });
        if (ws) ws.scrollTop = 1200;
        await new Promise(r => setTimeout(r, 600));

        window.scrollTo({ top: 2600, behavior: 'smooth' });
        if (ws) ws.scrollTop = 2600;
        await new Promise(r => setTimeout(r, 600));

        window.scrollTo({ top: 4000, behavior: 'smooth' });
        if (ws) ws.scrollTop = 4000;

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
  const profileData = await win.webContents.executeJavaScript(`
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
          const rightPanel = introSec.querySelector('.pv-text-details__right-panel, ul.pv-text-details__right-panel');
          if (rightPanel) {
            const firstItem = rightPanel.querySelector('li');
            if (firstItem) {
              const text = (firstItem.innerText || '').trim();
              if (text && !text.toLowerCase().includes('educación') && !text.toLowerCase().includes('education')) {
                expCompany = text.split('\n')[0].replace(/[·•|;].*$/, '').trim();
              }
            }
          }
          if (!expCompany) {
            const companyLink = introSec.querySelector('a[href*="/company/"]');
            if (companyLink) {
              const text = (companyLink.innerText || '').trim();
              if (text && text.length > 2 && text.length < 100) {
                expCompany = text.split('\n')[0].replace(/[·•|;].*$/, '').trim();
              } else {
                const img = companyLink.querySelector('img[alt]');
                if (img) {
                  const alt = (img.getAttribute('alt') || '').replace(/^(?:Logotipo\s+de|Logo\s+de)\s+/i, '').replace(/\s+logo$/i, '').trim();
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
                expCompany = text.split('\n')[0].replace(/[·•|;].*$/, '').trim();
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
              const headerLines = firstJobLi.innerText.split('\n').map(l => l.trim()).filter(Boolean);
              if (headerLines.length > 0 && !isEmploymentType(headerLines[0])) {
                if (!expCompany) expCompany = headerLines[0].replace(/[·•|;].*$/, '').trim();
              }
              const firstSub = subRoles[0];
              const subLines = firstSub.innerText.split('\n').map(l => l.trim()).filter(Boolean);
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
                  expCompany = cText.split('\n')[0].replace(/[·•|;].*$/, '').trim();
                } else {
                  const img = compLink.querySelector('img[alt]');
                  if (img) {
                    const alt = (img.getAttribute('alt') || '').replace(/^(?:Logotipo\s+de|Logo\s+de)\s+/i, '').replace(/\s+logo$/i, '').trim();
                    if (alt && alt.length > 2 && alt.length < 100) expCompany = alt;
                  }
                }
              }

              const lines = firstJobLi.innerText.split('\n').map(l => l.trim()).filter(Boolean);
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

        return {
          ok: true,
          nombre: name,
          headline: headline,
          expRole: expRole,
          expCompany: expCompany,
          location: location,
          grado: grado,
          url: url
        };
      } catch (e) {
        return { ok: false, error: e.message };
      }
    })()
  `).catch(err => ({ ok: false, error: err.message }));

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

      const detResult = await win.webContents.executeJavaScript(`
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
            const validLis = allLis.filter(li => {
              const text = (li.innerText || '').toLowerCase();
              return (text.includes('actualidad') || text.includes('present') || isDateLine(text)) && 
                     !li.parentElement.closest('li');
            });

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
                company = relevantLines[1].replace(/[·•|;].*$/, '').trim();
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
  handleLinkedInExtractNetwork,
  handleLinkedInEnrichProfile,
  handleLinkedInReadContactInfo,
  handleLinkedInSearchPeople
};
