// Espacio dedicado a la Búsqueda directa y Extracción de prospectos en LinkedIn
import React, { useState, useEffect } from 'react';
import { 
  Search, 
  Sparkles, 
  Building2, 
  MapPin, 
  ExternalLink, 
  UserPlus, 
  CheckCircle2, 
  AlertCircle, 
  ChevronLeft, 
  ChevronRight, 
  ChevronsLeft, 
  ChevronsRight, 
  X, 
  Plus, 
  Layers, 
  Database, 
  RefreshCw, 
  Eye,
  History,
  CheckSquare,
  Square,
  Compass,
  Users,
  UserCheck,
  Send
} from 'lucide-react';
import { 
  fetchLeadLists, 
  triggerExtraction,
  extractNetworkLeads,
  importSelectedProspects,
  syncLeadWithLinkedIn 
} from '../../services/api';
import LeadModal from './LeadModal';
import NewListModal from '../Lists/NewListModal';
import { showToast } from '../Toast';

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

function getWindowedPages(current, total) {
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }
  if (current <= 4) {
    return [1, 2, 3, 4, 5, '...', total];
  }
  if (current >= total - 3) {
    return [1, '...', total - 4, total - 3, total - 2, total - 1, total];
  }
  return [1, '...', current - 1, current, current + 1, '...', total];
}

