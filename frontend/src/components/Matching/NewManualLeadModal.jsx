// Modal para el ingreso manual uno a uno de prospectos al buzón de matching
import React, { useState, useEffect, useRef } from 'react';
import { X, UserPlus, Sparkles, Building2, Mail, Briefcase, Phone } from 'lucide-react';
import { createManualStagingLead } from '../../services/api';

export default function NewManualLeadModal({ onClose, onCreated, activeTenantWorkspace = '' }) {
  const [nombre, setNombre] = useState('');
  const [institucion, setInstitucion] = useState('');
  const [email, setEmail] = useState('');
  const [cargo, setCargo] = useState('');
  const [telefono, setTelefono] = useState('');
  const [buscarInmediato, setBuscarInmediato] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape' && onClose) onClose();
    }
    window.addEventListener('keydown', handleKeyDown);
    const timer = setTimeout(() => {
      if (inputRef.current) inputRef.current.focus();
    }, 50);

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      clearTimeout(timer);
    };
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    const cleanNombre = nombre.trim();
    if (!cleanNombre) {
      alert('Por favor ingresa el nombre de la persona');
      return;
    }

    try {
      setSubmitting(true);
      const res = await createManualStagingLead({
        nombre: cleanNombre,
        institucion: institucion.trim(),
        email: email.trim(),
        cargo_declarado: cargo.trim(),
        telefono: telefono.trim(),
        origen: 'MANUAL',
        buscar_inmediato: buscarInmediato,
        tenant_id: activeTenantWorkspace || undefined,
      });

      if (onCreated) onCreated(res);
      onClose();
    } catch (err) {
      alert(`Error ingresando prospecto: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-xs p-4 font-sans"
      onClick={onClose}
    >
      <div 
        className="w-full max-w-md bg-[#121316] border border-white/[0.08] rounded-xl shadow-2xl overflow-hidden relative z-10"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-4 border-b border-white/[0.06] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-md bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-zinc-300">
              <UserPlus className="w-3.5 h-3.5" />
            </div>
            <div>
              <h3 className="text-xs font-semibold text-zinc-100">Ingreso Manual de Prospecto</h3>
              <p className="text-[11px] text-zinc-400">Agrega una persona para descubrir y validar su perfil en LinkedIn</p>
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

        {/* Formulario */}
        <form onSubmit={handleSubmit} className="p-4 space-y-3.5 text-xs">
          <div>
            <label className="block text-zinc-400 mb-1 font-medium text-[11px]">
              Nombre Completo <span className="text-emerald-400">*</span>
            </label>
            <input 
              ref={inputRef}
              type="text"
              required
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
              placeholder="Ej: Carolina Morales Silva"
              className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-2 rounded-md text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 font-sans cursor-text transition"
            />
          </div>

          <div>
            <label className="block text-zinc-400 mb-1 font-medium text-[11px]">
              Colegio / Institución de Origen <span className="text-emerald-400">*</span>
            </label>
            <div className="relative">
              <Building2 className="w-3.5 h-3.5 text-zinc-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <input 
                type="text"
                required
                value={institucion}
                onChange={(e) => setInstitucion(e.target.value)}
                placeholder="Ej: Colegio San Ignacio El Bosque"
                className="w-full bg-[#0D0E12] border border-white/[0.08] pl-8.5 pr-3 py-2 rounded-md text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 font-sans cursor-text transition"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-zinc-400 mb-1 font-medium text-[11px]">
                Correo Electrónico <span className="text-zinc-500 font-normal">(Opcional)</span>
              </label>
              <div className="relative">
                <Mail className="w-3.5 h-3.5 text-zinc-500 absolute left-3 top-1/2 -translate-y-1/2" />
                <input 
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="cmorales@colegio.cl"
                  className="w-full bg-[#0D0E12] border border-white/[0.08] pl-8.5 pr-3 py-2 rounded-md text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 font-sans cursor-text transition"
                />
              </div>
            </div>

            <div>
              <label className="block text-zinc-400 mb-1 font-medium text-[11px]">
                Cargo Conocido <span className="text-zinc-500 font-normal">(Opcional)</span>
              </label>
              <div className="relative">
                <Briefcase className="w-3.5 h-3.5 text-zinc-500 absolute left-3 top-1/2 -translate-y-1/2" />
                <input 
                  type="text"
                  value={cargo}
                  onChange={(e) => setCargo(e.target.value)}
                  placeholder="Ej: Directora / Rectora"
                  className="w-full bg-[#0D0E12] border border-white/[0.08] pl-8.5 pr-3 py-2 rounded-md text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 font-sans cursor-text transition"
                />
              </div>
            </div>
          </div>

          <div>
            <label className="block text-zinc-400 mb-1 font-medium text-[11px]">
              Teléfono de Contacto <span className="text-zinc-500 font-normal">(Opcional)</span>
            </label>
            <div className="relative">
              <Phone className="w-3.5 h-3.5 text-zinc-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <input 
                type="text"
                value={telefono}
                onChange={(e) => setTelefono(e.target.value)}
                placeholder="+56 9 8765 4321"
                className="w-full bg-[#0D0E12] border border-white/[0.08] pl-8.5 pr-3 py-2 rounded-md text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 font-sans cursor-text transition"
              />
            </div>
          </div>

          {/* Opciones adicionales */}
          <div className="p-3 rounded-lg bg-zinc-900/60 border border-white/[0.06] flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Sparkles className="w-3.5 h-3.5 text-amber-400" />
              <span className="text-zinc-300 text-xs">Buscar de inmediato en LinkedIn al guardar</span>
            </div>
            <input 
              type="checkbox"
              checked={buscarInmediato}
              onChange={(e) => setBuscarInmediato(e.target.checked)}
              className="w-4 h-4 rounded border-zinc-700 bg-zinc-800 text-emerald-500 focus:ring-0 cursor-pointer"
            />
          </div>

          {/* Botones de acción */}
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
              disabled={submitting || !nombre.trim() || !institucion.trim()}
              className="px-4 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs shadow-sm transition cursor-pointer disabled:opacity-50"
            >
              {submitting ? 'Guardando...' : 'Guardar en Buzón'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

