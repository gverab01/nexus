// Modal para conectar una lista de leads disponible a la secuencia activa
import React, { useState } from 'react';
import { X, Link2 } from 'lucide-react';
import { connectListToSequence } from '../../services/api';

export default function ConnectListModal({ sequenceId, leadLists, onClose, onConnected }) {
  const [selectedListId, setSelectedListId] = useState(
    leadLists.length > 0 ? leadLists[0].id : ''
  );
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!selectedListId) {
      alert('Selecciona una lista de leads');
      return;
    }

    try {
      setSubmitting(true);
      await connectListToSequence(sequenceId, selectedListId);
      if (onConnected) onConnected();
      onClose();
    } catch (err) {
      alert(`Error conectando lista: ${err.message}`);
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
              <Link2 className="w-3.5 h-3.5" />
            </div>
            <div>
              <h3 className="text-xs font-medium text-zinc-100">Conectar Lista a Secuencia</h3>
              <p className="text-[11px] text-zinc-400">Enrola los prospectos de la lista en esta secuencia</p>
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
            <label className="block text-zinc-400 mb-1 font-medium text-[11px]">Seleccionar Lista de Leads</label>
            <select
              value={selectedListId}
              onChange={(e) => setSelectedListId(e.target.value)}
              className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-1.5 rounded-md text-zinc-200 focus:outline-none focus:border-zinc-500 font-sans"
            >
              {leadLists.length === 0 ? (
                <option value="">No hay listas disponibles</option>
              ) : (
                leadLists.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.nombre} ({l.total_leads || 0} leads - {l.estado})
                  </option>
                ))
              )}
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
              disabled={submitting || leadLists.length === 0}
              className="px-4 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs shadow-sm transition cursor-pointer disabled:opacity-50"
            >
              {submitting ? 'Conectando...' : 'Vincular Lista'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
