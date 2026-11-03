import React, { useState, useEffect } from 'react';
import { X, ShieldCheck, Clock, Zap, Save } from 'lucide-react';
import { fetchSafetyStatus, updateSafetyConfig } from '../services/api';

export default function AntibanSettingsModal({ isOpen, onClose, onSaved }) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [formData, setFormData] = useState({
    limite_linkedin_diario: '5',
    limite_email_workspace_diario: '15',
    horario_inicio: '09:00',
    horario_fin: '18:00',
    pausa_linkedin_min_seg: '180',
    pausa_linkedin_max_seg: '360',
    horario_laboral_activo: '1',
    pausas_antiban_activas: '1',
    limites_diarios_activos: '1',
  });

  useEffect(() => {
    if (isOpen) {
      loadConfig();
    }
  }, [isOpen]);

  async function loadConfig() {
    try {
      setLoading(true);
      const res = await fetchSafetyStatus();
      if (res?.configuracion) {
        setFormData({
          limite_linkedin_diario: res.configuracion.limite_linkedin_diario || '5',
          limite_email_workspace_diario: res.configuracion.limite_email_workspace_diario || '15',
          horario_inicio: res.configuracion.horario_inicio || '09:00',
          horario_fin: res.configuracion.horario_fin || '18:00',
          pausa_linkedin_min_seg: res.configuracion.pausa_linkedin_min_seg || '180',
          pausa_linkedin_max_seg: res.configuracion.pausa_linkedin_max_seg || '360',
          horario_laboral_activo: res.configuracion.horario_laboral_activo || '1',
          pausas_antiban_activas: res.configuracion.pausas_antiban_activas || '1',
          limites_diarios_activos: res.configuracion.limites_diarios_activos || '1',
        });
      }
    } catch (err) {
      console.error('Error cargando configuración antiban:', err);
    } finally {
      setLoading(false);
    }
  }

  async function handleSave(e) {
    e.preventDefault();
    try {
      setSaving(true);
      for (const [key, val] of Object.entries(formData)) {
        await updateSafetyConfig(key, val);
      }
      if (onSaved) onSaved();
      onClose();
    } catch (err) {
      alert(`Error guardando configuración: ${err.message}`);
    } finally {
      setSaving(false);
    }
  }

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-xs select-none">
      <div className="w-full max-w-lg bg-[#0E1015] border border-white/[0.08] rounded-xl shadow-2xl overflow-hidden flex flex-col">
        {/* Header */}
        <div className="px-5 py-4 border-b border-white/[0.06] flex items-center justify-between bg-zinc-950/60">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-zinc-100 leading-tight">Configuración de Seguridad Antiban</h3>
              <p className="text-[11px] text-zinc-400">Parámetros de protección y cadencia humana del sistema</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Form Body */}
        {loading ? (
          <div className="p-8 text-center text-xs text-zinc-400 flex items-center justify-center gap-2">
            <div className="w-4 h-4 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
            <span>Cargando parámetros...</span>
          </div>
        ) : (
          <form onSubmit={handleSave} className="p-5 space-y-4 text-xs">
            {/* 1. Límites Diarios */}
            <div className="p-3 rounded-lg bg-zinc-900/60 border border-white/[0.05] space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-zinc-200 text-[11px] uppercase tracking-wider">
                  Cuotas Máximas Diarias
                </span>
                <span className="text-[10px] text-zinc-500">Límites recomendados por cuenta</span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">Invitaciones LinkedIn / día</label>
                  <input
                    type="number"
                    min="1"
                    max="50"
                    value={formData.limite_linkedin_diario}
                    onChange={(e) => setFormData({ ...formData, limite_linkedin_diario: e.target.value })}
                    className="w-full px-2.5 py-1.5 rounded-md bg-zinc-950 border border-zinc-800 text-zinc-100 focus:outline-none focus:border-emerald-500 font-mono text-xs"
                  />
                  <span className="text-[10px] text-zinc-500 mt-0.5 block">Recomendado: 5 a 15</span>
                </div>
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">Correos Workspace / día</label>
                  <input
                    type="number"
                    min="1"
                    max="100"
                    value={formData.limite_email_workspace_diario}
                    onChange={(e) => setFormData({ ...formData, limite_email_workspace_diario: e.target.value })}
                    className="w-full px-2.5 py-1.5 rounded-md bg-zinc-950 border border-zinc-800 text-zinc-100 focus:outline-none focus:border-emerald-500 font-mono text-xs"
                  />
                  <span className="text-[10px] text-zinc-500 mt-0.5 block">Warmup: 15 a 30</span>
                </div>
              </div>
            </div>

            {/* 2. Horario Laboral */}
            <div className="p-3 rounded-lg bg-zinc-900/60 border border-white/[0.05] space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 font-semibold text-zinc-200 text-[11px] uppercase tracking-wider">
                  <Clock className="w-3.5 h-3.5 text-zinc-400" />
                  <span>Ventana Horaria Comercial</span>
                </div>
                <span className="text-[10px] text-zinc-500">Hora local Chile</span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">Hora Inicio</label>
                  <input
                    type="time"
                    value={formData.horario_inicio}
                    onChange={(e) => setFormData({ ...formData, horario_inicio: e.target.value })}
                    className="w-full px-2.5 py-1.5 rounded-md bg-zinc-950 border border-zinc-800 text-zinc-100 focus:outline-none focus:border-emerald-500 font-mono text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">Hora Fin</label>
                  <input
                    type="time"
                    value={formData.horario_fin}
                    onChange={(e) => setFormData({ ...formData, horario_fin: e.target.value })}
                    className="w-full px-2.5 py-1.5 rounded-md bg-zinc-950 border border-zinc-800 text-zinc-100 focus:outline-none focus:border-emerald-500 font-mono text-xs"
                  />
                </div>
              </div>
            </div>

            {/* 3. Pausas Estocásticas */}
            <div className="p-3 rounded-lg bg-zinc-900/60 border border-white/[0.05] space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 font-semibold text-zinc-200 text-[11px] uppercase tracking-wider">
                  <Zap className="w-3.5 h-3.5 text-amber-400" />
                  <span>Pausas Humanas LinkedIn (Gaussiana)</span>
                </div>
                <span className="text-[10px] text-zinc-500">En segundos</span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">Pausa Mínima (seg)</label>
                  <input
                    type="number"
                    min="10"
                    max="600"
                    value={formData.pausa_linkedin_min_seg}
                    onChange={(e) => setFormData({ ...formData, pausa_linkedin_min_seg: e.target.value })}
                    className="w-full px-2.5 py-1.5 rounded-md bg-zinc-950 border border-zinc-800 text-zinc-100 focus:outline-none focus:border-emerald-500 font-mono text-xs"
                  />
                  <span className="text-[10px] text-zinc-500 mt-0.5 block">3 min = 180s</span>
                </div>
                <div>
                  <label className="block text-[11px] text-zinc-400 mb-1">Pausa Máxima (seg)</label>
                  <input
                    type="number"
                    min="20"
                    max="1200"
                    value={formData.pausa_linkedin_max_seg}
                    onChange={(e) => setFormData({ ...formData, pausa_linkedin_max_seg: e.target.value })}
                    className="w-full px-2.5 py-1.5 rounded-md bg-zinc-950 border border-zinc-800 text-zinc-100 focus:outline-none focus:border-emerald-500 font-mono text-xs"
                  />
                  <span className="text-[10px] text-zinc-500 mt-0.5 block">6 min = 360s</span>
                </div>
              </div>
            </div>

            {/* Footer Buttons */}
            <div className="pt-3 border-t border-white/[0.06] flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="px-3 py-1.5 rounded-lg border border-zinc-700/80 hover:bg-zinc-800 text-zinc-300 font-medium transition cursor-pointer text-xs"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={saving}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium transition cursor-pointer text-xs shadow-xs disabled:opacity-50"
              >
                <Save className="w-3.5 h-3.5" />
                <span>{saving ? 'Guardando...' : 'Guardar Cambios'}</span>
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
