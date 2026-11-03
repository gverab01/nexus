import React, { useState, useEffect, useMemo, useRef } from 'react';
import { 
  Plus, 
  Trash2, 
  Play, 
  Pause, 
  Settings2, 
  CheckCircle2, 
  Clock, 
  ArrowRight, 
  ArrowLeft,
  Layers, 
  Link2, 
  Unlink, 
  Send, 
  Users, 
  Zap, 
  ShieldCheck, 
  AlertCircle,
  Eye,
  RefreshCw,
  FolderGit2,
  Sparkles,
  MessageCircle,
  Smartphone,
  GitFork,
  Search,
  Filter,
  Check,
  Edit3,
  ExternalLink,
  ChevronRight,
  Mail,
  Building2,
  MapPin,
  UserMinus,
  Globe
} from 'lucide-react';
import { 
  fetchSequences, 
  fetchLeadLists, 
  fetchMetrics,
  createSequence,
  updateSequence, 
  deleteSequence,
  addSequenceStep,
  deleteSequenceStep,
  toggleSequencePublish, 
  changeSequenceStatus,
  disconnectListFromSequence, 
  assignEnqueuedLeads, 
  executeSequenceNextStep,
  fetchBrowserStatus,
  showWorkBrowser,
  syncAcceptedConnections,
  fetchWorkerState,
  toggleAutopilot,
  forceWorkerNext,
  resolveLeadEmail,
  batchResolveLeadEmails,
  syncLeadWithLinkedIn
} from '../../services/api';
import EditStepModal from './EditStepModal';
import AddStepModal from './AddStepModal';
import NewSequenceModal from './NewSequenceModal';
import ConnectListModal from './ConnectListModal';
import LeadModal from '../Prospects/LeadModal';
import AutopilotBanner from './AutopilotBanner';
import UnifiedLeadsTable from '../Prospects/UnifiedLeadsTable';

