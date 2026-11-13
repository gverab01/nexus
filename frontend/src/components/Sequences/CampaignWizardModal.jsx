import React, { useEffect, useState } from 'react';
import {
  X,
  ArrowRight,
  ArrowLeft,
  CalendarCheck,
  Mail,
  MessageSquare,
  Sparkles,
  ListFilter,
  Check,
  Rocket,
  Edit3
} from 'lucide-react';
import {
  createSequence,
  connectListToSequence,
  changeSequenceStatus,
  fetchLeadLists
} from '../../services/api';
import { getEnabledChannels } from '../../utils/channelsConfig';
import { showToast } from '../Toast';

export default function CampaignWizardModal({
  isOpen,
  onClose,
  onCreated,
  activeTenantWorkspace = '',
}) {
  const [step, setStep] = useState(1); // 1: Plantilla, 2: Audiencia, 3: Nombre y lanzamiento
  const [selectedTemplate, setSelectedTemplate] = useState('linkedin_lineal');
  const [selectedListIds, setSelectedListIds] = useState(new Set());
  const [campaignName, setCampaignName] = useState('');
  const [launchImmediately, setLaunchImmediately] = useState(true);
  const [lists, setLists] = useState([]);
  const [loadingLists, setLoadingLists] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const enabledChannels = getEnabledChannels();

  useEffect(() => {
    if (!isOpen) return;
    setStep(1);
    setSelectedTemplate('linkedin_lineal');
    setSelectedListIds(new Set());
    setCampaignName('');
    setLaunchImmediately(true);

    async function load() {
      try {
        setLoadingLists(true);
        const data = await fetchLeadLists(activeTenantWorkspace);
        setLists(Array.isArray(data) ? data : data?.listas || []);
      } catch {
        setLists([]);
      } finally {
        setLoadingLists(false);
      }
    }
    load();
  }, [isOpen, activeTenantWorkspace]);

  if (!isOpen) return null;

  const allTemplates = [
    {
      id: 'linkedin_lineal',
      title: 'Conseguir reunión en LinkedIn',
      subtitle: 'Visita perfil → Invitación → Seguimientos orientados a agendar llamada',
      channels: ['LinkedIn'],
      icon: CalendarCheck,
      recommended: true,
      visible: true,
    },
    {
      id: 'multicanal',
      title: 'LinkedIn + Correo corporativo',
      subtitle: 'Combina invitación en LinkedIn con seguimiento al email si no responde',
      channels: ['LinkedIn', 'Correo'],
      icon: Mail,
      recommended: false,
      visible: Boolean(enabledChannels.email),
    },
    {
      id: 'whatsapp_lineal',
      title: 'Seguimiento directo por WhatsApp',
      subtitle: 'Secuencia cercana por WhatsApp Web para prospectos con teléfono',
      channels: ['WhatsApp'],
      icon: MessageSquare,
      recommended: false,
      visible: Boolean(enabledChannels.whatsapp),
    },
    {
      id: 'trilateral_multicanal',
      title: 'Campaña 360° Multicanal',
      subtitle: 'Combina LinkedIn, WhatsApp y Correo en una misma secuencia',
      channels: ['LinkedIn', 'WhatsApp', 'Correo'],
      icon: Sparkles,
      recommended: false,
      visible: Boolean(enabledChannels.whatsapp && enabledChannels.email),
    },
  ].filter((t) => t.visible);

  const chosenTemplateObj = allTemplates.find((t) => t.id === selectedTemplate) || allTemplates[0];

  function toggleList(id) {
    setSelectedListIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleFinish() {
    const finalName = campaignName.trim() || chosenTemplateObj?.title || 'Nueva campaña';
    try {
      setSubmitting(true);
      const created = await createSequence({
        nombre: finalName,
        descripcion: chosenTemplateObj?.subtitle || '',
        plantilla: selectedTemplate,
        publicada: false,
        estado: 'BORRADOR',
        tenant_id: activeTenantWorkspace || undefined,
      });

      const seqId = created?.id;
      if (seqId && selectedListIds.size > 0) {
        for (const listId of selectedListIds) {
          await connectListToSequence(listId, seqId);
        }
      }

      if (seqId && launchImmediately && selectedListIds.size > 0) {
        await changeSequenceStatus(seqId, 'PUBLICADA');
        showToast(`Campaña "${finalName}" creada y activada.`, 'success');
      } else {
        showToast(`Campaña "${finalName}" creada. Ya puedes revisar o editar sus mensajes.`, 'success');
      }

      if (onCreated) await onCreated(created);
      onClose();
    } catch (err) {
      showToast(`Error creando campaña: ${err.message}`, 'error');
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
        className="w-full max-w-xl bg-[#121316] border border-white/[0.1] rounded-2xl shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header del Wizard */}
        <div className="px-6 py-4 border-b border-white/[0.08] flex items-center justify-between">
          <div>
            <div className="text-xs font-medium text-blue-400">
              Paso {step} de 3
            </div>
            <h2 className="text-base font-semibold text-zinc-100 mt-0.5">
              {step === 1 && 'Elige una plantilla orientada a reuniones'}
              {step === 2 && '¿A qué lista de contactos quieres llegar?'}
              {step === 3 && 'Revisa y lanza tu campaña'}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-white/[0.06] transition cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Barra de progreso */}
        <div className="h-1 bg-zinc-900">
          <div
            className="h-full bg-blue-500 transition-all duration-300"
            style={{ width: `${(step / 3) * 100}%` }}
          />
        </div>

        {/* Contenido por paso */}
        <div className="p-6 space-y-4 max-h-[65vh] overflow-y-auto">
          {step === 1 && (
            <div className="space-y-3">
              {allTemplates.map((tpl) => {
                const Icon = tpl.icon;
                const active = selectedTemplate === tpl.id;
                return (
                  <button
                    key={tpl.id}
                    type="button"
                    onClick={() => setSelectedTemplate(tpl.id)}
                    className={`w-full text-left p-4 rounded-xl border transition cursor-pointer flex items-start gap-3.5 ${
                      active
                        ? 'bg-blue-600/15 border-blue-500/60'
                        : 'bg-[#0E0F12] border-[#22252B] hover:border-zinc-600'
                    }`}
                  >
                    <div className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${
                      active ? 'bg-blue-600 text-white' : 'bg-[#14161A] text-zinc-300 border border-[#22252B]'
                    }`}>
                      <Icon className="w-4 h-4" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-semibold text-zinc-100">{tpl.title}</span>
                        {tpl.recommended && (
                          <span className="px-2 py-0.5 rounded-full text-[11px] bg-emerald-950/60 text-emerald-300 border border-emerald-600/40">
                            Recomendada
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-zinc-400 mt-1">{tpl.subtitle}</p>
                      <div className="flex items-center gap-1.5 mt-2">
                        {tpl.channels.map((c) => (
                          <span key={c} className="px-2 py-0.5 rounded bg-white/[0.06] text-[11px] text-zinc-300">
                            {c}
                          </span>
                        ))}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}

          {step === 2 && (
            <div className="space-y-3">
              {loadingLists ? (
                <p className="text-xs text-zinc-400 py-6 text-center">Cargando tus listas...</p>
              ) : lists.length === 0 ? (
                <div className="rounded-xl bg-[#0E0F12] border border-[#22252B] p-6 text-center space-y-2">
                  <ListFilter className="w-6 h-6 text-zinc-400 mx-auto" />
                  <p className="text-sm font-medium text-zinc-200">Aún no tienes listas creadas</p>
                  <p className="text-xs text-zinc-400">
                    Puedes crear la campaña igual y conectar una lista después desde Audiencia.
                  </p>
                </div>
              ) : (
                <div className="space-y-2">
                  {lists.map((lista) => {
                    const checked = selectedListIds.has(lista.id);
                    const count = lista.total_leads ?? lista.cantidad_leads ?? lista.leads_count ?? 0;
                    return (
                      <button
                        key={lista.id}
                        type="button"
                        onClick={() => toggleList(lista.id)}
                        className={`w-full flex items-center justify-between p-3.5 rounded-xl border text-left transition cursor-pointer ${
                          checked
                            ? 'bg-blue-600/15 border-blue-500/60'
                            : 'bg-[#0E0F12] border-[#22252B] hover:border-zinc-600'
                        }`}
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <div className={`w-5 h-5 rounded flex items-center justify-center border shrink-0 ${
                            checked ? 'bg-blue-600 border-blue-500 text-white' : 'border-zinc-600'
                          }`}>
                            {checked && <Check className="w-3.5 h-3.5" />}
                          </div>
                          <div className="min-w-0">
                            <div className="text-sm font-medium text-zinc-100 truncate">{lista.nombre}</div>
                            {lista.descripcion && (
                              <div className="text-xs text-zinc-400 truncate">{lista.descripcion}</div>
                            )}
                          </div>
                        </div>
                        <span className="text-xs text-zinc-300 font-mono shrink-0 ml-3">
                          {count} contactos
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {step === 3 && (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-zinc-300 mb-1.5">
                  Nombre de la campaña
                </label>
                <input
                  type="text"
                  value={campaignName}
                  onChange={(e) => setCampaignName(e.target.value)}
                  placeholder={chosenTemplateObj?.title || 'Ej: Reuniones Gerentes Comerciales Q4'}
                  className="w-full bg-[#0E0F12] border border-[#22252B] focus:border-blue-500 rounded-lg px-3.5 py-2.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none"
                />
              </div>

              <div className="rounded-xl bg-[#0E0F12] border border-[#22252B] p-4 space-y-2 text-xs">
                <div className="flex justify-between text-zinc-300">
                  <span className="text-zinc-400">Plantilla elegida:</span>
                  <span className="font-medium text-zinc-100">{chosenTemplateObj?.title}</span>
                </div>
                <div className="flex justify-between text-zinc-300">
                  <span className="text-zinc-400">Listas conectadas:</span>
                  <span className="font-medium text-zinc-100">
                    {selectedListIds.size > 0 ? `${selectedListIds.size} lista(s)` : 'Ninguna por ahora'}
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 pt-1">
                <button
                  type="button"
                  onClick={() => setLaunchImmediately(false)}
                  className={`p-3 rounded-xl border text-left transition cursor-pointer ${
                    !launchImmediately
                      ? 'bg-white/[0.08] border-white/30 text-white'
                      : 'bg-[#0E0F12] border-[#22252B] text-zinc-300'
                  }`}
                >
                  <div className="flex items-center gap-2 text-xs font-semibold">
                    <Edit3 className="w-3.5 h-3.5" />
                    <span>Revisar mensajes primero</span>
                  </div>
                  <p className="text-[11px] text-zinc-400 mt-1">
                    Se guarda en borrador para editar textos antes de enviar.
                  </p>
                </button>

                <button
                  type="button"
                  onClick={() => setLaunchImmediately(true)}
                  disabled={selectedListIds.size === 0}
                  className={`p-3 rounded-xl border text-left transition cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${
                    launchImmediately && selectedListIds.size > 0
                      ? 'bg-emerald-950/40 border-emerald-500/60 text-emerald-100'
                      : 'bg-[#0E0F12] border-[#22252B] text-zinc-300'
                  }`}
                >
                  <div className="flex items-center gap-2 text-xs font-semibold">
                    <Rocket className="w-3.5 h-3.5 text-emerald-400" />
                    <span>Lanzar campaña ahora</span>
                  </div>
                  <p className="text-[11px] text-zinc-400 mt-1">
                    {selectedListIds.size > 0
                      ? 'Activa los envíos con los mensajes de la plantilla.'
                      : 'Requiere elegir al menos 1 lista.'}
                  </p>
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Footer del Wizard */}
        <div className="px-6 py-4 border-t border-white/[0.08] bg-[#0E0F12] flex items-center justify-between">
          {step > 1 ? (
            <button
              type="button"
              onClick={() => setStep((s) => s - 1)}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-[#14161A] hover:bg-zinc-800 border border-[#22252B] text-zinc-200 text-xs font-medium transition cursor-pointer"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Atrás</span>
            </button>
          ) : (
            <div />
          )}

          {step < 3 ? (
            <button
              type="button"
              onClick={() => setStep((s) => s + 1)}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold transition cursor-pointer"
            >
              <span>Continuar</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          ) : (
            <button
              type="button"
              onClick={handleFinish}
              disabled={submitting}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold transition cursor-pointer disabled:opacity-50"
            >
              <span>{submitting ? 'Creando...' : launchImmediately && selectedListIds.size > 0 ? 'Crear y lanzar' : 'Crear y editar mensajes'}</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

