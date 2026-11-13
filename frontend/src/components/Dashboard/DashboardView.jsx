// Vista principal de Dashboard de Rendimiento, KPIs B2B y Salud Antiban
import React, { useState, useEffect } from 'react';
import { 
  BarChart3, 
  Users, 
  UserCheck, 
  Send, 
  Mail, 
  Clock, 
  ShieldCheck, 
  ShieldAlert, 
  RefreshCw, 
  TrendingUp, 
  GitFork, 
  ListFilter, 
  Calendar, 
  CheckCircle2, 
  AlertTriangle, 
  Compass, 
  MessageSquare, 
  ArrowUpRight,
  Sparkles,
  Layers,
  Zap,
  Info
} from 'lucide-react';
import { fetchDashboardMetrics, syncAcceptedConnections } from '../../services/api';
import { showToast } from '../Toast';

export default function DashboardView({ activeTenantWorkspace = '', onNavigateToTab = null }) {
  const [loading, setLoading] = useState(true);
  const [syncingConnections, setSyncingConnections] = useState(false);
  const [metrics, setMetrics] = useState(null);
  const [selectedSequenceId, setSelectedSequenceId] = useState('');
  const [selectedListId, setSelectedListId] = useState('');
  const [lastRefreshed, setLastRefreshed] = useState(new Date());

  useEffect(() => {
    loadData();
  }, [activeTenantWorkspace, selectedSequenceId, selectedListId]);

  async function loadData() {
    try {
      setLoading(true);
      const data = await fetchDashboardMetrics({
        tenantId: activeTenantWorkspace,
        sequenceId: selectedSequenceId,
        listId: selectedListId
      });
      setMetrics(data);
      setLastRefreshed(new Date());
    } catch (err) {
      console.error('Error cargando métricas de dashboard:', err);
    } finally {
      setLoading(false);
    }
  }

  async function handleSyncConnections() {
    try {
      setSyncingConnections(true);
      const res = await syncAcceptedConnections(activeTenantWorkspace);
      showToast(res.mensaje || `Revisión completada: ${res.nuevos_conectados || 0} nuevas conexiones.`, 'success');
      await loadData();
    } catch (err) {
      showToast(`Error revisando conexiones: ${err.message}`, 'error');
    } finally {
      setSyncingConnections(false);
    }
  }

  const kpis = metrics?.metricas_clave || {};
  const zoho = metrics?.zoho_crm_kpis || {};
  const antiban = metrics?.antiban_salud || {};
  const funnel = metrics?.funnel || [];
  const sequences = metrics?.secuencias || [];
  const lists = metrics?.listas || [];

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-8 max-w-7xl mx-auto font-sans animate-fadeIn">
      {/* 1. Encabezado principal y filtros de contexto */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-white/[0.06]">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500/20 to-sky-500/20 border border-sky-500/30 flex items-center justify-center text-sky-400 shadow-lg">
            <BarChart3 className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-lg sm:text-xl font-semibold tracking-tight text-zinc-100">
              4. Resultados: Métricas y KPIs
            </h1>
            <p className="text-xs text-zinc-300 mt-0.5">
              Resumen de prospectos contactados, embudo de respuestas y protección de tu cuenta
            </p>
          </div>
        </div>

        {/* Filtros dinámicos de secuencia y lista */}
        <div className="flex items-center gap-2.5 flex-wrap">
          {/* Selector de Secuencia */}
          <div className="relative">
            <select
              value={selectedSequenceId}
              onChange={(e) => setSelectedSequenceId(e.target.value)}
              className="py-1.5 pl-3 pr-8 rounded-lg bg-[#0D0E12] border border-white/[0.08] text-xs text-zinc-200 focus:outline-none focus:border-sky-500/40 transition cursor-pointer"
            >
              <option value="">Todas las Secuencias ({sequences.length})</option>
              {sequences.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.nombre} ({s.total_leads} leads)
                </option>
              ))}
            </select>
          </div>

          {/* Selector de Lista */}
          <div className="relative">
            <select
              value={selectedListId}
              onChange={(e) => setSelectedListId(e.target.value)}
              className="py-1.5 pl-3 pr-8 rounded-lg bg-[#0D0E12] border border-white/[0.08] text-xs text-zinc-200 focus:outline-none focus:border-sky-500/40 transition cursor-pointer"
            >
              <option value="">Todas las Listas ({lists.length})</option>
              {lists.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.nombre} ({l.total_leads} leads)
                </option>
              ))}
            </select>
          </div>

          {/* Botón Sincronizar Aceptaciones LinkedIn */}
          <button
            type="button"
            onClick={handleSyncConnections}
            disabled={syncingConnections || loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-950/60 hover:bg-sky-900/80 border border-sky-500/30 text-sky-300 text-xs font-semibold transition cursor-pointer shadow-xs disabled:opacity-50"
            title="Inspeccionar en vivo si algún prospecto ha aceptado tu invitación en LinkedIn"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${syncingConnections ? 'animate-spin text-sky-400' : ''}`} />
            <span>{syncingConnections ? 'Revisando...' : 'Verificar Aceptaciones'}</span>
          </button>

          {/* Botón Refrescar */}
          <button
            type="button"
            onClick={loadData}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-white/[0.08] text-zinc-300 text-xs font-medium transition cursor-pointer shadow-xs disabled:opacity-50"
            title="Actualizar métricas"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-sky-400' : ''}`} />
            <span className="hidden sm:inline">Actualizar</span>
          </button>
        </div>
      </div>

      {/* 2. Grid de KPIs Principales (Métricas solicitadas a-k) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* KPI 1: Cupo de Invitaciones del Día (Warm-up) */}
        <div className="p-4 rounded-xl border border-white/[0.08] bg-[#121316] relative overflow-hidden space-y-3 shadow-md hover:border-white/20 transition">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
              <ShieldCheck className="w-3.5 h-3.5 text-sky-400" />
              Cupo Antiban Hoy
            </span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-sky-950/80 text-sky-300 border border-sky-500/30 font-bold">
              Semana {antiban.linkedin?.semana || 1} Warm-up
            </span>
          </div>

          <div className="flex items-baseline justify-between">
            <div className="text-2xl font-bold font-mono text-zinc-100">
              {kpis.invitaciones_hoy || 0}
              <span className="text-xs text-zinc-500 font-normal"> / {kpis.cupo_invitaciones_hoy || 15} máx</span>
            </div>
            <span className={`text-xs font-mono font-semibold ${
              (kpis.cupo_restante_hoy || 0) === 0 ? 'text-amber-400' : 'text-emerald-400'
            }`}>
              {kpis.cupo_restante_hoy || 0} disponibles
            </span>
          </div>

          {/* Barra de progreso de cupo diario */}
          <div className="space-y-1">
            <div className="w-full bg-zinc-800/80 rounded-full h-1.5 overflow-hidden">
              <div 
                className={`h-full rounded-full transition-all duration-500 ${
                  (kpis.cupo_usado_pct || 0) >= 100 ? 'bg-amber-500' : 'bg-gradient-to-r from-sky-500 to-indigo-500'
                }`}
                style={{ width: `${Math.min(100, kpis.cupo_usado_pct || 0)}%` }}
              />
            </div>
            <div className="flex justify-between text-[10px] text-zinc-500 font-mono">
              <span>{kpis.cupo_usado_pct || 0}% consumido</span>
              <span>Límite sugerido diario</span>
            </div>
          </div>
        </div>

        {/* KPI 2: Invitaciones Enviadas y Tasa de Aceptación */}
        <div className="p-4 rounded-xl border border-white/[0.08] bg-[#121316] relative overflow-hidden space-y-3 shadow-md hover:border-white/20 transition">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
              <Send className="w-3.5 h-3.5 text-cyan-400" />
              Invitaciones LinkedIn
            </span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950/80 text-emerald-300 border border-emerald-500/30 font-bold">
              {kpis.tasa_aceptacion_pct || 0}% Aceptación
            </span>
          </div>

          <div className="flex items-baseline justify-between">
            <div className="text-2xl font-bold font-mono text-zinc-100">
              {kpis.invitaciones_enviadas || 0}
              <span className="text-xs text-zinc-500 font-normal"> enviadas</span>
            </div>
            <span className="text-xs font-mono font-semibold text-emerald-400">
              {kpis.invitaciones_aceptadas || 0} conectadas
            </span>
          </div>

          <div className="text-[11px] text-zinc-400 flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />
            <span>Ratio de conexión sobre total emitido</span>
          </div>
        </div>

        {/* KPI 3: Leads en Secuencia & Completados */}
        <div className="p-4 rounded-xl border border-white/[0.08] bg-[#121316] relative overflow-hidden space-y-3 shadow-md hover:border-white/20 transition">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
              <GitFork className="w-3.5 h-3.5 text-purple-400" />
              Avance en Secuencias
            </span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-purple-950/80 text-purple-300 border border-purple-500/30 font-bold">
              {kpis.tasa_finalizacion_pct || 0}% Completados
            </span>
          </div>

          <div className="flex items-baseline justify-between">
            <div className="text-2xl font-bold font-mono text-zinc-100">
              {kpis.total_leads_secuencia || 0}
              <span className="text-xs text-zinc-500 font-normal"> inscritos</span>
            </div>
            <span className="text-xs font-mono font-semibold text-purple-300">
              {kpis.leads_completados || 0} finalizados
            </span>
          </div>

          <div className="text-[11px] text-zinc-400 flex items-center justify-between">
            <span className="text-zinc-500">Activos en cola:</span>
            <span className="font-mono font-semibold text-zinc-300">{kpis.leads_en_curso || 0} en curso</span>
          </div>
        </div>

        {/* KPI 4: Cobertura de Emails (Zoho + LinkedIn + Cascada) */}
        <div className="p-4 rounded-xl border border-white/[0.08] bg-[#121316] relative overflow-hidden space-y-3 shadow-md hover:border-white/20 transition">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
              <Mail className="w-3.5 h-3.5 text-emerald-400" />
              Correos Verificados
            </span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950/80 text-emerald-300 border border-emerald-500/30 font-bold">
              {kpis.cobertura_email_pct || 0}% Cobertura
            </span>
          </div>

          <div className="flex items-baseline justify-between">
            <div className="text-2xl font-bold font-mono text-zinc-100">
              {kpis.leads_con_email || 0}
              <span className="text-xs text-zinc-500 font-normal"> con email</span>
            </div>
            <span className="text-xs font-mono text-zinc-400">
              de {kpis.total_leads_base || 0} leads
            </span>
          </div>

          {/* Desglose por fuente */}
          <div className="flex items-center gap-1.5 text-[10px] font-mono flex-wrap">
            <span className="px-1.5 py-0.2 rounded bg-emerald-950 text-emerald-300 border border-emerald-500/30" title="Extraídos desde Zoho CRM">
              Zoho: {kpis.email_por_fuente?.zoho_crm || 0}
            </span>
            <span className="px-1.5 py-0.2 rounded bg-sky-950 text-sky-300 border border-sky-500/30" title="Cascada LinkedIn / DNS">
              LinkedIn: {kpis.email_por_fuente?.linkedin_waterfall || 0}
            </span>
          </div>
        </div>
      </div>

      {/* 3. Métricas Complementarias (KPIs Secundarios: Mensajería, Conversación y Base Global) */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="p-3.5 rounded-xl border border-white/[0.06] bg-[#0E0F12] flex items-center justify-between">
          <div>
            <span className="text-[11px] text-zinc-400 block font-medium">Mensajes Enviados</span>
            <span className="text-lg font-bold font-mono text-zinc-100">{kpis.mensajes_enviados || 0}</span>
          </div>
          <MessageSquare className="w-4 h-4 text-zinc-500" />
        </div>

        <div className="p-3.5 rounded-xl border border-white/[0.06] bg-[#0E0F12] flex items-center justify-between">
          <div>
            <span className="text-[11px] text-zinc-400 block font-medium">Respuestas Obtenidas</span>
            <span className="text-lg font-bold font-mono text-amber-300">{kpis.mensajes_recibidos || 0}</span>
          </div>
          <div className="text-right">
            <span className="text-[10px] font-mono text-zinc-500 block">Tasa Resp.</span>
            <span className="text-xs font-mono font-semibold text-amber-400">{kpis.tasa_respuesta_pct || 0}%</span>
          </div>
        </div>

        <div className="p-3.5 rounded-xl border border-white/[0.06] bg-[#0E0F12] flex items-center justify-between">
          <div>
            <span className="text-[11px] text-zinc-400 block font-medium">Reuniones Agendadas</span>
            <span className="text-lg font-bold font-mono text-pink-400">{kpis.reuniones_agendadas || 0}</span>
          </div>
          <Calendar className="w-4 h-4 text-pink-400" />
        </div>

        <div className="p-3.5 rounded-xl border border-white/[0.06] bg-[#0E0F12] flex items-center justify-between">
          <div>
            <span className="text-[11px] text-zinc-400 block font-medium">Base de Datos Completa</span>
            <span className="text-lg font-bold font-mono text-zinc-200">{kpis.total_leads_absoluto || 0}</span>
          </div>
          <Users className="w-4 h-4 text-zinc-500" />
        </div>
      </div>

      {/* 4. Sección Central: Embudo de Conversión (Funnel) & Salud Multicanal */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Embudo de Conversión (7 columnas) */}
        <div className="lg:col-span-7 p-5 rounded-xl border border-white/[0.08] bg-[#121316] shadow-xl space-y-4">
          <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
            <div className="flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-indigo-400" />
              <h2 className="text-sm font-bold text-zinc-100">
                Embudo de Conversión de Prospectos (Funnel B2B)
              </h2>
            </div>
            <span className="text-[11px] text-zinc-400 font-mono">
              Flujo acumulativo etapa por etapa
            </span>
          </div>

          <div className="space-y-2.5 pt-1">
            {funnel.map((step, idx) => {
              const maxCount = funnel[0]?.cantidad || 1;
              const pct = maxCount > 0 ? Math.round((step.cantidad / maxCount) * 100) : 0;

              return (
                <div key={idx} className="space-y-1">
                  <div className="flex items-center justify-between text-xs font-medium">
                    <span className="text-zinc-300 flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full" style={{ backgroundColor: step.color }} />
                      {step.etapa}
                      <span className="text-[10px] text-zinc-500 font-normal hidden sm:inline">({step.desc})</span>
                    </span>
                    <div className="flex items-center gap-3 font-mono">
                      <span className="text-zinc-100 font-bold">{step.cantidad}</span>
                      <span className="text-zinc-500 text-[11px] w-10 text-right">{pct}%</span>
                    </div>
                  </div>

                  <div className="w-full bg-zinc-800/50 rounded-full h-2 overflow-hidden">
                    <div 
                      className="h-full rounded-full transition-all duration-700"
                      style={{ 
                        width: `${Math.max(2, pct)}%`,
                        backgroundColor: step.color 
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Salud Multicanal y Plan de Warm-Up (5 columnas) */}
        <div className="lg:col-span-5 p-5 rounded-xl border border-white/[0.08] bg-[#121316] shadow-xl space-y-4">
          <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
              <h2 className="text-sm font-bold text-zinc-100">
                Salud Multicanal & Blindaje Antiban
              </h2>
            </div>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950/80 text-emerald-300 border border-emerald-500/30">
              Activo
            </span>
          </div>

          <div className="space-y-4 text-xs">
            {/* Canal 1: LinkedIn Warm-up y Búsquedas */}
            <div className="p-3 rounded-lg bg-zinc-900/60 border border-white/[0.06] space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-sky-300 flex items-center gap-1.5">
                  <Send className="w-3.5 h-3.5" />
                  LinkedIn Warm-up Progresivo
                </span>
                <span className="text-[10px] font-mono text-zinc-400">
                  Día {antiban.linkedin?.dia_actual || 1} del plan
                </span>
              </div>

              {/* Curva de 4 semanas */}
              <div className="grid grid-cols-4 gap-1.5 text-center font-mono text-[10px]">
                <div className={`p-1.5 rounded border ${
                  (antiban.linkedin?.semana || 1) === 1 ? 'bg-sky-950/80 border-sky-500/50 text-sky-200 font-bold' : 'bg-zinc-900 border-zinc-800 text-zinc-500'
                }`}>
                  <div>Semana 1</div>
                  <div className="text-xs">8/día</div>
                </div>
                <div className={`p-1.5 rounded border ${
                  (antiban.linkedin?.semana || 1) === 2 ? 'bg-sky-950/80 border-sky-500/50 text-sky-200 font-bold' : 'bg-zinc-900 border-zinc-800 text-zinc-500'
                }`}>
                  <div>Semana 2</div>
                  <div className="text-xs">14/día</div>
                </div>
                <div className={`p-1.5 rounded border ${
                  (antiban.linkedin?.semana || 1) === 3 ? 'bg-sky-950/80 border-sky-500/50 text-sky-200 font-bold' : 'bg-zinc-900 border-zinc-800 text-zinc-500'
                }`}>
                  <div>Semana 3</div>
                  <div className="text-xs">20/día</div>
                </div>
                <div className={`p-1.5 rounded border ${
                  (antiban.linkedin?.semana || 1) >= 4 ? 'bg-sky-950/80 border-sky-500/50 text-sky-200 font-bold' : 'bg-zinc-900 border-zinc-800 text-zinc-500'
                }`}>
                  <div>Semana 4+</div>
                  <div className="text-xs">25/día</div>
                </div>
              </div>

              {/* Medidor de Búsquedas Comerciales */}
              <div className="pt-1 flex items-center justify-between text-[11px] text-zinc-400">
                <span>Búsquedas Comerciales Mes:</span>
                <span className={`font-mono font-bold ${antiban.linkedin?.alerta_busquedas ? 'text-amber-400' : 'text-zinc-200'}`}>
                  {antiban.linkedin?.busquedas_mes || 0} / {antiban.linkedin?.busquedas_limite_max || 100}
                </span>
              </div>
            </div>

            {/* Canal 2: WhatsApp Web Antiban */}
            <div className="p-3 rounded-lg bg-zinc-900/60 border border-white/[0.06] space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-emerald-300 flex items-center gap-1.5">
                  <MessageSquare className="w-3.5 h-3.5" />
                  WhatsApp Web Seguro
                </span>
                <span className="text-[10px] font-mono text-zinc-400">
                  Cuota: {antiban.whatsapp?.cuota_diaria || 15}/día
                </span>
              </div>

              <div className="flex items-center justify-between text-[11px] text-zinc-400 font-mono">
                <span>Enviados hoy: {antiban.whatsapp?.enviados_hoy || 0}</span>
                <span className="text-emerald-400 font-semibold">{antiban.whatsapp?.cupo_restante || 15} disponibles</span>
              </div>

              <div className="flex items-center gap-2 text-[10px] text-zinc-500">
                <span className="px-1.5 py-0.5 rounded bg-zinc-800 border border-white/[0.04]">Mecanografía Biométrica</span>
                <span className="px-1.5 py-0.5 rounded bg-zinc-800 border border-white/[0.04]">Cero Links en Frío</span>
              </div>
            </div>

            {/* Canal 3: Inteligencia Zoho CRM */}
            <div className="p-3 rounded-lg bg-zinc-900/60 border border-white/[0.06] space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-amber-300 flex items-center gap-1.5">
                  <Compass className="w-3.5 h-3.5" />
                  Cruce Zoho CRM (Browser Session)
                </span>
                <span className="text-[10px] font-mono text-zinc-400">
                  {zoho.sincronizados || 0} cruzados
                </span>
              </div>

              <div className="grid grid-cols-2 gap-2 text-[11px] font-mono">
                <div className="p-1.5 rounded bg-zinc-900 border border-white/[0.04]">
                  <span className="text-[10px] text-zinc-500 block">Clientes Activos</span>
                  <span className="font-bold text-emerald-400">{zoho.clientes_activos || 0}</span>
                </div>
                <div className="p-1.5 rounded bg-zinc-900 border border-white/[0.04]">
                  <span className="text-[10px] text-zinc-500 block">Tratos Detectados</span>
                  <span className="font-bold text-amber-300">{zoho.con_tratos || 0}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 5. Tabla de Rendimiento por Secuencia */}
      <div className="rounded-xl border border-white/[0.08] bg-[#121316] shadow-xl overflow-hidden space-y-0">
        <div className="p-4 bg-[#0D0E12] border-b border-white/[0.06] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <GitFork className="w-4 h-4 text-purple-400" />
            <h2 className="text-sm font-bold text-zinc-100">
              Rendimiento Detallado por Secuencia
            </h2>
          </div>
          <span className="text-xs text-zinc-500 font-mono">
            {sequences.length} flujos registrados
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-sans">
            <thead className="bg-zinc-900/60 text-zinc-400 uppercase font-mono text-[10px] border-b border-white/[0.04]">
              <tr>
                <th className="py-2.5 px-4">Secuencia</th>
                <th className="py-2.5 px-4">Estado</th>
                <th className="py-2.5 px-4 text-right">Inscritos</th>
                <th className="py-2.5 px-4 text-right">En Curso</th>
                <th className="py-2.5 px-4 text-right">Completados</th>
                <th className="py-2.5 px-4 text-right">% Avance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04] text-zinc-300">
              {sequences.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-zinc-500">
                    No hay secuencias registradas en este espacio.
                  </td>
                </tr>
              ) : (
                sequences.map((s) => {
                  const avancePct = s.total_leads > 0 ? Math.round((s.completados / s.total_leads) * 100) : 0;
                  return (
                    <tr 
                      key={s.id} 
                      className={`hover:bg-white/[0.02] transition cursor-pointer ${selectedSequenceId === s.id ? 'bg-sky-950/20' : ''}`}
                      onClick={() => setSelectedSequenceId(selectedSequenceId === s.id ? '' : s.id)}
                    >
                      <td className="py-3 px-4 font-semibold text-zinc-100 flex items-center gap-2">
                        <span>{s.nombre}</span>
                        {selectedSequenceId === s.id && (
                          <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-sky-900 text-sky-200">Filtrando</span>
                        )}
                      </td>
                      <td className="py-3 px-4 font-mono text-[10px]">
                        <span className={`px-2 py-0.5 rounded border ${
                          s.estado === 'PUBLICADA' 
                            ? 'bg-emerald-950/60 text-emerald-300 border-emerald-500/30' 
                            : 'bg-zinc-900 text-zinc-400 border-zinc-800'
                        }`}>
                          {s.estado}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-right font-mono font-bold text-zinc-200">{s.total_leads}</td>
                      <td className="py-3 px-4 text-right font-mono text-zinc-400">{s.en_curso}</td>
                      <td className="py-3 px-4 text-right font-mono text-purple-300 font-semibold">{s.completados}</td>
                      <td className="py-3 px-4 text-right font-mono">
                        <span className="font-bold text-zinc-100">{avancePct}%</span>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
