// Banner persistente de seguridad y límites de tasa (Anti-ban LinkedIn & Google Workspace)
import React, { useState, useEffect } from 'react';
import { ShieldCheck, ShieldAlert } from 'lucide-react';
import { fetchSafetyStatus } from '../services/api';

export default function SafetyBanner({ quotaToday, quotaMax }) {
  const [safety, setSafety] = useState(null);

  useEffect(() => {
    loadSafety();
    const interval = setInterval(loadSafety, 15000);
    return () => clearInterval(interval);
  }, []);

  async function loadSafety() {
    try {
      const data = await fetchSafetyStatus();
      setSafety(data);
    } catch {
      // Ignorar fallos silenciosos para no interrumpir la vista
    }
  }

  const enHorario = safety?.horario_laboral?.en_horario ?? true;
  const detalleHorario = safety?.horario_laboral?.detalle || 'Horario Laboral';
  const killSwitch = Boolean(safety?.kill_switch?.activado);
  const killSwitchMotivo = safety?.kill_switch?.motivo || 'Freno manual activo';

  const limiteDiario = safety?.linkedin?.limite_diario ?? quotaMax ?? 5;
  const enviadasHoy = safety?.linkedin?.invitaciones_hoy ?? quotaToday ?? 0;
  const cupoRestante = Math.max(0, limiteDiario - enviadasHoy);
  const limiteWorkspace = safety?.google_workspace?.limite_diario ?? 15;

  if (killSwitch) {
    return (
      <section className="mb-5 rounded-lg border border-rose-500/30 bg-rose-950/20 px-3.5 py-2.5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
          <div className="flex items-center gap-2.5">
            <div className="w-6 h-6 rounded bg-rose-500/10 border border-rose-500/20 flex items-center justify-center shrink-0">
              <ShieldAlert className="w-3.5 h-3.5 text-rose-400" />
            </div>
            <div className="text-xs text-rose-300">
              <span className="font-medium text-rose-200">Freno de emergencia:</span>{' '}
              {killSwitchMotivo}. Operaciones automatizadas en pausa preventiva.
            </div>
          </div>
          <span className="px-2 py-0.5 rounded bg-rose-500/10 border border-rose-500/30 text-[10px] font-mono text-rose-300 font-medium self-start sm:self-auto shrink-0">
            KILL-SWITCH ACTIVO
          </span>
        </div>
      </section>
    );
  }

  return (
    <section className="mb-5 rounded-lg border border-white/[0.06] bg-[#121316] px-3.5 py-2.5 select-none font-sans">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="w-6 h-6 rounded bg-white/[0.04] border border-white/[0.08] flex items-center justify-center shrink-0 text-zinc-400">
            <ShieldCheck className="w-3.5 h-3.5 text-zinc-300" />
          </div>
          <div className="text-xs text-zinc-400 leading-normal">
            <span className="font-medium text-zinc-200">Cadencia segura:</span>{' '}
            Límite de <span className="text-zinc-200 font-medium">{limiteDiario} invitaciones/día</span> y{' '}
            <span className="text-zinc-200 font-medium">{limiteWorkspace} emails</span> con pausas gaussianas y horario comercial hábil.
          </div>
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto shrink-0">
          <div 
            title={detalleHorario}
            className={`flex items-center gap-1.5 px-2 py-0.5 rounded border text-[10px] font-mono transition ${
              enHorario
                ? 'bg-emerald-950/20 border-emerald-500/30 text-emerald-400'
                : 'bg-amber-950/20 border-amber-500/30 text-amber-300'
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${enHorario ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'}`} />
            <span>{enHorario ? 'Horario Laboral' : 'Fuera de Horario'}</span>
          </div>

          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-white/[0.03] border border-white/[0.06] text-[10px] font-mono text-zinc-400">
            <span>Cupo LinkedIn:</span>
            <span className="font-medium text-zinc-200">{cupoRestante} / {limiteDiario}</span>
          </div>
        </div>
      </div>
    </section>
  );
}