export default function SequencesView({ 
  activeTenantWorkspace = '', 
  initialSequenceId = null,
  onBackToGlobal = null,
  onSequencesUpdated = null 
}) {
  const [sequences, setSequences] = useState([]);
  const [selectedSeqId, setSelectedSeqId] = useState(initialSequenceId || null);
  const [leadLists, setLeadLists] = useState([]);
  const [metrics, setMetrics] = useState({ hoy: 0, cola: 0, enviadas: 0, conectados: 0 });
  const [loading, setLoading] = useState(true);

  // Filtros del Directorio Global
  const [filterStatus, setFilterStatus] = useState('TODAS'); // 'TODAS' | 'PUBLICADA' | 'PAUSADA' | 'BORRADOR'
  const [searchTerm, setSearchTerm] = useState('');

  // Modales
  const [selectedStepToEdit, setSelectedStepToEdit] = useState(null);
  const [addStepModalConfig, setAddStepModalConfig] = useState(null); // { position: 'inicio' | 'final' | 'intermedio' }
  const [showNewSequenceModal, setShowNewSequenceModal] = useState(false);
  const [showConnectListModal, setShowConnectListModal] = useState(false);

  // Action State
  const [executingStep, setExecutingStep] = useState(false);
  const [assigningLeads, setAssigningLeads] = useState(false);
  const [syncingConnections, setSyncingConnections] = useState(false);
  const [needsLinkedinLogin, setNeedsLinkedinLogin] = useState(false);
  const [needsWhatsappLogin, setNeedsWhatsappLogin] = useState(false);
  const [creatingTemplate, setCreatingTemplate] = useState(false);
  const [deletingSeqId, setDeletingSeqId] = useState(null);

  // Ficha de Lead y opciones completas para prospectos en secuencia
  const [selectedLeadForModal, setSelectedLeadForModal] = useState(null);
  const [selectedLeadIds, setSelectedLeadIds] = useState(new Set());
  const [leadSearchTerm, setLeadSearchTerm] = useState('');
  const [leadStatusFilter, setLeadStatusFilter] = useState('TODOS');
  const [syncingLeadIds, setSyncingLeadIds] = useState(new Set());
  const [resolvingLeadIds, setResolvingLeadIds] = useState(new Set());
  const [isBatchResolvingEmail, setIsBatchResolvingEmail] = useState(false);

  // Piloto Automático del Runner Local
  const [workerState, setWorkerState] = useState({ piloto_automatico: false, estado_actual: 'Consultando...' });
  const [togglingAutopilot, setTogglingAutopilot] = useState(false);
  const [isForcingNext, setIsForcingNext] = useState(false);

  const isAnyModalOpen = Boolean(
    showNewSequenceModal ||
    showConnectListModal ||
    selectedStepToEdit ||
    addStepModalConfig ||
    selectedLeadForModal
  );
  const isAnyModalOpenRef = useRef(false);
  isAnyModalOpenRef.current = isAnyModalOpen;

  useEffect(() => {
    loadData();
    checkWorkerLoopState();
    const interval = setInterval(checkWorkerState, 10000);
    const workerInterval = setInterval(async () => {
      if (isAnyModalOpenRef.current) return;
      await checkWorkerLoopState();
      await loadData(null, true);
    }, 3500);
    return () => {
      clearInterval(interval);
      clearInterval(workerInterval);
    };
  }, [activeTenantWorkspace]);

  useEffect(() => {
    if (initialSequenceId) {
      setSelectedSeqId(initialSequenceId);
    }
  }, [initialSequenceId]);

  async function checkWorkerLoopState() {
    try {
      const state = await fetchWorkerState();
      if (state) {
        setWorkerState(prev => ({
          ...prev,
          ...state,
          piloto_automatico: Boolean(state.piloto_automatico),
          estado_actual: state.estado_actual || 'En espera',
        }));
      }
    } catch {}
  }

  async function handleForceNext() {
    try {
      setIsForcingNext(true);
      await forceWorkerNext();
      await checkWorkerLoopState();
      await loadData(selectedSeqId, true);
    } catch (err) {
      console.error('Error adelantando ciclo del worker:', err);
    } finally {
      setIsForcingNext(false);
    }
  }

  async function handleToggleAutopilot() {
    try {
      setTogglingAutopilot(true);
      const res = await toggleAutopilot();
      setWorkerState(prev => ({
        ...prev,
        piloto_automatico: Boolean(res.piloto_automatico),
        estado_actual: res.mensaje || prev.estado_actual
      }));
      await loadData();
    } catch (err) {
      alert(`Error al cambiar piloto automático: ${err.message}`);
    } finally {
      setTogglingAutopilot(false);
    }
  }

  async function checkWorkerState() {
    try {
      const browser = await fetchBrowserStatus();
      setNeedsLinkedinLogin(Boolean(browser.is_electron && !browser.sesion_linkedin_activa));
      setNeedsWhatsappLogin(Boolean(browser.is_electron && !browser.sesion_whatsapp_activa));
    } catch {}
  }

  async function loadData(targetSeqId = null, silent = false) {
    try {
      if (!silent) setLoading(true);
      const [seqsData, listsData, browserState, metricsData] = await Promise.all([
        fetchSequences(activeTenantWorkspace),
        fetchLeadLists(activeTenantWorkspace),
        fetchBrowserStatus().catch(() => ({})),
        fetchMetrics(activeTenantWorkspace).catch(() => ({})),
      ]);
      setSequences(seqsData || []);
      setLeadLists(listsData || []);
      setNeedsLinkedinLogin(Boolean(browserState.is_electron && !browserState.sesion_linkedin_activa));
      setNeedsWhatsappLogin(Boolean(browserState.is_electron && !browserState.sesion_whatsapp_activa));
      setMetrics({
        hoy: metricsData?.invitaciones_hoy || 0,
        cola: metricsData?.en_cola || 0,
        enviadas: metricsData?.invitaciones_enviadas || 0,
        conectados: metricsData?.conectados || 0,
      });

      if (targetSeqId) {
        setSelectedSeqId(targetSeqId);
      }
    } catch (err) {
      console.error('Error cargando secuencias:', err);
    } finally {
      if (!silent) setLoading(false);
    }
  }

  function handleSequenceCreated(newSeq) {
    setShowNewSequenceModal(false);
    loadData(newSeq?.id);
    if (newSeq?.id) {
      setSelectedSeqId(newSeq.id);
    }
    if (onSequencesUpdated) onSequencesUpdated();
  }

  async function handleQuickCreateTemplate(templateType, customName = null) {
    try {
      setCreatingTemplate(true);
      const names = {
        trilateral_multicanal: 'Outreach Multicanal (LinkedIn + WhatsApp + Correo)',
        multicanal: 'Secuencia Multicanal LinkedIn + Email',
        linkedin_lineal: 'Secuencia Directa LinkedIn',
        whatsapp_lineal: 'Secuencia Directa WhatsApp Web (Antiban)',
      };
      const res = await createSequence({
        nombre: customName || names[templateType] || 'Nueva Secuencia',
        plantilla: templateType,
        publicada: false,
        estado: 'BORRADOR',
        tenant_id: activeTenantWorkspace || undefined,
      });
      await loadData(res?.id);
      if (res?.id) {
        setSelectedSeqId(res.id);
      }
    } catch (err) {
      alert(`Error creando secuencia: ${err.message}`);
    } finally {
      setCreatingTemplate(false);
    }
  }

  // Secuencia seleccionada actualmente
  const activeSequence = useMemo(() => {
    if (!selectedSeqId) return null;
    return sequences.find((s) => s.id === selectedSeqId) || null;
  }, [sequences, selectedSeqId]);

  async function handleSetSequenceStatus(sequenceId, targetEstado) {
    if (!sequenceId) return;
    try {
      await changeSequenceStatus(sequenceId, targetEstado);
      await loadData();
      if (onSequencesUpdated) onSequencesUpdated();
    } catch (err) {
      alert(`Error actualizando estado de la secuencia: ${err.message}`);
    }
  }

  async function handleDeleteSequence(seqId, seqName, e) {
    if (e) e.stopPropagation();
    const confirmed = window.confirm(
      `¿Estás seguro de eliminar permanentemente la secuencia "${seqName || seqId}"?\n\n` +
      `• Se eliminarán todos sus pasos y bifurcaciones.\n` +
      `• Se desvincularán las listas asociadas.\n` +
      `• Los prospectos inscritos quedarán liberados (no se borrarán de la base de datos).\n\n` +
      `Esta acción no se puede deshacer.`
    );
    if (!confirmed) return;

    try {
      setDeletingSeqId(seqId);
      await deleteSequence(seqId);
      if (selectedSeqId === seqId) {
        setSelectedSeqId(null);
        if (onBackToGlobal) onBackToGlobal();
      }
      await loadData();
      if (onSequencesUpdated) onSequencesUpdated();
    } catch (err) {
      alert(`Error al eliminar la secuencia: ${err.message}`);
    } finally {
      setDeletingSeqId(null);
    }
  }

  async function handleDisconnectList(listId) {
    if (!activeSequence) return;
    if (!confirm('¿Deseas desvincular esta lista de prospectos de la secuencia?')) return;
    try {
      await disconnectListFromSequence(activeSequence.id, listId);
      await loadData();
    } catch (err) {
      alert(`Error desvinculando lista: ${err.message}`);
    }
  }

  async function handleAssignEnqueued() {
    if (!activeSequence) return;
    try {
      setAssigningLeads(true);
      const res = await assignEnqueuedLeads(activeSequence.id);
      alert(`Leads inscritos: ${res.mensaje || 'Prospectos asignados con éxito'}`);
      await loadData();
    } catch (err) {
      alert(`Error asignando leads: ${err.message}`);
    } finally {
      setAssigningLeads(false);
    }
  }

  async function handleExecuteNextStep() {
    if (!activeSequence) return;
    try {
      setExecutingStep(true);
      const res = await executeSequenceNextStep(activeSequence.id);
      if (res.status === 'ok') {
        const detalle = res.paso_ejecutado?.detalle || 'Paso procesado con éxito';
        alert(`Éxito: ${detalle}`);
      } else if (res.status === 'bloqueado_por_seguridad') {
        alert(`Seguridad activa: ${res.motivo || 'Acción bloqueada por reglas de seguridad'}`);
      } else {
        alert(`Estado: ${res.mensaje || 'Sin prospectos listos para ejecutar'}`);
      }
      await loadData();
    } catch (err) {
      alert(`Aviso de ejecución: ${err.message}`);
    } finally {
      setExecutingStep(false);
    }
  }

  async function handleSyncAcceptedConnections() {
    try {
      setSyncingConnections(true);
      const res = await syncAcceptedConnections(activeTenantWorkspace);
      alert(res.mensaje || 'Sincronización de conexiones completada.');
      await loadData(selectedSeqId);
    } catch (err) {
      alert(`Error sincronizando conexiones: ${err.message}`);
    } finally {
      setSyncingConnections(false);
    }
  }

  async function handleSaveEditedStep(updatedStep) {
    if (!activeSequence) return;
    const newSteps = (activeSequence.pasos || []).map((s) =>
      s.id === updatedStep.id ? updatedStep : s
    );
    try {
      await updateSequence(activeSequence.id, { pasos: newSteps });
      setSelectedStepToEdit(null);
      await loadData();
    } catch (err) {
      alert(`Error guardando paso: ${err.message}`);
    }
  }

  async function handleDeleteStep(stepId) {
    if (!activeSequence) return;
    try {
      await deleteSequenceStep(activeSequence.id, stepId);
      setSelectedStepToEdit(null);
      await loadData();
    } catch (err) {
      alert(`Error eliminando paso: ${err.message}`);
    }
  }

  async function handleAddStep({ step, position, referenceStepId }) {
    if (!activeSequence) return;
    try {
      await addSequenceStep(activeSequence.id, { step, position, referenceStepId });
      setAddStepModalConfig(null);
      await loadData();
    } catch (err) {
      alert(`Error insertando paso: ${err.message}`);
    }
  }

  // Resolver correo en cascada para un prospecto individual
  async function handleResolveLeadEmail(e, lead) {
    if (e) e.stopPropagation();
    const leadId = lead?.lead_id || lead?.id;
    if (!leadId) return;
    try {
      setResolvingLeadIds(prev => new Set(prev).add(leadId));
      const res = await resolveLeadEmail(leadId, true);
      if (res && res.email) {
        alert(`Correo resuelto con éxito para ${lead.nombre}: ${res.email} (${res.source || 'verificado'})`);
        await loadData(selectedSeqId);
      } else {
        alert(res?.motivo || 'No se localizó correo electrónico verificado para este prospecto.');
      }
    } catch (err) {
      alert(`Error resolviendo correo en cascada: ${err.message}`);
    } finally {
      setResolvingLeadIds(prev => {
        const next = new Set(prev);
        next.delete(leadId);
        return next;
      });
    }
  }

  // Resolver correos en cascada en lote para los leads seleccionados
  async function handleBatchResolveEmails() {
    if (selectedLeadIds.size === 0) return;
    setIsBatchResolvingEmail(true);
    try {
      const res = await batchResolveLeadEmails(Array.from(selectedLeadIds), true);
      alert(`Resolución en cascada finalizada:\n• ${res?.resueltos || 0} correos corporativos resueltos\n• ${res?.no_encontrados || 0} no localizados.`);
      await loadData(selectedSeqId);
      setSelectedLeadIds(new Set());
    } catch (err) {
      alert(`Error en resolución en bloque: ${err.message}`);
    } finally {
      setIsBatchResolvingEmail(false);
    }
  }

  // Manejo de selección individual y toggle masivo
  function handleToggleSelectLead(leadId) {
    setSelectedLeadIds(prev => {
      const next = new Set(prev);
      if (next.has(leadId)) next.delete(leadId);
      else next.add(leadId);
      return next;
    });
  }

  function handleToggleSelectAllLeads(visibleLeads = []) {
    if (visibleLeads.length === 0) return;
    const allSelected = visibleLeads.every(l => selectedLeadIds.has(l.lead_id || l.id));
    if (allSelected) {
      setSelectedLeadIds(prev => {
        const next = new Set(prev);
        visibleLeads.forEach(l => next.delete(l.lead_id || l.id));
        return next;
      });
    } else {
      setSelectedLeadIds(prev => {
        const next = new Set(prev);
        visibleLeads.forEach(l => next.add(l.lead_id || l.id));
        return next;
      });
    }
  }

  // Actualización reactiva tras modificar un prospecto desde el modal
  function handleLeadUpdatedInSequence(updatedLead) {
    if (!updatedLead) return;
    setSelectedLeadForModal(updatedLead);
    loadData(selectedSeqId);
  }

  // Métricas Consolidadas del Grupo de Secuencias (Global KPIs)
  const globalStats = useMemo(() => {
    let publicadas = 0;
    let pausadas = 0;
    let borradores = 0;
    let leadsEnCursoActivas = 0;
    let leadsEnCursoTotal = 0;
    let leadsCompletados = 0;

    sequences.forEach((s) => {
      const st = (s.estado || (s.activa ? 'PUBLICADA' : 'BORRADOR')).toUpperCase();
      const isActiva = st === 'PUBLICADA' && Boolean(s.activa);
      const enCurso = Number(s.leads_en_curso || (s.leads_inscritos?.length || 0));
      const enrolledDone = (s.leads_inscritos || []).filter((l) => {
        const lst = (l.estado_secuencia || l.estado || '').toUpperCase();
        return lst === 'COMPLETADO' || lst === 'FINALIZADA' || lst === 'FINALIZADO';
      }).length;
      const completados = Math.max(
        Number(s.leads_completados || s.leads_completados_count || s.total_completados || 0),
        enrolledDone
      );

      if (isActiva) {
        publicadas++;
        leadsEnCursoActivas += enCurso;
      } else if (st === 'PAUSADA') {
        pausadas++;
      } else {
        borradores++;
      }

      leadsEnCursoTotal += enCurso;
      leadsCompletados += completados;
    });

    return {
      total: sequences.length,
      publicadas,
      pausadas,
      borradores,
      leadsEnCurso: leadsEnCursoActivas,
      leadsEnCursoActivas,
      leadsEnCursoTotal,
      leadsCompletados,
    };
  }, [sequences]);

  // Filtrado de secuencias para el Directorio Global
  const filteredSequences = useMemo(() => {
    return sequences.filter((s) => {
      const st = (s.estado || (s.activa ? 'PUBLICADA' : 'BORRADOR')).toUpperCase();
      const isPub = st === 'PUBLICADA' && Boolean(s.activa);
      const isPau = st === 'PAUSADA';
      const isBor = !isPub && !isPau;

      if (filterStatus === 'PUBLICADA' && !isPub) return false;
      if (filterStatus === 'PAUSADA' && !isPau) return false;
      if (filterStatus === 'BORRADOR' && !isBor) return false;

      if (searchTerm.trim()) {
        const term = searchTerm.toLowerCase();
        const matchesName = (s.nombre || '').toLowerCase().includes(term);
        const matchesDesc = (s.descripcion || '').toLowerCase().includes(term);
        if (!matchesName && !matchesDesc) return false;
      }
      return true;
    });
  }, [sequences, filterStatus, searchTerm]);

  // ============================================================
  // RENDER A: VISTA DETALLADA DE UNA SECUENCIA ESPECÍFICA
  // ============================================================
  if (selectedSeqId && activeSequence) {
    const steps = activeSequence.pasos || [];
    const enrolledLeads = activeSequence.leads_inscritos || [];
    const candidateLead = activeSequence.candidato_proximo || null;
    const connectedLists = (activeSequence.listas_asociadas && activeSequence.listas_asociadas.length > 0)
      ? activeSequence.listas_asociadas
      : (activeSequence.listas_conectadas || []).map(l => (typeof l === 'object' ? l : { id: l, nombre: l }));

    const st = (activeSequence.estado || (activeSequence.activa ? 'PUBLICADA' : 'BORRADOR')).toUpperCase();
    const isPublished = st === 'PUBLICADA' && Boolean(activeSequence.activa);
    const isPaused = st === 'PAUSADA';
    const isDraft = !isPublished && !isPaused;

    const hasWhatsAppSteps = steps.some(p => (p.accion || p.tipo_accion || p.tipo || '').includes('WHATSAPP'));
    const hasLinkedInSteps = steps.some(p => {
      const a = (p.accion || p.tipo_accion || p.tipo || '');
      return a.includes('LINKEDIN') || a.includes('INVITACION') || a.includes('PERFIL');
    });

    // Métricas en tiempo real de colas y prospectos en cada etapa
    const queueTotalEnCurso = steps.reduce((acc, p) => acc + (p.leads_en_paso || 0), 0);
    const queueTotalListos = steps.reduce((acc, p) => acc + (p.leads_listos || 0), 0);
    const queueTotalEnEspera = steps.reduce((acc, p) => acc + (p.leads_en_espera || 0), 0);
    const enrolledCompletedCount = enrolledLeads.filter((l) => {
      const st = (l.estado_secuencia || l.estado || '').toUpperCase();
      return st === 'COMPLETADO' || st === 'FINALIZADA' || st === 'FINALIZADO';
    }).length;
    const totalCompletados = Math.max(
      Number(activeSequence.total_completados || activeSequence.leads_completados || activeSequence.leads_completados_count || 0),
      enrolledCompletedCount
    );

    const getLeadQueueStatus = (lead) => {
      const stLead = (lead.estado_secuencia || lead.estado || '').toUpperCase();
      if (stLead === 'COMPLETADO' || stLead === 'FINALIZADA' || stLead === 'FINALIZADO') {
        return {
          type: 'completed',
          label: 'COMPLETADO',
          badgeClass: 'bg-purple-950/60 text-purple-300 border-purple-500/30',
          subtext: 'Completó todos los pasos'
        };
      }
      if (!lead.proxima_ejecucion_at) {
        return {
          type: 'ready',
          label: '⚡ LISTO PARA ENVÍO',
          badgeClass: 'bg-emerald-950/60 text-emerald-300 border-emerald-500/40',
          subtext: 'Aguardando cupo antiban'
        };
      }
      const proxDate = new Date(lead.proxima_ejecucion_at);
      const now = new Date();
      const diffMs = proxDate.getTime() - now.getTime();
      if (diffMs <= 0 || isNaN(diffMs)) {
        return {
          type: 'ready',
          label: '⚡ LISTO PARA ENVÍO',
          badgeClass: 'bg-emerald-950/60 text-emerald-300 border-emerald-500/40',
          subtext: 'Aguardando cupo antiban'
        };
      }
      const diffMins = Math.round(diffMs / 60000);
      let timeStr = `${diffMins} min`;
      if (diffMins >= 60) {
        const hrs = Math.floor(diffMins / 60);
        const mins = diffMins % 60;
        timeStr = mins > 0 ? `${hrs}h ${mins}m` : `${hrs}h`;
      }
      return {
        type: 'waiting',
        label: `⏱️ ENFRIAMIENTO (${timeStr})`,
        badgeClass: 'bg-amber-950/60 text-amber-300 border-amber-500/40',
        subtext: 'Pausa antiban activa'
      };
    };

    // Filtrado reactivo de prospectos en esta secuencia
    const filteredEnrolledLeads = enrolledLeads.filter((lead) => {
      if (leadSearchTerm.trim()) {
        const q = leadSearchTerm.toLowerCase();
        const matches =
          (lead.nombre || '').toLowerCase().includes(q) ||
          (lead.cargo_actual || lead.cargo_titular || lead.cargo || '').toLowerCase().includes(q) ||
          (lead.institucion_actual || lead.institucion || lead.empresa || '').toLowerCase().includes(q) ||
          (lead.email_directo || lead.email || '').toLowerCase().includes(q);
        if (!matches) return false;
      }

      if (leadStatusFilter === 'TODOS') return true;
      const qStatus = getLeadQueueStatus(lead);
      if (leadStatusFilter === 'LISTOS') return qStatus.type === 'ready';
      if (leadStatusFilter === 'TEMPORIZADOR') return qStatus.type === 'waiting';
      if (leadStatusFilter === 'COMPLETADO') return qStatus.type === 'completed';
      if (leadStatusFilter === 'CON_EMAIL') return Boolean(lead.email_directo && lead.email_directo !== 'No declarado');
      if (leadStatusFilter === 'SIN_EMAIL') return !lead.email_directo || lead.email_directo === 'No declarado';
      if (leadStatusFilter === 'ZOHO_SINCRONIZADO') return Boolean(lead.zoho_id || lead.email_zoho || lead.zoho_synced_at);

      return true;
    });

    return (
      <div className="space-y-6 font-sans">
        {/* 1. Barra de Navegación: Volver al Directorio */}
        <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
          <button
            onClick={() => {
              setSelectedSeqId(null);
              if (onBackToGlobal) onBackToGlobal();
            }}
            className="flex items-center gap-2 text-xs font-medium text-zinc-400 hover:text-zinc-100 transition cursor-pointer"
          >
            <ArrowLeft className="w-4 h-4 text-zinc-400" />
            <span>Volver al Directorio de Secuencias</span>
          </button>

          <span className="text-[11px] font-mono text-zinc-500">
            ID: {activeSequence.id}
          </span>
        </div>

        {/* 2. Header de la Secuencia Seleccionada */}
        <div className="p-4 rounded-xl bg-[#121316] border border-white/[0.08] flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-xs">
          <div className="space-y-1 min-w-0">
            <div className="flex items-center gap-2.5 flex-wrap">
              <h2 className="text-base font-semibold text-zinc-100 truncate">
                {activeSequence.nombre}
              </h2>

              {/* Indicador ÚNICO y limpio de estado */}
              {isPublished ? (
                <span className="px-2.5 py-0.5 rounded-full text-[11px] font-mono border font-medium bg-emerald-950/40 text-emerald-400 border-emerald-500/30 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0 animate-subtle-dot" />
                  <span>Publicada (En Marcha)</span>
                </span>
              ) : isPaused ? (
                <span className="px-2.5 py-0.5 rounded-full text-[11px] font-mono border font-medium bg-amber-950/40 text-amber-300 border-amber-500/30 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
                  <span>Pausada</span>
                </span>
              ) : (
                <span className="px-2.5 py-0.5 rounded-full text-[11px] font-mono border font-medium bg-zinc-800 text-zinc-300 border-zinc-700/60 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-zinc-400 shrink-0" />
                  <span>Borrador</span>
                </span>
              )}
            </div>

            <p className="text-xs text-zinc-400 truncate max-w-2xl">
              {activeSequence.descripcion || 'Secuencia de prospección automatizada multicanal.'}
            </p>
          </div>

          {/* Botones de Control de la Secuencia */}
          <div className="flex items-center gap-2 shrink-0">
            {isDraft ? (
              <button
                onClick={() => handleSetSequenceStatus(activeSequence.id, 'PUBLICADA')}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-xs font-semibold bg-emerald-500 hover:bg-emerald-400 text-zinc-950 transition cursor-pointer shadow-sm shadow-emerald-500/20"
                title="Publicar secuencia para comenzar a contactar los prospectos de las listas vinculadas"
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>Publicar Secuencia</span>
              </button>
            ) : isPublished ? (
              <button
                onClick={() => handleSetSequenceStatus(activeSequence.id, 'PAUSADA')}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-zinc-850 hover:bg-zinc-800 text-amber-300 border border-amber-500/30 transition cursor-pointer"
                title="Pausar temporalmente el avance de pasos de esta secuencia"
              >
                <Pause className="w-3.5 h-3.5" />
                <span>Pausar</span>
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleSetSequenceStatus(activeSequence.id, 'PUBLICADA')}
                  className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white transition cursor-pointer shadow-sm"
                  title="Reanudar el avance y despacho de prospectos"
                >
                  <Play className="w-3.5 h-3.5" />
                  <span>Reanudar</span>
                </button>
                <button
                  onClick={() => handleSetSequenceStatus(activeSequence.id, 'BORRADOR')}
                  className="px-2.5 py-1.5 rounded-md text-[11px] font-medium text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60 border border-transparent hover:border-zinc-750 transition cursor-pointer"
                  title="Devolver a borrador para detener envíos y realizar ajustes estructurales"
                >
                  Pasar a Borrador
                </button>
              </div>
            )}

            {/* Botón Eliminar Secuencia */}
            <button
              onClick={(e) => handleDeleteSequence(activeSequence.id, activeSequence.nombre, e)}
              disabled={deletingSeqId === activeSequence.id}
              className="p-1.5 rounded-md hover:bg-red-950/40 text-zinc-400 hover:text-red-400 border border-transparent hover:border-red-500/20 transition cursor-pointer"
              title="Eliminar permanentemente esta secuencia"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Banner Interactivo de Control y Telemetría en Tiempo Real del Piloto Automático */}
        <AutopilotBanner
          workerState={workerState}
          onToggleAutopilot={handleToggleAutopilot}
          togglingAutopilot={togglingAutopilot}
          onForceNext={handleForceNext}
          isForcingNext={isForcingNext}
        />

        {/* 3. Bloque de Métricas Consolidadas y Colas en Tiempo Real (Fuente Única) */}
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
          {/* Tarjeta 1: Cupo Antiban Hoy */}
          <div className="p-3 rounded-xl bg-[#121316] border border-emerald-500/20">
            <div className="flex items-center justify-between text-zinc-400 text-xs mb-1">
              <span className="font-medium text-zinc-300 text-[11px] truncate">Cupo Antiban Hoy</span>
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
            </div>
            <div className="text-xl font-bold font-mono tracking-tight text-emerald-300">
              {metrics.hoy || 0} <span className="text-xs text-zinc-500 font-normal">/ {metrics.limite_diario || 15}</span>
            </div>
            <span className="text-[10px] text-zinc-400 mt-1 block truncate">
              {metrics.semana_warmup || 'Warm-up'} &bull; {Math.max(0, (metrics.limite_diario || 15) - (metrics.hoy || 0))} libres
            </span>
          </div>

          {/* Tarjeta 2: Invitaciones Enviadas */}
          <div className="p-3 rounded-xl bg-[#121316] border border-sky-500/20">
            <div className="flex items-center justify-between text-zinc-400 text-xs mb-1">
              <span className="font-medium text-zinc-300 text-[11px] truncate">Invitaciones Enviadas</span>
              <Send className="w-3.5 h-3.5 text-sky-400 shrink-0" />
            </div>
            <div className="text-xl font-bold font-mono tracking-tight text-sky-300">
              {metrics.enviadas || 0}
            </div>
            <span className="text-[10px] text-zinc-400 mt-1 block truncate">
              Total acumuladas en flujo
            </span>
          </div>

          {/* Tarjeta 3: Conexiones Aceptadas */}
          <div className="p-3 rounded-xl bg-[#121316] border border-teal-500/20">
            <div className="flex items-center justify-between text-zinc-400 text-xs mb-1">
              <span className="font-medium text-zinc-300 text-[11px] truncate">Conexiones Aceptadas</span>
              <Users className="w-3.5 h-3.5 text-teal-400 shrink-0" />
            </div>
            <div className="text-xl font-bold font-mono tracking-tight text-teal-300">
              {metrics.conectados || 0}
            </div>
            <span className="text-[10px] text-zinc-400 mt-1 block truncate">
              {metrics.tasa_aceptacion ? `${metrics.tasa_aceptacion}% aceptación` : 'Conectados en red'}
            </span>
          </div>

          {/* Tarjeta 4: Listos para Envío */}
          <div className="p-3 rounded-xl bg-[#121316] border border-amber-500/20">
            <div className="flex items-center justify-between text-zinc-400 text-xs mb-1">
              <span className="font-medium text-zinc-300 text-[11px] truncate">Listos para Envío</span>
              <Zap className="w-3.5 h-3.5 text-amber-400 shrink-0" />
            </div>
            <div className="text-xl font-bold font-mono tracking-tight text-amber-300">
              {queueTotalListos}
            </div>
            <span className="text-[10px] text-zinc-400 mt-1 block truncate">
              Aguardando cupo antiban
            </span>
          </div>

          {/* Tarjeta 5: En Pausa / Enfriamiento */}
          <div className="p-3 rounded-xl bg-[#121316] border border-orange-500/20">
            <div className="flex items-center justify-between text-zinc-400 text-xs mb-1">
              <span className="font-medium text-zinc-300 text-[11px] truncate">En Pausa / Espera</span>
              <Clock className="w-3.5 h-3.5 text-orange-400 shrink-0" />
            </div>
            <div className="text-xl font-bold font-mono tracking-tight text-orange-300">
              {queueTotalEnEspera}
            </div>
            <span className="text-[10px] text-zinc-400 mt-1 block truncate">
              Temporizador antiban activo
            </span>
          </div>

          {/* Tarjeta 6: Flujo Completado */}
          <div className="p-3 rounded-xl bg-[#121316] border border-purple-500/20">
            <div className="flex items-center justify-between text-zinc-400 text-xs mb-1">
              <span className="font-medium text-zinc-300 text-[11px] truncate">Flujo Completado</span>
              <CheckCircle2 className="w-3.5 h-3.5 text-purple-400 shrink-0" />
            </div>
            <div className="text-xl font-bold font-mono tracking-tight text-purple-300">
              {totalCompletados}
            </div>
            <span className="text-[10px] text-zinc-400 mt-1 block truncate">
              Finalizaron ciclo completo
            </span>
          </div>
        </div>

        {/* 4. Alertas de Sesión Faltante (Solo si la secuencia usa ese canal) */}
        {hasLinkedInSteps && needsLinkedinLogin && (
          <div className="p-3 rounded-lg bg-amber-950/30 border border-amber-500/30 text-xs text-amber-200 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
              <div>
                <span className="font-semibold text-amber-300">Sesión de LinkedIn no detectada en Chromium embebido.</span>
                <p className="text-[11px] text-amber-200/80">Inicia sesión una sola vez para que los pasos de LinkedIn puedan ejecutarse.</p>
              </div>
            </div>
            <button
              onClick={() => showWorkBrowser('https://www.linkedin.com/login', 'linkedin')}
              className="px-3 py-1 rounded bg-amber-500 hover:bg-amber-400 text-zinc-950 font-bold text-xs shrink-0 cursor-pointer transition shadow-xs"
            >
              Conectar LinkedIn
            </button>
          </div>
        )}

        {hasWhatsAppSteps && needsWhatsappLogin && (
          <div className="p-3 rounded-lg bg-emerald-950/30 border border-emerald-500/30 text-xs text-emerald-200 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <MessageCircle className="w-4 h-4 text-emerald-400 shrink-0" />
              <div>
                <span className="font-semibold text-emerald-300">WhatsApp Web no vinculado en Chromium embebido.</span>
                <p className="text-[11px] text-emerald-200/80">Escanea el código QR para habilitar los pasos de envío automático por WhatsApp.</p>
              </div>
            </div>
            <button
              onClick={() => showWorkBrowser('https://web.whatsapp.com', 'whatsapp')}
              className="px-3 py-1 rounded bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-bold text-xs shrink-0 cursor-pointer transition shadow-xs"
            >
              Vincular QR
            </button>
          </div>
        )}

        {/* 5. Listas de Leads Vinculadas a esta Secuencia */}
        <div className="p-4 rounded-xl bg-[#121316] border border-white/[0.08] space-y-3">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-white/[0.06] pb-2.5">
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded-md bg-zinc-900 border border-zinc-800 flex items-center justify-center text-zinc-300">
                <Link2 className="w-3.5 h-3.5 text-sky-400" />
              </div>
              <div>
                <h3 className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
                  <span>Listas de Leads Vinculadas</span>
                  <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-zinc-900 border border-white/[0.06] text-zinc-300">
                    {connectedLists.length}
                  </span>
                </h3>
                <p className="text-[11px] text-zinc-400">
                  Los prospectos de estas listas alimentan y avanzan por esta secuencia.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowConnectListModal(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs shadow-sm transition cursor-pointer"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>+ Vincular Listas</span>
              </button>
              {connectedLists.length > 0 && (
                <button
                  onClick={handleAssignEnqueued}
                  disabled={assigningLeads}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-750 text-zinc-200 border border-zinc-700 text-xs font-medium transition cursor-pointer disabled:opacity-50"
                  title="Inscribe inmediatamente los leads disponibles de las listas conectadas"
                >
                  <Users className="w-3.5 h-3.5 text-zinc-400" />
                  <span>{assigningLeads ? 'Inscribiendo...' : 'Asignar Cola'}</span>
                </button>
              )}

              <button
                onClick={handleSyncAcceptedConnections}
                disabled={syncingConnections}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-sky-950/40 hover:bg-sky-900/60 text-sky-300 border border-sky-500/30 text-xs font-semibold transition cursor-pointer disabled:opacity-50"
                title="Inspecciona si las invitaciones pendientes han sido aceptadas en LinkedIn"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${syncingConnections ? 'animate-spin' : ''}`} />
                <span>{syncingConnections ? 'Sincronizando...' : 'Sincronizar Conexiones'}</span>
              </button>
            </div>
          </div>

          {connectedLists.length === 0 ? (
            <div className="p-3.5 rounded-lg bg-zinc-900/60 border border-white/[0.06] text-xs text-zinc-400 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <span>Esta secuencia aún no tiene listas vinculadas. Conecta una lista para alimentar el flujo de outreach.</span>
              <button
                onClick={() => setShowConnectListModal(true)}
                className="px-3 py-1 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-200 font-medium text-xs transition cursor-pointer shrink-0"
              >
                Vincular Lista ahora
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2.5 pt-1">
              {connectedLists.map((listItem) => {
                const listId = listItem.id;
                const listName = listItem.nombre || listItem.id;
                const leadCount = listItem.total_leads || 0;

                return (
                  <div
                    key={listId}
                    className="p-2.5 rounded-lg bg-[#0D0E12] border border-white/[0.06] flex items-center justify-between gap-2 hover:border-white/[0.14] transition"
                  >
                    <div className="min-w-0">
                      <div className="font-medium text-xs text-zinc-200 truncate">
                        {listName}
                      </div>
                      <div className="text-[10px] text-zinc-500 flex items-center gap-1.5 mt-0.5">
                        <span className="font-mono text-zinc-400">{leadCount} prospectos</span>
                        <span>&bull;</span>
                        <span className="text-emerald-400 font-mono">Auto-ingreso activo</span>
                      </div>
                    </div>

                    <button
                      onClick={() => handleDisconnectList(listId)}
                      className="p-1 rounded text-zinc-500 hover:text-red-400 hover:bg-red-950/20 transition cursor-pointer shrink-0"
                      title="Desvincular esta lista de la secuencia"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 6. Barra de Ejecución Siguiente Paso Manual (si hay prospecto listo) */}
        {candidateLead && (
          <div className="p-3 rounded-xl bg-sky-950/20 border border-sky-500/20 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-lg bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400 shrink-0">
                <Clock className="w-3.5 h-3.5" />
              </div>
              <div>
                <span className="text-zinc-400">Próximo prospecto listo para ejecutar: </span>
                <strong className="text-zinc-100">{candidateLead.nombre}</strong>
                <span className="font-mono text-sky-400 ml-1.5">➔ Paso #{candidateLead.paso_actual || 1}</span>
              </div>
            </div>
            <button
              onClick={handleExecuteNextStep}
              disabled={executingStep}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 text-xs font-semibold shadow-sm transition cursor-pointer disabled:opacity-50 shrink-0"
            >
              <Play className={`w-3.5 h-3.5 ${executingStep ? 'animate-spin' : 'fill-current'}`} />
              <span>{executingStep ? 'Procesando...' : 'Ejecutar Paso Ahora'}</span>
            </button>
          </div>
        )}

        {/* 7. Lienzo Visual del Árbol de Decisión / Flujo */}
        <div className="rounded-xl border border-white/[0.08] bg-[#121316] p-5 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-white/[0.06] pb-3">
            <div>
              <h3 className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
                <span>Árbol de Decisión Multicanal</span>
                <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-zinc-900 border border-white/[0.06] text-zinc-400">
                  {steps.length} pasos
                </span>
              </h3>
              <p className="text-[11px] text-zinc-400 mt-0.5">
                Haz clic en cualquier tarjeta de paso para editar mensajes, Spintax o tiempos de espera.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => setAddStepModalConfig({ position: 'inicio' })}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-750 text-xs text-zinc-200 border border-zinc-700/60 transition cursor-pointer"
              >
                <Plus className="w-3.5 h-3.5 text-zinc-400" />
                <span>+ Paso al Inicio</span>
              </button>
              <button
                onClick={() => setAddStepModalConfig({ position: 'final' })}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 text-xs font-medium transition cursor-pointer shadow-sm"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>+ Paso al Final</span>
              </button>
            </div>
          </div>

          {/* Renderizado de Nodos del Árbol en Cadena */}
          <div className="flex flex-col items-center py-4 space-y-4">
            {steps.map((step, idx) => {
              const isWhatsApp = (step.tipo || step.tipo_accion || '').includes('WHATSAPP');
              const isLinkedIn = !isWhatsApp && ((step.tipo || '').includes('LINKEDIN') || (step.tipo || '').includes('PERFIL') || (step.tipo || '').includes('INVITACION'));
              const isExtraction = (step.tipo || '').includes('EXTRAER') || (step.tipo || '').includes('RESOLVER');
              const isEmail = !isExtraction && ((step.tipo || '').includes('WORKSPACE') || (step.tipo || '').includes('CORREO'));
              const isDelay = (step.tipo || step.tipo_accion) === 'ESPERAR';

              const borderAccent = isWhatsApp
                ? 'border-emerald-500/40 hover:border-emerald-400 bg-emerald-950/20'
                : isExtraction
                ? 'border-cyan-500/40 hover:border-cyan-400 bg-cyan-950/20'
                : isLinkedIn 
                ? 'border-sky-500/30 hover:border-sky-400 bg-sky-950/15' 
                : isEmail 
                ? 'border-indigo-500/30 hover:border-indigo-400 bg-indigo-950/15' 
                : isDelay 
                ? 'border-amber-500/30 hover:border-amber-400 bg-amber-950/15' 
                : 'border-purple-500/30 hover:border-purple-400 bg-zinc-900/60';

              return (
                <React.Fragment key={step.id || idx}>
                  {idx > 0 && (
                    <div className="flex flex-col items-center my-2">
                      <div className={`w-0.5 h-3 ${step.leads_en_paso > 0 ? (isDelay ? 'bg-amber-500/60' : 'bg-sky-500/60') : 'bg-zinc-700/60'}`} />
                      
                      {isDelay ? (
                        /* Conector entrando a un Paso de Espera (Transición directa, sin colas previas) */
                        <div className="px-3 py-1 rounded-full bg-zinc-900/90 border border-amber-500/30 text-[10px] font-mono text-zinc-300 flex items-center gap-1.5 shadow-xs">
                          <Clock className="w-3 h-3 text-amber-400/90" />
                          <span className="text-zinc-400">Transición directa a espera estratégica</span>
                        </div>
                      ) : (
                        /* Conector entrando a un Paso de Acción (LinkedIn / WhatsApp / Email con colas antiban) */
                        step.leads_en_paso > 0 ? (
                          <div className="px-3.5 py-1.5 rounded-full bg-[#161B26] border border-sky-500/40 text-[11px] font-mono text-zinc-200 flex items-center gap-2 shadow-md">
                            <span className="relative flex h-2 w-2">
                              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75"></span>
                              <span className="relative inline-flex rounded-full h-2 w-2 bg-sky-500"></span>
                            </span>
                            <span className="font-bold text-sky-300">{step.leads_en_paso}</span>
                            <span className="text-zinc-300">
                              {step.leads_en_paso === 1 ? 'prospecto en cola antiban' : 'prospectos en cola antiban'}
                            </span>
                            {step.leads_listos > 0 && (
                              <span className="px-1.5 py-0.2 rounded bg-emerald-950 text-emerald-400 border border-emerald-500/30 text-[10px]">
                                {step.leads_listos} {step.leads_listos === 1 ? 'listo' : 'listos'}
                              </span>
                            )}
                            {step.leads_en_espera > 0 && (
                              <span className="px-1.5 py-0.2 rounded bg-amber-950 text-amber-400 border border-amber-500/30 text-[10px]">
                                {step.leads_en_espera} {step.leads_en_espera === 1 ? 'enfriando' : 'enfriando'}
                              </span>
                            )}
                          </div>
                        ) : (
                          <div className="px-3 py-0.5 rounded-full bg-zinc-900 border border-zinc-800 text-[10px] font-mono text-zinc-500 flex items-center gap-1.5">
                            <ArrowRight className="w-3 h-3 text-zinc-600" />
                            <span>0 prospectos en transición en este momento</span>
                          </div>
                        )
                      )}

                      <div className={`w-0.5 h-3 ${step.leads_en_paso > 0 ? (isDelay ? 'bg-amber-500/60' : 'bg-sky-500/60') : 'bg-zinc-700/60'}`} />
                      <div className={`w-2 h-2 rotate-45 border-b-2 border-r-2 -mt-1 ${step.leads_en_paso > 0 ? (isDelay ? 'border-amber-400' : 'border-sky-400') : 'border-zinc-600'}`} />
                    </div>
                  )}

                  <div
                    onClick={() => setSelectedStepToEdit(step)}
                    className={`w-full max-w-xl p-4 rounded-xl border ${borderAccent} transition cursor-pointer shadow-sm group hover:scale-[1.01] space-y-3`}
                  >
                    {/* Fila Superior: Título, Tipo y Badges */}
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <span className="w-7 h-7 rounded-lg bg-zinc-800 font-mono text-xs font-semibold text-zinc-300 flex items-center justify-center border border-zinc-700 shrink-0">
                          {idx + 1}
                        </span>
                        <div className="min-w-0">
                          <div className="text-xs sm:text-sm font-semibold text-zinc-100 group-hover:text-white transition truncate">
                            {step.etiqueta || step.tipo}
                          </div>
                          <span className="text-[10px] font-mono text-zinc-400 truncate block">{step.tipo}</span>
                        </div>
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
                        {step.condicion_rama && step.condicion_rama !== 'DEFAULT' && (
                          <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-medium border ${
                            step.condicion_rama === 'SI_ACEPTO' 
                              ? 'bg-emerald-950/80 text-emerald-400 border-emerald-500/40' 
                              : 'bg-amber-950/80 text-amber-400 border-amber-500/40'
                          }`}>
                            Rama: {step.condicion_rama}
                          </span>
                        )}
                        {isDelay && (
                          <span className="px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 text-[10px] font-mono border border-amber-500/20">
                            {step.parametros?.horas_espera ?? step.parametros?.horas ?? 24}h espera
                          </span>
                        )}
                        <Edit3 className="w-3.5 h-3.5 text-zinc-500 group-hover:text-zinc-300 transition" />
                      </div>
                    </div>

                    {/* Fila Inferior: Representación de la Etapa en Este Momento */}
                    {step.leads_en_paso === 0 ? (
                      <div className="pt-2 border-t border-white/[0.06] flex items-center justify-between text-xs">
                        <div className="flex items-center gap-2 text-zinc-500">
                          <span className="w-2 h-2 rounded-full bg-zinc-700"></span>
                          <span className="font-mono text-[11px]">
                            {isDelay ? 'Sin prospectos en espera en este momento' : 'Cola vacía en este momento'}
                          </span>
                        </div>
                        <span className="text-[10px] text-zinc-600 font-mono">0 en etapa</span>
                      </div>
                    ) : (
                      <div className="pt-2.5 border-t border-white/[0.06] space-y-2">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="relative flex h-2.5 w-2.5">
                              <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${isDelay ? 'bg-amber-400' : 'bg-sky-400'}`}></span>
                              <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${isDelay ? 'bg-amber-500' : 'bg-sky-500'}`}></span>
                            </span>
                            <span className="text-xs font-semibold text-zinc-200">
                              {isDelay ? 'En período de espera estratégica:' : 'En esta etapa en este momento:'}
                            </span>
                          </div>
                          <div className="flex items-center gap-1.5 font-mono">
                            <span className={`text-sm font-bold ${isDelay ? 'text-amber-300' : 'text-sky-300'}`}>{step.leads_en_paso}</span>
                            <span className="text-[11px] text-zinc-400">
                              {isDelay ? 'cumpliendo pausa' : 'prospectos en cola'}
                            </span>
                          </div>
                        </div>

                        {isDelay ? (
                          <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                            <div className={`p-2 rounded-lg border flex flex-col justify-between ${
                              step.leads_en_espera > 0 
                                ? 'bg-amber-950/40 border-amber-500/30 text-amber-200' 
                                : 'bg-zinc-900/60 border-zinc-800 text-zinc-500'
                            }`}>
                              <div className="flex items-center justify-between text-[10px] uppercase font-sans">
                                <span className="font-medium text-amber-400/90 flex items-center gap-1">
                                  <Clock className="w-3 h-3 text-amber-400" />
                                  Temporizador activo
                                </span>
                                <span className="font-bold text-amber-300 text-xs">{step.leads_en_espera || 0}</span>
                              </div>
                              <span className="text-[9px] text-zinc-400 font-sans mt-1">
                                {step.leads_en_espera > 0 ? `Cumpliendo las ${step.parametros?.horas_espera ?? step.parametros?.horas ?? 24}h de espera` : 'Ninguno en espera activa'}
                              </span>
                            </div>

                            <div className={`p-2 rounded-lg border flex flex-col justify-between ${
                              step.leads_listos > 0 
                                ? 'bg-emerald-950/40 border-emerald-500/30 text-emerald-200' 
                                : 'bg-zinc-900/60 border-zinc-800 text-zinc-500'
                            }`}>
                              <div className="flex items-center justify-between text-[10px] uppercase font-sans">
                                <span className="font-medium text-emerald-400/90 flex items-center gap-1">
                                  <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                                  Espera cumplida
                                </span>
                                <span className="font-bold text-emerald-300 text-xs">{step.leads_listos || 0}</span>
                              </div>
                              <span className="text-[9px] text-zinc-400 font-sans mt-1">
                                {step.leads_listos > 0 ? 'Plazo finalizado, listos para avanzar' : 'Aguardando fin de plazo'}
                              </span>
                            </div>
                          </div>
                        ) : (
                          <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                            <div className={`p-2 rounded-lg border flex flex-col justify-between ${
                              step.leads_listos > 0 
                                ? 'bg-emerald-950/40 border-emerald-500/30 text-emerald-200' 
                                : 'bg-zinc-900/60 border-zinc-800 text-zinc-500'
                            }`}>
                              <div className="flex items-center justify-between text-[10px] uppercase font-sans">
                                <span className="font-medium text-emerald-400/90 flex items-center gap-1">
                                  <Zap className="w-3 h-3 text-emerald-400" />
                                  Listos para envío
                                </span>
                                <span className="font-bold text-emerald-300 text-xs">{step.leads_listos || 0}</span>
                              </div>
                              <span className="text-[9px] text-zinc-400 font-sans mt-1">
                                {step.leads_listos > 0 ? 'Plazo cumplido, aguardando cupo antiban' : 'Ninguno listo ahora'}
                              </span>
                            </div>

                            <div className={`p-2 rounded-lg border flex flex-col justify-between ${
                              step.leads_en_espera > 0 
                                ? 'bg-amber-950/40 border-amber-500/30 text-amber-200' 
                                : 'bg-zinc-900/60 border-zinc-800 text-zinc-500'
                            }`}>
                              <div className="flex items-center justify-between text-[10px] uppercase font-sans">
                                <span className="font-medium text-amber-400/90 flex items-center gap-1">
                                  <Clock className="w-3 h-3 text-amber-400" />
                                  Pausa estocástica
                                </span>
                                <span className="font-bold text-amber-300 text-xs">{step.leads_en_espera || 0}</span>
                              </div>
                              <span className="text-[9px] text-zinc-400 font-sans mt-1">
                                {step.leads_en_espera > 0 ? 'Pausa humana de seguridad entre acciones' : 'Sin pausa pendiente'}
                              </span>
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </React.Fragment>
              );
            })}
          </div>
        </div>

        {/* 8. Tabla de leads actualmente inscritos en la secuencia con opciones avanzadas */}
        <div className="rounded-xl border border-white/[0.08] bg-[#121316] overflow-hidden space-y-0">
          {/* Header de la Tabla y Filtros */}
          <div className="p-4 border-b border-white/[0.06] flex flex-col md:flex-row md:items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-xs font-semibold text-zinc-100 uppercase tracking-wider">
                  Prospectos en el Flujo de la Secuencia
                </h3>
                <span className="px-2 py-0.5 rounded-full bg-zinc-800 text-[10px] font-mono text-zinc-300 border border-zinc-700">
                  {filteredEnrolledLeads.length} de {enrolledLeads.length}
                </span>
              </div>
              <p className="text-[11px] text-zinc-400 mt-0.5">
                Haz clic en cualquier prospecto para ver su ficha completa, notas, historial multicanal y cruce de datos.
              </p>
            </div>

            {/* Filtros internos y búsqueda */}
            <div className="flex items-center gap-2 flex-wrap">
              <div className="relative">
                <Search className="w-3.5 h-3.5 text-zinc-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={leadSearchTerm}
                  onChange={(e) => setLeadSearchTerm(e.target.value)}
                  placeholder="Buscar lead, cargo, email..."
                  className="bg-[#0D0E12] border border-white/[0.08] pl-8 pr-3 py-1.5 rounded-lg text-xs text-zinc-100 placeholder-zinc-500 w-48 sm:w-60 focus:outline-none focus:border-zinc-500"
                />
              </div>

              <select
                value={leadStatusFilter}
                onChange={(e) => setLeadStatusFilter(e.target.value)}
                className="bg-[#0D0E12] border border-white/[0.08] px-2.5 py-1.5 rounded-lg text-xs text-zinc-200 focus:outline-none focus:border-zinc-500 cursor-pointer"
              >
                <option value="TODOS">Todos los estados</option>
                <option value="LISTOS">⚡ Listos para envío</option>
                <option value="TEMPORIZADOR">⏱️ Enfriamiento activo</option>
                <option value="COMPLETADO">✓ Completaron secuencia</option>
                <option value="CON_EMAIL">Con email corporativo</option>
                <option value="SIN_EMAIL">Sin email resuelto</option>
                <option value="ZOHO_SINCRONIZADO">Cruzados con Zoho CRM</option>
              </select>

              <button
                onClick={handleSyncAcceptedConnections}
                disabled={syncingConnections}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-medium border border-zinc-700 transition cursor-pointer disabled:opacity-50"
                title="Sincronizar y auditar conexiones aceptadas desde LinkedIn"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${syncingConnections ? 'animate-spin text-teal-400' : ''}`} />
                <span className="hidden sm:inline">Auditar Conexiones</span>
              </button>
            </div>
          </div>

          {/* Barra de Acciones en Lote (cuando hay seleccionados) */}
          {selectedLeadIds.size > 0 && (
            <div className="p-3 bg-gradient-to-r from-sky-950/40 via-zinc-900 to-emerald-950/40 border-b border-sky-500/30 flex items-center justify-between gap-3 flex-wrap animate-fadeIn">
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded-md bg-sky-500/20 text-sky-300 font-mono text-xs font-semibold border border-sky-500/30">
                  {selectedLeadIds.size} seleccionados
                </span>
                <span className="text-xs text-zinc-300">Acciones masivas de prospección:</span>
              </div>

              <div className="flex items-center gap-2">
                {/* Cascada de Correo */}
                <button
                  onClick={handleBatchResolveEmails}
                  disabled={isBatchResolvingEmail}
                  className="flex items-center gap-1.5 px-3 py-1 rounded-md bg-emerald-950/70 hover:bg-emerald-900/80 text-emerald-300 border border-emerald-500/30 text-xs font-medium transition cursor-pointer disabled:opacity-50"
                  title="Resolver correos corporativos en cascada (Waterfall + DNS MX + SMTP)"
                >
                  <Mail className={`w-3.5 h-3.5 ${isBatchResolvingEmail ? 'animate-spin' : ''}`} />
                  <span>{isBatchResolvingEmail ? 'Resolviendo...' : 'Resolver Correo en Cascada'}</span>
                </button>

                <button
                  onClick={() => setSelectedLeadIds(new Set())}
                  className="px-2.5 py-1 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-zinc-200 text-xs transition cursor-pointer"
                >
                  Deseleccionar
                </button>
              </div>
            </div>
          )}

          {/* Tabla Unificada de Prospectos en Secuencia */}
          <UnifiedLeadsTable
            data={filteredEnrolledLeads}
            context="sequence"
            loading={loadingData}
            onOpenLead={(lead) => setSelectedLeadForModal({ ...lead, id: lead.id || lead.lead_id })}
            selectedLeadIds={selectedLeadIds}
            onToggleLead={handleToggleSelectLead}
            onToggleSelectAll={() => handleToggleSelectAllLeads(filteredEnrolledLeads)}
            onSyncLinkedIn={async (e, lead) => {
              if (e && e.stopPropagation) e.stopPropagation();
              const leadId = lead.id || lead.lead_id;
              if (!leadId) return;
              try {
                setSyncingLeadIds((prev) => new Set(prev).add(leadId));
                const res = await syncLeadWithLinkedIn(leadId);
                if (res && res.lead) {
                  setEnrolledLeads((prev) =>
                    prev.map((l) =>
                      (l.id === leadId || l.lead_id === leadId) ? { ...l, ...res.lead } : l
                    )
                  );
                }
              } catch (err) {
                alert(`Error sincronizando prospecto con LinkedIn: ${err.message}`);
              } finally {
                setSyncingLeadIds((prev) => {
                  const next = new Set(prev);
                  next.delete(leadId);
                  return next;
                });
              }
            }}
            onResolveEmail={(e, lead) => handleResolveLeadEmail(e, lead)}
            syncingLeadIds={syncingLeadIds}
            resolvingLeadIds={resolvingLeadIds}
            actionInProgress={isBatchResolvingEmail}
            clientSidePagination={true}
            pageSize={25}
            emptyTitle={
              enrolledLeads.length === 0
                ? 'No hay prospectos asignados a esta secuencia aún'
                : 'No se encontraron prospectos con los filtros aplicados'
            }
            emptySubtitle={
              enrolledLeads.length === 0
                ? 'Usa el botón "Asignar Cola" arriba para inscribir prospectos de las listas vinculadas.'
                : 'Prueba limpiando la búsqueda o el filtro de estado.'
            }
          />
        </div>

        {/* Modales contextuales de la vista de detalle */}
        {selectedStepToEdit && (
          <EditStepModal
            step={selectedStepToEdit}
            onClose={() => setSelectedStepToEdit(null)}
            onSave={handleSaveEditedStep}
            onDelete={handleDeleteStep}
          />
        )}

        {addStepModalConfig && (
          <AddStepModal
            initialPosition={addStepModalConfig.position}
            existingSteps={steps}
            onClose={() => setAddStepModalConfig(null)}
            onAdd={handleAddStep}
          />
        )}

        {showConnectListModal && activeSequence && (
          <ConnectListModal
            sequenceId={activeSequence.id}
            leadLists={leadLists}
            connectedListIds={connectedLists.map((l) => l.id)}
            onClose={() => setShowConnectListModal(false)}
            onConnected={loadData}
          />
        )}

        {/* Modal interactivo de Ficha Completa del Prospecto */}
        {selectedLeadForModal && (
          <LeadModal
            prospect={selectedLeadForModal}
            lead={selectedLeadForModal}
            onClose={() => setSelectedLeadForModal(null)}
            onUpdated={handleLeadUpdatedInSequence}
            onLeadUpdated={handleLeadUpdatedInSequence}
          />
        )}
      </div>
    );
  }

  // ============================================================
  // RENDER B: VISTA POR DEFECTO - DIRECTORIO GLOBAL DE SECUENCIAS
  // ============================================================
  return (
    <div className="space-y-6 font-sans">
      {/* 1. Header Principal del Directorio */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-white/[0.06] pb-4">
        <div>
          <h1 className="text-base font-semibold text-zinc-100 flex items-center gap-2">
            <GitFork className="w-4 h-4 text-zinc-400" />
            <span>Secuencias de Prospección</span>
          </h1>
          <p className="text-xs text-zinc-400 mt-0.5">
            Automatiza toques multicanal (LinkedIn, WhatsApp y Correo) respetando límites de seguridad antiban.
          </p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {/* Botón Crear Secuencia */}
          <button
            onClick={() => setShowNewSequenceModal(true)}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-semibold text-xs transition cursor-pointer shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Nueva Secuencia</span>
          </button>
        </div>
      </div>

      {/* Banner Interactivo de Control y Telemetría en Tiempo Real del Piloto Automático */}
      <AutopilotBanner
        workerState={workerState}
        onToggleAutopilot={handleToggleAutopilot}
        togglingAutopilot={togglingAutopilot}
        onForceNext={handleForceNext}
        isForcingNext={isForcingNext}
      />

      {/* 2. Bloque Superior de Métricas Consolidadas del Grupo */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3.5">
        <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
          <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
            <span className="font-medium text-zinc-300">Total Secuencias</span>
            <GitFork className="w-3.5 h-3.5 text-zinc-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">
            {globalStats.total}
          </div>
          <span className="text-[10px] text-zinc-500 mt-1 flex items-center gap-1.5 flex-wrap">
            {globalStats.publicadas > 0 ? (
              <span className="text-emerald-400 font-medium flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                <span>{globalStats.publicadas} en ejecución</span>
              </span>
            ) : (
              <span className="text-zinc-500">Motor en reposo</span>
            )}
            <span>&bull;</span>
            <span>{globalStats.pausadas} pausadas</span>
            <span>&bull;</span>
            <span>{globalStats.borradores} borrador</span>
          </span>
        </div>

        <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
          <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
            <span className="font-medium text-zinc-300">Prospectos en Flujos</span>
            <Users className="w-3.5 h-3.5 text-sky-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">
            {globalStats.leadsEnCurso}
          </div>
          <span className="text-[10px] text-zinc-500 mt-1 block">Avanzando en pasos de outreach</span>
        </div>

        <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
          <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
            <span className="font-medium text-zinc-300">Ciclos Completados</span>
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">
            {globalStats.leadsCompletados}
          </div>
          <span className="text-[10px] text-zinc-500 mt-1 block">Flujos finalizados exitosamente</span>
        </div>

        <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
          <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
            <span className="font-medium text-zinc-300">Capacidad Antiban</span>
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">
            {metrics.hoy || 0} <span className="text-xs text-zinc-500 font-normal">/ {metrics.limite_diario || 15} máx hoy ({metrics.semana_warmup || 'Semana 1'})</span>
          </div>
          <span className="text-[10px] text-zinc-500 mt-1 block font-mono">
            {globalStats.leadsEnCursoActivas} en cola de despacho total
          </span>
        </div>
      </div>

      {/* 3. Filtros por Estado y Búsqueda */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-1">
        {/* Pestañas de filtrado */}
        <div className="flex items-center gap-1 bg-[#121316] p-1 rounded-lg border border-white/[0.06] text-xs">
          <button
            onClick={() => setFilterStatus('TODAS')}
            className={`px-3 py-1 rounded-md transition cursor-pointer ${
              filterStatus === 'TODAS'
                ? 'bg-zinc-800 text-zinc-100 font-medium'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            Todas ({globalStats.total})
          </button>
          <button
            onClick={() => setFilterStatus('PUBLICADA')}
            className={`px-3 py-1 rounded-md transition cursor-pointer ${
              filterStatus === 'PUBLICADA'
                ? 'bg-zinc-800 text-emerald-400 font-medium'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            En Marcha ({globalStats.publicadas})
          </button>
          <button
            onClick={() => setFilterStatus('PAUSADA')}
            className={`px-3 py-1 rounded-md transition cursor-pointer ${
              filterStatus === 'PAUSADA'
                ? 'bg-zinc-800 text-amber-300 font-medium'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            Pausadas ({globalStats.pausadas})
          </button>
          <button
            onClick={() => setFilterStatus('BORRADOR')}
            className={`px-3 py-1 rounded-md transition cursor-pointer ${
              filterStatus === 'BORRADOR'
                ? 'bg-zinc-800 text-zinc-200 font-medium'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            Borradores ({globalStats.borradores})
          </button>
        </div>

        {/* Input de Búsqueda */}
        <div className="relative min-w-[220px]">
          <Search className="w-3.5 h-3.5 text-zinc-500 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Buscar secuencia..."
            className="w-full pl-8 pr-3 py-1.5 bg-[#121316] border border-white/[0.08] rounded-lg text-xs text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
          />
        </div>
      </div>

      {/* 4. Grid de Tarjetas de Secuencias */}
      {loading ? (
        <div className="p-12 text-center text-zinc-500 text-xs font-mono">
          Cargando secuencias...
        </div>
      ) : filteredSequences.length === 0 ? (
        <div className="p-12 rounded-xl border border-white/[0.08] bg-[#121316] text-center space-y-3">
          <div className="w-10 h-10 rounded-xl bg-white/[0.04] border border-white/[0.08] mx-auto flex items-center justify-center text-zinc-400">
            <GitFork className="w-5 h-5" />
          </div>
          <div className="space-y-1">
            <h3 className="text-xs font-semibold text-zinc-200">No se encontraron secuencias</h3>
            <p className="text-[11px] text-zinc-500 max-w-sm mx-auto">
              {searchTerm || filterStatus !== 'TODAS'
                ? 'No hay secuencias que coincidan con los criterios de búsqueda seleccionados.'
                : 'Crea tu primera secuencia de prospección automatizada para comenzar.'}
            </p>
          </div>
          {filterStatus !== 'TODAS' || searchTerm ? (
            <button
              onClick={() => { setFilterStatus('TODAS'); setSearchTerm(''); }}
              className="text-xs text-sky-400 hover:underline cursor-pointer"
            >
              Limpiar filtros
            </button>
          ) : (
            <button
              onClick={() => setShowNewSequenceModal(true)}
              className="px-3.5 py-1.5 rounded-lg bg-white hover:bg-zinc-200 text-zinc-950 font-semibold text-xs transition cursor-pointer shadow-sm"
            >
              + Crear Nueva Secuencia
            </button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
          {filteredSequences.map((seq) => {
            const seqStatus = (seq.estado || (seq.activa ? 'PUBLICADA' : 'BORRADOR')).toUpperCase();
            const isPub = seqStatus === 'PUBLICADA' && Boolean(seq.activa);
            const isPau = seqStatus === 'PAUSADA';
            const isDraft = !isPub && !isPau;

            const totalSteps = seq.pasos?.length || seq.total_pasos || 0;
            const inProgressLeads = seq.leads_en_curso || (seq.leads_inscritos?.length || 0);
            const associatedListsCount = seq.listas_asociadas?.length || seq.listas_conectadas?.length || 0;

            return (
              <div
                key={seq.id}
                onClick={() => setSelectedSeqId(seq.id)}
                className="p-4 rounded-xl bg-[#121316] border border-white/[0.08] hover:border-white/[0.18] transition flex flex-col justify-between space-y-3 cursor-pointer group shadow-xs"
              >
                <div className="space-y-2">
                  {/* Fila Superior: Título & Estado Único */}
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="text-xs font-semibold text-zinc-100 group-hover:text-white transition truncate">
                      {seq.nombre}
                    </h3>

                    {/* Badge de Estado Simple */}
                    {isPub ? (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-mono border font-medium bg-emerald-950/40 text-emerald-400 border-emerald-500/30 shrink-0 flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
                        <span>Publicada</span>
                      </span>
                    ) : isPau ? (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-mono border font-medium bg-amber-950/40 text-amber-300 border-amber-500/30 shrink-0 flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
                        <span>Pausada</span>
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-mono border font-medium bg-zinc-800 text-zinc-400 border-zinc-700/60 shrink-0 flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-zinc-500 shrink-0" />
                        <span>Borrador</span>
                      </span>
                    )}
                  </div>

                  <p className="text-[11px] text-zinc-400 line-clamp-2 leading-relaxed">
                    {seq.descripcion || 'Secuencia de outreach multicanal con reglas automáticas de avance.'}
                  </p>

                  {/* Resumen de Tags / Métricas */}
                  <div className="flex items-center gap-2 pt-1 text-[11px] text-zinc-400 flex-wrap">
                    <span className="px-2 py-0.5 rounded bg-[#0D0E12] border border-white/[0.06] font-mono text-[10px] text-zinc-300">
                      {totalSteps} pasos
                    </span>
                    <span className="px-2 py-0.5 rounded bg-[#0D0E12] border border-white/[0.06] font-mono text-[10px] text-sky-400">
                      {inProgressLeads} leads en curso
                    </span>
                    <span className="px-2 py-0.5 rounded bg-[#0D0E12] border border-white/[0.06] font-mono text-[10px] text-zinc-400">
                      {associatedListsCount} {associatedListsCount === 1 ? 'lista' : 'listas'}
                    </span>
                  </div>
                </div>

                {/* Footer de la tarjeta con acción rápida */}
                <div className="pt-2.5 border-t border-white/[0.06] flex items-center justify-between gap-2 text-xs">
                  <span className="text-zinc-400 group-hover:text-zinc-200 transition font-medium flex items-center gap-1 text-[11px]">
                    <span>Gestionar Flujo</span>
                    <ChevronRight className="w-3.5 h-3.5 text-zinc-500 group-hover:translate-x-0.5 transition" />
                  </span>

                  {/* Botón de acción rápida sin entrar al flujo */}
                  <div onClick={(e) => e.stopPropagation()} className="flex items-center gap-1.5">
                    {isDraft ? (
                      <button
                        onClick={() => handleSetSequenceStatus(seq.id, 'PUBLICADA')}
                        className="px-2.5 py-1 rounded bg-emerald-950/60 hover:bg-emerald-900/60 text-emerald-400 border border-emerald-500/30 text-[10px] font-semibold transition cursor-pointer"
                        title="Publicar secuencia inmediatamente"
                      >
                        Publicar
                      </button>
                    ) : isPub ? (
                      <button
                        onClick={() => handleSetSequenceStatus(seq.id, 'PAUSADA')}
                        className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-750 text-amber-300 border border-amber-500/20 text-[10px] font-medium transition cursor-pointer"
                        title="Pausar secuencia"
                      >
                        Pausar
                      </button>
                    ) : (
                      <button
                        onClick={() => handleSetSequenceStatus(seq.id, 'PUBLICADA')}
                        className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-750 text-emerald-400 border border-emerald-500/20 text-[10px] font-medium transition cursor-pointer"
                        title="Reanudar secuencia"
                      >
                        Reanudar
                      </button>
                    )}

                    <button
                      onClick={(e) => handleDeleteSequence(seq.id, seq.nombre, e)}
                      disabled={deletingSeqId === seq.id}
                      className="p-1 rounded hover:bg-red-950/40 text-zinc-500 hover:text-red-400 border border-transparent hover:border-red-500/20 transition cursor-pointer"
                      title="Eliminar permanentemente esta secuencia"
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

      {/* Modal para Crear Nueva Secuencia */}
      {showNewSequenceModal && (
        <NewSequenceModal
          onClose={() => setShowNewSequenceModal(false)}
          onCreated={handleSequenceCreated}
          activeTenantWorkspace={activeTenantWorkspace}
        />
      )}
    </div>
  );
}
