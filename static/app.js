// State Management
let currentFilter = '';
let currentSearch = '';
let currentLeads = [];
let currentSelectedLeadId = null;
let campaignActive = localStorage.getItem('dripify_campaign_active') === 'true';

// Column Management & Sorting
const DEFAULT_COLUMN_ORDER = ['contacto', 'perfil_linkedin', 'cargo', 'institucion', 'email', 'telefono', 'ubicacion', 'red', 'estado', 'acciones'];

const COLUMNS_DEF = {
    contacto: { label: 'Director / Contacto', sortKey: 'nombre' },
    perfil_linkedin: { label: 'LinkedIn BrowserOS', sortKey: null },
    cargo: { label: 'Cargo & Especialidad', sortKey: 'cargo_titular' },
    institucion: { label: 'Colegio / Institución', sortKey: 'institucion_actual' },
    email: { label: 'Correo Electrónico', sortKey: 'email' },
    telefono: { label: 'Teléfono', sortKey: 'telefono' },
    ubicacion: { label: 'Ubicación', sortKey: 'ubicacion' },
    red: { label: 'Red', sortKey: 'grado_red' },
    estado: { label: 'Estado Actual', sortKey: 'estado' },
    acciones: { label: 'Acciones', sortKey: null }
};

let columnOrder = loadColumnOrder();
let currentSortKey = null;
let currentSortDir = 'asc'; // 'asc' | 'desc'
let draggedColumnKey = null;

function loadColumnOrder() {
    try {
        const saved = JSON.parse(localStorage.getItem('dripify_column_order'));
        if (Array.isArray(saved)) {
            // Filtrar solo las que existen
            const currentList = saved.filter(c => DEFAULT_COLUMN_ORDER.includes(c));
            // Incorporar cualquier columna nueva que no estuviera guardada
            DEFAULT_COLUMN_ORDER.forEach(col => {
                if (!currentList.includes(col)) {
                    const accIdx = currentList.indexOf('acciones');
                    if (accIdx !== -1) currentList.splice(accIdx, 0, col);
                    else currentList.push(col);
                }
            });
            return currentList;
        }
    } catch (e) {}
    return [...DEFAULT_COLUMN_ORDER];
}

function saveColumnOrder() {
    localStorage.setItem('dripify_column_order', JSON.stringify(columnOrder));
}

function resetColumnas() {
    columnOrder = [...DEFAULT_COLUMN_ORDER];
    saveColumnOrder();
    currentSortKey = null;
    currentSortDir = 'asc';
    renderTableHeader();
    renderTabla(currentLeads);
    showToast('Orden de columnas restablecido por defecto.');
}

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    updateCampaignUI();
    renderTableHeader();
    cargarDatos();
    cargarListas();
    cargarSecuencias();
    verificarEstadoBrowserOS();
    // Auto-refresco de métricas, listas y seguridad cada 30 segundos
    setInterval(cargarMetricas, 30000);
    setInterval(cargarListas, 30000);
    setInterval(cargarEstadoSeguridad, 30000);
    // Verificación de BrowserOS cada 15 segundos
    setInterval(verificarEstadoBrowserOS, 15000);
});

// ==========================================================================
// Encabezado de Tabla Dinámico, Arrastrable y Ordenable
// ==========================================================================
function renderTableHeader() {
    const tr = document.getElementById('leads-header-row');
    if (!tr) return;

    tr.innerHTML = columnOrder.map(colKey => {
        const col = COLUMNS_DEF[colKey];
        if (!col) return '';

        const isSorted = currentSortKey === col.sortKey;
        let sortIcon = '↕';
        let sortClass = 'sort-indicator';
        if (isSorted) {
            sortIcon = currentSortDir === 'asc' ? '▲' : '▼';
            sortClass += ' active';
        }

        const isDraggable = colKey !== 'acciones';
        const sortableAttr = col.sortKey ? `onclick="handleSortClick('${col.sortKey}')"` : '';

        return `
            <th class="${isDraggable ? 'draggable-th' : ''}" 
                data-col-key="${colKey}" 
                ${isDraggable ? 'draggable="true"' : ''}>
                <div class="th-content" ${sortableAttr} title="${col.sortKey ? 'Clic para ordenar por esta columna' : ''}">
                    <div class="th-label-group">
                        ${isDraggable ? '<span class="th-drag-handle" title="Arrastrar para mover columna">⋮⋮</span>' : ''}
                        <span>${col.label}</span>
                    </div>
                    ${col.sortKey ? `<span class="${sortClass}">${sortIcon}</span>` : ''}
                </div>
            </th>
        `;
    }).join('');

    setupColumnDragAndDrop();
}

function setupColumnDragAndDrop() {
    const ths = document.querySelectorAll('#leads-header-row th.draggable-th');
    ths.forEach(th => {
        th.addEventListener('dragstart', handleDragStart);
        th.addEventListener('dragover', handleDragOver);
        th.addEventListener('dragenter', handleDragEnter);
        th.addEventListener('dragleave', handleDragLeave);
        th.addEventListener('drop', handleDrop);
        th.addEventListener('dragend', handleDragEnd);
    });
}

function handleDragStart(e) {
    draggedColumnKey = this.getAttribute('data-col-key');
    this.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', draggedColumnKey);
}

function handleDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
}

function handleDragEnter(e) {
    if (this.getAttribute('data-col-key') !== draggedColumnKey) {
        this.classList.add('drag-over');
    }
}

function handleDragLeave(e) {
    this.classList.remove('drag-over');
}

function handleDrop(e) {
    e.preventDefault();
    this.classList.remove('drag-over');
    const targetColKey = this.getAttribute('data-col-key');

    if (draggedColumnKey && targetColKey && draggedColumnKey !== targetColKey) {
        const fromIdx = columnOrder.indexOf(draggedColumnKey);
        const toIdx = columnOrder.indexOf(targetColKey);

        if (fromIdx !== -1 && toIdx !== -1) {
            columnOrder.splice(fromIdx, 1);
            columnOrder.splice(toIdx, 0, draggedColumnKey);
            saveColumnOrder();
            renderTableHeader();
            renderTabla(currentLeads);
            showToast(`Columna movida: ${COLUMNS_DEF[draggedColumnKey].label}`);
        }
    }
}

function handleDragEnd(e) {
    this.classList.remove('dragging');
    document.querySelectorAll('#leads-header-row th').forEach(th => th.classList.remove('drag-over'));
    draggedColumnKey = null;
}

// ==========================================================================
// Ordenamiento de Registros por Columna (Sorting)
// ==========================================================================
function handleSortClick(sortKey) {
    if (!sortKey) return;

    if (currentSortKey === sortKey) {
        if (currentSortDir === 'asc') {
            currentSortDir = 'desc';
        } else {
            currentSortKey = null;
            currentSortDir = 'asc';
        }
    } else {
        currentSortKey = sortKey;
        currentSortDir = 'asc';
    }

    renderTableHeader();
    renderTabla(currentLeads);
}

function getSortedLeads(leads) {
    if (!currentSortKey) return leads;

    return [...leads].sort((a, b) => {
        let valA = a[currentSortKey];
        let valB = b[currentSortKey];

        if (valA === null || valA === undefined) valA = '';
        if (valB === null || valB === undefined) valB = '';

        if (typeof valA === 'string') valA = valA.toLowerCase();
        if (typeof valB === 'string') valB = valB.toLowerCase();

        if (valA < valB) return currentSortDir === 'asc' ? -1 : 1;
        if (valA > valB) return currentSortDir === 'asc' ? 1 : -1;
        return 0;
    });
}

// ==========================================================================
// API Calls: Cargar Métricas y Prospectos
// ==========================================================================
async function cargarDatos() {
    await Promise.all([cargarMetricas(), cargarProspectos(), cargarEstadoSeguridad()]);
}

async function cargarMetricas() {
    try {
        const res = await fetch('/api/metricas');
        if (!res.ok) throw new Error('Error al obtener métricas');
        const data = await res.json();

        const metricHoy = document.getElementById('metric-hoy');
        if (metricHoy) metricHoy.innerHTML = `${data.invitaciones_hoy} <span class="kpi-denom">/ ${data.limite_diario}</span>`;

        const pct = Math.min(100, Math.round((data.invitaciones_hoy / data.limite_diario) * 100));
        const progressBar = document.getElementById('metric-progress-bar');
        if (progressBar) progressBar.style.width = `${pct}%`;

        const cupoText = document.getElementById('metric-cupo-text');
        if (cupoText) cupoText.textContent = `${data.cupo_restante_hoy} invitaciones disponibles hoy`;

        const quotaRemaining = document.getElementById('quota-remaining');
        if (quotaRemaining) quotaRemaining.textContent = `${data.cupo_restante_hoy} / ${data.limite_diario}`;

        const metricCola = document.getElementById('metric-cola');
        if (metricCola) metricCola.textContent = data.en_cola;

        const metricEnviadas = document.getElementById('metric-enviadas');
        if (metricEnviadas) metricEnviadas.textContent = data.invitaciones_enviadas;

        const metricConectados = document.getElementById('metric-conectados');
        if (metricConectados) metricConectados.textContent = data.conectados;

        const tasaBadge = document.getElementById('metric-tasa-badge');
        if (tasaBadge) tasaBadge.textContent = `Tasa: ${data.tasa_aceptacion_pct}%`;

        const totalBadge = document.getElementById('total-badge');
        if (totalBadge) totalBadge.textContent = `${data.total_leads} registrados`;
    } catch (err) {
        console.error('Error cargando métricas:', err);
    }
}

async function cargarProspectos() {
    try {
        let url = `/api/prospectos?limit=100`;
        if (currentFilter) url += `&estado=${encodeURIComponent(currentFilter)}`;
        if (currentSearch) url += `&busqueda=${encodeURIComponent(currentSearch)}`;

        const res = await fetch(url);
        if (!res.ok) throw new Error('Error al obtener prospectos');
        const data = await res.json();
        currentLeads = data.leads || [];
        renderTabla(currentLeads);
    } catch (err) {
        console.error('Error cargando prospectos:', err);
        const tbody = document.getElementById('leads-tbody');
        if (tbody) tbody.innerHTML = `<tr><td colspan="${columnOrder.length}" class="loading-cell" style="color: #F43F5E;">Error al conectar con la base de datos</td></tr>`;
    }
}

