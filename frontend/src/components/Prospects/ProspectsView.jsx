import React, { useState, useEffect } from 'react';
import { 
  Users, 
  Send, 
  UserCheck, 
  Clock, 
  Search, 
  RefreshCw, 
  ExternalLink, 
  Sparkles, 
  Building2, 
  ChevronRight,
  Filter,
  History,
  Trash2,
  UserPlus,
  CheckCircle2,
  X,
  CheckSquare,
  Square,
  AlertCircle,
  Briefcase
} from 'lucide-react';
import { 
  fetchProspects, 
  fetchMetrics, 
  fetchLeadLists, 
  triggerExtraction,
  importSelectedProspects,
  deleteProspect,
  deleteProspectsBatch
} from '../../services/api';
import LeadModal from './LeadModal';

const RECENT_SEARCHES_KEY = 'nexusreach_recent_searches';
const DEFAULT_SEARCHES = [
  'CEO Founder Chile',
  'Gerente General Chile',
  'Gerente Comercial Chile',
  'Gerente de Operaciones Chile',
  'Gerente Recursos Humanos Chile'
];

function getStoredRecentSearches() {
  try {
    const raw = localStorage.getItem(RECENT_SEARCHES_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed.slice(0, 5);
    }
  } catch (e) {
    console.error(e);
  }
  return DEFAULT_SEARCHES;
}

function saveSearchTermToStorage(term) {
  if (!term || !term.trim()) return null;
  const clean = term.trim();
  const current = getStoredRecentSearches();
  const updated = [clean, ...current.filter((t) => t.toLowerCase() !== clean.toLowerCase())].slice(0, 5);
  try {
    localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(updated));
  } catch (e) {
    console.error(e);
  }
  return updated;
}

