import React, { useState } from 'react';
import { 
  X, 
  ShieldCheck, 
  Calendar, 
  LogOut, 
  Sparkles, 
  CheckCircle2,
  Building2
} from 'lucide-react';
import { updateUserSubscription } from '../../services/api';

export default function SubscriptionModal({
  isOpen,
  onClose,
  currentUser,
  onLogout,
  onUserUpdated
}) {
  if (!isOpen || !currentUser) return null;

  const [updating, setUpdating] = useState(false);
  const [feedback, setFeedback] = useState(null);

  const sub = currentUser.suscripcion || {};
  const isSuperAdmin = currentUser.rol === 'SUPER_ADMIN';
  const isSubClient = currentUser.rol === 'COMPANY_MEMBER' || Boolean(currentUser.tenant?.parent_tenant_id);

  const expiraFecha = sub.expira ? new Date(sub.expira).toLocaleDateString('es-CL', {
    day: '2-digit',
    month: 'long',
    year: 'numeric'
  }) : 'Suscripción Activa';

  async function handleSimularEstado(nuevoEstado) {
    try {
      setUpdating(true);
      setFeedback(null);
      await updateUserSubscription(currentUser.id, { estado: nuevoEstado });
      setFeedback(`Suscripción actualizada a: ${nuevoEstado}`);
      if (onUserUpdated) {
        onUserUpdated({
          ...currentUser,
          suscripcion: {
            ...sub,
            estado: nuevoEstado,
            es_activa: nuevoEstado === 'activa' || nuevoEstado === 'en_prueba'
          }
        });
      }
      if (nuevoEstado !== 'activa') {
        setTimeout(() => {
          onLogout();
        }, 1200);
      }
    } catch (err) {
      setFeedback(`Error: ${err.message}`);
    } finally {
      setUpdating(false);
    }
  }

  async function handleExtenderDias(dias) {
    try {
      setUpdating(true);
      setFeedback(null);
      await updateUserSubscription(currentUser.id, { dias_extra: dias, estado: 'activa' });
      setFeedback(`Se añadieron +${dias} días a tu suscripción.`);
      if (onUserUpdated) {
        onUserUpdated({
          ...currentUser,
          suscripcion: {
            ...sub,
            estado: 'activa',
            dias_restantes: (sub.dias_restantes || 0) + dias,
            es_activa: true
          }
        });
      }
    } catch (err) {
      setFeedback(`Error: ${err.message}`);
    } finally {
      setUpdating(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-fadeIn select-none font-sans">
      <div className="relative w-full max-w-md rounded-xl bg-[#121316] border border-white/[0.08] p-6 shadow-2xl shadow-black/80 space-y-5">
        
        {/* Cabecera del modal */}
        <div className="flex items-center justify-between pb-3 border-b border-white/[0.06]">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-md bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-zinc-300">
              <ShieldCheck className="w-3.5 h-3.5" />
            </div>
            <div>
              <h2 className="text-xs font-medium text-zinc-100">
                {isSubClient ? 'Información de la Cuenta' : 'Estado de la Suscripción'}
              </h2>
              <p className="text-[11px] text-zinc-400">
                {isSubClient ? 'Detalles de acceso corporativo' : 'Licencia activa y control de acceso'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition cursor-pointer"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Ficha del usuario y plan */}
        <div className="p-3.5 rounded-lg bg-[#0D0E12] border border-white/[0.06] space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-full bg-zinc-900 border border-white/[0.1] flex items-center justify-center text-xs font-medium text-zinc-200 shadow-inner">
                {currentUser.nombre ? currentUser.nombre.substring(0, 2).toUpperCase() : 'US'}
              </div>
              <div>
                <div className="text-xs font-medium text-zinc-100">{currentUser.nombre}</div>
                <div className="text-[11px] text-zinc-400 font-mono">{currentUser.email}</div>
              </div>
            </div>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono font-medium bg-emerald-950/20 text-emerald-400 border border-emerald-500/20 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              {currentUser.estado || 'ACTIVO'}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-2 pt-2 border-t border-white/[0.04] text-[11px]">
            <div className="p-2 rounded-md bg-[#121316] border border-white/[0.06]">
              <span className="text-zinc-500 block text-[10px]">Organización</span>
              <span className="font-medium text-zinc-200 text-xs truncate block">
                {currentUser.tenant?.razon_social || 'NexusReach'}
              </span>
            </div>
            <div className="p-2 rounded-md bg-[#121316] border border-white/[0.06]">
              <span className="text-zinc-500 block text-[10px]">Rol Asignado</span>
              <span className="font-medium text-zinc-200 text-xs truncate block">
                {currentUser.rol}
              </span>
            </div>
          </div>

          {!isSubClient && (
            <div className="flex items-center gap-2 text-[11px] text-zinc-400 pt-1">
              <Calendar className="w-3.5 h-3.5 text-zinc-500" />
              <span>Vencimiento: <strong className="text-zinc-200">{expiraFecha}</strong></span>
            </div>
          )}
        </div>

        {/* Feedback visual */}
        {feedback && (
          <div className="p-2 rounded-md bg-white/[0.04] border border-white/[0.08] text-xs text-zinc-200 flex items-center gap-2">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
            <span>{feedback}</span>
          </div>
        )}

        {/* Simulador para Super Admin y administradores directos */}
        {!isSubClient && (
          <div className="p-3 rounded-lg bg-[#0D0E12] border border-white/[0.06] space-y-2">
            <div className="text-[10px] font-medium text-zinc-400 uppercase tracking-wider flex items-center gap-1.5">
              <Sparkles className="w-3 h-3 text-zinc-400" />
              Simulador de Pruebas de Suscripción
            </div>
            <p className="text-[11px] text-zinc-500">
              Prueba cómo reacciona el backend si la suscripción cambia de estado:
            </p>
            <div className="grid grid-cols-3 gap-1.5 pt-1">
              <button
                onClick={() => handleSimularEstado('activa')}
                disabled={updating}
                className="py-1 px-2 rounded-md bg-zinc-800/60 hover:bg-zinc-800 border border-white/[0.08] text-[10px] text-zinc-300 transition cursor-pointer"
              >
                Forzar Activa
              </button>
              <button
                onClick={() => handleSimularEstado('vencida')}
                disabled={updating}
                className="py-1 px-2 rounded-md bg-zinc-800/60 hover:bg-zinc-800 border border-white/[0.08] text-[10px] text-zinc-300 transition cursor-pointer"
              >
                Forzar Vencida
              </button>
              <button
                onClick={() => handleExtenderDias(30)}
                disabled={updating}
                className="py-1 px-2 rounded-md bg-zinc-800/60 hover:bg-zinc-800 border border-white/[0.08] text-[10px] text-zinc-300 transition cursor-pointer"
              >
                +30 Días
              </button>
            </div>
          </div>
        )}

        {isSubClient && (
          <div className="p-3 rounded-lg bg-[#0D0E12] border border-white/[0.06] text-xs text-zinc-400 space-y-1">
            <div className="flex items-center gap-1.5 text-zinc-300 font-medium">
              <Building2 className="w-3.5 h-3.5 text-zinc-400" />
              <span>Licencia Corporativa Delegada</span>
            </div>
            <p className="text-[11px] text-zinc-500">
              El acceso a esta estación local es gestionado centralmente por tu organización. Para cambios en tu cuenta contacta a tu administrador.
            </p>
          </div>
        )}

        {/* Botón de Cerrar Sesión y Aceptar */}
        <div className="pt-2 flex items-center justify-between border-t border-white/[0.06]">
          <button
            onClick={onLogout}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-rose-950/20 hover:bg-rose-950/40 text-rose-300 border border-rose-800/30 text-xs font-medium transition cursor-pointer"
          >
            <LogOut className="w-3.5 h-3.5" />
            <span>Cerrar Sesión</span>
          </button>

          <button
            onClick={onClose}
            className="px-3.5 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs transition cursor-pointer shadow-sm"
          >
            Aceptar
          </button>
        </div>

      </div>
    </div>
  );
}