// ==========================================================================
// Renderizado Dinámico de Celdas según ColumnOrder
// ==========================================================================
function renderTabla(leads) {
    const tbody = document.getElementById('leads-tbody');
    if (!tbody) return;

    if (!leads || leads.length === 0) {
        tbody.innerHTML = `<tr><td colspan="${columnOrder.length}" class="loading-cell">No se encontraron prospectos con este filtro.</td></tr>`;
        return;
    }

    const leadsToShow = getSortedLeads(leads);

    tbody.innerHTML = leadsToShow.map(lead => {
        const cellsHtml = columnOrder.map(colKey => {
            switch (colKey) {
                case 'contacto': {
                    const iniciales = getInitials(lead.nombre);
                    return `
                        <td>
                            <div class="lead-cell">
                                <div class="lead-avatar" onclick="verFichaLead('${lead.id}')" style="cursor: pointer;" title="Ver Ficha / Historial">${iniciales}</div>
                                <div class="lead-name-group">
                                    <span class="lead-name">
                                        <a href="javascript:void(0)" onclick="abrirPerfilEnBrowserOS('${lead.id}', '${escapeHtml(lead.perfil_url)}', '${escapeHtml(lead.nombre)}')" class="lead-name-link" title="Clic para abrir perfil directamente en BrowserOS">
                                            ${escapeHtml(lead.nombre)}
                                        </a>
                                        <a href="${escapeHtml(lead.perfil_url)}" target="_blank" class="link-external-icon" title="Abrir en pestaña normal del navegador">
                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                                                <polyline points="15 3 21 3 21 9"></polyline>
                                                <line x1="10" y1="14" x2="21" y2="3"></line>
                                            </svg>
                                        </a>
                                    </span>
                                </div>
                            </div>
                        </td>
                    `;
                }
                case 'perfil_linkedin': {
                    return `
                        <td>
                            <div class="linkedin-cell-group">
                                <button class="btn-open-browseros" onclick="abrirPerfilEnBrowserOS('${lead.id}', '${escapeHtml(lead.perfil_url)}', '${escapeHtml(lead.nombre)}')" title="Abrir perfil de ${escapeHtml(lead.nombre)} en BrowserOS">
                                    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
                                        <path d="M19 3a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14m-.5 15.5v-5.3a3.26 3.26 0 0 0-3.26-3.26c-.85 0-1.84.52-2.28 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 0 1 1.4 1.4v4.93h2.75M6.46 10.9v8.37H9.2V10.9H6.46M7.83 6.64a1.64 1.64 0 1 0 0 3.28 1.64 1.64 0 0 0 0-3.28Z"/>
                                    </svg>
                                    <span>BrowserOS</span>
                                </button>
                                <a href="${escapeHtml(lead.perfil_url)}" target="_blank" class="link-external-icon" title="Abrir en pestaña normal">
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                                        <polyline points="15 3 21 3 21 9"></polyline>
                                        <line x1="10" y1="14" x2="21" y2="3"></line>
                                    </svg>
                                </a>
                            </div>
                        </td>
                    `;
                }
                case 'cargo': {
                    const cargo = lead.cargo_titular || 'Cargo no especificado';
                    return `
                        <td>
                            <div style="max-width: 240px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${escapeHtml(cargo)}">
                                ${escapeHtml(cargo)}
                            </div>
                        </td>
                    `;
                }
                case 'institucion': {
                    const colegio = lead.institucion_actual || 'Colegio no especificado';
                    return `
                        <td>
                            <span class="lead-institution">${escapeHtml(colegio)}</span>
                        </td>
                    `;
                }
                case 'email': {
                    if (lead.email) {
                        return `
                            <td>
                                <a href="mailto:${escapeHtml(lead.email)}" class="contact-pill mail" title="${escapeHtml(lead.email)}">
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                                        <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path>
                                        <polyline points="22,6 12,13 2,6"></polyline>
                                    </svg>
                                    <span>${escapeHtml(lead.email)}</span>
                                </a>
                            </td>
                        `;
                    }
                    return `<td><span class="contact-empty">—</span></td>`;
                }
                case 'telefono': {
                    if (lead.telefono) {
                        return `
                            <td>
                                <a href="tel:${escapeHtml(lead.telefono)}" class="contact-pill phone" title="${escapeHtml(lead.telefono)}">
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                                        <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path>
                                    </svg>
                                    <span>${escapeHtml(lead.telefono)}</span>
                                </a>
                            </td>
                        `;
                    }
                    return `<td><span class="contact-empty">—</span></td>`;
                }
                case 'ubicacion': {
                    const ubicacion = lead.ubicacion || 'Chile';
                    return `
                        <td>
                            <span style="color: var(--text-dim);">${escapeHtml(ubicacion)}</span>
                        </td>
                    `;
                }
                case 'red': {
                    return `
                        <td>
                            <span style="font-weight: 600; color: var(--text-muted);">${escapeHtml(lead.grado_red || '2º')}</span>
                        </td>
                    `;
                }
                case 'estado': {
                    const badgeInfo = getBadgeInfo(lead.estado);
                    return `
                        <td>
                            <span class="status-badge ${badgeInfo.className}">
                                ${badgeInfo.label}
                            </span>
                        </td>
                    `;
                }
                case 'acciones': {
                    return `
                        <td>
                            <div class="action-btn-group">
                                <button class="btn-action-view" onclick="verFichaLead('${lead.id}')">
                                    Ficha / Historial
                                </button>
                            </div>
                        </td>
                    `;
                }
                default:
                    return `<td>-</td>`;
            }
        }).join('');

        return `<tr>${cellsHtml}</tr>`;
    }).join('');
}

function getBadgeInfo(estado) {
    switch (estado) {
        case 'EXTRAIDO':
            return { className: 'badge-extraido', label: 'En Cola' };
        case 'PERFIL_VISITADO':
            return { className: 'badge-visitado', label: 'Perfil Visitado' };
        case 'INVITACION_ENVIADA':
            return { className: 'badge-enviada', label: 'Invitación Enviada' };
        case 'INVITACION_PENDIENTE':
            return { className: 'badge-enviada', label: 'Pendiente Previo' };
        case 'CONECTADO':
            return { className: 'badge-conectado', label: 'Conectado' };
        default:
            return { className: 'badge-extraido', label: estado };
    }
}

function getInitials(name) {
    if (!name) return '??';
    const parts = name.trim().split(' ');
    if (parts.length === 1) return parts[0].substring(0, 2).toUpperCase();
    return (parts[0][0] + parts[1][0]).toUpperCase();
}

function escapeHtml(text) {
    if (!text) return '';
    return text.replace(/[&<>"']/g, m => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
    })[m]);
}

// ==========================================================================
// Filtros y Búsqueda
// ==========================================================================
function setFilter(buttonEl, filterValue) {
    document.querySelectorAll('.filter-tab').forEach(b => b.classList.remove('active'));
    buttonEl.classList.add('active');
    currentFilter = filterValue;
    cargarProspectos();
}

let searchTimeout;
function handleSearch() {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
        const input = document.getElementById('search-input');
        currentSearch = input.value.trim();
        cargarProspectos();
    }, 250);
}

// ==========================================================================
// Campaña Toggle
// ==========================================================================
function toggleCampaign() {
    campaignActive = !campaignActive;
    localStorage.setItem('dripify_campaign_active', campaignActive);
    updateCampaignUI();
    showToast(campaignActive ? '▶ Campaña activada. El motor trabajará en segundo plano.' : '⏸ Campaña pausada.');
}

function updateCampaignUI() {
    const btn = document.getElementById('campaign-toggle-btn');
    const text = document.getElementById('campaign-status-text');
    const icon = document.getElementById('campaign-icon');

    if (!btn || !text || !icon) return;

    if (campaignActive) {
        btn.className = 'campaign-btn active';
        text.textContent = 'ACTIVA';
        icon.textContent = '▶';
    } else {
        btn.className = 'campaign-btn paused';
        text.textContent = 'PAUSADA';
        icon.textContent = '⏸';
    }
}

// ==========================================================================
// Modal Drawer de Detalle del Lead
// ==========================================================================
async function verFichaLead(leadId) {
    try {
        const res = await fetch(`/api/prospectos/${leadId}`);
        if (!res.ok) throw new Error('No se pudo cargar el lead');
        const lead = await res.json();

        // Llenar header
        document.getElementById('modal-avatar').textContent = getInitials(lead.nombre);
        document.getElementById('modal-nombre').textContent = lead.nombre;
        document.getElementById('modal-cargo').textContent = lead.cargo_titular || 'Cargo no especificado';

        // Lead ID activo para edición
        currentSelectedLeadId = lead.id;
        currentSelectedLead = lead;

        // Llenar tab Resumen
        document.getElementById('modal-institucion').textContent = lead.institucion_actual || 'No especificado';
        
        // Correo y Teléfono
        const emailEl = document.getElementById('modal-email');
        if (lead.email) {
            emailEl.innerHTML = `<a href="mailto:${escapeHtml(lead.email)}" class="value link">${escapeHtml(lead.email)}</a>`;
        } else {
            emailEl.innerHTML = `<span class="empty-val">No disponible</span>`;
        }
        document.getElementById('input-edit-email').value = lead.email || '';

        const telEl = document.getElementById('modal-telefono');
        if (lead.telefono) {
            telEl.innerHTML = `<a href="tel:${escapeHtml(lead.telefono)}" class="value link mono-val">${escapeHtml(lead.telefono)}</a>`;
        } else {
            telEl.innerHTML = `<span class="empty-val">No disponible</span>`;
        }
        document.getElementById('input-edit-telefono').value = lead.telefono || '';

        document.getElementById('modal-ubicacion').textContent = lead.ubicacion || 'Chile';
        document.getElementById('modal-grado').textContent = lead.grado_red || '2º';
        
        const urlEl = document.getElementById('modal-url');
        urlEl.href = lead.perfil_url;
        urlEl.textContent = 'Pestaña normal ↗';

        document.getElementById('modal-siguiendo').textContent = lead.siguiendo ? `Sí (desde ${lead.siguiendo_desde || ''})` : 'No';
        document.getElementById('modal-fecha-extraccion').textContent = lead.fecha_extraccion ? formatDate(lead.fecha_extraccion) : '-';
        document.getElementById('modal-fecha-visita').textContent = lead.fecha_visita ? formatDate(lead.fecha_visita) : 'No visitado aún';
        document.getElementById('modal-fecha-invitacion').textContent = lead.fecha_invitacion ? formatDate(lead.fecha_invitacion) : 'No enviada aún';

        // Tags
        const tagsContainer = document.getElementById('modal-tags');
        const tags = lead.tags || [];
        tagsContainer.innerHTML = tags.map(t => `<span class="chip">${escapeHtml(t)}</span>`).join('') || '<span style="color:var(--text-dim);">Sin etiquetas</span>';

        // Timeline Historial
        const timeline = document.getElementById('modal-timeline');
        const historial = lead.historial || [];
        if (historial.length === 0) {
            timeline.innerHTML = '<p style="color:var(--text-dim);">No hay actividad registrada aún.</p>';
        } else {
            timeline.innerHTML = historial.map(item => `
                <div class="timeline-item">
                    <div class="timeline-dot"></div>
                    <div class="timeline-header">
                        <span class="timeline-action">${escapeHtml(item.tipo_evento)}</span>
                        <span class="timeline-time">${formatDate(item.timestamp)}</span>
                    </div>
                    <p class="timeline-desc">${escapeHtml(item.descripcion)}</p>
                </div>
            `).join('');
        }

        // Footer Actions Dinámicos
        const footer = document.getElementById('modal-footer-actions');
        footer.innerHTML = `
            <button class="btn-browser-inline" onclick="abrirPerfilEnBrowserOS('${lead.id}', '${escapeHtml(lead.perfil_url)}', '${escapeHtml(lead.nombre)}')">
                🌐 Abrir en BrowserOS
            </button>
            <button class="btn-secondary" onclick="toggleSeguir('${lead.id}', ${!lead.siguiendo})">
                ${lead.siguiendo ? 'Dejar de Seguir' : 'Seguir en LinkedIn'}
            </button>
            ${lead.estado === 'INVITACION_ENVIADA' ? `
                <button class="btn-danger" onclick="retirarInvitacion('${lead.id}')">
                    Retirar Invitación
                </button>
            ` : ''}
        `;

        // Abrir Drawer
        document.getElementById('lead-modal-backdrop').classList.add('open');
    } catch (err) {
        console.error('Error cargando ficha:', err);
        showToast('Error al cargar la información del contacto');
    }
}

