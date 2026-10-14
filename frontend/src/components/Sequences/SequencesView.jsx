// Vista avanzada del gestor de secuencias multicanal con árbol interactivo, telemetría y ejecución en tiempo real
import React, { useState, useEffect } from 'react';
import { 
  GitFork, 
  Plus, 
  Play, 
  Pause, 
  Link2, 
  Clock, 
  Users, 
  CheckCircle2, 
  Edit3, 
  Trash2, 
  RefreshCw, 
  CornerDownRight, 
  Mail, 
  MessageSquare, 
  Eye, 
  Compass, 
  Layers,
  ChevronRight,
  ListPlus,
  Zap,
  AlertCircle
} from 'lucide-react';
import { 
  fetchSequences, 
  fetchLeadLists, 
  updateSequence, 
  addSequenceStep,
  deleteSequenceStep,
  toggleSequencePublish, 
  disconnectListFromSequence, 
  assignEnqueuedLeads, 
  executeSequenceNextStep,
  fetchWorkerState,
  toggleAutopilot,
  fetchBrowserStatus,
  showWorkBrowser
} from '../../services/api';
import EditStepModal from './EditStepModal';
import AddStepModal from './AddStepModal';
import NewSequenceModal from './NewSequenceModal';
import ConnectListModal from './ConnectListModal';

