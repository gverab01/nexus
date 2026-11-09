// Vista global de Directorio / Base de Leads (CRM de Prospectos)
import React, { useState, useEffect, useCallback } from 'react';
import { 
  Users, 
  Search, 
  Building2, 
  MapPin, 
  ExternalLink, 
  Layers, 
  RefreshCw, 
  Eye, 
  Trash2, 
  Clock, 
  ChevronLeft, 
  ChevronRight, 
  ChevronsLeft, 
  ChevronsRight, 
  X, 
  Download,
  Sparkles,
  Mail,
  Compass
} from 'lucide-react';
import { 
  fetchProspects, 
  fetchLeadLists, 
  fetchSequences, 
  syncLeadWithLinkedIn, 
  deleteProspect, 
  deleteProspectsBatch,
  importSelectedProspects,
  syncAcceptedConnections,
  resolveLeadEmail,
  batchResolveLeadEmails,
  enqueueCentralTasks
} from '../../services/api';
import LeadModal from './LeadModal';
import NewListModal from '../Lists/NewListModal';
import UnifiedLeadsTable from './UnifiedLeadsTable';
import { useSyncQueue } from '../../hooks/useSyncQueue';

const ESTADOS_DISPONIBLES = [
  { id: '', label: 'Todos los estados' },
  { id: 'EXTRAIDO', label: 'Extraído (Sin acción)' },
  { id: 'PERFIL_VISITADO', label: 'Perfil Visitado' },
  { id: 'INVITACION_ENVIADA', label: 'Invitación Enviada' },
  { id: 'CONECTADO', label: 'Conectado en LinkedIn' },
  { id: 'MENSAJE_ENVIADO', label: 'Mensaje Enviado' },
  { id: 'RESPONDIÓ', label: 'Respondió' },
  { id: 'REUNIÓN_AGENDADA', label: 'Reunión Agendada' },
];

const PRESETS_FECHA = [
  { id: 'todo', label: 'Cualquier fecha' },
  { id: '7d', label: 'Últimos 7 días' },
  { id: '30d', label: 'Últimos 30 días' },
  { id: '90d', label: 'Últimos 3 meses' },
];

