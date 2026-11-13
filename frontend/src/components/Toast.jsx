import React, { useEffect, useState } from 'react';
import { CheckCircle2, AlertTriangle, Info, X, ArrowRight } from 'lucide-react';

const TOAST_EVENT_NAME = 'nexusreach-toast';

/**
 * Emite una notificación toast no bloqueante desde cualquier componente o servicio.
 * @param {string} message - Mensaje principal
 * @param {'success'|'error'|'info'|'warning'} [type='info'] - Tipo semántico
 * @param {{ label: string, onClick: Function }|null} [action=null] - Botón de acción opcional
 * @param {number} [duration=5000] - Duración en ms (0 = persistente hasta cerrar)
 */
export function showToast(message, type = 'info', action = null, duration = 5000) {
  window.dispatchEvent(
    new CustomEvent(TOAST_EVENT_NAME, {
      detail: {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        message,
        type,
        action,
        duration,
      },
    })
  );
}

export default function ToastContainer() {
  const [toasts, setToasts] = useState([]);

  useEffect(() => {
    function handleAddToast(e) {
      const toast = e.detail;
      if (!toast?.message) return;

      setToasts((prev) => [...prev.slice(-3), toast]);

      if (toast.duration > 0) {
        setTimeout(() => {
          setToasts((prev) => prev.filter((t) => t.id !== toast.id));
        }, toast.duration);
      }
    }

    window.addEventListener(TOAST_EVENT_NAME, handleAddToast);
    return () => window.removeEventListener(TOAST_EVENT_NAME, handleAddToast);
  }, []);

  if (toasts.length === 0) return null;

  const stylesByType = {
    success: {
      container: 'bg-[#141A17] border-emerald-500/40 text-emerald-100',
      icon: <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />,
    },
    error: {
      container: 'bg-[#1B1315] border-rose-500/40 text-rose-100',
      icon: <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />,
    },
    warning: {
      container: 'bg-[#1A1711] border-amber-500/40 text-amber-100',
      icon: <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />,
    },
    info: {
      container: 'bg-[#14171F] border-blue-500/40 text-zinc-100',
      icon: <Info className="w-4 h-4 text-blue-400 shrink-0 mt-0.5" />,
    },
  };

  return (
    <div
      aria-live="polite"
      className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none px-4 sm:px-0"
    >
      {toasts.map((toast) => {
        const style = stylesByType[toast.type] || stylesByType.info;
        return (
          <div
            key={toast.id}
            role="status"
            className={`pointer-events-auto rounded-xl border p-3.5 shadow-2xl shadow-black/60 backdrop-blur-sm flex items-start gap-3 transition-all ${style.container}`}
          >
            {style.icon}
            <div className="flex-1 min-w-0 space-y-2">
              <p className="text-xs leading-relaxed whitespace-pre-line font-medium">
                {toast.message}
              </p>
              {toast.action?.label && (
                <button
                  type="button"
                  onClick={() => {
                    toast.action.onClick?.();
                    setToasts((prev) => prev.filter((t) => t.id !== toast.id));
                  }}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/10 hover:bg-white/20 text-white text-xs font-medium transition cursor-pointer"
                >
                  <span>{toast.action.label}</span>
                  <ArrowRight className="w-3 h-3" />
                </button>
              )}
            </div>
            <button
              type="button"
              onClick={() => setToasts((prev) => prev.filter((t) => t.id !== toast.id))}
              className="p-1 rounded-md text-zinc-400 hover:text-white hover:bg-white/10 transition cursor-pointer shrink-0"
              aria-label="Cerrar notificación"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}

