// Banner de seguridad contextual (solo para amenazas reales y checkpoints)
import React, { useState, useEffect } from 'react';
import { ShieldAlert, Play, X } from 'lucide-react';
import { fetchSafetyStatus, toggleCampaign } from '../services/api';

export default function SafetyBanner({ activeTab = '' }) {
  const [safety, setSafety] = useState(null);
  const [isDismissed, setIsDismissed] = useState(false);
  const [resuming, setResuming] = useState(false);

  useEffect(() => {
    loadSafety();
    const interval = setInterval(() => {
      if (!document.hidden) loadSafety();
    }, 20000);
    const onVis = () => { if (!document.hidden) loadSafety(); };
    document.addEventListener('visibilitychange', onVis);
    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, []);

  async function loadSafety() {
    try {
      const data = await fetchSafetyStatus();
      setSafety(data);
    } catch {
      // Ignorar fallos silenciosos para no interrumpir la vista
    }
  }

  async function handleResume() {
    try {
      setResuming(true);
      await toggleCampaign(true);
      setIsDismissed(true);
      await loadSafety();
    } catch (err) {
      alert(`Error al reanudar despacho: ${err.message}`);
    } finally {
      setResuming(false);
    }
  }

  if (isDismissed || !safety) return null;

  const killSwitch = Boolean(safety?.kill_switch?.activado);
  const killSwitchMotivo = (safety?.kill_switch?.motivo || '').trim();

  // Solo consideramos "Amenaza Crítica" si hay un motivo real de seguridad
  // (por ejemplo: detección de captcha, checkpoint, límite de cuenta o bloqueo en LinkedIn).
  // Si fue simplemente pausado desde la interfaz ("Pausado_desde_la_interfaz" o manual),
  // o no hay secuencias activas, es un estado de espera normal (standby) y NO una emergencia.
  const isManualPause = !killSwitchMotivo || 
    killSwitchMotivo.toLowerCase().includes('pausado_desde_la_interfaz') ||
    killSwitchMotivo.toLowerCase().includes('manual') ||
    killSwitchMotivo.toLowerCase().includes('standby');

  const isRealThreat = killSwitch && !isManualPause;

  // Si no hay una amenaza real, no mostramos ningún banner persistente invasivo en las vistas de trabajo.
  // La cadencia y límites ya se visualizan de manera contextual y ordenada en el módulo de Secuencias.
  if (!isRealThreat) {
    return null;
  }

  return (
    <section className="mb-4 rounded-xl border border-rose-500/30 bg-rose-950/30 px-4 py-3 select-none font-sans animate-fadeIn">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-lg bg-rose-500/20 border border-rose-500/30 flex items-center justify-center shrink-0">
            <ShieldAlert className="w-4 h-4 text-rose-400" />
          </div>
          <div className="text-xs text-rose-200 leading-relaxed">
            <span className="font-semibold text-rose-100">Protección Antiban Activada:</span>{' '}
            {killSwitchMotivo}. El envío automático se pausó preventivamente para proteger tus cuentas.
          </div>
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto shrink-0">
          <button
            onClick={handleResume}
            disabled={resuming}
            className="flex items-center gap-1.5 px-3 py-1 rounded-md bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 border border-rose-500/40 text-xs font-medium transition cursor-pointer"
          >
            <Play className="w-3 h-3 fill-current" />
            <span>{resuming ? 'Reanudando...' : 'Reanudar Despacho'}</span>
          </button>
          <button
            onClick={() => setIsDismissed(true)}
            className="p-1 rounded text-rose-400 hover:text-rose-200 hover:bg-rose-900/40 transition cursor-pointer"
            title="Descartar este aviso"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    </section>
  );
}