export default function ProspectsView({ onExtractionStarted, activeTenantWorkspace = '', onNavigateToTab = null }) {
  // Parámetros de búsqueda
  const [searchTerm, setSearchTerm] = useState('CEO Founder Chile');
  const [selectedPage, setSelectedPage] = useState(1);
  const [extracting, setExtracting] = useState(false);
  const [networkSourceMode, setNetworkSourceMode] = useState('all'); // 'all', 'connections', 'sent_invitations'
  const [networkLimit, setNetworkLimit] = useState(50); // 20, 50, 100, 200
  const [extractingNetwork, setExtractingNetwork] = useState(false);
  const [recentSearches, setRecentSearches] = useState(getStoredRecentSearches);

  // Listas de leads en el workspace
  const [leadLists, setLeadLists] = useState([]);

  // Resultados de búsqueda en LinkedIn (descubiertos en vivo)
  const [discoveredLeads, setDiscoveredLeads] = useState([]);
  const [selectedDiscoveredUrls, setSelectedDiscoveredUrls] = useState(new Set());
  const [hasSearched, setHasSearched] = useState(false);
  const [savedUrls, setSavedUrls] = useState(new Set());

  // Paginación de resultados descubiertos / extraídos
  const [resultsPage, setResultsPage] = useState(1);
  const [resultsPerPage, setResultsPerPage] = useState(20);

  // Modal para guardar en múltiples listas
  const [showSaveToListsModal, setShowSaveToListsModal] = useState(false);
  const [selectedTargetListIds, setSelectedTargetListIds] = useState(new Set());
  const [importingSelected, setImportingSelected] = useState(false);
  const [showNewListModal, setShowNewListModal] = useState(false);

  // Modal para ver detalle completo de un lead
  const [selectedProspectForModal, setSelectedProspectForModal] = useState(null);
  const [syncingLeadIds, setSyncingLeadIds] = useState(new Set());

  useEffect(() => {
    loadLists();
  }, [activeTenantWorkspace]);

  async function loadLists() {
    try {
      const lists = await fetchLeadLists(activeTenantWorkspace);
      setLeadLists(lists || []);
      if (lists && lists.length > 0) {
        setSelectedTargetListIds(new Set([lists[0].id]));
      }
    } catch (err) {
      console.error('Error cargando listas:', err);
    }
  }

  async function handleSyncLead(e, lead) {
    e.stopPropagation();
    if (!lead?.id) return;
    try {
      setSyncingLeadIds(prev => new Set(prev).add(lead.id));
      const res = await syncLeadWithLinkedIn(lead.id);
      if (res && res.lead) {
        setDiscoveredLeads(prev => prev.map(l => (l.id === lead.id || l.perfil_url === lead.perfil_url) ? {
          ...l,
          cargo_actual: res.lead.cargo_actual,
          institucion_actual: res.lead.institucion_actual,
          ubicacion: res.lead.ubicacion,
          nombre: res.lead.nombre,
        } : l));
      }
    } catch (err) {
      showToast(`Error sincronizando lead: ${err.message}`, 'error');
    } finally {
      setSyncingLeadIds(prev => {
        const next = new Set(prev);
        next.delete(lead.id);
        return next;
      });
    }
  }

  async function executeSearch(termToSearch, pageToSearch = 1) {
    const term = termToSearch || searchTerm;
    if (!term.trim()) {
      showToast('Ingresa un término o cargo para buscar en LinkedIn.', 'warning');
      return;
    }

    try {
      setExtracting(true);
      if (onExtractionStarted) onExtractionStarted();

      const res = await triggerExtraction(term, pageToSearch, null, false, activeTenantWorkspace);

      if (res.status === 'error') {
        showToast(`Error en búsqueda: ${res.mensaje || 'Error desconocido'}`, 'error');
        return;
      }

      if (res.status === 'warning') {
        showToast(res.mensaje || 'Búsqueda completada con advertencias.', 'warning');
        if (!res.leads || res.leads.length === 0) return;
      }

      const leads = res.leads || [];
      setDiscoveredLeads(leads);
      setResultsPage(1);
      setHasSearched(true);

      // Pre-seleccionar todos los perfiles que no existen aún en la base de datos
      const initialSelected = new Set();
      leads.forEach((l) => {
        if (!l.ya_existe && !savedUrls.has(l.perfil_url)) {
          initialSelected.add(l.perfil_url);
        }
      });
      // Si todos ya estaban registrados, pre-seleccionamos todos por si desea asociarlos a otra lista
      if (initialSelected.size === 0 && leads.length > 0) {
        leads.forEach(l => initialSelected.add(l.perfil_url));
      }
      setSelectedDiscoveredUrls(initialSelected);

      const updatedSearches = saveSearchTermToStorage(term);
      if (updatedSearches) setRecentSearches(updatedSearches);
    } catch (err) {
      showToast(`Error buscando prospectos en LinkedIn: ${err.message}`, 'error');
    } finally {
      setExtracting(false);
    }
  }

  async function handleExtractNetwork(sourceToExtract = null, limitToExtract = null) {
    const src = sourceToExtract || networkSourceMode;
    const limit = limitToExtract || networkLimit;
    try {
      setExtractingNetwork(true);
      if (onExtractionStarted) onExtractionStarted();

      const res = await extractNetworkLeads(src, limit, activeTenantWorkspace);

      if (res.status === 'error') {
        showToast(`Error extrayendo contactos: ${res.mensaje || 'Error desconocido'}`, 'error');
        return;
      }

      if (res.status === 'warning') {
        showToast(res.mensaje || 'Extracción completada con advertencias.', 'warning');
        if (!res.leads || res.leads.length === 0) return;
      }

      const leads = res.leads || [];
      setDiscoveredLeads(leads);
      setResultsPage(1);
      setHasSearched(true);

      // Pre-seleccionar todos los perfiles que no existen aún en la base de datos
      const initialSelected = new Set();
      leads.forEach((l) => {
        if (!l.ya_existe && !savedUrls.has(l.perfil_url)) {
          initialSelected.add(l.perfil_url);
        }
      });
      // Si todos ya estaban registrados, pre-seleccionamos todos por si desea asociarlos a otra lista
      if (initialSelected.size === 0 && leads.length > 0) {
        leads.forEach(l => initialSelected.add(l.perfil_url));
      }
      setSelectedDiscoveredUrls(initialSelected);
    } catch (err) {
      showToast(`Error extrayendo contactos de LinkedIn: ${err.message}`, 'error');
    } finally {
      setExtractingNetwork(false);
    }
  }

  function handleSearchSubmit(e) {
    if (e) e.preventDefault();
    setSelectedPage(1);
    executeSearch(searchTerm, 1);
  }

  async function handleGoToPage(pageNum) {
    if (pageNum === selectedPage && discoveredLeads.length > 0) return;
    setSelectedPage(pageNum);
    await executeSearch(searchTerm, pageNum);
  }

  function handleToggleDiscoveredLead(url) {
    setSelectedDiscoveredUrls((prev) => {
      const next = new Set(prev);
      if (next.has(url)) next.delete(url);
      else next.add(url);
      return next;
    });
  }

  function handleToggleSelectAllDiscovered() {
    if (selectedDiscoveredUrls.size === discoveredLeads.length) {
      setSelectedDiscoveredUrls(new Set());
    } else {
      setSelectedDiscoveredUrls(new Set(discoveredLeads.map((l) => l.perfil_url)));
    }
  }

  function handleOpenSaveModal() {
    const toImport = discoveredLeads.filter(l => selectedDiscoveredUrls.has(l.perfil_url));
    if (toImport.length === 0) {
      showToast('Selecciona al menos un prospecto para guardar en tus listas.', 'warning');
      return;
    }
    setShowSaveToListsModal(true);
  }

  function handleToggleTargetList(listId) {
    setSelectedTargetListIds((prev) => {
      const next = new Set(prev);
      if (next.has(listId)) {
        if (next.size > 1) next.delete(listId); // Mantener al menos una seleccionada
      } else {
        next.add(listId);
      }
      return next;
    });
  }

  async function handleConfirmSaveToLists() {
    const toImport = discoveredLeads.filter(l => selectedDiscoveredUrls.has(l.perfil_url));
    if (toImport.length === 0) return;

    if (selectedTargetListIds.size === 0) {
      showToast('Selecciona al menos una lista de destino.', 'warning');
      return;
    }

    try {
      setImportingSelected(true);
      const listIdsArray = Array.from(selectedTargetListIds);
      const res = await importSelectedProspects(toImport, listIdsArray, activeTenantWorkspace);

      const agregados = res.nuevos_importados ?? 0;
      const omitidos = res.duplicados_omitidos ?? 0;
      const totalAfectados = toImport.length;

      // Marcar URLs como guardadas
      setSavedUrls((prev) => {
        const next = new Set(prev);
        toImport.forEach((l) => next.add(l.perfil_url));
        return next;
      });

      showToast(
        `${totalAfectados} prospectos guardados en ${listIdsArray.length} lista(s) (${agregados} nuevos, ${omitidos} ya existentes).`,
        'success',
        onNavigateToTab
          ? { label: 'Ir a campañas', onClick: () => onNavigateToTab('secuencias') }
          : null,
        7000
      );

      setShowSaveToListsModal(false);
      setSelectedDiscoveredUrls(new Set());
      await loadLists();
    } catch (err) {
      showToast(`Error guardando prospectos: ${err.message}`, 'error');
    } finally {
      setImportingSelected(false);
    }
  }

  // Cálculos de paginación para la lista de prospectos descubiertos/extraídos
  const isNetworkView = discoveredLeads.some(l => l.tipo_origen);
  const useClientPagination = isNetworkView || discoveredLeads.length > resultsPerPage;

  const totalResultsPages = Math.ceil(discoveredLeads.length / resultsPerPage) || 1;
  const safePage = Math.min(Math.max(1, resultsPage), totalResultsPages);

  const displayedLeads = useClientPagination
    ? discoveredLeads.slice((safePage - 1) * resultsPerPage, safePage * resultsPerPage)
    : discoveredLeads;

  const currentPageUrls = displayedLeads.map(l => l.perfil_url);
  const selectedOnCurrentPage = currentPageUrls.filter(u => selectedDiscoveredUrls.has(u)).length;
  const isCurrentPageFullySelected = currentPageUrls.length > 0 && selectedOnCurrentPage === currentPageUrls.length;
  const isAllFullySelected = discoveredLeads.length > 0 && selectedDiscoveredUrls.size === discoveredLeads.length;

  function handleToggleCurrentPageSelection() {
    setSelectedDiscoveredUrls((prev) => {
      const next = new Set(prev);
      if (isCurrentPageFullySelected) {
        currentPageUrls.forEach(url => next.delete(url));
      } else {
        currentPageUrls.forEach(url => next.add(url));
      }
      return next;
    });
  }

  function handleToggleAllDiscoveredSelection() {
    if (isAllFullySelected) {
      setSelectedDiscoveredUrls(new Set());
    } else {
      setSelectedDiscoveredUrls(new Set(discoveredLeads.map((l) => l.perfil_url)));
    }
  }

  return (
    <div className="space-y-5 font-sans animate-fadeIn">
      {/* 1. Header de Sección */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-zinc-100 tracking-tight">
            1. Captar: Buscar prospectos
          </h2>
          <p className="text-xs text-zinc-300 mt-0.5">
            Encuentra decisores en LinkedIn por cargo o empresa y guárdalos en tus listas para contactarlos.
          </p>
        </div>
      </div>

      {/* 2. Barra de Búsqueda y Extracción */}
      <div className="p-4 rounded-xl bg-[#121316] border border-white/[0.08] space-y-3.5 shadow-xs">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-md bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-zinc-300 shrink-0">
              <Search className="w-3.5 h-3.5 text-zinc-300" />
            </div>
            <div>
              <h3 className="text-xs font-medium text-zinc-100">Buscador de LinkedIn</h3>
              <p className="text-xs text-zinc-400">
                Consulta perfiles por cargos, sectores o empresas objetivo
              </p>
            </div>
          </div>

          {/* Búsquedas recientes */}
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-xs text-zinc-400 mr-1 flex items-center gap-1">
              <History className="w-3.5 h-3.5 text-zinc-400" />
              Recientes:
            </span>
            {recentSearches.map((term) => (
              <button
                key={term}
                type="button"
                onClick={() => {
                  setSearchTerm(term);
                  setSelectedPage(1);
                  executeSearch(term, 1);
                }}
                className="px-2.5 py-1 rounded-md text-xs bg-[#0D0E12] hover:bg-zinc-800 text-zinc-300 hover:text-white border border-white/[0.08] transition cursor-pointer"
                title={`Buscar "${term}"`}
              >
                {term}
              </button>
            ))}
          </div>
        </div>

        {/* Formulario de búsqueda */}
        <form onSubmit={handleSearchSubmit} className="flex flex-col sm:flex-row items-center gap-2.5">
          <div className="relative flex-1 w-full">
            <Search className="w-4 h-4 text-zinc-500 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Ej: CEO Founder Chile, Gerente Comercial, Director de Operaciones..."
              className="w-full bg-[#0D0E12] border border-white/[0.08] pl-9 pr-3 py-2 rounded-lg text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 font-sans"
            />
          </div>

          <button
            type="submit"
            disabled={extracting || extractingNetwork}
            className="w-full sm:w-auto flex items-center justify-center gap-2 px-5 py-2 rounded-lg bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs shadow-sm transition cursor-pointer disabled:opacity-50 shrink-0"
          >
            <Search className={`w-3.5 h-3.5 ${extracting ? 'animate-spin' : ''}`} />
            <span>{extracting ? 'Buscando en LinkedIn...' : 'Buscar en LinkedIn'}</span>
          </button>
        </form>

        {/* Barra de Extracción Directa desde mi Red LinkedIn */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-3 border-t border-white/[0.06]">
          <div className="flex flex-wrap items-center gap-3">
            {/* Canal de extracción */}
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] text-zinc-400 font-medium flex items-center gap-1">
                <Users className="w-3.5 h-3.5 text-blue-400" />
                <span>Canal:</span>
              </span>
              <div className="inline-flex rounded-lg bg-[#0D0E12] p-0.5 border border-white/[0.08]">
                <button
                  type="button"
                  onClick={() => setNetworkSourceMode('all')}
                  className={`px-2.5 py-1 text-[11px] font-medium rounded-md transition cursor-pointer ${
                    networkSourceMode === 'all'
                      ? 'bg-zinc-800 text-white shadow-xs'
                      : 'text-zinc-400 hover:text-zinc-200'
                  }`}
                >
                  Todo (Conexiones + Invitaciones)
                </button>
                <button
                  type="button"
                  onClick={() => setNetworkSourceMode('connections')}
                  className={`px-2.5 py-1 text-[11px] font-medium rounded-md transition cursor-pointer ${
                    networkSourceMode === 'connections'
                      ? 'bg-zinc-800 text-white shadow-xs'
                      : 'text-zinc-400 hover:text-zinc-200'
                  }`}
                >
                  1º Grado (Conectados)
                </button>
                <button
                  type="button"
                  onClick={() => setNetworkSourceMode('sent_invitations')}
                  className={`px-2.5 py-1 text-[11px] font-medium rounded-md transition cursor-pointer ${
                    networkSourceMode === 'sent_invitations'
                      ? 'bg-zinc-800 text-white shadow-xs'
                      : 'text-zinc-400 hover:text-zinc-200'
                  }`}
                >
                  Invitaciones Enviadas
                </button>
              </div>
            </div>

            {/* Selector de Límite / Profundidad */}
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] text-zinc-400 font-medium">Límite:</span>
              <div className="inline-flex rounded-lg bg-[#0D0E12] p-0.5 border border-white/[0.08]">
                {[20, 50, 100, 200].map((qty) => (
                  <button
                    key={qty}
                    type="button"
                    onClick={() => setNetworkLimit(qty)}
                    className={`px-2.5 py-1 text-[11px] font-medium rounded-md transition cursor-pointer ${
                      networkLimit === qty
                        ? 'bg-blue-600 text-white shadow-xs'
                        : 'text-zinc-400 hover:text-zinc-200'
                    }`}
                    title={`Extraer hasta ${qty} contactos de la cola`}
                  >
                    {qty}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <button
            type="button"
            disabled={extracting || extractingNetwork}
            onClick={() => handleExtractNetwork(networkSourceMode, networkLimit)}
            className="w-full sm:w-auto flex items-center justify-center gap-2 px-4 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium text-xs shadow-xs transition cursor-pointer disabled:opacity-50 shrink-0"
            title={`Extraer hasta ${networkLimit} contactos desde tu perfil autenticado de LinkedIn en 1 clic`}
          >
            <Sparkles className={`w-3.5 h-3.5 ${extractingNetwork ? 'animate-spin' : ''}`} />
            <span>{extractingNetwork ? `Extrayendo ${networkLimit} contactos...` : `Extraer ${networkLimit} Contactos`}</span>
          </button>
        </div>
      </div>

      {/* 3. Panel de Resultados de Búsqueda */}
      {!hasSearched ? (
        /* Estado inicial vacío cuando no se ha ejecutado ninguna búsqueda */
        <div className="p-16 rounded-xl border border-white/[0.08] bg-[#121316] text-center space-y-4">
          <div className="w-12 h-12 rounded-2xl bg-zinc-900 border border-zinc-800 flex items-center justify-center mx-auto text-zinc-400 shadow-xs">
            <Compass className="w-6 h-6 text-zinc-400" />
          </div>
          <div className="space-y-1.5 max-w-md mx-auto">
            <h3 className="text-sm font-semibold text-zinc-100">
              Espacio de Búsqueda y Extracción de Prospectos
            </h3>
            <p className="text-xs text-zinc-400">
              Busca nuevos decisores en LinkedIn o extrae directamente los contactos e invitaciones que ya enviaste para agregarlos a tu base de datos.
            </p>
          </div>

          <div className="pt-2 flex items-center justify-center gap-2 flex-wrap">
            {DEFAULT_SEARCHES.slice(0, 3).map((term) => (
              <button
                key={term}
                onClick={() => {
                  setSearchTerm(term);
                  setSelectedPage(1);
                  executeSearch(term, 1);
                }}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#0D0E12] hover:bg-zinc-800 border border-white/[0.08] text-xs text-zinc-300 hover:text-white transition cursor-pointer"
              >
                <Search className="w-3 h-3 text-zinc-500" />
                <span>Buscar: {term}</span>
              </button>
            ))}
          </div>

          {/* Tarjeta de acción rápida: Extraer desde red propia */}
          <div className="mt-4 p-4 rounded-xl bg-blue-950/20 border border-blue-500/20 max-w-lg mx-auto flex flex-col sm:flex-row items-center justify-between gap-3 text-left">
            <div className="space-y-0.5">
              <div className="text-xs font-semibold text-zinc-100 flex items-center gap-1.5">
                <Users className="w-3.5 h-3.5 text-blue-400" />
                <span>¿Ya tienes contactos o invitaciones en LinkedIn?</span>
              </div>
              <p className="text-[11px] text-zinc-400">
                Extrae tus conexiones de 1º grado e invitaciones enviadas en un clic para incorporarlas a tu base de leads.
              </p>
            </div>
            <button
              type="button"
              disabled={extracting || extractingNetwork}
              onClick={() => handleExtractNetwork('all')}
              className="w-full sm:w-auto px-3.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium text-xs shrink-0 cursor-pointer shadow-xs transition flex items-center justify-center gap-1.5"
            >
              <Sparkles className={`w-3 h-3 ${extractingNetwork ? 'animate-spin' : ''}`} />
              <span>{extractingNetwork ? 'Extrayendo...' : 'Extraer de mi Red'}</span>
            </button>
          </div>
        </div>
      ) : (extracting || extractingNetwork) ? (
        /* Estado de carga durante la extracción */
        <div className="p-16 rounded-xl border border-white/[0.08] bg-[#121316] text-center space-y-3">
          <div className="w-7 h-7 border-2 border-blue-500 border-t-white rounded-full animate-spin mx-auto" />
          <p className="text-xs text-zinc-200 font-medium">
            {extractingNetwork ? 'Extrayendo contactos e invitaciones desde tu cuenta de LinkedIn...' : 'Buscando prospectos en LinkedIn...'}
          </p>
          <p className="text-[11px] text-zinc-500">
            {extractingNetwork ? 'Inspeccionando conexiones y solicitudes con ritmo humano seguro' : `Navegando página ${selectedPage} con ritmo humano seguro`}
          </p>
        </div>
      ) : discoveredLeads.length === 0 ? (
        /* Estado cuando no se encontraron perfiles en esa página */
        <div className="p-12 rounded-xl border border-white/[0.08] bg-[#121316] text-center space-y-3">
          <AlertCircle className="w-8 h-8 text-zinc-500 mx-auto" />
          <p className="text-xs text-zinc-300 font-medium">
            No se detectaron perfiles en la página {selectedPage} para "{searchTerm}".
          </p>
          <p className="text-[11px] text-zinc-500">
            Prueba ajustando el término o navegando a otra página de resultados.
          </p>
        </div>
      ) : (
        /* Resultados encontrados */
        <div className="rounded-xl border border-white/[0.08] bg-[#121316] shadow-xl overflow-hidden space-y-0 animate-fadeIn">
          {/* Header de la tabla de resultados */}
          <div className="p-4 border-b border-white/[0.06] flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-md bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-zinc-300 shrink-0">
                <Sparkles className="w-3.5 h-3.5 text-zinc-300" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-xs sm:text-sm font-semibold text-zinc-100">
                    {isNetworkView 
                      ? `Contactos de mi Red LinkedIn (${discoveredLeads.length} perfiles)` 
                      : `Resultados en LinkedIn (${discoveredLeads.length} perfiles)`}
                  </h3>
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-zinc-900 text-zinc-300 border border-white/[0.08]">
                    {useClientPagination ? `Pág. ${safePage} de ${totalResultsPages}` : `Página ${selectedPage}`}
                  </span>
                </div>
                <p className="text-[11px] text-zinc-400">
                  {isNetworkView
                    ? 'Revisa tus contactos e invitaciones y elige cuáles guardar en tus listas de NexusReach'
                    : 'Selecciona los prospectos que deseas agregar a una o más listas de leads'}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              {useClientPagination && (
                <button
                  type="button"
                  onClick={handleToggleCurrentPageSelection}
                  className="px-2.5 py-1.5 rounded-md bg-[#0D0E12] hover:bg-zinc-800 border border-white/[0.08] text-zinc-300 text-xs font-medium transition cursor-pointer"
                  title="Seleccionar o deseleccionar solo los prospectos visibles en la página actual"
                >
                  {isCurrentPageFullySelected ? 'Deseleccionar pág. actual' : `Seleccionar pág. actual (${selectedOnCurrentPage}/${displayedLeads.length})`}
                </button>
              )}

              <button
                type="button"
                onClick={handleToggleAllDiscoveredSelection}
                className="px-2.5 py-1.5 rounded-md bg-[#0D0E12] hover:bg-zinc-800 border border-white/[0.08] text-zinc-300 text-xs font-medium transition cursor-pointer"
                title="Seleccionar o deseleccionar todos los prospectos extraídos"
              >
                {isAllFullySelected ? 'Deseleccionar todos' : `Seleccionar todos (${discoveredLeads.length})`}
              </button>

              <button
                type="button"
                onClick={handleOpenSaveModal}
                disabled={selectedDiscoveredUrls.size === 0}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 text-xs font-semibold shadow-sm transition cursor-pointer disabled:opacity-40"
              >
                <UserPlus className="w-3.5 h-3.5" />
                <span>Guardar en Listas ({selectedDiscoveredUrls.size})</span>
              </button>
            </div>
          </div>

          {/* Listado de perfiles descubiertos */}
          <div className="divide-y divide-white/[0.04] max-h-[500px] overflow-y-auto">
            {displayedLeads.map((lead, idx) => {
              const isSelected = selectedDiscoveredUrls.has(lead.perfil_url);
              const isSaved = lead.ya_existe || savedUrls.has(lead.perfil_url);

              return (
                <div
                  key={lead.perfil_url || idx}
                  onClick={() => handleToggleDiscoveredLead(lead.perfil_url)}
                  className={`py-3 px-4 flex items-center justify-between gap-3 transition cursor-pointer ${
                    isSelected ? 'bg-zinc-800/40 border-l-2 border-l-white' : 'hover:bg-white/[0.02]'
                  }`}
                >
                  <div className="flex items-center gap-3.5 min-w-0">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => handleToggleDiscoveredLead(lead.perfil_url)}
                      onClick={(e) => e.stopPropagation()}
                      className="w-4 h-4 rounded border-zinc-700 bg-zinc-900 text-zinc-100 focus:ring-0 cursor-pointer accent-zinc-200 shrink-0"
                    />

                    {/* Avatar o Iniciales */}
                    {lead.avatar_url ? (
                      <img
                        src={lead.avatar_url}
                        alt={lead.nombre}
                        className="w-8 h-8 rounded-full object-cover border border-white/[0.08] shrink-0"
                      />
                    ) : (
                      <div className="w-8 h-8 rounded-full bg-zinc-800 border border-white/[0.08] flex items-center justify-center text-xs font-semibold text-zinc-300 shrink-0">
                        {lead.nombre ? lead.nombre.charAt(0).toUpperCase() : 'L'}
                      </div>
                    )}

                    <div className="min-w-0 space-y-0.5">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-semibold text-xs text-zinc-100 hover:text-white transition truncate">
                          {lead.nombre}
                        </span>

                        {/* Badges de Estado en Red */}
                        {lead.estado_origen === 'CONECTADO' || lead.estado === 'CONECTADO' ? (
                          <span className="text-[10px] px-1.5 py-0.2 rounded bg-emerald-950/60 text-emerald-400 border border-emerald-500/30 font-mono flex items-center gap-1 font-medium">
                            <UserCheck className="w-2.5 h-2.5" /> 1º Grado • Conectado
                          </span>
                        ) : lead.estado_origen === 'INVITACION_ENVIADA' || lead.estado === 'INVITACION_ENVIADA' ? (
                          <span className="text-[10px] px-1.5 py-0.2 rounded bg-blue-950/60 text-blue-400 border border-blue-500/30 font-mono flex items-center gap-1 font-medium">
                            <Send className="w-2.5 h-2.5" /> Invitación Enviada
                          </span>
                        ) : lead.grado_red ? (
                          <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-zinc-900 text-zinc-400 border border-white/[0.06]">
                            {lead.grado_red}
                          </span>
                        ) : null}

                        {lead.tiempo && (
                          <span className="text-[10px] text-zinc-400 font-mono">
                            {lead.tiempo}
                          </span>
                        )}

                        {isSaved && (
                          <span className="text-[10px] px-1.5 py-0.2 rounded bg-emerald-950/40 text-emerald-400 border border-emerald-500/20 font-mono">
                            ✓ En Base de Leads
                          </span>
                        )}
                        {/* Listas a las que pertenece */}
                        {isSaved && lead.listas && lead.listas.length > 0 && lead.listas.map((lst) => (
                          <span 
                            key={lst.id} 
                            className="text-[10px] px-1.5 py-0.2 rounded bg-blue-950/50 text-blue-300 border border-blue-500/30 font-mono flex items-center gap-1"
                            title={`Pertenece a la lista: ${lst.nombre}`}
                          >
                            <Layers className="w-2.5 h-2.5 text-blue-400" />
                            {lst.nombre}
                          </span>
                        ))}
                        {/* Secuencias en las que participa */}
                        {isSaved && lead.secuencias && lead.secuencias.length > 0 && lead.secuencias.map((seq) => (
                          <span 
                            key={seq.id} 
                            className="text-[10px] px-1.5 py-0.2 rounded bg-purple-950/50 text-purple-300 border border-purple-500/30 font-mono flex items-center gap-1"
                            title={`En secuencia: ${seq.nombre} (${seq.estado || 'Activa'})`}
                          >
                            <span className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse" />
                            {seq.nombre}
                          </span>
                        ))}
                      </div>

                      <div className="text-[11px] text-zinc-300 truncate max-w-lg">
                        {lead.cargo_actual || lead.cargo_titular || lead.cargo || 'Profesional / Decisor'}
                      </div>

                      <div className="flex items-center gap-3 text-[11px] text-zinc-500 truncate">
                        {(lead.institucion_actual || lead.institucion) && (
                          <span className="flex items-center gap-1 truncate text-zinc-400">
                            <Building2 className="w-3 h-3 text-zinc-500 shrink-0" />
                            <span className="truncate">{lead.institucion_actual || lead.institucion}</span>
                          </span>
                        )}
                        {lead.ubicacion && (
                          <span className="flex items-center gap-1 truncate">
                            <MapPin className="w-3 h-3 text-zinc-500 shrink-0" />
                            <span className="truncate">{lead.ubicacion}</span>
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0" onClick={(e) => e.stopPropagation()}>
                    {/* Botón de Sincronización en vivo si ya existe en la base */}
                    {isSaved && lead.id && (
                      <button
                        type="button"
                        onClick={(e) => handleSyncLead(e, lead)}
                        disabled={syncingLeadIds.has(lead.id)}
                        className="flex items-center gap-1 px-2.5 py-1 rounded bg-zinc-900 hover:bg-zinc-800 border border-white/[0.08] text-[11px] font-medium text-zinc-300 hover:text-white transition cursor-pointer disabled:opacity-40"
                        title="Sincronizar datos en vivo con LinkedIn"
                      >
                        <RefreshCw className={`w-3 h-3 ${syncingLeadIds.has(lead.id) ? 'animate-spin text-emerald-400' : 'text-zinc-400'}`} />
                        <span className="hidden md:inline">{syncingLeadIds.has(lead.id) ? 'Sincronizando...' : 'Sincronizar'}</span>
                      </button>
                    )}

                    {/* Botón para abrir la ficha completa del lead si ya existe */}
                    {isSaved && lead.id && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedProspectForModal(lead);
                        }}
                        className="flex items-center gap-1 px-2.5 py-1 rounded bg-zinc-900 hover:bg-zinc-800 border border-white/[0.08] text-[11px] font-medium text-zinc-300 hover:text-white transition cursor-pointer"
                        title="Ver ficha completa, notas e historial"
                      >
                        <Eye className="w-3 h-3 text-zinc-400" />
                        <span className="hidden md:inline">Ver Ficha</span>
                      </button>
                    )}

                    {lead.perfil_url && (
                      <a
                        href={lead.perfil_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="p-1.5 rounded hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition"
                        title="Ver perfil directo en LinkedIn"
                      >
                        <ExternalLink className="w-4 h-4" />
                      </a>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* 4. PAGINACIÓN / FOOTER */}
          <div className="p-3.5 bg-[#0D0E12] border-t border-white/[0.06] space-y-3">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 flex-wrap">
              <span className="text-xs text-zinc-400 font-mono">
                {useClientPagination
                  ? `Mostrando ${(safePage - 1) * resultsPerPage + 1} - ${Math.min(safePage * resultsPerPage, discoveredLeads.length)} de ${discoveredLeads.length} contactos`
                  : `Mostrando página ${selectedPage} de resultados`}
              </span>

              {useClientPagination ? (
                /* Paginación cliente para la extracción de red o lotes grandes */
                <div className="flex items-center gap-3 flex-wrap">
                  {/* Selector de items por página */}
                  <div className="flex items-center gap-1.5 text-xs text-zinc-400">
                    <span>Filas:</span>
                    <div className="inline-flex rounded-md bg-zinc-900 p-0.5 border border-white/[0.06]">
                      {[10, 20, 50].map((num) => (
                        <button
                          key={num}
                          type="button"
                          onClick={() => {
                            setResultsPerPage(num);
                            setResultsPage(1);
                          }}
                          className={`px-2 py-0.5 text-[11px] rounded transition cursor-pointer font-mono ${
                            resultsPerPage === num
                              ? 'bg-zinc-800 text-white font-medium'
                              : 'text-zinc-400 hover:text-zinc-200'
                          }`}
                        >
                          {num}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Botones de navegación */}
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      disabled={safePage <= 1}
                      onClick={() => setResultsPage(1)}
                      className="flex items-center gap-1 px-2 py-1 rounded bg-zinc-900 hover:bg-zinc-800 border border-white/[0.06] text-xs font-medium text-zinc-300 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition cursor-pointer"
                      title="Primera página"
                    >
                      <ChevronsLeft className="w-3.5 h-3.5" />
                    </button>

                    <button
                      type="button"
                      disabled={safePage <= 1}
                      onClick={() => setResultsPage(p => Math.max(1, p - 1))}
                      className="flex items-center gap-1 px-2.5 py-1 rounded bg-zinc-900 hover:bg-zinc-800 border border-white/[0.06] text-xs font-medium text-zinc-300 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition cursor-pointer"
                      title="Página anterior"
                    >
                      <ChevronLeft className="w-3.5 h-3.5" />
                      <span className="hidden sm:inline">Anterior</span>
                    </button>

                    <div className="flex items-center gap-1">
                      {getWindowedPages(safePage, totalResultsPages).map((p, idx) => {
                        if (p === '...') {
                          return (
                            <span key={`ellipsis-${idx}`} className="px-1 text-xs text-zinc-500 font-mono">
                              ...
                            </span>
                          );
                        }
                        const isCurrent = p === safePage;
                        return (
                          <button
                            key={p}
                            type="button"
                            onClick={() => setResultsPage(p)}
                            className={`w-7 h-7 rounded text-xs font-mono font-medium transition cursor-pointer flex items-center justify-center ${
                              isCurrent
                                ? 'bg-white text-zinc-950 font-bold shadow-xs'
                                : 'bg-zinc-900/60 hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 border border-white/[0.04]'
                            }`}
                          >
                            {p}
                          </button>
                        );
                      })}
                    </div>

                    <button
                      type="button"
                      disabled={safePage >= totalResultsPages}
                      onClick={() => setResultsPage(p => Math.min(totalResultsPages, p + 1))}
                      className="flex items-center gap-1 px-2.5 py-1 rounded bg-zinc-900 hover:bg-zinc-800 border border-white/[0.06] text-xs font-medium text-zinc-300 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition cursor-pointer"
                      title="Página siguiente"
                    >
                      <span className="hidden sm:inline">Siguiente</span>
                      <ChevronRight className="w-3.5 h-3.5" />
                    </button>

                    <button
                      type="button"
                      disabled={safePage >= totalResultsPages}
                      onClick={() => setResultsPage(totalResultsPages)}
                      className="flex items-center gap-1 px-2 py-1 rounded bg-zinc-900 hover:bg-zinc-800 border border-white/[0.06] text-xs font-medium text-zinc-300 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition cursor-pointer"
                      title="Última página"
                    >
                      <ChevronsRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ) : (
                /* Paginación remota para búsqueda en vivo en LinkedIn */
                <div className="flex items-center gap-1 flex-wrap">
                  <button
                    type="button"
                    disabled={selectedPage <= 1 || extracting}
                    onClick={() => handleGoToPage(1)}
                    className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-zinc-900 hover:bg-zinc-800 border border-white/[0.06] text-xs font-medium text-zinc-300 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition cursor-pointer"
                    title="Ir a la primera página"
                  >
                    <ChevronsLeft className="w-3.5 h-3.5" />
                    <span className="hidden sm:inline">Primera</span>
                  </button>

                  <button
                    type="button"
                    disabled={selectedPage <= 1 || extracting}
                    onClick={() => handleGoToPage(selectedPage - 1)}
                    className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-zinc-900 hover:bg-zinc-800 border border-white/[0.06] text-xs font-medium text-zinc-300 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition cursor-pointer"
                    title="Página anterior"
                  >
                    <ChevronLeft className="w-3.5 h-3.5" />
                    <span className="hidden sm:inline">Anterior</span>
                  </button>

                  <div className="flex items-center gap-1">
                    {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((num) => {
                      const isCurrent = num === selectedPage;
                      return (
                        <button
                          key={num}
                          type="button"
                          disabled={extracting}
                          onClick={() => handleGoToPage(num)}
                          className={`w-7 h-7 rounded-md text-xs font-mono font-medium transition cursor-pointer flex items-center justify-center ${
                            isCurrent
                              ? 'bg-white text-zinc-950 font-bold shadow-xs'
                              : 'bg-zinc-900/60 hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 border border-white/[0.04]'
                          }`}
                        >
                          {num}
                        </button>
                      );
                    })}
                  </div>

                  <button
                    type="button"
                    disabled={selectedPage >= 10 || extracting}
                    onClick={() => handleGoToPage(selectedPage + 1)}
                    className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-zinc-900 hover:bg-zinc-800 border border-white/[0.06] text-xs font-medium text-zinc-300 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition cursor-pointer"
                    title="Página siguiente"
                  >
                    <span className="hidden sm:inline">Siguiente</span>
                    <ChevronRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
            </div>

            {/* Fila secundaria si es extracción de red: ampliar extracción */}
            {isNetworkView && (
              <div className="pt-2 border-t border-white/[0.04] flex items-center justify-between gap-3 text-xs text-zinc-400">
                <span className="text-[11px] text-zinc-500">¿Quieres extraer un lote mayor directamente desde LinkedIn?</span>
                <div className="flex items-center gap-1.5">
                  {[20, 50, 100, 200].map((qty) => (
                    <button
                      key={qty}
                      type="button"
                      disabled={extractingNetwork}
                      onClick={() => {
                        setNetworkLimit(qty);
                        handleExtractNetwork(networkSourceMode, qty);
                      }}
                      className={`px-2 py-0.5 text-[11px] rounded border transition cursor-pointer ${
                        networkLimit === qty
                          ? 'bg-blue-600 border-blue-500 text-white font-medium shadow-xs'
                          : 'bg-zinc-900 border-white/[0.08] text-zinc-300 hover:text-white'
                      }`}
                      title={`Extraer hasta ${qty} contactos de LinkedIn`}
                    >
                      {qty}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* MODAL: GUARDAR EN UNA O MÚLTIPLES LISTAS DE LEADS A LA VEZ */}
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
                    Guardar en Listas de Leads
                  </h3>
                  <p className="text-[11px] text-zinc-400">
                    Selecciona una o varias listas de destino para estos {selectedDiscoveredUrls.size} prospectos
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
                <span className="text-xs font-medium text-zinc-300">Listas disponibles en tu workspace:</span>
                <button
                  type="button"
                  onClick={() => setShowNewListModal(true)}
                  className="text-xs text-zinc-300 hover:text-white flex items-center gap-1 font-medium cursor-pointer"
                >
                  <Plus className="w-3 h-3" />
                  <span>Crear nueva lista</span>
                </button>
              </div>

              {leadLists.length === 0 ? (
                <div className="p-6 text-center text-zinc-500 text-xs border border-white/[0.06] rounded-lg space-y-2">
                  <p>Aún no tienes listas creadas.</p>
                  <button
                    onClick={() => setShowNewListModal(true)}
                    className="px-3 py-1.5 rounded-md bg-white text-zinc-950 font-medium text-xs cursor-pointer"
                  >
                    Crear primera lista
                  </button>
                </div>
              ) : (
                <div className="space-y-1.5">
                  {leadLists.map((list) => {
                    const isChecked = selectedTargetListIds.has(list.id);
                    const connectedSeqsCount = list.secuencias_conectadas ? list.secuencias_conectadas.length : 0;

                    return (
                      <div
                        key={list.id}
                        onClick={() => handleToggleTargetList(list.id)}
                        className={`p-3 rounded-lg border transition flex items-center justify-between gap-3 cursor-pointer ${
                          isChecked
                            ? 'bg-zinc-800/60 border-white/[0.18]'
                            : 'bg-zinc-900/40 border-white/[0.06] hover:border-white/[0.12]'
                        }`}
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={() => handleToggleTargetList(list.id)}
                            onClick={(e) => e.stopPropagation()}
                            className="w-4 h-4 rounded border-zinc-700 bg-zinc-900 text-zinc-100 focus:ring-0 cursor-pointer accent-zinc-200 shrink-0"
                          />
                          <div className="min-w-0">
                            <div className="font-medium text-xs text-zinc-200 truncate">
                              {list.nombre}
                            </div>
                            {list.descripcion && (
                              <p className="text-[11px] text-zinc-400 truncate max-w-xs mt-0.5">
                                {list.descripcion}
                              </p>
                            )}
                          </div>
                        </div>

                        <div className="flex items-center gap-2 shrink-0">
                          {connectedSeqsCount > 0 && (
                            <span className="text-[10px] px-1.5 py-0.2 rounded bg-emerald-950/40 text-emerald-400 border border-emerald-500/20 font-mono">
                              ⚡ {connectedSeqsCount} {connectedSeqsCount === 1 ? 'secuencia' : 'secuencias'}
                            </span>
                          )}
                          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-zinc-900 text-zinc-400 border border-white/[0.06]">
                            {list.total_leads || 0} leads
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="pt-3 border-t border-white/[0.06] flex items-center justify-between gap-2">
              <span className="text-[11px] text-zinc-400 font-mono">
                {selectedTargetListIds.size} {selectedTargetListIds.size === 1 ? 'lista elegida' : 'listas elegidas'}
              </span>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setShowSaveToListsModal(false)}
                  className="px-3 py-1.5 rounded-md text-xs font-medium text-zinc-400 hover:text-zinc-200 cursor-pointer"
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  onClick={handleConfirmSaveToLists}
                  disabled={importingSelected || selectedTargetListIds.size === 0 || leadLists.length === 0}
                  className="px-4 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 text-xs font-semibold shadow-sm transition cursor-pointer disabled:opacity-40"
                >
                  {importingSelected 
                    ? 'Guardando...' 
                    : `Guardar en ${selectedTargetListIds.size} ${selectedTargetListIds.size === 1 ? 'Lista' : 'Listas'}`}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal para crear una nueva lista de prospectos */}
      {showNewListModal && (
        <NewListModal
          onClose={() => setShowNewListModal(false)}
          onCreated={async () => {
            setShowNewListModal(false);
            await loadLists();
          }}
          activeTenantWorkspace={activeTenantWorkspace}
        />
      )}

      {/* Modal de Detalle de Lead */}
      {selectedProspectForModal && (
        <LeadModal
          prospect={selectedProspectForModal}
          onClose={() => setSelectedProspectForModal(null)}
          onUpdated={() => {}}
        />
      )}
    </div>
  );
}
