// Modal para crear una nueva secuencia multicanal personalizada
import React, { useState, useEffect, useRef } from 'react';
import { X, GitPullRequest, Sparkles } from 'lucide-react';
import { createSequence } from '../../services/api';

export default function NewSequenceModal({ onClose, onCreated, activeTenantWorkspace = '' }) {
  const [nombre, setNombre] = useState('');
  const [descripcion, setDescripcion] = useState('');
  const [plantilla, setPlantilla] = useState('multicanal');
  const [submitting, setSubmitting] = useState(false);
  const inputRef = useRef(null);

  // Foco automático garantizado y manejo de tecla Escape
  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', handleKeyDown);
    const timer = setTimeout(() => {
      if (inputRef.current) {
        inputRef.current.focus();
        inputRef.current.select();
      }
    }, 60);

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      clearTimeout(timer);
    };
  }, [onClose]);

  async function handleSubmit(e) {
    e.preventDefault();
    const cleanNombre = nombre.trim();
    if (!cleanNombre) {
      alert('Ingresa un nombre para la secuencia');
      return;
    }

    try {
      setSubmitting(true);
      const res = await createSequence({
        nombre: cleanNombre,
        descripcion: descripcion.trim(),
        plantilla,
        publicada: false,
        estado: 'BORRADOR',
        tenant_id: activeTenantWorkspace || undefined,
      });
      if (onCreated) onCreated(res);
      onClose();
    } catch (err) {
      alert(`Error creando secuencia: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-xs p-4 font-sans select-none"
      onClick={onClose}
    >
      <div 
        className="w-full max-w-md bg-[#121316] border border-white/[0.08] rounded-xl shadow-2xl overflow-hidden relative z-10 select-text"
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
            type="button"
            onClick={onClose}
            className="p-1 rounded-md text-zinc-400 hover:text-white hover:bg-zinc-800 transition cursor-pointer"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4 space-y-3.5 text-xs">
          <div>
            <label htmlFor="sequence-nombre-input" className="block text-zinc-400 mb-1 font-medium text-[11px] cursor-pointer">
              Nombre de la Secuencia <span className="text-emerald-400">*</span>
            </label>
            <input 
              ref={inputRef}
              id="sequence-nombre-input"
              name="nombre"
              type="text"
              autoFocus
              required
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
              placeholder="Ej: Prospección Gerentes de Operaciones 2026"
              className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-2 rounded-md text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 font-sans cursor-text select-text transition"
            />
          </div>

          <div>
            <label htmlFor="sequence-desc-input" className="block text-zinc-400 mb-1 font-medium text-[11px] cursor-pointer">
              Descripción u Objetivo <span className="text-zinc-500 font-normal">(Opcional)</span>
            </label>
            <textarea 
              id="sequence-desc-input"
              name="descripcion"
              rows={2}
              value={descripcion}
              onChange={(e) => setDescripcion(e.target.value)}
              placeholder="Campaña multicanal dirigida a tomadores de decisiones..."
              className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-2 rounded-md text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 font-sans cursor-text select-text transition resize-none"
            />
          </div>

          <div>
            <label htmlFor="sequence-plantilla-select" className="block text-zinc-400 mb-1 font-medium text-[11px] cursor-pointer">
              Estructura Inicial (Plantilla)
            </label>
            <select
              id="sequence-plantilla-select"
              name="plantilla"
              value={plantilla}
              onChange={(e) => setPlantilla(e.target.value)}
              className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-2 rounded-md text-zinc-200 focus:outline-none focus:border-zinc-500 cursor-pointer"
            >
              <option value="trilateral_multicanal">Trilateral Inteligente (LinkedIn + WhatsApp Web Antiban + Correo Workspace)</option>
              <option value="multicanal">Árbol Multicanal LinkedIn + Email Workspace con Bifurcación</option>
              <option value="linkedin_lineal">Secuencia Lineal LinkedIn (Visita ➔ Conectar con Nota ➔ Mensaje)</option>
              <option value="whatsapp_lineal">Secuencia Directa WhatsApp Web (Saludo ➔ Pausa Antiban ➔ Follow-up)</option>
              <option value="workspace_lineal">Secuencia Lineal Workspace (Email ➔ Espera ➔ Follow-up)</option>
              <option value="vacia">Secuencia Vacía (Empezar desde cero)</option>
            </select>
          </div>

          <div className="p-3 rounded-lg bg-zinc-900/60 border border-white/[0.06] flex items-start gap-2.5">
            <div className="w-5 h-5 rounded-full bg-zinc-800 border border-zinc-700/60 flex items-center justify-center shrink-0 mt-0.5 text-zinc-300 font-mono text-[10px]">
              📝
            </div>
            <div>
              <p className="text-xs font-medium text-zinc-200">Estado inicial: Borrador</p>
              <p className="text-[11px] text-zinc-400 mt-0.5 leading-relaxed">
                Cada secuencia se inicia en modo <strong>Borrador</strong> para que configures los pasos y vincules tus listas con tranquilidad. Solo empezará a ejecutarse cuando hagas clic en <strong>"Publicar Secuencia"</strong>.
              </p>
            </div>
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
              disabled={submitting || !nombre.trim()}
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
