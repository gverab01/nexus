import React, { useState, useEffect } from 'react';
import { 
  Building2, 
  ShieldAlert, 
  ShieldCheck, 
  Users, 
  DollarSign, 
  RefreshCw, 
  Plus, 
  AlertTriangle, 
  CheckCircle2, 
  X, 
  TrendingUp,
  Sparkles,
  Layers,
  Calendar,
  Lock,
  ArrowUpRight
} from 'lucide-react';
import { 
  fetchTenants, 
  revokeTenantLicense, 
  reactivateTenantLicense, 
  adjustTenantSeats 
} from '../../services/api';

export default function SuperAdminView({ onEnterWorkspace }) {
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [feedback, setFeedback] = useState(null);
  const [actionLoading, setActionLoading] = useState(null);

  useEffect(() => {
    loadTenants();
  }, []);

  async function loadTenants() {
    try {
      setLoading(true);
      const data = await fetchTenants();
      setTenants(Array.isArray(data) ? data : []);
    } catch (err) {
      setFeedback({ tipo: 'error', mensaje: `Error cargando organizaciones: ${err.message}` });
    } finally {
      setLoading(false);
    }
  }

  async function handleRevokeLicense(tenantId, companyName) {
    if (!window.confirm(`¿Estás seguro de que deseas REVOCAR la licencia de "${companyName}"? Todas sus sesiones y las de sus clientes serán expulsadas de inmediato.`)) {
      return;
    }
    try {
      setActionLoading(tenantId);
      await revokeTenantLicense(tenantId, 'Revocación manual por Super Admin');
      setFeedback({ tipo: 'success', mensaje: `Licencia de "${companyName}" revocada con éxito.` });
      await loadTenants();
    } catch (err) {
      setFeedback({ tipo: 'error', mensaje: `Error al revocar: ${err.message}` });
    } finally {
      setActionLoading(null);
    }
  }

  async function handleReactivateLicense(tenantId, companyName) {
    try {
      setActionLoading(tenantId);
      await reactivateTenantLicense(tenantId, 30);
      setFeedback({ tipo: 'success', mensaje: `Licencia de "${companyName}" reactivada por 30 días.` });
      await loadTenants();
    } catch (err) {
      setFeedback({ tipo: 'error', mensaje: `Error al reactivar: ${err.message}` });
    } finally {
      setActionLoading(null);
    }
  }

  async function handleAdjustSeats(tenantId, delta) {
    try {
      setActionLoading(tenantId);
      await adjustTenantSeats(tenantId, delta);
      setFeedback({ tipo: 'success', mensaje: `Bolsa de puestos actualizada.` });
      await loadTenants();
    } catch (err) {
      setFeedback({ tipo: 'error', mensaje: `Error ajustando puestos: ${err.message}` });
    } finally {
      setActionLoading(null);
    }
  }

  // Aggregate Metrics
  const totalOrganizations = tenants.length;
  const totalSeats = tenants.reduce((acc, t) => acc + (t.puestos_contratados || 0), 0);
  const occupiedSeats = tenants.reduce((acc, t) => acc + (t.puestos_ocupados || 0), 0);
  const activeLicenses = tenants.filter(t => t.sub_estado === 'ACTIVA').length;
  const estimatedMrr = tenants.reduce((acc, t) => {
    if (t.sub_estado !== 'ACTIVA') return acc;
    const price = t.precio_unitario_plataforma || 35.0;
    const seats = t.puestos_contratados || 1;
    return acc + (price * seats);
  }, 0);

  return (
    <div className="space-y-5 select-none animate-fadeIn">
      {/* 1. Header con Resumen */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 rounded-lg bg-[#121316] border border-white/[0.07]">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-md bg-zinc-850 border border-zinc-750 flex items-center justify-center text-zinc-200 shrink-0">
            <Building2 className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-zinc-100 tracking-tight">Consola Master de Licenciamiento</h2>
              <span className="px-1.5 py-0.5 rounded text-[9px] font-mono font-medium bg-zinc-800 text-zinc-400 border border-zinc-700/60">
                SUPER ADMIN
              </span>
            </div>
            <p className="text-[11px] text-zinc-500 mt-0.5">
              Control global de organizaciones, bolsas de puestos y revocación de licencias en tiempo real
            </p>
          </div>
        </div>

        <button
          onClick={loadTenants}
          disabled={loading}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-750 border border-zinc-700/60 text-xs text-zinc-200 font-medium transition cursor-pointer self-start sm:self-auto"
        >
          <RefreshCw className={`w-3.5 h-3.5 text-zinc-400 ${loading ? 'animate-spin' : ''}`} />
          <span>Actualizar</span>
        </button>
      </div>

      {/* 2. Feedback Alert */}
      {feedback && (
        <div className={`p-3 rounded-lg border text-xs flex items-center justify-between gap-3 animate-fadeIn ${
          feedback.tipo === 'success' 
            ? 'bg-emerald-950/20 border-emerald-500/30 text-emerald-300' 
            : 'bg-rose-950/20 border-rose-500/30 text-rose-300'
        }`}>
          <div className="flex items-center gap-2">
            {feedback.tipo === 'success' ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            ) : (
              <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
            )}
            <span>{feedback.mensaje}</span>
          </div>
          <button onClick={() => setFeedback(null)} className="p-1 text-zinc-400 hover:text-zinc-200 cursor-pointer">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* 3. Tarjetas KPI Globales */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="p-3.5 rounded-lg bg-[#121316] border border-white/[0.07] space-y-1">
          <div className="text-[11px] font-medium text-zinc-400 uppercase tracking-wider flex items-center justify-between">
            <span>Organizaciones Activas</span>
            <Building2 className="w-3.5 h-3.5 text-zinc-500" />
          </div>
          <div className="text-xl font-semibold text-zinc-100 font-mono tracking-tight">
            {activeLicenses} <span className="text-xs font-normal text-zinc-500">/ {totalOrganizations}</span>
          </div>
          <p className="text-[10px] text-zinc-500">Empresas, Agencias e Individuales</p>
        </div>

        <div className="p-3.5 rounded-lg bg-[#121316] border border-white/[0.07] space-y-1">
          <div className="text-[11px] font-medium text-zinc-400 uppercase tracking-wider flex items-center justify-between">
            <span>Puestos en Operación</span>
            <Users className="w-3.5 h-3.5 text-zinc-500" />
          </div>
          <div className="text-xl font-semibold text-zinc-100 font-mono tracking-tight">
            {occupiedSeats} <span className="text-xs font-normal text-zinc-500">/ {totalSeats} seats</span>
          </div>
          <div className="w-full bg-zinc-800 h-1 rounded-full overflow-hidden mt-1.5">
            <div 
              className="bg-zinc-400 h-full rounded-full transition-all"
              style={{ width: `${totalSeats > 0 ? (occupiedSeats / totalSeats) * 100 : 0}%` }}
            />
          </div>
        </div>

        <div className="p-3.5 rounded-lg bg-[#121316] border border-white/[0.07] space-y-1">
          <div className="text-[11px] font-medium text-zinc-400 uppercase tracking-wider flex items-center justify-between">
            <span>Facturación Mensual (MRR)</span>
            <DollarSign className="w-3.5 h-3.5 text-zinc-500" />
          </div>
          <div className="text-xl font-semibold text-emerald-400 font-mono tracking-tight">
            ${estimatedMrr.toLocaleString('es-CL')} <span className="text-xs text-zinc-500 font-normal">USD/mes</span>
          </div>
          <p className="text-[10px] text-zinc-500">Ingresos directos por software</p>
        </div>

        <div className="p-3.5 rounded-lg bg-[#121316] border border-white/[0.07] space-y-1">
          <div className="text-[11px] font-medium text-zinc-400 uppercase tracking-wider flex items-center justify-between">
            <span>Seguridad & Aislamiento</span>
            <ShieldCheck className="w-3.5 h-3.5 text-zinc-500" />
          </div>
          <div className="text-xs font-medium text-zinc-300 pt-0.5 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
            <span>OWASP Multi-Tenant Activo</span>
          </div>
          <p className="text-[10px] text-zinc-500">Aislamiento estricto por tenant_id</p>
        </div>
      </div>

      {/* 4. Directorio de Tenants */}
      <div className="rounded-lg bg-[#121316] border border-white/[0.07] overflow-hidden">
        <div className="p-3.5 border-b border-white/[0.06] flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Layers className="w-3.5 h-3.5 text-zinc-400" />
            <h3 className="text-xs font-semibold text-zinc-200 uppercase tracking-wider">
              Directorio Global de Organizaciones
            </h3>
          </div>
          <span className="text-[11px] text-zinc-500 font-mono">
            {tenants.length} tenants registrados
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#0F1014] text-zinc-400 text-[10px] uppercase tracking-wider font-medium border-b border-white/[0.06]">
              <tr>
                <th className="py-2.5 px-3.5">Organización</th>
                <th className="py-2.5 px-3.5">Tipo</th>
                <th className="py-2.5 px-3.5">Puestos (Seats)</th>
                <th className="py-2.5 px-3.5">Ciclo / Tarifa</th>
                <th className="py-2.5 px-3.5">Estado Licencia</th>
                <th className="py-2.5 px-3.5 text-right">Acciones de Control</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.05]">
              {tenants.map((t) => {
                const isRevocada = t.sub_estado === 'REVOCADA';
                const isActiva = t.sub_estado === 'ACTIVA';
                const isAgency = t.tipo_tenant === 'AGENCIA';

                return (
                  <tr key={t.id} className="hover:bg-white/[0.02] transition-colors">
                    {/* Organización */}
                    <td className="py-3 px-3.5">
                      <div className="font-medium text-zinc-200">{t.razon_social}</div>
                      <div className="text-[10px] text-zinc-500 font-mono">ID: {t.id}</div>
                    </td>

                    {/* Tipo */}
                    <td className="py-3 px-3.5">
                      <span className="px-1.5 py-0.5 rounded text-[9px] font-mono font-medium bg-zinc-800 text-zinc-300 border border-zinc-700/60">
                        {t.tipo_tenant}
                      </span>
                    </td>

                    {/* Puestos */}
                    <td className="py-3 px-3.5">
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-medium text-zinc-300">
                          {t.puestos_ocupados} / {t.puestos_contratados}
                        </span>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => handleAdjustSeats(t.id, 1)}
                            disabled={actionLoading === t.id}
                            title="Añadir +1 puesto a la bolsa"
                            className="px-1.5 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 font-mono text-[10px] cursor-pointer border border-zinc-700/40"
                          >
                            +1
                          </button>
                          {t.puestos_contratados > 1 && (
                            <button
                              onClick={() => handleAdjustSeats(t.id, -1)}
                              disabled={actionLoading === t.id}
                              title="Restar -1 puesto"
                              className="px-1.5 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-400 font-mono text-[10px] cursor-pointer border border-zinc-700/40"
                            >
                              -1
                            </button>
                          )}
                        </div>
                      </div>
                    </td>

                    {/* Ciclo / Tarifa */}
                    <td className="py-3 px-3.5 font-mono text-[11px]">
                      <span className="text-zinc-300">{t.periodicidad || 'MENSUAL'}</span>
                      <div className="text-[10px] text-zinc-500">
                        ${t.precio_unitario_plataforma || 35}/seat/mes
                      </div>
                    </td>

                    {/* Estado Licencia */}
                    <td className="py-3 px-3.5">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-medium flex items-center gap-1.5 w-fit ${
                        isActiva 
                          ? 'bg-emerald-950/30 text-emerald-400 border border-emerald-500/25' 
                          : 'bg-rose-950/30 text-rose-400 border border-rose-500/25'
                      }`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${isActiva ? 'bg-emerald-400' : 'bg-rose-400'}`} />
                        {t.sub_estado || 'ACTIVA'}
                      </span>
                    </td>

                    {/* Acciones de Control */}
                    <td className="py-3 px-3.5 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        {onEnterWorkspace && (
                          <button
                            onClick={() => onEnterWorkspace(t.id, t.razon_social)}
                            className="px-2 py-1 rounded-md bg-zinc-800/80 hover:bg-zinc-700/80 text-zinc-200 border border-white/[0.08] text-xs font-medium transition cursor-pointer flex items-center gap-1"
                            title={`Entrar al workspace de ${t.razon_social} para auditar o prospectar`}
                          >
                            <ArrowUpRight className="w-3.5 h-3.5 text-zinc-400" />
                            <span>Entrar</span>
                          </button>
                        )}
                        {isActiva ? (
                          <button
                            onClick={() => handleRevokeLicense(t.id, t.razon_social)}
                            disabled={actionLoading === t.id}
                            className="px-2 py-1 rounded-md bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/20 text-xs font-medium transition cursor-pointer"
                            title="Revocar licencia inmediatamente y congelar accesos"
                          >
                            Revocar
                          </button>
                        ) : (
                          <button
                            onClick={() => handleReactivateLicense(t.id, t.razon_social)}
                            disabled={actionLoading === t.id}
                            className="px-2 py-1 rounded-md bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 border border-emerald-500/20 text-xs font-medium transition cursor-pointer"
                            title="Reactivar licencia por 30 días"
                          >
                            Reactivar
                          </button>
                        )}
                      </div>
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

