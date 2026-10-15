// Cliente centralizado de comunicación con la API de FastAPI
// Sigue la convención de funciones en inglés y comentarios en español

const API_BASE = '/api';

const TOKEN_KEY = 'nexus_session_token';

export function getSessionToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setSessionToken(token) {
  try {
    if (token) {
      sessionStorage.setItem(TOKEN_KEY, token);
    } else {
      sessionStorage.removeItem(TOKEN_KEY);
    }
  } catch {}
}

export function clearSessionToken() {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
  } catch {}
}

/**
 * Función auxiliar para realizar peticiones HTTP con manejo estandarizado de errores
 */
async function request(endpoint, options = {}) {
  try {
    const token = getSessionToken();
    const authHeaders = token ? { Authorization: `Bearer ${token}` } : {};

    const config = {
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders,
        ...options.headers,
      },
      ...options,
    };

    const response = await fetch(`${API_BASE}${endpoint}`, config);
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
    console.error(`[API Error] en ${endpoint}:`, error);
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
    setSessionToken(data.token);
  }
  return data;
}

export async function checkUserSession() {
  const token = getSessionToken();
  if (!token) return null;
  try {
    const res = await request('/auth/sesion');
    return res?.usuario || null;
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

export async function fetchProspects(estado = '', busqueda = '', tenantId = '') {
  // Obtiene el listado completo de prospectos con filtros opcionales
  const params = new URLSearchParams();
  if (estado) params.append('estado', estado);
  if (busqueda) params.append('busqueda', busqueda);
  if (tenantId) params.append('tenant_id', tenantId);
  params.append('limit', '100');
  const query = `?${params.toString()}`;
  
  const res = await request(`/prospectos${query}`);
  // El endpoint de FastAPI retorna {"total": N, "leads": [...]}
  const leads = Array.isArray(res) ? res : (res.leads || []);
  
  // Normalizar campos para compatibilidad con la vista
  return leads.map(l => ({
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
  }));
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

export async function importSelectedProspects(leads, listId = null, tenantId = null) {
  // Guarda únicamente los prospectos seleccionados y los vincula a la lista especificada
  const body = { leads, lista_id: listId || null };
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
    visible: Boolean(res.visible),
  };
}

export async function launchBrowser() {
  // Solicita abrir y preparar navegador de trabajo con LinkedIn y Zoho
  return await request('/browser/iniciar', { method: 'POST' });
}

export async function showWorkBrowser(url = null) {
  // Abre o trae al frente la ventana de Chromium embebido de Electron
  const query = url ? `?url=${encodeURIComponent(url)}` : '';
  return await request(`/browser/mostrar${query}`, { method: 'POST' });
}

export async function hideWorkBrowser() {
  // Oculta la ventana de Chromium embebido
  return await request('/browser/ocultar', { method: 'POST' });
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

        // Normalizar los leads asignados para que coincidan con la tabla de la UI
        const normalizedLeads = (leadsRes.leads || []).map((l) => ({
          id: l.id || l.lead_id,
          lead_id: l.lead_id || l.id,
          nombre: l.nombre,
          institucion: l.institucion_actual || l.institucion || '-',
          email_directo: l.email || l.email_directo || 'No declarado',
          paso_actual: l.paso_orden || l.paso_actual || 1,
          paso_etiqueta: l.paso_etiqueta || l.paso_accion || '',
          estado_secuencia: l.estado || l.estado_secuencia || 'EN_CURSO',
          perfil_url: l.perfil_url,
          proxima_ejecucion_at: l.proxima_ejecucion_at,
        }));

        const proxLead = merged.proximo_lead
          ? {
              ...merged.proximo_lead,
              paso_actual: merged.proximo_lead.paso_orden || merged.proximo_lead.paso_actual || 1,
            }
          : null;

        return {
          ...merged,
          publicada: Boolean(merged.activa || merged.estado === 'PUBLICADA'),
          listas_asociadas: associatedLists,
          listas_conectadas: associatedLists.map(l => l.nombre || l.id),
          leads_inscritos: normalizedLeads,
          leads_completados_count: merged.total_completados ?? merged.leads_completados ?? 0,
          candidato_proximo: proxLead,
          pasos: normalizedSteps,
        };
      } catch {
        return {
          ...s,
          publicada: Boolean(s.activa || s.estado === 'PUBLICADA'),
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

export async function createSequence(data) {
  // Crea una nueva secuencia con su plantilla inicial
  const body = {
    nombre: data.nombre,
    descripcion: data.descripcion || '',
    activa: data.publicada !== false,
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

export async function toggleSequencePublish(sequenceId) {
  // Publica o pausa una secuencia individual
  const seq = await request(`/secuencias/${sequenceId}`);
  const nuevoEstado = (seq.estado === 'PUBLICADA' || seq.activa) ? 'PAUSADA' : 'PUBLICADA';
  return await request(`/secuencias/${sequenceId}/estado`, {
    method: 'POST',
    body: JSON.stringify({ estado: nuevoEstado }),
  });
}

export async function connectListToSequence(sequenceId, listId) {
  // Vincula una lista de leads a una secuencia
  return await request(`/listas/${listId}/conectar-secuencia`, {
    method: 'POST',
    body: JSON.stringify({ secuencia_id: sequenceId }),
  });
}

export async function disconnectListFromSequence(sequenceId, listId) {
  // Desvincula una lista de leads de una secuencia
  return await request(`/listas/${listId}/desconectar-secuencia`, {
    method: 'POST',
    body: JSON.stringify({ secuencia_id: sequenceId }),
  });
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

export async function fetchLogStats() {
  // Obtiene métricas agregadas de actividad reciente y estado del extractor
  return await request('/logs/stats');
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

// Backward compatibility aliases
export const togglePilotoAutomatico = toggleAutopilot;
export const fetchProximaTarea = fetchNextTask;
export const reportarTareaResultado = reportTaskResult;

