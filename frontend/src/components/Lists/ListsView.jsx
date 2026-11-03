// Vista de gestión de listas de prospectos, inspección profunda de leads y secuencias conectadas
import React, { useState, useEffect } from 'react';
import { 
  ListFilter, 
  Plus, 
  Search, 
  Layers, 
  GitFork, 
  Zap, 
  Database, 
  ExternalLink,
  ChevronRight,
  Clock,
  ArrowLeft,
  Trash2,
  Unlink,
  Link2,
  User,
  Building2,
  MapPin,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Sparkles,
  Filter,
  Eye,
  UserX,
  Pause,
  Play,
  Check,
  ShieldCheck
} from 'lucide-react';
import { 
  fetchLeadLists, 
  fetchLeadListDetail, 
  deleteLeadList, 
  connectListToSequence, 
  disconnectListFromSequence, 
  removeLeadFromList,
  fetchSequences,
  syncLeadWithLinkedIn,
  startListExtraction,
  stopListExtraction,
  updateLeadList,
  resolveLeadEmail,
  batchResolveLeadEmails
} from '../../services/api';
import NewListModal from './NewListModal';
import LeadModal from '../Prospects/LeadModal';
import UnifiedLeadsTable from '../Prospects/UnifiedLeadsTable';

export default function ListsView({ 
  onSelectSequence, 
  onNavigateToSearch,
  activeTenantWorkspace = '' 
}) {
  const [lists, setLists] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterState, setFilterState] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [showNewModal, setShowNewModal] = useState(false);

  // Estado para la vista en detalle de una lista seleccionada
  const [selectedListId, setSelectedListId] = useState(null);
  const [listDetail, setListDetail] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [detailSearchQuery, setDetailSearchQuery] = useState('');
  const [detailFilterStatus, setDetailFilterStatus] = useState('');
  const [selectedLeadForModal, setSelectedLeadForModal] = useState(null);

  // Modal para conectar secuencia a la lista
  const [showConnectSeqModal, setShowConnectSeqModal] = useState(false);
  const [availableSequences, setAvailableSequences] = useState([]);
  const [loadingSequences, setLoadingSequences] = useState(false);
  const [selectedSeqToConnect, setSelectedSeqToConnect] = useState('');
  const [actionInProgress, setActionInProgress] = useState(false);
  const [syncingLeadIds, setSyncingLeadIds] = useState(new Set());
  const [selectedLeadIds, setSelectedLeadIds] = useState(new Set());
  const [resolvingLeadIds, setResolvingLeadIds] = useState(new Set());
  const [isBatchResolvingEmail, setIsBatchResolvingEmail] = useState(false);
  const [extractionLoading, setExtractionLoading] = useState(false);
  const [deletingListId, setDeletingListId] = useState(null);

  useEffect(() => {
    loadLists();
  }, [activeTenantWorkspace]);

  useEffect(() => {
    if (selectedListId) {
      loadListDetail(selectedListId);
    } else {
      setListDetail(null);
    }
  }, [selectedListId]);

  // Polling automático cuando la extracción está activamente en ejecución
  useEffect(() => {
    if (!selectedListId) return;
    if (listDetail?.extrayendo_activo) {
      const interval = setInterval(async () => {
        try {
          const detail = await fetchLeadListDetail(selectedListId);
          if (detail) {
            setListDetail(detail);
            setLists((prev) => prev.map((l) => (l.id === selectedListId ? { ...l, ...detail } : l)));
          }
        } catch (e) {
          console.error('Error actualizando progreso de extracción:', e);
        }
      }, 3000);
      return () => clearInterval(interval);
    }
  }, [selectedListId, listDetail?.extrayendo_activo]);

  async function loadLists() {
    try {
      setLoading(true);
      const data = await fetchLeadLists(activeTenantWorkspace);
      setLists(data || []);
    } catch (err) {
      console.error('Error cargando listas de leads:', err);
    } finally {
      setLoading(false);
    }
  }

  async function loadListDetail(listId) {
    try {
      setLoadingDetail(true);
      const detail = await fetchLeadListDetail(listId);
      setListDetail(detail);
    } catch (err) {
      console.error(`Error cargando detalle de lista ${listId}:`, err);
      alert(`No se pudo cargar el detalle de la lista: ${err.message}`);
      setSelectedListId(null);
    } finally {
      setLoadingDetail(false);
    }
  }

  async function handleDeleteList(listId, listName, e) {
    if (e) e.stopPropagation();
    const confirmed = window.confirm(
      `¿Estás seguro de eliminar permanentemente la lista "${listName || listId}"?\n\n` +
      `• Se desvinculará de las secuencias asociadas.\n` +
      `• Los prospectos pertenecientes a esta lista no serán borrados de la base de datos general.\n\n` +
      `Esta acción no se puede deshacer.`
    );
    if (!confirmed) return;

    try {
      setDeletingListId(listId);
      setActionInProgress(true);
      await deleteLeadList(listId);
      if (selectedListId === listId) {
        setSelectedListId(null);
      }
      await loadLists();
    } catch (err) {
      alert(`Error eliminando lista: ${err.message}`);
    } finally {
      setDeletingListId(null);
      setActionInProgress(false);
    }
  }

  async function handleRemoveLead(leadId, leadName, e) {
    if (e) e.stopPropagation();
    if (!selectedListId) return;

    const confirmed = window.confirm(`¿Quitar a "${leadName}" de esta lista?\nEl prospecto seguirá existiendo en el directorio general.`);
    if (!confirmed) return;

    try {
      setActionInProgress(true);
      await removeLeadFromList(selectedListId, leadId);
      // Actualizar estado local inmediatamente
      setListDetail((prev) => {
        if (!prev) return null;
        const updatedLeads = (prev.leads || []).filter((l) => l.id !== leadId);
        return {
          ...prev,
          leads: updatedLeads,
          total_leads: updatedLeads.length
        };
      });
      // Actualizar contador en la lista general en segundo plano
      setLists((prev) =>
        prev.map((l) =>
          l.id === selectedListId
            ? { ...l, total_leads: Math.max(0, (l.total_leads || 1) - 1) }
            : l
        )
      );
    } catch (err) {
      alert(`Error quitando prospecto de la lista: ${err.message}`);
    } finally {
      setActionInProgress(false);
    }
  }

  async function handleOpenConnectSequence() {
    try {
      setLoadingSequences(true);
      setShowConnectSeqModal(true);
      const seqs = await fetchSequences(activeTenantWorkspace);
      // Filtrar aquellas que ya están conectadas
      const connectedIds = new Set((listDetail?.secuencias_conectadas || []).map((s) => s.id));
      const candidates = (seqs || []).filter((s) => !connectedIds.has(s.id));
      setAvailableSequences(candidates);
      if (candidates.length > 0) {
        setSelectedSeqToConnect(candidates[0].id);
      } else {
        setSelectedSeqToConnect('');
      }
    } catch (err) {
      alert(`Error obteniendo secuencias: ${err.message}`);
    } finally {
      setLoadingSequences(false);
    }
  }

  async function handleConfirmConnectSequence() {
    if (!selectedSeqToConnect || !selectedListId) return;
    try {
      setActionInProgress(true);
      await connectListToSequence(selectedListId, selectedSeqToConnect);
      setShowConnectSeqModal(false);
      await loadListDetail(selectedListId);
      await loadLists();
    } catch (err) {
      alert(`Error conectando secuencia a la lista: ${err.message}`);
    } finally {
      setActionInProgress(false);
    }
  }

  async function handleDisconnectSequence(seqId, seqName, e) {
    if (e) e.stopPropagation();
    if (!selectedListId) return;

    const confirmed = window.confirm(`¿Desvincular la secuencia "${seqName}" de esta lista?\nLos prospectos nuevos que ingresen ya no se enrolarán automáticamente a este flujo.`);
    if (!confirmed) return;

    try {
      setActionInProgress(true);
      await disconnectListFromSequence(selectedListId, seqId);
      await loadListDetail(selectedListId);
      await loadLists();
    } catch (err) {
      alert(`Error desvinculando secuencia: ${err.message}`);
    } finally {
      setActionInProgress(false);
    }
  }

  function handleLeadUpdated(updatedLead) {
    if (!updatedLead) return;
    setListDetail((prev) => {
      if (!prev) return null;
      if (updatedLead._deleted) {
        const filtered = (prev.leads || []).filter((l) => l.id !== updatedLead.id);
        return { ...prev, leads: filtered, total_leads: filtered.length };
      }
      const updatedList = (prev.leads || []).map((l) => (l.id === updatedLead.id ? { ...l, ...updatedLead } : l));
      return { ...prev, leads: updatedList };
    });
  }

  async function handleSyncSingleLead(lead, e) {
    if (e) e.stopPropagation();
    if (!lead?.id) return;

    try {
      setSyncingLeadIds((prev) => new Set(prev).add(lead.id));
      const res = await syncLeadWithLinkedIn(lead.id);
      if (res && res.lead) {
        const updated = res.lead;
        setListDetail((prev) => {
          if (!prev) return null;
          const updatedLeads = (prev.leads || []).map((l) =>
            l.id === lead.id
              ? {
                  ...l,
                  ...updated,
                  cargo: updated.cargo_actual || updated.cargo_titular || l.cargo,
                  cargo_actual: updated.cargo_actual || l.cargo_actual,
                  cargo_titular: updated.cargo_titular || l.cargo_titular,
                  institucion: updated.institucion_actual || l.institucion,
                  institucion_actual: updated.institucion_actual || l.institucion_actual,
                  ubicacion: updated.ubicacion || l.ubicacion,
                  grado_red: updated.grado_red || l.grado_red,
                }
              : l
          );
          return {
            ...prev,
            leads: updatedLeads,
            leads_extraidos: updatedLeads.filter(
              (l) => l.cargo_actual && l.cargo_actual !== 'No determinado'
            ).length,
          };
        });
      }
    } catch (err) {
      alert(`Error sincronizando lead con LinkedIn: ${err.message}`);
    } finally {
      setSyncingLeadIds((prev) => {
        const next = new Set(prev);
        next.delete(lead.id);
        return next;
      });
    }
  }

  function handleToggleLead(leadId) {
    setSelectedLeadIds((prev) => {
      const next = new Set(prev);
      if (next.has(leadId)) next.delete(leadId);
      else next.add(leadId);
      return next;
    });
  }

  function handleToggleSelectAll(leadsToSelect) {
    const list = leadsToSelect || [];
    if (selectedLeadIds.size === list.length && list.length > 0) {
      setSelectedLeadIds(new Set());
    } else {
      setSelectedLeadIds(new Set(list.map((l) => l.id)));
    }
  }

  async function handleResolveSingleEmail(e, lead) {
    if (e && e.stopPropagation) e.stopPropagation();
    if (!lead?.id) return;
    try {
      setResolvingLeadIds((prev) => new Set(prev).add(lead.id));
      const res = await resolveLeadEmail(lead.id, true);
      if (res && res.email) {
        setListDetail((prev) => {
          if (!prev) return null;
          return {
            ...prev,
            leads: (prev.leads || []).map((l) =>
              l.id === lead.id
                ? {
                    ...l,
                    email: res.email,
                    email_directo: res.email,
                    email_extracted: res.email,
                    email_source: res.source,
                    email_status: res.status
                  }
                : l
            )
          };
        });
      } else {
        alert(res?.motivo || 'No se localizó correo verificado para este prospecto.');
      }
    } catch (err) {
      alert(`Error resolviendo correo: ${err.message}`);
    } finally {
      setResolvingLeadIds((prev) => {
        const next = new Set(prev);
        next.delete(lead.id);
        return next;
      });
    }
  }

  async function handleBatchResolveEmails() {
    if (selectedLeadIds.size === 0) return;
    setIsBatchResolvingEmail(true);
    try {
      const res = await batchResolveLeadEmails(Array.from(selectedLeadIds), true);
      alert(`Resolución en cascada finalizada: ${res?.resueltos || 0} correos resueltos, ${res?.no_encontrados || 0} no localizados.`);
      if (selectedListId) await loadListDetail(selectedListId);
    } catch (err) {
      alert(`Error en resolución masiva: ${err.message}`);
    } finally {
      setIsBatchResolvingEmail(false);
    }
  }

  async function handleToggleExtraction() {
    if (!selectedListId || !listDetail) return;
    const isExtracting = Boolean(listDetail.extrayendo_activo);
    try {
      setExtractionLoading(true);
      if (isExtracting) {
        await stopListExtraction(selectedListId);
        setListDetail((prev) => (prev ? { ...prev, extrayendo_activo: false } : null));
        setLists((prev) => prev.map((l) => (l.id === selectedListId ? { ...l, extrayendo_activo: false } : l)));
      } else {
        const res = await startListExtraction(selectedListId);
        if (res && res.completado) {
          alert(res.mensaje || 'Todos los prospectos ya tienen sus datos extraídos.');
        }
        await loadListDetail(selectedListId);
        await loadLists();
      }
    } catch (err) {
      alert(`Error al gestionar la extracción de la lista: ${err.message}`);
    } finally {
      setExtractionLoading(false);
    }
  }

  // ============================================================
  // RENDER: VISTA EN DETALLE DE UNA LISTA PINCHADA
  // ============================================================
  if (selectedListId) {
    if (loadingDetail || !listDetail) {
      return (
        <div className="space-y-6 font-sans animate-fadeIn">
          <button
            onClick={() => setSelectedListId(null)}
            className="flex items-center gap-2 text-xs font-medium text-zinc-400 hover:text-zinc-100 transition cursor-pointer"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>Volver a Listas de Leads</span>
          </button>
          <div className="p-16 rounded-xl border border-white/[0.08] bg-[#121316] text-center space-y-3">
            <div className="w-6 h-6 border-2 border-zinc-500 border-t-white rounded-full animate-spin mx-auto" />
            <p className="text-xs text-zinc-400">Cargando prospectos y secuencias de la lista...</p>
          </div>
        </div>
      );
    }

    const connectedSeqs = listDetail.secuencias_conectadas || [];
    const allLeads = listDetail.leads || [];
    const isExtracting = Boolean(listDetail.extrayendo_activo);
    const totalLeadsCount = listDetail.total_leads || allLeads.length;
    const extractedCount = listDetail.leads_extraidos !== undefined ? listDetail.leads_extraidos : 0;
    const pendingCount = Math.max(0, totalLeadsCount - extractedCount);
    const allExtracted = totalLeadsCount > 0 && pendingCount === 0;

    // Filtros de leads internos
    const filteredDetailLeads = allLeads.filter((l) => {
      const matchesSearch = detailSearchQuery
        ? (l.nombre && l.nombre.toLowerCase().includes(detailSearchQuery.toLowerCase())) ||
          (l.cargo && l.cargo.toLowerCase().includes(detailSearchQuery.toLowerCase())) ||
          (l.institucion && l.institucion.toLowerCase().includes(detailSearchQuery.toLowerCase()))
        : true;

      const matchesStatus = detailFilterStatus
        ? l.estado === detailFilterStatus
        : true;

      return matchesSearch && matchesStatus;
    });

    const statusCounts = {
      total: allLeads.length,
      en_cola: allLeads.filter((l) => l.estado === 'EN_COLA' || !l.estado).length,
      contactados: allLeads.filter((l) => l.estado === 'INVITACION_ENVIADA' || l.estado === 'CONTACTADO' || l.estado === 'EN_SECUENCIA').length,
      conectados: allLeads.filter((l) => l.estado === 'CONECTADO' || l.estado === 'REUNION_AGENDADA').length,
    };

    const badgeClasses = {
      ACTIVA: 'bg-emerald-950/30 text-emerald-400 border-emerald-500/20',
      EXTRAYENDO: 'bg-cyan-950/30 text-cyan-400 border-cyan-500/20',
      DETENIDA: 'bg-white/[0.03] text-zinc-400 border-white/[0.08]',
    }[isExtracting ? 'EXTRAYENDO' : listDetail.estado] || 'bg-white/[0.04] text-zinc-400 border-white/[0.08]';

    return (
      <div className="space-y-6 font-sans animate-fadeIn">
        {/* Barra superior de navegación interna */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.06]">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSelectedListId(null)}
              className="p-2 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-white/[0.08] text-zinc-300 hover:text-white transition cursor-pointer"
              title="Volver a todas las listas"
            >
              <ArrowLeft className="w-4 h-4" />
            </button>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-semibold text-zinc-100 tracking-tight">
                  {listDetail.nombre}
                </h1>
                {isExtracting && (
                  <span className="flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-mono border bg-cyan-950/40 text-cyan-300 border-cyan-500/30">
                    <RefreshCw className="w-2.5 h-2.5 animate-spin" />
                    <span>EXTRAYENDO</span>
                    <span className="text-zinc-500">&bull;</span>
                    <span>Antiban Activo (8-14s)</span>
                  </span>
                )}
              </div>
              <p className="text-xs text-zinc-400 mt-0.5">
                {listDetail.descripcion || 'Lista de prospección segmentada para campañas multicanal'}
              </p>
            </div>
          </div>

          {/* Botones de acción rápida */}
          <div className="flex items-center gap-2 flex-wrap">
            {/* Control de Extracción por Demanda */}
            {isExtracting ? (
              <button
                onClick={handleToggleExtraction}
                disabled={extractionLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-amber-500/15 hover:bg-amber-500/25 text-amber-300 border border-amber-500/30 font-medium text-xs transition cursor-pointer"
                title="Detener la extracción de datos de leads"
              >
                <Pause className="w-3.5 h-3.5" />
                <span>{extractionLoading ? 'Deteniendo...' : 'Detener Extracción'}</span>
              </button>
            ) : allExtracted ? (
              <div
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-emerald-950/30 text-emerald-300 border border-emerald-500/30 font-medium text-xs font-mono shadow-xs"
                title="Todos los prospectos de esta lista ya tienen sus datos extraídos y verificados"
              >
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                <span>Datos Completos ({extractedCount}/{totalLeadsCount})</span>
              </div>
            ) : (
              <button
                onClick={handleToggleExtraction}
                disabled={extractionLoading || totalLeadsCount === 0}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-cyan-950/40 hover:bg-cyan-900/50 text-cyan-200 border border-cyan-500/30 font-medium text-xs transition cursor-pointer shadow-xs disabled:opacity-40"
                title="Extrae cargo actual, empresa y ubicación de los prospectos pendientes con pausas antiban"
              >
                <Zap className="w-3.5 h-3.5 text-cyan-400" />
                <span>{extractionLoading ? 'Iniciando...' : (pendingCount > 0 ? `Extraer Datos (${pendingCount} pendientes)` : 'Extraer Datos de Leads')}</span>
              </button>
            )}

            {onNavigateToSearch && (
              <button
                onClick={() => onNavigateToSearch(listDetail.termino_busqueda)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-zinc-900 hover:bg-zinc-800 border border-white/[0.08] text-zinc-200 hover:text-white font-medium text-xs transition cursor-pointer"
              >
                <Search className="w-3.5 h-3.5 text-zinc-400" />
                <span>Buscar Prospectos</span>
              </button>
            )}
            <button
              onClick={handleOpenConnectSequence}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs shadow-sm transition cursor-pointer"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Conectar Secuencia</span>
            </button>
            <button
              onClick={(e) => handleDeleteList(listDetail.id, listDetail.nombre, e)}
              disabled={actionInProgress}
              className="p-2 rounded-md hover:bg-red-950/30 text-zinc-400 hover:text-red-400 border border-transparent hover:border-red-500/20 transition cursor-pointer"
              title="Eliminar esta lista"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Banner de Estado de Extracción en Vivo */}
        {isExtracting && (
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3.5 rounded-xl bg-cyan-950/25 border border-cyan-500/30 shadow-sm animate-fadeIn">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-cyan-900/40 border border-cyan-500/40 flex items-center justify-center shrink-0">
                <RefreshCw className="w-4 h-4 text-cyan-300 animate-spin" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-cyan-100">
                    Extracción de Datos en Progreso
                  </span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-900/60 text-cyan-300 font-mono">
                    Antiban Activo (8-14s entre perfiles)
                  </span>
                </div>
                <p className="text-[11px] text-cyan-300/80 mt-0.5">
                  Extrayendo cargo actual, empresa u organización y zona geográfica. Al completarse, los leads quedarán listos para sus secuencias.
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <div className="text-right">
                <span className="text-[10px] text-cyan-400 block font-mono">Progreso Verificado</span>
                <span className="text-sm font-semibold font-mono text-white">
                  {extractedCount} / {totalLeadsCount} leads
                </span>
              </div>
              <button
                onClick={handleToggleExtraction}
                disabled={extractionLoading}
                className="px-2.5 py-1 rounded bg-cyan-900/40 hover:bg-cyan-900/70 text-cyan-200 border border-cyan-500/30 text-[11px] font-medium transition cursor-pointer"
              >
                Detener
              </button>
            </div>
          </div>
        )}

        {/* Banner si todos los datos ya están extraídos */}
        {!isExtracting && allExtracted && (
          <div className="flex items-center justify-between p-3 rounded-xl bg-emerald-950/20 border border-emerald-500/20 text-xs text-emerald-300 animate-fadeIn">
            <div className="flex items-center gap-2.5">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>
                Todos los <strong className="text-white font-medium">{totalLeadsCount} prospectos</strong> de esta lista tienen cargo, empresa y ubicación verificados en vivo.
              </span>
            </div>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-900/40 border border-emerald-500/30 text-emerald-400">
              ✓ Listos para Secuencias
            </span>
          </div>
        )}

        {/* Banner informativo si hay prospectos pendientes de extracción */}
        {!isExtracting && !allExtracted && pendingCount > 0 && (
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3 rounded-lg bg-zinc-900/40 border border-white/[0.06] text-xs">
            <div className="flex items-center gap-2.5">
              <Sparkles className="w-4 h-4 text-cyan-400 shrink-0" />
              <span className="text-zinc-300">
                <strong className="text-white font-medium">{pendingCount} prospectos</strong> de esta lista aún no tienen cargo y empresa actual verificados en vivo.
              </span>
            </div>
            <button
              onClick={handleToggleExtraction}
              disabled={extractionLoading}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 font-medium text-[11px] transition cursor-pointer shrink-0"
            >
              <Zap className="w-3 h-3 text-cyan-400" />
              <span>Extraer datos pendientes</span>
            </button>
          </div>
        )}

        {/* Término de búsqueda asociado si existe */}
        {listDetail.termino_busqueda && (
          <div className="flex items-center justify-between p-3 rounded-lg bg-[#0D0E12] border border-white/[0.06]">
            <div className="flex items-center gap-2">
              <span className="text-xs text-zinc-400">Término de búsqueda asignado:</span>
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-zinc-900 border border-white/[0.08] text-xs font-mono text-zinc-200">
                <Search className="w-3 h-3 text-zinc-400" />
                {listDetail.termino_busqueda}
              </span>
            </div>
            {onNavigateToSearch && (
              <button
                onClick={() => onNavigateToSearch(listDetail.termino_busqueda)}
                className="text-xs text-zinc-300 hover:text-white flex items-center gap-1 cursor-pointer font-medium"
              >
                <span>Ejecutar búsqueda ahora</span>
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        )}

        {/* ============================================================ */}
        {/* SECCIÓN 1: SECUENCIAS EN LAS QUE SE ESTÁ USANDO ESTA LISTA */}
        {/* ============================================================ */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded-md bg-zinc-900 border border-zinc-800 flex items-center justify-center text-zinc-300">
                <GitFork className="w-3.5 h-3.5" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-zinc-100 tracking-tight">
                  Secuencias en las que se está usando ({connectedSeqs.length})
                </h2>
                <p className="text-[11px] text-zinc-400">
                  Flujos automáticos que enrolan a los leads que ingresan a esta lista
                </p>
              </div>
            </div>
            <button
              onClick={handleOpenConnectSequence}
              className="text-xs text-zinc-300 hover:text-white font-medium flex items-center gap-1 cursor-pointer"
            >
              <Plus className="w-3 h-3" />
              <span>Vincular otra secuencia</span>
            </button>
          </div>

          {connectedSeqs.length === 0 ? (
            <div className="p-5 rounded-xl border border-dashed border-white/[0.08] bg-[#121316]/50 text-center space-y-2.5">
              <div className="w-8 h-8 rounded-full bg-zinc-900 border border-zinc-800 flex items-center justify-center mx-auto text-zinc-400">
                <GitFork className="w-4 h-4" />
              </div>
              <div>
                <h4 className="text-xs font-medium text-zinc-200">Esta lista no está vinculada a ninguna secuencia</h4>
                <p className="text-[11px] text-zinc-400 mt-0.5 max-w-md mx-auto">
                  Los prospectos se mantendrán almacenados en esta audiencia sin recibir mensajes de divulgación automática hasta que la vincules a un flujo.
                </p>
              </div>
              <button
                onClick={handleOpenConnectSequence}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-zinc-900 hover:bg-zinc-800 border border-white/[0.08] text-xs font-medium text-zinc-200 hover:text-white transition cursor-pointer"
              >
                <Plus className="w-3 h-3" />
                <span>Vincular a una Secuencia ahora</span>
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {connectedSeqs.map((seq, idx) => {
                const seqId = seq.id || `seq-${idx}`;
                const seqName = seq.nombre || 'Secuencia de Prospección';
                const seqEstado = (seq.estado || (seq.activa ? 'PUBLICADA' : 'BORRADOR')).toUpperCase();
                const isSeqPublished = seqEstado === 'PUBLICADA' && seq.activa === 1;
                const isSeqPaused = seqEstado === 'PAUSADA';

                return (
                  <div
                    key={seqId}
                    className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08] flex flex-col justify-between hover:border-white/[0.18] transition space-y-3"
                  >
                    <div>
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-1.5">
                          <span className={`w-2 h-2 rounded-full ${isSeqPublished ? 'bg-emerald-400 animate-pulse' : isSeqPaused ? 'bg-amber-400' : 'bg-zinc-500'}`} />
                          <h3 className="text-xs font-semibold text-zinc-100 truncate">
                            {seqName}
                          </h3>
                        </div>
                        <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${
                          isSeqPublished
                            ? 'bg-emerald-950/40 text-emerald-400 border-emerald-500/30'
                            : isSeqPaused
                            ? 'bg-amber-950/40 text-amber-400 border-amber-500/30'
                            : 'bg-zinc-900 text-zinc-400 border-zinc-750'
                        }`}>
                          {seqEstado}
                        </span>
                      </div>

                      <div className="mt-2.5 flex items-center gap-1.5 text-[11px] text-zinc-400">
                        <Zap className="w-3 h-3 text-amber-400 shrink-0" />
                        <span>Auto-enrolamiento automático: <strong className="text-zinc-200">Activo</strong></span>
                      </div>
                    </div>

                    <div className="pt-2.5 border-t border-white/[0.06] flex items-center justify-between gap-2">
                      {onSelectSequence ? (
                        <button
                          onClick={() => onSelectSequence(seq)}
                          className="flex items-center gap-1 text-xs text-zinc-300 hover:text-white font-medium cursor-pointer"
                        >
                          <span>Abrir Secuencia</span>
                          <ChevronRight className="w-3.5 h-3.5" />
                        </button>
                      ) : (
                        <span className="text-[11px] text-zinc-400">Conectada</span>
                      )}

                      <button
                        onClick={(e) => handleDisconnectSequence(seq.id, seqName, e)}
                        disabled={actionInProgress}
                        className="text-[11px] text-zinc-500 hover:text-red-400 transition cursor-pointer flex items-center gap-1"
                        title="Desvincular esta secuencia de la lista"
                      >
                        <Unlink className="w-3 h-3" />
                        <span>Desvincular</span>
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* ============================================================ */}
        {/* SECCIÓN 2: MÉTRICAS DE PROSPECTOS DE ESTA LISTA */}
        {/* ============================================================ */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
            <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
              <span className="font-medium text-zinc-300">Total Leads</span>
              <Database className="w-3.5 h-3.5 text-zinc-400" />
            </div>
            <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">{statusCounts.total}</div>
            <span className="text-[10px] text-zinc-500 mt-1 block">Prospectos en esta lista</span>
          </div>

          <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
            <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
              <span className="font-medium text-zinc-300">En Cola</span>
              <Clock className="w-3.5 h-3.5 text-zinc-400" />
            </div>
            <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">{statusCounts.en_cola}</div>
            <span className="text-[10px] text-zinc-400 mt-1 block font-medium">Listos para el flujo</span>
          </div>

          <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
            <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
              <span className="font-medium text-zinc-300">En Secuencia</span>
              <GitFork className="w-3.5 h-3.5 text-zinc-400" />
            </div>
            <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">{statusCounts.contactados}</div>
            <span className="text-[10px] text-blue-400 mt-1 block font-medium">Invitación o mensaje enviado</span>
          </div>

          <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
            <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
              <span className="font-medium text-zinc-300">Conectados / Éxito</span>
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
            </div>
            <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">{statusCounts.conectados}</div>
            <span className="text-[10px] text-emerald-400 mt-1 block font-medium">Aceptaron o agendaron</span>
          </div>
        </div>

        {/* ============================================================ */}
        {/* SECCIÓN 3: LEADS QUE TIENE EN SU INTERIOR */}
        {/* ============================================================ */}
        <div className="space-y-3">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-zinc-100 tracking-tight">
                Prospectos en el interior de la lista ({filteredDetailLeads.length})
              </h2>
              <p className="text-[11px] text-zinc-400">
                Contactos específicos clasificados en esta audiencia segmentada
              </p>
            </div>

            {/* Filtros internos */}
            <div className="flex items-center gap-2 flex-wrap">
              <div className="relative">
                <Search className="w-3.5 h-3.5 text-zinc-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={detailSearchQuery}
                  onChange={(e) => setDetailSearchQuery(e.target.value)}
                  placeholder="Buscar lead, cargo o empresa..."
                  className="bg-[#0D0E12] border border-white/[0.08] pl-8 pr-3 py-1 rounded-md text-xs text-zinc-100 placeholder-zinc-500 w-52 sm:w-64 focus:outline-none focus:border-zinc-500"
                />
              </div>

              <select
                value={detailFilterStatus}
                onChange={(e) => setDetailFilterStatus(e.target.value)}
                className="bg-[#0D0E12] border border-white/[0.08] px-2 py-1 rounded-md text-xs text-zinc-200 focus:outline-none focus:border-zinc-500 cursor-pointer"
              >
                <option value="">Todos los estados</option>
                <option value="EN_COLA">En Cola</option>
                <option value="INVITACION_ENVIADA">Invitación Enviada</option>
                <option value="CONECTADO">Conectados</option>
                <option value="REUNION_AGENDADA">Reunión Agendada</option>
              </select>
            </div>
          </div>

          {/* Barra de Acciones en Lote (cuando hay seleccionados en la lista) */}
          {selectedLeadIds.size > 0 && (
            <div className="p-3 bg-gradient-to-r from-sky-950/40 via-zinc-900 to-emerald-950/40 border border-sky-500/30 rounded-xl mb-3 flex items-center justify-between gap-3 flex-wrap animate-fadeIn">
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded-md bg-sky-500/20 text-sky-300 font-mono text-xs font-semibold border border-sky-500/30">
                  {selectedLeadIds.size} seleccionados
                </span>
                <span className="text-xs text-zinc-300">Acciones masivas:</span>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleBatchResolveEmails}
                  disabled={isBatchResolvingEmail}
                  className="flex items-center gap-1.5 px-3 py-1 rounded-md bg-emerald-950/70 hover:bg-emerald-900/80 text-emerald-300 border border-emerald-500/30 text-xs font-medium transition cursor-pointer disabled:opacity-50"
                  title="Resolver correos corporativos en cascada"
                >
                  <Mail className={`w-3.5 h-3.5 ${isBatchResolvingEmail ? 'animate-spin' : ''}`} />
                  <span>{isBatchResolvingEmail ? 'Resolviendo...' : 'Resolver Emails en Cascada'}</span>
                </button>

                <button
                  type="button"
                  onClick={() => setSelectedLeadIds(new Set())}
                  className="px-2.5 py-1 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-zinc-200 text-xs transition cursor-pointer"
                >
                  Deseleccionar
                </button>
              </div>
            </div>
          )}

          {/* Tabla Unificada de Prospectos en Lista */}
          <UnifiedLeadsTable
            data={filteredDetailLeads}
            context="list"
            loading={loadingDetail}
            onOpenLead={(lead) => setSelectedLeadForModal(lead)}
            selectedLeadIds={selectedLeadIds}
            onToggleLead={handleToggleLead}
            onToggleSelectAll={() => handleToggleSelectAll(filteredDetailLeads)}
            onSyncLinkedIn={(e, lead) => handleSyncSingleLead(lead, e)}
            onResolveEmail={handleResolveSingleEmail}
            onRemoveFromList={(e, lead) => handleRemoveLead(lead.id, lead.nombre, e)}
            syncingLeadIds={syncingLeadIds}
            resolvingLeadIds={resolvingLeadIds}
            actionInProgress={actionInProgress}
            clientSidePagination={true}
            pageSize={25}
            emptyTitle={
              allLeads.length === 0
                ? 'Aún no hay prospectos en esta lista'
                : 'No se encontraron prospectos con este filtro de búsqueda'
            }
            emptySubtitle={
              allLeads.length === 0
                ? 'Ve a la sección Búsqueda para extraer prospectos de LinkedIn y guardarlos directamente en esta lista.'
                : 'Prueba cambiando o limpiando los términos de búsqueda aplicados.'
            }
            emptyAction={
              allLeads.length === 0 && onNavigateToSearch ? (
                <button
                  type="button"
                  onClick={() => onNavigateToSearch(listDetail.termino_busqueda)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 text-xs font-medium transition cursor-pointer"
                >
                  <Search className="w-3.5 h-3.5" />
                  <span>Ir al espacio de Búsqueda</span>
                </button>
              ) : null
            }
          />
        </div>

        {/* Modal de Detalle de Lead */}
        {selectedLeadForModal && (
          <LeadModal
            prospect={selectedLeadForModal}
            onClose={() => setSelectedLeadForModal(null)}
            onUpdated={handleLeadUpdated}
          />
        )}

        {/* Modal para conectar una nueva secuencia a esta lista */}
        {showConnectSeqModal && (
          <div className="fixed inset-0 bg-black/70 backdrop-blur-xs flex items-center justify-center p-4 z-50 animate-fadeIn">
            <div className="bg-[#121316] border border-white/[0.08] rounded-xl max-w-md w-full p-5 space-y-4 shadow-2xl">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="w-7 h-7 rounded-md bg-zinc-900 border border-zinc-800 flex items-center justify-center text-zinc-300">
                    <Link2 className="w-4 h-4" />
                  </div>
                  <h3 className="text-sm font-semibold text-zinc-100">
                    Vincular Secuencia a esta Lista
                  </h3>
                </div>
                <button
                  onClick={() => setShowConnectSeqModal(false)}
                  className="text-zinc-500 hover:text-zinc-300 cursor-pointer"
                >
                  ✕
                </button>
              </div>

              <p className="text-xs text-zinc-400">
                Selecciona la secuencia multicanal a la que se enrolarán automáticamente los prospectos de <strong className="text-zinc-200">"{listDetail.nombre}"</strong>.
              </p>

              {loadingSequences ? (
                <div className="p-6 text-center text-xs text-zinc-500">Cargando secuencias disponibles...</div>
              ) : availableSequences.length === 0 ? (
                <div className="p-4 rounded-lg bg-zinc-900/50 border border-white/[0.06] text-center text-xs text-zinc-400 space-y-2">
                  <p>No hay secuencias disponibles sin vincular a esta lista.</p>
                  <p className="text-[11px] text-zinc-500">Todas tus secuencias ya están conectadas o aún no has creado una.</p>
                </div>
              ) : (
                <div className="space-y-2">
                  <label className="text-xs font-medium text-zinc-300 block">Secuencia de destino:</label>
                  <select
                    value={selectedSeqToConnect}
                    onChange={(e) => setSelectedSeqToConnect(e.target.value)}
                    className="w-full bg-[#0D0E12] border border-white/[0.08] rounded-lg px-3 py-2 text-xs text-zinc-200 focus:outline-none focus:border-zinc-500 cursor-pointer"
                  >
                    {availableSequences.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.nombre} ({s.estado || (s.activa ? 'ACTIVA' : 'PAUSADA')})
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div className="pt-2 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowConnectSeqModal(false)}
                  className="px-3 py-1.5 rounded-md text-xs font-medium text-zinc-400 hover:text-zinc-200 cursor-pointer"
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  onClick={handleConfirmConnectSequence}
                  disabled={!selectedSeqToConnect || actionInProgress || availableSequences.length === 0}
                  className="px-3.5 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 text-xs font-medium transition cursor-pointer disabled:opacity-40"
                >
                  {actionInProgress ? 'Conectando...' : 'Confirmar Vínculo'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  // ============================================================
  // RENDER: GRILLA PRINCIPAL DE TODAS LAS LISTAS
  // ============================================================
  const filteredLists = lists.filter((item) => {
    if (!searchQuery.trim()) return true;
    const term = searchQuery.toLowerCase();
    return (
      (item.nombre || '').toLowerCase().includes(term) ||
      (item.descripcion || '').toLowerCase().includes(term) ||
      (item.termino_busqueda && item.termino_busqueda.toLowerCase().includes(term))
    );
  });

  const totalLeads = lists.reduce((acc, curr) => acc + (curr.total_leads || 0), 0);
  const listsWithSequences = lists.filter((l) => (l.secuencias_conectadas || []).length > 0).length;
  const totalConnections = lists.reduce((acc, curr) => acc + (curr.secuencias_conectadas ? curr.secuencias_conectadas.length : 0), 0);

  return (
    <div className="space-y-5 font-sans animate-fadeIn">
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-zinc-100 tracking-tight">Listas de Leads & Audiencias</h2>
          <p className="text-xs text-zinc-400 mt-0.5">
            Organiza y segmenta tus prospectos por criterios y campañas.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {onNavigateToSearch && (
            <button
              onClick={() => onNavigateToSearch()}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-zinc-900 hover:bg-zinc-800 border border-white/[0.08] text-zinc-200 hover:text-white font-medium text-xs transition cursor-pointer"
            >
              <Search className="w-3.5 h-3.5 text-zinc-400" />
              <span>Espacio de Búsqueda</span>
            </button>
          )}
          <button
            onClick={() => setShowNewModal(true)}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs shadow-sm transition cursor-pointer"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Nueva Lista</span>
          </button>
        </div>
      </div>

      {/* Tarjetas KPI */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
          <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
            <span className="font-medium text-zinc-300">Total Listas</span>
            <Layers className="w-3.5 h-3.5 text-zinc-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">{lists.length}</div>
          <span className="text-[10px] text-zinc-500 mt-1 block">Audiencias configuradas</span>
        </div>

        <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
          <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
            <span className="font-medium text-zinc-300">Total Prospectos</span>
            <Database className="w-3.5 h-3.5 text-zinc-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">{totalLeads}</div>
          <span className="text-[10px] text-zinc-500 mt-1 block">Leads en listas</span>
        </div>

        <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
          <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
            <span className="font-medium text-zinc-300">Con Secuencia</span>
            <Zap className="w-3.5 h-3.5 text-zinc-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">{listsWithSequences}</div>
          <span className="text-[10px] text-zinc-500 mt-1 block">Listas automatizadas</span>
        </div>

        <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
          <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
            <span className="font-medium text-zinc-300">Vínculos de Flujo</span>
            <GitFork className="w-3.5 h-3.5 text-zinc-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">{totalConnections}</div>
          <span className="text-[10px] text-zinc-500 mt-1 block">Conexiones a secuencias</span>
        </div>
      </div>

      {/* Toolbar y Filtros */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs text-zinc-400">
          <Layers className="w-3.5 h-3.5 text-zinc-500" />
          <span>{filteredLists.length} {filteredLists.length === 1 ? 'lista' : 'listas'}</span>
        </div>

        <div className="relative">
          <Search className="w-3.5 h-3.5 text-zinc-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Buscar lista por nombre o nota..."
            className="bg-[#0D0E12] border border-white/[0.08] pl-8 pr-3 py-1.5 rounded-md text-xs text-zinc-100 placeholder-zinc-500 w-full sm:w-64 focus:outline-none focus:border-zinc-500 font-sans"
          />
        </div>
      </div>

      {/* Grilla de Listas */}
      {loading ? (
        <div className="p-12 text-center text-zinc-500 text-xs">Cargando listas...</div>
      ) : filteredLists.length === 0 ? (
        <div className="p-12 rounded-xl border border-zinc-800/80 bg-zinc-900/20 text-center text-zinc-500 text-xs space-y-2">
          <p>No hay listas de prospectos configuradas con este filtro.</p>
          <button
            onClick={() => setShowNewModal(true)}
            className="text-xs text-zinc-300 hover:text-white font-medium underline cursor-pointer"
          >
            Crear tu primera lista de prospectos
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
          {filteredLists.map((item) => {
            const isItemExtracting = Boolean(item.extrayendo_activo);
            const connectedSeqs = item.secuencias_conectadas || [];

            return (
              <div
                key={item.id}
                onClick={() => setSelectedListId(item.id)}
                className="group rounded-xl border border-white/[0.08] bg-[#121316] p-4 space-y-3 hover:border-white/[0.22] hover:bg-[#15171b] transition-all cursor-pointer flex flex-col justify-between shadow-xs"
              >
                <div>
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="font-semibold text-zinc-100 text-xs leading-tight group-hover:text-white transition">
                      {item.nombre}
                    </h3>
                    {isItemExtracting && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono border shrink-0 bg-cyan-950/20 text-cyan-400 border-cyan-500/20 flex items-center gap-1">
                        <RefreshCw className="w-2.5 h-2.5 animate-spin" />
                        <span>EXTRAYENDO</span>
                      </span>
                    )}
                  </div>

                  {item.descripcion && (
                    <p className="text-xs text-zinc-400 mt-1 line-clamp-2">
                      {item.descripcion}
                    </p>
                  )}

                  {item.termino_busqueda && (
                    <div className="mt-2.5 inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-[#0D0E12] border border-white/[0.06] text-[11px] text-zinc-300 font-mono">
                      <Search className="w-3 h-3 text-zinc-500" />
                      <span className="truncate max-w-[200px]">{item.termino_busqueda}</span>
                    </div>
                  )}
                </div>

                <div className="pt-2.5 border-t border-white/[0.06] space-y-2">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-zinc-400">Total Prospectos:</span>
                    <span className="font-mono font-medium text-zinc-200 bg-zinc-900 px-2 py-0.5 rounded border border-white/[0.06]">
                      {item.total_leads || 0}
                    </span>
                  </div>

                  <div className="text-[11px] text-zinc-400">
                    <span className="block mb-1 text-[10px] uppercase tracking-wider text-zinc-500 font-medium">
                      Secuencias en uso ({connectedSeqs.length}):
                    </span>
                    <div className="flex flex-wrap gap-1">
                      {connectedSeqs.length === 0 ? (
                        <span className="text-zinc-500 italic text-[10px]">Sin secuencias vinculadas</span>
                      ) : (
                        connectedSeqs.slice(0, 3).map((seq, seqIdx) => {
                          const seqName = typeof seq === 'string' ? seq : (seq.nombre || seq.id);
                          const seqKey = typeof seq === 'string' ? seq : (seq.id || seqIdx);
                          return (
                            <span
                              key={seqKey}
                              className="px-1.5 py-0.5 rounded bg-white/[0.04] text-zinc-300 text-[10px] font-mono border border-white/[0.06] truncate max-w-[140px]"
                            >
                              {seqName}
                            </span>
                          );
                        })
                      )}
                      {connectedSeqs.length > 3 && (
                        <span className="px-1.5 py-0.5 rounded bg-zinc-900 text-zinc-500 text-[10px] font-mono">
                          +{connectedSeqs.length - 3}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Footer de la tarjeta con acción para abrir y botón de eliminar lista */}
                <div className="pt-2.5 border-t border-white/[0.06] flex items-center justify-between gap-2 text-xs">
                  <span className="text-zinc-400 group-hover:text-zinc-200 transition font-medium flex items-center gap-1 text-[11px]">
                    <span>Abrir y ver leads</span>
                    <ChevronRight className="w-3.5 h-3.5 text-zinc-500 group-hover:translate-x-0.5 transition" />
                  </span>

                  <div onClick={(e) => e.stopPropagation()} className="flex items-center gap-1.5">
                    <button
                      onClick={(e) => handleDeleteList(item.id, item.nombre, e)}
                      disabled={deletingListId === item.id || actionInProgress}
                      className="p-1 rounded hover:bg-red-950/40 text-zinc-500 hover:text-red-400 border border-transparent hover:border-red-500/20 transition cursor-pointer"
                      title="Eliminar permanentemente esta lista"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Modal Nueva Lista */}
      {showNewModal && (
        <NewListModal
          onClose={() => setShowNewModal(false)}
          onCreated={loadLists}
          activeTenantWorkspace={activeTenantWorkspace}
        />
      )}
    </div>
  );
}
