// Cliente centralizado de comunicación con la API de FastAPI
// Sigue la convención de funciones en inglés y comentarios en español

let cachedApiBase = null;

/**
 * Resuelve dinámicamente la URL base de la API:
 * 1. Si corre dentro de Electron, consulta al proceso principal vía IPC (window.nexusDesktop).
 * 2. Si existe variable de entorno VITE_API_URL en el build.
 * 3. Fallback: '/api' relativo para servidor web local o proxy de desarrollo.
 */
export async function resolveApiBase() {
  if (cachedApiBase !== null) return cachedApiBase;

  // 1. Electron bridge (Preload IPC)
  if (typeof window !== 'undefined' && window.nexusDesktop?.getApiBaseUrl) {
    try {
      const electronUrl = await window.nexusDesktop.getApiBaseUrl();
      if (electronUrl && typeof electronUrl === 'string') {
        const clean = electronUrl.replace(/\/+$/, '');
        cachedApiBase = clean.endsWith('/api') ? clean : `${clean}/api`;
        return cachedApiBase;
      }
    } catch (err) {
      console.warn('[API Base] Error obteniendo URL desde Electron, usando fallback:', err);
    }
  }

  // 2. Variable de entorno Vite
  if (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) {
    const envUrl = String(import.meta.env.VITE_API_URL).replace(/\/+$/, '');
    cachedApiBase = envUrl.endsWith('/api') ? envUrl : `${envUrl}/api`;
    return cachedApiBase;
  }

  // 3. Fallback relativo
  cachedApiBase = '/api';
  return cachedApiBase;
}

const TOKEN_KEY = 'nexus_session_token';

export function getSessionToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setSessionToken(token, tenantId = null) {
  try {
    if (token) {
      sessionStorage.setItem(TOKEN_KEY, token);
      localStorage.setItem(TOKEN_KEY, token);
      if (typeof window !== 'undefined' && window.nexusDesktop?.setAuthSession) {
        window.nexusDesktop.setAuthSession({ sessionToken: token, tenantId }).catch(() => {});
      }
    } else {
      sessionStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(TOKEN_KEY);
      if (typeof window !== 'undefined' && window.nexusDesktop?.clearAuthSession) {
        window.nexusDesktop.clearAuthSession().catch(() => {});
      }
    }
  } catch {}
}

export function clearSessionToken() {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(TOKEN_KEY);
    if (typeof window !== 'undefined' && window.nexusDesktop?.clearAuthSession) {
      window.nexusDesktop.clearAuthSession().catch(() => {});
    }
  } catch {}
}

/**
 * Función auxiliar para realizar peticiones HTTP con manejo estandarizado de errores
 */
async function request(endpoint, options = {}) {
  try {
    const apiBase = await resolveApiBase();
    const token = getSessionToken();
    const authHeaders = token ? { 
      Authorization: `Bearer ${token}`,
      'X-Session-Token': token,
    } : {};

    const config = {
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders,
        ...options.headers,
      },
      ...options,
    };

    const response = await fetch(`${apiBase}${endpoint}`, config);
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      let message = `Error HTTP ${response.status}`;
      if (typeof errorData.detail === 'object' && errorData.detail?.mensaje) {
        message = errorData.detail.mensaje;
      } else if (typeof errorData.detail === 'string') {
        message = errorData.detail;
      } else if (errorData.mensaje) {
        message = errorData.mensaje;
      }
      const err = new Error(message);
      err.data = errorData;
      err.status = response.status;
      throw err;
    }
    return await response.json();
  } catch (error) {
    if (!options?.silent) {
      console.error(`[API Error] en ${endpoint}:`, error);
    }
    throw error;
  }
}

// ==========================================
// AUTENTICACIÓN Y CONTROL DE SUSCRIPCIÓN
// ==========================================

export async function loginUser(email, password) {
  const data = await request('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  if (data?.token) {
    const tenantId = data.usuario?.tenant_id || data.tenant_id || null;
    setSessionToken(data.token, tenantId);
  }
  return data;
}

