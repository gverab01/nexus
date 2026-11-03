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
  Sparkles,
  Briefcase,
  RefreshCw,
  ShieldCheck,
  Layers,
  DollarSign,
  UserCheck,
  Database
} from 'lucide-react';
import { saveLeadContact, fetchLeadDetail, deleteProspect, markLeadMeeting, syncLeadWithLinkedIn, resolveLeadEmail } from '../../services/api';

export default function LeadModal({ prospect, lead, onClose, onUpdated, onLeadUpdated }) {
  const rawLead = prospect || lead || {};
  const activeLead = { ...rawLead, id: rawLead.id || rawLead.lead_id };
  const notifyUpdated = onUpdated || onLeadUpdated;
  const [leadData, setLeadData] = useState(activeLead);
  const [activeTab, setActiveTab] = useState('resumen');
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState(null);
  const [emailInput, setEmailInput] = useState(activeLead.email_directo || activeLead.email || activeLead.email_extracted || '');
  const [phoneInput, setPhoneInput] = useState(activeLead.telefono_directo || activeLead.telefono || '');
  const [savingContact, setSavingContact] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isResolvingEmail, setIsResolvingEmail] = useState(false);
  const [resolveFeedback, setResolveFeedback] = useState(null);

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
    if (!activeLead?.id) return;
    setLeadData(activeLead);
    setEmailInput(activeLead.email_directo || activeLead.email || activeLead.email_extracted || '');
    setPhoneInput(activeLead.telefono_directo || activeLead.telefono || '');

    let isMounted = true;
    setLoadingDetail(true);
    fetchLeadDetail(activeLead.id)
      .then((detail) => {
        if (isMounted && detail) {
          setLeadData(detail);
          if (detail.email_directo || detail.email) setEmailInput(detail.email_directo || detail.email);
          if (detail.telefono_directo || detail.telefono) setPhoneInput(detail.telefono_directo || detail.telefono);
        }
      })
      .catch((err) => console.error('Error cargando detalle de lead:', err))
      .finally(() => {
        if (isMounted) setLoadingDetail(false);
      });

    return () => { isMounted = false; };
  }, [activeLead?.id]);

  if (!activeLead || !activeLead.id) return null;

  async function handleSyncLinkedIn() {
    if (!leadData?.id) return;
    try {
      setIsSyncing(true);
      setSyncMessage(null);
      const res = await syncLeadWithLinkedIn(leadData.id);
      if (res && res.lead) {
        const updated = res.lead;
        setLeadData((prev) => ({
          ...prev,
          nombre: updated.nombre || prev.nombre,
          cargo_actual: updated.cargo_actual || prev.cargo_actual,
          cargo_titular: updated.cargo_titular || prev.cargo_titular,
          cargo: updated.cargo_actual || updated.cargo_titular || prev.cargo,
          institucion: updated.institucion_actual || prev.institucion,
          institucion_actual: updated.institucion_actual || prev.institucion_actual,
          ubicacion: updated.ubicacion || prev.ubicacion,
        }));
        setSyncMessage({ type: 'success', text: res.mensaje || 'Perfil sincronizado en vivo exitosamente desde LinkedIn.' });
        if (notifyUpdated) notifyUpdated(updated);
      }
    } catch (err) {
      setSyncMessage({ type: 'error', text: err.message || 'Error sincronizando con LinkedIn' });
    } finally {
      setIsSyncing(false);
      setTimeout(() => setSyncMessage(null), 5000);
    }
  }

  async function handleSaveContact() {
    try {
      setSavingContact(true);
      await saveLeadContact(leadData.id, {
        email: emailInput,
        telefono: phoneInput,
      });
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2000);
      if (notifyUpdated) notifyUpdated({
        ...leadData,
        email: emailInput,
        email_directo: emailInput,
        telefono: phoneInput,
        telefono_directo: phoneInput,
      });
    } catch (err) {
      alert(`Error guardando datos de contacto: ${err.message}`);
    } finally {
      setSavingContact(false);
    }
  }

  async function handleResolveEmail() {
    if (!leadData?.id) return;
    try {
      setIsResolvingEmail(true);
      setResolveFeedback(null);
      const res = await resolveLeadEmail(leadData.id, true);
      if (res && res.email) {
        setEmailInput(res.email);
        setLeadData((prev) => ({
          ...prev,
          email: res.email,
          email_directo: res.email,
          email_extracted: res.email,
          email_source: res.source,
          email_status: res.status,
          empresa_dominio: res.dominio || prev.empresa_dominio,
        }));
        setResolveFeedback({
          type: 'success',
          text: `Correo resuelto (${res.source || 'cascada'}): ${res.email} [${res.status || 'OK'}]`
        });
        if (notifyUpdated) notifyUpdated({
          ...leadData,
          email: res.email,
          email_directo: res.email,
          email_extracted: res.email,
          email_source: res.source,
          email_status: res.status
        });
      } else {
        setResolveFeedback({
          type: 'warning',
          text: res?.motivo || 'No se localizó un correo público ni corporativo verificado.'
        });
      }
    } catch (err) {
      setResolveFeedback({
        type: 'error',
        text: err.message || 'Error en proceso de resolución de correo'
      });
    } finally {
      setIsResolvingEmail(false);
      setTimeout(() => setResolveFeedback(null), 6000);
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
      if (notifyUpdated) notifyUpdated({ id: leadData.id, _deleted: true });
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
        const meetingLead = {
          ...leadData,
          estado: 'REUNION_AGENDADA',
          fecha_reunion_agendada: meetingDate,
          valor_reunion: res.valor_reunion || 0,
        };
        setLeadData(meetingLead);
        setIsBookingMeeting(false);
        if (notifyUpdated) notifyUpdated(meetingLead);
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
              <p className="text-xs text-emerald-400 mt-0.5 line-clamp-1 font-medium flex items-center gap-1.5">
                <Briefcase className="w-3 h-3 text-emerald-400 shrink-0" />
                <span>{leadData.cargo_actual || leadData.cargo || 'Profesional / Decisor'}</span>
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

              {/* Feedback de sincronización con LinkedIn */}
              {syncMessage && (
                <div className={`p-2.5 rounded-lg text-xs flex items-center gap-2 border transition-all ${
                  syncMessage.type === 'success' 
                    ? 'bg-emerald-950/40 border-emerald-500/40 text-emerald-300' 
                    : 'bg-rose-950/40 border-rose-500/40 text-rose-300'
                }`}>
                  {syncMessage.type === 'success' ? <Check className="w-3.5 h-3.5 shrink-0" /> : <X className="w-3.5 h-3.5 shrink-0" />}
                  <span>{syncMessage.text}</span>
                </div>
              )}

              {/* Cargo Actual y Titular de LinkedIn */}
              <div className="p-3.5 rounded-xl bg-zinc-950/60 border border-zinc-800 space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-start gap-2.5 min-w-0">
                    <Briefcase className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                    <div className="min-w-0">
                      <span className="text-[10px] text-zinc-400 block font-medium uppercase tracking-wider">Cargo / Puesto Actual</span>
                      <span className="font-semibold text-zinc-100 text-xs block">
                        {leadData.cargo_actual || leadData.cargo || 'No determinado'}
                      </span>
                    </div>
                  </div>
                  {leadData.url_perfil && (
                    <button
                      onClick={handleSyncLinkedIn}
                      disabled={isSyncing}
                      className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-[11px] font-medium transition cursor-pointer disabled:opacity-50 shrink-0"
                      title="Sincronizar y verificar en vivo los datos desde el perfil de LinkedIn"
                    >
                      <RefreshCw className={`w-3 h-3 ${isSyncing ? 'animate-spin' : ''}`} />
                      <span>{isSyncing ? 'Sincronizando...' : 'Sincronizar'}</span>
                    </button>
                  )}
                </div>
                {leadData.cargo_titular && leadData.cargo_titular !== leadData.cargo_actual && (
                  <div className="pt-2 border-t border-zinc-800/60 pl-6 text-[11px] text-zinc-400">
                    <span className="text-zinc-500 block text-[10px] uppercase tracking-wider">Titular de LinkedIn (Headline):</span>
                    <span className="italic text-zinc-300 block">{leadData.cargo_titular}</span>
                  </div>
                )}
              </div>

              {/* Institución / Empresa */}
              <div className="flex items-start gap-3 p-3 rounded-lg bg-zinc-950/50 border border-zinc-800/80">
                <Building2 className="w-4 h-4 text-sky-400 shrink-0 mt-0.5" />
                <div>
                  <span className="text-[11px] text-zinc-400 block">Empresa / Organización</span>
                  <span className="font-medium text-zinc-200">{leadData.institucion || 'No especificada'}</span>
                </div>
              </div>

              {/* Formulario de Contacto Directo y Resolución en Cascada */}
              <div className="p-3.5 rounded-xl bg-zinc-950/80 border border-zinc-800 space-y-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] font-semibold text-zinc-300 block uppercase tracking-wider">
                      Datos de Contacto
                    </span>
                    {leadData.email_status && (
                      <span className={`text-[10px] font-mono px-1.5 py-0.2 rounded border ${
                        leadData.email_status === 'VERIFICADO'
                          ? 'bg-emerald-950/80 text-emerald-300 border-emerald-500/40'
                          : leadData.email_status === 'PROBABLE'
                          ? 'bg-amber-950/80 text-amber-300 border-amber-500/40'
                          : 'bg-zinc-900 text-zinc-400 border-zinc-700'
                      }`}>
                        {leadData.email_status}
                      </span>
                    )}
                  </div>
                  
                  {/* Botón Resolver Correo */}
                  <button
                    type="button"
                    onClick={handleResolveEmail}
                    disabled={isResolvingEmail}
                    className="flex items-center gap-1 px-2.5 py-1 rounded bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-500 hover:to-indigo-500 text-white text-[11px] font-medium shadow-xs transition cursor-pointer disabled:opacity-50 shrink-0"
                    title="Resolver email: 1er grado directo desde LinkedIn o cascada (dominio + APIs + patrones corporativos + DNS MX + SMTP)"
                  >
                    <Sparkles className={`w-3 h-3 ${isResolvingEmail ? 'animate-spin' : ''}`} />
                    <span>{isResolvingEmail ? 'Resolviendo...' : 'Resolver Email'}</span>
                  </button>
                </div>

                {/* Badges de origen y dominio si existen */}
                {(leadData.email_source || leadData.empresa_dominio) && (
                  <div className="flex items-center gap-2 text-[10px] font-mono text-zinc-400 flex-wrap">
                    {leadData.email_source && (
                      <span className="px-2 py-0.5 rounded bg-zinc-900 border border-zinc-800 text-zinc-300">
                        Fuente: {
                          leadData.email_source === 'linkedin_direct' ? 'LinkedIn Directo (1º)' :
                          leadData.email_source === 'smtp_verified' ? 'SMTP Ping 250 OK' :
                          leadData.email_source === 'hunter' ? 'Hunter.io API' :
                          leadData.email_source === 'dropcontact' ? 'Dropcontact' :
                          leadData.email_source === 'pattern_catch_all' ? 'Patrón Catch-All' :
                          'Patrón Corporativo MX'
                        }
                      </span>
                    )}
                    {leadData.empresa_dominio && (
                      <span className="px-2 py-0.5 rounded bg-zinc-900 border border-zinc-800 text-sky-400">
                        Dominio: {leadData.empresa_dominio}
                      </span>
                    )}
                  </div>
                )}

                {/* Notificación de feedback de resolución */}
                {resolveFeedback && (
                  <div className={`p-2.5 rounded-lg text-xs flex items-center gap-2 border transition-all ${
                    resolveFeedback.type === 'success'
                      ? 'bg-emerald-950/40 border-emerald-500/40 text-emerald-300'
                      : resolveFeedback.type === 'warning'
                      ? 'bg-amber-950/40 border-amber-500/40 text-amber-300'
                      : 'bg-rose-950/40 border-rose-500/40 text-rose-300'
                  }`}>
                    {resolveFeedback.type === 'success' ? (
                      <Check className="w-3.5 h-3.5 shrink-0" />
                    ) : (
                      <X className="w-3.5 h-3.5 shrink-0" />
                    )}
                    <span className="text-[11px] leading-tight">{resolveFeedback.text}</span>
                  </div>
                )}

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

              {/* Tarjeta de Inteligencia B2B: Cruce con Zoho CRM */}
              <div className="p-3.5 rounded-xl bg-zinc-950/80 border border-zinc-800 space-y-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <div className="w-6 h-6 rounded bg-amber-500/10 text-amber-400 flex items-center justify-center border border-amber-500/20">
                      <Database className="w-3.5 h-3.5" />
                    </div>
                    <div>
                      <span className="text-[11px] font-semibold text-zinc-200 block uppercase tracking-wider">
                        Inteligencia Zoho CRM
                      </span>
                      <p className="text-[10px] text-zinc-400">
                        {leadData.zoho_synced_at ? `Sincronizado: ${new Date(leadData.zoho_synced_at).toLocaleDateString()}` : 'Sin cruce reciente'}
                      </p>
                    </div>
                  </div>
                </div>

                {leadData.zoho_id ? (
                  <div className="space-y-2.5 pt-1 border-t border-zinc-800/80">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <div className="flex items-center gap-1.5">
                        <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-zinc-900 border border-zinc-700 text-zinc-200">
                          {leadData.zoho_entidad_tipo || 'Entidad'}
                        </span>
                        {leadData.zoho_cuenta_es_cliente === 1 && (
                          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 flex items-center gap-1">
                            <ShieldCheck className="w-3 h-3" />
                            CLIENTE ACTIVO
                          </span>
                        )}
                        {leadData.zoho_lead_status && (
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-zinc-900 border border-zinc-800 text-zinc-400">
                            Estado: {leadData.zoho_lead_status}
                          </span>
                        )}
                      </div>
                      <span className="text-[10px] font-mono text-zinc-500">
                        ID: {leadData.zoho_id}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-2 text-[11px]">
                      <div className="p-2 rounded bg-zinc-900/60 border border-zinc-800/60">
                        <span className="text-[10px] text-zinc-400 block mb-0.5">Email en Zoho</span>
                        <span className="font-mono text-zinc-200 break-all">
                          {leadData.email_zoho || 'Sin correo registrado'}
                        </span>
                      </div>
                      <div className="p-2 rounded bg-zinc-900/60 border border-zinc-800/60">
                        <span className="text-[10px] text-zinc-400 block mb-0.5">Dueño de la Cuenta</span>
                        <span className="font-medium text-zinc-200">
                          {leadData.zoho_cuenta_dueno || 'Sin asignar'}
                        </span>
                      </div>
                    </div>

                    {leadData.zoho_cuenta_nombre && (
                      <div className="p-2 rounded bg-zinc-900/40 border border-zinc-800/50 flex items-center justify-between text-[11px]">
                        <span className="text-zinc-400">Cuenta / Colegio:</span>
                        <span className="font-medium text-zinc-200">{leadData.zoho_cuenta_nombre}</span>
                      </div>
                    )}

                    {/* Tratos / Oportunidades asociadas */}
                    {leadData.zoho_tratos && leadData.zoho_tratos.length > 0 && (
                      <div className="space-y-1.5 pt-1">
                        <span className="text-[10px] uppercase font-semibold text-zinc-400 tracking-wider block">
                          Tratos Asociados ({leadData.zoho_tratos.length})
                        </span>
                        <div className="space-y-1 max-h-36 overflow-y-auto">
                          {leadData.zoho_tratos.map((trato, tIdx) => (
                            <div key={tIdx} className="p-2 rounded bg-zinc-900/90 border border-zinc-800 text-[11px] flex items-center justify-between">
                              <div className="min-w-0 pr-2">
                                <span className="font-medium text-zinc-200 block truncate">{trato.deal_name || 'Oportunidad'}</span>
                                <span className="text-[10px] text-zinc-400 block">Etapa: {trato.stage || 'En curso'}</span>
                              </div>
                              <div className="text-right shrink-0">
                                {trato.amount && (
                                  <span className="font-mono text-emerald-400 font-medium block">
                                    ${Number(trato.amount).toLocaleString()}
                                  </span>
                                )}
                                <span className="text-[9px] text-zinc-500 block">{trato.owner_name}</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-[11px] text-zinc-400 pt-1 border-t border-zinc-800/80">
                    Aún no se ha realizado el cruce con Zoho CRM. Haz clic en "Cruzar con Zoho" para verificar si es Contacto o Lead, extraer su email y alertar si la cuenta ya es cliente activo.
                  </p>
                )}
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
              <div className="p-3 rounded-lg bg-zinc-950/50 border border-zinc-800/80 flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <span className="text-[11px] text-zinc-400 block">Perfil de LinkedIn</span>
                  <span className="text-xs text-zinc-300 font-mono truncate max-w-xs block">
                    {leadData.url_perfil}
                  </span>
                </div>
                {leadData.url_perfil && (
                  <div className="flex items-center gap-1.5 shrink-0">
                    <button
                      onClick={handleSyncLinkedIn}
                      disabled={isSyncing}
                      className="flex items-center gap-1 px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-emerald-400 text-xs transition cursor-pointer disabled:opacity-50"
                      title="Sincronizar datos reales desde LinkedIn"
                    >
                      <RefreshCw className={`w-3 h-3 ${isSyncing ? 'animate-spin' : ''}`} />
                      <span>{isSyncing ? 'Sincronizando...' : 'Sincronizar'}</span>
                    </button>
                    <a
                      href={leadData.url_perfil}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1 px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-sky-400 text-xs transition"
                    >
                      <ExternalLink className="w-3 h-3" />
                      <span>Abrir</span>
                    </a>
                  </div>
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
