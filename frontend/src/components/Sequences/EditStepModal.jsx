// Modal para editar los parámetros y plantillas de un paso existente en la secuencia
import React, { useState, useEffect } from 'react';
import { X, Trash2, Edit3, Clock, Mail, MessageSquare, Shield } from 'lucide-react';

export default function EditStepModal({ step, onClose, onSave, onDelete }) {
  const [etiqueta, setEtiqueta] = useState(step.etiqueta || '');
  const [parametros, setParametros] = useState({ ...(step.parametros || {}) });

  // Cerrar con Escape
  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  function handleParamChange(key, value) {
    setParametros((prev) => ({
      ...prev,
      [key]: value,
    }));
  }

  function handleSave(e) {
    e.preventDefault();

    // Normalizar nombres de parámetros antes de guardar para compatibilidad con sequence_engine
    const p = { ...parametros };
    if (step.tipo === 'ESPERAR') {
      const h = parseInt(p.horas_espera || p.horas || 24, 10);
      p.horas_espera = h;
      p.horas = h;
    } else if (step.tipo === 'ENVIAR_INVITACION') {
      const nota = p.plantilla_nota || p.nota || p.plantilla || '';
      p.plantilla_nota = nota;
      p.nota = nota;
      p.incluir_nota = Boolean(nota.trim());
      p.usar_spintax = true;
    } else if (step.tipo === 'ENVIAR_MENSAJE_LINKEDIN') {
      const msg = p.plantilla_mensaje || p.mensaje || p.plantilla || '';
      p.plantilla_mensaje = msg;
      p.mensaje = msg;
    } else if (step.tipo === 'ENVIAR_CORREO_WORKSPACE') {
      const cuerpo = p.cuerpo_email || p.cuerpo || p.plantilla || '';
      p.cuerpo_email = cuerpo;
      p.cuerpo = cuerpo;
      p.asunto = p.asunto || 'Contacto institucional';
    }

    onSave({
      ...step,
      etiqueta,
      parametros: p,
    });
  }

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 font-sans"
      onClick={onClose}
    >
      <div 
        className="w-full max-w-lg bg-[#121316] border border-white/[0.08] rounded-xl shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-4 border-b border-white/[0.06] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-md bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-zinc-300">
              <Edit3 className="w-3.5 h-3.5" />
            </div>
            <div>
              <h3 className="text-xs font-medium text-zinc-100">Editar Paso #{step.orden || step.id}</h3>
              <p className="text-[11px] text-zinc-400 font-mono">{step.tipo}</p>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="p-1 rounded-md text-zinc-400 hover:text-white hover:bg-zinc-800 transition cursor-pointer"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>

        <form onSubmit={handleSave} className="p-4 space-y-3.5 text-xs">
          <div>
            <label className="block text-zinc-400 mb-1 font-medium">Etiqueta Visible del Paso</label>
            <input 
              type="text"
              required
              value={etiqueta}
              onChange={(e) => setEtiqueta(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 px-3 py-1.5 rounded-lg text-zinc-200 focus:outline-hidden focus:border-sky-500 font-sans"
            />
          </div>

          {/* Campos específicos según el tipo de acción */}
          {step.tipo === 'ESPERAR' && (
            <div>
              <label className="block text-zinc-400 mb-1 font-medium">Horas de Espera</label>
              <input 
                type="number"
                min="1"
                max="720"
                value={parametros.horas_espera ?? parametros.horas ?? 24}
                onChange={(e) => {
                  const val = parseInt(e.target.value, 10);
                  handleParamChange('horas_espera', val);
                  handleParamChange('horas', val);
                }}
                className="w-full bg-zinc-950 border border-zinc-800 px-3 py-1.5 rounded-lg text-zinc-200 focus:outline-hidden focus:border-sky-500 font-mono"
              />
              <span className="text-[10px] text-zinc-500 mt-1 block">
                Pausa calculada en horas antes de avanzar al siguiente nodo.
              </span>
            </div>
          )}

          {step.tipo === 'ENVIAR_INVITACION' && (
            <div>
              <label className="block text-zinc-400 mb-1 font-medium">Nota de Invitación (Spintax opcional)</label>
              <textarea 
                rows={3}
                value={parametros.plantilla_nota ?? parametros.nota ?? parametros.plantilla ?? ''}
                onChange={(e) => {
                  handleParamChange('plantilla_nota', e.target.value);
                  handleParamChange('nota', e.target.value);
                }}
                placeholder="Hola {nombre}, un gusto saludarte..."
                className="w-full bg-zinc-950 border border-zinc-800 px-3 py-1.5 rounded-lg text-zinc-200 focus:outline-hidden focus:border-sky-500 font-sans"
              />
              <span className="text-[10px] text-zinc-500 mt-1 block">
                Variables dinámicas disponibles: {'{nombre}'}, {'{empresa}'}, {'{cargo}'}. Deja vacío para invitación directa sin nota (mayor ratio de aceptación).
              </span>
            </div>
          )}

          {step.tipo === 'ENVIAR_MENSAJE_LINKEDIN' && (
            <div>
              <label className="block text-zinc-400 mb-1 font-medium">Mensaje Directo (1er Grado)</label>
              <textarea 
                rows={4}
                value={parametros.plantilla_mensaje ?? parametros.mensaje ?? parametros.plantilla ?? ''}
                onChange={(e) => {
                  handleParamChange('plantilla_mensaje', e.target.value);
                  handleParamChange('mensaje', e.target.value);
                }}
                placeholder="Estimado/a {nombre}, gracias por conectar..."
                className="w-full bg-zinc-950 border border-zinc-800 px-3 py-1.5 rounded-lg text-zinc-200 focus:outline-hidden focus:border-sky-500 font-sans"
              />
            </div>
          )}

          {step.tipo === 'ENVIAR_CORREO_WORKSPACE' && (
            <div className="space-y-3">
              <div>
                <label className="block text-zinc-400 mb-1 font-medium">Asunto del Correo</label>
                <input 
                  type="text"
                  value={parametros.asunto ?? ''}
                  onChange={(e) => handleParamChange('asunto', e.target.value)}
                  placeholder="Propuesta de valor para {empresa}"
                  className="w-full bg-zinc-950 border border-zinc-800 px-3 py-1.5 rounded-lg text-zinc-200 focus:outline-hidden focus:border-sky-500 font-sans"
                />
              </div>
              <div>
                <label className="block text-zinc-400 mb-1 font-medium">Cuerpo del Mensaje (Email)</label>
                <textarea 
                  rows={4}
                  value={parametros.cuerpo_email ?? parametros.cuerpo ?? parametros.plantilla ?? ''}
                  onChange={(e) => {
                    handleParamChange('cuerpo_email', e.target.value);
                    handleParamChange('cuerpo', e.target.value);
                  }}
                  placeholder="Estimado directivo..."
                  className="w-full bg-zinc-950 border border-zinc-800 px-3 py-1.5 rounded-lg text-zinc-200 focus:outline-hidden focus:border-sky-500 font-sans"
                />
              </div>
            </div>
          )}

          <div className="pt-3 border-t border-zinc-800 flex items-center justify-between">
            <button
              type="button"
              onClick={() => {
                if (confirm(`¿Seguro que deseas eliminar el paso "${step.etiqueta}"?`)) {
                  onDelete(step.id);
                }
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-rose-800/30 text-rose-300 bg-rose-950/20 hover:bg-rose-950/40 transition text-xs font-medium cursor-pointer"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span>Eliminar Paso</span>
            </button>

            <div className="flex gap-2">
              <button
                type="button"
                onClick={onClose}
                className="px-3 py-1.5 rounded-md bg-[#0D0E12] hover:bg-zinc-800 border border-white/[0.08] text-zinc-300 font-medium text-xs transition cursor-pointer"
              >
                Cancelar
              </button>
              <button
                type="submit"
                className="px-4 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs shadow-sm transition cursor-pointer"
              >
                Guardar Cambios
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