function switchModalTab(tabId) {
    document.querySelectorAll('.modal-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

    const tabBtn = Array.from(document.querySelectorAll('.modal-tab')).find(b => b.textContent.toLowerCase().includes(tabId));
    if (tabBtn) tabBtn.classList.add('active');

    const pane = document.getElementById(`pane-${tabId}`);
    if (pane) pane.classList.add('active');
}

function cerrarModal() {
    document.getElementById('lead-modal-backdrop').classList.remove('open');
}

// ==========================================================================
// Acciones de Red
// ==========================================================================
async function toggleSeguir(leadId, seguir) {
    try {
        const res = await fetch(`/api/prospectos/${leadId}/seguir?seguir=${seguir}`, { method: 'POST' });
        if (!res.ok) throw new Error('Error al actualizar estado');
        showToast(seguir ? 'Comenzaste a seguir al contacto.' : 'Dejaste de seguir al contacto.');
        cerrarModal();
        cargarDatos();
    } catch (err) {
        console.error(err);
        showToast('Error al procesar la acción');
    }
}

async function retirarInvitacion(leadId) {
    if (!confirm('¿Seguro que deseas retirar la invitación enviada a este contacto?')) return;
    try {
        const res = await fetch(`/api/prospectos/${leadId}/retirar-invitacion`, { method: 'POST' });
        if (!res.ok) throw new Error('Error al retirar invitación');
        showToast('Invitación retirada con éxito.');
        cerrarModal();
        cargarDatos();
    } catch (err) {
        console.error(err);
        showToast('Error al retirar la invitación');
    }
}

async function guardarDatosContacto() {
    if (!currentSelectedLeadId) return;
    const email = document.getElementById('input-edit-email').value.trim();
    const telefono = document.getElementById('input-edit-telefono').value.trim();

    try {
        const url = `/api/prospectos/${encodeURIComponent(currentSelectedLeadId)}/contacto?email=${encodeURIComponent(email)}&telefono=${encodeURIComponent(telefono)}`;
        const res = await fetch(url, { method: 'PUT' });
        if (!res.ok) throw new Error('Error al actualizar datos de contacto');
        showToast('Datos de contacto guardados con éxito.');
        await verFichaLead(currentSelectedLeadId);
        cargarProspectos();
    } catch (err) {
        console.error(err);
        showToast('Error al guardar datos de contacto');
    }
}

// ==========================================================================
// Utilities
// ==========================================================================
function formatDate(isoStr) {
    if (!isoStr) return '';
    try {
        const d = new Date(isoStr);
        return d.toLocaleString('es-CL', {
            year: 'numeric', month: 'short', day: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
    } catch (e) {
        return isoStr;
    }
}

function showToast(message) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#10B981" stroke-width="2">
            <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        <span>${escapeHtml(message)}</span>
    `;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        toast.style.transition = 'all 0.25s ease';
        setTimeout(() => toast.remove(), 250);
    }, 4000);
}

// ==========================================================================
// Integración con BrowserOS: Apertura de Perfiles y Sesiones de Trabajo
// ==========================================================================
let currentSelectedLead = null;

function abrirPerfilModalEnBrowserOS() {
    if (!currentSelectedLead) return;
    abrirPerfilEnBrowserOS(currentSelectedLead.id, currentSelectedLead.perfil_url, currentSelectedLead.nombre);
}

async function abrirPerfilEnBrowserOS(leadId, perfilUrl, leadNombre) {
    showToast(`Abriendo perfil de ${leadNombre || 'lead'} en BrowserOS...`);
    try {
        const res = await fetch(`/api/prospectos/${encodeURIComponent(leadId)}/abrir-en-browseros`, {
            method: 'POST'
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast(`Perfil de ${leadNombre || 'lead'} cargado en BrowserOS.`);
            // Si la ficha está abierta para este lead, recargar su historial
            if (currentSelectedLeadId === leadId) {
                verFichaLead(leadId);
            }
        } else {
            throw new Error(data.detail || 'Error al abrir');
        }
    } catch (err) {
        console.error('Error abriendo en BrowserOS:', err);
        showToast('Abriendo en pestaña normal del navegador...');
        window.open(perfilUrl, '_blank');
    }
}

async function verificarEstadoBrowserOS() {
    try {
        const res = await fetch('/api/browser/estado');
        if (!res.ok) return;
        const data = await res.json();
        
        const pill = document.getElementById('browseros-status');
        const text = document.getElementById('browseros-status-text');
        const btn = document.getElementById('btn-iniciar-browser');
        const btnText = document.getElementById('btn-iniciar-browser-text');
        
        if (data.activo) {
            if (pill) {
                pill.className = 'status-pill connected';
                pill.title = 'Sesión de BrowserOS conectada y activa vía MCP (clic para re-verificar)';
            }
            if (text) text.textContent = 'BrowserOS Activo';
            if (btn) {
                btn.className = 'btn-browser-launch connected';
                btn.title = 'BrowserOS ya está abierto. Clic para asegurar pestañas de LinkedIn y Zoho CRM.';
            }
            if (btnText) btnText.textContent = 'Abrir LinkedIn & Zoho';
        } else {
            if (pill) {
                pill.className = 'status-pill disconnected';
                pill.title = 'BrowserOS inactivo. Haz clic para levantarlo con sesiones de LinkedIn y Zoho.';
            }
            if (text) text.textContent = 'BrowserOS Inactivo';
            if (btn) {
                btn.className = 'btn-browser-launch disconnected';
                btn.title = 'Iniciar BrowserOS con LinkedIn y Zoho CRM listos para trabajar';
            }
            if (btnText) btnText.textContent = 'Iniciar BrowserOS (LinkedIn + Zoho)';
        }
    } catch (err) {
        console.warn('Error verificando estado BrowserOS:', err);
    }
}

async function iniciarBrowserOS() {
    const btn = document.getElementById('btn-iniciar-browser');
    if (btn) btn.disabled = true;
    showToast('Iniciando BrowserOS con sesiones de LinkedIn y Zoho CRM...');
    
    try {
        const res = await fetch('/api/browser/iniciar', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast(data.mensaje || 'BrowserOS iniciado con éxito.');
            setTimeout(verificarEstadoBrowserOS, 2000);
        } else {
            showToast('Error al iniciar BrowserOS: ' + (data.mensaje || 'Error desconocido'));
        }
    } catch (err) {
        console.error('Error al iniciar BrowserOS:', err);
        showToast('Error de conexión al intentar iniciar BrowserOS');
    } finally {
        if (btn) btn.disabled = false;
    }
}

// ==========================================================================
// Monitor de Seguridad Anti-Baneo y Horario Laboral
// ==========================================================================
async function cargarEstadoSeguridad() {
    try {
        const res = await fetch('/api/seguridad/estado');
        if (!res.ok) return;
        const data = await res.json();
        
        const schedulePill = document.getElementById('schedule-pill');
        const scheduleText = document.getElementById('schedule-status-text');
        const safetyBanner = document.getElementById('safety-banner');
        const safetyIcon = document.getElementById('safety-icon');
        const safetyText = document.getElementById('safety-text');
        
        // Manejo de Kill-Switch
        if (data.kill_switch && data.kill_switch.activado) {
            if (safetyBanner) {
                safetyBanner.style.borderColor = '#F43F5E';
                safetyBanner.style.background = 'rgba(244, 63, 94, 0.15)';
            }
            if (safetyIcon) safetyIcon.textContent = '🚨';
            if (safetyText) {
                safetyText.innerHTML = `<strong>FRENO DE EMERGENCIA ACTIVO:</strong> ${escapeHtml(data.kill_switch.motivo)} <button onclick="desactivarKillSwitch()" class="btn-save-contact" style="background:#F43F5E; margin-left:10px; cursor:pointer;">Reanudar Operaciones</button>`;
            }
        } else {
            if (safetyBanner) {
                safetyBanner.style.borderColor = '';
                safetyBanner.style.background = '';
            }
            if (safetyIcon) safetyIcon.textContent = '🛡️';
        }
        
        // Manejo de Horario Laboral
        if (scheduleText) {
            if (data.horario_laboral.en_horario) {
                scheduleText.textContent = `En Horario Laboral`;
                if (schedulePill) {
                    schedulePill.title = data.horario_laboral.detalle;
                    const dot = schedulePill.querySelector('.status-indicator-dot');
                    if (dot) { dot.className = 'status-indicator-dot online'; }
                }
            } else {
                scheduleText.textContent = `Fuera de Horario (Pausado)`;
                if (schedulePill) {
                    schedulePill.title = data.horario_laboral.detalle;
                    const dot = schedulePill.querySelector('.status-indicator-dot');
                    if (dot) { dot.className = 'status-indicator-dot offline'; }
                }
            }
        }
    } catch (e) {
        console.warn('Error cargando estado de seguridad:', e);
    }
}

async function desactivarKillSwitch() {
    try {
        const res = await fetch('/api/seguridad/kill-switch/desactivar', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast('Freno de emergencia desactivado.');
            cargarEstadoSeguridad();
        }
    } catch (e) {
        showToast('Error al desactivar freno de emergencia');
    }
}

// ==========================================================================
// Extracción Automática de Leads desde LinkedIn
// ==========================================================================
function aplicarPresetBusqueda(termino) {
    const input = document.getElementById('input-busqueda-linkedin');
    if (input) {
        input.value = termino;
        input.focus();
        showToast(`Búsqueda establecida: ${termino}`);
    }
}

async function ejecutarExtraccionLinkedIn() {
    const input = document.getElementById('input-busqueda-linkedin');
    const selectPagina = document.getElementById('select-pagina-linkedin');
    const selectLista = document.getElementById('select-extractor-target-list');
    const btn = document.getElementById('btn-ejecutar-extraccion');
    const btnIcon = document.getElementById('extractor-btn-icon');
    const btnText = document.getElementById('extractor-btn-text');

    const termino = input ? input.value.trim() : 'Director de Colegio Chile';
    const pagina = selectPagina ? parseInt(selectPagina.value, 10) : 1;
    const listaId = selectLista ? selectLista.value : '';

    if (!termino) {
        showToast('Por favor ingresa un término de búsqueda');
        return;
    }

    if (btn) btn.disabled = true;
    if (btnIcon) btnIcon.textContent = '⏳';
    if (btnText) btnText.textContent = `Extrayendo en BrowserOS (Pág. ${pagina})...`;
    showToast(`Iniciando extracción de "${termino}" en BrowserOS...`);

    try {
        let url = `/api/extraccion/buscar?termino=${encodeURIComponent(termino)}&pagina=${pagina}&auto_guardar=true`;
        if (listaId) {
            url += `&lista_id=${encodeURIComponent(listaId)}`;
        }
        const res = await fetch(url, { method: 'POST' });
        const data = await res.json();

        if (data.status === 'ok') {
            const nuevos = data.nuevos_importados || 0;
            const duplicados = data.duplicados_omitidos || 0;
            showToast(`¡Extracción completada! ${nuevos} nuevos leads importados (${duplicados} duplicados omitidos).`);
            
            // Recargar tabla, listas y métricas en tiempo real
            await cargarDatos();
            await cargarListas();
            if (currentMainView === 'secuencias') {
                await cargarLeadsEnSecuencia();
            }

            // Incrementar selector a la siguiente página automáticamente
            if (selectPagina) {
                const nextPag = pagina + 1;
                if (selectPagina.querySelector(`option[value="${nextPag}"]`)) {
                    selectPagina.value = nextPag.toString();
                }
            }
        } else if (data.status === 'warning') {
            showToast(data.mensaje || 'No se encontraron más resultados.');
        } else {
            showToast('Error: ' + (data.mensaje || 'Error desconocido al extraer'));
        }
    } catch (err) {
        console.error('Error al ejecutar extracción:', err);
        showToast('Error de conexión al ejecutar la extracción.');
    } finally {
        if (btn) btn.disabled = false;
        if (btnIcon) btnIcon.textContent = '⚡';
        if (btnText) btnText.textContent = 'Extraer 10 Leads en BrowserOS';
    }
}

// ==========================================================================
// GESTOR DE SECUENCIAS MULTICANAL Y ÁRBOLES DE DECISIÓN
// ==========================================================================
let currentMainView = 'prospectos';
let activeSequenceId = 'sec-default-directores-2026';
let activeSequenceData = null;
let currentEditingStep = null;
let secSubViewMode = 'flujo';
let currentGlobalSecFilter = '';
let allLoadedSecuencias = [];

function switchMainView(viewName, autoReload = true) {
    currentMainView = viewName;
    document.querySelectorAll('.nav-view-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.main-view').forEach(v => {
        v.style.display = 'none';
        v.classList.remove('active');
    });

    const activeBtn = document.getElementById(`tab-nav-${viewName}`);
    if (activeBtn) activeBtn.classList.add('active');

    const activeView = document.getElementById(`view-${viewName}`);
    if (activeView) {
        activeView.style.display = 'flex';
        activeView.classList.add('active');
    }

    if (viewName === 'secuencias') {
        cargarSecuencias();
        cargarSecuenciaDetalle(activeSequenceId);
        cargarLeadsEnSecuencia();
    } else if (viewName === 'listas') {
        cargarListas();
    } else if (viewName === 'prospectos' && autoReload) {
        cargarDatos();
    }
}

async function cargarSecuencias() {
    try {
        const res = await fetch('/api/secuencias');
        if (!res.ok) return;
        const data = await res.json();
        const secuencias = data.secuencias || [];
        allLoadedSecuencias = secuencias;

        const badge = document.getElementById('badge-secuencias-count');
        if (badge) badge.textContent = secuencias.length;

        const globalBadge = document.getElementById('sec-global-badge');
        if (globalBadge) globalBadge.textContent = `${secuencias.length} secuencias registradas`;

        const select = document.getElementById('select-secuencia-activa');
        if (select && secuencias.length > 0) {
            select.innerHTML = secuencias.map(s => `
                <option value="${s.id}" ${s.id === activeSequenceId ? 'selected' : ''}>
                    ${escapeHtml(s.nombre)}
                </option>
            `).join('');
        }

        if (secuencias.length > 0 && !activeSequenceId) {
            activeSequenceId = secuencias[0].id;
        }

        renderMatrizGlobalSecuencias(secuencias);
    } catch (e) {
        console.warn('Error cargando secuencias:', e);
    }
}

async function cambiarSecuenciaSeleccionada(secId) {
    activeSequenceId = secId;
    await cargarSecuenciaDetalle(secId);
    await cargarLeadsEnSecuencia();
}

async function cargarSecuenciaDetalle(secId) {
    if (!secId) return;
    try {
        const res = await fetch(`/api/secuencias/${encodeURIComponent(secId)}`);
        if (!res.ok) return;
        const sec = await res.json();
        activeSequenceData = sec;

        // Métricas de Pasos y Leads
        const pasosEl = document.getElementById('sec-total-pasos');
        if (pasosEl) pasosEl.textContent = sec.pasos ? sec.pasos.length : 0;

        const totalLeadsEl = document.getElementById('sec-leads-total');
        if (totalLeadsEl) totalLeadsEl.textContent = sec.total_inscritos ?? (sec.total_leads || 0);

        const enCursoEl = document.getElementById('sec-leads-en-curso');
        if (enCursoEl) enCursoEl.textContent = `${sec.total_en_curso || 0} en curso`;

        const compEl = document.getElementById('sec-leads-completados');
        if (compEl) compEl.textContent = sec.total_completados || 0;

        // Próximo lead listo a ejecutar
        const proximoNombre = document.getElementById('sec-proximo-lead-nombre');
        const proximaHora = document.getElementById('sec-proxima-hora');
        const btnEjecutarText = document.getElementById('btn-ejecutar-paso-text');

        if (sec.proximo_lead) {
            const pl = sec.proximo_lead;
            if (proximoNombre) {
                proximoNombre.textContent = pl.nombre || 'Lead en cola';
            }
            if (proximaHora) {
                const pasoStr = `Paso ${pl.paso_orden}: ${pl.etiqueta || pl.tipo_accion}`;
                if (pl.listo_ahora) {
                    proximaHora.innerHTML = `<span style="color: var(--status-emerald); font-weight: 600;">⚡ Listo: ${escapeHtml(pasoStr)}</span>`;
                } else {
                    proximaHora.innerHTML = `<span style="color: var(--status-amber);">⏳ Espera hasta ${formatDate(pl.proxima_ejecucion_at)} (${escapeHtml(pasoStr)})</span>`;
                }
            }
            if (btnEjecutarText) {
                if (pl.listo_ahora) {
                    btnEjecutarText.textContent = `⚡ Ejecutar: ${pl.nombre.split(' ')[0]} ➔ Paso ${pl.paso_orden}`;
                } else {
                    btnEjecutarText.textContent = `⏳ En espera: ${pl.nombre.split(' ')[0]} (Paso ${pl.paso_orden})`;
                }
            }
        } else {
            if (proximoNombre) proximoNombre.textContent = 'Ninguno en cola';
            if (proximaHora) proximaHora.textContent = 'Todos al día';
            if (btnEjecutarText) btnEjecutarText.textContent = 'Ejecutar Siguiente Paso Ahora';
        }

        actualizarHeaderSecuencia(sec);
        renderAudienceChipsSecuencia(sec.listas_asociadas || []);
        renderPipelineRibbon(sec);
        renderFlowchart(sec);
    } catch (e) {
        console.error('Error cargando detalle de secuencia:', e);
    }
}

function renderPipelineRibbon(sec) {
    const summaryEl = document.getElementById('pipeline-ribbon-summary');
    const trackEl = document.getElementById('pipeline-stages-track');
    if (!summaryEl || !trackEl) return;

    const enCurso = sec.total_en_curso || 0;
    const completados = sec.total_completados || 0;
    const inscritos = sec.total_inscritos || 0;

    summaryEl.textContent = `${enCurso} recorriendo el pipeline · ${completados} finalizados de ${inscritos} inscritos`;

    const pasos = sec.pasos || [];
    if (pasos.length === 0) {
        trackEl.innerHTML = '<span style="color: var(--text-muted); font-size: 0.75rem;">Sin pasos definidos en esta secuencia.</span>';
        return;
    }

    let stagesHtml = '';
    pasos.forEach((p, idx) => {
        const count = p.leads_en_paso || 0;
        const listos = p.leads_listos || 0;
        const enEspera = p.leads_en_espera || 0;
        const etiqueta = (p.parametros && p.parametros.etiqueta) ? p.parametros.etiqueta : p.tipo_accion;
        const hasLeadsClass = count > 0 ? 'has-leads' : '';

        const titleText = `${etiqueta}: ${count} leads (${listos} listos ahora, ${enEspera} en delay de seguridad)`;

        stagesHtml += `
            <div class="pipeline-stage-node ${hasLeadsClass}" title="${escapeHtml(titleText)}" onclick="abrirEditorPaso('${p.id}')" style="cursor: pointer;">
                <span class="stage-num">${p.orden}</span>
                <span class="stage-name">${escapeHtml(etiqueta)}</span>
                <span class="stage-count-badge">${count}</span>
            </div>
            ${idx < pasos.length - 1 ? '<span class="pipeline-stage-arrow">➔</span>' : ''}
        `;
    });

    stagesHtml += `
        <span class="pipeline-stage-arrow">➔</span>
        <div class="pipeline-stage-node completed ${completados > 0 ? 'has-leads' : ''}" title="Ciclo completo finalizado exitosamente">
            <span class="stage-num" style="color: var(--status-emerald);">✓</span>
            <span class="stage-name">Completados</span>
            <span class="stage-count-badge">${completados}</span>
        </div>
    `;

    trackEl.innerHTML = stagesHtml;
}

function actualizarHeaderSecuencia(sec) {
    const estado = (sec.estado || (sec.activa ? 'PUBLICADA' : 'PAUSADA')).toUpperCase();
    const pill = document.getElementById('secuencia-status-pill');
    const btnToggle = document.getElementById('btn-toggle-publicar-secuencia');
    const iconToggle = document.getElementById('btn-toggle-publish-icon');
    const textToggle = document.getElementById('btn-toggle-publish-text');

    if (pill) {
        if (estado === 'PUBLICADA') {
            pill.className = 'badge-status-active';
            pill.style.background = '';
            pill.style.color = '';
            pill.style.borderColor = '';
            pill.textContent = '● PUBLICADA';
        } else {
            pill.className = 'badge-status-active paused';
            pill.style.background = 'var(--status-amber-bg)';
            pill.style.color = 'var(--status-amber)';
            pill.style.borderColor = 'var(--status-amber-border)';
            pill.textContent = '⏸ PAUSADA';
        }
    }

    if (btnToggle) {
        if (estado === 'PUBLICADA') {
            btnToggle.className = 'btn-toggle-publish published';
            if (iconToggle) iconToggle.textContent = '⏸';
            if (textToggle) textToggle.textContent = 'Pausar Secuencia';
        } else {
            btnToggle.className = 'btn-toggle-publish paused';
            if (iconToggle) iconToggle.textContent = '▶';
            if (textToggle) textToggle.textContent = 'Publicar / Activar';
        }
    }
}

function renderAudienceChipsSecuencia(listas) {
    const container = document.getElementById('sec-audiences-chips');
    if (!container) return;

    if (!listas || listas.length === 0) {
        container.innerHTML = '<span class="audience-chip empty">Ninguna lista vinculada a esta secuencia</span>';
        return;
    }

    container.innerHTML = listas.map(l => `
        <div class="audience-chip">
            <span>${escapeHtml(l.nombre)}</span>
            <span class="chip-count">${l.total_leads || 0} leads</span>
            ${l.auto_ingresar_nuevos ? '<span class="chip-rt-badge" title="Auto-ingreso en tiempo real activo">⚡ En tiempo real</span>' : ''}
            <span class="chip-remove-btn" onclick="desconectarListaDeSecuencia('${l.id}', '${activeSequenceId}')" title="Desvincular esta lista">&times;</span>
        </div>
    `).join('');
}

async function togglePublicacionSecuenciaActual() {
    if (!activeSequenceData) return;
    const estadoActual = (activeSequenceData.estado || (activeSequenceData.activa ? 'PUBLICADA' : 'PAUSADA')).toUpperCase();
    const nuevoEstado = estadoActual === 'PUBLICADA' ? 'PAUSADA' : 'PUBLICADA';
    await cambiarEstadoSecuencia(activeSequenceData.id, nuevoEstado);
}

async function cambiarEstadoSecuencia(secId, nuevoEstado) {
    try {
        const res = await fetch(`/api/secuencias/${encodeURIComponent(secId)}/estado`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ estado: nuevoEstado })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast(`Secuencia marcada como ${nuevoEstado}`);
            await cargarSecuencias();
            if (activeSequenceId === secId) {
                await cargarSecuenciaDetalle(secId);
            }
        } else {
            showToast('Error al actualizar estado de la secuencia');
        }
    } catch (e) {
        console.error(e);
        showToast('Error de conexión al actualizar estado');
    }
}

function switchSecuenciaSubView(mode) {
    secSubViewMode = mode;
    const btnFlujo = document.getElementById('subtab-sec-flujo');
    const btnGlobal = document.getElementById('subtab-sec-global');
    const headerFlujo = document.getElementById('sec-header-flujo');
    const audiencesBar = document.getElementById('sec-audiences-bar');
    const containerFlujo = document.getElementById('sec-subview-flujo-container');
    const containerGlobal = document.getElementById('sec-subview-global-container');

    if (mode === 'flujo') {
        if (btnFlujo) btnFlujo.classList.add('active');
        if (btnGlobal) btnGlobal.classList.remove('active');
        if (headerFlujo) headerFlujo.style.display = 'flex';
        if (audiencesBar) audiencesBar.style.display = 'flex';
        if (containerFlujo) containerFlujo.style.display = 'block';
        if (containerGlobal) containerGlobal.style.display = 'none';
        cargarSecuenciaDetalle(activeSequenceId);
    } else {
        if (btnFlujo) btnFlujo.classList.remove('active');
        if (btnGlobal) btnGlobal.classList.add('active');
        if (headerFlujo) headerFlujo.style.display = 'none';
        if (audiencesBar) audiencesBar.style.display = 'none';
        if (containerFlujo) containerFlujo.style.display = 'none';
        if (containerGlobal) containerGlobal.style.display = 'block';
        renderMatrizGlobalSecuencias();
    }
}

function filtrarMatrizSecuenciasUI(btn, estado) {
    currentGlobalSecFilter = estado;
    const tabs = document.querySelectorAll('#sec-global-filter-tabs .filter-tab');
    tabs.forEach(t => t.classList.remove('active'));
    if (btn) btn.classList.add('active');
    renderMatrizGlobalSecuencias();
}

function renderMatrizGlobalSecuencias(secuencias = null) {
    const tbody = document.getElementById('sec-global-tbody');
    if (!tbody) return;

    const list = secuencias || allLoadedSecuencias;
    let filtradas = list;
    if (currentGlobalSecFilter) {
        filtradas = filtradas.filter(s => {
            const st = (s.estado || (s.activa ? 'PUBLICADA' : 'PAUSADA')).toUpperCase();
            return st === currentGlobalSecFilter;
        });
    }

    if (filtradas.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="loading-cell">No hay secuencias con el filtro seleccionado.</td></tr>`;
        return;
    }

    tbody.innerHTML = filtradas.map(s => {
        const estado = (s.estado || (s.activa ? 'PUBLICADA' : 'PAUSADA')).toUpperCase();
        const esPub = estado === 'PUBLICADA';
        const listas = s.listas_asociadas || [];

        const listasHtml = listas.length > 0
            ? listas.map(l => `<span class="sec-mini-chip">${escapeHtml(l.nombre)} <span class="mono-val" style="color: var(--status-blue);">(${l.total_leads || 0})</span></span>`).join(' ')
            : '<span style="color: var(--text-muted); font-size: 0.72rem;">Sin listas asignadas</span>';

        return `
            <tr>
                <td>
                    <div style="font-weight: 600; color: var(--text-primary);">${escapeHtml(s.nombre)}</div>
                    <div style="font-size: 0.73rem; color: var(--text-muted);">${escapeHtml(s.descripcion || 'Sin descripción')}</div>
                </td>
                <td>
                    <span class="list-status-pill ${esPub ? 'ACTIVA' : 'DETENIDA'}">
                        ${esPub ? '● PUBLICADA' : '⏸ PAUSADA'}
                    </span>
                </td>
                <td>
                    <div style="display: flex; flex-wrap: wrap; gap: 4px;">
                        ${listasHtml}
                    </div>
                </td>
                <td class="mono-val">${s.total_pasos || 0}</td>
                <td class="mono-val">${s.leads_en_curso || 0}</td>
                <td class="mono-val">${s.leads_completados || 0}</td>
                <td>
                    <div style="display: flex; gap: 6px; align-items: center;">
                        <button class="btn-table-action" onclick="seleccionarYVerFlujo('${s.id}')" title="Ver árbol de decisión">
                            Ver Flujo
                        </button>
                        <button class="btn-toggle-publish ${esPub ? 'published' : 'paused'}" style="padding: 3px 8px; font-size: 0.72rem;" onclick="cambiarEstadoSecuencia('${s.id}', '${esPub ? 'PAUSADA' : 'PUBLICADA'}')">
                            ${esPub ? 'Pausar' : 'Publicar'}
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function seleccionarYVerFlujo(secId) {
    activeSequenceId = secId;
    const sel = document.getElementById('select-secuencia-activa');
    if (sel) sel.value = secId;
    switchSecuenciaSubView('flujo');
}

function renderFlowchart(sec) {
    const canvas = document.getElementById('flowchart-canvas');
    if (!canvas) return;

    const pasos = sec.pasos || [];
    if (pasos.length === 0) {
        canvas.innerHTML = `
            <div style="text-align: center; padding: 40px 20px; background: rgba(255,255,255,0.02); border: 1px dashed var(--border-default); border-radius: var(--radius-md); max-width: 400px; margin: 20px auto;">
                <div style="font-size: 0.95rem; font-weight: 500; color: var(--text-primary); margin-bottom: 6px;">Esta secuencia aún no tiene pasos</div>
                <div style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 16px;">Comienza agregando el primer paso para estructurar tu campaña multicanal.</div>
                <button class="btn-primary-action" onclick="abrirModalAgregarPaso('inicio')" style="margin: 0 auto;">
                    + Agregar Primer Paso
                </button>
            </div>
        `;
        return;
    }

    // Comprobar si hay paso de bifurcación condicional
    const pasoBifurcacion = pasos.find(p => p.tipo_accion === 'VERIFICAR_ESTADO' || p.condicion_rama === 'SI_ACEPTO' || p.condicion_rama === 'SI_NO_ACEPTO');

    let html = '';

    if (pasoBifurcacion) {
        // Modo bifurcado
        const ordenSplit = pasos.find(p => p.tipo_accion === 'VERIFICAR_ESTADO')?.orden || 5;
        const tronco = pasos.filter(p => (!p.padre_paso_id || p.condicion_rama === 'DEFAULT') && p.orden <= ordenSplit);
        const ramaSi = pasos.filter(p => p.condicion_rama === 'SI_ACEPTO' || (p.orden > ordenSplit && (p.id.includes('6a') || p.id.includes('7a') || p.id.includes('8a'))));
        const ramaNo = pasos.filter(p => p.condicion_rama === 'SI_NO_ACEPTO' || (p.orden > ordenSplit && (p.id.includes('6b') || p.id.includes('7b') || p.id.includes('8b'))));

        tronco.forEach((p, idx) => {
            html += renderStepCardHtml(p);
            if (idx < tronco.length - 1) {
                html += renderConnectorHtml(p.id);
            }
        });

        const ultPasoTronco = tronco[tronco.length - 1];

        html += `
            <div class="flow-branches-split-header">
                <div class="flow-connector" style="height: 18px;">
                    <div class="flow-connector-line"></div>
                    <span class="flow-connector-arrow">▼</span>
                </div>
                <div class="flow-split-horizontal-bar"></div>
            </div>

            <div class="flow-branches-container">
                <!-- Rama Verde: Si Aceptó Conexión -->
                <div class="flow-branch-column">
                    <div class="branch-pill-header yes">
                        <span>✓ Si Aceptó en LinkedIn (1er Grado)</span>
                    </div>
                    ${ramaSi.map((p, idx) => {
                        return renderStepCardHtml(p) + (idx < ramaSi.length - 1 ? renderConnectorHtml(p.id) : '');
                    }).join('')}
                    <div class="flow-add-step-end-card" onclick="abrirModalAgregarPaso('intermedio', '${ramaSi.length > 0 ? ramaSi[ramaSi.length - 1].id : ultPasoTronco?.id}')" title="Añadir paso al final de esta rama">
                        + Agregar Paso a Rama Si
                    </div>
                </div>

                <!-- Rama Naranja: Si NO Aceptó -->
                <div class="flow-branch-column">
                    <div class="branch-pill-header no">
                        <span>✗ Si NO Aceptó tras 48h (Sin respuesta)</span>
                    </div>
                    ${ramaNo.map((p, idx) => {
                        return renderStepCardHtml(p) + (idx < ramaNo.length - 1 ? renderConnectorHtml(p.id) : '');
                    }).join('')}
                    <div class="flow-add-step-end-card" onclick="abrirModalAgregarPaso('intermedio', '${ramaNo.length > 0 ? ramaNo[ramaNo.length - 1].id : ultPasoTronco?.id}')" title="Añadir paso al final de esta rama">
                        + Agregar Paso a Rama No
                    </div>
                </div>
            </div>
        `;
    } else {
        // Modo Lineal (secuencia simple sin bifurcación)
        pasos.forEach((p, idx) => {
            html += renderStepCardHtml(p);
            if (idx < pasos.length - 1) {
                html += renderConnectorHtml(p.id);
            }
        });

        html += `
            <div style="display: flex; justify-content: center; width: 100%;">
                <div class="flow-add-step-end-card" onclick="abrirModalAgregarPaso('final')" title="Añadir nuevo paso al final de la secuencia">
                    + Agregar Paso al Final
                </div>
            </div>
        `;
    }

    canvas.innerHTML = html;
}

function renderStepCardHtml(p) {
    const params = p.parametros || {};
    let badgeClass = 'linkedin';
    let badgeLabel = 'LinkedIn';
    let previewText = '';

    switch (p.tipo_accion) {
        case 'VISITAR_PERFIL':
            badgeClass = 'linkedin';
            badgeLabel = 'LinkedIn Visita';
            previewText = `Scroll y lectura humana: ${params.tiempo_lectura_min_seg || 6}s a ${params.tiempo_lectura_max_seg || 12}s`;
            break;
        case 'ESPERAR':
            badgeClass = 'delay';
            badgeLabel = 'Espera';
            previewText = `Pausa de ${params.horas_espera || 24} horas antes del siguiente paso`;
            break;
        case 'ENVIAR_INVITACION':
            badgeClass = 'linkedin';
            badgeLabel = 'LinkedIn Conectar';
            previewText = params.incluir_nota ? `Nota: "${params.plantilla_nota || ''}"` : 'Enviar sin nota (Directo)';
            break;
        case 'VERIFICAR_ESTADO':
            badgeClass = 'condition';
            badgeLabel = 'Bifurcación';
            previewText = 'Comprueba si aceptó invitación para bifurcar el flujo';
            break;
        case 'ENVIAR_MENSAJE_LINKEDIN':
            badgeClass = 'linkedin';
            badgeLabel = 'LinkedIn Mensaje';
            previewText = `Plantilla: "${params.plantilla_mensaje || ''}"`;
            break;
        case 'ENVIAR_CORREO_WORKSPACE':
            badgeClass = 'email';
            badgeLabel = 'Google Workspace';
            previewText = `Asunto: "${params.asunto || ''}" | Email institucional`;
            break;
        case 'RETIRAR_INVITACION':
            badgeClass = 'delay';
            badgeLabel = 'LinkedIn Retiro';
            previewText = 'Retira solicitud para proteger ratio de cuenta';
            break;
        default:
            badgeLabel = p.tipo_accion;
            previewText = '-';
    }

    const etiqueta = params.etiqueta || p.tipo_accion;
    const leadsCount = p.leads_en_paso || 0;
    const listos = p.leads_listos || 0;
    const enEspera = p.leads_en_espera || 0;
    const isNodeActive = leadsCount > 0;

    let readyStatusHtml = '';
    if (leadsCount > 0) {
        if (listos > 0) {
            readyStatusHtml = `<span class="flow-step-ready-status ready">⚡ ${listos} listos</span>`;
        } else {
            readyStatusHtml = `<span class="flow-step-ready-status">⏳ ${enEspera} en espera</span>`;
        }
    } else {
        readyStatusHtml = `<span class="flow-step-ready-status" style="opacity: 0.45;">0 en cola</span>`;
    }

    return `
        <div class="flow-step-wrapper">
            <div class="flow-step-card" onclick="abrirEditorPaso('${p.id}')" title="Clic para editar este paso">
                <div class="flow-step-header">
                    <span class="flow-step-badge ${badgeClass}">${badgeLabel}</span>
                    <span class="flow-step-order">Paso ${p.orden}</span>
                    <button class="btn-step-delete-card" onclick="event.stopPropagation(); confirmarEliminarPaso('${p.id}')" title="Eliminar este paso de la secuencia">&times;</button>
                </div>
                <div class="flow-step-title">${escapeHtml(etiqueta)}</div>
                <div class="flow-step-preview">${escapeHtml(previewText)}</div>
                <div class="flow-step-telemetry-row">
                    <span class="flow-step-leads-pill ${isNodeActive ? 'active' : ''}">
                        <span class="dot"></span>
                        ${leadsCount} ${leadsCount === 1 ? 'lead' : 'leads'}
                    </span>
                    ${readyStatusHtml}
                </div>
            </div>
        </div>
    `;
}

function renderConnectorHtml(padrePasoId = null) {
    return `
        <div class="flow-connector">
            <div class="flow-connector-line"></div>
            ${padrePasoId ? `<button class="flow-connector-add-btn" onclick="abrirModalAgregarPaso('intermedio', '${padrePasoId}')" title="Insertar paso intermedio aquí">+</button>` : ''}
            <span class="flow-connector-arrow">▼</span>
        </div>
    `;
}

async function cargarLeadsEnSecuencia() {
    if (!activeSequenceId) return;
    try {
        const res = await fetch(`/api/secuencias/${encodeURIComponent(activeSequenceId)}/leads`);
        if (!res.ok) return;
        const data = await res.json();
        const leads = data.leads || [];

        const totalEl = document.getElementById('sec-leads-total');
        if (totalEl) totalEl.textContent = leads.length;

        const tableBadge = document.getElementById('sec-table-badge');
        if (tableBadge) tableBadge.textContent = `${leads.length} inscritos`;

        const enCurso = leads.filter(l => l.estado === 'EN_CURSO').length;
        const enCursoEl = document.getElementById('sec-leads-en-curso');
        if (enCursoEl) enCursoEl.textContent = `${enCurso} en curso`;

        const comp = leads.filter(l => l.estado === 'COMPLETADO').length;
        const compEl = document.getElementById('sec-leads-completados');
        if (compEl) compEl.textContent = comp;

        // Próximo lead listo
        const proximo = leads.find(l => l.estado === 'EN_CURSO');
        const proximoNombre = document.getElementById('sec-proximo-lead-nombre');
        const proximaHora = document.getElementById('sec-proxima-hora');
        if (proximo && proximoNombre) {
            proximoNombre.textContent = proximo.nombre;
            if (proximaHora) proximaHora.textContent = `Próximo: ${proximo.paso_accion || 'Acción'} (${formatDate(proximo.proxima_ejecucion_at)})`;
        } else if (proximoNombre) {
            proximoNombre.textContent = 'Ninguno en cola';
            if (proximaHora) proximaHora.textContent = 'Todos al día';
        }

        const tbody = document.getElementById('sec-leads-tbody');
        if (!tbody) return;

        if (leads.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="loading-cell">No hay prospectos inscritos en esta secuencia aún. Haz clic en "Asignar Leads en Cola".</td></tr>`;
            return;
        }

        tbody.innerHTML = leads.map(l => {
            let statusPill = `<span class="status-badge badge-visitado">En Curso</span>`;
            if (l.estado === 'COMPLETADO') statusPill = `<span class="status-badge badge-conectado">Completado</span>`;
            else if (l.estado === 'PAUSADO') statusPill = `<span class="status-badge badge-enviada">Pausado</span>`;

            return `
                <tr>
                    <td>
                        <span style="font-weight: 500; color: #FFF;">${escapeHtml(l.nombre)}</span>
                    </td>
                    <td>${escapeHtml(l.institucion_actual || '-')}</td>
                    <td>
                        ${l.email ? `<span class="mono-val" style="color:var(--text-secondary);">${escapeHtml(l.email)}</span>` : '<span class="contact-empty">—</span>'}
                    </td>
                    <td>
                        <span class="flow-step-badge ${l.paso_accion === 'ENVIAR_CORREO_WORKSPACE' ? 'email' : 'linkedin'}">
                            ${escapeHtml(l.paso_etiqueta || l.paso_accion || '-')}
                        </span>
                    </td>
                    <td class="mono-val" style="font-size: 0.76rem;">
                        ${l.proxima_ejecucion_at ? formatDate(l.proxima_ejecucion_at) : '-'}
                    </td>
                    <td>${statusPill}</td>
                </tr>
            `;
        }).join('');
    } catch (e) {
        console.error('Error cargando leads en secuencia:', e);
    }
}

async function asignarTodosLosLeadsASecuencia() {
    if (!activeSequenceId) return;
    showToast('Asignando leads en cola a la secuencia activa...');
    try {
        const res = await fetch(`/api/secuencias/${encodeURIComponent(activeSequenceId)}/asignar-leads`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lead_ids: [] }) // Vacío asigna todos los en EXTRAIDO
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast(`¡${data.asignados} leads inscritos con éxito en el paso inicial de la secuencia!`);
            cargarLeadsEnSecuencia();
            cargarSecuencias();
            if (activeSequenceId) cargarSecuenciaDetalle(activeSequenceId);
        } else {
            showToast('Error: ' + (data.mensaje || 'No se pudieron asignar'));
        }
    } catch (e) {
        showToast('Error de conexión al asignar leads');
    }
}

