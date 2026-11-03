// Modal para crear y configurar una nueva lista de prospectos segmentada
import React, { useState } from 'react';
import { X, ListPlus, AlertCircle } from 'lucide-react';
import { createLeadList } from '../../services/api';

export default function NewListModal({ onClose, onCreated, activeTenantWorkspace = '' }) {
  const [nombre, setNombre] = useState('');
  const [descripcion, setDescripcion] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  React.useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  async function handleSubmit(e) {
    e.preventDefault();
    setErrorMsg('');
    const cleanNombre = nombre.trim();
    if (!cleanNombre) {
      setErrorMsg('Por favor ingresa un nombre para la lista.');
      return;
    }

    try {
      setSubmitting(true);
      await createLeadList({
        nombre: cleanNombre,
        descripcion: descripcion.trim(),
        estado: 'ACTIVA',
        conectar_secuencia_activa: false,
        tenant_id: activeTenantWorkspace || undefined,
      });
      if (onCreated) onCreated();
      onClose();
    } catch (err) {
      setErrorMsg(err.message || 'Error al crear la lista');
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
              <p className="text-[11px] text-zinc-400">Crea un segmento o carpeta para organizar prospectos</p>
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
          {errorMsg && (
            <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{errorMsg}</span>
            </div>
          )}

          <div>
            <label className="block text-zinc-400 mb-1 font-medium text-[11px]">
              Nombre de la Lista <span className="text-emerald-400">*</span>
            </label>
            <input 
              type="text"
              autoFocus
              required
              value={nombre}
              onChange={(e) => {
                setNombre(e.target.value);
                if (errorMsg) setErrorMsg('');
              }}
              placeholder="Ej: Directores de Colegios RM 2026"
              className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-2 rounded-md text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 font-sans transition"
            />
          </div>

          <div>
            <label className="block text-zinc-400 mb-1 font-medium text-[11px]">
              Descripción o Notas <span className="text-zinc-500 font-normal">(Opcional)</span>
            </label>
            <textarea 
              rows={3}
              value={descripcion}
              onChange={(e) => setDescripcion(e.target.value)}
              placeholder="Notas sobre el segmento, criterios o campaña..."
              className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-2 rounded-md text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 font-sans transition resize-none"
            />
          </div>

          <div className="pt-2 border-t border-white/[0.06] flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 rounded-md bg-[#0D0E12] hover:bg-zinc-800 border border-white/[0.08] text-zinc-300 font-medium text-xs transition cursor-pointer"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={submitting || !nombre.trim()}
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
