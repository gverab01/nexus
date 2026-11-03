// Banner interactivo de monitoreo en tiempo real del Piloto Automático (Runner Local / Nube)
// Incluye contador regresivo segundo a segundo, telemetría de pasos y adelanto manual de pausas.

import React, { useState, useEffect, useMemo, useRef } from 'react';
import { 
  Zap, 
  Pause, 
  Play, 
  Clock, 
  FastForward, 
  ShieldCheck, 
  CheckCircle2, 
  AlertCircle, 
  Loader2, 
  User, 
  Building2, 
  Sparkles, 
  RefreshCw 
} from 'lucide-react';

export default function AutopilotBanner({
  workerState = {},
  onToggleAutopilot,
  togglingAutopilot = false,
  onForceNext,
  isForcingNext = false
}) {
  const isAutopilotActive = Boolean(workerState.piloto_automatico);
  const rawStatus = workerState.estado_actual || '';

  // Referencias para anclaje inteligente del temporizador local
  const countdownAnchorRef = useRef({
    targetTime: null,
    totalSeconds: null,
    sourceString: ''
  });

  const [remainingSeconds, setRemainingSeconds] = useState(null);
  const [totalSeconds, setTotalSeconds] = useState(null);

  const handleForceClick = async () => {
    countdownAnchorRef.current = { targetTime: null, totalSeconds: null, sourceString: '' };
    setRemainingSeconds(null);
    if (onForceNext) {
      await onForceNext();
    }
  };

  // 1. Detección y Sincronización del Contador Regresivo
  useEffect(() => {
    if (!isAutopilotActive) {
      countdownAnchorRef.current = { targetTime: null, totalSeconds: null, sourceString: '' };
      setRemainingSeconds(null);
      setTotalSeconds(null);
      return;
    }

    // Caso A: El servidor entrega timestamp explícito en ms
    if (workerState.cuenta_regresiva_hasta) {
      const target = Number(workerState.cuenta_regresiva_hasta);
      const total = Number(workerState.segundos_totales) || Math.max(1, Math.ceil((target - Date.now()) / 1000));
      countdownAnchorRef.current = {
        targetTime: target,
        totalSeconds: total,
        sourceString: rawStatus
      };
      const diff = Math.max(0, Math.ceil((target - Date.now()) / 1000));
      setRemainingSeconds(diff);
      setTotalSeconds(total);
      return;
    }

    // Caso B: Fallback inteligente mediante análisis del texto (ej. "esperando 282s antes del próximo lead...")
    const match = rawStatus.match(/esperando\s+(\d+)\s*s/i) || 
                  rawStatus.match(/espera:\s*(\d+)\s*s/i) || 
                  rawStatus.match(/(\d+)\s*s(?:egundos)?\s+antes/i);

    if (match) {
      const extractedSecs = parseInt(match[1], 10);
      const currentAnchor = countdownAnchorRef.current;

      // Si no tenemos anclaje previo o el valor difiere drásticamente (nuevo ciclo), anclamos
      const isNewCycle = !currentAnchor.targetTime || 
                         Math.abs(currentAnchor.totalSeconds - extractedSecs) > 8 ||
                         currentAnchor.sourceString !== rawStatus;

      if (isNewCycle) {
        const now = Date.now();
        const target = now + (extractedSecs * 1000);
        countdownAnchorRef.current = {
          targetTime: target,
          totalSeconds: extractedSecs,
          sourceString: rawStatus
        };
        setRemainingSeconds(extractedSecs);
        setTotalSeconds(extractedSecs);
      }
    } else {
      // Si el estado actual es de ejecución activa o consulta sin espera, reseteamos el contador
      if (rawStatus.includes('Ejecutando:') || rawStatus.includes('Consultando') || rawStatus.includes('Navegando')) {
        countdownAnchorRef.current = { targetTime: null, totalSeconds: null, sourceString: '' };
        setRemainingSeconds(null);
        setTotalSeconds(null);
      }
    }
  }, [workerState.cuenta_regresiva_hasta, workerState.segundos_totales, rawStatus, isAutopilotActive]);

  // 2. Intervalo Local de 1 Segundo (Tick down continuo sin parpadeo)
  useEffect(() => {
    if (!isAutopilotActive || !countdownAnchorRef.current.targetTime) return;

    const interval = setInterval(() => {
      const { targetTime } = countdownAnchorRef.current;
      if (!targetTime) return;

      const diff = Math.max(0, Math.ceil((targetTime - Date.now()) / 1000));
      setRemainingSeconds(diff);

      if (diff <= 0) {
        countdownAnchorRef.current.targetTime = null;
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [isAutopilotActive]);

  // 3. Formateador de tiempo visual (MM:SS)
  const formattedCountdown = useMemo(() => {
    if (remainingSeconds === null || remainingSeconds <= 0) return null;
    const mins = Math.floor(remainingSeconds / 60);
    const secs = remainingSeconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }, [remainingSeconds]);

  // Porcentaje de progreso de la pausa (0% a 100%)
  const progressPercent = useMemo(() => {
    if (!totalSeconds || remainingSeconds === null) return 0;
    const elapsed = totalSeconds - remainingSeconds;
    return Math.min(100, Math.max(0, Math.round((elapsed / totalSeconds) * 100)));
  }, [totalSeconds, remainingSeconds]);

  // 4. Clasificación de Fase y Telemetría Detallada
  const telemetry = useMemo(() => {
    if (!isAutopilotActive) {
      return {
        fase: 'reposo',
        badgeTexto: 'EN REPOSO',
        badgeColor: 'bg-zinc-800 text-zinc-400 border-zinc-700',
        titulo: 'Piloto Automático: En Pausa / Reposo',
        descripcion: 'Las secuencias están detenidas. Haz clic en Activar para iniciar el envío programado.',
        tipoVisual: 'reposo'
      };
    }

    const rawLower = rawStatus.toLowerCase();
    const faseProp = (workerState.fase || '').toLowerCase();

    // Fase: Pausa humana de seguridad
    if (faseProp === 'pausa_humana' || rawLower.includes('pausa humana') || rawLower.includes('esperando')) {
      return {
        fase: 'pausa_humana',
        badgeTexto: 'PAUSA HUMANA ANTIBAN',
        badgeColor: 'bg-amber-950/80 text-amber-300 border-amber-500/30',
        titulo: 'Pausa de Seguridad Humana Antiban',
        descripcion: workerState.detalle_accion || 'Esperando intervalo estocástico aleatorio antes del próximo lead para proteger tu cuenta de LinkedIn.',
        tipoVisual: 'pausa'
      };
    }

    // Fase: Ejecución activa
    if (faseProp === 'ejecutando' || rawLower.includes('ejecutando:') || rawLower.includes('navegando') || rawLower.includes('emulando')) {
      const prospecto = workerState.prospecto_actual || '';
      const canal = workerState.canal || 'LinkedIn';
      return {
        fase: 'ejecutando',
        badgeTexto: 'EJECUTANDO AHORA',
        badgeColor: 'bg-sky-950/90 text-sky-300 border-sky-500/40 animate-pulse',
        titulo: workerState.accion_actual || `Ejecutando acción en ${canal}`,
        descripcion: workerState.detalle_accion || (prospecto ? `Procesando paso para ${prospecto} en ${canal}...` : 'Navegando y ejecutando interacción en navegador...'),
        tipoVisual: 'ejecutando'
      };
    }

    // Fase: Consultando órdenes
    if (faseProp === 'consultando' || rawLower.includes('consultando')) {
      return {
        fase: 'consultando',
        badgeTexto: 'SINCRONIZANDO',
        badgeColor: 'bg-indigo-950/80 text-indigo-300 border-indigo-500/30',
        titulo: 'Consultando órdenes al despachador en la nube...',
        descripcion: 'Verificando prospectos listos, cupos antiban disponibles y filtros de horario laboral.',
        tipoVisual: 'consultando'
      };
    }

    // Fase: Espera de condiciones (Horario, cupo o cola vacía)
    if (faseProp === 'espera_cola' || rawLower.includes('seguridad:') || rawLower.includes('horario') || rawLower.includes('sin tareas') || rawLower.includes('cupo')) {
      return {
        fase: 'espera_cola',
        badgeTexto: 'EN ESPERA DE CONDICIONES',
        badgeColor: 'bg-orange-950/80 text-orange-300 border-orange-500/30',
        titulo: workerState.accion_actual || rawStatus || 'Esperando condiciones óptimas de campaña',
        descripcion: workerState.detalle_accion || 'El despachador reevaluará automáticamente la cola al finalizar la espera programada.',
        tipoVisual: 'condiciones'
      };
    }

    // Fallback general activo
    return {
      fase: 'activo',
      badgeTexto: 'ACTIVO',
      badgeColor: 'bg-emerald-950 text-emerald-300 border-emerald-500/30',
      titulo: 'Piloto Automático: En Ejecución',
      descripcion: workerState.accion_actual || rawStatus || 'Motor activo y en funcionamiento.',
      tipoVisual: 'activo'
    };
  }, [isAutopilotActive, rawStatus, workerState]);

  // Contexto del prospecto actual o última acción
  const prospectoActivo = workerState.prospecto_actual;
  const institucionActiva = workerState.institucion_actual;
  const ultimaAccion = workerState.ultima_accion;

  return (
    <div className={`rounded-xl border transition-all duration-300 overflow-hidden shadow-sm ${
      !isAutopilotActive
        ? 'bg-[#101216]/90 border-white/[0.08] text-zinc-300'
        : telemetry.tipoVisual === 'ejecutando'
        ? 'bg-gradient-to-r from-sky-950/30 via-[#0d1520]/80 to-[#10131a] border-sky-500/30 text-sky-100'
        : telemetry.tipoVisual === 'pausa'
        ? 'bg-gradient-to-r from-amber-950/20 via-[#14120e]/80 to-[#101216] border-amber-500/30 text-amber-100'
        : 'bg-emerald-950/25 border-emerald-500/30 text-emerald-100'
    }`}>
      {/* Barra superior de contenido */}
      <div className="p-3.5 sm:p-4 flex flex-col md:flex-row md:items-center justify-between gap-3.5">
        
        {/* Lado Izquierdo: Icono temático + Diagnóstico en tiempo real */}
        <div className="flex items-start sm:items-center gap-3 min-w-0">
          {/* Icono de Estado */}
          <div className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 border transition-colors ${
            !isAutopilotActive
              ? 'bg-zinc-800 border-zinc-700 text-zinc-400'
              : telemetry.tipoVisual === 'ejecutando'
              ? 'bg-sky-500/20 border-sky-400/40 text-sky-400'
              : telemetry.tipoVisual === 'pausa'
              ? 'bg-amber-500/20 border-amber-400/40 text-amber-300'
              : 'bg-emerald-500/20 border-emerald-500/40 text-emerald-400'
          }`}>
            {!isAutopilotActive ? (
              <Pause className="w-4 h-4 text-zinc-400" />
            ) : telemetry.tipoVisual === 'ejecutando' ? (
              <Zap className="w-4 h-4 animate-pulse text-sky-400" />
            ) : telemetry.tipoVisual === 'pausa' ? (
              <Clock className="w-4 h-4 text-amber-300 animate-[spin_10s_linear_infinite]" />
            ) : telemetry.tipoVisual === 'consultando' ? (
              <RefreshCw className="w-4 h-4 text-indigo-400 animate-spin" />
            ) : (
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
            )}
          </div>

          {/* Bloque de Textos y Acción Detallada */}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-zinc-100 text-sm tracking-tight">
                {telemetry.titulo}
              </span>

              {/* Badge de Fase */}
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-mono border font-medium uppercase tracking-wider flex items-center gap-1 ${telemetry.badgeColor}`}>
                {isAutopilotActive && <span className="w-1.5 h-1.5 rounded-full bg-current animate-ping" />}
                {telemetry.badgeTexto}
              </span>

              {/* Canal activo si aplica */}
              {workerState.canal && isAutopilotActive && (
                <span className="px-2 py-0.5 rounded-full text-[10px] font-mono border bg-zinc-800/80 text-zinc-300 border-zinc-700">
                  {workerState.canal}
                </span>
              )}
            </div>

            {/* Descripción en tiempo real de la acción */}
            <p className="text-xs text-zinc-300 mt-1 line-clamp-2 leading-relaxed">
              {telemetry.descripcion}
            </p>

            {/* Pill informativo de Prospecto o Última Acción */}
            <div className="flex flex-wrap items-center gap-2 mt-2 text-[11px]">
              {/* Si está ejecutando y hay prospecto actual */}
              {prospectoActivo && telemetry.tipoVisual === 'ejecutando' && (
                <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md bg-sky-950/60 border border-sky-500/30 text-sky-200 font-medium">
                  <User className="w-3 h-3 text-sky-400 shrink-0" />
                  <span className="truncate max-w-[200px]">{prospectoActivo}</span>
                  {institucionActiva && (
                    <>
                      <span className="text-sky-500">•</span>
                      <Building2 className="w-3 h-3 text-sky-400 shrink-0" />
                      <span className="truncate max-w-[180px] text-sky-300/80">{institucionActiva}</span>
                    </>
                  )}
                </div>
              )}

              {/* Si está en pausa y hay última acción registrada */}
              {ultimaAccion && telemetry.tipoVisual === 'pausa' && (
                <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md bg-zinc-900/80 border border-zinc-700/60 text-zinc-300">
                  <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />
                  <span>Última acción:</span>
                  <span className="text-zinc-100 font-medium">{ultimaAccion.nombre_accion || ultimaAccion.tipo}</span>
                  <span className="text-zinc-500">→</span>
                  <span className="text-emerald-300 truncate max-w-[160px]">{ultimaAccion.prospecto}</span>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Lado Derecho: Contador Regresivo + Botones de Control */}
        <div className="flex flex-wrap items-center gap-3 shrink-0 self-end sm:self-center">
          
          {/* WIDGET DEL CONTADOR REGRESIVO (Si hay tiempo pendiente) */}
          {isAutopilotActive && remainingSeconds !== null && remainingSeconds > 0 && (
            <div className="flex items-center gap-2.5 px-3 py-1.5 rounded-lg bg-black/40 border border-white/10 shadow-inner">
              <div className="flex flex-col text-right">
                <span className="text-[9px] uppercase tracking-wider text-zinc-400 font-semibold font-mono">
                  Próximo Lead
                </span>
                <span className="font-mono text-base font-bold text-amber-300 tracking-tight flex items-center gap-1">
                  <Clock className="w-3.5 h-3.5 text-amber-400 animate-pulse" />
                  {formattedCountdown}
                  <span className="text-[10px] text-zinc-400 font-normal">({remainingSeconds}s)</span>
                </span>
              </div>
            </div>
          )}

          {/* Botón 1: Adelantar Pausa Humana (Si el usuario no quiere esperar los minutos restantes) */}
          {isAutopilotActive && onForceNext && (telemetry.tipoVisual === 'pausa' || (remainingSeconds !== null && remainingSeconds > 0)) && (
            <button
              onClick={handleForceClick}
              disabled={isForcingNext}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-amber-500/15 hover:bg-amber-500/25 text-amber-200 hover:text-amber-100 border border-amber-500/30 transition cursor-pointer disabled:opacity-50 shadow-sm"
              title="Saltar la pausa estocástica y procesar el siguiente prospecto de inmediato"
            >
              {isForcingNext ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin text-amber-400" />
              ) : (
                <FastForward className="w-3.5 h-3.5 text-amber-400" />
              )}
              <span>{isForcingNext ? 'Adelantando...' : 'Adelantar espera'}</span>
            </button>
          )}

          {/* Botón Principal: Pausar / Activar Piloto Automático */}
          <button
            onClick={onToggleAutopilot}
            disabled={togglingAutopilot}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold shadow-sm transition cursor-pointer disabled:opacity-50 ${
              isAutopilotActive
                ? 'bg-amber-950/80 hover:bg-amber-900 text-amber-200 border border-amber-500/30'
                : 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-950/50'
            }`}
          >
            {togglingAutopilot ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Actualizando...</span>
              </>
            ) : isAutopilotActive ? (
              <>
                <Pause className="w-3.5 h-3.5 fill-current" />
                <span>Pausar Piloto Automático</span>
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>▶ Activar Piloto Automático</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Barra de Progreso Dinámica de la Pausa (Subtle footer bar) */}
      {isAutopilotActive && remainingSeconds !== null && remainingSeconds > 0 && (
        <div className="w-full bg-black/40 h-1 overflow-hidden relative">
          <div 
            className="h-full bg-gradient-to-r from-amber-500 via-emerald-400 to-sky-400 transition-all duration-1000 ease-linear"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      )}
    </div>
  );
}