export default function SequencesView({ activeTenantWorkspace = '' }) {
  const [sequences, setSequences] = useState([]);
  const [activeSeqId, setActiveSeqId] = useState('');
  const [leadLists, setLeadLists] = useState([]);
  const [loading, setLoading] = useState(true);
  const [subView, setSubView] = useState('flujo'); // 'flujo' | 'global'

  // Modales
  const [selectedStepToEdit, setSelectedStepToEdit] = useState(null);
  const [addStepModalConfig, setAddStepModalConfig] = useState(null); // { position: 'inicio' | 'final' | 'intermedio' }
  const [showNewSequenceModal, setShowNewSequenceModal] = useState(false);
  const [showConnectListModal, setShowConnectListModal] = useState(false);

  // Action State
  const [executingStep, setExecutingStep] = useState(false);
  const [assigningLeads, setAssigningLeads] = useState(false);
  const [isAutopilotActive, setIsAutopilotActive] = useState(false);
  const [togglingAutopilot, setTogglingAutopilot] = useState(false);
  const [needsLinkedinLogin, setNeedsLinkedinLogin] = useState(false);

  useEffect(() => {
    loadData();
    const interval = setInterval(checkWorkerState, 10000);
    return () => clearInterval(interval);
  }, [activeTenantWorkspace]);

  async function checkWorkerState() {
    try {
      const state = await fetchWorkerState();
      setIsAutopilotActive(Boolean(state.piloto_automatico));
      const browser = await fetchBrowserStatus();
      setNeedsLinkedinLogin(Boolean(browser.is_electron && !browser.sesion_linkedin_activa));
    } catch {}
  }

  async function loadData() {
    try {
      setLoading(true);
      const [seqsData, listsData, workerState, browserState] = await Promise.all([
        fetchSequences(activeTenantWorkspace),
        fetchLeadLists(activeTenantWorkspace),
        fetchWorkerState().catch(() => ({ piloto_automatico: false })),
        fetchBrowserStatus().catch(() => ({})),
      ]);
      setSequences(seqsData || []);
      setLeadLists(listsData || []);
      setIsAutopilotActive(Boolean(workerState.piloto_automatico));
      setNeedsLinkedinLogin(Boolean(browserState.is_electron && !browserState.sesion_linkedin_activa));

      if (seqsData && seqsData.length > 0 && !activeSeqId) {
        setActiveSeqId(seqsData[0].id);
      }
    } catch (err) {
      console.error('Error cargando secuencias:', err);
    } finally {
      setLoading(false);
    }
  }

  async function handleToggleAutopilot() {
    try {
      setTogglingAutopilot(true);
      const res = await toggleAutopilot();
      const nextState = Boolean(res.piloto_automatico);
      setIsAutopilotActive(nextState);

      // Non-blocking sync with Electron runner if active
      try {
        await fetch(`http://127.0.0.1:9099/worker/${nextState ? 'start' : 'stop'}`, { method: 'POST' });
      } catch {}
    } catch (err) {
      alert(`Error alternando piloto automático: ${err.message}`);
    } finally {
      setTogglingAutopilot(false);
    }
  }

  const activeSequence = sequences.find((s) => s.id === activeSeqId) || sequences[0];

  async function handleTogglePublish() {
    if (!activeSequence) return;
    try {
      await toggleSequencePublish(activeSequence.id);
      await loadData();
    } catch (err) {
      alert(`Error alternando publicación: ${err.message}`);
    }
  }

  async function handleDisconnectList(listId) {
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

  if (loading && sequences.length === 0) {
    return <div className="p-12 text-center text-zinc-500 text-xs">Cargando secuencias...</div>;
  }

  if (!activeSequence) {
    return (
      <div className="p-12 rounded-xl border border-zinc-800 bg-zinc-900/20 text-center">
        <p className="text-xs text-zinc-400 mb-3">No hay secuencias registradas actualmente.</p>
        <button
          onClick={() => setShowNewSequenceModal(true)}
          className="px-4 py-2 rounded-lg bg-sky-600 text-white text-xs font-medium cursor-pointer"
        >
          Crear Primera Secuencia
        </button>
      </div>
    );
  }

  const steps = activeSequence.pasos || [];
  const enrolledLeads = activeSequence.leads_inscritos || [];
  const candidateLead = activeSequence.candidato_proximo || null;

  return (
    <div className="space-y-6">
      {/* Selector de Sub-Modo: Flujo vs Matriz Global */}
      <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
        <div className="flex items-center bg-[#0D0E12] p-0.5 rounded-md border border-white/[0.08] text-xs">
          <button
            onClick={() => setSubView('flujo')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded transition cursor-pointer ${
              subView === 'flujo'
                ? 'bg-zinc-800 text-zinc-100 font-medium shadow-xs'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <GitFork className="w-3.5 h-3.5 text-zinc-400" />
            <span>Árbol de Decisión & Flujo</span>
          </button>
          <button
            onClick={() => setSubView('global')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded transition cursor-pointer ${
              subView === 'global'
                ? 'bg-zinc-800 text-zinc-100 font-medium shadow-xs'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Layers className="w-3.5 h-3.5 text-zinc-400" />
            <span>Todas las Secuencias (Matriz Global)</span>
          </button>
        </div>

        <button
          onClick={() => setShowNewSequenceModal(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs transition cursor-pointer shadow-sm"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>Nueva Secuencia</span>
        </button>
      </div>

      {subView === 'global' ? (
        /* VISTA: MATRIZ GLOBAL DE TODAS LAS SECUENCIAS */
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/30 overflow-hidden">
          <div className="p-4 border-b border-zinc-800 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-zinc-100">Visión Global de Campañas y Secuencias</h3>
            <span className="text-xs text-zinc-400 font-mono">{sequences.length} secuencias registradas</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-zinc-950/60 border-b border-zinc-800 text-zinc-400">
                <tr>
                  <th className="py-2.5 px-4">Nombre de Secuencia</th>
                  <th className="py-2.5 px-4">Estado</th>
                  <th className="py-2.5 px-4">Listas Conectadas</th>
                  <th className="py-2.5 px-4 font-mono">Pasos</th>
                  <th className="py-2.5 px-4 font-mono">En Curso</th>
                  <th className="py-2.5 px-4 text-right">Acción</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/50">
                {sequences.map((s) => (
                  <tr key={s.id} className="hover:bg-zinc-800/20">
                    <td className="py-3 px-4 font-medium text-zinc-200">{s.nombre}</td>
                    <td className="py-3 px-4">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-mono border ${
                        s.publicada 
                          ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                          : 'bg-zinc-800 text-zinc-400 border-zinc-700'
                      }`}>
                        {s.publicada ? 'PUBLICADA' : 'PAUSADA'}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-zinc-400">
                      {(s.listas_conectadas || []).join(', ') || 'Sin listas'}
                    </td>
                    <td className="py-3 px-4 font-mono text-zinc-300">{(s.pasos || []).length}</td>
                    <td className="py-3 px-4 font-mono text-sky-400">{(s.leads_inscritos || []).length}</td>
                    <td className="py-3 px-4 text-right">
                      <button
                        onClick={() => {
                          setActiveSeqId(s.id);
                          setSubView('flujo');
                        }}
                        className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-sky-400 text-xs transition cursor-pointer"
                      >
                        Abrir Flujo
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        /* VISTA: FLUJO DETALLADO DE LA SECUENCIA SELECCIONADA */
        <div className="space-y-6">
          {/* Header de la secuencia activa */}
          <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08] flex flex-col md:flex-row md:items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div>
                <span className="text-[10px] font-mono uppercase tracking-wider text-zinc-500 block mb-0.5">
                  Secuencia Seleccionada
                </span>
                <div className="flex items-center gap-2">
                  <select
                    value={activeSeqId}
                    onChange={(e) => setActiveSeqId(e.target.value)}
                    className="bg-[#0D0E12] border border-white/[0.08] px-2.5 py-1 rounded-md text-xs font-medium text-zinc-100 focus:outline-none focus:border-zinc-500"
                  >
                    {sequences.map((s) => (
                      <option key={s.id} value={s.id}>{s.nombre}</option>
                    ))}
                  </select>

                  <span className={`px-2 py-0.5 rounded text-[10px] font-mono border ${
                    activeSequence.publicada
                      ? 'bg-emerald-950/20 text-emerald-400 border-emerald-500/20'
                      : 'bg-white/[0.04] text-zinc-400 border-white/[0.08]'
                  }`}>
                    {activeSequence.publicada ? '● PUBLICADA' : '⏸ PAUSADA'}
                  </span>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              {/* Botón Piloto Automático */}
              <button
                onClick={handleToggleAutopilot}
                disabled={togglingAutopilot}
                title="Activa o pausa el runner automático en segundo plano"
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium border transition cursor-pointer ${
                  isAutopilotActive
                    ? 'bg-amber-950/20 text-amber-300 border-amber-500/30'
                    : 'bg-[#0D0E12] text-zinc-400 border-white/[0.08] hover:text-zinc-200 hover:bg-zinc-800'
                }`}
              >
                <Zap className={`w-3.5 h-3.5 ${isAutopilotActive ? 'text-amber-400' : 'text-zinc-400'}`} />
                <span>{isAutopilotActive ? '⚡ Piloto: ACTIVO' : 'Piloto: PAUSADO'}</span>
              </button>

              {/* Botón Publicar / Pausar */}
              <button
                onClick={handleTogglePublish}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium border transition cursor-pointer ${
                  activeSequence.publicada
                    ? 'bg-[#0D0E12] text-zinc-300 border-white/[0.08] hover:bg-zinc-800'
                    : 'bg-emerald-950/20 text-emerald-300 border-emerald-500/30 hover:bg-emerald-900/30'
                }`}
              >
                {activeSequence.publicada ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                <span>{activeSequence.publicada ? 'Pausar' : 'Publicar'}</span>
              </button>

              {/* Botón Inscribir Leads en Cola */}
              <button
                onClick={handleAssignEnqueued}
                disabled={assigningLeads}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-[#0D0E12] hover:bg-zinc-800 text-zinc-300 border border-white/[0.08] text-xs font-medium transition cursor-pointer disabled:opacity-50"
              >
                <Users className="w-3.5 h-3.5 text-zinc-400" />
                <span>{assigningLeads ? 'Inscribiendo...' : 'Asignar Cola'}</span>
              </button>

              {/* Botón Ejecutar Siguiente Paso Ahora con candidato visual (Linear solid white) */}
              <button
                onClick={handleExecuteNextStep}
                disabled={executingStep}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 text-xs font-medium shadow-sm transition cursor-pointer disabled:opacity-50"
              >
                <Play className={`w-3.5 h-3.5 ${executingStep ? 'animate-spin' : ''}`} />
                <span>
                  {candidateLead
                    ? `Ejecutar: ${candidateLead.nombre || 'Lead'} ➔ Paso ${candidateLead.paso_actual || 1}`
                    : 'Ejecutar Siguiente Paso'}
                </span>
              </button>
            </div>
          </div>

          {/* Banner de Advertencia de Sesión de LinkedIn */}
          {needsLinkedinLogin && (
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3.5 rounded-xl bg-amber-950/40 border border-amber-500/40 text-xs text-amber-200">
              <div className="flex items-center gap-2.5">
                <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
                <div>
                  <p className="font-semibold text-amber-300">Sesión de LinkedIn no detectada en el navegador de trabajo</p>
                  <p className="text-[11px] text-amber-200/80">
                    Inicia sesión una sola vez en el Chromium embebido. Tu sesión quedará guardada de forma permanente en tu disco.
                  </p>
                </div>
              </div>
              <button
                onClick={() => showWorkBrowser('https://www.linkedin.com/login')}
                className="px-3.5 py-1.5 bg-amber-500 hover:bg-amber-400 text-zinc-950 font-bold rounded-lg text-xs shrink-0 cursor-pointer transition shadow-sm shadow-amber-500/20"
              >
                🔑 Iniciar Sesión en LinkedIn
              </button>
            </div>
          )}

          {/* Barra de Públicos y Listas Asignadas */}
          <div className="p-3 rounded-xl bg-zinc-900/30 border border-zinc-800 flex items-center justify-between gap-3 text-xs flex-wrap">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-zinc-400 font-medium flex items-center gap-1">
                <Link2 className="w-3.5 h-3.5 text-sky-400" />
                <span>Públicos y Listas Vinculadas:</span>
              </span>
              {((activeSequence.listas_asociadas && activeSequence.listas_asociadas.length > 0)
                ? activeSequence.listas_asociadas
                : (activeSequence.listas_conectadas || []).map(l => (typeof l === 'object' ? l : { id: l, nombre: l }))
              ).length === 0 ? (
                <span className="text-zinc-500 italic text-[11px]">Ninguna lista vinculada aún</span>
              ) : (
                ((activeSequence.listas_asociadas && activeSequence.listas_asociadas.length > 0)
                  ? activeSequence.listas_asociadas
                  : (activeSequence.listas_conectadas || []).map(l => (typeof l === 'object' ? l : { id: l, nombre: l }))
                ).map((listItem) => {
                  const listId = listItem.id;
                  const listName = listItem.nombre || listItem.id;
                  return (
                    <span
                      key={listId}
                      className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-zinc-800 border border-zinc-700 text-zinc-300 text-[11px] font-mono"
                    >
                      <span>{listName}</span>
                      <button
                        onClick={() => handleDisconnectList(listId)}
                        className="hover:text-rose-400 transition cursor-pointer text-sm font-bold leading-none"
                        title="Desvincular lista"
                      >
                        &times;
                      </button>
                    </span>
                  );
                })
              )}
            </div>

            <button
              onClick={() => setShowConnectListModal(true)}
              className="flex items-center gap-1 text-[11px] font-medium text-sky-400 hover:text-sky-300 transition cursor-pointer"
            >
              <Plus className="w-3 h-3" />
              <span>Conectar Lista</span>
            </button>
          </div>

          {/* 4 KPIs de la Secuencia */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3.5">
            <div className="p-4 rounded-xl bg-zinc-900/50 border border-zinc-800">
              <div className="flex items-center justify-between text-zinc-400 text-xs mb-2">
                <span>Pasos del Árbol</span>
                <GitFork className="w-4 h-4 text-sky-400" />
              </div>
              <div className="text-2xl font-bold font-mono text-zinc-100">{steps.length}</div>
              <span className="text-[10px] text-zinc-500 mt-1 block">Acciones y bifurcaciones</span>
            </div>

            <div className="p-4 rounded-xl bg-zinc-900/50 border border-zinc-800">
              <div className="flex items-center justify-between text-zinc-400 text-xs mb-2">
                <span>Leads Asignados</span>
                <Users className="w-4 h-4 text-indigo-400" />
              </div>
              <div className="text-2xl font-bold font-mono text-zinc-100">{enrolledLeads.length}</div>
              <span className="text-[10px] text-indigo-400 mt-1 block font-medium">En curso por el flujo</span>
            </div>

            <div className="p-4 rounded-xl bg-zinc-900/50 border border-zinc-800">
              <div className="flex items-center justify-between text-zinc-400 text-xs mb-2">
                <span>Próxima Acción Lista</span>
                <Clock className="w-4 h-4 text-amber-400" />
              </div>
              <div className="text-sm font-semibold text-zinc-200 truncate">
                {candidateLead ? candidateLead.nombre : 'Ninguno en cola'}
              </div>
              <span className="text-[10px] text-zinc-500 mt-1 block font-mono">
                {candidateLead ? `Paso #${candidateLead.paso_actual || 1}` : 'En espera'}
              </span>
            </div>

            <div className="p-4 rounded-xl bg-zinc-900/50 border border-zinc-800">
              <div className="flex items-center justify-between text-zinc-400 text-xs mb-2">
                <span>Completados</span>
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              </div>
              <div className="text-2xl font-bold font-mono text-zinc-100">
                {activeSequence.leads_completados_count || 0}
              </div>
              <span className="text-[10px] text-emerald-400 mt-1 block font-medium">Ciclo finalizado</span>
            </div>
          </div>

          {/* Lienzo Visual del Árbol de Decisión / Flujo */}
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/30 p-5 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-zinc-100">Árbol de Decisión Multicanal (Flujo)</h3>
                <p className="text-xs text-zinc-400">
                  Haz clic en cualquier tarjeta de paso para editar mensajes, Spintax o tiempos de espera.
                </p>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => setAddStepModalConfig({ position: 'inicio' })}
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-xs text-zinc-200 transition cursor-pointer"
                >
                  <Plus className="w-3.5 h-3.5 text-sky-400" />
                  <span>+ Paso al Inicio</span>
                </button>
                <button
                  onClick={() => setAddStepModalConfig({ position: 'final' })}
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-xs text-zinc-200 transition cursor-pointer"
                >
                  <Plus className="w-3.5 h-3.5 text-sky-400" />
                  <span>+ Paso al Final</span>
                </button>
              </div>
            </div>

            {/* Renderizado de Nodos del Árbol en Cadena */}
            <div className="flex flex-col items-center py-6 space-y-3">
              {steps.map((step, idx) => {
                const isLinkedIn = step.tipo.includes('LINKEDIN') || step.tipo.includes('PERFIL') || step.tipo.includes('INVITACION');
                const isEmail = step.tipo.includes('WORKSPACE') || step.tipo.includes('CORREO');
                const isDelay = step.tipo === 'ESPERAR';
                const isCheck = step.tipo.includes('VERIFICAR');

                const borderAccent = isLinkedIn 
                  ? 'border-sky-500/40 hover:border-sky-400' 
                  : isEmail 
                  ? 'border-indigo-500/40 hover:border-indigo-400' 
                  : isDelay 
                  ? 'border-amber-500/40 hover:border-amber-400' 
                  : 'border-emerald-500/40 hover:border-emerald-400';

                return (
                  <React.Fragment key={step.id || idx}>
                    {/* Flecha conectora */}
                    {idx > 0 && (
                      <div className="flex flex-col items-center">
                        <div className="w-0.5 h-4 bg-zinc-700/80" />
                        <div className="w-2 h-2 rotate-45 border-b-2 border-r-2 border-zinc-500 -mt-1" />
                      </div>
                    )}

                    {/* Tarjeta del paso */}
                    <div
                      onClick={() => setSelectedStepToEdit(step)}
                      className={`w-full max-w-md p-3.5 rounded-xl bg-zinc-900/90 border ${borderAccent} transition cursor-pointer shadow-md group relative hover:scale-[1.01]`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-3">
                          <span className="w-6 h-6 rounded-md bg-zinc-800 font-mono text-[11px] font-semibold text-zinc-300 flex items-center justify-center border border-zinc-700">
                            {idx + 1}
                          </span>
                          <div>
                            <div className="text-xs font-semibold text-zinc-100 group-hover:text-sky-400 transition">
                              {step.etiqueta || step.tipo}
                            </div>
                            <span className="text-[10px] font-mono text-zinc-400">{step.tipo}</span>
                          </div>
                        </div>

                        <div className="flex items-center gap-2">
                          {step.condicion_rama && step.condicion_rama !== 'DEFAULT' && (
                            <span className="px-1.5 py-0.5 rounded bg-sky-950 text-sky-400 text-[10px] font-mono border border-sky-800">
                              {step.condicion_rama}
                            </span>
                          )}
                          {isDelay && (
                            <span className="px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 text-[10px] font-mono border border-amber-500/20">
                              {step.parametros?.horas_espera ?? step.parametros?.horas ?? 24}h espera
                            </span>
                          )}
                          <Edit3 className="w-3.5 h-3.5 text-zinc-500 group-hover:text-zinc-300 transition" />
                        </div>
                      </div>
                    </div>
                  </React.Fragment>
                );
              })}
            </div>
          </div>

          {/* Tabla de leads actualmente inscritos en la secuencia */}
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/30 overflow-hidden">
            <div className="p-4 border-b border-zinc-800 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-zinc-100">Prospectos en esta Secuencia</h3>
              <span className="text-xs text-zinc-400 font-mono">{enrolledLeads.length} inscritos</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-zinc-950/60 border-b border-zinc-800 text-zinc-400">
                  <tr>
                    <th className="py-2.5 px-4">Prospecto / Contacto</th>
                    <th className="py-2.5 px-4">Empresa / Organización</th>
                    <th className="py-2.5 px-4">Email</th>
                    <th className="py-2.5 px-4 font-mono">Paso Actual</th>
                    <th className="py-2.5 px-4">Estado</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/50">
                  {enrolledLeads.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="py-8 text-center text-zinc-500">
                        No hay leads asignados a esta secuencia aún. Usa "Asignar Leads en Cola".
                      </td>
                    </tr>
                  ) : (
                    enrolledLeads.map((lead, idx) => (
                      <tr key={lead.id || idx} className="hover:bg-zinc-800/20">
                        <td className="py-3 px-4 font-medium text-zinc-200">{lead.nombre}</td>
                        <td className="py-3 px-4 text-zinc-400">{lead.institucion || '-'}</td>
                        <td className="py-3 px-4 text-zinc-400 font-mono text-[11px]">{lead.email_directo || 'No declarado'}</td>
                        <td className="py-3 px-4 font-mono text-sky-400">Paso #{lead.paso_actual || 1}</td>
                        <td className="py-3 px-4">
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-zinc-800 text-zinc-300 border border-zinc-700">
                            {lead.estado_secuencia || 'EN_PROGRESO'}
                          </span>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Modales contextuales */}
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

      {showNewSequenceModal && (
        <NewSequenceModal
          onClose={() => setShowNewSequenceModal(false)}
          onCreated={loadData}
          activeTenantWorkspace={activeTenantWorkspace}
        />
      )}

      {showConnectListModal && (
        <ConnectListModal
          sequenceId={activeSequence.id}
          leadLists={leadLists}
          onClose={() => setShowConnectListModal(false)}
          onConnected={loadData}
        />
      )}
    </div>
  );
}
