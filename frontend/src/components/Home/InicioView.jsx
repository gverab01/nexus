import React, { useEffect, useState } from 'react';
import {
  CalendarCheck,
  MessageSquare,
  UserCheck,
  Send,
  Play,
  Pause,
  Plus,
  Users,
  ArrowRight,
  CheckCircle2,
  Circle,
  Sparkles,
  BarChart3,
  Settings,
  X
} from 'lucide-react';
import { fetchDashboardMetrics, fetchWorkerState } from '../../services/api';
import {
  CHANNELS_CHANGED_EVENT,
  getEnabledChannels,
  isOnboardingDismissed,
  setOnboardingDismissed,
  toggleEnabledChannel
} from '../../utils/channelsConfig';

export default function InicioView({
  activeTenantWorkspace = '',
  linkedinSessionActive = false,
  campaignActive = true,
  sequencesCount = 0,
  totalLeadsCount = 0,
  onToggleCampaign = null,
  onOpenLinkedin = null,
  onNavigateToTab = null,
  onOpenCampaignWizard = null,
  onOpenFullAnalytics = null,
}) {
  const [loading, setLoading] = useState(true);
  const [metrics, setMetrics] = useState(null);
  const [workerState, setWorkerState] = useState(null);
  const [enabledChannels, setEnabledChannelsState] = useState(getEnabledChannels);
  const [checklistHidden, setChecklistHidden] = useState(() => isOnboardingDismissed());

  useEffect(() => {
    const onChannelsChanged = (e) => setEnabledChannelsState(e.detail || getEnabledChannels());
    window.addEventListener(CHANNELS_CHANGED_EVENT, onChannelsChanged);
    return () => window.removeEventListener(CHANNELS_CHANGED_EVENT, onChannelsChanged);
  }, []);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        setLoading(true);
        const [m, w] = await Promise.all([
          fetchDashboardMetrics({ tenantId: activeTenantWorkspace }).catch(() => null),
          fetchWorkerState().catch(() => null),
        ]);
        if (!active) return;
        setMetrics(m);
        setWorkerState(w);
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    return () => { active = false; };
  }, [activeTenantWorkspace]);

  const kpis = metrics?.metricas_clave || {};
  const reuniones = kpis.reuniones_agendadas ?? 0;
  const respuestas = kpis.respuestas_recibidas ?? 0;
  const conectados = kpis.conectados_total ?? kpis.aceptaciones ?? 0;
  const invitaciones = kpis.invitaciones_enviadas ?? 0;

  const showOnboarding = !checklistHidden || !linkedinSessionActive;

  function handleDismissChecklist() {
    setOnboardingDismissed(true);
    setChecklistHidden(true);
  }

  return (
    <div className="space-y-6 font-sans animate-fadeIn">
      {/* Encabezado limpio orientado a reuniones */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-zinc-100 tracking-tight">
            Resumen de hoy
          </h1>
          <p className="text-xs text-zinc-300 mt-0.5">
            Tu foco diario: convertir prospectos en conversaciones y reuniones agendadas.
          </p>
        </div>

        <div className="flex items-center gap-2.5 flex-wrap">
          <button
            type="button"
            onClick={() => (onOpenCampaignWizard ? onOpenCampaignWizard() : onNavigateToTab?.('campanas'))}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold shadow-sm transition cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            <span>Nueva campaña</span>
          </button>
          <button
            type="button"
            onClick={() => onNavigateToTab?.('audiencia')}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-lg bg-[#14161A] hover:bg-zinc-800 border border-[#22252B] text-zinc-200 text-xs font-medium transition cursor-pointer"
          >
            <Users className="w-3.5 h-3.5 text-zinc-300" />
            <span>Buscar contactos</span>
          </button>
        </div>
      </div>

      {/* Checklist inicial de 3 pasos (se oculta cuando el usuario termina o lo cierra) */}
      {showOnboarding && (
        <section className="rounded-xl bg-[#121316] border border-white/[0.08] p-5 space-y-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="inline-flex items-center gap-1.5 text-xs font-semibold text-blue-400 mb-1">
                <Sparkles className="w-3.5 h-3.5" />
                <span>Puesta en marcha en 3 pasos</span>
              </div>
              <h2 className="text-sm font-semibold text-zinc-100">
                Prepara tu cuenta para empezar a agendar reuniones
              </h2>
            </div>
            {linkedinSessionActive && (
              <button
                type="button"
                onClick={handleDismissChecklist}
                className="p-1.5 rounded-md text-zinc-400 hover:text-white hover:bg-white/[0.06] transition cursor-pointer"
                title="Ocultar guía inicial"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {/* Paso 1: Conectar LinkedIn */}
            <div className="rounded-lg bg-[#0E0F12] border border-[#22252B] p-4 flex flex-col justify-between gap-3">
              <div className="space-y-1.5">
                <div className="flex items-center gap-2 text-xs font-semibold text-zinc-100">
                  {linkedinSessionActive ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                  ) : (
                    <Circle className="w-4 h-4 text-amber-400 shrink-0" />
                  )}
                  <span>1. Conecta tu LinkedIn</span>
                </div>
                <p className="text-xs text-zinc-400 leading-relaxed">
                  {linkedinSessionActive
                    ? 'Tu sesión de LinkedIn está conectada y lista para prospectar.'
                    : 'Inicia sesión una vez para buscar decisores y enviar invitaciones.'}
                </p>
              </div>
              <button
                type="button"
                onClick={onOpenLinkedin}
                className={`w-full py-1.5 px-3 rounded-md text-xs font-medium transition cursor-pointer ${
                  linkedinSessionActive
                    ? 'bg-emerald-950/40 text-emerald-300 border border-emerald-600/30 hover:bg-emerald-950/60'
                    : 'bg-white text-zinc-950 hover:bg-zinc-200 font-semibold'
                }`}
              >
                {linkedinSessionActive ? 'LinkedIn conectado' : 'Conectar LinkedIn'}
              </button>
            </div>

            {/* Paso 2: Elegir canales opcionales */}
            <div className="rounded-lg bg-[#0E0F12] border border-[#22252B] p-4 flex flex-col justify-between gap-3">
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs font-semibold text-zinc-100">
                  <CheckCircle2 className="w-4 h-4 text-blue-400 shrink-0" />
                  <span>2. Canales opcionales</span>
                </div>
                <p className="text-xs text-zinc-400">
                  Activa solo los canales que quieras usar en tus campañas:
                </p>
                <div className="flex flex-wrap gap-1.5 pt-0.5">
                  {[
                    { key: 'email', label: 'Correo' },
                    { key: 'whatsapp', label: 'WhatsApp' },
                    { key: 'zoho', label: 'Zoho CRM' },
                  ].map((ch) => {
                    const active = Boolean(enabledChannels[ch.key]);
                    return (
                      <button
                        key={ch.key}
                        type="button"
                        onClick={() => setEnabledChannelsState(toggleEnabledChannel(ch.key))}
                        className={`px-2.5 py-1 rounded-md text-xs font-medium border transition cursor-pointer ${
                          active
                            ? 'bg-blue-600/20 border-blue-500/50 text-blue-200'
                            : 'bg-[#14161A] border-[#22252B] text-zinc-400 hover:text-zinc-200'
                        }`}
                      >
                        {active ? `✓ ${ch.label}` : `+ ${ch.label}`}
                      </button>
                    );
                  })}
                </div>
              </div>
              <button
                type="button"
                onClick={() => onNavigateToTab?.('ajustes')}
                className="inline-flex items-center justify-center gap-1.5 w-full py-1.5 px-3 rounded-md bg-[#14161A] hover:bg-zinc-800 border border-[#22252B] text-zinc-300 text-xs font-medium transition cursor-pointer"
              >
                <Settings className="w-3.5 h-3.5" />
                <span>Configurar cuentas</span>
              </button>
            </div>

            {/* Paso 3: Lanzar campaña */}
            <div className="rounded-lg bg-[#0E0F12] border border-[#22252B] p-4 flex flex-col justify-between gap-3">
              <div className="space-y-1.5">
                <div className="flex items-center gap-2 text-xs font-semibold text-zinc-100">
                  {sequencesCount > 0 ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                  ) : (
                    <Circle className="w-4 h-4 text-zinc-400 shrink-0" />
                  )}
                  <span>3. Lanza tu campaña</span>
                </div>
                <p className="text-xs text-zinc-400 leading-relaxed">
                  {totalLeadsCount > 0
                    ? `Ya tienes ${totalLeadsCount} contactos en tu base. Elige una plantilla y comienza a agendar reuniones.`
                    : 'Usa una plantilla lista para invitar y dar seguimiento automático.'}
                </p>
              </div>
              <button
                type="button"
                onClick={() => (onOpenCampaignWizard ? onOpenCampaignWizard() : onNavigateToTab?.('campanas'))}
                className="inline-flex items-center justify-center gap-1.5 w-full py-1.5 px-3 rounded-md bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold transition cursor-pointer"
              >
                <span>Crear campaña con plantilla</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </section>
      )}

      {/* KPIs centrados en el objetivo comercial: Reuniones */}
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-3.5">
        <div className="rounded-xl bg-[#121316] border border-emerald-500/30 p-4 space-y-2">
          <div className="flex items-center justify-between text-xs text-emerald-300 font-medium">
            <span>Reuniones agendadas</span>
            <CalendarCheck className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-bold text-white tabular-nums">
            {loading ? '—' : reuniones}
          </div>
          <p className="text-xs text-zinc-400">Meta principal de tus campañas</p>
        </div>

        <div className="rounded-xl bg-[#121316] border border-white/[0.08] p-4 space-y-2">
          <div className="flex items-center justify-between text-xs text-zinc-300 font-medium">
            <span>Respuestas recibidas</span>
            <MessageSquare className="w-4 h-4 text-blue-400" />
          </div>
          <div className="text-2xl font-bold text-white tabular-nums">
            {loading ? '—' : respuestas}
          </div>
          <p className="text-xs text-zinc-400">Conversaciones abiertas</p>
        </div>

        <div className="rounded-xl bg-[#121316] border border-white/[0.08] p-4 space-y-2">
          <div className="flex items-center justify-between text-xs text-zinc-300 font-medium">
            <span>Contactos aceptados</span>
            <UserCheck className="w-4 h-4 text-sky-400" />
          </div>
          <div className="text-2xl font-bold text-white tabular-nums">
            {loading ? '—' : conectados}
          </div>
          <p className="text-xs text-zinc-400">Listos para seguimiento</p>
        </div>

        <div className="rounded-xl bg-[#121316] border border-white/[0.08] p-4 space-y-2">
          <div className="flex items-center justify-between text-xs text-zinc-300 font-medium">
            <span>Invitaciones enviadas</span>
            <Send className="w-4 h-4 text-zinc-300" />
          </div>
          <div className="text-2xl font-bold text-white tabular-nums">
            {loading ? '—' : invitaciones}
          </div>
          <p className="text-xs text-zinc-400">Total acumulado</p>
        </div>
      </section>

      {/* Estado de automatización y accesos rápidos */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 rounded-xl bg-[#121316] border border-white/[0.08] p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <span
                className={`w-2.5 h-2.5 rounded-full ${
                  campaignActive ? 'bg-emerald-400 animate-status-pulse' : 'bg-amber-400'
                }`}
              />
              <h3 className="text-sm font-semibold text-zinc-100">
                {campaignActive ? 'Tus envíos automáticos están activos' : 'Tus envíos automáticos están en pausa'}
              </h3>
            </div>
            <p className="text-xs text-zinc-300">
              {workerState?.estado_actual
                ? workerState.estado_actual
                : campaignActive
                ? `Tienes ${sequencesCount} campaña(s) configurada(s) y ${totalLeadsCount} contactos en tu base.`
                : 'Reanuda el envío cuando quieras continuar contactando prospectos.'}
            </p>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {onToggleCampaign && (
              <button
                type="button"
                onClick={onToggleCampaign}
                className={`inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-semibold border transition cursor-pointer ${
                  campaignActive
                    ? 'bg-amber-950/30 border-amber-600/40 text-amber-200 hover:bg-amber-950/50'
                    : 'bg-emerald-950/30 border-emerald-600/40 text-emerald-200 hover:bg-emerald-950/50'
                }`}
              >
                {campaignActive ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                <span>{campaignActive ? 'Pausar envíos' : 'Reanudar envíos'}</span>
              </button>
            )}
            <button
              type="button"
              onClick={() => onNavigateToTab?.('campanas')}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-[#14161A] hover:bg-zinc-800 border border-[#22252B] text-zinc-200 text-xs font-medium transition cursor-pointer"
            >
              <span>Ver campañas</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <div className="rounded-xl bg-[#121316] border border-white/[0.08] p-5 flex flex-col justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-zinc-100">Analítica detallada</h3>
            <p className="text-xs text-zinc-400 mt-1">
              Revisa tasas de conversión paso a paso y rendimiento por campaña.
            </p>
          </div>
          <button
            type="button"
            onClick={() => (onOpenFullAnalytics ? onOpenFullAnalytics() : onNavigateToTab?.('dashboard'))}
            className="inline-flex items-center justify-center gap-2 w-full py-2 px-3 rounded-lg bg-[#14161A] hover:bg-zinc-800 border border-[#22252B] text-zinc-200 text-xs font-medium transition cursor-pointer"
          >
            <BarChart3 className="w-3.5 h-3.5 text-blue-400" />
            <span>Abrir métricas completas</span>
          </button>
        </div>
      </section>
    </div>
  );
}

