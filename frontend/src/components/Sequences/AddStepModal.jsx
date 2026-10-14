// Modal para insertar un nuevo paso al inicio, intermedio o final del flujo de la secuencia
import React, { useState, useEffect } from 'react';
import { X, PlusCircle, ArrowDown } from 'lucide-react';

export default function AddStepModal({ initialPosition = 'final', existingSteps = [], onClose, onAdd }) {
  const [position, setPosition] = useState(initialPosition);
  const [referenceStepId, setReferenceStepId] = useState(
    existingSteps.length > 0 ? existingSteps[0].id : ''
  );
  const [actionType, setActionType] = useState('ESPERAR');
  const [label, setLabel] = useState('Pausa de 24 Horas');
  const [delayHours, setDelayHours] = useState(24);
  const [template, setTemplate] = useState('');
  const [emailSubject, setEmailSubject] = useState('');

  // Cerrar con Escape
  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  // Sincronizar etiqueta por defecto según el tipo seleccionado
  function handleTypeChange(type) {
    setActionType(type);
    const defaultLabels = {
      VISITAR_PERFIL: 'Visitar Perfil LinkedIn',
      ESPERAR: 'Pausa de 24 Horas',
      ENVIAR_INVITACION: 'Enviar Invitación a Conectar',
      ENVIAR_MENSAJE_LINKEDIN: 'Mensaje Directo 1er Grado',
      ENVIAR_CORREO_WORKSPACE: 'Email Institucional Workspace',
      VERIFICAR_ESTADO: 'Verificar si Aceptó Conexión',
      RETIRAR_INVITACION: 'Retirar Solicitud Pendiente',
    };
    if (defaultLabels[type]) {
      setLabel(defaultLabels[type]);
    }
  }

  function handleSubmit(e) {
    e.preventDefault();

    const newStep = {
      id: `step-${Date.now().toString(36)}`,
      tipo: actionType,
      tipo_accion: actionType,
      etiqueta: label,
      parametros: {},
    };

    if (actionType === 'ESPERAR') {
      newStep.parametros = { horas_espera: delayHours, horas: delayHours };
    } else if (actionType === 'ENVIAR_INVITACION') {
      newStep.parametros = {
        plantilla_nota: template,
        nota: template,
        incluir_nota: Boolean(template.trim()),
        usar_spintax: true,
      };
    } else if (actionType === 'ENVIAR_MENSAJE_LINKEDIN') {
      newStep.parametros = {
        plantilla_mensaje: template,
        mensaje: template,
      };
    } else if (actionType === 'ENVIAR_CORREO_WORKSPACE') {
      newStep.parametros = {
        asunto: emailSubject || 'Contacto institucional',
        cuerpo_email: template,
        cuerpo: template,
      };
    }

    onAdd({
      step: newStep,
      position,
      referenceStepId: position === 'intermedio' ? referenceStepId : null,
    });
    onClose();
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
              <PlusCircle className="w-3.5 h-3.5" />
            </div>
            <div>
              <h3 className="text-xs font-medium text-zinc-100">Insertar Nuevo Paso</h3>
              <p className="text-[11px] text-zinc-400">Agrega una acción o bifurcación al flujo</p>
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
            <label className="block text-zinc-400 mb-1 font-medium">Posición en la Secuencia</label>
            <select
              value={position}
              onChange={(e) => setPosition(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 px-3 py-1.5 rounded-lg text-zinc-200 focus:outline-hidden focus:border-sky-500"
            >
              <option value="final">Al final de la secuencia</option>
              <option value="inicio">Al inicio (Paso 1, desplaza los demás)</option>
              <option value="intermedio">Paso intermedio (después de uno específico)</option>
            </select>
          </div>

          {position === 'intermedio' && (
            <div>
              <label className="block text-zinc-400 mb-1 font-medium">Insertar inmediatamente después de:</label>
              <select
                value={referenceStepId}
                onChange={(e) => setReferenceStepId(e.target.value)}
                className="w-full bg-zinc-950 border border-zinc-800 px-3 py-1.5 rounded-lg text-zinc-200 focus:outline-hidden focus:border-sky-500"
              >
                {existingSteps.map((s, idx) => (
                  <option key={s.id || idx} value={s.id || idx}>
                    Paso #{idx + 1}: {s.etiqueta || s.tipo}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label className="block text-zinc-400 mb-1 font-medium">Tipo de Acción *</label>
            <select
              value={actionType}
              onChange={(e) => handleTypeChange(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 px-3 py-1.5 rounded-lg text-zinc-200 focus:outline-hidden focus:border-sky-500"
            >
              <option value="VISITAR_PERFIL">LinkedIn: Visita de Perfil</option>
              <option value="ESPERAR">Espera: Pausa de Tiempo (Horas)</option>
              <option value="ENVIAR_INVITACION">LinkedIn: Enviar Invitación a Conectar</option>
              <option value="ENVIAR_MENSAJE_LINKEDIN">LinkedIn: Enviar Mensaje Directo (1er Grado)</option>
              <option value="ENVIAR_CORREO_WORKSPACE">Google Workspace: Enviar Correo Institucional</option>
              <option value="VERIFICAR_ESTADO">Bifurcación: Verificar si Aceptó Conexión</option>
              <option value="RETIRAR_INVITACION">LinkedIn: Retirar Solicitud Pendiente</option>
            </select>
          </div>

          <div>
            <label className="block text-zinc-400 mb-1 font-medium">Nombre / Etiqueta Visible</label>
            <input 
              type="text"
              required
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 px-3 py-1.5 rounded-lg text-zinc-200 focus:outline-hidden focus:border-sky-500 font-sans"
            />
          </div>

          {actionType === 'ESPERAR' && (
            <div>
              <label className="block text-zinc-400 mb-1 font-medium">Horas de Espera</label>
              <input 
                type="number"
                min="1"
                value={delayHours}
                onChange={(e) => setDelayHours(parseInt(e.target.value, 10))}
                className="w-full bg-zinc-950 border border-zinc-800 px-3 py-1.5 rounded-lg text-zinc-200 focus:outline-hidden focus:border-sky-500 font-mono"
              />
            </div>
          )}

          {actionType === 'ENVIAR_CORREO_WORKSPACE' && (
            <div>
              <label className="block text-zinc-400 mb-1 font-medium">Asunto</label>
              <input 
                type="text"
                value={emailSubject}
                onChange={(e) => setEmailSubject(e.target.value)}
                placeholder="Propuesta institucional"
                className="w-full bg-zinc-950 border border-zinc-800 px-3 py-1.5 rounded-lg text-zinc-200 focus:outline-hidden focus:border-sky-500 font-sans"
              />
            </div>
          )}

          {(actionType === 'ENVIAR_INVITACION' || actionType === 'ENVIAR_MENSAJE_LINKEDIN' || actionType === 'ENVIAR_CORREO_WORKSPACE') && (
            <div>
              <label className="block text-zinc-400 mb-1 font-medium">Plantilla de Mensaje / Texto</label>
              <textarea 
                rows={3}
                value={template}
                onChange={(e) => setTemplate(e.target.value)}
                placeholder="Texto con variables {nombre}, {empresa}, {cargo}..."
                className="w-full bg-zinc-950 border border-zinc-800 px-3 py-1.5 rounded-lg text-zinc-200 focus:outline-hidden focus:border-sky-500 font-sans"
              />
            </div>
          )}

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
              className="px-4 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs shadow-sm transition cursor-pointer"
            >
              Insertar Paso
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