export default function ProspectsView({ onExtractionStarted, activeTenantWorkspace = '' }) {
  const [prospects, setProspects] = useState([]);
  const [metrics, setMetrics] = useState({ hoy: 0, cola: 0, enviadas: 0, conectados: 0 });
  const [leadLists, setLeadLists] = useState([]);
  const [loading, setLoading] = useState(true);
  
  // Filtros y búsqueda
  const [activeFilter, setActiveFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  
  // Parámetros de extracción
  const [searchTerm, setSearchTerm] = useState('CEO Founder Chile');
  const [selectedPage, setSelectedPage] = useState(1);
  const [targetListId, setTargetListId] = useState('');
  const [extracting, setExtracting] = useState(false);
  const [recentSearches, setRecentSearches] = useState(getStoredRecentSearches);
  
  // Vista previa de resultados de búsqueda (Descubrimiento y selección previa)
  const [discoveredLeads, setDiscoveredLeads] = useState([]);
  const [selectedDiscoveredUrls, setSelectedDiscoveredUrls] = useState(new Set());
  const [showDiscoveryPanel, setShowDiscoveryPanel] = useState(false);
  const [importingSelected, setImportingSelected] = useState(false);

  // Selección múltiple para eliminación en bloque de la base de datos
  const [selectedDirectoryIds, setSelectedDirectoryIds] = useState(new Set());
  const [isDeletingBatch, setIsDeletingBatch] = useState(false);

  // Modal de detalle
  const [selectedProspect, setSelectedProspect] = useState(null);

  useEffect(() => {
    loadData();
    loadLists();
  }, [activeFilter, activeTenantWorkspace]);

  async function loadData() {
    try {
      setLoading(true);
      const [prospectsData, metricsData] = await Promise.all([
        fetchProspects(activeFilter, searchQuery, activeTenantWorkspace),
        fetchMetrics(activeTenantWorkspace).catch(() => ({})),
      ]);
      setProspects(prospectsData || []);
      setMetrics({
        hoy: metricsData.invitaciones_hoy || 0,
        cola: metricsData.en_cola || 0,
        enviadas: metricsData.invitaciones_enviadas || 0,
        conectados: metricsData.conectados || 0,
      });
    } catch (err) {
      console.error('Error cargando prospectos:', err);
    } finally {
      setLoading(false);
    }
  }

  async function loadLists() {
    try {
      const lists = await fetchLeadLists(activeTenantWorkspace);
      setLeadLists(lists || []);
      if (lists && lists.length > 0 && !targetListId) {
        setTargetListId(lists[0].id);
      }
    } catch (err) {
      console.error('Error cargando listas:', err);
    }
  }

  async function handleSearch(e) {
    e.preventDefault();
    try {
      setLoading(true);
      const data = await fetchProspects(activeFilter, searchQuery, activeTenantWorkspace);
      setProspects(data || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  async function handleRunExtraction() {
    try {
      setExtracting(true);
      if (onExtractionStarted) onExtractionStarted();
      
      // Ejecutar búsqueda en LinkedIn con auto_guardar = false para mostrar primero los resultados al usuario
      const res = await triggerExtraction(searchTerm, selectedPage, targetListId || null, false, activeTenantWorkspace);
      
      if (res.status === 'error') {
        alert(`Error en búsqueda: ${res.mensaje || 'Error desconocido'}`);
        return;
      }
      
      if (res.status === 'warning') {
        alert(`Aviso: ${res.mensaje}`);
        if (!res.leads || res.leads.length === 0) return;
      }
      
      const leads = res.leads || [];
      if (leads.length === 0) {
        alert(`No se detectaron perfiles en la página ${selectedPage} para "${searchTerm}".`);
        return;
      }

      setDiscoveredLeads(leads);
      // Pre-seleccionar todos los perfiles que no existen aún en la base de datos
      const initialSelected = new Set();
      leads.forEach((l) => {
        if (!l.ya_existe) {
          initialSelected.add(l.perfil_url);
        }
      });
      // Si todos ya estaban registrados, pre-seleccionamos todos por si desea asociarlos a una lista
      if (initialSelected.size === 0) {
        leads.forEach(l => initialSelected.add(l.perfil_url));
      }
      setSelectedDiscoveredUrls(initialSelected);
      setShowDiscoveryPanel(true);

      const updatedSearches = saveSearchTermToStorage(searchTerm);
      if (updatedSearches) setRecentSearches(updatedSearches);
    } catch (err) {
      alert(`Error buscando prospectos en LinkedIn: ${err.message}`);
    } finally {
      setExtracting(false);
    }
  }

  async function handleImportSelected() {
    const toImport = discoveredLeads.filter(l => selectedDiscoveredUrls.has(l.perfil_url));
    if (toImport.length === 0) {
      alert('Por favor selecciona al menos un prospecto para incorporar.');
      return;
    }

    try {
      setImportingSelected(true);
      const res = await importSelectedProspects(toImport, targetListId || null, activeTenantWorkspace);
      const agregados = res.nuevos_importados ?? 0;
      const omitidos = res.duplicados_omitidos ?? 0;
      alert(`¡Éxito! ${agregados} prospectos incorporados a tu base de datos (${omitidos} ya existentes asociados).`);

      // Actualizar estado de los descubiertos
      setDiscoveredLeads(prev => prev.map(l => {
        if (selectedDiscoveredUrls.has(l.perfil_url)) {
          return { ...l, ya_existe: true, guardado: true };
        }
        return l;
      }));
      setSelectedDiscoveredUrls(new Set());
      loadData();
      loadLists();
    } catch (err) {
      alert(`Error incorporando prospectos: ${err.message}`);
    } finally {
      setImportingSelected(false);
    }
  }

  function handleToggleSelectAllDiscovered() {
    if (selectedDiscoveredUrls.size === discoveredLeads.length) {
      setSelectedDiscoveredUrls(new Set());
    } else {
      setSelectedDiscoveredUrls(new Set(discoveredLeads.map(l => l.perfil_url)));
    }
  }

  function handleToggleDiscoveredLead(url) {
    setSelectedDiscoveredUrls(prev => {
      const next = new Set(prev);
      if (next.has(url)) next.delete(url);
      else next.add(url);
      return next;
    });
  }

  async function handleDeleteSingleProspect(prospect, e) {
    if (e) e.stopPropagation();
    const confirmed = window.confirm(`¿Seguro que deseas eliminar permanentemente a "${prospect.nombre}" de tu base de datos?`);
    if (!confirmed) return;

    try {
      await deleteProspect(prospect.id);
      setSelectedDirectoryIds(prev => {
        const next = new Set(prev);
        next.delete(prospect.id);
        return next;
      });
      loadData();
      loadLists();
    } catch (err) {
      alert(`Error eliminando prospecto: ${err.message}`);
    }
  }

  async function handleDeleteBatch() {
    if (selectedDirectoryIds.size === 0) return;
    const count = selectedDirectoryIds.size;
    const confirmed = window.confirm(
      `¿Seguro que deseas eliminar permanentemente los ${count} prospectos seleccionados de tu base de datos?\nEsta acción no se puede deshacer.`
    );
    if (!confirmed) return;

    try {
      setIsDeletingBatch(true);
      await deleteProspectsBatch(Array.from(selectedDirectoryIds));
      setSelectedDirectoryIds(new Set());
      loadData();
      loadLists();
    } catch (err) {
      alert(`Error eliminando prospectos seleccionados: ${err.message}`);
    } finally {
      setIsDeletingBatch(false);
    }
  }

  function handleToggleSelectAllDirectory() {
    if (selectedDirectoryIds.size === filteredProspects.length && filteredProspects.length > 0) {
      setSelectedDirectoryIds(new Set());
    } else {
      setSelectedDirectoryIds(new Set(filteredProspects.map(p => p.id)));
    }
  }

  function handleToggleSelectDirectoryLead(id, e) {
    if (e) e.stopPropagation();
    setSelectedDirectoryIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Cálculo de tasa de aceptación
  const acceptanceRate = metrics.enviadas > 0 
    ? Math.round((metrics.conectados / metrics.enviadas) * 100) 
    : 0;

  // Filtrado local por texto
  const filteredProspects = prospects.filter((p) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      (p.nombre && p.nombre.toLowerCase().includes(q)) ||
      (p.cargo && p.cargo.toLowerCase().includes(q)) ||
      (p.institucion && p.institucion.toLowerCase().includes(q))
    );
  });

  return (
    <div className="space-y-5 font-sans animate-fadeIn">
      {/* 1. Header de Sección */}
      <div>
        <h2 className="text-base font-semibold text-zinc-100 tracking-tight">Directorio de Prospectos B2B</h2>
        <p className="text-xs text-zinc-400 mt-0.5">
          Búsqueda directa en LinkedIn, extracción y enriquecimiento de decisores calificados
        </p>
      </div>

      {/* 2. Tarjetas KPI Métricas */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
          <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
            <span className="font-medium text-zinc-300">Invitaciones Hoy</span>
            <Clock className="w-3.5 h-3.5 text-zinc-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">
            {metrics.hoy} <span className="text-xs text-zinc-500 font-normal">/ 5</span>
          </div>
          <div className="mt-2 w-full bg-white/[0.06] h-1 rounded-full overflow-hidden">
            <div 
              className="bg-zinc-200 h-full rounded-full transition-all"
              style={{ width: `${Math.min(100, (metrics.hoy / 5) * 100)}%` }}
            />
          </div>
          <span className="text-[10px] text-zinc-500 mt-1.5 block">5 máx. diario seguro</span>
        </div>

        <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
          <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
            <span className="font-medium text-zinc-300">En Cola</span>
            <Users className="w-3.5 h-3.5 text-zinc-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">
            {metrics.cola}
          </div>
          <span className="text-[10px] text-zinc-400 mt-2 block font-medium">Listos para secuencia</span>
        </div>

        <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
          <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
            <span className="font-medium text-zinc-300">Invitaciones Enviadas</span>
            <Send className="w-3.5 h-3.5 text-zinc-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">
            {metrics.enviadas}
          </div>
          <span className="text-[10px] text-zinc-500 mt-2 block">Esperando respuesta</span>
        </div>

        <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
          <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
            <span className="font-medium text-zinc-300">Conectados</span>
            <UserCheck className="w-3.5 h-3.5 text-zinc-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100 flex items-baseline gap-2">
            {metrics.conectados}
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/[0.04] text-zinc-300 border border-white/[0.08] font-mono font-normal">
              Tasa: {acceptanceRate}%
            </span>
          </div>
          <span className="text-[10px] text-zinc-500 mt-2 block">1er Grado activo</span>
        </div>
      </div>

      {/* Panel de Extracción Directa desde LinkedIn */}
      <div className="p-4 rounded-xl bg-[#121316] border border-white/[0.08] space-y-3.5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-md bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-zinc-300">
              <Sparkles className="w-3.5 h-3.5 text-zinc-300" />
            </div>
            <div>
              <h3 className="text-xs font-medium text-zinc-100">Extracción Directa de LinkedIn</h3>
              <p className="text-[11px] text-zinc-400">Descubre y califica prospectos mediante tu sesión conectada</p>
            </div>
          </div>
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[11px] text-zinc-500 mr-1 flex items-center gap-1">
              <History className="w-3 h-3 text-zinc-500" />
              Recientes:
            </span>
            {recentSearches.map((term) => (
              <button
                key={term}
                type="button"
                onClick={() => setSearchTerm(term)}
                className="px-2 py-0.5 rounded-md text-[11px] bg-[#0D0E12] hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 border border-white/[0.06] transition cursor-pointer"
                title={`Buscar "${term}"`}
              >
                {term}
              </button>
            ))}
          </div>
        </div>

        {/* Formulario de extracción */}
        <div className="grid grid-cols-1 md:grid-cols-12 gap-2.5 items-end">
          <div className="md:col-span-5">
            <label className="block text-[11px] font-medium text-zinc-400 mb-1">Término de Búsqueda</label>
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Ej: CEO Founder Chile, Gerente Comercial, Director..."
              className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-1.5 rounded-md text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 font-sans"
            />
          </div>

          <div className="md:col-span-2">
            <label className="block text-[11px] font-medium text-zinc-400 mb-1">Página</label>
            <select
              value={selectedPage}
              onChange={(e) => setSelectedPage(e.target.value)}
              className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-1.5 rounded-md text-xs text-zinc-200 focus:outline-none focus:border-zinc-500"
            >
              {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((num) => (
                <option key={num} value={num}>Página {num}</option>
              ))}
            </select>
          </div>

          <div className="md:col-span-3">
            <label className="block text-[11px] font-medium text-zinc-400 mb-1">Lista Destino</label>
            <select
              value={targetListId}
              onChange={(e) => setTargetListId(e.target.value)}
              className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-1.5 rounded-md text-xs text-zinc-200 focus:outline-none focus:border-zinc-500"
            >
              {leadLists.length === 0 ? (
                <option value="">Sin listas creadas</option>
              ) : (
                leadLists.map((l) => (
                  <option key={l.id} value={l.id}>{l.nombre} ({l.total_leads || 0})</option>
                ))
              )}
            </select>
          </div>

          <div className="md:col-span-2">
            <button
              onClick={handleRunExtraction}
              disabled={extracting}
              className="w-full flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs shadow-sm transition cursor-pointer disabled:opacity-50"
            >
              <Search className={`w-3.5 h-3.5 ${extracting ? 'animate-spin' : ''}`} />
              <span>{extracting ? 'Buscando...' : 'Buscar'}</span>
            </button>
          </div>
        </div>
      </div>

      {/* Panel Interactivo de Descubrimiento de Prospectos (Previsualización antes de guardar) */}
      {showDiscoveryPanel && discoveredLeads.length > 0 && (
        <div className="rounded-xl border border-white/[0.08] bg-[#121316] shadow-2xl p-4 space-y-3.5 animate-in fade-in duration-200">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-white/[0.06] pb-3">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-md bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-zinc-300 shrink-0">
                <Sparkles className="w-3.5 h-3.5 text-zinc-300" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-xs sm:text-sm font-medium text-zinc-100">
                    Resultados encontrados en LinkedIn ({discoveredLeads.length})
                  </h3>
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-white/[0.03] text-zinc-400 border border-white/[0.06]">
                    Pág. {selectedPage}
                  </span>
                </div>
                <p className="text-[11px] text-zinc-400">
                  Selecciona los contactos que deseas agregar a tu base de leads o vincular a la lista destino.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              <button
                type="button"
                onClick={handleToggleSelectAllDiscovered}
                className="px-2.5 py-1 rounded-md bg-[#0D0E12] hover:bg-zinc-800 border border-white/[0.08] text-zinc-300 text-[11px] font-medium transition cursor-pointer"
              >
                {selectedDiscoveredUrls.size === discoveredLeads.length ? 'Deseleccionar todos' : 'Seleccionar todos'}
              </button>

              <button
                type="button"
                onClick={handleImportSelected}
                disabled={importingSelected || selectedDiscoveredUrls.size === 0}
                className="flex items-center gap-1.5 px-3 py-1 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 text-xs font-medium shadow-sm transition cursor-pointer disabled:opacity-50"
              >
                <UserPlus className={`w-3.5 h-3.5 ${importingSelected ? 'animate-spin' : ''}`} />
                <span>
                  {importingSelected 
                    ? 'Agregando...' 
                    : `Agregar a mis Leads (${selectedDiscoveredUrls.size})`}
                </span>
              </button>

              <button
                type="button"
                onClick={() => setShowDiscoveryPanel(false)}
                title="Cerrar resultados de búsqueda"
                className="p-1 rounded-md text-zinc-400 hover:text-white hover:bg-zinc-800 transition cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Listado de prospectos descubiertos */}
          <div className="divide-y divide-white/[0.04] max-h-80 overflow-y-auto pr-1">
            {discoveredLeads.map((lead, idx) => {
              const isSelected = selectedDiscoveredUrls.has(lead.perfil_url);
              return (
                <div
                  key={lead.perfil_url || idx}
                  onClick={() => handleToggleDiscoveredLead(lead.perfil_url)}
                  className={`py-2 px-3 rounded-md flex items-center justify-between gap-3 transition cursor-pointer ${
                    isSelected ? 'bg-zinc-800/50 border border-white/[0.08]' : 'hover:bg-zinc-800/20 border border-transparent'
                  }`}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => handleToggleDiscoveredLead(lead.perfil_url)}
                      onClick={(e) => e.stopPropagation()}
                      className="w-3.5 h-3.5 rounded border-zinc-700 bg-zinc-900 text-zinc-100 focus:ring-0 cursor-pointer accent-zinc-200 shrink-0"
                    />

                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-xs text-zinc-100 hover:text-zinc-300 transition truncate">
                          {lead.nombre}
                        </span>
                        {lead.grado_red && (
                          <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-zinc-800 text-zinc-400">
                            {lead.grado_red}
                          </span>
                        )}
                        {lead.ya_existe ? (
                          <span className="text-[10px] px-1.5 py-0.2 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
                            Ya en tu base
                          </span>
                        ) : (
                          <span className="text-[10px] px-1.5 py-0.2 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">
                            Nuevo
                          </span>
                        )}
                      </div>

                      <div className="text-[11px] text-zinc-300 truncate flex items-center gap-1.5 mt-0.5">
                        <span className="font-medium text-emerald-400">
                          {lead.cargo_actual || lead.cargo_titular || lead.cargo || 'Profesional'}
                        </span>
                        {lead.institucion_actual && <span className="text-zinc-500">· {lead.institucion_actual}</span>}
                        {lead.ubicacion && <span className="text-zinc-500">· {lead.ubicacion}</span>}
                      </div>
                      {lead.cargo_titular && lead.cargo_titular !== lead.cargo_actual && (
                        <div className="text-[10px] text-zinc-500 truncate italic">
                          {lead.cargo_titular}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0" onClick={(e) => e.stopPropagation()}>
                    {lead.perfil_url && (
                      <a
                        href={lead.perfil_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        title="Ver en LinkedIn"
                        className="p-1 rounded text-zinc-400 hover:text-white hover:bg-zinc-800 transition"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                      </a>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Toolbar y Tabla de Prospectos */}
      <div className="rounded-xl border border-white/[0.08] bg-[#121316] overflow-hidden">
        <div className="p-3.5 border-b border-white/[0.06] flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <h2 className="text-xs font-medium text-zinc-100 tracking-tight">Directorio de Prospectos</h2>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono text-zinc-400 bg-white/[0.03] border border-white/[0.06]">
              {filteredProspects.length} registrados
            </span>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {/* Buscador */}
            <form onSubmit={handleSearch} className="relative">
              <Search className="w-3.5 h-3.5 text-zinc-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Buscar por nombre, empresa o cargo..."
                className="bg-[#0D0E12] border border-white/[0.08] pl-8 pr-3 py-1.5 rounded-md text-xs text-zinc-100 placeholder-zinc-500 w-48 sm:w-60 focus:outline-none focus:border-zinc-500 font-sans"
              />
            </form>

            {/* Pestañas de Filtro por Estado */}
            <div className="flex items-center bg-[#0D0E12] p-0.5 rounded-md border border-white/[0.08] text-[11px]">
              {[
                { id: '', label: 'Todos' },
                { id: 'EXTRAIDO', label: 'En Cola' },
                { id: 'INVITACION_ENVIADA', label: 'Invitados' },
                { id: 'CONECTADO', label: 'Conectados' },
                { id: 'REUNION_AGENDADA', label: 'Reuniones Agendadas' },
              ].map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveFilter(tab.id)}
                  className={`px-2.5 py-1 rounded transition cursor-pointer ${
                    activeFilter === tab.id
                      ? 'bg-zinc-800 text-zinc-100 font-medium shadow-xs'
                      : 'text-zinc-400 hover:text-zinc-200'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {/* Botón Refrescar */}
            <button
              onClick={loadData}
              title="Refrescar lista"
              className="p-1.5 rounded-md bg-[#0D0E12] border border-white/[0.08] hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition cursor-pointer"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* Barra contextual de selección múltiple */}
        {selectedDirectoryIds.size > 0 && (
          <div className="bg-white/[0.03] border-b border-white/[0.06] px-4 py-2 flex items-center justify-between gap-3 animate-in fade-in">
            <div className="flex items-center gap-2 text-xs text-zinc-300">
              <span className="w-1.5 h-1.5 rounded-full bg-zinc-400"></span>
              <span className="font-medium text-zinc-100">{selectedDirectoryIds.size}</span>
              <span className="text-zinc-400">prospectos seleccionados</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setSelectedDirectoryIds(new Set())}
                className="px-2.5 py-1 rounded-md text-[11px] text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition cursor-pointer"
              >
                Deseleccionar
              </button>
              <button
                type="button"
                onClick={handleDeleteBatch}
                disabled={isDeletingBatch}
                className="flex items-center gap-1.5 px-3 py-1 rounded-md bg-rose-950/40 hover:bg-rose-900/50 text-rose-300 border border-rose-800/40 text-xs font-medium transition cursor-pointer disabled:opacity-50"
              >
                <Trash2 className={`w-3.5 h-3.5 ${isDeletingBatch ? 'animate-spin' : ''}`} />
                <span>{isDeletingBatch ? 'Eliminando...' : `Eliminar (${selectedDirectoryIds.size})`}</span>
              </button>
            </div>
          </div>
        )}

        {/* Tabla */}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-white/[0.06] bg-[#0F1014] text-zinc-400 text-[11px] font-medium tracking-tight">
                <th className="py-2.5 px-4 w-10">
                  <input
                    type="checkbox"
                    checked={filteredProspects.length > 0 && selectedDirectoryIds.size === filteredProspects.length}
                    onChange={handleToggleSelectAllDirectory}
                    className="w-3.5 h-3.5 rounded border-zinc-700 bg-zinc-900 accent-zinc-200 cursor-pointer"
                    title="Seleccionar todos los visibles"
                  />
                </th>
                <th className="py-2.5 px-3">Prospecto / Contacto</th>
                <th className="py-2.5 px-3">Cargo / Puesto Actual</th>
                <th className="py-2.5 px-3">Empresa / Organización</th>
                <th className="py-2.5 px-3">Ubicación</th>
                <th className="py-2.5 px-3">Red</th>
                <th className="py-2.5 px-3">Estado</th>
                <th className="py-2.5 px-4 text-right">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {loading ? (
                <tr>
                  <td colSpan={8} className="py-8 text-center text-zinc-500">
                    Cargando prospectos...
                  </td>
                </tr>
              ) : filteredProspects.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-8 text-center text-zinc-500">
                    No se encontraron prospectos con este criterio.
                  </td>
                </tr>
              ) : (
                filteredProspects.map((prospect) => {
                  const stateBadgeStyles = {
                    EXTRAIDO: 'bg-white/[0.04] text-zinc-400 border-white/[0.08]',
                    INVITACION_ENVIADA: 'bg-emerald-950/20 text-emerald-400 border-emerald-500/20',
                    INVITACION_PENDIENTE: 'bg-amber-950/20 text-amber-300 border-amber-500/20',
                    CONECTADO: 'bg-zinc-800 text-zinc-200 border-zinc-700/60',
                    REUNION_AGENDADA: 'bg-emerald-950/30 text-emerald-300 border-emerald-500/30 font-medium',
                  }[prospect.estado] || 'bg-white/[0.04] text-zinc-400 border-white/[0.08]';

                  const isSelected = selectedDirectoryIds.has(prospect.id);

                  return (
                    <tr 
                      key={prospect.id}
                      onClick={() => setSelectedProspect(prospect)}
                      className={`transition cursor-pointer group ${
                        isSelected ? 'bg-white/[0.04]' : 'hover:bg-white/[0.02]'
                      }`}
                    >
                      <td className="py-3 px-4 w-10" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={(e) => handleToggleSelectDirectoryLead(prospect.id, e)}
                          className="w-3.5 h-3.5 rounded border-zinc-700 bg-zinc-900 accent-zinc-200 cursor-pointer"
                        />
                      </td>

                      <td className="py-3 px-3">
                        <div className="font-medium text-zinc-200 group-hover:text-white transition">
                          {prospect.nombre}
                        </div>
                        <div className="text-[11px] text-zinc-400 line-clamp-1 italic" title={prospect.cargo_titular || prospect.cargo}>
                          {prospect.cargo_titular || prospect.cargo || 'Titular de LinkedIn'}
                        </div>
                      </td>

                      <td className="py-3 px-3">
                        <div className="flex items-center gap-1.5">
                          <Briefcase className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                          <span className="font-medium text-xs text-zinc-100 truncate max-w-[210px]" title={prospect.cargo_actual || prospect.cargo}>
                            {prospect.cargo_actual || prospect.cargo || 'Profesional / Decisor'}
                          </span>
                        </div>
                      </td>

                      <td className="py-3 px-3 text-zinc-300">
                        <div className="flex items-center gap-1.5">
                          <Building2 className="w-3.5 h-3.5 text-zinc-500 shrink-0" />
                          <span className="truncate max-w-xs">{prospect.institucion || 'Organización no declarada'}</span>
                        </div>
                      </td>

                      <td className="py-3 px-3 text-zinc-400 text-[11px]">
                        {prospect.ubicacion || 'Chile'}
                      </td>

                      <td className="py-3 px-3 font-mono text-[11px] text-zinc-400">
                        {prospect.grado_red || '2°/3°'}
                      </td>

                      <td className="py-3 px-3">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono border ${stateBadgeStyles}`}>
                          {prospect.estado === 'REUNION_AGENDADA' ? '📅 Cita Agendada' : prospect.estado}
                        </span>
                      </td>

                      <td className="py-3 px-4 text-right">
                        <div className="flex items-center justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
                          {prospect.url_perfil && (
                            <a
                              href={prospect.url_perfil}
                              target="_blank"
                              rel="noopener noreferrer"
                              title="Abrir perfil de LinkedIn"
                              className="p-1 rounded text-zinc-400 hover:text-white hover:bg-zinc-800 transition"
                            >
                              <ExternalLink className="w-3.5 h-3.5" />
                            </a>
                          )}
                          <button
                            onClick={() => setSelectedProspect(prospect)}
                            className="flex items-center gap-1 px-2 py-1 rounded-md bg-white/[0.04] hover:bg-white/[0.08] text-zinc-300 border border-white/[0.06] text-[11px] transition cursor-pointer"
                          >
                            <span>Ver</span>
                            <ChevronRight className="w-3 h-3" />
                          </button>
                          <button
                            onClick={(e) => handleDeleteSingleProspect(prospect, e)}
                            title="Eliminar de mi base de datos"
                            className="p-1 rounded text-zinc-500 hover:text-rose-400 hover:bg-rose-950/40 transition cursor-pointer"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Modal Lateral de Detalle */}
      {selectedProspect && (
        <LeadModal
          prospect={selectedProspect}
          onClose={() => setSelectedProspect(null)}
          onUpdated={loadData}
        />
      )}
    </div>
  );
}