export async function checkUserSession() {
  const token = getSessionToken();
  if (!token) return null;
  try {
    const res = await request('/auth/sesion');
    const usuario = res?.usuario || null;
    if (usuario && typeof window !== 'undefined' && window.nexusDesktop?.setAuthSession) {
      const tenantId = usuario.tenant_id || (usuario.tenant && usuario.tenant.id) || null;
      window.nexusDesktop.setAuthSession({ sessionToken: token, tenantId }).catch(() => {});
    }
    return usuario;
  } catch {
    clearSessionToken();
    return null;
  }
}

export async function logoutUser() {
  try {
    await request('/auth/logout', { method: 'POST' });
  } catch {
  } finally {
    clearSessionToken();
  }
}

export async function fetchUsersList() {
  return await request('/auth/usuarios');
}

export async function updateUserSubscription(userId, data) {
  return await request(`/auth/usuarios/${userId}/suscripcion`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

// ==========================================
// GESTIÓN MULTI-TENANT, AGENCIA Y PUESTOS
// ==========================================

export async function fetchTenants() {
  return await request('/tenants');
}

export async function revokeTenantLicense(tenantId, motivo = '') {
  const query = motivo ? `?motivo=${encodeURIComponent(motivo)}` : '';
  return await request(`/tenants/${tenantId}/revocar${query}`, { method: 'POST' });
}

export async function reactivateTenantLicense(tenantId, dias = 30) {
  return await request(`/tenants/${tenantId}/reactivar?dias=${dias}`, { method: 'POST' });
}

export async function adjustTenantSeats(tenantId, delta) {
  return await request(`/tenants/${tenantId}/puestos`, {
    method: 'POST',
    body: JSON.stringify({ delta }),
  });
}

export async function createFullAccount(payload) {
  return await request('/admin/cuentas', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function fetchAgencyClients(agencyId) {
  return await request(`/agencia/${agencyId}/clientes`);
}

export async function createAgencyClient(agencyId, clientData) {
  return await request(`/agencia/${agencyId}/clientes`, {
    method: 'POST',
    body: JSON.stringify(clientData),
  });
}

export async function fetchAgencyFinances(agencyId) {
  return await request(`/agencia/${agencyId}/finanzas`);
}

export async function fetchTenantMembers(tenantId) {
  return await request(`/tenants/${tenantId}/miembros`);
}

export async function createTenantMember(tenantId, memberData) {
  return await request(`/tenants/${tenantId}/usuarios`, {
    method: 'POST',
    body: JSON.stringify(memberData),
  });
}

export async function toggleUserSeat(userId, puestoActivo) {
  return await request(`/usuarios/${userId}/puesto`, {
    method: 'PATCH',
    body: JSON.stringify({ puesto_activo: puestoActivo }),
  });
}

export async function markLeadMeeting(leadId, meetingData = {}) {
  return await request(`/leads/${leadId}/reunion`, {
    method: 'POST',
    body: JSON.stringify(meetingData),
  });
}

// ==========================================
// MÉTRICAS Y PROSPECTOS
// ==========================================

export async function fetchMetrics(tenantId = '') {
  // Obtiene los contadores KPI generales de la campaña desde /api/metricas
  const query = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : '';
  return await request(`/metricas${query}`);
}

export async function fetchProspects(optionsOrEstado = {}, busquedaArg = '', tenantIdArg = '') {
  // Obtiene el listado completo de prospectos con filtros avanzados
  const params = new URLSearchParams();
  
  let estado = '';
  let busqueda = '';
  let listaId = '';
  let secuenciaId = '';
  let fechaDesde = '';
  let fechaHasta = '';
  let orden = 'fecha_desc';
  let tenantId = '';
  let limit = 50;
  let offset = 0;

  if (typeof optionsOrEstado === 'object' && optionsOrEstado !== null) {
    estado = optionsOrEstado.estado || '';
    busqueda = optionsOrEstado.busqueda || '';
    listaId = optionsOrEstado.listaId || '';
    secuenciaId = optionsOrEstado.secuenciaId || '';
    fechaDesde = optionsOrEstado.fechaDesde || '';
    fechaHasta = optionsOrEstado.fechaHasta || '';
    orden = optionsOrEstado.orden || 'fecha_desc';
    tenantId = optionsOrEstado.tenantId || '';
    limit = optionsOrEstado.limit || 50;
    offset = optionsOrEstado.offset || 0;
  } else {
    estado = optionsOrEstado || '';
    busqueda = busquedaArg || '';
    tenantId = tenantIdArg || '';
  }

  if (estado) params.append('estado', estado);
  if (busqueda) params.append('busqueda', busqueda);
  if (listaId) params.append('lista_id', listaId);
  if (secuenciaId) params.append('secuencia_id', secuenciaId);
  if (fechaDesde) params.append('fecha_desde', fechaDesde);
  if (fechaHasta) params.append('fecha_hasta', fechaHasta);
  if (orden) params.append('orden', orden);
  if (tenantId) params.append('tenant_id', tenantId);
  params.append('limit', String(limit));
  params.append('offset', String(offset));

  const query = `?${params.toString()}`;
  const res = await request(`/prospectos${query}`);
  const rawLeads = Array.isArray(res) ? res : (res.leads || []);
  const total = typeof res?.total === 'number' ? res.total : rawLeads.length;
  
  const leads = rawLeads.map(l => ({
    id: l.id,
    nombre: l.nombre,
    cargo_actual: l.cargo_actual || l.cargo || l.cargo_titular || 'Profesional / Decisor',
    cargo_titular: l.cargo_titular || l.cargo || '',
    cargo: l.cargo_actual || l.cargo_titular || l.cargo || 'Profesional / Decisor',
    institucion: l.institucion_actual || l.institucion,
    institucion_actual: l.institucion_actual || l.institucion,
    ubicacion: l.ubicacion || 'Chile',
    url_perfil: l.perfil_url || l.url_perfil,
    perfil_url: l.perfil_url || l.url_perfil,
    grado_red: l.grado_red || '2°',
    estado: l.estado || 'EXTRAIDO',
    email_directo: l.email || l.email_directo,
    telefono_directo: l.telefono || l.telefono_directo,
    fecha_extraccion: l.fecha_extraccion || l.created_at,
    created_at: l.created_at,
    updated_at: l.updated_at,
    listas: Array.isArray(l.listas) ? l.listas : [],
    secuencias: Array.isArray(l.secuencias) ? l.secuencias : [],
    ultima_actividad: l.ultima_actividad || null,
    etiquetas: Array.isArray(l.tags) ? l.tags : [],
    historial_interacciones: l.historial || [],
  }));

  return {
    total,
    limit,
    offset,
    leads,
  };
}

export async function fetchLeadDetail(prospectId) {
  // Obtiene el detalle profundo del prospecto con su historial completo, mensajes y correos
  const l = await request(`/prospectos/${prospectId}`);
  return {
    id: l.id,
    nombre: l.nombre,
    cargo_actual: l.cargo_actual || l.cargo || l.cargo_titular || 'Profesional / Decisor',
    cargo_titular: l.cargo_titular || l.cargo || '',
    cargo: l.cargo_actual || l.cargo_titular || l.cargo || 'Profesional / Decisor',
    institucion: l.institucion_actual || l.institucion,
    ubicacion: l.ubicacion || 'Chile',
    url_perfil: l.perfil_url || l.url_perfil,
    grado_red: l.grado_red || '2°/3°',
    estado: l.estado || 'EXTRAIDO',
    email_directo: l.email || l.email_directo,
    telefono_directo: l.telefono || l.telefono_directo,
    fecha_extraccion: l.fecha_extraccion || l.created_at,
    fecha_invitacion: l.fecha_invitacion,
    fecha_conexion: l.fecha_conexion,
    etiquetas: Array.isArray(l.tags) ? l.tags : [],
    historial_interacciones: l.historial || [],
    mensajes_linkedin: l.mensajes_linkedin || [],
    correos: l.correos || [],
    interacciones: l.interacciones || [],
  };
}

export async function saveLeadContact(prospectId, { email, telefono }) {
  // Actualiza email y teléfono de un prospecto específico
  const params = new URLSearchParams();
  if (email) params.append('email', email);
  if (telefono) params.append('telefono', telefono);
  return await request(`/prospectos/${prospectId}/contacto?${params.toString()}`, {
    method: 'PUT',
  });
}

export async function syncLeadWithLinkedIn(prospectId) {
  // Sincroniza y enriquece en vivo los datos del prospecto desde su perfil real en LinkedIn
  return await request(`/prospectos/${prospectId}/sincronizar-linkedin`, {
    method: 'POST',
  });
}

export async function resolveLeadEmail(prospectId, force = false) {
  // Resuelve el correo del lead mediante extracción directa (1er grado) o cascada (Waterfall + DNS MX + SMTP)
  return await request(`/prospectos/${prospectId}/resolver-correo?forzar=${force ? 'true' : 'false'}`, {
    method: 'POST',
  });
}

export async function batchResolveLeadEmails(leadIds, force = false) {
  // Resuelve en bloque los correos de una lista de prospectos
  return await request('/prospectos/lote/resolver-correo', {
    method: 'POST',
    body: JSON.stringify({ lead_ids: leadIds, forzar: force }),
  });
}

export async function getZohoSessionStatus() {
  // Consulta si la sesión de Zoho CRM está viva en el navegador de trabajo
  return await request('/zoho/estado-sesion');
}

export async function loginZoho() {
  // Abre la ventana de Zoho CRM para iniciar sesión persistente en el navegador aislado
  return await request('/zoho/login', { method: 'POST' });
}



export async function getWhatsAppSafetyStatus() {
  // Obtiene el estado de cuota diaria y horario seguro de WhatsApp Web
  return await request('/whatsapp/seguridad/estado');
}

export async function getLinkedInWarmupStatus() {
  // Obtiene el estado de la curva de calentamiento y medidor de búsquedas
  return await request('/linkedin/warmup/estado');
}

export async function withdrawStaleInvitations(diasLimite = 21) {
  // Retira en bloque invitaciones antiguas de LinkedIn
  return await request(`/linkedin/invitaciones-vencidas/retirar?dias_limite=${diasLimite}`, {
    method: 'POST',
  });
}

export async function testEnrichmentDiagnostics(params) {
  // Diagnóstico en vivo de sintaxis, DNS MX y ping SMTP
  return await request('/enrichment/test-diagnostico', {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

export async function deleteProspect(prospectId) {
  // Elimina permanentemente un prospecto de la base de datos
  return await request(`/prospectos/${prospectId}`, {
    method: 'DELETE',
  });
}

export async function deleteProspectsBatch(prospectIds) {
  // Elimina permanentemente un lote de prospectos
  return await request('/prospectos/eliminar-lote', {
    method: 'POST',
    body: JSON.stringify({ lead_ids: prospectIds }),
  });
}

export async function importSelectedProspects(leads, listTarget = null, tenantId = null) {
  // Guarda únicamente los prospectos seleccionados y los vincula a una o varias listas
  const body = { leads };
  if (Array.isArray(listTarget)) {
    body.lista_ids = listTarget;
  } else if (listTarget) {
    body.lista_id = listTarget;
  }
  if (tenantId) body.tenant_id = tenantId;
  return await request('/prospectos/importar-lote', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

// ==========================================
// BÚSQUEDA Y EXTRACCIÓN (LINKEDIN)
// ==========================================

export async function triggerExtraction(searchTerm, page = 1, listId = null, autoSave = false, tenantId = null) {
  // Ejecuta la búsqueda de prospectos en LinkedIn (por defecto devuelve vista previa sin auto-guardar)
  const params = new URLSearchParams();
  params.append('termino', searchTerm);
  params.append('pagina', String(page));
  params.append('auto_guardar', autoSave ? 'true' : 'false');
  if (listId) params.append('lista_id', listId);
  if (tenantId) params.append('tenant_id', tenantId);
  return await request(`/extraccion/buscar?${params.toString()}`, { method: 'POST' });
}

export async function extractNetworkLeads(source = 'all', limit = 50, tenantId = null) {
  // Extrae decisores y contactos desde la red personal de LinkedIn (Conexiones 1º grado o Invitaciones enviadas)
  const params = new URLSearchParams();
  params.append('origen', source);
  params.append('limite', String(limit));
  if (tenantId) params.append('tenant_id', tenantId);
  return await request(`/extraccion/red-linkedin?${params.toString()}`, { method: 'POST' });
}

export async function fetchBrowserStatus() {
  // Consulta si Chromium embebido o BrowserOS está activo y respondiendo
  const res = await request('/browser/estado');
  return {
    online: Boolean(res.activo),
    activo: Boolean(res.activo),
    is_electron: Boolean(res.is_electron),
    motor: res.motor || 'Inactivo',
    mensaje: res.mensaje,
    sesion_linkedin_activa: Boolean(res.sesion_linkedin_activa),
    sesion_whatsapp_activa: Boolean(res.sesion_whatsapp_activa),
    sesion_zoho_activa: Boolean(res.sesion_zoho_activa),
    visible: Boolean(res.visible),
  };
}

export async function launchBrowser() {
  // Solicita abrir y preparar navegador de trabajo con LinkedIn y Zoho
  return await request('/browser/iniciar', { method: 'POST' });
}

export async function showWorkBrowser(url = null, channel = null) {
  // Abre o trae al frente la ventana de Chromium embebido de Electron
  const params = new URLSearchParams();
  if (url) params.append('url', url);
  if (channel) params.append('channel', channel);
  const query = params.toString() ? `?${params.toString()}` : '';
  return await request(`/browser/mostrar${query}`, { method: 'POST' });
}

export async function hideWorkBrowser(channel = null) {
  // Oculta la ventana de Chromium embebido
  const query = channel ? `?channel=${encodeURIComponent(channel)}` : '';
  return await request(`/browser/ocultar${query}`, { method: 'POST' });
}


export async function logoutZoho() {
  // Cierra sesión en Zoho CRM, purga cookies y restablece el formulario de login
  return await request('/zoho/logout', { method: 'POST' });
}

export async function fetchSafetyStatus() {
  // Consulta el estado de seguridad, cupos y kill-switch
  return await request('/seguridad/estado');
}

export async function toggleCampaign(targetState) {
  // Activa o desactiva el Kill Switch / horario para la campaña
  if (!targetState) {
    const res = await request('/seguridad/kill-switch/activar?motivo=Pausado_desde_la_interfaz', { method: 'POST' });
    return { activa: false, kill_switch: res.kill_switch };
  } else {
    const res = await request('/seguridad/kill-switch/desactivar', { method: 'POST' });
    return { activa: true, kill_switch: res.kill_switch };
  }
}

export async function updateSafetyConfig(clave, valor) {
  return await request(`/seguridad/configuracion?clave=${encodeURIComponent(clave)}&valor=${encodeURIComponent(valor)}`, { method: 'POST' });
}

export async function syncAcceptedConnections(tenantId = '') {
  // Sincroniza en bloque las conexiones aceptadas inspeccionando LinkedIn
  const query = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : '';
  return await request(`/leads/sincronizar-conexiones${query}`, { method: 'POST' });
}


// ==========================================
// LISTAS DE LEADS (AUDIENCIAS)
// ==========================================

export async function fetchLeadLists(tenantId = '') {
  // Consulta todas las listas de prospectos configuradas
  const query = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : '';
  const res = await request(`/listas${query}`);
  return res.listas || [];
}

export async function createLeadList(data) {
  // Crea una nueva lista de prospectos
  return await request('/listas', {
    method: 'POST',
    body: JSON.stringify({
      nombre: data.nombre,
      descripcion: data.descripcion || '',
      termino_busqueda: data.termino_busqueda || '',
      estado: data.estado || 'ACTIVA',
      conectar_secuencia_activa: Boolean(data.conectar_secuencia_activa),
      tenant_id: data.tenant_id || undefined,
    }),
  });
}

export async function fetchLeadListDetail(listId) {
  // Consulta la información detallada de una lista con sus prospectos y secuencias
  return await request(`/listas/${listId}`);
}

export async function deleteLeadList(listId) {
  // Elimina una lista de prospectos
  return await request(`/listas/${listId}`, { method: 'DELETE' });
}

export async function connectListToSequence(firstId, secondId) {
  // Vincula una lista de leads a una secuencia (admite tanto (listId, sequenceId) como (sequenceId, listId))
  let listId = firstId;
  let sequenceId = secondId;
  if (typeof firstId === 'string' && (firstId.startsWith('seq-') || firstId.startsWith('sec-') || (typeof secondId === 'string' && (secondId.startsWith('lista-') || secondId.startsWith('list-'))))) {
    sequenceId = firstId;
    listId = secondId;
  }
  return await request(`/listas/${listId}/conectar-secuencia`, {
    method: 'POST',
    body: JSON.stringify({ secuencia_id: sequenceId }),
  });
}

export async function disconnectListFromSequence(firstId, secondId) {
  // Desvincula una lista de leads de una secuencia (admite tanto (listId, sequenceId) como (sequenceId, listId))
  let listId = firstId;
  let sequenceId = secondId;
  if (typeof firstId === 'string' && (firstId.startsWith('seq-') || firstId.startsWith('sec-') || (typeof secondId === 'string' && (secondId.startsWith('lista-') || secondId.startsWith('list-'))))) {
    sequenceId = firstId;
    listId = secondId;
  }
  return await request(`/listas/${listId}/desconectar-secuencia`, {
    method: 'POST',
    body: JSON.stringify({ secuencia_id: sequenceId }),
  });
}

export async function removeLeadFromList(listId, leadId) {
  // Quita un prospecto de una lista específica
  return await request(`/listas/${listId}/leads/${leadId}`, { method: 'DELETE' });
}

export async function addLeadsToList(listId, leadIds) {
  // Incorpora prospectos a una lista existente
  return await request(`/listas/${listId}/leads`, {
    method: 'POST',
    body: JSON.stringify({ lead_ids: leadIds }),
  });
}

export async function updateLeadList(listId, data) {
  // Actualiza metadatos o estado de una lista
  return await request(`/listas/${listId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function startListExtraction(listId) {
  // Inicia la extracción automática con pausas antiban de los leads de una lista
  return await request(`/listas/${listId}/iniciar-extraccion`, {
    method: 'POST',
  });
}

export async function stopListExtraction(listId) {
  // Detiene la extracción automática de la lista
  return await request(`/listas/${listId}/detener-extraccion`, {
    method: 'POST',
  });
}

// ==========================================
// SECUENCIAS MULTICANAL
// ==========================================

export async function fetchSequences(tenantId = '') {
  // Obtiene todas las secuencias registradas con detalle completo
  const query = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : '';
  const res = await request(`/secuencias${query}`);
  const seqs = res.secuencias || [];
  
  // Enriquecer cada secuencia con su árbol de pasos y leads inscritos
  const fullSeqs = await Promise.all(
    seqs.map(async (s) => {
      try {
        const full = await request(`/secuencias/${s.id}`);
        const leadsRes = await request(`/secuencias/${s.id}/leads`).catch(() => ({ leads: [] }));
        const merged = { ...s, ...full };
        const associatedLists = (merged.listas_asociadas || []).map((l) => ({
          id: l.id,
          nombre: l.nombre || l.id,
          estado: l.estado || 'ACTIVA',
          total_leads: l.total_leads || 0,
        }));
        
        // Normalizar pasos para asegurar tipo, tipo_accion, etiqueta y parámetros consistentes
        const normalizedSteps = (merged.pasos || []).map((p, idx) => {
          const actionType = p.tipo_accion || p.tipo || 'VISITAR_PERFIL';
          const label = p.etiqueta || p.parametros?.etiqueta || `${idx + 1}. ${actionType}`;
          return {
            ...p,
            tipo: actionType,
            tipo_accion: actionType,
            etiqueta: label,
            parametros: p.parametros || {},
          };
        });

        // Normalizar los leads asignados para que coincidan con la tabla de la UI preservando todos sus atributos
        const normalizedLeads = (leadsRes.leads || []).map((l) => ({
          ...l,
          id: l.lead_id || l.id,
          lead_id: l.lead_id || l.id,
          nombre: l.nombre,
          cargo_actual: l.cargo_actual || l.cargo_titular || 'Cargo no especificado',
          institucion: l.institucion_actual || l.institucion || '-',
          institucion_actual: l.institucion_actual || l.institucion || '-',
          ubicacion: l.ubicacion || 'Chile',
          email_directo: l.email || l.email_zoho || l.email_extracted || 'No declarado',
          paso_actual: l.paso_orden || l.paso_actual || 1,
          paso_etiqueta: l.paso_etiqueta || l.paso_accion || '',
          estado_secuencia: (() => {
            const rawSt = (l.estado || l.estado_secuencia || 'EN_CURSO').toUpperCase();
            return (rawSt === 'FINALIZADA' || rawSt === 'FINALIZADO') ? 'COMPLETADO' : (l.estado || l.estado_secuencia || 'EN_CURSO');
          })(),
          perfil_url: l.perfil_url,
          proxima_ejecucion_at: l.proxima_ejecucion_at,
        }));

        const enrolledCompletedCount = normalizedLeads.filter(
          ld => (ld.estado_secuencia || '').toUpperCase() === 'COMPLETADO'
        ).length;

        const proxLead = merged.proximo_lead
          ? {
              ...merged.proximo_lead,
              paso_actual: merged.proximo_lead.paso_orden || merged.proximo_lead.paso_actual || 1,
            }
          : null;

        const rawEstado = (merged.estado || (merged.activa ? 'PUBLICADA' : 'BORRADOR')).toUpperCase();
        const isPublished = rawEstado === 'PUBLICADA' && Boolean(merged.activa);
        const isPaused = rawEstado === 'PAUSADA';
        const estadoNormalizado = isPublished ? 'PUBLICADA' : (isPaused ? 'PAUSADA' : 'BORRADOR');

        return {
          ...merged,
          estado: estadoNormalizado,
          publicada: isPublished,
          activa: isPublished,
          listas_asociadas: associatedLists,
          listas_conectadas: associatedLists.map(l => l.nombre || l.id),
          leads_inscritos: normalizedLeads,
          leads_completados: Math.max(Number(merged.total_completados ?? merged.leads_completados ?? 0), enrolledCompletedCount),
          total_completados: Math.max(Number(merged.total_completados ?? merged.leads_completados ?? 0), enrolledCompletedCount),
          leads_completados_count: Math.max(Number(merged.total_completados ?? merged.leads_completados ?? 0), enrolledCompletedCount),
          candidato_proximo: proxLead,
          pasos: normalizedSteps,
        };
      } catch {
        const rawEstado = (s.estado || (s.activa ? 'PUBLICADA' : 'BORRADOR')).toUpperCase();
        const isPublished = rawEstado === 'PUBLICADA' && Boolean(s.activa);
        const isPaused = rawEstado === 'PAUSADA';
        const estadoNormalizado = isPublished ? 'PUBLICADA' : (isPaused ? 'PAUSADA' : 'BORRADOR');

        return {
          ...s,
          estado: estadoNormalizado,
          publicada: isPublished,
          activa: isPublished,
          listas_asociadas: [],
          listas_conectadas: [],
          leads_inscritos: [],
          leads_completados_count: 0,
          candidato_proximo: null,
          pasos: [],
        };
      }
    })
  );

  return fullSeqs;
}

export async function addSequenceStep(sequenceId, { step, position = 'final', referenceStepId = null }) {
  // Inserta un paso atómico respetando la topología del árbol de decisión
  return await request(`/secuencias/${sequenceId}/pasos/agregar`, {
    method: 'POST',
    body: JSON.stringify({
      posicion: position,
      paso_referencia_id: referenceStepId,
      tipo_accion: step.tipo || step.tipo_accion,
      etiqueta: step.etiqueta,
      parametros: step.parametros || {},
      condicion_rama: step.condicion_rama || 'DEFAULT',
    }),
  });
}

export async function deleteSequenceStep(sequenceId, stepId) {
  // Elimina un paso atómico y re-indexa / re-enruta los leads inscritos
  return await request(`/secuencias/${sequenceId}/pasos/${stepId}`, {
    method: 'DELETE',
  });
}

export async function deleteSequence(sequenceId) {
  // Elimina permanentemente una secuencia, sus pasos asociados y desvincula las listas y prospectos
  return await request(`/secuencias/${sequenceId}`, {
    method: 'DELETE',
  });
}

export async function createSequence(data) {
  // Crea una nueva secuencia empezando en estado BORRADOR
  const body = {
    nombre: data.nombre,
    descripcion: data.descripcion || '',
    activa: Boolean(data.publicada && data.estado === 'PUBLICADA'),
    estado: data.estado || 'BORRADOR',
    plantilla: data.plantilla || 'multicanal',
  };
  if (data.tenant_id) body.tenant_id = data.tenant_id;
  return await request('/secuencias', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function updateSequence(sequenceId, { pasos, nombre, descripcion }) {
  // Actualiza los pasos o metadatos de una secuencia
  if (pasos) {
    await request(`/secuencias/${sequenceId}/pasos`, {
      method: 'POST',
      body: JSON.stringify({ pasos }),
    });
  }
  if (nombre || descripcion) {
    await request(`/secuencias/${sequenceId}`, {
      method: 'PUT',
      body: JSON.stringify({ nombre, descripcion }),
    });
  }
  return { status: 'ok' };
}

export async function changeSequenceStatus(sequenceId, nuevoEstado) {
  // Modifica el estado explícito de la secuencia ('BORRADOR' | 'PUBLICADA' | 'PAUSADA')
  return await request(`/secuencias/${sequenceId}/estado`, {
    method: 'POST',
    body: JSON.stringify({ estado: nuevoEstado }),
  });
}

export async function toggleSequencePublish(sequenceId, targetEstado = null) {
  // Publica, pausa o reanuda una secuencia
  if (targetEstado) {
    return await changeSequenceStatus(sequenceId, targetEstado);
  }
  const seq = await request(`/secuencias/${sequenceId}`);
  const currentEstado = (seq.estado || (seq.activa ? 'PUBLICADA' : 'BORRADOR')).toUpperCase();
  let nuevoEstado = 'PUBLICADA';
  if (currentEstado === 'PUBLICADA') {
    nuevoEstado = 'PAUSADA';
  } else if (currentEstado === 'PAUSADA') {
    nuevoEstado = 'PUBLICADA';
  } else {
    // Si era BORRADOR, pasa a PUBLICADA
    nuevoEstado = 'PUBLICADA';
  }
  return await changeSequenceStatus(sequenceId, nuevoEstado);
}



export async function assignEnqueuedLeads(sequenceId) {
  // Inscribe todos los leads actualmente en cola a esta secuencia
  return await request(`/secuencias/${sequenceId}/asignar-leads`, {
    method: 'POST',
    body: JSON.stringify({ lead_ids: [] }),
  });
}

export async function executeSequenceNextStep(sequenceId) {
  // Ejecuta de forma inmediata el siguiente paso elegible de la secuencia
  const query = sequenceId ? `?secuencia_id=${sequenceId}` : '';
  return await request(`/secuencias/ejecutar-siguiente${query}`, {
    method: 'POST',
  });
}

// ==========================================
// LOGS Y AUDITORÍA DE ACTIVIDAD EN TIEMPO REAL
// ==========================================

export async function fetchLogs(params = {}) {
  // Obtiene los eventos recientes del log del sistema con filtros
  const searchParams = new URLSearchParams();
  if (params.limit) searchParams.append('limit', String(params.limit));
  if (params.module) searchParams.append('module', params.module);
  if (params.level) searchParams.append('level', params.level);
  if (params.search) searchParams.append('search', params.search);
  if (params.sinceId) searchParams.append('since_id', String(params.sinceId));

  const query = searchParams.toString() ? `?${searchParams.toString()}` : '';
  return await request(`/logs${query}`);
}

export async function fetchLogStats(options = {}) {
  // Obtiene métricas agregadas de actividad reciente y estado del extractor
  return await request('/logs/stats', options);
}

export async function clearLogs() {
  // Limpia el historial de eventos en base de datos
  return await request('/logs', {
    method: 'DELETE',
  });
}

// ==========================================
// TASK DISPATCHER (HYBRID ARCHITECTURE)
// ==========================================

export async function fetchWorkerState() {
  // Obtains dispatcher state and whether autopilot is active
  return await request('/worker/estado');
}

export async function toggleAutopilot(active = null) {
  // Activates or pauses campaign autopilot
  const query = active !== null ? `?activo=${Boolean(active)}` : '';
  return await request(`/worker/piloto-automatico/toggle${query}`, {
    method: 'POST',
  });
}

export async function forceWorkerNext() {
  // Salta la pausa actual y ejecuta la siguiente tarea de inmediato
  return await request('/worker/forzar-siguiente', {
    method: 'POST',
  });
}

export async function fetchNextTask() {
  // Queries next authorized task from cloud server
  return await request('/worker/proxima-tarea');
}

export async function reportTaskResult(data) {
  // Reports task execution outcome to server
  return await request('/worker/reportar-resultado', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function fetchDashboardMetrics({ tenantId = '', sequenceId = '', listId = '' } = {}) {
  // Consulta métricas integrales de prospección, KPIs de secuencias y embudo para el Dashboard
  const params = new URLSearchParams();
  if (tenantId) params.append('tenant_id', tenantId);
  if (sequenceId) params.append('secuencia_id', sequenceId);
  if (listId) params.append('lista_id', listId);
  const query = params.toString() ? `?${params.toString()}` : '';
  return await request(`/dashboard/metricas${query}`);
}