async function ejecutarSiguientePasoSecuencia() {
    const btn = document.getElementById('btn-ejecutar-siguiente-paso');
    const btnText = document.getElementById('btn-ejecutar-paso-text');
    if (btn) btn.disabled = true;
    if (btnText) btnText.textContent = 'Procesando paso...';

    showToast('Evaluando seguridad y ejecutando paso de la secuencia...');
    try {
        const url = activeSequenceId 
            ? `/api/secuencias/ejecutar-siguiente?secuencia_id=${encodeURIComponent(activeSequenceId)}`
            : `/api/secuencias/ejecutar-siguiente`;

        const res = await fetch(url, { method: 'POST' });
        const data = await res.json();

        if (data.status === 'ok') {
            const lead = data.lead || {};
            const paso = data.paso_ejecutado || {};
            showToast(`¡Paso ejecutado! ${lead.nombre}: ${paso.accion} - ${paso.detalle}`);
            // Refrescar vistas
            await cargarLeadsEnSecuencia();
            if (activeSequenceId) await cargarSecuenciaDetalle(activeSequenceId);
            cargarDatos();
        } else if (data.status === 'bloqueado_por_seguridad') {
            showToast(`Seguridad: ${data.motivo}`);
        } else if (data.status === 'idle') {
            showToast(data.mensaje);
        } else {
            showToast(`Error: ${data.mensaje || data.detail || 'Fallo desconocido'}`);
        }
    } catch (e) {
        console.error(e);
        showToast('Error de conexión al ejecutar el paso');
    } finally {
        if (btn) btn.disabled = false;
        if (activeSequenceData && activeSequenceData.proximo_lead) {
            const pl = activeSequenceData.proximo_lead;
            if (btnText) {
                if (pl.listo_ahora) {
                    btnText.textContent = `⚡ Ejecutar: ${pl.nombre.split(' ')[0]} ➔ Paso ${pl.paso_orden}`;
                } else {
                    btnText.textContent = `⏳ En espera: ${pl.nombre.split(' ')[0]} (Paso ${pl.paso_orden})`;
                }
            }
        } else {
            if (btnText) btnText.textContent = 'Ejecutar Siguiente Paso Ahora';
        }
    }
}

