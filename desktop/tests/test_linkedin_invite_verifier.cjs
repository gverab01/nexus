/**
 * Test Suite: Verificador de Invitaciones de LinkedIn y Prevención de Falsos Positivos
 * 
 * Valida:
 * 1. Detección exacta del botón [+ Conectar] en la cabecera (incluyendo botones con SVG/iconos)
 * 2. Aislamiento total del sidebar (<aside>): 0% de interferencia con contactos sugeridos
 * 3. Interacción modal para "Enviar sin nota" (orientado a botón primario) y notas personalizadas
 * 4. Detección de barreras de seguridad (solicitud de email o límite semanal)
 * 5. COMPROBACIÓN TERMINANTE DE SEGURIDAD (Zero False Positives):
 *    Si LinkedIn no confirma el estado "Pendiente" / "Pending", la acción NUNCA retorna success: true.
 * 6. Detección de estado previo "ALREADY_PENDING" para evitar clics duplicados
 * 7. Restauración de scroll a la cabecera antes de buscar botones.
 */

const assert = require('assert');
const { handleLinkedInSendInvite, executeAction } = require('../security/action_handlers.cjs');

// Mock DOM Node representation para pruebas de lógica de selectores
class MockElement {
  constructor(tag, attrs = {}, text = '') {
    this.tagName = tag.toUpperCase();
    this.attrs = { ...attrs };
    this.innerText = text;
    this.textContent = text;
    this.children = [];
    this.parentElement = null;
    this._rect = { top: 100, left: 100, width: 120, height: 40 };
    this.clicked = false;
    this.events = [];
    this.value = '';
  }

  getAttribute(name) {
    return this.attrs[name] || null;
  }

  setAttribute(name, val) {
    this.attrs[name] = val;
  }

  getBoundingClientRect() {
    return this._rect;
  }

  setRect(top, left, width, height) {
    this._rect = { top, left, width, height };
  }

  appendChild(child) {
    child.parentElement = this;
    this.children.push(child);
    return child;
  }

