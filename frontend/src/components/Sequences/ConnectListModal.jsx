// Modal avanzado para vincular una o múltiples listas de prospectos a una secuencia
import React, { useState } from 'react';
import { X, Link2, CheckSquare, Square, Layers, Database, AlertCircle } from 'lucide-react';
import { connectListToSequence } from '../../services/api';

export default function ConnectListModal({ 
  sequenceId, 
  leadLists = [], 
  connectedListIds = [], 
  onClose, 
  onConnected 
}) {
  const connectedSet = new Set(connectedListIds);
  // Pre-seleccionar la primera lista no conectada si existe
  const availableLists = leadLists.filter((l) => !connectedSet.has(l.id));
  const [selectedListIds, setSelectedListIds] = useState(() => {
    return availableLists.length > 0 ? new Set([availableLists[0].id]) : new Set();
  });
  const [submitting, setSubmitting] = useState(false);

  function handleToggleList(id) {
    if (connectedSet.has(id)) return;
    setSelectedListIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function handleSelectAllAvailable() {
    if (selectedListIds.size === availableLists.length) {
      setSelectedListIds(new Set());
    } else {
      setSelectedListIds(new Set(availableLists.map((l) => l.id)));
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (selectedListIds.size === 0) {
      alert('Selecciona al menos una lista de leads para vincular');
      return;
    }

    try {
      setSubmitting(true);
      const listIdsArray = Array.from(selectedListIds);
      await Promise.all(
        listIdsArray.map((listId) => connectListToSequence(sequenceId, listId))
      );
      if (onConnected) onConnected();
      onClose();
    } catch (err) {
      alert(`Error vinculando listas a la secuencia: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-xs p-4 font-sans animate-fadeIn">
      <div 
        className="w-full max-w-lg bg-[#121316] border border-white/[0.08] rounded-xl shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150 flex flex-col max-h-[85vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-4 border-b border-white/[0.06] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-md bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-zinc-300">
              <Link2 className="w-3.5 h-3.5" />
            </div>
            <div>
              <h3 className="text-xs font-semibold text-zinc-100">Vincular Listas de Leads a la Secuencia</h3>
              <p className="text-[11px] text-zinc-400">
                Los leads de las listas seleccionadas recorrerán este flujo de outreach automáticamente
              </p>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="p-1 rounded-md text-zinc-400 hover:text-white hover:bg-zinc-800 transition cursor-pointer"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4 space-y-3.5 text-xs flex flex-col min-h-0 flex-1">
          <div className="flex items-center justify-between">
            <label className="text-[11px] font-medium text-zinc-300">
              Listas disponibles en tu workspace:
            </label>
            {availableLists.length > 1 && (
              <button
                type="button"
                onClick={handleSelectAllAvailable}
                className="text-[11px] text-zinc-400 hover:text-zinc-200 underline cursor-pointer"
              >
                {selectedListIds.size === availableLists.length ? 'Deseleccionar todas' : 'Seleccionar todas'}
              </button>
            )}
          </div>

          <div className="overflow-y-auto space-y-2 flex-1 pr-1 border border-white/[0.06] rounded-lg p-2 bg-[#0D0E12]">
            {leadLists.length === 0 ? (
              <div className="p-6 text-center text-zinc-500 text-xs space-y-1">
                <AlertCircle className="w-5 h-5 mx-auto text-zinc-600 mb-1" />
                <p>No tienes listas de prospectos creadas en este workspace.</p>
                <p className="text-[11px] text-zinc-600">Crea primero una lista desde la sección "Listas de Leads".</p>
              </div>
            ) : (
              leadLists.map((l) => {
                const isAlreadyConnected = connectedSet.has(l.id);
                const isSelected = selectedListIds.has(l.id);

                return (
                  <div
                    key={l.id}
                    onClick={() => handleToggleList(l.id)}
                    className={`p-2.5 rounded-lg border transition flex items-center justify-between gap-3 ${
                      isAlreadyConnected
                        ? 'bg-zinc-900/30 border-white/[0.03] opacity-60 cursor-not-allowed'
                        : isSelected
                        ? 'bg-zinc-800/60 border-white/[0.18] cursor-pointer'
                        : 'bg-zinc-900/50 border-white/[0.06] hover:border-white/[0.12] cursor-pointer'
                    }`}
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      {isAlreadyConnected ? (
                        <div className="w-4 h-4 rounded bg-emerald-950/60 border border-emerald-500/30 flex items-center justify-center shrink-0">
                          <span className="text-[10px] text-emerald-400 leading-none">✓</span>
                        </div>
                      ) : (
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => handleToggleList(l.id)}
                          onClick={(e) => e.stopPropagation()}
                          className="w-4 h-4 rounded border-zinc-700 bg-zinc-900 text-zinc-100 focus:ring-0 cursor-pointer accent-zinc-200 shrink-0"
                        />
                      )}

                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-xs text-zinc-100 truncate">
                            {l.nombre}
                          </span>
                          {isAlreadyConnected && (
                            <span className="text-[9px] px-1.5 py-0.2 rounded bg-zinc-800 text-zinc-400 font-mono">
                              YA CONECTADA
                            </span>
                          )}
                        </div>
                        {l.descripcion && (
                          <p className="text-[11px] text-zinc-500 truncate max-w-sm mt-0.5">
                            {l.descripcion}
                          </p>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-zinc-900 border border-white/[0.06] text-zinc-300">
                        {l.total_leads || 0} leads
                      </span>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          <div className="pt-2 border-t border-white/[0.06] flex items-center justify-between gap-2 shrink-0">
            <span className="text-[11px] text-zinc-500">
              {selectedListIds.size} {selectedListIds.size === 1 ? 'lista seleccionada' : 'listas seleccionadas'}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onClose}
                className="px-3 py-1.5 rounded-md bg-[#0D0E12] hover:bg-zinc-800 border border-white/[0.08] text-zinc-300 font-medium text-xs transition cursor-pointer"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={submitting || selectedListIds.size === 0}
                className="px-4 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs shadow-sm transition cursor-pointer disabled:opacity-40"
              >
                {submitting ? 'Vinculando...' : `Vincular ${selectedListIds.size} ${selectedListIds.size === 1 ? 'Lista' : 'Listas'}`}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
