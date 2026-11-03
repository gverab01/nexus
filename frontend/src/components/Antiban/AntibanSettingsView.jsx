import React, { useState, useEffect } from 'react';
import { 
  ShieldCheck, 
  ShieldAlert, 
  Clock, 
  Power, 
  RefreshCw, 
  ExternalLink, 
  CheckCircle2, 
  AlertTriangle, 
  Lock,
  Sparkles,
  Zap,
  Info,
  Calendar,
  Mail,
  Building2,
  Globe,
  Sliders,
  TrendingUp,
  MessageSquare,
  Search,
  Check,
  UserCheck,
  UserX
} from 'lucide-react';
import { 
  fetchSafetyStatus, 
  toggleCampaign, 
  showWorkBrowser,
  syncAcceptedConnections,
  getLinkedInWarmupStatus,
  getWhatsAppSafetyStatus,
  withdrawStaleInvitations
} from '../../services/api';

/**
 * Centro de Monitoreo de Seguridad Antiban & Blindaje Autónomo (NexusReach Pro)
 * 
 * Esta vista presenta de manera ejecutiva y transparente el estado en tiempo real
 * de todos los escudos antiban automáticos de la plataforma:
 * 1. Curva de calentamiento (Warm-up) de LinkedIn (8 -> 12 -> 16 -> 20 / día).
 * 2. Radar de consumo de cuota de búsqueda comercial mensual en LinkedIn.
 * 3. Temporizador estocástico humano (pausas gaussianas de 180s-360s y horarios hábiles).
 * 4. Blindaje multicanal: cuota segura de WhatsApp Web y entregabilidad de Google Workspace.
 * 5. Kill-Switch de parada de emergencia inmediata.
 * 6. Herramientas de mantenimiento activo: retiro de invitaciones vencidas y sync de conexiones.
 */