export default function LeadsDirectoryView({ activeTenantWorkspace = '', onOpenLeadSearch = null }) {
  // Datos
  const [leads, setLeads] = useState([]);
  const [totalLeads, setTotalLeads] = useState(0);
  const [loading, setLoading] = useState(true);
  const [leadLists, setLeadLists] = useState([]);
  const [sequences, setSequences] = useState([]);

  // Filtros
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [selectedListId, setSelectedListId] = useState('');
  const [selectedSequenceId, setSelectedSequenceId] = useState('');
  const [selectedEstado, setSelectedEstado] = useState('');
  const [selectedDatePreset, setSelectedDatePreset] = useState('todo');
  const [sortOrder, setSortOrder] = useState('fecha_desc');

  // Paginación
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  // Selección múltiple
  const [selectedLeadIds, setSelectedLeadIds] = useState(new Set());

  // Acciones en curso
  const [resolvingEmailIds, setResolvingEmailIds] = useState(new Set());
  const [isBatchResolvingEmail, setIsBatchResolvingEmail] = useState(false);
  const [isBatchDeleting, setIsBatchDeleting] = useState(false);
  const [isSyncingConnections, setIsSyncingConnections] = useState(false);

  // Cola serializada de sincronización con LinkedIn
  const handleLeadUpdatedFromQueue = useCallback((updatedLead) => {
    setLeads((prev) =>
      prev.map((l) =>
        l.id === updatedLead.id
          ? {
              ...l,
              ...updatedLead,
              cargo: updatedLead.cargo_actual || updatedLead.cargo_titular || l.cargo,
              cargo_actual: updatedLead.cargo_actual || l.cargo_actual,
              cargo_titular: updatedLead.cargo_titular || l.cargo_titular,
              institucion: updatedLead.institucion_actual || l.institucion,
              institucion_actual: updatedLead.institucion_actual || l.institucion_actual,
              empresa: updatedLead.institucion_actual || l.empresa || updatedLead.empresa,
              ubicacion: updatedLead.ubicacion || l.ubicacion,
              nombre: updatedLead.nombre || l.nombre,
              grado_red: updatedLead.grado_red || l.grado_red,
              estado: updatedLead.estado || l.estado,
              updated_at: updatedLead.updated_at || l.updated_at
            }
          : l
      )
    );
  }, []);

  const {
    syncingLeadIds,
    activeSyncingLeadId,
    syncQueue,
    syncQueueStats,
    isProcessing: isBatchSyncing,
    enqueueLead,
    enqueueLeads,
    cancelQueue
  } = useSyncQueue({
    onLeadUpdated: handleLeadUpdatedFromQueue
  });

  // Modales
  const [selectedLeadForModal, setSelectedLeadForModal] = useState(null);
  const [showSaveToListsModal, setShowSaveToListsModal] = useState(false);
  const [targetListIds, setTargetListIds] = useState(new Set());
  const [savingToLists, setSavingToLists] = useState(false);
  const [showNewListModal, setShowNewListModal] = useState(false);

  // Debounce del término de búsqueda
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery.trim());
      setCurrentPage(1);
    }, 350);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Cargar listas y secuencias del workspace para los dropdowns
  useEffect(() => {
    loadAuxiliaryData();
  }, [activeTenantWorkspace]);

  async function loadAuxiliaryData() {
    try {
      const [listsRes, seqRes] = await Promise.all([
        fetchLeadLists(activeTenantWorkspace).catch(() => []),
        fetchSequences(activeTenantWorkspace).catch(() => [])
      ]);
      setLeadLists(listsRes || []);
      setSequences(seqRes || []);
    } catch (e) {
      console.error('Error cargando listas/secuencias auxiliares:', e);
    }
  }

  // Cargar los leads cada vez que cambian filtros o paginación
  useEffect(() => {
    loadLeads();
  }, [
    activeTenantWorkspace, 
    debouncedSearch, 
    selectedListId, 
    selectedSequenceId, 
    selectedEstado, 
    selectedDatePreset, 
    sortOrder, 
    currentPage, 
    pageSize
  ]);

  async function loadLeads() {
    setLoading(true);
    try {
      let fechaDesde = '';
      if (selectedDatePreset === '7d') {
        const d = new Date();
        d.setDate(d.getDate() - 7);
        fechaDesde = d.toISOString();
      } else if (selectedDatePreset === '30d') {
        const d = new Date();
        d.setDate(d.getDate() - 30);
        fechaDesde = d.toISOString();
      } else if (selectedDatePreset === '90d') {
        const d = new Date();
        d.setDate(d.getDate() - 90);
        fechaDesde = d.toISOString();
      }

      const offset = (currentPage - 1) * pageSize;
      const res = await fetchProspects({
        busqueda: debouncedSearch,
        listaId: selectedListId,
        secuenciaId: selectedSequenceId,
        estado: selectedEstado,
        fechaDesde: fechaDesde,
        orden: sortOrder,
        tenantId: activeTenantWorkspace,
        limit: pageSize,
        offset: offset
      });

      setLeads(res.leads || []);
      setTotalLeads(res.total || 0);
      // Limpiar selección de IDs que ya no están en la vista si cambiaron los filtros
      setSelectedLeadIds(new Set());
    } catch (err) {
      console.error('Error cargando prospectos:', err);
    } finally {
      setLoading(false);
    }
  }

  // Sincronizar un lead individual en vivo (encolado persistente en PostgreSQL)
  async function handleSyncSingleLead(e, lead) {
    if (e && e.stopPropagation) e.stopPropagation();
    if (!lead?.id) return;
    try {
      const res = await enqueueCentralTasks('LI_ENRICH', [lead.id], {}, 5, activeTenantWorkspace);
      if (res && res.ok) {
        alert(`Prospecto '${lead.nombre || 'Lead'}' encolado en la base de datos PostgreSQL.\nSe sincronizará en segundo plano con descansos antibaneo.`);
      }
    } catch (err) {
      alert(`Error encolando tarea: ${err.message}`);
    }
  }

  // Resolver correo de un lead individual (1er grado o Cascada Waterfall)
  async function handleResolveSingleLeadEmail(e, lead) {
    if (e) e.stopPropagation();
    if (!lead?.id) return;
    try {
      setResolvingEmailIds(prev => new Set(prev).add(lead.id));
      const res = await resolveLeadEmail(lead.id, true);
      if (res && res.email) {
        setLeads(prev => prev.map(l => l.id === lead.id ? {
          ...l,
          email: res.email,
          email_extracted: res.email,
          email_source: res.source,
          email_status: res.status,
          empresa_dominio: res.dominio || l.empresa_dominio
        } : l));
      } else {
        alert(res?.motivo || 'No se localizó correo verificado para este prospecto.');
      }
    } catch (err) {
      alert(`Error resolviendo correo: ${err.message}`);
    } finally {
      setResolvingEmailIds(prev => {
        const next = new Set(prev);
        next.delete(lead.id);
        return next;
      });
    }
  }

  // Resolver correos en bloque para los leads seleccionados
  async function handleBatchResolveEmails() {
    if (selectedLeadIds.size === 0) return;
    setIsBatchResolvingEmail(true);
    try {
      const res = await batchResolveLeadEmails(Array.from(selectedLeadIds), true);
      alert(`Resolución en cascada finalizada: ${res?.resueltos || 0} correos resueltos, ${res?.no_encontrados || 0} no localizados.`);
      await loadLeads();
    } catch (err) {
      alert(`Error en resolución en bloque: ${err.message}`);
    } finally {
      setIsBatchResolvingEmail(false);
    }
  }

  // Sincronizar en lote los leads seleccionados (encolado persistente en PostgreSQL)
  async function handleBatchSync() {
    if (selectedLeadIds.size === 0) return;
    const ids = Array.from(selectedLeadIds);
    try {
      const res = await enqueueCentralTasks('LI_ENRICH', ids, {}, 5, activeTenantWorkspace);
      if (res && res.ok) {
        alert(`${res.enqueued || ids.length} prospectos encolados en la base de datos PostgreSQL.\nSe sincronizarán en segundo plano a ritmo seguro con pausas antibaneo (${res.skipped || 0} omitidos por ya estar en cola).\n\nPuedes navegar libremente entre pestañas.`);
      }
      setSelectedLeadIds(new Set());
    } catch (err) {
      alert(`Error encolando lote de prospectos: ${err.message}`);
    }
  }

  // Sincronizar en bloque las conexiones aceptadas desde LinkedIn
  async function handleSyncConnections() {
    setIsSyncingConnections(true);
    try {
      const res = await syncAcceptedConnections(activeTenantWorkspace);
      if (res && res.ok) {
        alert(res.mensaje || `Sincronización exitosa: ${res.nuevos_conectados || 0} nuevas conexiones detectadas.`);
        await loadLeads();
      } else {
        alert(res?.mensaje || 'No se pudo completar la sincronización de conexiones con LinkedIn.');
      }
    } catch (err) {
      alert(`Error sincronizando conexiones con LinkedIn: ${err.message}`);
    } finally {
      setIsSyncingConnections(false);
    }
  }

  // Eliminar un lead individual
  async function handleDeleteSingleLead(e, leadId) {
    e.stopPropagation();
    if (!confirm('¿Estás seguro de eliminar este prospecto permanentemente de la base de datos?')) return;
    try {
      await deleteProspect(leadId);
      setLeads(prev => prev.filter(l => l.id !== leadId));
      setTotalLeads(prev => Math.max(0, prev - 1));
      setSelectedLeadIds(prev => {
        const next = new Set(prev);
        next.delete(leadId);
        return next;
      });
    } catch (err) {
      alert(`Error eliminando prospecto: ${err.message}`);
    }
  }

  // Eliminar en lote los leads seleccionados
  async function handleBatchDelete() {
    if (selectedLeadIds.size === 0) return;
    if (!confirm(`¿Eliminar permanentemente ${selectedLeadIds.size} prospectos seleccionados de la base de datos?`)) return;
    setIsBatchDeleting(true);
    try {
      await deleteProspectsBatch(Array.from(selectedLeadIds));
      setSelectedLeadIds(new Set());
      await loadLeads();
    } catch (err) {
      alert(`Error eliminando lote de prospectos: ${err.message}`);
    } finally {
      setIsBatchDeleting(false);
    }
  }

  // Selección individual y toggle all
  function handleToggleLead(leadId) {
    setSelectedLeadIds(prev => {
      const next = new Set(prev);
      if (next.has(leadId)) next.delete(leadId);
      else next.add(leadId);
      return next;
    });
  }

  function handleToggleSelectAll() {
    if (selectedLeadIds.size === leads.length && leads.length > 0) {
      setSelectedLeadIds(new Set());
    } else {
      setSelectedLeadIds(new Set(leads.map(l => l.id)));
    }
  }

  // Asociar leads seleccionados a listas
  async function handleConfirmAddToLists() {
    if (selectedLeadIds.size === 0 || targetListIds.size === 0) return;
    setSavingToLists(true);
    try {
      const selectedLeadsObjects = leads.filter(l => selectedLeadIds.has(l.id));
      await importSelectedProspects(selectedLeadsObjects, Array.from(targetListIds), activeTenantWorkspace);
      setShowSaveToListsModal(false);
      setTargetListIds(new Set());
      setSelectedLeadIds(new Set());
      await loadLeads();
    } catch (err) {
      alert(`Error vinculando prospectos a listas: ${err.message}`);
    } finally {
      setSavingToLists(false);
    }
  }

  // Exportar a CSV
  function handleExportCSV() {
    if (leads.length === 0) {
      alert('No hay prospectos para exportar con los filtros actuales');
      return;
    }
    const headers = ['Nombre', 'Cargo Actual', 'Empresa / Institución', 'Ubicación', 'Estado', 'Listas', 'Secuencias', 'Fecha Creación', 'Perfil LinkedIn'];
    const rows = leads.map(l => [
      `"${(l.nombre || '').replace(/"/g, '""')}"`,
      `"${(l.cargo_actual || '').replace(/"/g, '""')}"`,
      `"${(l.institucion_actual || '').replace(/"/g, '""')}"`,
      `"${(l.ubicacion || '').replace(/"/g, '""')}"`,
      `"${l.estado || ''}"`,
      `"${(l.listas || []).map(lst => lst.nombre).join('; ')}"`,
      `"${(l.secuencias || []).map(seq => seq.nombre).join('; ')}"`,
      `"${l.created_at || ''}"`,
      `"${l.perfil_url || ''}"`
    ]);
    const csvContent = 'data:text/csv;charset=utf-8,\uFEFF' + [headers.join(','), ...rows.map(e => e.join(','))].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `leads_nexusreach_${new Date().toISOString().split('T')[0]}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  // Limpiar filtros
  const hasActiveFilters = Boolean(
    searchQuery || 
    selectedListId || 
    selectedSequenceId || 
    selectedEstado || 
    selectedDatePreset !== 'todo' || 
    sortOrder !== 'fecha_desc'
  );

  function handleResetFilters() {
    setSearchQuery('');
    setDebouncedSearch('');
    setSelectedListId('');
    setSelectedSequenceId('');
    setSelectedEstado('');
    setSelectedDatePreset('todo');
    setSortOrder('fecha_desc');
    setCurrentPage(1);
  }

  const totalPages = Math.max(1, Math.ceil(totalLeads / pageSize));

  // Formateador de tiempo relativo
  function formatRelativeTime(isoString) {
    if (!isoString) return '';
    try {
      const d = new Date(isoString);
      const diffMs = Date.now() - d.getTime();
      const diffMins = Math.floor(diffMs / 60000);
      const diffHours = Math.floor(diffMins / 60);
      const diffDays = Math.floor(diffHours / 24);

      if (diffMins < 2) return 'Ahora mismo';
      if (diffMins < 60) return `Hace ${diffMins} min`;
      if (diffHours < 24) return `Hace ${diffHours} h`;
      if (diffDays === 1) return 'Ayer';
      if (diffDays < 7) return `Hace ${diffDays} días`;
      return d.toLocaleDateString('es-CL', { day: '2-digit', month: 'short' });
    } catch {
      return '';
    }
  }

  return (
    <div className="space-y-4 font-sans animate-fadeIn">
      {/* 1. Header principal con métrica y acciones globales */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[#22252B]">
        <div className="flex items-center gap-2.5">
          <h1 className="text-base font-medium text-[#F1F3F5] tracking-tight">
            Directorio de leads
          </h1>
          <span className="text-xs font-mono text-zinc-400 bg-[#14161A] border border-[#22252B] px-2 py-0.5 rounded">
            {totalLeads} {totalLeads === 1 ? 'prospecto' : 'prospectos'}
          </span>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {selectedLeadIds.size > 0 && (
            <div className="flex items-center gap-1.5 bg-[#14161A] border border-[#22252B] p-1 rounded-md">
              <span className="text-[11px] font-mono text-zinc-400 px-2">
                {selectedLeadIds.size} seleccionados
              </span>

              <button
                type="button"
                onClick={handleBatchResolveEmails}
                disabled={isBatchResolvingEmail}
                className="flex items-center gap-1 px-2.5 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium transition cursor-pointer disabled:opacity-40"
              >
                <Sparkles className={`w-3 h-3 ${isBatchResolvingEmail ? 'animate-spin' : ''}`} />
                <span>{isBatchResolvingEmail ? 'Resolviendo...' : 'Resolver correos'}</span>
              </button>

              <button
                type="button"
                onClick={() => setShowSaveToListsModal(true)}
                className="flex items-center gap-1 px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-medium transition cursor-pointer"
              >
                <Layers className="w-3 h-3 text-zinc-400" />
                <span>Añadir a lista</span>
              </button>

              <button
                type="button"
                onClick={handleBatchSync}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-emerald-950/60 hover:bg-emerald-900/80 text-emerald-300 border border-emerald-500/30 text-xs font-medium transition cursor-pointer"
                title="Encolar sincronización de prospectos seleccionados con LinkedIn"
              >
                <RefreshCw className="w-3 h-3 text-emerald-400" />
                <span>Sincronizar seleccionados ({selectedLeadIds.size})</span>
              </button>

              <button
                type="button"
                onClick={handleBatchDelete}
                disabled={isBatchDeleting}
                className="flex items-center gap-1 px-2 py-1 rounded text-red-400 hover:bg-red-950/30 text-xs font-medium transition cursor-pointer disabled:opacity-40"
              >
                <Trash2 className="w-3 h-3" />
                <span>Eliminar</span>
              </button>
            </div>
          )}

          <button
            type="button"
            onClick={handleSyncConnections}
            disabled={isSyncingConnections}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-[#14161A] hover:bg-zinc-800 border border-[#22252B] text-zinc-300 text-xs font-medium transition cursor-pointer disabled:opacity-50"
            title="Sincronizar conexiones aceptadas en LinkedIn"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isSyncingConnections ? 'animate-spin' : 'text-zinc-400'}`} />
            <span className="hidden sm:inline">{isSyncingConnections ? 'Sincronizando...' : 'Sincronizar conexiones'}</span>
          </button>

          <button
            type="button"
            onClick={handleExportCSV}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-[#14161A] hover:bg-zinc-800 border border-[#22252B] text-zinc-300 text-xs font-medium transition cursor-pointer"
            title="Exportar a archivo CSV"
          >
            <Download className="w-3.5 h-3.5 text-zinc-400" />
            <span className="hidden sm:inline">Exportar CSV</span>
          </button>

          {onOpenLeadSearch && (
            <button
              type="button"
              onClick={onOpenLeadSearch}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium transition cursor-pointer shadow-xs"
            >
              <Search className="w-3.5 h-3.5" />
              <span>Buscar prospectos</span>
            </button>
          )}
        </div>
      </div>

      {/* 2. Barra de filtros compacta */}
      <div className="p-3 rounded-lg border border-[#22252B] bg-[#14161A] space-y-2.5">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-3 items-center">
          {/* Búsqueda por texto (Nombre, cargo, empresa, ubicación) */}
          <div className="md:col-span-4 relative">
            <Search className="w-4 h-4 text-zinc-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Buscar por nombre, cargo, colegio o ciudad..."
              className="w-full pl-9 pr-8 py-1.5 rounded-md bg-[#0E0F12] border border-[#22252B] text-xs text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-zinc-500 transition"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300 cursor-pointer"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {/* Filtro por Lista de Leads */}
          <div className="md:col-span-2">
            <select
              value={selectedListId}
              onChange={(e) => {
                setSelectedListId(e.target.value);
                setCurrentPage(1);
              }}
              className="w-full py-1.5 px-2.5 rounded-md bg-[#0E0F12] border border-[#22252B] text-xs text-zinc-200 focus:outline-none focus:border-zinc-500 transition cursor-pointer"
            >
              <option value="">Todas las listas</option>
              <option value="sin_lista">Sin lista asignada</option>
              {leadLists.map(lst => (
                <option key={lst.id} value={lst.id}>
                  {lst.nombre}
                </option>
              ))}
            </select>
          </div>

          {/* Filtro por Secuencia */}
          <div className="md:col-span-2">
            <select
              value={selectedSequenceId}
              onChange={(e) => {
                setSelectedSequenceId(e.target.value);
                setCurrentPage(1);
              }}
              className="w-full py-1.5 px-2.5 rounded-md bg-[#0E0F12] border border-[#22252B] text-xs text-zinc-200 focus:outline-none focus:border-zinc-500 transition cursor-pointer"
            >
              <option value="">Todas las secuencias</option>
              <option value="sin_secuencia">Sin secuencia</option>
              {sequences.map(seq => (
                <option key={seq.id} value={seq.id}>
                  {seq.nombre}
                </option>
              ))}
            </select>
          </div>

          {/* Filtro por Estado */}
          <div className="md:col-span-2">
            <select
              value={selectedEstado}
              onChange={(e) => {
                setSelectedEstado(e.target.value);
                setCurrentPage(1);
              }}
              className="w-full py-1.5 px-2.5 rounded-md bg-[#0E0F12] border border-[#22252B] text-xs text-zinc-200 focus:outline-none focus:border-zinc-500 transition cursor-pointer"
            >
              {ESTADOS_DISPONIBLES.map(est => (
                <option key={est.id} value={est.id}>
                  {est.label}
                </option>
              ))}
            </select>
          </div>

          {/* Ordenamiento */}
          <div className="md:col-span-2">
            <select
              value={sortOrder}
              onChange={(e) => {
                setSortOrder(e.target.value);
                setCurrentPage(1);
              }}
              className="w-full py-1.5 px-2.5 rounded-md bg-[#0E0F12] border border-[#22252B] text-xs text-zinc-200 focus:outline-none focus:border-zinc-500 transition cursor-pointer"
            >
              <option value="fecha_desc">Más recientes primero</option>
              <option value="fecha_asc">Más antiguos primero</option>
              <option value="actividad_desc">Última actividad</option>
              <option value="nombre_asc">Nombre (A - Z)</option>
            </select>
          </div>
        </div>

        {/* Barra inferior de filtros secundarios y reset */}
        <div className="flex items-center justify-between pt-2 border-t border-[#22252B]/60 text-xs text-zinc-400 flex-wrap gap-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[11px] text-zinc-500 font-medium">Fecha de adición:</span>
            {PRESETS_FECHA.map(p => (
              <button
                key={p.id}
                type="button"
                onClick={() => {
                  setSelectedDatePreset(p.id);
                  setCurrentPage(1);
                }}
                className={`px-2 py-0.5 rounded text-[11px] font-medium transition cursor-pointer ${
                  selectedDatePreset === p.id 
                    ? 'bg-zinc-800 text-white font-semibold' 
                    : 'text-zinc-500 hover:text-zinc-300'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>

          {hasActiveFilters && (
            <button
              type="button"
              onClick={handleResetFilters}
              className="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-white transition cursor-pointer underline"
            >
              <X className="w-3 h-3" />
              <span>Limpiar filtros</span>
            </button>
          )}
        </div>
      </div>

      {/* Banner de progreso de la cola de sincronización */}
      {(syncQueue.length > 0 || activeSyncingLeadId) && (
        <div className="flex items-center justify-between px-4 py-2.5 bg-emerald-950/40 border border-emerald-500/30 rounded-xl text-xs text-emerald-200 animate-fadeIn mb-3">
          <div className="flex items-center gap-2.5">
            <RefreshCw className="w-4 h-4 animate-spin text-emerald-400" />
            <div>
              <span className="font-semibold text-emerald-300">Cola de sincronización:</span>{' '}
              {activeSyncingLeadId ? (
                <span>
                  Sincronizando <span className="text-white font-medium">
                    {leads.find((l) => l.id === activeSyncingLeadId)?.nombre || syncQueue[0]?.nombre || 'prospecto'}
                  </span> en vivo...
                </span>
              ) : (
                'Preparando siguiente prospecto...'
              )}
              <span className="text-zinc-400 ml-2">
                ({syncQueueStats.completed} completados, {syncQueue.length + (activeSyncingLeadId ? 1 : 0)} pendientes
                {syncQueueStats.failed > 0 ? `, ${syncQueueStats.failed} fallidos` : ''})
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={cancelQueue}
            className="px-2.5 py-1 rounded bg-red-950/40 hover:bg-red-950/70 text-red-300 border border-red-500/20 text-xs font-medium transition cursor-pointer"
          >
            Cancelar cola ({syncQueue.length + (activeSyncingLeadId ? 1 : 0)})
          </button>
        </div>
      )}

      {/* 3. Tabla principal unificada de prospectos */}
      <UnifiedLeadsTable
        data={leads}
        context="directory"
        loading={loading}
        onOpenLead={(lead) => setSelectedLeadForModal(lead)}
        selectedLeadIds={selectedLeadIds}
        onToggleLead={handleToggleLead}
        onToggleSelectAll={handleToggleSelectAll}
        onSyncLinkedIn={handleSyncSingleLead}
        onResolveEmail={handleResolveSingleLeadEmail}
        onDeleteLead={handleDeleteSingleLead}
        syncingLeadIds={syncingLeadIds}
        activeSyncingLeadId={activeSyncingLeadId}
        resolvingLeadIds={resolvingEmailIds}
        actionInProgress={isBatchDeleting || isBatchResolvingEmail}
        onFilterByList={(listId) => {
          setSelectedListId(listId);
          setCurrentPage(1);
        }}
        onFilterBySequence={(seqId) => {
          setSelectedSequenceId(seqId);
          setCurrentPage(1);
        }}
        clientSidePagination={false}
        currentPage={currentPage}
        pageSize={pageSize}
        totalItems={totalLeads}
        onPageChange={(p) => setCurrentPage(p)}
        onPageSizeChange={(s) => {
          setPageSize(s);
          setCurrentPage(1);
        }}
        externalSortColumn={
          sortOrder === 'fecha_desc' || sortOrder === 'fecha_asc' ? 'fecha'
          : sortOrder === 'nombre_asc' ? 'prospecto'
          : null
        }
        externalSortDirection={
          sortOrder === 'fecha_desc' ? 'desc'
          : sortOrder === 'fecha_asc' ? 'asc'
          : sortOrder === 'nombre_asc' ? 'asc'
          : null
        }
        onSortChange={({ column, direction }) => {
          if (column === 'fecha') {
            setSortOrder(direction === 'asc' ? 'fecha_asc' : 'fecha_desc');
          } else if (column === 'prospecto') {
            setSortOrder('nombre_asc');
          } else {
            setSortOrder('fecha_desc');
          }
          setCurrentPage(1);
        }}
        emptyTitle="No se encontraron prospectos"
        emptySubtitle={
          hasActiveFilters
            ? 'Ningún lead coincide con los filtros aplicados. Intenta restablecer los filtros.'
            : 'Aún no tienes prospectos guardados en este workspace. Puedes descubrirlos con el buscador de LinkedIn.'
        }
        emptyAction={
          hasActiveFilters ? (
            <button
              type="button"
              onClick={handleResetFilters}
              className="px-3.5 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-medium transition cursor-pointer"
            >
              Limpiar filtros
            </button>
          ) : onOpenLeadSearch ? (
            <button
              type="button"
              onClick={onOpenLeadSearch}
              className="px-4 py-2 rounded-lg bg-white hover:bg-zinc-200 text-zinc-950 text-xs font-semibold shadow transition cursor-pointer"
            >
              Ir al buscador de LinkedIn
            </button>
          ) : null
        }
      />

      {/* MODAL: GUARDAR LEADS SELECCIONADOS EN LISTAS */}
      {showSaveToListsModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-xs flex items-center justify-center p-4 z-50 animate-fadeIn font-sans">
          <div className="bg-[#121316] border border-white/[0.08] rounded-xl max-w-lg w-full p-5 space-y-4 shadow-2xl flex flex-col max-h-[85vh]">
            <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
              <div className="flex items-center gap-2.5">
                <div className="w-7 h-7 rounded-md bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-zinc-300">
                  <Layers className="w-3.5 h-3.5" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-zinc-100">
                    Añadir Prospectos a Listas
                  </h3>
                  <p className="text-[11px] text-zinc-400">
                    Selecciona las listas de destino para los {selectedLeadIds.size} prospectos seleccionados
                  </p>
                </div>
              </div>
              <button
                onClick={() => setShowSaveToListsModal(false)}
                className="text-zinc-500 hover:text-zinc-300 cursor-pointer"
              >
                ✕
              </button>
            </div>

            <div className="space-y-2 flex-1 overflow-y-auto pr-1">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-zinc-300">Listas disponibles:</span>
                <button
                  type="button"
                  onClick={() => setShowNewListModal(true)}
                  className="text-xs text-zinc-300 hover:text-white flex items-center gap-1 font-medium cursor-pointer"
                >
                  + Nueva Lista
                </button>
              </div>

              {leadLists.length === 0 ? (
                <div className="p-4 rounded-lg border border-dashed border-white/[0.08] text-center text-xs text-zinc-500">
                  No tienes listas creadas en este workspace.
                </div>
              ) : (
                leadLists.map(lst => {
                  const isChecked = targetListIds.has(lst.id);
                  return (
                    <div
                      key={lst.id}
                      onClick={() => {
                        setTargetListIds(prev => {
                          const next = new Set(prev);
                          if (next.has(lst.id)) next.delete(lst.id);
                          else next.add(lst.id);
                          return next;
                        });
                      }}
                      className={`p-3 rounded-lg border transition cursor-pointer flex items-center justify-between ${
                        isChecked 
                          ? 'bg-zinc-800/60 border-white/20' 
                          : 'bg-[#0D0E12] border-white/[0.06] hover:border-white/[0.12]'
                      }`}
                    >
                      <div className="flex items-center gap-2.5">
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => {}}
                          className="w-4 h-4 rounded border-zinc-700 bg-zinc-900 text-zinc-100 accent-zinc-200"
                        />
                        <div>
                          <p className="text-xs font-semibold text-zinc-200">{lst.nombre}</p>
                          {lst.descripcion && (
                            <p className="text-[11px] text-zinc-500 line-clamp-1">{lst.descripcion}</p>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            <div className="flex items-center justify-between border-t border-white/[0.06] pt-3">
              <span className="text-xs text-zinc-400 font-mono">
                {targetListIds.size} {targetListIds.size === 1 ? 'lista seleccionada' : 'listas seleccionadas'}
              </span>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setShowSaveToListsModal(false)}
                  className="px-3 py-1.5 rounded-md bg-zinc-900 hover:bg-zinc-800 border border-white/[0.08] text-zinc-300 text-xs font-medium cursor-pointer"
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  onClick={handleConfirmAddToLists}
                  disabled={savingToLists || targetListIds.size === 0}
                  className="px-4 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 text-xs font-semibold shadow-sm transition cursor-pointer disabled:opacity-40"
                >
                  {savingToLists ? 'Añadiendo...' : 'Confirmar'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal para crear una nueva lista */}
      {showNewListModal && (
        <NewListModal
          onClose={() => setShowNewListModal(false)}
          onCreated={async () => {
            setShowNewListModal(false);
            await loadAuxiliaryData();
          }}
          activeTenantWorkspace={activeTenantWorkspace}
        />
      )}

      {/* Modal de Detalle de Lead */}
      {selectedLeadForModal && (
        <LeadModal
          prospect={selectedLeadForModal}
          onClose={() => setSelectedLeadForModal(null)}
          onUpdated={async () => {
            await loadLeads();
          }}
        />
      )}
    </div>
  );
}
