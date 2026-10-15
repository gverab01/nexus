import React, { useState, useEffect } from 'react';
import { 
  Building2, 
  Users, 
  DollarSign, 
  RefreshCw, 
  TrendingUp, 
  Sparkles, 
  Layers, 
  Calendar, 
  Clock, 
  ArrowUpRight,
  Briefcase,
  User,
  ShieldCheck,
  AlertCircle,
  CreditCard,
  CheckCircle2,
  ChevronRight
} from 'lucide-react';
import { fetchTenants } from '../../services/api';

function formatFecha(fechaIso) {
  if (!fechaIso) return '—';
  try {
    const d = new Date(fechaIso);
    if (isNaN(d.getTime())) return fechaIso;
    return d.toLocaleDateString('es-CL', {
      day: '2-digit',
      month: 'short',
      year: 'numeric'
    });
  } catch {
    return fechaIso;
  }
}

export default function SuperAdminView({ onEnterWorkspace, onNavigateToClients }) {
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [feedback, setFeedback] = useState(null);

  useEffect(() => {
    loadTenants();
  }, []);

  async function loadTenants() {
    try {
      setLoading(true);
      const data = await fetchTenants();
      // Filtrar cuenta técnica de sistema
      const clientesReales = (Array.isArray(data) ? data : []).filter(t => t.id !== 'ten_superadmin');
      setTenants(clientesReales);
    } catch (err) {
      setFeedback({ tipo: 'error', mensaje: `Error cargando métricas: ${err.message}` });
    } finally {
      setLoading(false);
    }
  }

  // Segmentación
  const empresas = tenants.filter(t => t.tipo_tenant === 'EMPRESA');
  const freelancers = tenants.filter(t => t.tipo_tenant === 'INDIVIDUAL' || t.tipo_tenant === 'FREELANCER');
  const agencias = tenants.filter(t => t.tipo_tenant === 'AGENCIA');

  // Puestos
  const totalSeats = tenants.reduce((acc, t) => acc + (t.puestos_contratados || 0), 0);
  const occupiedSeats = tenants.reduce((acc, t) => acc + (t.puestos_ocupados || 0), 0);

  // Ingresos por modalidad
  const mrrEmpresas = empresas.reduce((acc, t) => acc + (t.monto_mensual ?? ((t.precio_unitario_plataforma || 35) * (t.puestos_contratados || 1))), 0);
  const mrrFreelancers = freelancers.reduce((acc, t) => acc + (t.monto_mensual ?? ((t.precio_unitario_plataforma || 35) * (t.puestos_contratados || 1))), 0);
  const mrrAgencias = agencias.reduce((acc, t) => acc + (t.monto_mensual ?? ((t.precio_unitario_plataforma || 35) * (t.puestos_contratados || 1))), 0);
  const totalMrr = mrrEmpresas + mrrFreelancers + mrrAgencias;
  const totalArr = totalMrr * 12;

  // Próximas renovaciones ordenadas por fecha más cercana
  const proximasRenovaciones = [...tenants].sort((a, b) => {
    const da = a.dias_restantes ?? 999;
    const db = b.dias_restantes ?? 999;
    return da - db;
  });

  return (
    <div className="space-y-6 select-none animate-fadeIn">
      {/* 1. Header con Resumen Ejecutivo y Acceso Rápido a Clientes */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 rounded-xl bg-[#121316] border border-white/[0.07]">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-zinc-100 tracking-tight">
              Dashboard de Gestión de Plataforma
            </h2>
            <span className="px-2 py-0.5 rounded-full text-[10px] font-mono font-medium bg-emerald-950/40 text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              SISTEMA OPERATIVO
            </span>
          </div>
          <p className="text-xs text-zinc-400">
            Supervisión integral de facturación recurrente, capacidad de puestos y clientes en plataforma
          </p>
        </div>

        <div className="flex items-center gap-2">
          {onNavigateToClients && (
            <button
              onClick={onNavigateToClients}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 border border-white/[0.1] text-xs font-medium text-zinc-200 transition cursor-pointer"
            >
              <Users className="w-3.5 h-3.5 text-zinc-300" />
              <span>Ver Directorio de Clientes</span>
              <ChevronRight className="w-3.5 h-3.5 text-zinc-400" />
            </button>
          )}

          <button
            onClick={loadTenants}
            disabled={loading}
            title="Recargar métricas"
            className="p-1.5 rounded-lg bg-zinc-850 hover:bg-zinc-800 border border-zinc-750 text-zinc-400 hover:text-zinc-200 transition cursor-pointer"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-zinc-200' : ''}`} />
          </button>
        </div>
      </div>

      {/* 2. Tarjetas KPI Principales */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
        {/* MRR */}
        <div className="p-4 rounded-xl bg-[#121316] border border-white/[0.07] space-y-2">
          <div className="text-[11px] font-medium text-zinc-400 uppercase tracking-wider flex items-center justify-between">
            <span>Facturación Mensual (MRR)</span>
            <DollarSign className="w-3.5 h-3.5 text-emerald-400" />
          </div>
          <div className="text-2xl font-semibold text-emerald-400 font-mono tracking-tight">
            ${totalMrr.toLocaleString('es-CL')} <span className="text-xs text-zinc-500 font-normal">USD/mes</span>
          </div>
          <div className="text-[10px] text-zinc-500 font-mono">
            Proyección anual: ${totalArr.toLocaleString('es-CL')} USD
          </div>
        </div>

        {/* Clientes Activos */}
        <div className="p-4 rounded-xl bg-[#121316] border border-white/[0.07] space-y-2">
          <div className="text-[11px] font-medium text-zinc-400 uppercase tracking-wider flex items-center justify-between">
            <span>Clientes Registrados</span>
            <Users className="w-3.5 h-3.5 text-sky-400" />
          </div>
          <div className="text-2xl font-semibold text-zinc-100 font-mono tracking-tight">
            {tenants.length} <span className="text-xs text-zinc-500 font-normal">cuentas</span>
          </div>
          <div className="text-[10px] text-zinc-400 flex items-center gap-1.5 truncate">
            <span>{empresas.length} empresas</span> &bull; 
            <span>{freelancers.length} freelance</span> &bull; 
            <span>{agencias.length} agencias</span>
          </div>
        </div>

        {/* Puestos / Seats */}
        <div className="p-4 rounded-xl bg-[#121316] border border-white/[0.07] space-y-2">
          <div className="text-[11px] font-medium text-zinc-400 uppercase tracking-wider flex items-center justify-between">
            <span>Puestos en Operación</span>
            <Layers className="w-3.5 h-3.5 text-purple-400" />
          </div>
          <div className="text-2xl font-semibold text-zinc-100 font-mono tracking-tight">
            {occupiedSeats} <span className="text-xs text-zinc-500 font-normal">/ {totalSeats} seats</span>
          </div>
          <div className="w-full bg-zinc-800 h-1.5 rounded-full overflow-hidden">
            <div 
              className="bg-purple-400 h-full rounded-full transition-all"
              style={{ width: `${totalSeats > 0 ? (occupiedSeats / totalSeats) * 100 : 0}%` }}
            />
          </div>
        </div>

        {/* Salud de Cobranza */}
        <div className="p-4 rounded-xl bg-[#121316] border border-white/[0.07] space-y-2">
          <div className="text-[11px] font-medium text-zinc-400 uppercase tracking-wider flex items-center justify-between">
            <span>Salud de Licencias</span>
            <ShieldCheck className="w-3.5 h-3.5 text-zinc-400" />
          </div>
          <div className="text-2xl font-semibold text-zinc-100 font-mono tracking-tight flex items-center gap-2">
            <span>100%</span>
            <span className="text-xs font-normal text-emerald-400 px-1.5 py-0.2 rounded bg-emerald-950/40 border border-emerald-500/30">
              AL DÍA
            </span>
          </div>
          <div className="text-[10px] text-zinc-500">
            Todas las cuentas con cobros activos
          </div>
        </div>
      </div>

      {/* 3. Desglose de Modalidades de Clientes */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold text-zinc-300 uppercase tracking-wider flex items-center gap-2">
            <span>Segmentación de Clientes por Modalidad</span>
          </h3>
          <span className="text-[11px] text-zinc-500">
            Modelos de venta del software
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5">
          {/* Tarjeta Empresas */}
          <div className="p-4 rounded-xl bg-[#121316] border border-white/[0.07] space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-sky-950/30 border border-sky-500/30 text-sky-400 flex items-center justify-center">
                  <Building2 className="w-3.5 h-3.5" />
                </div>
                <div>
                  <h4 className="text-xs font-semibold text-zinc-200">Empresas</h4>
                  <p className="text-[10px] text-zinc-500">Con puestos operadores</p>
                </div>
              </div>
              <span className="text-xs font-mono font-semibold text-zinc-200 px-2 py-0.5 rounded bg-zinc-800">
                {empresas.length}
              </span>
            </div>

            <div className="pt-2 border-t border-white/[0.05] flex items-center justify-between text-xs font-mono">
              <span className="text-zinc-500">Aporte MRR:</span>
              <span className="font-semibold text-emerald-400">${mrrEmpresas.toLocaleString('es-CL')} USD</span>
            </div>

            <div className="text-[11px] text-zinc-400 leading-snug">
              Cuentas corporativas con múltiples vendedores u operadores asignados.
            </div>

            {onNavigateToClients && (
              <button
                onClick={onNavigateToClients}
                className="w-full mt-1 py-1.5 px-3 rounded-lg bg-zinc-850 hover:bg-zinc-800 border border-zinc-750 text-xs text-zinc-300 hover:text-zinc-100 transition cursor-pointer flex items-center justify-center gap-1.5"
              >
                <span>Administrar Empresas</span>
                <ChevronRight className="w-3 h-3 text-zinc-400" />
              </button>
            )}
          </div>

          {/* Tarjeta Freelancers */}
          <div className="p-4 rounded-xl bg-[#121316] border border-white/[0.07] space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-purple-950/30 border border-purple-500/30 text-purple-400 flex items-center justify-center">
                  <User className="w-3.5 h-3.5" />
                </div>
                <div>
                  <h4 className="text-xs font-semibold text-zinc-200">Freelancers</h4>
                  <p className="text-[10px] text-zinc-500">Consultores independientes</p>
                </div>
              </div>
              <span className="text-xs font-mono font-semibold text-zinc-200 px-2 py-0.5 rounded bg-zinc-800">
                {freelancers.length}
              </span>
            </div>

            <div className="pt-2 border-t border-white/[0.05] flex items-center justify-between text-xs font-mono">
              <span className="text-zinc-500">Aporte MRR:</span>
              <span className="font-semibold text-emerald-400">${mrrFreelancers.toLocaleString('es-CL')} USD</span>
            </div>

            <div className="text-[11px] text-zinc-400 leading-snug">
              Profesionales que prospectan para su propia cartera individual.
            </div>

            {onNavigateToClients && (
              <button
                onClick={onNavigateToClients}
                className="w-full mt-1 py-1.5 px-3 rounded-lg bg-zinc-850 hover:bg-zinc-800 border border-zinc-750 text-xs text-zinc-300 hover:text-zinc-100 transition cursor-pointer flex items-center justify-center gap-1.5"
              >
                <span>Administrar Freelancers</span>
                <ChevronRight className="w-3 h-3 text-zinc-400" />
              </button>
            )}
          </div>

          {/* Tarjeta Agencias */}
          <div className="p-4 rounded-xl bg-[#121316] border border-white/[0.07] space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-amber-950/30 border border-amber-500/30 text-amber-400 flex items-center justify-center">
                  <Briefcase className="w-3.5 h-3.5" />
                </div>
                <div>
                  <h4 className="text-xs font-semibold text-zinc-200">Agencias</h4>
                  <p className="text-[10px] text-zinc-500">Multi-Workspace & Seats</p>
                </div>
              </div>
              <span className="text-xs font-mono font-semibold text-zinc-200 px-2 py-0.5 rounded bg-zinc-800">
                {agencias.length}
              </span>
            </div>

            <div className="pt-2 border-t border-white/[0.05] flex items-center justify-between text-xs font-mono">
              <span className="text-zinc-500">Aporte MRR:</span>
              <span className="font-semibold text-emerald-400">${mrrAgencias.toLocaleString('es-CL')} USD</span>
            </div>

            <div className="text-[11px] text-zinc-400 leading-snug">
              Agencias de outbound B2B gestionando carteras de clientes sub-tenants.
            </div>

            {onNavigateToClients && (
              <button
                onClick={onNavigateToClients}
                className="w-full mt-1 py-1.5 px-3 rounded-lg bg-zinc-850 hover:bg-zinc-800 border border-zinc-750 text-xs text-zinc-300 hover:text-zinc-100 transition cursor-pointer flex items-center justify-center gap-1.5"
              >
                <span>Administrar Agencias</span>
                <ChevronRight className="w-3 h-3 text-zinc-400" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 4. Widget de Próximas Facturaciones y Renovaciones */}
      <div className="rounded-xl bg-[#121316] border border-white/[0.07] overflow-hidden shadow-xs">
        <div className="p-3.5 border-b border-white/[0.06] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock className="w-3.5 h-3.5 text-zinc-400" />
            <h3 className="text-xs font-semibold text-zinc-200 uppercase tracking-wider">
              Próximas Facturaciones del Mes
            </h3>
          </div>
          <span className="text-[11px] font-mono text-zinc-500">
            {tenants.length} cuentas en calendario
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#0F1014] text-zinc-400 text-[10px] uppercase tracking-wider font-medium border-b border-white/[0.06]">
              <tr>
                <th className="py-2.5 px-3.5">Cliente</th>
                <th className="py-2.5 px-3.5">Correo de Registro</th>
                <th className="py-2.5 px-3.5">Modalidad</th>
                <th className="py-2.5 px-3.5">Fecha de Cobro</th>
                <th className="py-2.5 px-3.5">Días Restantes</th>
                <th className="py-2.5 px-3.5 text-right">Monto a Facturar</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.05]">
              {proximasRenovaciones.map((t) => {
                const monto = t.monto_mensual !== undefined 
                  ? t.monto_mensual 
                  : ((t.precio_unitario_plataforma || 35) * (t.puestos_contratados || 1));
                const dias = t.dias_restantes ?? 0;

                return (
                  <tr key={t.id} className="hover:bg-white/[0.02] transition-colors">
                    <td className="py-2.5 px-3.5 font-medium text-zinc-200">
                      {t.razon_social}
                    </td>
                    <td className="py-2.5 px-3.5 font-mono text-zinc-400 text-[11px]">
                      {t.admin_email || '—'}
                    </td>
                    <td className="py-2.5 px-3.5">
                      <span className="px-1.5 py-0.5 rounded text-[9px] font-mono font-medium bg-zinc-800 text-zinc-300 border border-zinc-700/60">
                        {t.tipo_tenant}
                      </span>
                    </td>
                    <td className="py-2.5 px-3.5 font-mono text-zinc-300">
                      {formatFecha(t.fecha_expiracion)}
                    </td>
                    <td className="py-2.5 px-3.5 font-mono">
                      {dias > 5 ? (
                        <span className="text-emerald-400 text-[11px]">En {dias} días</span>
                      ) : (
                        <span className="text-amber-400 text-[11px]">En {dias} días</span>
                      )}
                    </td>
                    <td className="py-2.5 px-3.5 text-right font-mono font-semibold text-emerald-400">
                      ${monto.toLocaleString('es-CL')} USD
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