export default function AntibanSettingsView() {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [syncingConnections, setSyncingConnections] = useState(false);
  const [withdrawingStale, setWithdrawingStale] = useState(false);
  const [staleDays, setStaleDays] = useState(21);
  const [notification, setNotification] = useState(null);

  // 1. Estado de Kill-Switch y Horario Laboral
  const [safetyData, setSafetyData] = useState({
    campana_activa: true,
    kill_switch_activado: false,
    es_horario_laboral: true,
    detalle_horario: 'Lunes a Viernes de 09:00 a 18:00 hrs',
    invitaciones_hoy: 0,
    limite_invitaciones_hoy: 8,
    mensajes_hoy: 0,
    emails_hoy: 0,
  });

  // 2. Curva de Calentamiento y Cuota Comercial de LinkedIn
  const [warmupData, setWarmupData] = useState({
    semana_actual: 1,
    limite_diario_actual: 15,
    dias_en_fase: 2,
    curva: [
      { semana: 1, limite: 15, etiqueta: 'Semana 1', activo: true, descripcion: 'Inicio seguro y acondicionamiento' },
      { semana: 2, limite: 18, etiqueta: 'Semana 2', activo: false, descripcion: 'Incremento moderado de actividad' },
      { semana: 3, limite: 22, etiqueta: 'Semana 3', activo: false, descripcion: 'Consolidación de red y ritmo' },
      { semana: 4, limite: 25, etiqueta: 'Semana 4+', activo: false, descripcion: 'Régimen de crucero óptimo (Free)' },
    ],
    busquedas: {
      usadas_este_mes: 24,
      limite_mensual: 100,
      restantes: 76,
      porcentaje: 24,
    }
  });

  // 3. Blindaje WhatsApp Web
  const [whatsappData, setWhatsappData] = useState({
    enviados_hoy: 0,
    limite_diario: 15,
    horario_seguro: true,
    pausa_promedio_seg: 65,
  });

  useEffect(() => {
    loadAllSafetyData();
  }, []);

  async function loadAllSafetyData(showRefreshIndicator = false) {
    try {
      if (showRefreshIndicator) setRefreshing(true);
      else setLoading(true);

      const [safetyRes, warmupRes, whatsappRes] = await Promise.all([
        fetchSafetyStatus().catch(() => null),
        getLinkedInWarmupStatus().catch(() => null),
        getWhatsAppSafetyStatus().catch(() => null),
      ]);

      // Procesar Estado General y Horario
      if (safetyRes) {
        const enHorario = Boolean(safetyRes.horario_laboral?.en_horario);
        const detalle = safetyRes.horario_laboral?.detalle || 'Lunes a Viernes de 09:00 a 18:00 hrs';
        const isKillSwitch = Boolean(safetyRes.kill_switch?.activado);
        const invHoy = safetyRes.linkedin?.acciones_hoy ?? 0;
        const limInv = safetyRes.linkedin?.limite_diario ?? 8;

        setSafetyData({
          campana_activa: !isKillSwitch,
          kill_switch_activado: isKillSwitch,
          es_horario_laboral: enHorario,
          detalle_horario: detalle,
          invitaciones_hoy: invHoy,
          limite_invitaciones_hoy: limInv,
          mensajes_hoy: safetyRes.mensajes_hoy ?? 0,
          emails_hoy: safetyRes.google_workspace?.correos_hoy ?? 0,
        });
      }

      // Procesar Curva Warm-up y Búsquedas Comerciales
      if (warmupRes) {
        const w = warmupRes.warmup || {};
        const b = warmupRes.busquedas_comerciales || {};
        const sem = w.semana || 1;
        const lim = w.limite_diario || 15;

        const curva = w.curva || [
          { semana: 1, limite: 15, etiqueta: 'Semana 1', activo: sem === 1, descripcion: 'Inicio seguro y acondicionamiento' },
          { semana: 2, limite: 18, etiqueta: 'Semana 2', activo: sem === 2, descripcion: 'Incremento moderado de actividad' },
          { semana: 3, limite: 22, etiqueta: 'Semana 3', activo: sem === 3, descripcion: 'Consolidación de red y ritmo' },
          { semana: 4, limite: 25, etiqueta: 'Semana 4+', activo: sem >= 4, descripcion: 'Régimen de crucero óptimo (Free)' },
        ];

        setWarmupData({
          semana_actual: sem,
          limite_diario_actual: lim,
          dias_en_fase: w.dias_activo || 2,
          curva,
          busquedas: {
            usadas_este_mes: b.usadas_este_mes || 0,
            limite_mensual: b.limite_mensual || 100,
            restantes: b.restantes || Math.max(0, 100 - (b.usadas_este_mes || 0)),
            porcentaje: b.porcentaje_usado || Math.round(((b.usadas_este_mes || 0) / (b.limite_mensual || 100)) * 100),
          }
        });
      }

      // Procesar Blindaje WhatsApp
      if (whatsappRes) {
        const uso = whatsappRes.uso_diario || {};
        const seg = whatsappRes.seguridad || {};
        setWhatsappData({
          enviados_hoy: uso.enviados_hoy || 0,
          limite_diario: uso.limite_diario || 15,
          horario_seguro: Boolean(seg.horario_seguro !== false),
          pausa_promedio_seg: whatsappRes.pausa_sugerida_segundos || 60,
        });
      }
    } catch (err) {
      console.error('Error cargando monitoreo de seguridad:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  // Interruptor Maestro (Kill-Switch)
  async function handleToggleKillSwitch() {
    const nextKillState = !safetyData.kill_switch_activado;
    try {
      await toggleCampaign(!nextKillState);
      setSafetyData(prev => ({
        ...prev,
        kill_switch_activado: nextKillState,
        campana_activa: !nextKillState,
      }));
      setNotification({
        type: nextKillState ? 'warning' : 'success',
        text: nextKillState
          ? 'KILL-SWITCH ACTIVADO: Todas las secuencias multicanal han entrado en pausa de emergencia.'
          : 'BLINDAJE REANUDADO: Las secuencias continuarán su ejecución respetando el warm-up y pausas estocásticas.'
      });
      setTimeout(() => setNotification(null), 7000);
    } catch (err) {
      alert(`Error alternando Kill-Switch: ${err.message}`);
    }
  }

  // Sincronizar Conexiones Aceptadas
  async function handleSyncConnections() {
    try {
      setSyncingConnections(true);
      setNotification(null);
      const res = await syncAcceptedConnections();
      if (res && res.ok) {
        setNotification({
          type: 'success',
          text: res.mensaje || `Auditoría finalizada: ${res.nuevos_conectados || 0} nuevas conexiones detectadas y actualizadas en base de datos.`
        });
        await loadAllSafetyData(true);
      } else {
        setNotification({
          type: 'error',
          text: res?.mensaje || 'No se pudo completar la sincronización con LinkedIn.'
        });
      }
    } catch (err) {
      setNotification({
        type: 'error',
        text: `Error al auditar conexiones: ${err.message}`
      });
    } finally {
      setSyncingConnections(false);
      setTimeout(() => setNotification(null), 8000);
    }
  }

  // Retirar Invitaciones Antiguas
  async function handleWithdrawStale() {
    if (!confirm(`¿Deseas retirar automáticamente las invitaciones pendientes que lleven más de ${staleDays} días sin respuesta?\n\nEsta medida protege tu ratio de aceptación y evita penalizaciones en el algoritmo de LinkedIn.`)) {
      return;
    }
    try {
      setWithdrawingStale(true);
      setNotification(null);
      const res = await withdrawStaleInvitations(staleDays);
      setNotification({
        type: 'success',
        text: `Retiro preventivo finalizado: ${res.retiradas || 0} invitaciones antiguas retiradas exitosamente de LinkedIn.`
      });
      await loadAllSafetyData(true);
    } catch (err) {
      setNotification({
        type: 'error',
        text: `Error retirando invitaciones antiguas: ${err.message}`
      });
    } finally {
      setWithdrawingStale(false);
      setTimeout(() => setNotification(null), 8000);
    }
  }

  const isShieldFullyActive = !safetyData.kill_switch_activado;

  return (
    <div className="flex-1 overflow-y-auto bg-[#090A0C] p-5 md:p-8 space-y-6 font-sans">
      {/* 1. Header Principal y Estado Ejecutivo */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-white/[0.08] pb-5">
        <div>
          <div className="flex items-center gap-3">
            <div className={`p-2.5 rounded-xl border flex items-center justify-center shrink-0 ${
              isShieldFullyActive 
                ? 'bg-emerald-950/60 text-emerald-400 border-emerald-500/30 shadow-sm shadow-emerald-900/30' 
                : 'bg-rose-950/60 text-rose-400 border-rose-500/30 shadow-sm shadow-rose-900/30'
            }`}>
              <ShieldCheck className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-2.5 flex-wrap">
                <h1 className="text-xl md:text-2xl font-bold tracking-tight text-zinc-100">
                  Centro de Monitoreo Antiban & Blindaje Autónomo
                </h1>
                <span className={`text-[11px] px-2.5 py-0.5 rounded-full font-mono font-medium border flex items-center gap-1.5 ${
                  isShieldFullyActive 
                    ? 'bg-emerald-950/80 text-emerald-300 border-emerald-500/40' 
                    : 'bg-rose-950/80 text-rose-300 border-rose-500/40'
                }`}>
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${isShieldFullyActive ? 'bg-emerald-400 animate-pulse' : 'bg-rose-400'}`} />
                  <span>{isShieldFullyActive ? 'BLINDAJE AUTÓNOMO 100% ACTIVO' : 'KILL-SWITCH ACTIVADO (EN PAUSA)'}</span>
                </span>
              </div>
              <p className="text-xs text-zinc-400 mt-1 max-w-3xl leading-relaxed">
                Supervisión en tiempo real de los algoritmos de calentamiento (Warm-up), retardos estocásticos gaussianos y preservación de cuentas en LinkedIn, WhatsApp Web y Google Workspace.
              </p>
            </div>
          </div>
        </div>

        {/* Botones de Acción Superior */}
        <div className="flex items-center gap-2 shrink-0 flex-wrap">
          <button
            onClick={() => loadAllSafetyData(true)}
            disabled={refreshing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-900 hover:bg-zinc-800 text-zinc-300 hover:text-zinc-100 text-xs font-medium border border-zinc-800 transition cursor-pointer disabled:opacity-50"
            title="Actualizar datos de seguridad en tiempo real"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin text-sky-400' : ''}`} />
            <span>Refrescar</span>
          </button>

          {/* Navegadores Aislados en Chromium */}
          <div className="flex items-center gap-1 bg-zinc-900/80 p-1 rounded-lg border border-white/[0.06]">
            <button
              onClick={() => showWorkBrowser('https://www.linkedin.com/feed/', 'linkedin')}
              className="px-2.5 py-1 rounded-md text-[11px] font-medium text-sky-300 hover:bg-zinc-800 transition cursor-pointer flex items-center gap-1"
              title="Abrir ventana de LinkedIn en Chromium Aislado"
            >
              <Globe className="w-3 h-3 text-sky-400" />
              <span>LinkedIn</span>
            </button>
            <button
              onClick={() => showWorkBrowser('https://web.whatsapp.com', 'whatsapp')}
              className="px-2.5 py-1 rounded-md text-[11px] font-medium text-emerald-300 hover:bg-zinc-800 transition cursor-pointer flex items-center gap-1"
              title="Abrir ventana de WhatsApp Web en Chromium Aislado"
            >
              <MessageSquare className="w-3 h-3 text-emerald-400" />
              <span>WhatsApp</span>
            </button>
            <button
              onClick={() => showWorkBrowser(null, 'zoho')}
              className="px-2.5 py-1 rounded-md text-[11px] font-medium text-amber-300 hover:bg-zinc-800 transition cursor-pointer flex items-center gap-1"
              title="Abrir o autenticar Zoho CRM en Chromium Aislado"
            >
              <Building2 className="w-3 h-3 text-amber-400" />
              <span>Zoho</span>
            </button>
          </div>
        </div>
      </div>

      {/* Banner de Notificación Contextual */}
      {notification && (
        <div className={`p-4 rounded-xl border text-xs flex items-center justify-between gap-3 animate-fadeIn ${
          notification.type === 'success'
            ? 'bg-emerald-950/40 border-emerald-500/40 text-emerald-200'
            : notification.type === 'warning'
            ? 'bg-amber-950/40 border-amber-500/40 text-amber-200'
            : 'bg-rose-950/40 border-rose-500/40 text-rose-200'
        }`}>
          <div className="flex items-center gap-2.5">
            {notification.type === 'success' && <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />}
            {notification.type === 'warning' && <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />}
            {notification.type === 'error' && <ShieldAlert className="w-4 h-4 text-rose-400 shrink-0" />}
            <span>{notification.text}</span>
          </div>
          <button
            onClick={() => setNotification(null)}
            className="text-zinc-400 hover:text-zinc-200 text-xs px-2 py-0.5"
          >
            &times;
          </button>
        </div>
      )}

      {/* 2. Tarjeta Destacada: Interruptor Maestro (Kill-Switch) de Emergencia */}
      <div className={`p-5 rounded-2xl border transition-all ${
        safetyData.kill_switch_activado
          ? 'bg-gradient-to-r from-rose-950/40 via-zinc-900 to-rose-950/30 border-rose-500/40 shadow-lg shadow-rose-950/20'
          : 'bg-gradient-to-r from-emerald-950/30 via-[#121316] to-zinc-900 border-white/[0.08]'
      }`}>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3.5">
            <div className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 border ${
              safetyData.kill_switch_activado
                ? 'bg-rose-500/20 border-rose-500/40 text-rose-400'
                : 'bg-emerald-500/20 border-emerald-500/40 text-emerald-400'
            }`}>
              <Power className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-semibold text-zinc-100">
                  Interruptor Maestro de Seguridad (Kill-Switch)
                </h2>
                <span className={`text-[10px] px-2 py-0.2 rounded-full font-mono border ${
                  safetyData.kill_switch_activado
                    ? 'bg-rose-950 text-rose-300 border-rose-500/40'
                    : 'bg-emerald-950 text-emerald-300 border-emerald-500/40'
                }`}>
                  {safetyData.kill_switch_activado ? 'DETENIDO' : 'EN OPERACIÓN'}
                </span>
              </div>
              <p className="text-xs text-zinc-400 mt-0.5 leading-relaxed">
                {safetyData.kill_switch_activado
                  ? 'PARADA DE EMERGENCIA ACTIVA: Todas las secuencias multicanal están temporalmente congeladas. Ninguna acción de contacto se ejecutará.'
                  : 'Modo autónomo operando con normalidad. Ante cualquier sospecha o aviso en LinkedIn, activa este botón para detener inmediatamente todo el flujo.'}
              </p>
            </div>
          </div>

          <button
            onClick={handleToggleKillSwitch}
            className={`px-4 py-2 rounded-xl text-xs font-semibold shadow-sm transition cursor-pointer shrink-0 flex items-center gap-2 ${
              safetyData.kill_switch_activado
                ? 'bg-emerald-500 hover:bg-emerald-400 text-zinc-950 shadow-emerald-500/20'
                : 'bg-rose-950/80 hover:bg-rose-900 text-rose-200 border border-rose-500/40 shadow-rose-950/40'
            }`}
          >
            <Power className="w-3.5 h-3.5" />
            <span>{safetyData.kill_switch_activado ? 'Reanudar Actividad Segura' : 'Pausar Todo de Emergencia'}</span>
          </button>
        </div>
      </div>

      {/* 3. Grid Principal: Curva de Warm-up & Radar de Búsqueda Comercial */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        
        {/* PANEL A: Curva de Calentamiento Autónoma de LinkedIn (2 columnas) */}
        <div className="lg:col-span-2 p-5 rounded-2xl bg-[#121316] border border-white/[0.08] space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-white/[0.06] pb-3">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-lg bg-emerald-950/60 text-emerald-400 border border-emerald-500/30">
                <TrendingUp className="w-4 h-4" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-zinc-100 flex items-center gap-2">
                  <span>Curva Progresiva de Calentamiento (Warm-up Program)</span>
                  <span className="text-[10px] px-2 py-0.2 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-500/30 font-mono">
                    Semana {warmupData.semana_actual} de 4
                  </span>
                </h3>
                <p className="text-[11px] text-zinc-400">
                  Escalamiento semanal automático de volumen para no alertar a los algoritmos heurísticos de LinkedIn.
                </p>
              </div>
            </div>

            <div className="text-right">
              <span className="text-[11px] text-zinc-400 font-mono">Cuota Hoy: </span>
              <span className="text-xs font-mono font-bold text-emerald-300">
                {safetyData.invitaciones_hoy} / {warmupData.limite_diario_actual} inv.
              </span>
            </div>
          </div>

          {/* Barra de progreso de consumo de hoy */}
          <div className="space-y-1.5 p-3 rounded-xl bg-[#0D0E12] border border-white/[0.04]">
            <div className="flex items-center justify-between text-xs">
              <span className="text-zinc-400 text-[11px]">Consumo diario actual (Semana {warmupData.semana_actual})</span>
              <span className="font-mono text-zinc-200 font-medium">
                {safetyData.invitaciones_hoy} de {warmupData.limite_diario_actual} invitaciones despachadas
              </span>
            </div>
            <div className="w-full h-2 rounded-full bg-zinc-800 overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-emerald-500 to-teal-400 transition-all duration-500 rounded-full"
                style={{
                  width: `${Math.min(100, Math.round((safetyData.invitaciones_hoy / (warmupData.limite_diario_actual || 15)) * 100))}%`
                }}
              />
            </div>
            <div className="flex items-center justify-between text-[10px] text-zinc-500 font-mono">
              <span>{Math.max(0, (warmupData.limite_diario_actual || 15) - safetyData.invitaciones_hoy)} cupos disponibles hoy</span>
              <span>Reinicio automático cada medianoche</span>
            </div>
          </div>

          {/* Tarjetas de las 4 Fases de la Curva */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 pt-1">
            {warmupData.curva.map((fase) => {
              const isCurrent = fase.semana === warmupData.semana_actual;
              const isPassed = fase.semana < warmupData.semana_actual;
              return (
                <div
                  key={fase.semana}
                  className={`p-3 rounded-xl border flex flex-col justify-between transition-all ${
                    isCurrent
                      ? 'bg-emerald-950/40 border-emerald-500/40 shadow-sm shadow-emerald-950/40'
                      : isPassed
                      ? 'bg-zinc-900/60 border-zinc-800/80 text-zinc-400'
                      : 'bg-zinc-900/30 border-zinc-850 text-zinc-500'
                  }`}
                >
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className={`text-[10px] font-mono uppercase font-semibold ${
                        isCurrent ? 'text-emerald-400' : isPassed ? 'text-zinc-400' : 'text-zinc-600'
                      }`}>
                        {fase.etiqueta}
                      </span>
                      {isCurrent && (
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                      )}
                      {isPassed && (
                        <Check className="w-3 h-3 text-zinc-500" />
                      )}
                    </div>
                    <div className={`text-xl font-bold font-mono tracking-tight ${
                      isCurrent ? 'text-emerald-300' : isPassed ? 'text-zinc-300' : 'text-zinc-500'
                    }`}>
                      {fase.limite} <span className="text-[10px] font-normal font-sans text-zinc-500">/día</span>
                    </div>
                  </div>

                  <p className="text-[10px] text-zinc-400 mt-2 leading-tight">
                    {fase.descripcion}
                  </p>
                </div>
              );
            })}
          </div>

          <div className="text-[11px] text-zinc-400 bg-zinc-900/40 p-2.5 rounded-lg border border-white/[0.04] flex items-center gap-2">
            <Info className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
            <span>
              <strong>Fórmula Antiban:</strong> El sistema avanza a la siguiente semana tras cumplir 7 días de actividad regular. No requiere configuración manual.
            </span>
          </div>
        </div>

        {/* PANEL B: Radar de Cuota de Búsqueda Comercial (1 columna) */}
        <div className="p-5 rounded-2xl bg-[#121316] border border-white/[0.08] space-y-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center gap-2.5 border-b border-white/[0.06] pb-3">
              <div className="p-2 rounded-lg bg-sky-950/60 text-sky-400 border border-sky-500/30 shrink-0">
                <Search className="w-4 h-4" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-zinc-100">
                  Límite de Búsqueda Comercial
                </h3>
                <p className="text-[11px] text-zinc-400">
                  Protección de cuota mensual gratuita de LinkedIn
                </p>
              </div>
            </div>

            <div className="pt-4 space-y-3">
              <div className="text-center py-2">
                <div className="text-3xl font-bold font-mono text-zinc-100 tracking-tight">
                  {warmupData.busquedas.restantes}
                </div>
                <span className="text-[11px] text-zinc-400 font-mono">
                  búsquedas comerciales restantes este mes
                </span>
              </div>

              {/* Barra de progreso mensual */}
              <div className="space-y-1">
                <div className="flex justify-between text-[11px] font-mono text-zinc-400">
                  <span>Usadas: {warmupData.busquedas.usadas_este_mes}</span>
                  <span>Tope: {warmupData.busquedas.limite_mensual}</span>
                </div>
                <div className="w-full h-2 rounded-full bg-zinc-800 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      warmupData.busquedas.porcentaje > 80
                        ? 'bg-rose-500'
                        : warmupData.busquedas.porcentaje > 50
                        ? 'bg-amber-400'
                        : 'bg-sky-400'
                    }`}
                    style={{ width: `${Math.min(100, warmupData.busquedas.porcentaje)}%` }}
                  />
                </div>
              </div>

              <div className="p-3 rounded-xl bg-[#0D0E12] border border-white/[0.04] space-y-1.5 text-[11px] text-zinc-400 leading-relaxed">
                <div className="font-semibold text-zinc-200 flex items-center gap-1.5">
                  <ShieldCheck className="w-3.5 h-3.5 text-sky-400" />
                  <span>Optimizador de Extracción NexusReach</span>
                </div>
                <p>
                  LinkedIn limita las cuentas sin Sales Navigator a ~100 búsquedas de personas al mes. NexusReach pagina los resultados para extraer hasta 10 leads por consulta, maximizando tu rendimiento sin quemar la cuota.
                </p>
              </div>
            </div>
          </div>

          <div className="text-[10px] text-zinc-500 font-mono text-center pt-2 border-t border-white/[0.04]">
            La cuota se renueva el día 1 de cada mes
          </div>
        </div>
      </div>

      {/* 4. Grid Secundario: Temporizador Estocástico & Blindaje Multicanal */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">

        {/* TARJETA 1: Pausas Estocásticas y Horario Hábil */}
        <div className="p-5 rounded-2xl bg-[#121316] border border-white/[0.08] space-y-3.5">
          <div className="flex items-center gap-2.5 border-b border-white/[0.06] pb-3">
            <div className="p-2 rounded-lg bg-purple-950/60 text-purple-400 border border-purple-500/30 shrink-0">
              <Clock className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-zinc-100">
                Pausas Estocásticas Gaussianas
              </h3>
              <p className="text-[11px] text-zinc-400">
                Variación humana aleatoria entre acciones
              </p>
            </div>
          </div>

          <div className="space-y-2 text-xs">
            <div className="p-2.5 rounded-xl bg-[#0D0E12] border border-white/[0.04] flex items-center justify-between font-mono">
              <span className="text-zinc-400 text-[11px]">Pausa entre invitaciones:</span>
              <span className="text-purple-300 font-bold">180s — 360s (aleatorio)</span>
            </div>
            <div className="p-2.5 rounded-xl bg-[#0D0E12] border border-white/[0.04] flex items-center justify-between font-mono">
              <span className="text-zinc-400 text-[11px]">Scroll y permanencia en perfil:</span>
              <span className="text-purple-300 font-bold">5s — 15s progresivo</span>
            </div>
            <div className="p-2.5 rounded-xl bg-[#0D0E12] border border-white/[0.04] flex items-center justify-between font-mono">
              <span className="text-zinc-400 text-[11px]">Horario comercial programado:</span>
              <span className="text-zinc-200">Lun - Vie &bull; 09:00 - 18:00</span>
            </div>
          </div>

          <div className="p-2.5 rounded-lg bg-zinc-900/60 border border-white/[0.04] flex items-center gap-2 text-[11px]">
            <span className={`w-2 h-2 rounded-full shrink-0 ${safetyData.es_horario_laboral ? 'bg-emerald-400' : 'bg-amber-400'}`} />
            <span className={safetyData.es_horario_laboral ? 'text-emerald-300' : 'text-amber-300'}>
              {safetyData.es_horario_laboral ? 'Dentro de jornada laboral hábil' : 'Fuera de jornada (despachos en reposo)'}
            </span>
          </div>
        </div>

        {/* TARJETA 2: Blindaje de WhatsApp Web Local */}
        <div className="p-5 rounded-2xl bg-[#121316] border border-white/[0.08] space-y-3.5">
          <div className="flex items-center gap-2.5 border-b border-white/[0.06] pb-3">
            <div className="p-2 rounded-lg bg-emerald-950/60 text-emerald-400 border border-emerald-500/30 shrink-0">
              <MessageSquare className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-zinc-100">
                Blindaje WhatsApp Web
              </h3>
              <p className="text-[11px] text-zinc-400">
                Control de cadencia para evitar bloqueos de Meta
              </p>
            </div>
          </div>

          <div className="space-y-2 text-xs">
            <div className="p-2.5 rounded-xl bg-[#0D0E12] border border-white/[0.04] flex items-center justify-between font-mono">
              <span className="text-zinc-400 text-[11px]">Enviados hoy / Límite diario:</span>
              <span className="text-emerald-300 font-bold">
                {whatsappData.enviados_hoy} / {whatsappData.limite_diario} msgs
              </span>
            </div>
            <div className="p-2.5 rounded-xl bg-[#0D0E12] border border-white/[0.04] flex items-center justify-between font-mono">
              <span className="text-zinc-400 text-[11px]">Pausa estocástica por mensaje:</span>
              <span className="text-emerald-300 font-bold">45s — 90s con retardo</span>
            </div>
            <div className="p-2.5 rounded-xl bg-[#0D0E12] border border-white/[0.04] flex items-center justify-between font-mono">
              <span className="text-zinc-400 text-[11px]">Rotación Spintax:</span>
              <span className="text-emerald-400 font-medium">Activa obligatoria</span>
            </div>
          </div>

          <div className="text-[11px] text-zinc-400 leading-relaxed">
            WhatsApp analiza ráfagas de mensajes idénticos. NexusReach varía los saludos y textos con Spintax para que cada mensaje sea único.
          </div>
        </div>

        {/* TARJETA 3: Blindaje de Correo Electrónico (Google Workspace & Cascada) */}
        <div className="p-5 rounded-2xl bg-[#121316] border border-white/[0.08] space-y-3.5">
          <div className="flex items-center gap-2.5 border-b border-white/[0.06] pb-3">
            <div className="p-2 rounded-lg bg-teal-950/60 text-teal-400 border border-teal-500/30 shrink-0">
              <Mail className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-zinc-100">
                Entregabilidad de Correo (Workspace)
              </h3>
              <p className="text-[11px] text-zinc-400">
                Protección de reputación del dominio corporativo
              </p>
            </div>
          </div>

          <div className="space-y-2 text-xs">
            <div className="p-2.5 rounded-xl bg-[#0D0E12] border border-white/[0.04] flex items-center justify-between font-mono">
              <span className="text-zinc-400 text-[11px]">Correos hoy / Techo seguro:</span>
              <span className="text-teal-300 font-bold">
                {safetyData.emails_hoy} / 25 diarios
              </span>
            </div>
            <div className="p-2.5 rounded-xl bg-[#0D0E12] border border-white/[0.04] flex items-center justify-between font-mono">
              <span className="text-zinc-400 text-[11px]">Validación previa DNS MX:</span>
              <span className="text-teal-400 font-medium">100% verificado</span>
            </div>
            <div className="p-2.5 rounded-xl bg-[#0D0E12] border border-white/[0.04] flex items-center justify-between font-mono">
              <span className="text-zinc-400 text-[11px]">Pausa entre correos:</span>
              <span className="text-teal-300 font-bold">240s — 480s</span>
            </div>
          </div>

          <div className="text-[11px] text-zinc-400 leading-relaxed">
            Antes de cada despacho, el motor confirma la existencia de registros DNS MX válidos para prevenir rebotes (Bounces) y proteger el SPF/DKIM de tu dominio.
          </div>
        </div>
      </div>

      {/* 5. Bloque de Mantenimiento Activo de Reputación */}
      <div className="p-5 rounded-2xl bg-[#121316] border border-white/[0.08] space-y-4">
        <div className="border-b border-white/[0.06] pb-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-zinc-100 flex items-center gap-2">
              <Lock className="w-4 h-4 text-emerald-400" />
              <span>Herramientas de Mantenimiento Activo de Reputación</span>
            </h3>
            <p className="text-[11px] text-zinc-400 mt-0.5">
              Acciones de higiene preventiva recomendadas por los lineamientos de algoritmos de prospección.
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-1">
          {/* Herramienta 1: Retiro de Invitaciones Vencidas */}
          <div className="p-4 rounded-xl bg-[#0D0E12] border border-white/[0.04] space-y-3 flex flex-col justify-between">
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-zinc-200">
                  Retiro de Invitaciones Vencidas (&gt; {staleDays} días)
                </span>
                <span className="text-[10px] text-amber-400 font-mono">Higiene SSI</span>
              </div>
              <p className="text-[11px] text-zinc-400 leading-relaxed">
                Tener un volumen alto de invitaciones sin responder por más de 3 semanas daña tu tasa de aceptación y puede generar restricciones preventivas en LinkedIn.
              </p>
            </div>

            <div className="flex items-center gap-2 pt-2 border-t border-zinc-800/60">
              <select
                value={staleDays}
                onChange={(e) => setStaleDays(parseInt(e.target.value, 10))}
                className="bg-zinc-900 border border-zinc-700 px-2 py-1.5 rounded-lg text-xs text-zinc-200 cursor-pointer"
              >
                <option value={14}>Más de 14 días</option>
                <option value={21}>Más de 21 días (Recomendado)</option>
                <option value={30}>Más de 30 días</option>
              </select>

              <button
                onClick={handleWithdrawStale}
                disabled={withdrawingStale}
                className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-medium border border-zinc-700 transition cursor-pointer disabled:opacity-50"
              >
                <UserX className={`w-3.5 h-3.5 ${withdrawingStale ? 'animate-spin text-amber-400' : ''}`} />
                <span>{withdrawingStale ? 'Retirando...' : 'Retirar en Lote'}</span>
              </button>
            </div>
          </div>

          {/* Herramienta 2: Auditoría y Detección de Conexiones Aceptadas */}
          <div className="p-4 rounded-xl bg-[#0D0E12] border border-white/[0.04] space-y-3 flex flex-col justify-between">
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-zinc-200">
                  Auditoría de Nuevas Conexiones Aceptadas
                </span>
                <span className="text-[10px] text-teal-400 font-mono">Sync LinkedIn</span>
              </div>
              <p className="text-[11px] text-zinc-400 leading-relaxed">
                Explora tu buzón de conexiones en LinkedIn para detectar prospectos que han aceptado tu invitación y promoverlos de inmediato al siguiente paso del flujo.
              </p>
            </div>

            <div className="pt-2 border-t border-zinc-800/60 flex items-center justify-end">
              <button
                onClick={handleSyncConnections}
                disabled={syncingConnections}
                className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg bg-teal-950/70 hover:bg-teal-900/80 text-teal-300 text-xs font-medium border border-teal-500/30 transition cursor-pointer disabled:opacity-50"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${syncingConnections ? 'animate-spin' : ''}`} />
                <span>{syncingConnections ? 'Auditando red en LinkedIn...' : 'Auditar y Sincronizar Conexiones Ahora'}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