// ==========================================================================
// EDITOR DE PASOS DE LA SECUENCIA (MODAL)
// ==========================================================================
function abrirEditorPaso(pasoId) {
    if (!activeSequenceData || !activeSequenceData.pasos) return;
    const paso = activeSequenceData.pasos.find(p => p.id === pasoId);
    if (!paso) return;

    currentEditingStep = paso;
    const params = paso.parametros || {};

    const titleEl = document.getElementById('step-modal-title');
    const subEl = document.getElementById('step-modal-subtitle');
    const bodyEl = document.getElementById('step-modal-body');

    if (titleEl) titleEl.textContent = `Editar Paso: ${paso.tipo_accion}`;
    if (subEl) subEl.textContent = `Paso orden ${paso.orden} | ID: ${paso.id}`;

    let formHtml = `
        <div class="step-form-group">
            <label>Etiqueta / Nombre Visible del Paso</label>
            <input type="text" id="edit-step-etiqueta" value="${escapeHtml(params.etiqueta || paso.tipo_accion)}">
        </div>
    `;

    if (paso.tipo_accion === 'ESPERAR') {
        formHtml += `
            <div class="step-form-group">
                <label>Horas de Espera (Pausa antes de la siguiente acción)</label>
                <input type="number" id="edit-step-horas" value="${params.horas_espera || 24}" min="0.5" step="0.5">
            </div>
        `;
    } else if (paso.tipo_accion === 'VISITAR_PERFIL') {
        formHtml += `
            <div class="step-form-group">
                <label>Tiempo Mínimo de Lectura y Scroll (segundos)</label>
                <input type="number" id="edit-step-tmin" value="${params.tiempo_lectura_min_seg || 6}" min="3">
            </div>
            <div class="step-form-group">
                <label>Tiempo Máximo de Lectura (segundos)</label>
                <input type="number" id="edit-step-tmax" value="${params.tiempo_lectura_max_seg || 12}" min="6">
            </div>
        `;
    } else if (paso.tipo_accion === 'ENVIAR_INVITACION') {
        formHtml += `
            <div class="step-form-group">
                <label>¿Incluir Nota Personalizada de Invitación?</label>
                <select id="edit-step-incluir-nota">
                    <option value="true" ${params.incluir_nota ? 'selected' : ''}>Sí, incluir nota personalizada</option>
                    <option value="false" ${!params.incluir_nota ? 'selected' : ''}>No, enviar invitación directa sin nota</option>
                </select>
            </div>
            <div class="step-form-group">
                <label>Plantilla de Nota de Invitación (Soporta Spintax)</label>
                <textarea id="edit-step-nota" placeholder="Hola {nombre}, un gusto saludarte.">${escapeHtml(params.plantilla_nota || '')}</textarea>
                <div class="variables-hint-bar">
                    <span>Variables disponibles:</span>
                    <span class="var-tag">{nombre}</span>
                    <span class="var-tag">{colegio}</span>
                    <span class="var-tag">{cargo}</span>
                </div>
            </div>
        `;
    } else if (paso.tipo_accion === 'ENVIAR_MENSAJE_LINKEDIN') {
        formHtml += `
            <div class="step-form-group">
                <label>Asunto o Propósito del Mensaje</label>
                <input type="text" id="edit-step-asunto" value="${escapeHtml(params.asunto || 'Mensaje de Seguimiento')}">
            </div>
            <div class="step-form-group">
                <label>Cuerpo del Mensaje de LinkedIn (Soporta Spintax)</label>
                <textarea id="edit-step-mensaje" rows="4">${escapeHtml(params.plantilla_mensaje || '')}</textarea>
                <div class="variables-hint-bar">
                    <span>Variables disponibles:</span>
                    <span class="var-tag">{nombre}</span>
                    <span class="var-tag">{colegio}</span>
                    <span class="var-tag">{cargo}</span>
                </div>
            </div>
        `;
    } else if (paso.tipo_accion === 'ENVIAR_CORREO_WORKSPACE') {
        formHtml += `
            <div class="step-form-group">
                <label>Asunto del Correo (Google Workspace)</label>
                <input type="text" id="edit-step-email-asunto" value="${escapeHtml(params.asunto || 'Consulta sobre gestión escolar en {colegio}')}">
            </div>
            <div class="step-form-group">
                <label>Cuerpo del Correo Formal (Soporta Spintax)</label>
                <textarea id="edit-step-email-cuerpo" rows="6">${escapeHtml(params.cuerpo_email || '')}</textarea>
                <div class="variables-hint-bar">
                    <span>Variables disponibles:</span>
                    <span class="var-tag">{nombre}</span>
                    <span class="var-tag">{colegio}</span>
                    <span class="var-tag">{cargo}</span>
                </div>
            </div>
        `;
    }

    if (bodyEl) bodyEl.innerHTML = formHtml;
    document.getElementById('step-modal-backdrop').classList.add('open');
}

