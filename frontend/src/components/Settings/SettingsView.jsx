import React, { useEffect, useState } from 'react';
import {
  Plug,
  ShieldCheck,
  Terminal,
  CheckCircle2,
  ExternalLink,
  Mail,
  MessageSquare,
  Briefcase,
  Globe,
  Eye
} from 'lucide-react';
import AntibanSettingsView from '../Antiban/AntibanSettingsView';
import ActivityLogsView from '../Activity/ActivityLogsView';
import {
  CHANNELS_CHANGED_EVENT,
  getEnabledChannels,
  toggleEnabledChannel
} from '../../utils/channelsConfig';

export default function SettingsView({
  activeTenantWorkspace = '',
  initialSubTab = 'canales', // 'canales' | 'proteccion' | 'historial'
  currentUser = null,
  linkedinSessionActive = false,
  whatsappSessionActive = false,
  zohoSessionActive = false,
  onOpenLinkedin = null,
  onOpenWhatsApp = null,
  onOpenZoho = null,
  onLogoutZoho = null,
  onViewBrowser = null,
  onLogStatusChange = null,
}) {
  const [subTab, setSubTab] = useState(initialSubTab);
  const [enabledChannels, setEnabledChannelsState] = useState(getEnabledChannels);

  useEffect(() => {
    const onChannelsChanged = (e) => setEnabledChannelsState(e.detail || getEnabledChannels());
    window.addEventListener(CHANNELS_CHANGED_EVENT, onChannelsChanged);
    return () => window.removeEventListener(CHANNELS_CHANGED_EVENT, onChannelsChanged);
  }, []);

  const tabs = [
    { id: 'canales', label: 'Integraciones y canales', icon: Plug },
    { id: 'proteccion', label: 'Límites y protección', icon: ShieldCheck },
    { id: 'historial', label: 'Historial de envíos', icon: Terminal },
  ];

  const channels = [
    {
      key: 'linkedin',
      name: 'LinkedIn',
      desc: 'Canal principal para buscar decisores, visitar perfiles, enviar invitaciones y mensajes.',
      icon: Globe,
      required: true,
      connected: linkedinSessionActive,
      onConnect: onOpenLinkedin,
      connectLabel: linkedinSessionActive ? 'Abrir ventana LinkedIn' : 'Conectar LinkedIn',
    },
    {
      key: 'email',
      name: 'Correo electrónico',
      desc: 'Envío de seguimientos por email y enriquecimiento automático de correos corporativos.',
      icon: Mail,
      required: false,
      connected: Boolean(enabledChannels.email),
      onConnect: null,
      connectLabel: null,
    },
    {
      key: 'whatsapp',
      name: 'WhatsApp Web',
      desc: 'Canal opcional para mensajes directos en campañas multicanal.',
      icon: MessageSquare,
      required: false,
      connected: whatsappSessionActive,
      onConnect: onOpenWhatsApp,
      connectLabel: whatsappSessionActive ? 'Abrir WhatsApp Web' : 'Vincular con QR',
    },
    {
      key: 'zoho',
      name: 'Zoho CRM',
      desc: 'Importa leads desde Zoho CRM y sincroniza su estado comercial.',
      icon: Briefcase,
      required: false,
      connected: zohoSessionActive,
      onConnect: onOpenZoho,
      connectLabel: zohoSessionActive ? 'Abrir Zoho CRM' : 'Conectar Zoho CRM',
      onDisconnect: zohoSessionActive ? onLogoutZoho : null,
    },
  ];

  return (
    <div className="space-y-5 font-sans animate-fadeIn">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-white/[0.08] pb-3">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100 tracking-tight">
            Ajustes y cuentas conectadas
          </h1>
          <p className="text-xs text-zinc-300 mt-0.5">
            Elige qué canales integrar en tu flujo de trabajo y ajusta los límites de seguridad de tu cuenta.
          </p>
        </div>

        <div className="inline-flex flex-wrap gap-1 p-1 rounded-lg bg-[#121316] border border-white/[0.08] self-start sm:self-auto">
          {tabs.map((t) => {
            const Icon = t.icon;
            const active = subTab === t.id;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => setSubTab(t.id)}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition cursor-pointer ${
                  active
                    ? 'bg-white/[0.12] text-white shadow-xs'
                    : 'text-zinc-300 hover:text-white hover:bg-white/[0.04]'
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                <span>{t.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {subTab === 'canales' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-xs text-zinc-300">
              Solo los canales que actives aquí aparecerán como opciones al crear tus campañas.
            </p>
            {onViewBrowser && (
              <button
                type="button"
                onClick={onViewBrowser}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-[#14161A] hover:bg-zinc-800 border border-[#22252B] text-zinc-200 text-xs font-medium transition cursor-pointer"
              >
                <Eye className="w-3.5 h-3.5" />
                <span>Ver navegador de trabajo</span>
              </button>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {channels.map((ch) => {
              const Icon = ch.icon;
              const isEnabled = ch.required || Boolean(enabledChannels[ch.key]);
              return (
                <div
                  key={ch.key}
                  className={`rounded-xl border p-5 flex flex-col justify-between gap-4 transition ${
                    isEnabled
                      ? 'bg-[#121316] border-white/[0.12]'
                      : 'bg-[#0E0F12] border-[#22252B] opacity-85'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3">
                      <div className="w-9 h-9 rounded-lg bg-[#14161A] border border-[#22252B] flex items-center justify-center text-zinc-200 shrink-0">
                        <Icon className="w-4 h-4" />
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="text-sm font-semibold text-zinc-100">{ch.name}</h3>
                          {ch.connected && (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] bg-emerald-950/50 text-emerald-300 border border-emerald-600/30">
                              <CheckCircle2 className="w-3 h-3" />
                              <span>Conectado</span>
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-zinc-400 mt-1 leading-relaxed">
                          {ch.desc}
                        </p>
                      </div>
                    </div>

                    {!ch.required && (
                      <button
                        type="button"
                        onClick={() => setEnabledChannelsState(toggleEnabledChannel(ch.key))}
                        className={`px-2.5 py-1 rounded-md text-xs font-medium border transition cursor-pointer shrink-0 ${
                          isEnabled
                            ? 'bg-blue-600/20 border-blue-500/50 text-blue-200 hover:bg-blue-600/30'
                            : 'bg-[#14161A] border-[#22252B] text-zinc-300 hover:text-white'
                        }`}
                      >
                        {isEnabled ? 'Activado' : 'Activar'}
                      </button>
                    )}
                  </div>

                  {isEnabled && (ch.onConnect || ch.onDisconnect) && (
                    <div className="flex items-center gap-2 pt-2 border-t border-white/[0.06]">
                      {ch.onConnect && (
                        <button
                          type="button"
                          onClick={ch.onConnect}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 text-xs font-semibold transition cursor-pointer"
                        >
                          <span>{ch.connectLabel}</span>
                          <ExternalLink className="w-3 h-3" />
                        </button>
                      )}
                      {ch.onDisconnect && (
                        <button
                          type="button"
                          onClick={ch.onDisconnect}
                          className="px-3 py-1.5 rounded-md bg-[#14161A] hover:bg-rose-950/40 border border-[#22252B] hover:border-rose-600/40 text-zinc-300 hover:text-rose-200 text-xs font-medium transition cursor-pointer"
                        >
                          Desconectar
                        </button>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {subTab === 'proteccion' && (
        <AntibanSettingsView activeTenantWorkspace={activeTenantWorkspace} />
      )}

      {subTab === 'historial' && (
        <ActivityLogsView onStatusChange={onLogStatusChange} currentUser={currentUser} />
      )}
    </div>
  );
}