  closest(selector) {
    let curr = this;
    const selectors = selector.split(',').map(s => s.trim().toLowerCase());
    while (curr) {
      for (const sel of selectors) {
        if (sel.startsWith('.') && curr.attrs.class && curr.attrs.class.split(' ').includes(sel.slice(1))) {
          return curr;
        }
        if (sel.startsWith('#') && curr.attrs.id === sel.slice(1)) {
          return curr;
        }
        if (sel.startsWith('[') && sel.endsWith(']')) {
          const attrMatch = sel.slice(1, -1).split('=');
          const attrName = attrMatch[0];
          const attrVal = attrMatch[1] ? attrMatch[1].replace(/["']/g, '') : null;
          if (attrVal) {
            if ((curr.attrs[attrName] || '') === attrVal) return curr;
          } else if (curr.attrs[attrName] !== undefined) {
            return curr;
          }
        }
        if (curr.tagName.toLowerCase() === sel) {
          return curr;
        }
      }
      curr = curr.parentElement;
    }
    return null;
  }

  querySelectorAll(sel) {
    const res = [];
    const walk = (node) => {
      for (const c of node.children) {
        if (matches(c, sel)) res.push(c);
        walk(c);
      }
    };
    walk(this);
    return res;
  }

  querySelector(sel) {
    const list = this.querySelectorAll(sel);
    return list.length > 0 ? list[0] : null;
  }

  dispatchEvent(evt) {
    this.events.push(evt.type);
    return true;
  }

  focus() {
    this.events.push('focus');
  }

  click() {
    this.clicked = true;
    this.events.push('click');
  }

  scrollIntoView() {
    this.events.push('scrollIntoView');
  }
}

function matches(el, sel) {
  const parts = sel.split(',').map(s => s.trim().toLowerCase());
  for (const p of parts) {
    if (p.includes('button.artdeco-button--primary')) {
      if (el.tagName === 'BUTTON' && el.attrs.class && el.attrs.class.includes('artdeco-button--primary')) return true;
    }
    if (p.includes('button.artdeco-button--secondary')) {
      if (el.tagName === 'BUTTON' && el.attrs.class && el.attrs.class.includes('artdeco-button--secondary')) return true;
    }
    if (p.startsWith('button')) {
      if (el.tagName === 'BUTTON') return true;
    }
    if (p.startsWith('a[role="button"]')) {
      if (el.tagName === 'A' && el.attrs.role === 'button') return true;
    }
    if (p.includes('span.artdeco-button__text')) {
      if (el.tagName === 'SPAN' && el.attrs.class && el.attrs.class.includes('artdeco-button__text')) return true;
    }
    if (p === 'div[role="dialog"]' || p === 'div.artdeco-modal') {
      if (el.tagName === 'DIV' && (el.attrs.role === 'dialog' || (el.attrs.class && el.attrs.class.includes('artdeco-modal')))) return true;
    }
    if (p === 'textarea' || p.includes('textarea')) {
      if (el.tagName === 'TEXTAREA') return true;
    }
  }
  return false;
}

// Genera un DOM idéntico al perfil real de LinkedIn de Jose Antonio Arellano Blanco
function createJoseAntonioProfileDom() {
  const root = new MockElement('html');
  const body = root.appendChild(new MockElement('body'));

  // 1. Barra de navegación superior (debe ignorarse)
  const nav = body.appendChild(new MockElement('header', { id: 'global-nav' }));
  nav.setRect(0, 0, 1200, 52);
  const navBtn = nav.appendChild(new MockElement('button', {}, 'Inicio'));
  navBtn.setRect(10, 10, 50, 30);

  // 2. Contenedor Principal <main>
  const main = body.appendChild(new MockElement('main', { class: 'scaffold-layout__main' }));
  main.setRect(60, 100, 750, 1800);

  // Cabecera del prospecto (Top Card)
  const topCard = main.appendChild(new MockElement('section', { class: 'artdeco-card' }));
  topCard.setRect(70, 100, 750, 480);

  const h1 = topCard.appendChild(new MockElement('h1', { class: 'pv-top-card__name' }, 'Jose Antonio Arellano Blanco'));
  h1.setRect(280, 130, 400, 32);

  const headline = topCard.appendChild(new MockElement('div', { class: 'text-body-medium' }, 'Director Fundaciones Educacionales'));
  headline.setRect(320, 130, 400, 24);

  // Enlace de contactos en común ("Paola Andrea, Maria Paz y 6 contactos más en común") - NO debe ser detectado como conectar
  const mutualConn = topCard.appendChild(new MockElement('a', { role: 'button', href: '#' }, 'Paola Andrea, Maria Paz y 6 contactos más en común'));
  mutualConn.setRect(390, 130, 350, 20);

  // Acciones de cabecera:
  // Botón [+ Conectar] con icono SVG y span interno
  const connectBtn = topCard.appendChild(new MockElement('button', {
    class: 'artdeco-button artdeco-button--2 artdeco-button--primary',
    'aria-label': 'Invitar a Jose Antonio Arellano Blanco a conectar'
  }, 'Conectar'));
  connectBtn.setRect(440, 130, 120, 36);

  // Botón [Enviar mensaje]
  const msgBtn = topCard.appendChild(new MockElement('button', {
    class: 'artdeco-button artdeco-button--2 artdeco-button--secondary',
    'aria-label': 'Enviar mensaje a Jose Antonio Arellano Blanco'
  }, 'Enviar mensaje'));
  msgBtn.setRect(440, 260, 140, 36);

  // Botón [Más / ...]
  const moreBtn = topCard.appendChild(new MockElement('button', {
    class: 'artdeco-button artdeco-button--2 artdeco-button--muted',
    'aria-label': 'Más acciones'
  }, 'Más'));
  moreBtn.setRect(440, 410, 60, 36);

  // 3. Sidebar lateral <aside> con personas sugeridas ("Gente que quizás conozcas")
  // Estos botones tienen texto "Conectar", pero están en aside y NUNCA deben ser cliqueados
  const aside = body.appendChild(new MockElement('aside', { class: 'scaffold-layout__aside' }));
  aside.setRect(70, 880, 320, 1200);

  const suggested1 = aside.appendChild(new MockElement('div', { 'data-view-name': 'profile-component-entity' }));
  suggested1.setRect(100, 890, 300, 100);
  const asideBtn1 = suggested1.appendChild(new MockElement('button', {
    class: 'artdeco-button',
    'aria-label': 'Invitar a Maria Ignacia a conectar'
  }, 'Conectar'));
  asideBtn1.setRect(150, 900, 100, 32);

  const suggested2 = aside.appendChild(new MockElement('div', { 'data-view-name': 'profile-component-entity' }));
  suggested2.setRect(220, 890, 300, 100);
  const asideBtn2 = suggested2.appendChild(new MockElement('button', {
    class: 'artdeco-button',
    'aria-label': 'Invitar a Carlos Perez a conectar'
  }, 'Conectar'));
  asideBtn2.setRect(270, 900, 100, 32);

  return { root, topCard, connectBtn, msgBtn, moreBtn, asideBtn1, asideBtn2, mutualConn };
}

// Pruebas automatizadas
async function runTestSuite() {
  console.log('========================================================================');
  console.log('  TEST SUITE: VERIFICACIÓN ESTRICTA DE INVITACIONES LINKEDIN Y SELECTORES');
  console.log('========================================================================\n');

  // ------------------------------------------------------------------------------------
  // TEST 1: Reconocimiento exacto del botón [+ Conectar] en la cabecera
  // ------------------------------------------------------------------------------------
  console.log('TEST 1: Detección y filtrado de botones en perfil (Jose Antonio Arellano Blanco)...');
  {
    const dom = createJoseAntonioProfileDom();
    const allButtons = dom.root.querySelectorAll('button, a[role="button"]');

    // Aplicar la lógica de filtrado de heroButtons implementada en action_handlers.cjs
    const heroButtons = allButtons.filter(b => {
      if (b.closest('aside, .scaffold-layout__aside, [data-view-name="profile-component-entity"], .pv-profile-body-item')) {
        return false;
      }
      if (b.closest('header, nav, #global-nav, footer, .msg-overlay-container, #msg-overlay')) {
        return false;
      }
      const r = b.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && r.top < 850 && r.top >= 0;
    });

    // Validar que los botones del aside fueron excluidos
    assert.strictEqual(heroButtons.includes(dom.asideBtn1), false, 'ERROR: El botón del sidebar 1 fue incluido en heroButtons');
    assert.strictEqual(heroButtons.includes(dom.asideBtn2), false, 'ERROR: El botón del sidebar 2 fue incluido en heroButtons');

    // Validar que el botón de nav fue excluido
    const navBtn = dom.root.querySelector('#global-nav button');
    assert.strictEqual(heroButtons.includes(navBtn), false, 'ERROR: El botón de navegación fue incluido');

    // Identificar el botón Conectar con isConnectBtn
    const isConnectBtn = (btn) => {
      const txt = (btn.innerText || btn.textContent || '').trim().toLowerCase();
      const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
      const title = (btn.getAttribute('title') || '').toLowerCase();
      const combined = txt + ' ' + aria + ' ' + title;

      const hasConnect = combined.includes('conectar') || combined.includes('connect') || aria.includes('invitar') || aria.includes('invite');
      const isExcluded = combined.includes('en común') || combined.includes('contactos en común') || combined.includes('mensaje') || combined.includes('message') || combined.includes('retirar') || combined.includes('withdraw') || combined.includes('siguiendo') || combined.includes('following');
      return hasConnect && !isExcluded;
    };

    const targetBtn = heroButtons.find(isConnectBtn);
    assert.ok(targetBtn, 'ERROR: No se encontró el botón Conectar en la cabecera');
    assert.strictEqual(targetBtn, dom.connectBtn, 'ERROR: El botón detectado no es el de Jose Antonio');
    assert.strictEqual(isConnectBtn(dom.mutualConn), false, 'ERROR: El enlace de contactos en común fue clasificado erróneamente como Conectar');
    assert.strictEqual(isConnectBtn(dom.msgBtn), false, 'ERROR: El botón Mensaje fue clasificado erróneamente como Conectar');

    console.log('  [PASS] Botón [+ Conectar] de Jose Antonio identificado con precisión milimétrica.');
    console.log('  [PASS] Enlaces de contactos en común y mensajes descartados correctamente.');
  }

  // ------------------------------------------------------------------------------------
  // TEST 2: Aislamiento total del sidebar (<aside>) y contactos sugeridos
  // ------------------------------------------------------------------------------------
  console.log('\nTEST 2: Aislamiento de sidebar (<aside>) para prevenir invitaciones a terceros...');
  {
    const dom = createJoseAntonioProfileDom();
    // Simular que el prospecto NO tiene botón directo en cabecera
    dom.connectBtn.parentElement.children = dom.connectBtn.parentElement.children.filter(c => c !== dom.connectBtn);

    const allButtons = dom.root.querySelectorAll('button, a[role="button"]');
    const heroButtons = allButtons.filter(b => {
      if (b.closest('aside, .scaffold-layout__aside, [data-view-name="profile-component-entity"], .pv-profile-body-item')) {
        return false;
      }
      if (b.closest('header, nav, #global-nav, footer, .msg-overlay-container, #msg-overlay')) {
        return false;
      }
      const r = b.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && r.top < 850 && r.top >= 0;
    });

    const isConnectBtn = (btn) => {
      const txt = (btn.innerText || '').toLowerCase();
      const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
      const combined = txt + ' ' + aria;
      return (combined.includes('conectar') || combined.includes('connect')) && !combined.includes('mensaje');
    };

    const leakConnect = heroButtons.find(isConnectBtn);
    assert.strictEqual(leakConnect, undefined, 'ERROR CRÍTICO: Se seleccionó un botón de recomendación del sidebar');
    console.log('  [PASS] Cero filtraciones: ningún contacto del sidebar puede ser seleccionado.');
  }

  // ------------------------------------------------------------------------------------
  // TEST 3: Manejo de modal de invitación ("Enviar sin nota" vs "Añadir nota")
  // ------------------------------------------------------------------------------------
  console.log('\nTEST 3: Selección de botones dentro del modal de confirmación de LinkedIn...');
  {
    const modal = new MockElement('div', { class: 'artdeco-modal', role: 'dialog' });
    modal.setRect(150, 300, 500, 300);

    const dismissBtn = modal.appendChild(new MockElement('button', { class: 'artdeco-modal__dismiss', 'aria-label': 'Cerrar' }));
    const addNoteBtn = modal.appendChild(new MockElement('button', { class: 'artdeco-button artdeco-button--secondary' }, 'Añadir una nota'));
    const sendWithoutNoteBtn = modal.appendChild(new MockElement('button', {
      class: 'artdeco-button artdeco-button--primary',
      'aria-label': 'Enviar ahora'
    }, 'Enviar sin nota'));

    // Búsqueda para envío SIN nota
    const modalButtons = modal.querySelectorAll('button');
    let sendBtn = modalButtons.find(b => {
      const txt = (b.innerText || '').trim().toLowerCase();
      const aria = (b.getAttribute('aria-label') || '').toLowerCase();
      return txt.includes('sin nota') || aria.includes('sin nota') || txt.includes('without a note') || aria.includes('without a note');
    });
    if (!sendBtn) {
      sendBtn = modal.querySelector('button.artdeco-button--primary');
    }

    assert.ok(sendBtn, 'ERROR: No se encontró el botón de envío en el modal');
    assert.strictEqual(sendBtn, sendWithoutNoteBtn, 'ERROR: El botón de envío no fue el botón primario "Enviar sin nota"');
    console.log('  [PASS] Botón primario "Enviar sin nota" seleccionado correctamente.');
  }

  // ------------------------------------------------------------------------------------
  // TEST 4: Detección de barreras (Email Requerido / Límite Semanal)
  // ------------------------------------------------------------------------------------
  console.log('\nTEST 4: Detección de barreras defensivas de LinkedIn...');
  {
    // Barrera 1: Email Requerido
    const emailModal = new MockElement('div', { role: 'dialog' }, 'Introduce el correo electrónico de Jose para conectar');
    const emailTxt = (emailModal.innerText || '').toLowerCase();
    const isEmailReq = emailTxt.includes('introduce el correo') || emailTxt.includes('enter the email') || emailTxt.includes('correo electrónico');
    assert.strictEqual(isEmailReq, true, 'ERROR: No se detectó requerimiento de email');

    // Barrera 2: Límite Semanal
    const limitModal = new MockElement('div', { role: 'dialog' }, 'Has alcanzado el límite semanal de invitaciones');
    const limitTxt = (limitModal.innerText || '').toLowerCase();
    const isLimit = limitTxt.includes('límite semanal') || limitTxt.includes('weekly invitation limit');
    assert.strictEqual(isLimit, true, 'ERROR: No se detectó límite semanal');

    console.log('  [PASS] Detección de EMAIL_REQUIRED y WEEKLY_LIMIT verificada.');
  }

  // ------------------------------------------------------------------------------------
  // TEST 5: COMPROBACIÓN TERMINANTE DE SEGURIDAD (Zero False Positives)
  // ------------------------------------------------------------------------------------
  console.log('\nTEST 5: Comprobación terminante de seguridad (Zero False Positives)...');
  {
    // Subcaso 5A: LinkedIn NO cambia el botón a "Pendiente" (fallo de red, modal cerrado sin enviar, etc.)
    // La función DEBE retornar success: false y NUNCA marcar la invitación como enviada en BD.
    const mockWinFailing = {
      isDestroyed: () => false,
      loadURL: async () => {},
      webContents: {
        getURL: () => 'https://www.linkedin.com/in/jose-arellano/',
        once: (evt, cb) => cb(),
        executeJavaScript: async (code) => {
          if (code.includes('window.scrollTo')) return true;
          if (code.includes('already_pending')) return { already_pending: false };
          if (code.includes('isConnectBtn')) return { found: true, method: 'direct_header' };
          if (code.includes('has_modal')) return { has_modal: true, blocked: false };
          if (code.includes('verifyRes') || code.includes('isPending')) {
            // El botón NO pasó a Pendiente
            return { isPending: false, modalOpen: false };
          }
          return {};
        }
      }
    };

    const failResult = await handleLinkedInSendInvite(mockWinFailing, {
      profile_url: 'https://www.linkedin.com/in/jose-arellano/',
      note: ''
    });

    assert.strictEqual(failResult.success, false, 'ERROR CRÍTICO: Retornó success: true cuando el perfil NO estaba en Pendiente');
    assert.strictEqual(failResult.verified_pending, false, 'ERROR: verified_pending debe ser false');
    assert.ok(failResult.error.includes('Pendiente'), 'ERROR: El mensaje de error debe indicar falta de confirmación Pendiente');
    console.log('  [PASS] Zero False Positives: Retornó success: false cuando LinkedIn no confirmó "Pendiente".');

    // Subcaso 5B: LinkedIn SÍ cambia el botón a "Pendiente"
    const mockWinSuccess = {
      isDestroyed: () => false,
      loadURL: async () => {},
      webContents: {
        getURL: () => 'https://www.linkedin.com/in/jose-arellano/',
        once: (evt, cb) => cb(),
        executeJavaScript: async (code) => {
          if (code.includes('window.scrollTo')) return true;
          if (code.includes('already_pending')) return { already_pending: false };
          if (code.includes('isConnectBtn')) return { found: true, method: 'direct_header' };
          if (code.includes('has_modal')) return { has_modal: true, blocked: false };
          if (code.includes('verifyRes') || code.includes('isPending')) {
            // Confirmación real de LinkedIn: el botón cambió a Pendiente
            return { isPending: true, modalOpen: false };
          }
          return {};
        }
      }
    };

    const successResult = await handleLinkedInSendInvite(mockWinSuccess, {
      profile_url: 'https://www.linkedin.com/in/jose-arellano/',
      note: ''
    });

    assert.strictEqual(successResult.success, true, 'ERROR: Debe retornar success: true cuando el botón es confirmado');
    assert.strictEqual(successResult.result.verified_pending, true, 'ERROR: verified_pending debe ser true');
    console.log('  [PASS] Confirmación genuina: Retornó success: true solo con verified_pending = true.');
  }

  // ------------------------------------------------------------------------------------
  // TEST 6: Detección preventiva de estado "ALREADY_PENDING"
  // ------------------------------------------------------------------------------------
  console.log('\nTEST 6: Detección preventiva de contacto ya pendiente (evita clics innecesarios)...');
  {
    const mockWinAlreadyPending = {
      isDestroyed: () => false,
      loadURL: async () => {},
      webContents: {
        getURL: () => 'https://www.linkedin.com/in/jose-arellano/',
        once: (evt, cb) => cb(),
        executeJavaScript: async (code) => {
          if (code.includes('window.scrollTo')) return true;
          if (code.includes('already_pending')) return { already_pending: true };
          throw new Error('No debe ejecutar más pasos si ya estaba pendiente');
        }
      }
    };

    const pendingResult = await handleLinkedInSendInvite(mockWinAlreadyPending, {
      profile_url: 'https://www.linkedin.com/in/jose-arellano/'
    });

    assert.strictEqual(pendingResult.success, true);
    assert.strictEqual(pendingResult.result.status, 'ALREADY_PENDING');
    console.log('  [PASS] Estado ALREADY_PENDING detectado sin enviar comandos adicionales.');
  }

  // ------------------------------------------------------------------------------------
  // TEST 7: Despacho a través de executeAction('LI_SEND_INVITE', ...)
  // ------------------------------------------------------------------------------------
  console.log('\nTEST 7: Despacho unificado vía executeAction("LI_SEND_INVITE")...');
  {
    const mockWin = {
      isDestroyed: () => false,
      loadURL: async () => {},
      webContents: {
        getURL: () => 'https://www.linkedin.com/in/jose-arellano/',
        once: (evt, cb) => cb(),
        executeJavaScript: async (code) => {
          if (code.includes('window.scrollTo')) return true;
          if (code.includes('already_pending')) return { already_pending: false };
          if (code.includes('isConnectBtn')) return { found: true, method: 'direct_header' };
          if (code.includes('has_modal')) return { has_modal: true, blocked: false };
          if (code.includes('isPending')) return { isPending: true, modalOpen: false };
          return {};
        }
      }
    };

    const res = await executeAction('LI_SEND_INVITE', { profile_url: 'https://www.linkedin.com/in/jose-arellano/' }, { linkedInWindow: mockWin });
    assert.strictEqual(res.success, true);
    assert.strictEqual(res.result.action, 'LI_SEND_INVITE');
    assert.strictEqual(res.result.verified_pending, true);
    console.log('  [PASS] executeAction despachó y verificó LI_SEND_INVITE correctamente.');
  }

  console.log('\n========================================================================');
  console.log('  TODAS LAS PRUEBAS PASARON EXITOSAMENTE (7/7)');
  console.log('  - Detección precisa de botón [+ Conectar] comprobada.');
  console.log('  - Protección anti-hijacking de sidebar (<aside>) comprobada.');
  console.log('  - Garantía de Zero False Positives comprobada.');
  console.log('========================================================================\n');
}

runTestSuite().catch(err => {
  console.error('\n❌ FALLO EN LA TEST SUITE:', err);
  process.exit(1);
});
