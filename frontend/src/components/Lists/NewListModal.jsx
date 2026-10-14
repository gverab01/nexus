// Modal para crear y configurar una nueva lista de prospectos segmentada
import React, { useState } from 'react';
import { X, ListPlus, Search, FileText } from 'lucide-react';
import { createLeadList } from '../../services/api';

export default function NewListModal({ onClose, onCreated, activeTenantWorkspace = '' }) {
  const [nombre, setNombre] = useState('');
  const [terminoBusqueda, setTerminoBusqueda] = useState('');
  const [descripcion, setDescripcion] = useState('');
  const [estado, setEstado] = useState('ACTIVA');
  const [autoConectar, setAutoConectar] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  React.useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!nombre.trim()) {
      alert('Por favor ingresa un nombre para la lista');
      return;
    }

    try {
      setSubmitting(true);
      await createLeadList({
        nombre,
        termino_busqueda: terminoBusqueda,
        descripcion,
        estado,
        conectar_secuencia_activa: autoConectar,
        tenant_id: activeTenantWorkspace || undefined,
      });
      if (onCreated) onCreated();
      onClose();
    } catch (err) {
      alert(`Error creando lista: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 font-sans"
      onClick={onClose}
    >
      <div 
        className="w-full max-w-md bg-[#121316] border border-white/[0.08] rounded-xl shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-4 border-b border-white/[0.06] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-md bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-zinc-300">
              <ListPlus className="w-3.5 h-3.5" />
            </div>
            <div>
              <h3 className="text-xs font-medium text-zinc-100">Nueva Lista de Leads</h3>
              <p className="text-[11px] text-zinc-400">Segmenta prospectos por región o cargo</p>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="p-1 rounded-md text-zinc-400 hover:text-white hover:bg-zinc-800 transition"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4 space-y-3.5 text-xs">
          <div>
            <label className="block text-zinc-400 mb-1 font-medium text-[11px]">Nombre de la Lista *</label>
            <input 
              type="text"
              required
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
              placeholder="Ej: CEOs y Fundadores Startups RM"
              className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-1.5 rounded-md text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 font-sans"
            />
          </div>

          <div>
            <label className="block text-zinc-400 mb-1 font-medium text-[11px]">Término de Búsqueda Asociado (LinkedIn)</label>
            <input 
              type="text"
              value={terminoBusqueda}
              onChange={(e) => setTerminoBusqueda(e.target.value)}
              placeholder="Ej: CEO Founder Santiago"
              className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-1.5 rounded-md text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 font-sans"
            />
          </div>

          <div>
            <label className="block text-zinc-400 mb-1 font-medium text-[11px]">Descripción u Objetivo</label>
            <textarea 
              rows={2}
              value={descripcion}
              onChange={(e) => setDescripcion(e.target.value)}
              placeholder="Notas sobre el segmento o campaña..."
              className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-1.5 rounded-md text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 font-sans"
            />
          </div>

          <div>
            <label className="block text-zinc-400 mb-1 font-medium text-[11px]">Estado Inicial</label>
            <select
              value={estado}
              onChange={(e) => setEstado(e.target.value)}
              className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-1.5 rounded-md text-zinc-200 focus:outline-none focus:border-zinc-500"
            >
              <option value="ACTIVA">ACTIVA (Lista para enriquecer y enrolar)</option>
              <option value="EXTRAYENDO">EXTRAYENDO (En proceso de extracción activa)</option>
              <option value="DETENIDA">DETENIDA / FIJA (Congelada para no añadir)</option>
            </select>
          </div>

          <label className="flex items-center gap-2 pt-1 cursor-pointer">
            <input 
              type="checkbox"
              checked={autoConectar}
              onChange={(e) => setAutoConectar(e.target.checked)}
              className="rounded bg-[#0D0E12] border-white/[0.08] accent-zinc-200 cursor-pointer"
            />
            <span className="text-[11px] text-zinc-300">
              Conectar automáticamente a la secuencia de outreach activa
            </span>
          </label>

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
              {submitting ? 'Creando...' : 'Crear Lista'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
