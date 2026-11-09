import React, { useState, useEffect } from 'react';
import { 
  Sliders, 
  RotateCcw, 
  Check, 
  AlertTriangle, 
  Clock, 
  ShieldCheck, 
  ShieldAlert, 
  RefreshCw, 
  Save, 
  Trash2,
  Calendar,
  Zap,
  Info
} from 'lucide-react';
import { 
  fetchQueuePolicies, 
  updateQueuePolicy, 
  resetQueuePoliciesToRecommended,
  fetchQueueStatus,
  cancelCentralQueueTasks
} from '../../services/api';

export default function TaskPoliciesConfigurator({ activeTenantWorkspace = '' }) {
  const [policies, setPolicies] = useState([]);
  const [queueStatus, setQueueStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [savingPolicy, setSavingPolicy] = useState(null);
  const [resetting, setResetting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [feedbackMsg, setFeedbackMsg] = useState(null);

  // Carga inicial y por cambio de tenant
  useEffect(() => {
    loadData();
    const interval = setInterval(loadStatusOnly, 12000);
    return () => clearInterval(interval);
  }, [activeTenantWorkspace]);

  async function loadData() {
    setLoading(true);
    try {
      const [pols, st] = await Promise.all([
        fetchQueuePolicies(activeTenantWorkspace).catch(() => []),
        fetchQueueStatus(activeTenantWorkspace).catch(() => null)
      ]);
      setPolicies(pols);
      setQueueStatus(st);
    } catch (err) {
      console.error('Error cargando políticas de cola:', err);
    } finally {
      setLoading(false);
    }
  }

  async function loadStatusOnly() {
    try {
      const st = await fetchQueueStatus(activeTenantWorkspace);
      setQueueStatus(st);
    } catch (_) {}
  }

  function handleFieldChange(tipoTarea, field, val) {
    setPolicies(prev => prev.map(p => {
      if (p.tipo_tarea === tipoTarea) {
        return { ...p, [field]: val, _isDirty: true };
      }
      return p;
    }));
  }

  async function handleSaveRow(policy) {
    setSavingPolicy(policy.tipo_tarea);
    setFeedbackMsg(null);
    try {
      const res = await updateQueuePolicy(policy.tipo_tarea, {
        limite_diario: parseInt(policy.limite_diario, 10),
        pausa_min_seg: parseInt(policy.pausa_min_seg, 10),
        pausa_max_seg: parseInt(policy.pausa_max_seg, 10),
        activo: Boolean(policy.activo)
      }, activeTenantWorkspace);

      if (res && res.ok) {
        setPolicies(prev => prev.map(p => p.tipo_tarea === policy.tipo_tarea ? { ...p, _isDirty: false } : p));
        setFeedbackMsg({ type: 'success', text: `Política de '${policy.tipo_tarea}' guardada en PostgreSQL.` });
      }
    } catch (err) {
      setFeedbackMsg({ type: 'error', text: `Error guardando política: ${err.message}` });
    } finally {
      setSavingPolicy(null);
      setTimeout(() => setFeedbackMsg(null), 4000);
    }
  }

  async function handleResetRecommended() {
    if (!confirm('¿Restaurar todas las políticas de ritmo al estándar recomendado antibaneo (50 invitaciones/día con pausas orgánicas)?')) {
      return;
    }
    setResetting(true);
    try {
      const restored = await resetQueuePoliciesToRecommended(activeTenantWorkspace);
      setPolicies(restored);
      setFeedbackMsg({ type: 'success', text: 'Políticas restauradas a los valores recomendados antiban.' });
    } catch (err) {
      setFeedbackMsg({ type: 'error', text: `Error al restaurar: ${err.message}` });
    } finally {
      setResetting(false);
      setTimeout(() => setFeedbackMsg(null), 4000);
    }
  }

  async function handleCancelPendingQueue() {
    if (!confirm('¿Deseas cancelar todas las tareas pendientes en la cola central de PostgreSQL?')) {
      return;
    }
    setCancelling(true);
    try {
      const res = await cancelCentralQueueTasks(null, activeTenantWorkspace);
      setFeedbackMsg({ type: 'success', text: `Se cancelaron ${res?.canceladas || 0} tareas pendientes en PostgreSQL.` });
      await loadStatusOnly();
    } catch (err) {
      setFeedbackMsg({ type: 'error', text: `Error cancelando tareas: ${err.message}` });
    } finally {
      setCancelling(false);
      setTimeout(() => setFeedbackMsg(null), 4000);
    }
  }

  const getRiskBadge = (nivel) => {
    switch (nivel) {
      case 'ALTO':
        return (
          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-rose-950/80 text-rose-300 border border-rose-500/40">
            🔴 Alto (LinkedIn)
          </span>
        );
      case 'MEDIO':
        return (
          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-amber-950/80 text-amber-300 border border-amber-500/40">
            🟡 Medio (Email)
          </span>
        );
      default:
        return (
          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-950/80 text-emerald-300 border border-emerald-500/40">
            🟢 Seguro (API)
          </span>
        );
    }
  };

  return (
    <div className="p-5 rounded-2xl bg-[#121316] border border-white/[0.08] space-y-5">
      {/* 1. Header con métricas de la cola persistente */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b border-white/[0.06] pb-4">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-indigo-950/60 text-indigo-400 border border-indigo-500/30">
              <Sliders className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-zinc-100 flex items-center gap-2">
                <span>Configurador Granular de Políticas de Ritmo & Cuotas</span>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-950 text-indigo-300 border border-indigo-500/40 font-mono">
                  PostgreSQL Central
                </span>
              </h2>
              <p className="text-xs text-zinc-400 mt-0.5">
                Define cuotas máximas diarias y descansos estocásticos con jitter para proteger tus 5 cuentas de LinkedIn y dominios de correo.
              </p>
            </div>
          </div>
        </div>

        {/* Acciones de Cabecera */}
        <div className="flex items-center gap-2 shrink-0 flex-wrap">
          <button
            type="button"
            onClick={handleResetRecommended}
            disabled={resetting}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-900 hover:bg-zinc-800 text-zinc-300 text-xs font-medium border border-zinc-700/60 transition cursor-pointer disabled:opacity-50"
            title="Cargar cuotas recomendadas antibaneo (50 invitaciones/día)"
          >
            <RotateCcw className={`w-3.5 h-3.5 ${resetting ? 'animate-spin' : ''}`} />
            <span>Cargar Recomendados (50 inv/d)</span>
          </button>

          {queueStatus && queueStatus.pendientes > 0 && (
            <button
              type="button"
              onClick={handleCancelPendingQueue}
              disabled={cancelling}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-950/40 hover:bg-rose-950/70 text-rose-300 text-xs font-medium border border-rose-500/40 transition cursor-pointer disabled:opacity-50"
              title="Cancelar todas las tareas que esperan en la cola central de PostgreSQL"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span>Limpiar Cola ({queueStatus.pendientes})</span>
            </button>
          )}
        </div>
      </div>

      {/* 2. Banner de Estado en Vivo de la Cola Persistente */}
      {queueStatus && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-3.5 rounded-xl bg-[#0D0E12] border border-white/[0.04]">
          <div className="flex flex-col">
            <span className="text-[10px] font-mono uppercase text-zinc-500">Tareas en Cola</span>
            <span className="text-xl font-bold font-mono text-indigo-300 mt-0.5">
              {queueStatus.pendientes} <span className="text-xs font-normal text-zinc-400">pendientes</span>
            </span>
          </div>

          <div className="flex flex-col">
            <span className="text-[10px] font-mono uppercase text-zinc-500">En Ejecución</span>
            <span className="text-xl font-bold font-mono text-emerald-300 mt-0.5">
              {queueStatus.en_proceso} <span className="text-xs font-normal text-zinc-400">activas</span>
            </span>
          </div>

          <div className="flex flex-col">
            <span className="text-[10px] font-mono uppercase text-zinc-500">Completadas Hoy</span>
            <span className="text-xl font-bold font-mono text-zinc-200 mt-0.5">
              {queueStatus.completadas_hoy}
            </span>
          </div>

          <div className="flex flex-col">
            <span className="text-[10px] font-mono uppercase text-zinc-500">Próxima Acción</span>
            <span className="text-xs font-mono text-amber-300 mt-1 truncate" title={queueStatus.proxima_ejecucion || 'Sin tareas programadas'}>
              {queueStatus.proxima_ejecucion 
                ? new Date(queueStatus.proxima_ejecucion).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                : 'En reposo'}
            </span>
          </div>
        </div>
      )}

      {/* Feedback Toast */}
      {feedbackMsg && (
        <div className={`p-3 rounded-lg text-xs font-medium border flex items-center gap-2 ${
          feedbackMsg.type === 'success' 
            ? 'bg-emerald-950/60 text-emerald-300 border-emerald-500/40' 
            : 'bg-rose-950/60 text-rose-300 border-rose-500/40'
        }`}>
          {feedbackMsg.type === 'success' ? <Check className="w-4 h-4 shrink-0" /> : <AlertTriangle className="w-4 h-4 shrink-0" />}
          <span>{feedbackMsg.text}</span>
        </div>
      )}

      {/* 3. Tabla Interactiva de Políticas Granulares */}
      <div className="overflow-x-auto rounded-xl border border-white/[0.06]">
        <table className="w-full text-left text-xs border-collapse">
          <thead>
            <tr className="bg-[#0D0E12] text-zinc-400 border-b border-white/[0.06] font-mono text-[11px]">
              <th className="py-2.5 px-3 font-medium">Activa</th>
              <th className="py-2.5 px-3 font-medium">Acción & Descripción</th>
              <th className="py-2.5 px-3 font-medium">Nivel de Riesgo</th>
              <th className="py-2.5 px-3 font-medium text-center">Tope Diario</th>
              <th className="py-2.5 px-3 font-medium text-center">Pausa Mín (seg)</th>
              <th className="py-2.5 px-3 font-medium text-center">Pausa Máx (seg)</th>
              <th className="py-2.5 px-3 font-medium text-center">Consumo Hoy</th>
              <th className="py-2.5 px-3 font-medium text-right">Guardar</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.04]">
            {policies.map((p) => {
              const isDirty = Boolean(p._isDirty);
              const isSaving = savingPolicy === p.tipo_tarea;
              const ratio = p.limite_diario > 0 ? Math.min(100, Math.round((p.ejecutadas_hoy / p.limite_diario) * 100)) : 0;

              return (
                <tr key={p.tipo_tarea} className="hover:bg-white/[0.02] transition-colors">
                  {/* Switch Activo */}
                  <td className="py-3 px-3">
                    <input
                      type="checkbox"
                      checked={Boolean(p.activo)}
                      onChange={(e) => handleFieldChange(p.tipo_tarea, 'activo', e.target.checked)}
                      className="rounded border-zinc-700 bg-zinc-900 text-emerald-500 focus:ring-0 cursor-pointer w-4 h-4"
                    />
                  </td>

                  {/* Nombre y Descripción */}
                  <td className="py-3 px-3">
                    <div className="font-semibold text-zinc-200 flex items-center gap-1.5">
                      <span>{p.tipo_tarea}</span>
                    </div>
                    <div className="text-[11px] text-zinc-400 mt-0.5">
                      {p.descripcion}
                    </div>
                  </td>

                  {/* Nivel de Riesgo */}
                  <td className="py-3 px-3">
                    {getRiskBadge(p.nivel_riesgo)}
                  </td>

                  {/* Límite Diario */}
                  <td className="py-3 px-3 text-center">
                    <input
                      type="number"
                      min="1"
                      max="1000"
                      value={p.limite_diario}
                      onChange={(e) => handleFieldChange(p.tipo_tarea, 'limite_diario', e.target.value)}
                      className="w-16 px-2 py-1 rounded bg-[#0A0B0E] border border-zinc-800 text-zinc-100 text-center font-mono text-xs focus:border-indigo-500 focus:outline-none"
                    />
                  </td>

                  {/* Pausa Mínima */}
                  <td className="py-3 px-3 text-center">
                    <input
                      type="number"
                      min="1"
                      max="3600"
                      value={p.pausa_min_seg}
                      onChange={(e) => handleFieldChange(p.tipo_tarea, 'pausa_min_seg', e.target.value)}
                      className="w-16 px-2 py-1 rounded bg-[#0A0B0E] border border-zinc-800 text-zinc-100 text-center font-mono text-xs focus:border-indigo-500 focus:outline-none"
                    />
                  </td>

                  {/* Pausa Máxima */}
                  <td className="py-3 px-3 text-center">
                    <input
                      type="number"
                      min="1"
                      max="7200"
                      value={p.pausa_max_seg}
                      onChange={(e) => handleFieldChange(p.tipo_tarea, 'pausa_max_seg', e.target.value)}
                      className="w-16 px-2 py-1 rounded bg-[#0A0B0E] border border-zinc-800 text-zinc-100 text-center font-mono text-xs focus:border-indigo-500 focus:outline-none"
                    />
                  </td>

                  {/* Consumo Hoy */}
                  <td className="py-3 px-3 text-center">
                    <div className="flex flex-col items-center gap-1">
                      <span className="font-mono text-[11px] text-zinc-300">
                        {p.ejecutadas_hoy} / {p.limite_diario}
                      </span>
                      <div className="w-16 h-1.5 rounded-full bg-zinc-800 overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${
                            ratio >= 100 ? 'bg-rose-500' : ratio > 75 ? 'bg-amber-500' : 'bg-emerald-500'
                          }`}
                          style={{ width: `${ratio}%` }}
                        />
                      </div>
                    </div>
                  </td>

                  {/* Botón Guardar */}
                  <td className="py-3 px-3 text-right">
                    <button
                      type="button"
                      onClick={() => handleSaveRow(p)}
                      disabled={isSaving || !isDirty}
                      className={`p-1.5 rounded-lg border text-xs font-medium transition cursor-pointer disabled:opacity-40 ${
                        isDirty
                          ? 'bg-indigo-600 hover:bg-indigo-500 text-white border-indigo-400 shadow-sm'
                          : 'bg-zinc-900 text-zinc-500 border-zinc-800 hover:text-zinc-300'
                      }`}
                      title={isDirty ? 'Guardar cambios en base de datos' : 'Sin cambios pendientes'}
                    >
                      {isSaving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="p-3 rounded-xl bg-zinc-900/40 border border-white/[0.04] text-[11px] text-zinc-400 flex items-start gap-2.5">
        <Info className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
        <div>
          <strong className="text-zinc-300">Algoritmo de Intercalación Estocástica:</strong> El despachador de PostgreSQL calcula automáticamente marcas temporales con distribución normal truncada (*Gaussian Jitter*) entre la pausa mínima y máxima de cada tarea, y alterna acciones directas con pausas de correo o descanso para que cada una de tus 5 cuentas mantenga un comportamiento idéntico al de un humano.
        </div>
      </div>
    </div>
  );
}

