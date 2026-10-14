import React, { useState } from 'react';
import { 
  ShieldCheck, 
  Lock, 
  Mail, 
  Eye, 
  EyeOff, 
  ArrowRight, 
  AlertTriangle, 
  ShieldAlert
} from 'lucide-react';
import { loginUser } from '../../services/api';

export default function LoginView({ onLoginSuccess }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorInfo, setErrorInfo] = useState(null);

  async function handleSubmit(e) {
    if (e) e.preventDefault();
    if (!email.trim() || !password) {
      setErrorInfo({
        tipo: 'error',
        mensaje: 'Por favor completa todos los campos para continuar.'
      });
      return;
    }

    try {
      setLoading(true);
      setErrorInfo(null);
      const res = await loginUser(email.trim(), password);
      if (res?.exito && res?.usuario) {
        onLoginSuccess(res.usuario);
      } else {
        setErrorInfo({
          tipo: 'error',
          mensaje: res?.mensaje || 'Error de validación al iniciar sesión.'
        });
      }
    } catch (err) {
      const isSubscriptionError = 
        err.message?.toLowerCase().includes('suscripci') || 
        err.data?.detail?.codigo?.includes('SUSCRIPCION') ||
        err.status === 403;

      setErrorInfo({
        tipo: isSubscriptionError ? 'subscription' : 'error',
        mensaje: err.message || 'No se pudo conectar con el servidor de autenticación.'
      });
    } finally {
      setLoading(false);
    }
  }

  function handleAutoFill(demoEmail, demoPass) {
    setEmail(demoEmail);
    setPassword(demoPass);
    setErrorInfo(null);
  }

  return (
    <div className="relative min-h-screen w-full bg-[#090A0C] text-zinc-100 flex items-center justify-center p-4 sm:p-6 select-none font-sans">
      {/* Central Login Card - Linear/Subframe style */}
      <div className="relative w-full max-w-[380px] z-10">
        <div className="rounded-xl border border-white/[0.08] bg-[#121316] p-7 shadow-2xl shadow-black/80 space-y-6">
          
          {/* Header con Emblem minimalista */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="w-9 h-9 rounded-lg bg-zinc-900 border border-white/[0.1] flex items-center justify-center shadow-inner">
                <span className="text-zinc-100 font-semibold text-xs tracking-tight">NR</span>
              </div>
              <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-mono text-zinc-400 bg-white/[0.03] border border-white/[0.06]">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                <span>v2.4 stable</span>
              </div>
            </div>

            <div>
              <h1 className="text-base font-medium tracking-tight text-zinc-100">
                Iniciar sesión en NexusReach
              </h1>
              <p className="text-xs text-zinc-400 mt-1 leading-relaxed">
                Ingresa tus credenciales autorizadas para acceder al workspace
              </p>
            </div>
          </div>

          {/* Formulario */}
          <form onSubmit={handleSubmit} className="space-y-3.5">
            {/* Input Correo */}
            <div className="space-y-1.5">
              <label className="block text-[11px] font-medium text-zinc-400 tracking-tight">
                Correo corporativo
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-zinc-500">
                  <Mail className="w-3.5 h-3.5" />
                </div>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="nombre@empresa.com"
                  autoComplete="email"
                  required
                  className="w-full pl-9 pr-3 py-2 bg-[#0D0E12] border border-white/[0.08] rounded-md text-xs text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500/20 transition font-sans"
                />
              </div>
            </div>

            {/* Input Contraseña */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="block text-[11px] font-medium text-zinc-400 tracking-tight">
                  Contraseña
                </label>
              </div>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-zinc-500">
                  <Lock className="w-3.5 h-3.5" />
                </div>
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  autoComplete="current-password"
                  required
                  className="w-full pl-9 pr-9 py-2 bg-[#0D0E12] border border-white/[0.08] rounded-md text-xs text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500/20 transition font-sans"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 pr-2.5 flex items-center text-zinc-500 hover:text-zinc-300 transition cursor-pointer"
                  title={showPassword ? 'Ocultar contraseña' : 'Ver contraseña'}
                >
                  {showPassword ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>

            {/* Alerta de Error / Notificación de Suscripción */}
            {errorInfo && (
              <div className={`p-2.5 rounded-md border text-xs flex items-start gap-2 ${
                errorInfo.tipo === 'subscription'
                  ? 'bg-amber-950/20 border-amber-500/30 text-amber-200'
                  : 'bg-rose-950/20 border-rose-500/30 text-rose-200'
              }`}>
                {errorInfo.tipo === 'subscription' ? (
                  <ShieldAlert className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
                ) : (
                  <AlertTriangle className="w-3.5 h-3.5 text-rose-400 shrink-0 mt-0.5" />
                )}
                <div className="text-[11px] leading-relaxed">
                  <span className="font-medium block">
                    {errorInfo.tipo === 'subscription' ? 'Aviso de suscripción' : 'Error de autenticación'}
                  </span>
                  {errorInfo.mensaje}
                </div>
              </div>
            )}

            {/* Botón Principal de Acceso (Linear solid white) */}
            <button
              type="submit"
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 py-2 px-4 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs transition duration-150 shadow-sm cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed mt-2"
            >
              {loading ? (
                <>
                  <div className="w-3.5 h-3.5 border-2 border-zinc-950/30 border-t-zinc-950 rounded-full animate-spin" />
                  <span>Validando...</span>
                </>
              ) : (
                <>
                  <span>Continuar</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </>
              )}
            </button>
          </form>

          {/* Accesos rápidos minimalistas */}
          <div className="pt-3 border-t border-white/[0.06] space-y-2">
            <div className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">
              Acceso rápido para testing
            </div>
            
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => handleAutoFill('demo@nexusreach.com', 'demo123')}
                className="p-2 rounded-md bg-[#0D0E12] hover:bg-zinc-800/40 border border-white/[0.06] hover:border-white/[0.12] transition text-left cursor-pointer flex flex-col gap-0.5"
              >
                <span className="text-[11px] font-medium text-zinc-200">Operador Demo</span>
                <span className="text-[10px] text-zinc-500 font-mono">Plan Pro</span>
              </button>

              <button
                type="button"
                onClick={() => handleAutoFill('admin@nexusreach.com', 'admin123')}
                className="p-2 rounded-md bg-[#0D0E12] hover:bg-zinc-800/40 border border-white/[0.06] hover:border-white/[0.12] transition text-left cursor-pointer flex flex-col gap-0.5"
              >
                <span className="text-[11px] font-medium text-zinc-200">Superadmin</span>
                <span className="text-[10px] text-zinc-500 font-mono">Master Root</span>
              </button>
            </div>
          </div>

          {/* Pie de seguridad */}
          <div className="flex items-center justify-center gap-1.5 text-[10px] text-zinc-600 font-mono">
            <ShieldCheck className="w-3 h-3 text-zinc-500" />
            <span>Encriptación TLS & Aislamiento Tenant</span>
          </div>

        </div>
      </div>
    </div>
  );
}