function cerrarStepModal() {
    document.getElementById('step-modal-backdrop').classList.remove('open');
    currentEditingStep = null;
}

async function guardarEdicionPaso() {
    if (!currentEditingStep || !activeSequenceData) return;
    const paso = currentEditingStep;
    const params = paso.parametros || {};

    const etiquetaInput = document.getElementById('edit-step-etiqueta');
    if (etiquetaInput) params.etiqueta = etiquetaInput.value.trim();

    if (paso.tipo_accion === 'ESPERAR') {
        const hInput = document.getElementById('edit-step-horas');
        if (hInput) params.horas_espera = parseFloat(hInput.value) || 24;
    } else if (paso.tipo_accion === 'VISITAR_PERFIL') {
        const tminInput = document.getElementById('edit-step-tmin');
        const tmaxInput = document.getElementById('edit-step-tmax');
        if (tminInput) params.tiempo_lectura_min_seg = parseInt(tminInput.value, 10) || 6;
        if (tmaxInput) params.tiempo_lectura_max_seg = parseInt(tmaxInput.value, 10) || 12;
    } else if (paso.tipo_accion === 'ENVIAR_INVITACION') {
        const notaSel = document.getElementById('edit-step-incluir-nota');
        const notaTxt = document.getElementById('edit-step-nota');
        if (notaSel) params.incluir_nota = notaSel.value === 'true';
        if (notaTxt) params.plantilla_nota = notaTxt.value.trim();
    } else if (paso.tipo_accion === 'ENVIAR_MENSAJE_LINKEDIN') {
        const asInput = document.getElementById('edit-step-asunto');
        const msgTxt = document.getElementById('edit-step-mensaje');
        if (asInput) params.asunto = asInput.value.trim();
        if (msgTxt) params.plantilla_mensaje = msgTxt.value.trim();
    } else if (paso.tipo_accion === 'ENVIAR_CORREO_WORKSPACE') {
        const asInput = document.getElementById('edit-step-email-asunto');
        const bodyTxt = document.getElementById('edit-step-email-cuerpo');
        if (asInput) params.asunto = asInput.value.trim();
        if (bodyTxt) params.cuerpo_email = bodyTxt.value.trim();
    }

    paso.parametros = params;
    paso.parametros_json = JSON.stringify(params);

    // Guardar pasos actualizados en el servidor
    try {
        const res = await fetch(`/api/secuencias/${encodeURIComponent(activeSequenceId)}/pasos`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pasos: activeSequenceData.pasos })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast('Paso actualizado y guardado con éxito.');
            cerrarStepModal();
            renderFlowchart(activeSequenceData);
        } else {
            showToast('Error al guardar cambios en el paso.');
        }
    } catch (e) {
        showToast('Error de conexión al guardar paso.');
    }
}

// ==========================================================================
// MODAL: CREAR NUEVA SECUENCIA
// ==========================================================================
function abrirModalNuevaSecuencia() {
    const inputNombre = document.getElementById('input-nueva-sec-nombre');
    const inputDesc = document.getElementById('input-nueva-sec-desc');
    const selectPlantilla = document.getElementById('select-nueva-sec-plantilla');
    const selectEstado = document.getElementById('select-nueva-sec-estado');

    if (inputNombre) inputNombre.value = '';
    if (inputDesc) inputDesc.value = '';
    if (selectPlantilla) selectPlantilla.value = 'multicanal';
    if (selectEstado) selectEstado.value = 'true';

    const backdrop = document.getElementById('modal-nueva-secuencia-backdrop');
    if (backdrop) backdrop.classList.add('open');
}

function cerrarModalNuevaSecuencia() {
    const backdrop = document.getElementById('modal-nueva-secuencia-backdrop');
    if (backdrop) backdrop.classList.remove('open');
}

async function guardarNuevaSecuencia() {
    const inputNombre = document.getElementById('input-nueva-sec-nombre');
    const inputDesc = document.getElementById('input-nueva-sec-desc');
    const selectPlantilla = document.getElementById('select-nueva-sec-plantilla');
    const selectEstado = document.getElementById('select-nueva-sec-estado');

    const nombre = inputNombre ? inputNombre.value.trim() : '';
    if (!nombre) {
        showToast('Debes ingresar un nombre para la secuencia.');
        return;
    }

    const payload = {
        nombre: nombre,
        descripcion: inputDesc ? inputDesc.value.trim() : '',
        plantilla: selectPlantilla ? selectPlantilla.value : 'multicanal',
        activa: selectEstado ? selectEstado.value === 'true' : true
    };

    try {
        const res = await fetch('/api/secuencias', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.id) {
            showToast(`¡Secuencia "${data.nombre}" creada con éxito!`);
            cerrarModalNuevaSecuencia();
            activeSequenceId = data.id;
            await cargarSecuencias();
            await cargarSecuenciaDetalle(data.id);
            switchSecuenciaSubView('flujo');
        } else {
            showToast('Error al crear secuencia: ' + (data.detail || 'Fallo inesperado'));
        }
    } catch (e) {
        console.error(e);
        showToast('Error de conexión al crear secuencia');
    }
}

// ==========================================================================
// MODAL: INSERTAR NUEVO PASO (INICIAL, INTERMEDIO O FINAL)
// ==========================================================================
let pasoNuevoRefId = null;

function abrirModalAgregarPaso(posicion = 'final', refPasoId = null) {
    if (!activeSequenceId) {
        showToast('Selecciona primero una secuencia activa.');
        return;
    }

    pasoNuevoRefId = refPasoId;
    const selPos = document.getElementById('select-nuevo-paso-posicion');
    if (selPos) selPos.value = posicion;

    // Rellenar selector de paso de referencia
    const selRef = document.getElementById('select-nuevo-paso-referencia');
    if (selRef && activeSequenceData && activeSequenceData.pasos) {
        selRef.innerHTML = activeSequenceData.pasos.map(p => {
            const etiqueta = (p.parametros && p.parametros.etiqueta) ? p.parametros.etiqueta : p.tipo_accion;
            return `<option value="${p.id}" ${p.id === refPasoId ? 'selected' : ''}>Paso ${p.orden}: ${escapeHtml(etiqueta)}</option>`;
        }).join('');
    }

    actualizarVisibilidadPasoReferencia();
    renderCamposDinamicosNuevoPaso();

    const backdrop = document.getElementById('modal-agregar-paso-backdrop');
    if (backdrop) backdrop.classList.add('open');
}

function cerrarModalAgregarPaso() {
    const backdrop = document.getElementById('modal-agregar-paso-backdrop');
    if (backdrop) backdrop.classList.remove('open');
    pasoNuevoRefId = null;
}

function actualizarVisibilidadPasoReferencia() {
    const selPos = document.getElementById('select-nuevo-paso-posicion');
    const grpRef = document.getElementById('group-nuevo-paso-referencia');
    if (selPos && grpRef) {
        grpRef.style.display = selPos.value === 'intermedio' ? 'flex' : 'none';
    }
}

