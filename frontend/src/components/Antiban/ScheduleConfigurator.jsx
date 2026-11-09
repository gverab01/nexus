// Componente de Configuración Personalizada de Días y Horarios de Operación
import React, { useState, useEffect } from 'react';
import { 
  Clock, 
  Calendar, 
  Check, 
  AlertCircle, 
  CheckCircle2, 
  Zap, 
  Moon, 
  Sun, 
  CalendarDays,
  ShieldCheck,
  RefreshCw,
  Power
} from 'lucide-react';
import { updateSafetyConfig } from '../../services/api';

const DIAS = [
  { id: 0, label: 'Lunes', short: 'Lun' },
  { id: 1, label: 'Martes', short: 'Mar' },
  { id: 2, label: 'Miércoles', short: 'Mié' },
  { id: 3, label: 'Jueves', short: 'Jue' },
  { id: 4, label: 'Viernes', short: 'Vie' },
  { id: 5, label: 'Sábado', short: 'Sáb' },
  { id: 6, label: 'Domingo', short: 'Dom' },
];

export default function ScheduleConfigurator({ scheduleData, onUpdated }) {
  const [activo, setActivo] = useState(true);
  const [horaInicio, setHoraInicio] = useState('09:00');
  const [horaFin, setHoraFin] = useState('18:00');
  const [diasSeleccionados, setDiasSeleccionados] = useState(new Set([0, 1, 2, 3, 4]));
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState(null);

  useEffect(() => {
    if (scheduleData) {
      setActivo(scheduleData.restriccion_activa !== false);
      setHoraInicio(scheduleData.horario_inicio || '09:00');
      setHoraFin(scheduleData.horario_fin || '18:00');

      if (scheduleData.dias_laborales) {
        const dias = String(scheduleData.dias_laborales)
          .split(',')
          .map((d) => parseInt(d.trim(), 10))
          .filter((d) => !isNaN(d));
        if (dias.length > 0) {
          setDiasSeleccionados(new Set(dias));
        }
      }
    }
  }, [scheduleData]);

  function toggleDia(diaId) {
    setDiasSeleccionados((prev) => {
      const next = new Set(prev);
      if (next.has(diaId)) {
        if (next.size > 1) next.delete(diaId); // Evitar dejar 0 días
      } else {
        next.add(diaId);
      }
      return next;
    });
  }

  function setPresetDays(type) {
    if (type === 'workdays') setDiasSeleccionados(new Set([0, 1, 2, 3, 4]));
    else if (type === 'mon_sat') setDiasSeleccionados(new Set([0, 1, 2, 3, 4, 5]));
    else if (type === 'all_week') setDiasSeleccionados(new Set([0, 1, 2, 3, 4, 5, 6]));
  }

  function setPresetHours(start, end) {
    setHoraInicio(start);
    setHoraFin(end);
  }

  async function handleSave(overridePayload = null) {
    setSaving(true);
    setFeedback(null);
    try {
      const diasArr = Array.from(diasSeleccionados).sort((a, b) => a - b);
      const payload = overridePayload || {
        horario_laboral_activo: activo ? '1' : '0',
        horario_inicio: horaInicio,
        horario_fin: horaFin,
        dias_laborales: diasArr.join(','),
      };

      await updateSafetyConfig(payload);
      setFeedback({
        tipo: 'success',
        mensaje: 'Horarios de operación actualizados correctamente.',
      });

      if (onUpdated) onUpdated();
    } catch (err) {
      setFeedback({
        tipo: 'error',
        mensaje: `Error al guardar configuración: ${err.message}`,
      });
    } finally {
      setSaving(false);
    }
  }

  async function handleUnlockNow247() {
    setActivo(false);
    await handleSave({
      horario_laboral_activo: '0',
      horario_inicio: horaInicio,
      horario_fin: horaFin,
      dias_laborales: Array.from(diasSeleccionados).sort().join(','),
    });
  }

  async function handleExtendUntilMidnight() {
    setHoraFin('23:59');
    setActivo(true);
    const today = new Date().getDay();
    const normalizedToday = today === 0 ? 6 : today - 1; // 0=Lun, 6=Dom
    const updatedDays = new Set(diasSeleccionados);
    updatedDays.add(normalizedToday);
    setDiasSeleccionados(updatedDays);

    await handleSave({
      horario_laboral_activo: '1',
      horario_inicio: horaInicio,
      horario_fin: '23:59',
      dias_laborales: Array.from(updatedDays).sort().join(','),
    });
  }

  const enHorario = Boolean(scheduleData?.en_horario);
  const detalle = scheduleData?.detalle || '';

  return (
    <div className="p-6 rounded-2xl bg-[#121316] border border-white/[0.08] space-y-6 shadow-xl">
      {/* Encabezado y Estado en Vivo */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-white/[0.06] pb-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-purple-950/60 text-purple-400 border border-purple-500/30 shrink-0">
            <CalendarDays className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-zinc-100 flex items-center gap-2">
              <span>Jornada y Horarios de Operación</span>
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-mono border ${
                enHorario
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                  : 'bg-amber-500/10 text-amber-400 border-amber-500/30'
              }`}>
                {enHorario ? '● EN HORARIO ACTIVO' : '○ EN REPOSO'}
              </span>
            </h3>
            <p className="text-xs text-zinc-400 mt-0.5">
              Controla con precisión qué días y en qué rango de horas se ejecutan las secuencias y tareas automatizadas.
            </p>
          </div>
        </div>

        {/* Botones de Desbloqueo Rápido Inmediato */}
        {!enHorario && (
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={handleExtendUntilMidnight}
              disabled={saving}
              title="Permite operar hoy hasta las 23:59 hrs"
              className="px-3 py-1.5 rounded-xl bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 text-xs font-medium transition cursor-pointer flex items-center gap-1.5"
            >
              <Zap className="w-3.5 h-3.5" />
              <span>Ampliar hasta 23:59 hrs</span>
            </button>
            <button
              onClick={handleUnlockNow247}
              disabled={saving}
              title="Desactiva restricciones de horario para operar 24/7"
              className="px-3 py-1.5 rounded-xl bg-purple-500/10 hover:bg-purple-500/20 text-purple-300 border border-purple-500/30 text-xs font-medium transition cursor-pointer flex items-center gap-1.5"
            >
              <Power className="w-3.5 h-3.5" />
              <span>Modo 24/7 (Sin límite)</span>
            </button>
          </div>
        )}
      </div>

      {/* Banner de Diagnóstico del Horario Actual */}
      <div className={`p-3.5 rounded-xl border flex items-center justify-between gap-3 text-xs font-mono ${
        enHorario
          ? 'bg-emerald-950/20 border-emerald-500/30 text-emerald-300'
          : 'bg-amber-950/20 border-amber-500/30 text-amber-300'
      }`}>
        <div className="flex items-center gap-2.5">
          <Clock className="w-4 h-4 shrink-0" />
          <span>{detalle || (enHorario ? 'En horario laboral comercial' : 'Fuera de horario laboral')}</span>
        </div>
        <div className="text-[11px] text-zinc-400">
          Modo: <span className="font-semibold text-zinc-200">{activo ? 'Horario Programado' : 'Continuo 24/7'}</span>
        </div>
      </div>

      {/* Switch de Activación de Restricción */}
      <div className="p-4 rounded-xl bg-[#0D0E12] border border-white/[0.04] flex items-center justify-between">
        <div>
          <div className="text-sm font-medium text-zinc-200">
            Respetar Restricción de Horario Comercial
          </div>
          <div className="text-xs text-zinc-500 mt-0.5">
            {activo
              ? 'Las secuencias solo procesarán pasos dentro de los días y horas indicados abajo.'
              : 'Desactivado: El sistema operará 24/7 de manera continua a cualquier hora del día o noche.'}
          </div>
        </div>

        <button
          onClick={() => setActivo(!activo)}
          className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-hidden ${
            activo ? 'bg-sky-500' : 'bg-zinc-700'
          }`}
        >
          <span
            className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-lg ring-0 transition duration-200 ease-in-out ${
              activo ? 'translate-x-5' : 'translate-x-0'
            }`}
          />
        </button>
      </div>

      {/* Selector de Días Habilitados */}
      <div className={`space-y-3 transition-opacity ${activo ? 'opacity-100' : 'opacity-40 pointer-events-none'}`}>
        <div className="flex items-center justify-between">
          <label className="text-xs font-medium text-zinc-300 flex items-center gap-1.5">
            <Calendar className="w-3.5 h-3.5 text-sky-400" />
            <span>Días Activos de la Semana</span>
          </label>
          <div className="flex items-center gap-2 text-[11px]">
            <button
              onClick={() => setPresetDays('workdays')}
              className="text-zinc-400 hover:text-sky-400 transition cursor-pointer"
            >
              Lun-Vie
            </button>
            <span className="text-zinc-600">|</span>
            <button
              onClick={() => setPresetDays('mon_sat')}
              className="text-zinc-400 hover:text-sky-400 transition cursor-pointer"
            >
              Lun-Sáb
            </button>
            <span className="text-zinc-600">|</span>
            <button
              onClick={() => setPresetDays('all_week')}
              className="text-zinc-400 hover:text-sky-400 transition cursor-pointer"
            >
              Toda la Semana
            </button>
          </div>
        </div>

        <div className="grid grid-cols-7 gap-2">
          {DIAS.map((d) => {
            const isSelected = diasSeleccionados.has(d.id);
            return (
              <button
                key={d.id}
                type="button"
                onClick={() => toggleDia(d.id)}
                className={`p-3 rounded-xl border text-center transition cursor-pointer flex flex-col items-center justify-center gap-1 ${
                  isSelected
                    ? 'bg-sky-500/15 border-sky-500/40 text-sky-300 shadow-md shadow-sky-950/40'
                    : 'bg-[#0D0E12] border-white/[0.04] text-zinc-500 hover:text-zinc-300 hover:bg-zinc-900'
                }`}
              >
                <span className="text-xs font-bold">{d.short}</span>
                <span className="text-[10px] text-zinc-500">{d.label.slice(0, 3)}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Rango de Horario (Inicio y Fin) */}
      <div className={`space-y-3 transition-opacity ${activo ? 'opacity-100' : 'opacity-40 pointer-events-none'}`}>
        <div className="flex items-center justify-between">
          <label className="text-xs font-medium text-zinc-300 flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-sky-400" />
            <span>Ventana Horaria de Operación Diaria</span>
          </label>
          <div className="flex items-center gap-2 text-[11px]">
            <button
              onClick={() => setPresetHours('09:00', '18:00')}
              className="text-zinc-400 hover:text-sky-400 transition cursor-pointer"
            >
              Oficina (09:00-18:00)
            </button>
            <span className="text-zinc-600">|</span>
            <button
              onClick={() => setPresetHours('08:00', '21:00')}
              className="text-zinc-400 hover:text-sky-400 transition cursor-pointer"
            >
              Extendido (08:00-21:00)
            </button>
            <span className="text-zinc-600">|</span>
            <button
              onClick={() => setPresetHours('08:00', '23:59')}
              className="text-zinc-400 hover:text-sky-400 transition cursor-pointer"
            >
              Hasta Medianoche (23:59)
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="p-3.5 rounded-xl bg-[#0D0E12] border border-white/[0.04] space-y-1.5">
            <div className="text-[11px] text-zinc-400 flex items-center gap-1.5">
              <Sun className="w-3.5 h-3.5 text-amber-400" />
              <span>Hora de Inicio de Actividad:</span>
            </div>
            <input
              type="time"
              value={horaInicio}
              onChange={(e) => setHoraInicio(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-100 font-mono focus:outline-hidden focus:border-sky-500"
            />
          </div>

          <div className="p-3.5 rounded-xl bg-[#0D0E12] border border-white/[0.04] space-y-1.5">
            <div className="text-[11px] text-zinc-400 flex items-center gap-1.5">
              <Moon className="w-3.5 h-3.5 text-indigo-400" />
              <span>Hora de Fin de Actividad:</span>
            </div>
            <input
              type="time"
              value={horaFin}
              onChange={(e) => setHoraFin(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-100 font-mono focus:outline-hidden focus:border-sky-500"
            />
          </div>
        </div>
      </div>

      {/* Feedback de Guardado */}
      {feedback && (
        <div className={`p-3 rounded-xl border text-xs flex items-center gap-2 ${
          feedback.tipo === 'success'
            ? 'bg-emerald-950/30 border-emerald-500/30 text-emerald-300'
            : 'bg-rose-950/30 border-rose-500/30 text-rose-300'
        }`}>
          {feedback.tipo === 'success' ? <CheckCircle2 className="w-4 h-4 shrink-0" /> : <AlertCircle className="w-4 h-4 shrink-0" />}
          <span>{feedback.mensaje}</span>
        </div>
      )}

      {/* Botón Guardar Cambios */}
      <div className="flex items-center justify-end gap-3 pt-2">
        <button
          onClick={() => handleSave()}
          disabled={saving}
          className="px-5 py-2.5 rounded-xl bg-sky-500 hover:bg-sky-400 text-zinc-950 font-semibold text-xs shadow-lg shadow-sky-500/20 transition cursor-pointer flex items-center gap-2 disabled:opacity-50"
        >
          {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
          <span>Guardar Configuración de Horario</span>
        </button>
      </div>
    </div>
  );
}

