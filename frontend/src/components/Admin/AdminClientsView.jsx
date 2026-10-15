import React, { useState, useEffect } from 'react';
import { 
  Building2, 
  Users, 
  DollarSign, 
  RefreshCw, 
  AlertTriangle, 
  CheckCircle2, 
  X, 
  ArrowUpRight,
  Search,
  Mail,
  Calendar,
  Clock,
  Briefcase,
  User,
  ShieldCheck,
  ShieldAlert,
  Copy,
  Check,
  Layers,
  Sparkles,
  UserPlus
} from 'lucide-react';
import { 
  fetchTenants, 
  revokeTenantLicense, 
  reactivateTenantLicense, 
  adjustTenantSeats 
} from '../../services/api';

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

export default function AdminClientsView({ onEnterWorkspace, onNavigateToCreateAccount }) {
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [feedback, setFeedback] = useState(null);
  const [actionLoading, setActionLoading] = useState(null);
  const [filtroTipo, setFiltroTipo] = useState('TODOS');
  const [busqueda, setBusqueda] = useState('');
  const [copiedEmail, setCopiedEmail] = useState(null);

  useEffect(() => {
    loadTenants();
  }, []);

  async function loadTenants() {
    try {
      setLoading(true);
      const data = await fetchTenants();
      // Filtramos la cuenta del sistema ten_superadmin para que solo aparezcan clientes reales
      const clientesReales = (Array.isArray(data) ? data : []).filter(t => t.id !== 'ten_superadmin');
      setTenants(clientesReales);
    } catch (err) {
      setFeedback({ tipo: 'error', mensaje: `Error cargando clientes: ${err.message}` });
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

  function handleCopy(email) {
    if (!email) return;
    navigator.clipboard.writeText(email);
    setCopiedEmail(email);
    setTimeout(() => setCopiedEmail(null), 2000);
  }

  // Conteo de clientes por modalidad
  const totalEmpresas = tenants.filter(t => t.tipo_tenant === 'EMPRESA').length;
  const totalFreelancers = tenants.filter(t => t.tipo_tenant === 'INDIVIDUAL' || t.tipo_tenant === 'FREELANCER').length;
  const totalAgencias = tenants.filter(t => t.tipo_tenant === 'AGENCIA').length;

  // Filtrado de la lista
  const filteredTenants = tenants.filter(t => {
    // Filtro por tipo
    if (filtroTipo === 'EMPRESA' && t.tipo_tenant !== 'EMPRESA') return false;
    if (filtroTipo === 'FREELANCER' && t.tipo_tenant !== 'INDIVIDUAL' && t.tipo_tenant !== 'FREELANCER') return false;
    if (filtroTipo === 'AGENCIA' && t.tipo_tenant !== 'AGENCIA') return false;

    // Filtro por búsqueda
    if (busqueda.trim()) {
      const q = busqueda.toLowerCase();
      const matchName = (t.razon_social || '').toLowerCase().includes(q);
      const matchEmail = (t.admin_email || '').toLowerCase().includes(q);
      const matchId = (t.id || '').toLowerCase().includes(q);
      return matchName || matchEmail || matchId;
    }
    return true;
  });

  return (
    <div className="space-y-5 select-none animate-fadeIn">
      {/* 1. Header con Título, Contador y Buscador */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-zinc-100 tracking-tight flex items-center gap-2">
            <span>Directorio de Clientes de la Plataforma</span>
            <span className="text-xs font-mono font-medium px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-300 border border-zinc-700/60">
              {tenants.length} cuentas registradas
            </span>
          </h2>
          <p className="text-xs text-zinc-400 mt-0.5">
            Empresas con operadores, Consultores Freelancers y Agencias con subcuentas
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* Buscador */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
            <input
              type="text"
              placeholder="Buscar por cuenta o correo..."
              value={busqueda}
              onChange={(e) => setBusqueda(e.target.value)}
              className="pl-8 pr-3 py-1.5 rounded-lg bg-zinc-900 border border-white/[0.08] text-xs text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 w-56 transition"
            />
          </div>

          <button
            onClick={loadTenants}
            disabled={loading}
            title="Refrescar lista"
            className="p-2 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-white/[0.08] text-zinc-400 hover:text-zinc-200 transition cursor-pointer"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-zinc-200' : ''}`} />
          </button>

          {onNavigateToCreateAccount && (
            <button
              onClick={onNavigateToCreateAccount}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-zinc-950 font-semibold text-xs transition cursor-pointer shadow-xs ml-1"
            >
              <UserPlus className="w-3.5 h-3.5" />
              <span>+ Crear Cuenta</span>
            </button>
          )}
        </div>
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

      {/* 3. Selector de Pestañas / Filtros de Segmento */}
      <div className="flex items-center gap-1.5 p-1 rounded-xl bg-zinc-900/60 border border-white/[0.06] w-fit">
        <button
          onClick={() => setFiltroTipo('TODOS')}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition cursor-pointer flex items-center gap-2 ${
            filtroTipo === 'TODOS'
              ? 'bg-zinc-800 text-zinc-100 shadow-xs border border-white/[0.08]'
              : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40'
          }`}
        >
          <span>Todos</span>
          <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-zinc-700/60 text-zinc-300">
            {tenants.length}
          </span>
        </button>

        <button
          onClick={() => setFiltroTipo('EMPRESA')}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition cursor-pointer flex items-center gap-2 ${
            filtroTipo === 'EMPRESA'
              ? 'bg-zinc-800 text-zinc-100 shadow-xs border border-white/[0.08]'
              : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40'
          }`}
        >
          <Building2 className="w-3.5 h-3.5 text-sky-400" />
          <span>Empresas con Operadores</span>
          <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-zinc-700/60 text-zinc-300">
            {totalEmpresas}
          </span>
        </button>

        <button
          onClick={() => setFiltroTipo('FREELANCER')}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition cursor-pointer flex items-center gap-2 ${
            filtroTipo === 'FREELANCER'
              ? 'bg-zinc-800 text-zinc-100 shadow-xs border border-white/[0.08]'
              : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40'
          }`}
        >
          <User className="w-3.5 h-3.5 text-purple-400" />
          <span>Freelancers</span>
          <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-zinc-700/60 text-zinc-300">
            {totalFreelancers}
          </span>
        </button>

        <button
          onClick={() => setFiltroTipo('AGENCIA')}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition cursor-pointer flex items-center gap-2 ${
            filtroTipo === 'AGENCIA'
              ? 'bg-zinc-800 text-zinc-100 shadow-xs border border-white/[0.08]'
              : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40'
          }`}
        >
          <Briefcase className="w-3.5 h-3.5 text-amber-400" />
          <span>Agencias</span>
          <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-zinc-700/60 text-zinc-300">
            {totalAgencias}
          </span>
        </button>
      </div>

      {/* 4. Tabla Detallada de Clientes */}
      <div className="rounded-lg bg-[#121316] border border-white/[0.07] overflow-hidden shadow-xs">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#0F1014] text-zinc-400 text-[10px] uppercase tracking-wider font-medium border-b border-white/[0.06]">
              <tr>
                <th className="py-3 px-3.5">Nombre de la Cuenta</th>
                <th className="py-3 px-3.5">Correo de Registro</th>
                <th className="py-3 px-3.5">Tipo & Modalidad</th>
                <th className="py-3 px-3.5">Fecha Registro</th>
                <th className="py-3 px-3.5">Próxima Facturación</th>
                <th className="py-3 px-3.5">Facturación Mensual</th>
                <th className="py-3 px-3.5">Estado</th>
                <th className="py-3 px-3.5 text-right">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.05]">
              {filteredTenants.length === 0 ? (
                <tr>
                  <td colSpan="8" className="py-8 text-center text-zinc-500">
                    No se encontraron clientes que coincidan con los criterios.
                  </td>
                </tr>
              ) : (
                filteredTenants.map((t) => {
                  const isActiva = t.sub_estado === 'ACTIVA' || t.estado === 'ACTIVO';
                  const isAgency = t.tipo_tenant === 'AGENCIA';
                  const isFreelancer = t.tipo_tenant === 'INDIVIDUAL' || t.tipo_tenant === 'FREELANCER';
                  const isCompany = t.tipo_tenant === 'EMPRESA';
                  const email = t.admin_email || 'sin-registro@correo.com';
                  const diasRestantes = t.dias_restantes ?? 0;

                  // Monto mensual calculado
                  const monto = t.monto_mensual !== undefined 
                    ? t.monto_mensual 
                    : ((t.precio_unitario_plataforma || 35) * (t.puestos_contratados || 1));

                  return (
                    <tr key={t.id} className="hover:bg-white/[0.02] transition-colors">
                      {/* 1. Nombre de la Cuenta */}
                      <td className="py-3 px-3.5">
                        <div className="flex items-center gap-2.5">
                          <div className={`w-7 h-7 rounded-md flex items-center justify-center shrink-0 border ${
                            isAgency 
                              ? 'bg-amber-950/20 border-amber-500/30 text-amber-400'
                              : isCompany
                              ? 'bg-sky-950/20 border-sky-500/30 text-sky-400'
                              : 'bg-purple-950/20 border-purple-500/30 text-purple-400'
                          }`}>
                            {isAgency ? (
                              <Briefcase className="w-3.5 h-3.5" />
                            ) : isCompany ? (
                              <Building2 className="w-3.5 h-3.5" />
                            ) : (
                              <User className="w-3.5 h-3.5" />
                            )}
                          </div>
                          <div className="min-w-0">
                            <div className="font-medium text-zinc-200 truncate">{t.razon_social}</div>
                            <div className="text-[10px] text-zinc-500 font-mono">ID: {t.id}</div>
                          </div>
                        </div>
                      </td>

                      {/* 2. Correo de Registro */}
                      <td className="py-3 px-3.5">
                        <div className="flex items-center gap-1.5">
                          <Mail className="w-3 h-3 text-zinc-500 shrink-0" />
                          <span className="font-mono text-zinc-300 truncate max-w-[170px]" title={email}>
                            {email}
                          </span>
                          <button
                            onClick={() => handleCopy(email)}
                            className="p-1 rounded hover:bg-zinc-800 text-zinc-500 hover:text-zinc-200 transition cursor-pointer"
                            title="Copiar correo"
                          >
                            {copiedEmail === email ? (
                              <Check className="w-3 h-3 text-emerald-400" />
                            ) : (
                              <Copy className="w-3 h-3" />
                            )}
                          </button>
                        </div>
                        {t.admin_nombre && (
                          <div className="text-[10px] text-zinc-500 mt-0.5 truncate max-w-[170px]">
                            {t.admin_nombre}
                          </div>
                        )}
                      </td>

                      {/* 3. Tipo & Modalidad */}
                      <td className="py-3 px-3.5">
                        {isCompany && (
                          <div className="space-y-0.5">
                            <span className="px-1.5 py-0.5 rounded text-[9px] font-mono font-medium bg-sky-950/30 text-sky-300 border border-sky-500/30 inline-block">
                              EMPRESA
                            </span>
                            <div className="text-[10px] text-zinc-400 font-mono">
                              {t.puestos_ocupados || 1} / {t.puestos_contratados || 1} puestos
                            </div>
                          </div>
                        )}

                        {isFreelancer && (
                          <div className="space-y-0.5">
                            <span className="px-1.5 py-0.5 rounded text-[9px] font-mono font-medium bg-purple-950/30 text-purple-300 border border-purple-500/30 inline-block">
                              FREELANCER
                            </span>
                            <div className="text-[10px] text-zinc-500 font-mono">
                              Puesto Individual
                            </div>
                          </div>
                        )}

                        {isAgency && (
                          <div className="space-y-0.5">
                            <span className="px-1.5 py-0.5 rounded text-[9px] font-mono font-medium bg-amber-950/30 text-amber-300 border border-amber-500/30 inline-block">
                              AGENCIA
                            </span>
                            <div className="text-[10px] text-zinc-400 font-mono">
                              {t.sub_clientes_count || 0} sub-cuentas &bull; {t.puestos_contratados || 1} seats
                            </div>
                          </div>
                        )}
                      </td>

                      {/* 4. Fecha de Registro */}
                      <td className="py-3 px-3.5 font-mono text-[11px] text-zinc-300">
                        <div className="flex items-center gap-1.5">
                          <Calendar className="w-3 h-3 text-zinc-500 shrink-0" />
                          <span>{formatFecha(t.created_at)}</span>
                        </div>
                      </td>

                      {/* 5. Próxima Facturación */}
                      <td className="py-3 px-3.5 font-mono text-[11px]">
                        <div className="flex items-center gap-1.5 text-zinc-200">
                          <Clock className="w-3 h-3 text-zinc-500 shrink-0" />
                          <span>{formatFecha(t.fecha_expiracion)}</span>
                        </div>
                        <div className="mt-0.5">
                          {diasRestantes > 5 ? (
                            <span className="text-[9px] text-emerald-400 font-medium">
                              En {diasRestantes} días
                            </span>
                          ) : diasRestantes >= 0 ? (
                            <span className="text-[9px] text-amber-400 font-medium">
                              Vence en {diasRestantes} días
                            </span>
                          ) : (
                            <span className="text-[9px] text-rose-400 font-medium">
                              Vencida hace {Math.abs(diasRestantes)}d
                            </span>
                          )}
                        </div>
                      </td>

                      {/* 6. Facturación Mensual */}
                      <td className="py-3 px-3.5 font-mono">
                        <div className="text-sm font-semibold text-emerald-400">
                          ${monto.toLocaleString('es-CL')} <span className="text-[10px] text-zinc-500 font-normal">USD</span>
                        </div>
                        <div className="text-[10px] text-zinc-500">
                          ${t.precio_unitario_plataforma || 35}/puesto/mes
                        </div>
                      </td>

                      {/* 7. Estado */}
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

                      {/* 8. Acciones */}
                      <td className="py-3 px-3.5 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {onEnterWorkspace && (
                            <button
                              onClick={() => onEnterWorkspace(t.id, t.razon_social)}
                              className="px-2 py-1 rounded-md bg-zinc-800/80 hover:bg-zinc-700/80 text-zinc-200 border border-white/[0.08] text-xs font-medium transition cursor-pointer flex items-center gap-1"
                              title={`Entrar al workspace de ${t.razon_social}`}
                            >
                              <ArrowUpRight className="w-3.5 h-3.5 text-zinc-400" />
                              <span>Entrar</span>
                            </button>
                          )}

                          {isCompany && (
                            <div className="flex items-center gap-0.5 ml-1">
                              <button
                                onClick={() => handleAdjustSeats(t.id, 1)}
                                disabled={actionLoading === t.id}
                                title="Añadir +1 puesto"
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
                          )}

                          {isActiva ? (
                            <button
                              onClick={() => handleRevokeLicense(t.id, t.razon_social)}
                              disabled={actionLoading === t.id}
                              className="px-2 py-1 rounded-md bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/20 text-xs font-medium transition cursor-pointer"
                              title="Revocar licencia"
                            >
                              Revocar
                            </button>
                          ) : (
                            <button
                              onClick={() => handleReactivateLicense(t.id, t.razon_social)}
                              disabled={actionLoading === t.id}
                              className="px-2 py-1 rounded-md bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 border border-emerald-500/20 text-xs font-medium transition cursor-pointer"
                              title="Reactivar licencia"
                            >
                              Reactivar
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
