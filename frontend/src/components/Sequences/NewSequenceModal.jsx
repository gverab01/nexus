// Modal para crear una nueva secuencia multicanal personalizada
import React, { useState } from 'react';
import { X, GitPullRequest, Sparkles } from 'lucide-react';
import { createSequence } from '../../services/api';

export default function NewSequenceModal({ onClose, onCreated, activeTenantWorkspace = '' }) {
  const [nombre, setNombre] = useState('');
  const [descripcion, setDescripcion] = useState('');
  const [plantilla, setPlantilla] = useState('multicanal');
  const [publicada, setPublicada] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!nombre.trim()) {
      alert('Ingresa un nombre para la secuencia');
      return;
    }

    try {
      setSubmitting(true);
      await createSequence({
        nombre,
        descripcion,
        plantilla,
        publicada,
        tenant_id: activeTenantWorkspace || undefined,
      });
      if (onCreated) onCreated();
      onClose();
    } catch (err) {
      alert(`Error creando secuencia: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 font-sans">
      <div 
        className="w-full max-w-md bg-[#121316] border border-white/[0.08] rounded-xl shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-4 border-b border-white/[0.06] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-md bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-zinc-300">
              <GitPullRequest className="w-3.5 h-3.5" />
            </div>
            <div>
              <h3 className="text-xs font-medium text-zinc-100">Nueva Secuencia</h3>
              <p className="text-[11px] text-zinc-400">Diseña una campaña automatizada de outreach</p>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="p-1 rounded-md text-zinc-400 hover:text-white hover:bg-zinc-800 transition cursor-pointer"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4 space-y-3.5 text-xs">
          <div>
            <label className="block text-zinc-400 mb-1 font-medium text-[11px]">Nombre de la Secuencia *</label>
            <input 
              type="text"
              required
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
              placeholder="Ej: Prospección Gerentes de Operaciones 2026"
              className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-1.5 rounded-md text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 font-sans"
            />
          </div>

          <div>
            <label className="block text-zinc-400 mb-1 font-medium text-[11px]">Descripción u Objetivo</label>
            <textarea 
              rows={2}
              value={descripcion}
              onChange={(e) => setDescripcion(e.target.value)}
              placeholder="Campaña multicanal dirigida a tomadores de decisiones..."
              className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-1.5 rounded-md text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 font-sans"
            />
          </div>

          <div>
            <label className="block text-zinc-400 mb-1 font-medium text-[11px]">Estructura Inicial (Plantilla)</label>
            <select
              value={plantilla}
              onChange={(e) => setPlantilla(e.target.value)}
              className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-1.5 rounded-md text-zinc-200 focus:outline-none focus:border-zinc-500"
            >
              <option value="multicanal">Árbol Completo Multicanal (LinkedIn + Workspace + Bifurcación)</option>
              <option value="linkedin_lineal">Secuencia Lineal LinkedIn (Visita ➔ Conectar ➔ Mensaje)</option>
              <option value="workspace_lineal">Secuencia Lineal Workspace (Email ➔ Espera ➔ Follow-up)</option>
              <option value="vacia">Secuencia Vacía (Empezar desde cero)</option>
            </select>
          </div>

          <div>
            <label className="block text-zinc-400 mb-1 font-medium text-[11px]">Estado Inicial</label>
            <select
              value={publicada ? 'true' : 'false'}
              onChange={(e) => setPublicada(e.target.value === 'true')}
              className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-1.5 rounded-md text-zinc-200 focus:outline-none focus:border-zinc-500"
            >
              <option value="true">Publicada / Activa inmediatamente</option>
              <option value="false">Pausada (Borrador)</option>
            </select>
          </div>

          <div className="pt-2 border-t border-white/[0.06] flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 rounded-md bg-[#0D0E12] hover:bg-zinc-800 border border-white/[0.08] text-zinc-300 font-medium text-xs transition cursor-pointer"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs shadow-sm transition cursor-pointer disabled:opacity-50"
            >
              {submitting ? 'Creando...' : 'Crear Secuencia'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
