// Componente de Configuración Personalizada de Cuota Diaria de Invitaciones LinkedIn
import React, { useState, useEffect } from 'react';
import { 
  UserPlus, 
  ShieldCheck, 
  ShieldAlert, 
  AlertTriangle, 
  Check, 
  Sparkles, 
  Zap, 
  TrendingUp, 
  Info,
  CheckCircle2,
  Sliders
} from 'lucide-react';
import { updateSafetyConfig } from '../../services/api';

const PRESETS = [
  { valor: 15, label: '15 / día', badge: 'Recomendado', sub: 'Calentamiento Inicial (Antiban Máximo)' },
  { valor: 20, label: '20 / día', badge: 'Seguro', sub: 'Cuentas con actividad regular' },
  { valor: 25, label: '25 / día', badge: 'Crucero', sub: 'Régimen óptimo (LinkedIn Free)' },
  { valor: 35, label: '35 / día', badge: 'Avanzado', sub: 'LinkedIn Premium / Antiguas' },
  { valor: 50, label: '50 / día', badge: 'Intensivo', sub: 'Sales Navigator profesional' },
];

export default function InviteQuotaConfigurator({ safetyData, warmupData, onUpdated }) {
  const currentLimitFromData = safetyData?.limite_invitaciones_hoy || warmupData?.limite_diario_actual || 15;
  const sentToday = safetyData?.invitaciones_hoy || 0;

  const [limite, setLimite] = useState(currentLimitFromData);
  const [warmupActivo, setWarmupActivo] = useState(true);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState(null);

  useEffect(() => {
    if (safetyData?.limite_invitaciones_hoy) {
      setLimite(safetyData.limite_invitaciones_hoy);
    } else if (warmupData?.limite_diario_actual) {
      setLimite(warmupData.limite_diario_actual);
    }
  }, [safetyData, warmupData]);

  const pctUsed = Math.min(100, Math.round((sentToday / Math.max(1, limite)) * 100));

  async function handleSave(newLimitValue = null) {
    const targetLimit = newLimitValue !== null ? newLimitValue : limite;
    setSaving(true);
    setFeedback(null);

    try {
      const payload = {
        limite_linkedin_diario: String(targetLimit),
        linkedin_warmup_limite_actual: String(targetLimit),
        linkedin_warmup_activo: warmupActivo ? '1' : '0'
      };

      await updateSafetyConfig(payload);

      setFeedback({
        tipo: 'success',
        mensaje: `Cuota diaria de invitaciones actualizada exitosamente a ${targetLimit}/día.`
      });

      if (onUpdated) onUpdated();
    } catch (err) {
      setFeedback({
        tipo: 'error',
        mensaje: `Error al guardar cuota: ${err.message}`
      });
    } finally {
      setSaving(false);
    }
  }

  function handlePresetClick(val) {
    setLimite(val);
    handleSave(val);
  }

  // Nivel de riesgo según el valor seleccionado
  let riesgo = {
    color: 'text-emerald-400',
    bg: 'bg-emerald-500/10 border-emerald-500/30',
    texto: 'Riesgo Mínimo (Cumple 100% de políticas antibaneo de LinkedIn)'
  };
  if (limite > 40) {
    riesgo = {
      color: 'text-rose-400',
      bg: 'bg-rose-500/10 border-rose-500/30',
      texto: 'Ritmo Intensivo: Recomendado solo con Sales Navigator y cuenta antigua (+1 año)'
    };
  } else if (limite > 25) {
    riesgo = {
      color: 'text-amber-400',
      bg: 'bg-amber-500/10 border-amber-500/30',
      texto: 'Ritmo Moderado-Alto: Recomendado para cuentas con ratio de aceptación > 30%'
    };
  }

  return (
    <div className="p-6 rounded-2xl bg-[#121316] border border-white/[0.08] space-y-6 shadow-xl">
      {/* Encabezado y Progreso en Vivo */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-white/[0.06] pb-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-cyan-950/60 text-cyan-400 border border-cyan-500/30 shrink-0">
            <UserPlus className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-zinc-100 flex items-center gap-2">
              <span>Cuota Diaria de Invitaciones LinkedIn</span>
              <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-cyan-500/10 text-cyan-400 border border-cyan-500/30">
                {limite} / día
              </span>
            </h3>
            <p className="text-xs text-zinc-400 mt-0.5">
              Controla cuántas invitaciones salientes puede despachar el motor de secuencias cada 24 horas.
            </p>
          </div>
        </div>

        {/* Medidor de Consumo del Día */}
        <div className="flex items-center gap-4 bg-zinc-900/80 px-4 py-2.5 rounded-xl border border-white/[0.06]">
          <div className="text-right">
            <div className="text-[11px] text-zinc-400 font-medium">Consumo Hoy</div>
            <div className="text-sm font-semibold font-mono text-zinc-100">
              {sentToday} <span className="text-zinc-500">/ {limite}</span>
            </div>
          </div>
          <div className="w-20 bg-zinc-800 h-2.5 rounded-full overflow-hidden border border-white/[0.04]">
            <div 
              className={`h-full transition-all duration-500 ${
                pctUsed >= 100 ? 'bg-amber-500' : 'bg-cyan-500'
              }`}
              style={{ width: `${pctUsed}%` }}
            />
          </div>
        </div>
      </div>

      {/* Botones de Presets Rápidos */}
      <div className="space-y-2">
        <label className="text-xs font-semibold text-zinc-300 uppercase tracking-wider flex items-center gap-1.5">
          <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
          <span>Configuraciones Rápidas Recomendadas</span>
        </label>
        <div className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-5 gap-2.5">
          {PRESETS.map((p) => {
            const isSelected = limite === p.valor;
            return (
              <button
                key={p.valor}
                type="button"
                onClick={() => handlePresetClick(p.valor)}
                className={`p-3 rounded-xl border text-left transition-all cursor-pointer flex flex-col justify-between ${
                  isSelected
                    ? 'bg-cyan-950/40 border-cyan-500/50 shadow-lg shadow-cyan-950/50 ring-1 ring-cyan-500/40'
                    : 'bg-zinc-900/60 border-white/[0.06] hover:bg-zinc-800/80 hover:border-white/[0.12]'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className={`text-base font-bold font-mono ${isSelected ? 'text-cyan-400' : 'text-zinc-200'}`}>
                    {p.label}
                  </span>
                  <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${
                    isSelected ? 'bg-cyan-500/20 text-cyan-300' : 'bg-zinc-800 text-zinc-400'
                  }`}>
                    {p.badge}
                  </span>
                </div>
                <p className="text-[10px] text-zinc-400 mt-1 leading-tight">
                  {p.sub}
                </p>
              </button>
            );
          })}
        </div>
      </div>

      {/* Control Deslizante (Slider) e Input Numérico */}
      <div className="p-4 rounded-xl bg-zinc-900/50 border border-white/[0.06] space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-zinc-300 flex items-center gap-2">
            <Sliders className="w-3.5 h-3.5 text-zinc-400" />
            <span>Ajuste Personalizado de Invitaciones Diarias:</span>
          </span>
          <div className="flex items-center gap-2">
            <input
              type="number"
              min="5"
              max="80"
              value={limite}
              onChange={(e) => setLimite(Math.max(1, parseInt(e.target.value, 10) || 1))}
              className="w-20 px-2.5 py-1 text-center font-mono font-bold text-sm bg-zinc-950 border border-white/[0.1] rounded-lg text-cyan-300 focus:outline-none focus:border-cyan-500"
            />
            <span className="text-xs text-zinc-400 font-medium">al día</span>
          </div>
        </div>

        <input
          type="range"
          min="5"
          max="60"
          step="1"
          value={limite}
          onChange={(e) => setLimite(parseInt(e.target.value, 10))}
          className="w-full accent-cyan-500 cursor-pointer h-2 bg-zinc-800 rounded-lg"
        />

        <div className="flex justify-between text-[10px] text-zinc-500 font-mono">
          <span>5 / día (Mínimo seguro)</span>
          <span>15 (Recomendado Warm-up)</span>
          <span>25 (Crucero Free)</span>
          <span>50 (Intensivo Sales Nav)</span>
          <span>60 / día</span>
        </div>
      </div>

      {/* Alerta de Nivel de Seguridad Antiban */}
      <div className={`p-3 rounded-xl border text-xs flex items-center gap-2.5 ${riesgo.bg}`}>
        <Info className={`w-4 h-4 shrink-0 ${riesgo.color}`} />
        <span className={riesgo.color}>{riesgo.texto}</span>
      </div>

      {/* Feedback de Guardado */}
      {feedback && (
        <div className={`p-3 rounded-xl text-xs flex items-center gap-2 ${
          feedback.tipo === 'success'
            ? 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-400'
            : 'bg-rose-500/10 border border-rose-500/30 text-rose-400'
        }`}>
          {feedback.tipo === 'success' ? (
            <CheckCircle2 className="w-4 h-4 shrink-0" />
          ) : (
            <AlertTriangle className="w-4 h-4 shrink-0" />
          )}
          <span>{feedback.mensaje}</span>
        </div>
      )}

      {/* Acciones */}
      <div className="flex items-center justify-end gap-3 pt-2">
        <button
          type="button"
          disabled={saving}
          onClick={() => handleSave()}
          className="px-5 py-2.5 rounded-xl text-xs font-semibold bg-cyan-500 hover:bg-cyan-400 text-zinc-950 shadow-lg shadow-cyan-500/20 transition cursor-pointer flex items-center gap-2 disabled:opacity-50"
        >
          {saving ? (
            <div className="w-3.5 h-3.5 border-2 border-zinc-950 border-t-transparent rounded-full animate-spin" />
          ) : (
            <Check className="w-4 h-4" />
          )}
          <span>Guardar Cuota Diaria</span>
        </button>
      </div>
    </div>
  );
}
