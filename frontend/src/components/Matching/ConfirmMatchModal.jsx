// Modal para confirmar y promover un lead validado al Directorio oficial o a una lista
import React, { useState, useEffect } from 'react';
import { X, CheckCircle2, UserCheck, ExternalLink, ListFilter, ShieldCheck } from 'lucide-react';
import { confirmAndPromoteStagingLead, fetchLeadLists } from '../../services/api';

export default function ConfirmMatchModal({ lead, onClose, onConfirmed, activeTenantWorkspace = '' }) {
  const [selectedListId, setSelectedListId] = useState('');
  const [lists, setLists] = useState([]);
  const [nombre, setNombre] = useState('');
  const [cargo, setCargo] = useState('');
  const [institucion, setInstitucion] = useState('');
  const [perfilUrl, setPerfilUrl] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (lead) {
      setNombre(lead.candidato_nombre || lead.nombre || '');
      setCargo(lead.candidato_cargo || lead.cargo_declarado || 'Profesional');
      setInstitucion(lead.candidato_institucion || lead.institucion || '');
      setPerfilUrl(lead.candidato_url || '');
    }
    loadLists();
  }, [lead]);

  async function loadLists() {
    try {
      const data = await fetchLeadLists(activeTenantWorkspace);
      setLists(data || []);
    } catch (err) {
      console.error('Error cargando listas:', err);
    }
  }

  async function handleConfirm() {
    if (!perfilUrl.trim()) {
      alert('Debes indicar una URL válida de LinkedIn');
      return;
    }

    try {
      setSubmitting(true);
      await confirmAndPromoteStagingLead(lead.id, {
        lista_id: selectedListId || undefined,
        perfil_url: perfilUrl.trim(),
        nombre: nombre.trim(),
        cargo_actual: cargo.trim(),
        institucion_actual: institucion.trim(),
        tenant_id: activeTenantWorkspace || undefined,
      });

      if (onConfirmed) onConfirmed();
      onClose();
    } catch (err) {
      alert(`Error confirmando prospecto: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  }

  if (!lead) return null;

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-xs p-4 font-sans"
      onClick={onClose}
    >
      <div 
        className="w-full max-w-lg bg-[#121316] border border-white/[0.08] rounded-xl shadow-2xl overflow-hidden relative z-10 flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-4 border-b border-white/[0.06] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-md bg-emerald-950/60 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
              <UserCheck className="w-3.5 h-3.5" />
            </div>
            <div>
              <h3 className="text-xs font-semibold text-zinc-100">Validar y Promover Prospecto</h3>
              <p className="text-[11px] text-zinc-400">Confirma la coincidencia para incorporarlo a NexusReach</p>
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
        <div className="p-4 space-y-4 text-xs">
          {/* Tarjeta resumen de datos cruzados */}
          <div className="p-3 rounded-lg bg-[#0D0E12] border border-white/[0.06] space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-mono text-zinc-500 uppercase">Datos de Origen ({lead.origen || 'MANUAL'})</span>
              {lead.score_coincidencia > 0 && (
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-mono border font-semibold ${
                  lead.score_coincidencia >= 75 
                    ? 'bg-emerald-950/50 text-emerald-300 border-emerald-500/40' 
                    : 'bg-amber-950/50 text-amber-300 border-amber-500/40'
                }`}>
                  Afinidad: {lead.score_coincidencia}%
                </span>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2 text-zinc-300 text-[11px]">
              <div>
                <span className="text-zinc-500 block">Colegio de origen:</span>
                <span className="font-medium text-zinc-200">{lead.institucion || 'No especificado'}</span>
              </div>
              <div>
                <span className="text-zinc-500 block">Email verificado:</span>
                <span className="font-mono text-sky-400">{lead.email || 'No especificado'}</span>
              </div>
            </div>
          </div>

          {/* Ajuste fino de campos oficiales */}
          <div className="space-y-3">
            <div>
              <label className="block text-zinc-400 mb-1 font-medium text-[11px]">
                Nombre Definitivo
              </label>
              <input 
                type="text"
                value={nombre}
                onChange={(e) => setNombre(e.target.value)}
                className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-1.5 rounded-md text-zinc-100 text-xs focus:outline-none focus:border-zinc-500"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-zinc-400 mb-1 font-medium text-[11px]">
                  Cargo Actual en NexusReach
                </label>
                <input 
                  type="text"
                  value={cargo}
                  onChange={(e) => setCargo(e.target.value)}
                  className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-1.5 rounded-md text-zinc-100 text-xs focus:outline-none focus:border-zinc-500"
                />
              </div>

              <div>
                <label className="block text-zinc-400 mb-1 font-medium text-[11px]">
                  Institución Actual
                </label>
                <input 
                  type="text"
                  value={institucion}
                  onChange={(e) => setInstitucion(e.target.value)}
                  className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-1.5 rounded-md text-zinc-100 text-xs focus:outline-none focus:border-zinc-500"
                />
              </div>
            </div>

            <div>
              <label className="block text-zinc-400 mb-1 font-medium text-[11px] flex items-center justify-between">
                <span>URL de Perfil en LinkedIn</span>
                {perfilUrl && (
                  <a 
                    href={perfilUrl} 
                    target="_blank" 
                    rel="noreferrer" 
                    className="text-sky-400 hover:underline flex items-center gap-1 font-normal"
                  >
                    Abrir enlace <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </label>
              <input 
                type="url"
                required
                value={perfilUrl}
                onChange={(e) => setPerfilUrl(e.target.value)}
                placeholder="https://www.linkedin.com/in/usuario"
                className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-1.5 rounded-md text-zinc-100 text-xs focus:outline-none focus:border-zinc-500 font-mono"
              />
            </div>

            {/* Selector de lista de destino */}
            <div className="pt-2 border-t border-white/[0.06]">
              <label className="block text-zinc-400 mb-1 font-medium text-[11px] flex items-center gap-1.5">
                <ListFilter className="w-3.5 h-3.5 text-zinc-400" />
                <span>¿Deseas agregarlo a una Lista de Prospección de inmediato?</span>
              </label>
              <select
                value={selectedListId}
                onChange={(e) => setSelectedListId(e.target.value)}
                className="w-full bg-[#0D0E12] border border-white/[0.08] px-3 py-2 rounded-md text-zinc-200 text-xs focus:outline-none focus:border-zinc-500 cursor-pointer"
              >
                <option value="">Solo al Directorio General de Leads</option>
                {lists.map((l) => (
                  <option key={l.id} value={l.id}>
                    Lista: {l.nombre} ({l.total_leads || l.leads_count || 0} prospectos)
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-white/[0.06] flex justify-end gap-2 shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded-md bg-[#0D0E12] hover:bg-zinc-800 border border-white/[0.08] text-zinc-300 font-medium text-xs transition cursor-pointer"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={submitting || !perfilUrl.trim()}
            className="px-4 py-1.5 rounded-md bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-semibold text-xs shadow-sm transition cursor-pointer disabled:opacity-50 flex items-center gap-1.5"
          >
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>{submitting ? 'Promoviendo...' : 'Confirmar y Promover Lead'}</span>
          </button>
        </div>
      </div>
    </div>
  );
}

