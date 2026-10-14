// Modal lateral de detalle profundo y edición rápida de datos de contacto del prospecto
import React, { useState, useEffect } from 'react';
import { 
  X, 
  Building2, 
  Mail, 
  Phone, 
  MapPin, 
  ExternalLink, 
  Calendar, 
  Check, 
  Clock, 
  Tag, 
  MessageSquare, 
  Compass,
  Trash2,
  CalendarCheck,
  Sparkles
} from 'lucide-react';
import { saveLeadContact, fetchLeadDetail, deleteProspect, markLeadMeeting } from '../../services/api';

export default function LeadModal({ prospect, onClose, onUpdated }) {
  const [leadData, setLeadData] = useState(prospect);
  const [activeTab, setActiveTab] = useState('resumen');
  const [emailInput, setEmailInput] = useState(prospect.email_directo || '');
  const [phoneInput, setPhoneInput] = useState(prospect.telefono_directo || '');
  const [savingContact, setSavingContact] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  // Estado de conversión de reunión agendada
  const [isBookingMeeting, setIsBookingMeeting] = useState(false);
  const [meetingDate, setMeetingDate] = useState(() => new Date().toISOString().split('T')[0]);
  const [meetingValue, setMeetingValue] = useState('');
  const [submittingMeeting, setSubmittingMeeting] = useState(false);

  // Cerrar con Escape
  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  // Cargar detalle profundo (historial, mensajes, correos)
  useEffect(() => {
    if (!prospect?.id) return;
    setLeadData(prospect);
    setEmailInput(prospect.email_directo || '');
    setPhoneInput(prospect.telefono_directo || '');

    let isMounted = true;
    setLoadingDetail(true);
    fetchLeadDetail(prospect.id)
      .then((detail) => {
        if (isMounted && detail) {
          setLeadData(detail);
          if (detail.email_directo) setEmailInput(detail.email_directo);
          if (detail.telefono_directo) setPhoneInput(detail.telefono_directo);
        }
      })
      .catch((err) => console.error('Error cargando detalle de lead:', err))
      .finally(() => {
        if (isMounted) setLoadingDetail(false);
      });

    return () => { isMounted = false; };
  }, [prospect?.id]);

  if (!prospect) return null;

  async function handleSaveContact() {
    try {
      setSavingContact(true);
      await saveLeadContact(leadData.id, {
        email: emailInput,
        telefono: phoneInput,
      });
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2000);
      if (onUpdated) onUpdated();
    } catch (err) {
      alert(`Error guardando datos de contacto: ${err.message}`);
    } finally {
      setSavingContact(false);
    }
  }

  async function handleDeleteLead() {
    if (!leadData?.id) return;
    const confirmDelete = window.confirm(
      `¿Seguro que deseas eliminar a "${leadData.nombre || 'este prospecto'}" de la base de datos?\nEsta acción no se puede deshacer.`
    );
    if (!confirmDelete) return;

    try {
      setIsDeleting(true);
      await deleteProspect(leadData.id);
      if (onUpdated) onUpdated();
      onClose();
    } catch (err) {
      alert(`Error eliminando prospecto: ${err.message}`);
    } finally {
      setIsDeleting(false);
    }
  }

  async function handleMarkMeeting(e) {
    if (e) e.preventDefault();
    try {
      setSubmittingMeeting(true);
      const res = await markLeadMeeting(leadData.id, {
        fecha_reunion: meetingDate,
        valor_reunion: meetingValue ? parseFloat(meetingValue) : undefined,
      });
      if (res?.exito) {
        setLeadData((prev) => ({
          ...prev,
          estado: 'REUNION_AGENDADA',
          fecha_reunion_agendada: meetingDate,
          valor_reunion: res.valor_reunion || 0,
        }));
        setIsBookingMeeting(false);
        if (onUpdated) onUpdated();
      }
    } catch (err) {
      alert(`Error registrando reunión: ${err.message}`);
    } finally {
      setSubmittingMeeting(false);
    }
  }

  // Obtener iniciales para el avatar
  const initials = (leadData.nombre || 'P')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map(w => w[0])
    .join('')
    .toUpperCase();

  const history = Array.isArray(leadData.historial_interacciones) 
    ? leadData.historial_interacciones 
    : [];

  const mensajes = Array.isArray(leadData.mensajes_linkedin) ? leadData.mensajes_linkedin : [];
  const correos = Array.isArray(leadData.correos) ? leadData.correos : [];

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-end bg-black/60 backdrop-blur-xs transition-opacity font-sans"
      onClick={onClose}
    >
      <div 
        className="w-full max-w-lg h-full bg-[#0D0E12] border-l border-white/[0.08] flex flex-col shadow-2xl animate-in slide-in-from-right duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-5 border-b border-white/[0.06] flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-md bg-zinc-900 border border-white/[0.1] flex items-center justify-center text-zinc-200 font-medium text-xs shadow-inner">
              {initials}
            </div>
            <div>
              <h3 className="text-sm font-medium text-zinc-100 leading-tight">
                {leadData.nombre || 'Sin nombre'}
              </h3>
              <p className="text-xs text-zinc-400 mt-0.5 line-clamp-1">
                {leadData.cargo || 'Profesional / Decisor'}
              </p>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="p-1 rounded-md text-zinc-400 hover:text-white hover:bg-zinc-800 transition cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Navigation Tabs */}
        <div className="flex border-b border-white/[0.06] px-5 gap-3 bg-[#090A0C]/50">
          {[
            { id: 'resumen', label: 'Resumen' },
            { id: 'historial', label: `Historial (${history.length})` },
            { id: 'mensajes', label: `LinkedIn (${mensajes.length})` },
            { id: 'correos', label: `Emails (${correos.length})` },
          ].map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`py-2.5 px-1 text-xs font-medium border-b-2 transition cursor-pointer ${
                activeTab === tab.id
                  ? 'border-zinc-200 text-zinc-100'
                  : 'border-transparent text-zinc-400 hover:text-zinc-200'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4 text-xs">
          {activeTab === 'resumen' && (
            <div className="space-y-4">
              {/* Tarjeta de Conversión: Reunión Comercial Agendada */}
              {leadData.estado === 'REUNION_AGENDADA' ? (
                <div className="p-3.5 rounded-lg bg-emerald-950/20 border border-emerald-500/30 space-y-1.5 animate-fadeIn">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="w-6 h-6 rounded bg-emerald-500/10 text-emerald-400 flex items-center justify-center">
                        <CalendarCheck className="w-3.5 h-3.5" />
                      </div>
                      <div>
                        <span className="font-medium text-emerald-300 text-xs">Reunión Agendada</span>
                        <p className="text-[10px] text-zinc-400">Prospecto convertido a oportunidad comercial</p>
                      </div>
                    </div>
                    {leadData.valor_reunion > 0 && (
                      <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 font-mono text-[11px] font-medium border border-emerald-500/20">
                        +${leadData.valor_reunion} USD
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] font-mono text-zinc-400 pt-1 flex items-center justify-between border-t border-emerald-500/20">
                    <span>Fecha pactada:</span>
                    <span className="text-zinc-200 font-medium">
                      {leadData.fecha_reunion_agendada || 'Registrada'}
                    </span>
                  </div>
                </div>
              ) : (
                <div className="p-3.5 rounded-lg bg-[#121316] border border-white/[0.08] space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Calendar className="w-3.5 h-3.5 text-zinc-400" />
                      <span className="font-medium text-zinc-200 text-xs">Conversión Comercial</span>
                    </div>
                    {!isBookingMeeting && (
                      <button
                        onClick={() => setIsBookingMeeting(true)}
                        className="px-2 py-1 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 text-[11px] font-medium transition cursor-pointer flex items-center gap-1 shadow-sm"
                      >
                        <Sparkles className="w-3 h-3 text-zinc-950" />
                        <span>Agendar Reunión</span>
                      </button>
                    )}
                  </div>

                  {isBookingMeeting ? (
                    <form onSubmit={handleMarkMeeting} className="pt-2 border-t border-zinc-800/80 space-y-2.5">
                      <p className="text-[11px] text-zinc-400">
                        Ingresa los detalles para registrar la reunión y alimentar la facturación del workspace:
                      </p>
                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <label className="block text-[10px] text-zinc-400 mb-1">Fecha de la Cita</label>
                          <input
                            type="date"
                            value={meetingDate}
                            onChange={(e) => setMeetingDate(e.target.value)}
                            required
                            className="w-full bg-zinc-950 border border-zinc-800 px-2 py-1 rounded-lg text-xs text-zinc-200 focus:outline-none focus:border-emerald-500"
                          />
                        </div>
                        <div>
                          <label className="block text-[10px] text-zinc-400 mb-1">Valor Pactado (USD, opcional)</label>
                          <input
                            type="number"
                            step="any"
                            placeholder="Tarifa por defecto"
                            value={meetingValue}
                            onChange={(e) => setMeetingValue(e.target.value)}
                            className="w-full bg-zinc-950 border border-zinc-800 px-2 py-1 rounded-lg text-xs text-zinc-200 focus:outline-none focus:border-emerald-500"
                          />
                        </div>
                      </div>
                      <div className="flex items-center justify-end gap-2 pt-1">
                        <button
                          type="button"
                          onClick={() => setIsBookingMeeting(false)}
                          className="px-2.5 py-1 text-xs text-zinc-400 hover:text-zinc-200 cursor-pointer"
                        >
                          Cancelar
                        </button>
                        <button
                          type="submit"
                          disabled={submittingMeeting}
                          className="px-3 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-xs shadow-md shadow-emerald-600/20 transition cursor-pointer flex items-center gap-1"
                        >
                          <Check className="w-3.5 h-3.5" />
                          <span>{submittingMeeting ? 'Registrando...' : 'Confirmar Reunión'}</span>
                        </button>
                      </div>
                    </form>
                  ) : (
                    <p className="text-[11px] text-zinc-400">
                      Si el prospecto aceptó una demo o llamada, márcalo aquí para reflejarlo en los reportes de resultados.
                    </p>
                  )}
                </div>
              )}

              {/* Institución / Empresa */}
              <div className="flex items-start gap-3 p-3 rounded-lg bg-zinc-950/50 border border-zinc-800/80">
                <Building2 className="w-4 h-4 text-sky-400 shrink-0 mt-0.5" />
                <div>
                  <span className="text-[11px] text-zinc-400 block">Empresa / Organización</span>
                  <span className="font-medium text-zinc-200">{leadData.institucion || 'No especificada'}</span>
                </div>
              </div>

              {/* Formulario de Contacto Directo */}
              <div className="p-3.5 rounded-xl bg-zinc-950/80 border border-zinc-800 space-y-2.5">
                <span className="text-[11px] font-semibold text-zinc-300 block uppercase tracking-wider">
                  Datos de Contacto Directo
                </span>
                <div className="space-y-2">
                  <div className="flex items-center gap-2 bg-zinc-900 px-2.5 py-1.5 rounded-lg border border-zinc-800 focus-within:border-sky-500">
                    <Mail className="w-3.5 h-3.5 text-zinc-400" />
                    <input 
                      type="email"
                      value={emailInput}
                      onChange={(e) => setEmailInput(e.target.value)}
                      placeholder="contacto@empresa.com"
                      className="bg-transparent text-xs text-zinc-200 placeholder-zinc-500 w-full focus:outline-hidden"
                    />
                  </div>
                  <div className="flex items-center gap-2 bg-zinc-900 px-2.5 py-1.5 rounded-lg border border-zinc-800 focus-within:border-sky-500">
                    <Phone className="w-3.5 h-3.5 text-zinc-400" />
                    <input 
                      type="text"
                      value={phoneInput}
                      onChange={(e) => setPhoneInput(e.target.value)}
                      placeholder="+56 9 8765 4321"
                      className="bg-transparent text-xs text-zinc-200 placeholder-zinc-500 w-full focus:outline-hidden"
                    />
                  </div>
                  <button
                    onClick={handleSaveContact}
                    disabled={savingContact}
                    className="w-full flex items-center justify-center gap-1.5 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs transition cursor-pointer shadow-sm"
                  >
                    {saveSuccess ? (
                      <>
                        <Check className="w-3.5 h-3.5" />
                        <span>Guardado correctamente</span>
                      </>
                    ) : (
                      <span>{savingContact ? 'Guardando...' : 'Guardar Contacto'}</span>
                    )}
                  </button>
                </div>
              </div>

              {/* Ubicación y Grado */}
              <div className="grid grid-cols-2 gap-3">
                <div className="p-3 rounded-lg bg-zinc-950/50 border border-zinc-800/80">
                  <div className="flex items-center gap-1.5 text-zinc-400 text-[11px] mb-1">
                    <MapPin className="w-3.5 h-3.5" />
                    <span>Ubicación</span>
                  </div>
                  <span className="text-zinc-200 font-medium">{leadData.ubicacion || 'Chile'}</span>
                </div>
                <div className="p-3 rounded-lg bg-zinc-950/50 border border-zinc-800/80">
                  <span className="text-zinc-400 text-[11px] block mb-1">Grado de Red</span>
                  <span className="text-zinc-200 font-mono font-medium">{leadData.grado_red || '2° o 3°'}</span>
                </div>
              </div>

              {/* Enlace de LinkedIn */}
              <div className="p-3 rounded-lg bg-zinc-950/50 border border-zinc-800/80 flex items-center justify-between">
                <div>
                  <span className="text-[11px] text-zinc-400 block">Perfil de LinkedIn</span>
                  <span className="text-xs text-zinc-300 font-mono truncate max-w-xs block">
                    {leadData.url_perfil}
                  </span>
                </div>
                {leadData.url_perfil && (
                  <a
                    href={leadData.url_perfil}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-sky-400 text-xs transition"
                  >
                    <ExternalLink className="w-3 h-3" />
                    <span>Abrir</span>
                  </a>
                )}
              </div>

              {/* Fechas de Seguimiento */}
              <div className="space-y-1.5 p-3 rounded-lg bg-zinc-950/50 border border-zinc-800/80 text-[11px] font-mono">
                <div className="flex justify-between text-zinc-400">
                  <span>Extracción:</span>
                  <span className="text-zinc-200">{leadData.fecha_extraccion || '-'}</span>
                </div>
                <div className="flex justify-between text-zinc-400">
                  <span>Invitación enviada:</span>
                  <span className="text-zinc-200">{leadData.fecha_invitacion || '-'}</span>
                </div>
                <div className="flex justify-between text-zinc-400">
                  <span>Conexión aceptada:</span>
                  <span className="text-zinc-200">{leadData.fecha_conexion || '-'}</span>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'historial' && (
            <div className="space-y-3">
              {history.length === 0 ? (
                <div className="p-8 text-center text-zinc-500">
                  No hay interacciones registradas aún.
                </div>
              ) : (
                history.map((item, idx) => (
                  <div key={idx} className="flex items-start gap-3 p-3 rounded-lg bg-zinc-950/40 border border-zinc-800">
                    <Clock className="w-3.5 h-3.5 text-sky-400 shrink-0 mt-0.5" />
                    <div>
                      <div className="text-zinc-200 font-medium">
                        {typeof item === 'string' ? item : (item.descripcion || item.tipo_evento || item.accion || item.tipo)}
                      </div>
                      {item.timestamp && (
                        <span className="text-[10px] text-zinc-500 font-mono block mt-0.5">
                          {item.timestamp}
                        </span>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

          {activeTab === 'mensajes' && (
            <div className="space-y-3">
              {mensajes.length === 0 ? (
                <div className="p-8 text-center text-zinc-500">
                  <MessageSquare className="w-8 h-8 mx-auto text-zinc-600 mb-2" />
                  <p>Sin mensajes directos enviados aún.</p>
                  <small className="text-zinc-600">Se activan al confirmar la conexión de 1er grado.</small>
                </div>
              ) : (
                mensajes.map((msg, idx) => (
                  <div key={idx} className="p-3 rounded-lg bg-zinc-950/40 border border-zinc-800 space-y-1.5">
                    <div className="flex items-center justify-between text-[11px] text-zinc-400">
                      <span className="font-medium text-sky-400">{msg.campana_nombre || 'Secuencia'}</span>
                      <span className="font-mono">{msg.enviado_at || msg.created_at || ''}</span>
                    </div>
                    <p className="text-zinc-200 text-xs whitespace-pre-wrap">{msg.contenido}</p>
                    <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-mono bg-zinc-800 text-zinc-300">
                      {msg.estado || 'ENVIADO'}
                    </span>
                  </div>
                ))
              )}
            </div>
          )}

          {activeTab === 'correos' && (
            <div className="space-y-3">
              {correos.length === 0 ? (
                <div className="p-8 text-center text-zinc-500">
                  <Mail className="w-8 h-8 mx-auto text-zinc-600 mb-2" />
                  <p>Sin emails institucionales enviados aún.</p>
                  <small className="text-zinc-600">Enrolado en las secuencias multicanal activas.</small>
                </div>
              ) : (
                correos.map((mail, idx) => (
                  <div key={idx} className="p-3 rounded-lg bg-zinc-950/40 border border-zinc-800 space-y-1.5">
                    <div className="flex items-center justify-between text-[11px] text-zinc-400">
                      <span className="font-medium text-indigo-400">{mail.asunto || 'Sin asunto'}</span>
                      <span className="font-mono">{mail.enviado_at || mail.created_at || ''}</span>
                    </div>
                    <div className="text-[11px] text-zinc-400 font-mono">Para: {mail.email_destino}</div>
                    <p className="text-zinc-300 text-xs whitespace-pre-wrap bg-zinc-900/60 p-2 rounded border border-zinc-800/80">
                      {mail.cuerpo}
                    </p>
                    <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-mono bg-zinc-800 text-zinc-300">
                      {mail.estado || 'ENVIADO'}
                    </span>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {/* Footer de Acciones */}
        <div className="p-4 border-t border-zinc-800 bg-zinc-950/80 flex items-center justify-between shrink-0">
          <button
            onClick={handleDeleteLead}
            disabled={isDeleting}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-rose-400 hover:text-white hover:bg-rose-950/60 border border-rose-900/40 hover:border-rose-600 text-xs font-medium transition cursor-pointer disabled:opacity-50"
            title="Eliminar este prospecto y todo su historial de la base de datos"
          >
            <Trash2 className={`w-3.5 h-3.5 ${isDeleting ? 'animate-spin' : ''}`} />
            <span>{isDeleting ? 'Eliminando...' : 'Eliminar prospecto'}</span>
          </button>
          
          <button
            onClick={onClose}
            className="px-3.5 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs font-medium transition cursor-pointer"
          >
            Cerrar
          </button>
        </div>
      </div>
    </div>
  );
}