function renderCamposDinamicosNuevoPaso() {
    const tipo = document.getElementById('select-nuevo-paso-tipo')?.value || 'ESPERAR';
    const container = document.getElementById('nuevo-paso-parametros-container');
    const etiquetaInput = document.getElementById('input-nuevo-paso-etiqueta');
    if (!container) return;

    let html = '';
    let defaultEtiqueta = '';

    switch (tipo) {
        case 'VISITAR_PERFIL':
            defaultEtiqueta = 'Visitar Perfil LinkedIn (Scroll y Lectura Humana)';
            html = `
                <div class="step-form-group">
                    <label>Tiempo Mínimo de Scroll (segundos)</label>
                    <input type="number" id="input-nuevo-tmin" value="6" min="3">
                </div>
                <div class="step-form-group">
                    <label>Tiempo Máximo de Scroll (segundos)</label>
                    <input type="number" id="input-nuevo-tmax" value="12" min="6">
                </div>
            `;
            break;
        case 'ESPERAR':
            defaultEtiqueta = 'Pausa de 24 Horas';
            html = `
                <div class="step-form-group">
                    <label>Horas de Espera antes del siguiente paso</label>
                    <input type="number" id="input-nuevo-horas" value="24" min="0.5" step="0.5">
                </div>
            `;
            break;
        case 'ENVIAR_INVITACION':
            defaultEtiqueta = 'Enviar Invitación a Conectar en LinkedIn';
            html = `
                <div class="step-form-group">
                    <label>¿Incluir Nota Personalizada?</label>
                    <select id="input-nuevo-invitacion-nota-flag">
                        <option value="true" selected>Sí, incluir nota personalizada</option>
                        <option value="false">No, invitación directa sin nota</option>
                    </select>
                </div>
                <div class="step-form-group">
                    <label>Plantilla de Nota (Soporta Spintax)</label>
                    <textarea id="input-nuevo-invitacion-nota" placeholder="Hola {nombre}, un gusto saludarte. Veo tu gestión en {colegio}...">Hola {nombre}, un gusto saludarte. Veo tu gestión en {colegio}. Me encantaría conectar por aquí.</textarea>
                    <div class="variables-hint-bar">
                        <span>Variables: {nombre}, {colegio}, {cargo}</span>
                    </div>
                </div>
            `;
            break;
        case 'ENVIAR_MENSAJE_LINKEDIN':
            defaultEtiqueta = 'Mensaje de Valor en LinkedIn';
            html = `
                <div class="step-form-group">
                    <label>Asunto o Propósito</label>
                    <input type="text" id="input-nuevo-msg-asunto" value="Mensaje de Seguimiento">
                </div>
                <div class="step-form-group">
                    <label>Cuerpo del Mensaje (Soporta Spintax)</label>
                    <textarea id="input-nuevo-msg-cuerpo" rows="4">Hola {nombre}, gracias por conectar. Me gustaría compartir contigo algunos avances sobre gestión en {colegio}.</textarea>
                    <div class="variables-hint-bar">
                        <span>Variables: {nombre}, {colegio}, {cargo}</span>
                    </div>
                </div>
            `;
            break;
        case 'ENVIAR_CORREO_WORKSPACE':
            defaultEtiqueta = 'Correo Frío Google Workspace';
            html = `
                <div class="step-form-group">
                    <label>Asunto del Correo (Soporta Spintax)</label>
                    <input type="text" id="input-nuevo-email-asunto" value="Contacto formal: Gestión directiva en {colegio}">
                </div>
                <div class="step-form-group">
                    <label>Cuerpo del Correo Formal</label>
                    <textarea id="input-nuevo-email-cuerpo" rows="6">Estimado/a {nombre},\n\nLe escribo en relación a su gestión escolar en {colegio}...</textarea>
                    <div class="variables-hint-bar">
                        <span>Variables: {nombre}, {colegio}, {cargo}</span>
                    </div>
                </div>
            `;
            break;
        case 'VERIFICAR_ESTADO':
            defaultEtiqueta = 'Bifurcación: ¿Aceptó en LinkedIn?';
            html = `
                <div class="step-form-group">
                    <label>Descripción de la condición</label>
                    <input type="text" id="input-nuevo-verif-desc" value="Comprobar si el contacto aceptó solicitud de conexión">
                </div>
            `;
            break;
        case 'RETIRAR_INVITACION':
            defaultEtiqueta = 'Retirar Solicitud de Conexión Pendiente';
            html = `
                <div class="step-form-group">
                    <label>Motivo de Retiro</label>
                    <input type="text" id="input-nuevo-retiro-motivo" value="Retiro automático para proteger ratio de cuenta">
                </div>
            `;
            break;
    }

    container.innerHTML = html;
    if (etiquetaInput && (!etiquetaInput.value || etiquetaInput.value.startsWith('Paso ') || etiquetaInput.value.includes('LinkedIn') || etiquetaInput.value.includes('Pausa') || etiquetaInput.value.includes('Correo') || etiquetaInput.value.includes('Mensaje') || etiquetaInput.value.includes('Bifurcación'))) {
        etiquetaInput.value = defaultEtiqueta;
    }
}

async function guardarNuevoPaso() {
    if (!activeSequenceId) return;

    const selPos = document.getElementById('select-nuevo-paso-posicion');
    const selRef = document.getElementById('select-nuevo-paso-referencia');
    const selTipo = document.getElementById('select-nuevo-paso-tipo');
    const inputEtiqueta = document.getElementById('input-nuevo-paso-etiqueta');

    const posicion = selPos ? selPos.value : 'final';
    const refId = (posicion === 'intermedio' && selRef) ? selRef.value : (pasoNuevoRefId || null);
    const tipo = selTipo ? selTipo.value : 'ESPERAR';
    const etiqueta = inputEtiqueta ? inputEtiqueta.value.trim() : `Paso ${tipo}`;

    if (!etiqueta) {
        showToast('Debes ingresar una etiqueta para el paso.');
        return;
    }

    const parametros = { etiqueta: etiqueta };

    if (tipo === 'VISITAR_PERFIL') {
        parametros.tiempo_lectura_min_seg = parseInt(document.getElementById('input-nuevo-tmin')?.value, 10) || 6;
        parametros.tiempo_lectura_max_seg = parseInt(document.getElementById('input-nuevo-tmax')?.value, 10) || 12;
    } else if (tipo === 'ESPERAR') {
        parametros.horas_espera = parseFloat(document.getElementById('input-nuevo-horas')?.value) || 24;
    } else if (tipo === 'ENVIAR_INVITACION') {
        parametros.incluir_nota = document.getElementById('input-nuevo-invitacion-nota-flag')?.value === 'true';
        parametros.plantilla_nota = document.getElementById('input-nuevo-invitacion-nota')?.value || '';
    } else if (tipo === 'ENVIAR_MENSAJE_LINKEDIN') {
        parametros.asunto = document.getElementById('input-nuevo-msg-asunto')?.value || 'Mensaje';
        parametros.plantilla_mensaje = document.getElementById('input-nuevo-msg-cuerpo')?.value || '';
    } else if (tipo === 'ENVIAR_CORREO_WORKSPACE') {
        parametros.asunto = document.getElementById('input-nuevo-email-asunto')?.value || 'Correo';
        parametros.cuerpo_email = document.getElementById('input-nuevo-email-cuerpo')?.value || '';
    } else if (tipo === 'VERIFICAR_ESTADO') {
        parametros.descripcion = document.getElementById('input-nuevo-verif-desc')?.value || '';
    } else if (tipo === 'RETIRAR_INVITACION') {
        parametros.motivo = document.getElementById('input-nuevo-retiro-motivo')?.value || '';
    }

    const payload = {
        posicion: posicion,
        paso_referencia_id: refId,
        tipo_accion: tipo,
        etiqueta: etiqueta,
        parametros: parametros
    };

    try {
        const res = await fetch(`/api/secuencias/${encodeURIComponent(activeSequenceId)}/pasos/agregar`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast(`¡Paso "${etiqueta}" insertado correctamente!`);
            cerrarModalAgregarPaso();
            await cargarSecuenciaDetalle(activeSequenceId);
            await cargarLeadsEnSecuencia();
        } else {
            showToast('Error al agregar paso: ' + (data.detail || 'Fallo'));
        }
    } catch (e) {
        console.error(e);
        showToast('Error de conexión al agregar paso');
    }
}

// ==========================================================================
// ELIMINAR PASOS DE LA SECUENCIA
// ==========================================================================
async function confirmarEliminarPaso(pasoId) {
    if (!activeSequenceId || !activeSequenceData) return;
    const paso = activeSequenceData.pasos?.find(p => p.id === pasoId);
    const nombre = paso?.parametros?.etiqueta || paso?.tipo_accion || 'este paso';

    if (!confirm(`¿Estás seguro de eliminar "${nombre}" de la secuencia?\nLos prospectos que estén en esta etapa avanzarán automáticamente a la siguiente.`)) {
        return;
    }

    try {
        const res = await fetch(`/api/secuencias/${encodeURIComponent(activeSequenceId)}/pasos/${encodeURIComponent(pasoId)}`, {
            method: 'DELETE'
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast(`Paso "${nombre}" eliminado de la secuencia.`);
            await cargarSecuenciaDetalle(activeSequenceId);
            await cargarLeadsEnSecuencia();
        } else {
            showToast('Error al eliminar paso: ' + (data.detail || 'Fallo'));
        }
    } catch (e) {
        console.error(e);
        showToast('Error de conexión al eliminar paso');
    }
}

function confirmarEliminarPasoDesdeModal() {
    if (!currentEditingStep) return;
    const pId = currentEditingStep.id;
    cerrarStepModal();
    confirmarEliminarPaso(pId);
}

// ==========================================================================
// GESTOR DE LISTAS DE LEADS (AUDIENCIAS Y SEGMENTACIÓN)
// ==========================================================================
let allLoadedListas = [];
let currentListFilter = '';
let currentListSearch = '';

async function cargarListas() {
    try {
        const res = await fetch('/api/listas');
        if (!res.ok) return;
        const data = await res.json();
        const listas = data.listas || [];
        allLoadedListas = listas;

        // Badge navbar
        const badge = document.getElementById('badge-listas-count');
        if (badge) badge.textContent = listas.length;

        // Actualizar selector de lista destino en el extractor
        const selectExtractor = document.getElementById('select-extractor-target-list');
        if (selectExtractor) {
            const currentVal = selectExtractor.value;
            selectExtractor.innerHTML = `
                <option value="">(Sin lista específica / General)</option>
                ${listas.map(l => `
                    <option value="${l.id}" ${l.id === currentVal ? 'selected' : ''}>
                        ${escapeHtml(l.nombre)} (${l.total_leads || 0} leads)
                    </option>
                `).join('')}
            `;
            // Si no había selección y hay al menos una lista, seleccionar la primera por defecto
            if (!currentVal && listas.length > 0) {
                selectExtractor.value = listas[0].id;
            }
        }

        // Actualizar KPIs de listas
        actualizarKPIsListas(listas);

        // Renderizar cuadrícula de tarjetas de listas
        renderListas(listas);
    } catch (e) {
        console.warn('Error cargando listas de leads:', e);
    }
}

function actualizarKPIsListas(listas) {
    const totalEl = document.getElementById('metric-listas-total');
    const activasEl = document.getElementById('metric-listas-activas');
    const leadsEl = document.getElementById('metric-listas-leads');
    const vinculosEl = document.getElementById('metric-listas-vinculos');

    if (totalEl) totalEl.textContent = listas.length;

    let activas = 0;
    let totalLeads = 0;
    let vinculos = 0;

    listas.forEach(l => {
        const est = (l.estado || 'ACTIVA').toUpperCase();
        if (est === 'ACTIVA' || est === 'EXTRAYENDO') activas++;
        totalLeads += (l.total_leads || 0);
        const seqs = l.secuencias_conectadas || l.secuencias_vinculadas || [];
        vinculos += seqs.length;
    });

    if (activasEl) activasEl.textContent = activas;
    if (leadsEl) leadsEl.textContent = totalLeads;
    if (vinculosEl) vinculosEl.textContent = vinculos;
}

function filtrarListasUI(btn, estado) {
    currentListFilter = estado;
    const tabs = document.querySelectorAll('#listas-filter-tabs .filter-tab');
    tabs.forEach(t => t.classList.remove('active'));
    if (btn) btn.classList.add('active');
    renderListas();
}

function handleSearchListas() {
    const input = document.getElementById('input-buscar-listas');
    currentListSearch = input ? input.value.trim().toLowerCase() : '';
    renderListas();
}

function renderListas(listas = null) {
    const container = document.getElementById('listas-grid');
    if (!container) return;

    const list = listas || allLoadedListas;
    let filtradas = list;

    if (currentListFilter) {
        filtradas = filtradas.filter(l => {
            const st = (l.estado || 'ACTIVA').toUpperCase();
            return st === currentListFilter;
        });
    }

    if (currentListSearch) {
        filtradas = filtradas.filter(l => {
            const nom = (l.nombre || '').toLowerCase();
            const desc = (l.descripcion || '').toLowerCase();
            const term = (l.termino_busqueda || '').toLowerCase();
            return nom.includes(currentListSearch) || desc.includes(currentListSearch) || term.includes(currentListSearch);
        });
    }

    if (filtradas.length === 0) {
        container.innerHTML = `
            <div style="grid-column: 1 / -1; padding: 40px; text-align: center; background: var(--bg-surface); border: 1px dashed var(--border-default); border-radius: var(--radius-lg);">
                <div style="font-size: 2rem; margin-bottom: 10px;">📋</div>
                <h3 style="font-size: 1rem; color: var(--text-primary); margin-bottom: 6px;">No se encontraron listas con los filtros seleccionados</h3>
                <p style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 16px;">Crea una nueva lista de prospectos para comenzar a organizar tus campañas escolares.</p>
                <button class="btn-primary-action" onclick="abrirModalNuevaLista()">
                    + Crear Nueva Lista
                </button>
            </div>
        `;
        return;
    }

    container.innerHTML = filtradas.map(l => {
        const estado = (l.estado || 'ACTIVA').toUpperCase();
        const seqs = l.secuencias_conectadas || l.secuencias_vinculadas || [];

        const seqChipsHtml = seqs.length > 0
            ? seqs.map(s => `
                <div class="sec-mini-chip ${s.auto_ingresar_nuevos ? 'realtime-on' : ''}">
                    ${s.auto_ingresar_nuevos ? '<span class="chip-rt-dot" title="Flujo en tiempo real activo"></span>' : ''}
                    <span>${escapeHtml(s.nombre)}</span>
                    <span class="chip-unlink-btn" onclick="desconectarListaDeSecuencia('${l.id}', '${s.id}')" title="Desconectar esta secuencia">&times;</span>
                </div>
            `).join('')
            : '<span style="color: var(--text-muted); font-size: 0.72rem;">Sin secuencias conectadas</span>';

        return `
            <div class="list-card" id="card-lista-${l.id}">
                <div class="list-card-header">
                    <div class="list-card-title-group">
                        <div class="list-card-title">${escapeHtml(l.nombre)}</div>
                        ${l.descripcion ? `<div class="list-card-desc">${escapeHtml(l.descripcion)}</div>` : ''}
                    </div>
                    <span class="list-status-pill ${estado}">${estado}</span>
                </div>

                ${l.termino_busqueda ? `
                    <div class="list-card-query-box">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="11" cy="11" r="8"></circle>
                            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                        </svg>
                        <span class="list-card-query-text" title="Término asociado: ${escapeHtml(l.termino_busqueda)}">
                            ${escapeHtml(l.termino_busqueda)}
                        </span>
                    </div>
                ` : ''}

                <div class="list-card-stats-grid">
                    <div class="list-stat-item">
                        <span class="list-stat-val">${l.total_leads || 0}</span>
                        <span class="list-stat-lbl">Total</span>
                    </div>
                    <div class="list-stat-item">
                        <span class="list-stat-val" style="color: var(--text-primary);">${l.leads_en_cola || 0}</span>
                        <span class="list-stat-lbl">En Cola</span>
                    </div>
                    <div class="list-stat-item">
                        <span class="list-stat-val" style="color: var(--status-amber);">${l.leads_contactados || 0}</span>
                        <span class="list-stat-lbl">Invitados</span>
                    </div>
                    <div class="list-stat-item">
                        <span class="list-stat-val" style="color: var(--status-emerald);">${l.leads_conectados || 0}</span>
                        <span class="list-stat-lbl">Conectados</span>
                    </div>
                </div>

                <div class="list-card-sequences-section">
                    <div class="list-sec-title-row">
                        <span>Secuencias Conectadas (${seqs.length})</span>
                        <button class="btn-icon-subtle" onclick="abrirModalConectarLista('${l.id}')" title="Vincular a otra secuencia" style="padding: 2px 6px; font-size: 0.7rem;">
                            + Vincular
                        </button>
                    </div>
                    <div class="list-sec-chips">
                        ${seqChipsHtml}
                    </div>
                </div>

                <div class="list-card-footer">
                    <button class="btn-table-action" onclick="verLeadsDeLista('${l.id}', '${escapeHtml(l.nombre)}')" title="Ver prospectos de esta lista">
                        Ver Leads (${l.total_leads || 0})
                    </button>
                    <div class="list-card-footer-btns">
                        ${estado === 'ACTIVA' || estado === 'EXTRAYENDO' ? `
                            <button class="btn-icon-subtle" onclick="cambiarEstadoLista('${l.id}', 'DETENIDA')" title="Pausar / Detener lista">
                                ⏸ Pausar
                            </button>
                        ` : `
                            <button class="btn-icon-subtle" onclick="cambiarEstadoLista('${l.id}', 'ACTIVA')" title="Activar lista">
                                ▶ Activar
                            </button>
                        `}
                        <button class="btn-icon-subtle" onclick="eliminarLista('${l.id}')" title="Eliminar lista" style="color: var(--status-rose);">
                            🗑️
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

async function verLeadsDeLista(listaId, listaNombre) {
    try {
        const res = await fetch(`/api/listas/${encodeURIComponent(listaId)}`);
        if (!res.ok) throw new Error('No se pudo cargar la lista');
        const data = await res.json();
        
        switchMainView('prospectos', false);
        const input = document.getElementById('search-input');
        if (input) input.value = '';
        currentSearch = '';

        currentLeads = data.leads || [];
        renderTabla(currentLeads);

        const badge = document.getElementById('total-badge');
        if (badge) {
            badge.innerHTML = `Lista: <strong>${escapeHtml(data.nombre)}</strong> (${currentLeads.length}) <a href="javascript:void(0)" onclick="cargarProspectos(); document.getElementById('total-badge').textContent = currentLeads.length + ' registrados';" style="color: var(--status-blue); margin-left: 6px; text-decoration: underline;">[Ver todos]</a>`;
        }

        showToast(`Mostrando ${currentLeads.length} leads de "${data.nombre}"`);
    } catch (e) {
        console.error(e);
        showToast('Error al cargar leads de la lista');
    }
}

// Modales de Lista
function abrirModalNuevaLista() {
    const backdrop = document.getElementById('modal-nueva-lista-backdrop');
    if (backdrop) backdrop.classList.add('active');
}

function cerrarModalNuevaLista() {
    const backdrop = document.getElementById('modal-nueva-lista-backdrop');
    if (backdrop) backdrop.classList.remove('active');
}

async function guardarNuevaLista() {
    const nombreInput = document.getElementById('input-nueva-lista-nombre');
    const terminoInput = document.getElementById('input-nueva-lista-termino');
    const descInput = document.getElementById('input-nueva-lista-descripcion');
    const estadoSelect = document.getElementById('select-nueva-lista-estado');
    const checkConectar = document.getElementById('check-conectar-secuencia-inmediata');

    const nombre = nombreInput ? nombreInput.value.trim() : '';
    const termino = terminoInput ? terminoInput.value.trim() : '';
    const desc = descInput ? descInput.value.trim() : '';
    const estado = estadoSelect ? estadoSelect.value : 'ACTIVA';

    if (!nombre) {
        showToast('El nombre de la lista es obligatorio');
        return;
    }

    try {
        const res = await fetch('/api/listas', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                nombre: nombre,
                termino_busqueda: termino,
                descripcion: desc,
                estado: estado
            })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            const nuevaListaId = data.lista.id;
            showToast(`Lista "${nombre}" creada con éxito.`);

            // Conectar a la secuencia activa si se marcó la casilla
            if (checkConectar && checkConectar.checked && activeSequenceId) {
                await fetch(`/api/listas/${encodeURIComponent(nuevaListaId)}/conectar-secuencia`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        secuencia_id: activeSequenceId,
                        auto_ingresar_nuevos: true
                    })
                });
                showToast(`Lista vinculada automáticamente a la secuencia activa.`);
            }

            cerrarModalNuevaLista();
            // Limpiar inputs
            if (nombreInput) nombreInput.value = '';
            if (terminoInput) terminoInput.value = '';
            if (descInput) descInput.value = '';

            await cargarListas();
            if (activeSequenceId) {
                await cargarSecuenciaDetalle(activeSequenceId);
            }
        } else {
            showToast('Error al crear la lista');
        }
    } catch (e) {
        console.error(e);
        showToast('Error de red al crear la lista');
    }
}

async function cambiarEstadoLista(listaId, nuevoEstado) {
    try {
        const res = await fetch(`/api/listas/${encodeURIComponent(listaId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ estado: nuevoEstado })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast(`Estado de la lista actualizado a ${nuevoEstado}`);
            await cargarListas();
        } else {
            showToast('Error al actualizar lista');
        }
    } catch (e) {
        showToast('Error de conexión al actualizar estado de lista');
    }
}

async function eliminarLista(listaId) {
    if (!confirm('¿Estás seguro de que deseas eliminar esta lista de leads? (Los leads individuales no se borrarán de la base de datos)')) {
        return;
    }

    try {
        const res = await fetch(`/api/listas/${encodeURIComponent(listaId)}`, {
            method: 'DELETE'
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast('Lista eliminada correctamente.');
            await cargarListas();
            if (activeSequenceId) {
                await cargarSecuenciaDetalle(activeSequenceId);
            }
        } else {
            showToast('Error al eliminar lista');
        }
    } catch (e) {
        showToast('Error de conexión al eliminar lista');
    }
}

// Conectar lista a secuencia (Modal)
function abrirModalConectarLista(listaIdPreseleccionada = null, secuenciaIdPreseleccionada = null) {
    const selectLista = document.getElementById('select-conectar-lista-id');
    const selectSec = document.getElementById('select-conectar-secuencia-id');
    const backdrop = document.getElementById('modal-conectar-sec-backdrop');

    // Población de Listas de Leads disponibles
    if (selectLista) {
        if (allLoadedListas.length === 0) {
            selectLista.innerHTML = '<option value="">No hay listas creadas aún</option>';
        } else {
            selectLista.innerHTML = allLoadedListas.map(l => {
                const isSelected = listaIdPreseleccionada ? l.id === listaIdPreseleccionada : false;
                return `
                    <option value="${l.id}" ${isSelected ? 'selected' : ''}>
                        ${escapeHtml(l.nombre)} (${l.total_leads || 0} leads)
                    </option>
                `;
            }).join('');
            if (!listaIdPreseleccionada && allLoadedListas.length > 0) {
                selectLista.value = allLoadedListas[0].id;
            }
        }
    }

    // Población de Secuencias disponibles
    if (selectSec) {
        const secTarget = secuenciaIdPreseleccionada || activeSequenceId;
        if (allLoadedSecuencias.length === 0) {
            selectSec.innerHTML = '<option value="">No hay secuencias disponibles</option>';
        } else {
            selectSec.innerHTML = allLoadedSecuencias.map(s => `
                <option value="${s.id}" ${s.id === secTarget ? 'selected' : ''}>
                    ${escapeHtml(s.nombre)}
                </option>
            `).join('');
            if (secTarget) {
                selectSec.value = secTarget;
            }
        }
    }

    if (backdrop) backdrop.classList.add('active');
}

function abrirModalConectarListaASecuenciaActual() {
    if (allLoadedListas.length === 0) {
        showToast('Debes crear primero una lista de leads antes de vincularla a una secuencia.');
        abrirModalNuevaLista();
        return;
    }
    // Abrir modal con la secuencia actual preseleccionada, permitiendo al usuario elegir la lista
    abrirModalConectarLista(null, activeSequenceId);
}

function cerrarModalConectarSecuencia() {
    const backdrop = document.getElementById('modal-conectar-sec-backdrop');
    if (backdrop) backdrop.classList.remove('active');
}

async function confirmarConectarListaASecuencia() {
    const selectLista = document.getElementById('select-conectar-lista-id');
    const selectSec = document.getElementById('select-conectar-secuencia-id');
    const checkAuto = document.getElementById('check-auto-ingresar-nuevos');

    const listaId = selectLista ? selectLista.value : '';
    const secId = selectSec ? selectSec.value : '';
    const autoIngresar = checkAuto ? checkAuto.checked : true;

    if (!listaId || !secId) {
        showToast('Debes seleccionar tanto la lista de leads como la secuencia de destino');
        return;
    }

    try {
        const res = await fetch(`/api/listas/${encodeURIComponent(listaId)}/conectar-secuencia`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                secuencia_id: secId,
                auto_ingresar_nuevos: autoIngresar
            })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast(`Lista vinculada exitosamente a la secuencia.`);
            cerrarModalConectarSecuencia();
            await cargarListas();
            await cargarSecuencias();
            if (activeSequenceId === secId) {
                await cargarSecuenciaDetalle(secId);
            }
        } else {
            showToast('Error al vincular lista a secuencia');
        }
    } catch (e) {
        showToast('Error de conexión al vincular lista');
    }
}

async function desconectarListaDeSecuencia(listaId, secId) {
    if (!confirm('¿Deseas desvincular esta lista de prospectos de la secuencia?')) {
        return;
    }

    try {
        const res = await fetch(`/api/listas/${encodeURIComponent(listaId)}/desconectar-secuencia`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ secuencia_id: secId })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast('Lista desvinculada de la secuencia.');
            await cargarListas();
            await cargarSecuencias();
            if (activeSequenceId === secId) {
                await cargarSecuenciaDetalle(secId);
            }
        } else {
            showToast('Error al desvincular lista');
        }
    } catch (e) {
        showToast('Error de conexión al desvincular lista');
    }
}




