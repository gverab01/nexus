import React, { useState, useEffect } from 'react';
import { 
  Briefcase, 
  TrendingUp, 
  Users, 
  DollarSign, 
  Plus, 
  Calendar, 
  Sparkles, 
  X, 
  RefreshCw, 
  CheckCircle2, 
  AlertTriangle,
  Layers,
  ArrowUpRight,
  Calculator,
  UserPlus,
  Power,
  Shield,
  Key
} from 'lucide-react';
import { 
  fetchAgencyFinances, 
  adjustTenantSeats, 
  createAgencyClient,
  fetchTenantMembers,
  createTenantMember,
  toggleUserSeat
} from '../../services/api';

export default function AgencyPortalView({ currentUser, onSelectWorkspace }) {
  const [finances, setFinances] = useState(null);
  const [loading, setLoading] = useState(true);
  const [feedback, setFeedback] = useState(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [isNewClientModalOpen, setIsNewClientModalOpen] = useState(false);

  // Formulario nuevo cliente
  const [companyName, setCompanyName] = useState('');
  const [billingModel, setBillingModel] = useState('POR_REUNION');
  const [meetingRate, setMeetingRate] = useState(150);
  const [seatPrice, setSeatPrice] = useState(75);
  const [monthlyFee, setMonthlyFee] = useState(1200);
  const [assignedSeats, setAssignedSeats] = useState(1);

  // Gestión de miembros / operadores del cliente
  const [selectedClientForMembers, setSelectedClientForMembers] = useState(null);
  const [clientMembers, setClientMembers] = useState([]);
  const [loadingMembers, setLoadingMembers] = useState(false);
  const [newMemberName, setNewMemberName] = useState('');
  const [newMemberEmail, setNewMemberEmail] = useState('');
  const [newMemberPassword, setNewMemberPassword] = useState('');

  const agencyId = currentUser?.tenant?.id || 'ten_growthx';

  useEffect(() => {
    loadFinances();
  }, []);

  async function loadFinances() {
    try {
      setLoading(true);
      const data = await fetchAgencyFinances(agencyId);
      if (data?.exito) {
        setFinances(data);
      }
    } catch (err) {
      setFeedback({ tipo: 'error', mensaje: `Error cargando finanzas: ${err.message}` });
    } finally {
      setLoading(false);
    }
  }

  async function handleExpandPool() {
    try {
      setActionLoading(true);
      await adjustTenantSeats(agencyId, 1);
      setFeedback({ tipo: 'success', mensaje: '¡Bolsa ampliada con éxito! Se añadió +1 puesto a tu capacidad.' });
      await loadFinances();
    } catch (err) {
      setFeedback({ tipo: 'error', mensaje: `Error ampliando bolsa: ${err.message}` });
    } finally {
      setActionLoading(false);
    }
  }

  async function handleCreateClient(e) {
    e.preventDefault();
    if (!companyName.trim()) {
      alert('Por favor ingresa la razón social del cliente.');
      return;
    }
    try {
      setActionLoading(true);
      const res = await createAgencyClient(agencyId, {
        razon_social: companyName.trim(),
        modelo_cobro: billingModel,
        tarifa_por_reunion: parseFloat(meetingRate) || 0,
        precio_cliente_por_puesto: parseFloat(seatPrice) || 0,
        fee_fijo_mensual: parseFloat(monthlyFee) || 0,
        puestos_asignados: parseInt(assignedSeats) || 1
      });
      if (res?.exito) {
        setFeedback({ tipo: 'success', mensaje: `Cliente "${companyName}" creado exitosamente.` });
        setIsNewClientModalOpen(false);
        setCompanyName('');
        await loadFinances();
      }
    } catch (err) {
      alert(`Error creando cliente: ${err.message}`);
    } finally {
      setActionLoading(false);
    }
  }

  async function handleOpenMemberManagement(client) {
    setSelectedClientForMembers(client);
    setLoadingMembers(true);
    try {
      const data = await fetchTenantMembers(client.id);
      setClientMembers(Array.isArray(data) ? data : []);
    } catch (err) {
      alert(`Error al cargar miembros: ${err.message}`);
    } finally {
      setLoadingMembers(false);
    }
  }

  async function handleToggleMemberSeat(memberId, currentActive) {
    try {
      const nextState = currentActive === 1 ? 0 : 1;
      await toggleUserSeat(memberId, nextState);
      if (selectedClientForMembers) {
        const data = await fetchTenantMembers(selectedClientForMembers.id);
        setClientMembers(Array.isArray(data) ? data : []);
      }
      await loadFinances();
    } catch (err) {
      alert(`Error modificando puesto: ${err.message}`);
    }
  }

  async function handleCreateMember(e) {
    e.preventDefault();
    if (!newMemberName || !newMemberEmail || !newMemberPassword) {
      alert('Por favor completa todos los campos del nuevo operador.');
      return;
    }
    try {
      setActionLoading(true);
      await createTenantMember(selectedClientForMembers.id, {
        nombre: newMemberName.trim(),
        email: newMemberEmail.trim(),
        password: newMemberPassword.trim(),
        rol: 'COMPANY_MEMBER'
      });
      setNewMemberName('');
      setNewMemberEmail('');
      setNewMemberPassword('');
      const data = await fetchTenantMembers(selectedClientForMembers.id);
      setClientMembers(Array.isArray(data) ? data : []);
      await loadFinances();
      setFeedback({ tipo: 'success', mensaje: 'Operador creado exitosamente con puesto asignado.' });
    } catch (err) {
      alert(`Error creando operador: ${err.message}`);
    } finally {
      setActionLoading(false);
    }
  }

  const bolsa = finances?.resumen_bolsa || {};
  const consolidado = finances?.consolidado_financiero || {};
  const clientes = finances?.clientes || [];

  return (
    <div className="space-y-6 select-none animate-fadeIn font-sans">
      {/* 1. Cabecera del Portal */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-5 rounded-xl bg-[#121316] border border-white/[0.08]">
        <div className="flex items-center gap-3.5">
          <div className="w-9 h-9 rounded-lg bg-zinc-900 border border-white/[0.1] flex items-center justify-center text-zinc-200">
            <Briefcase className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-medium text-zinc-100 tracking-tight">Portal de Agencia & Rentabilidad</h2>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-medium bg-white/[0.04] text-zinc-400 border border-white/[0.08]">
                AGENCY HQ
              </span>
            </div>
            <p className="text-xs text-zinc-400 mt-0.5">
              Control de clientes, bolsa dinámica de puestos y análisis financiero de márgenes
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto">
          <button
            onClick={() => setIsNewClientModalOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs transition duration-150 cursor-pointer shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Nuevo Cliente</span>
          </button>

          <button
            onClick={loadFinances}
            disabled={loading}
            className="p-1.5 rounded-md bg-[#0D0E12] hover:bg-zinc-800/60 border border-white/[0.08] text-zinc-400 hover:text-zinc-200 transition cursor-pointer"
            title="Actualizar datos"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* 2. Feedback Alert */}
      {feedback && (
        <div className={`p-3.5 rounded-xl border text-xs flex items-center justify-between gap-3 animate-fadeIn ${
          feedback.tipo === 'success' 
            ? 'bg-emerald-950/40 border-emerald-500/40 text-emerald-200' 
            : 'bg-rose-950/40 border-rose-500/40 text-rose-200'
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

      {/* 3. Métricas Financieras y Bolsa Elástica */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Bolsa de Puestos */}
        <div className="p-4 rounded-xl bg-zinc-900/40 border border-zinc-800/80 space-y-2">
          <div className="text-[11px] font-medium text-zinc-400 flex items-center justify-between">
            <span>Bolsa Elástica de Puestos</span>
            <Users className="w-4 h-4 text-sky-400" />
          </div>
          <div className="text-2xl font-bold text-zinc-100 font-mono">
            {bolsa.puestos_ocupados || 0} <span className="text-xs font-normal text-zinc-500">/ {bolsa.puestos_contratados || 0} seats</span>
          </div>
          <div className="flex items-center justify-between pt-1">
            <span className="text-[10px] text-emerald-400 font-mono">
              {bolsa.puestos_libres || 0} puestos libres
            </span>
            <button
              onClick={handleExpandPool}
              disabled={actionLoading}
              className="text-[10px] font-semibold text-sky-400 hover:text-sky-300 transition cursor-pointer flex items-center gap-0.5"
            >
              + Ampliar Bolsa
            </button>
          </div>
        </div>

        {/* Facturación a Clientes */}
        <div className="p-4 rounded-xl bg-zinc-900/40 border border-zinc-800/80 space-y-1">
          <div className="text-[11px] font-medium text-zinc-400 flex items-center justify-between">
            <span>Facturación a Clientes</span>
            <TrendingUp className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-bold text-emerald-400 font-mono">
            ${(consolidado.facturacion_total_clientes || 0).toLocaleString('es-CL')} <span className="text-xs text-zinc-500">USD</span>
          </div>
          <p className="text-[10px] text-zinc-500">Total ingresos por reuniones y fees</p>
        </div>

        {/* Costo Plataforma */}
        <div className="p-4 rounded-xl bg-zinc-900/40 border border-zinc-800/80 space-y-1">
          <div className="text-[11px] font-medium text-zinc-400 flex items-center justify-between">
            <span>Costo Base Plataforma</span>
            <DollarSign className="w-4 h-4 text-zinc-400" />
          </div>
          <div className="text-2xl font-bold text-zinc-300 font-mono">
            ${(consolidado.costo_total_plataforma || 0).toLocaleString('es-CL')} <span className="text-xs text-zinc-500">USD</span>
          </div>
          <p className="text-[10px] text-zinc-500">
            {bolsa.puestos_contratados || 0} seats × ${bolsa.costo_unitario || 35} USD
          </p>
        </div>

        {/* Margen Neto */}
        <div className="p-4 rounded-xl bg-zinc-900/40 border border-zinc-800/80 space-y-1">
          <div className="text-[11px] font-medium text-zinc-400 flex items-center justify-between">
            <span>Margen Neto Agencia</span>
            <Calculator className="w-4 h-4 text-indigo-400" />
          </div>
          <div className={`text-2xl font-bold font-mono ${
            (consolidado.margen_neto_agencia || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'
          }`}>
            ${(consolidado.margen_neto_agencia || 0).toLocaleString('es-CL')} <span className="text-xs text-zinc-500">USD</span>
          </div>
          <div className="text-[10px] font-semibold text-emerald-400 font-mono">
            Rentabilidad: {consolidado.porcentaje_margen || 0}%
          </div>
        </div>
      </div>

      {/* 4. Tabla de Clientes con Modelos Comerciales & Operadores */}
      <div className="rounded-2xl bg-zinc-900/40 border border-zinc-800/80 overflow-hidden">
        <div className="p-4 border-b border-zinc-800 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Layers className="w-4 h-4 text-sky-400" />
            <h3 className="text-xs font-semibold text-zinc-200 uppercase tracking-wider">
              Cartera de Clientes & Rendimiento por Acuerdo
            </h3>
          </div>
          <span className="text-[11px] text-zinc-500 font-mono">
            {clientes.length} clientes gestionados
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-zinc-950/60 text-zinc-400 text-[11px] uppercase tracking-wider font-semibold border-b border-zinc-800/80">
              <tr>
                <th className="py-3 px-4">Cliente (Workspace)</th>
                <th className="py-3 px-4">Modelo Comercial</th>
                <th className="py-3 px-4">Puestos</th>
                <th className="py-3 px-4">Reuniones</th>
                <th className="py-3 px-4">Facturado</th>
                <th className="py-3 px-4">Costo Software</th>
                <th className="py-3 px-4">Margen Neto</th>
                <th className="py-3 px-4 text-right">Equipo & Workspace</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/60">
              {clientes.map((c) => {
                const isMeetingModel = c.modelo_cobro === 'POR_REUNION';
                return (
                  <tr key={c.id} className="hover:bg-zinc-800/30 transition">
                    {/* Cliente */}
                    <td className="py-3.5 px-4">
                      <div className="font-semibold text-zinc-100">{c.razon_social}</div>
                      <div className="text-[10px] text-zinc-500 font-mono">ID: {c.id}</div>
                    </td>

                    {/* Modelo */}
                    <td className="py-3.5 px-4">
                      <span className={`px-2 py-0.5 rounded-md text-[10px] font-mono font-semibold ${
                        isMeetingModel 
                          ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20'
                          : c.modelo_cobro === 'POR_PUESTO'
                          ? 'bg-sky-500/10 text-sky-300 border border-sky-500/20'
                          : 'bg-indigo-500/10 text-indigo-300 border border-indigo-500/20'
                      }`}>
                        {c.modelo_cobro}
                      </span>
                    </td>

                    {/* Puestos */}
                    <td className="py-3.5 px-4 font-mono text-zinc-300">
                      {c.puestos_usados} / {c.puestos_asignados}
                    </td>

                    {/* Reuniones */}
                    <td className="py-3.5 px-4 font-mono font-semibold text-emerald-400">
                      {c.reuniones_agendadas} citas
                    </td>

                    {/* Facturado */}
                    <td className="py-3.5 px-4 font-mono text-zinc-200">
                      ${c.facturacion_cliente} USD
                    </td>

                    {/* Costo */}
                    <td className="py-3.5 px-4 font-mono text-zinc-500">
                      ${c.costo_plataforma} USD
                    </td>

                    {/* Margen */}
                    <td className="py-3.5 px-4 font-mono font-bold">
                      <span className={c.margen_neto >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                        {c.margen_neto >= 0 ? `+$${c.margen_neto}` : `-$${Math.abs(c.margen_neto)}`} USD
                      </span>
                    </td>

                    {/* Acciones de Equipo y Workspace */}
                    <td className="py-3.5 px-4 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          onClick={() => handleOpenMemberManagement(c)}
                          className="px-2.5 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-sky-400 border border-zinc-700/60 font-medium text-[11px] transition cursor-pointer flex items-center gap-1"
                          title="Gestionar operadores y asignación de puestos de este cliente"
                        >
                          <Users className="w-3.5 h-3.5" />
                          <span>Operadores ({c.puestos_usados}/{c.puestos_asignados})</span>
                        </button>
                        {onSelectWorkspace && (
                          <button
                            onClick={() => onSelectWorkspace(c.id, c.razon_social)}
                            className="px-2.5 py-1.5 rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 font-medium text-[11px] transition cursor-pointer flex items-center gap-1"
                            title="Entrar al workspace de este cliente para ver sus prospectos"
                          >
                            <ArrowUpRight className="w-3.5 h-3.5" />
                            <span>Entrar</span>
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

      {/* 5. Modal de Gestión de Operadores del Cliente */}
      {selectedClientForMembers && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fadeIn">
          <div className="relative w-full max-w-lg rounded-2xl bg-zinc-900 border border-zinc-800 p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <Users className="w-5 h-5 text-sky-400" />
                <div>
                  <h3 className="text-sm font-semibold text-zinc-100">
                    Operadores & Seats: {selectedClientForMembers.razon_social}
                  </h3>
                  <p className="text-[11px] text-zinc-400">
                    Puestos: {selectedClientForMembers.puestos_usados} ocupados de {selectedClientForMembers.puestos_asignados} asignados
                  </p>
                </div>
              </div>
              <button 
                onClick={() => setSelectedClientForMembers(null)}
                className="p-1 rounded-lg text-zinc-400 hover:text-zinc-200 cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Listado de miembros */}
            <div className="space-y-2 max-h-56 overflow-y-auto">
              <div className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wider">
                Operadores del Cliente
              </div>

              {loadingMembers ? (
                <div className="p-4 text-center text-xs text-zinc-400 font-mono">Cargando operadores...</div>
              ) : clientMembers.length === 0 ? (
                <div className="p-4 text-center text-xs text-zinc-500 bg-zinc-950/40 rounded-xl border border-zinc-800">
                  No hay operadores registrados aún para este cliente.
                </div>
              ) : (
                clientMembers.map((m) => {
                  const tienePuesto = m.puesto_activo === 1;
                  return (
                    <div 
                      key={m.id} 
                      className="p-2.5 rounded-xl bg-zinc-950/60 border border-zinc-800 flex items-center justify-between gap-3 text-xs"
                    >
                      <div className="min-w-0">
                        <div className="font-semibold text-zinc-200 truncate">{m.nombre}</div>
                        <div className="text-[10px] text-zinc-500 font-mono truncate">{m.email}</div>
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold flex items-center gap-1 ${
                          tienePuesto 
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' 
                            : 'bg-zinc-800 text-zinc-500 border border-zinc-700/40'
                        }`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${tienePuesto ? 'bg-emerald-400 animate-pulse' : 'bg-zinc-600'}`} />
                          {tienePuesto ? 'Seat Activo' : 'Sin Seat'}
                        </span>

                        <button
                          onClick={() => handleToggleMemberSeat(m.id, m.puesto_activo)}
                          className={`px-2 py-1 rounded-lg text-[10px] font-medium transition cursor-pointer border ${
                            tienePuesto 
                              ? 'bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border-rose-500/30' 
                              : 'bg-sky-500/10 hover:bg-sky-500/20 text-sky-300 border-sky-500/30'
                          }`}
                          title={tienePuesto ? 'Liberar seat de este usuario' : 'Asignar seat a este usuario'}
                        >
                          {tienePuesto ? 'Liberar' : 'Activar Seat'}
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            {/* Formulario nuevo operador */}
            <div className="pt-3 border-t border-zinc-800">
              <div className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                <UserPlus className="w-3.5 h-3.5 text-sky-400" />
                Invitar Nuevo Operador para este Cliente
              </div>

              <form onSubmit={handleCreateMember} className="space-y-2 text-xs">
                <div className="grid grid-cols-2 gap-2">
                  <input
                    type="text"
                    value={newMemberName}
                    onChange={(e) => setNewMemberName(e.target.value)}
                    placeholder="Nombre del operador"
                    required
                    className="px-3 py-1.5 bg-zinc-950 border border-zinc-800 rounded-xl text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-sky-500 text-xs"
                  />
                  <input
                    type="email"
                    value={newMemberEmail}
                    onChange={(e) => setNewMemberEmail(e.target.value)}
                    placeholder="correo@cliente.cl"
                    required
                    className="px-3 py-1.5 bg-zinc-950 border border-zinc-800 rounded-xl text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-sky-500 text-xs"
                  />
                </div>
                <div className="flex gap-2">
                  <input
                    type="password"
                    value={newMemberPassword}
                    onChange={(e) => setNewMemberPassword(e.target.value)}
                    placeholder="Contraseña inicial"
                    required
                    className="flex-1 px-3 py-1.5 bg-[#0D0E12] border border-white/[0.08] rounded-md text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 text-xs"
                  />
                  <button
                    type="submit"
                    disabled={actionLoading}
                    className="px-3 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs shadow-sm transition cursor-pointer"
                  >
                    {actionLoading ? 'Guardando...' : '+ Crear Operador'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}

      {/* 6. Modal para Crear Nuevo Cliente */}
      {isNewClientModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fadeIn">
          <div className="relative w-full max-w-md rounded-2xl bg-zinc-900 border border-zinc-800 p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <Briefcase className="w-5 h-5 text-sky-400" />
                <h3 className="text-sm font-semibold text-zinc-100">Registrar Nuevo Cliente</h3>
              </div>
              <button 
                onClick={() => setIsNewClientModalOpen(false)}
                className="p-1 rounded-lg text-zinc-400 hover:text-zinc-200 cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleCreateClient} className="space-y-3.5 text-xs">
              <div>
                <label className="block text-[11px] font-medium text-zinc-300 mb-1">
                  Nombre / Razón Social del Cliente
                </label>
                <input
                  type="text"
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                  placeholder="ej. Inmobiliaria Andes SpA"
                  required
                  className="w-full px-3 py-2 bg-zinc-950 border border-zinc-800 rounded-xl text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-sky-500"
                />
              </div>

              <div>
                <label className="block text-[11px] font-medium text-zinc-300 mb-1">
                  Modelo de Cobro Acordado con el Cliente
                </label>
                <select
                  value={billingModel}
                  onChange={(e) => setBillingModel(e.target.value)}
                  className="w-full px-3 py-2 bg-zinc-950 border border-zinc-800 rounded-xl text-zinc-100 focus:outline-none focus:border-sky-500"
                >
                  <option value="POR_REUNION">Pago por Reunión Agendada (Pay-per-Meeting)</option>
                  <option value="POR_PUESTO">Reventa por Puesto / Seat</option>
                  <option value="RETAINER_FIJO">Fee Fijo Mensual (Retainer)</option>
                  <option value="INTERNO">Prospección Interna (Sin Cobro)</option>
                </select>
              </div>

              {billingModel === 'POR_REUNION' && (
                <div>
                  <label className="block text-[11px] font-medium text-zinc-300 mb-1">
                    Tarifa por Reunión Agendada (USD)
                  </label>
                  <input
                    type="number"
                    value={meetingRate}
                    onChange={(e) => setMeetingRate(e.target.value)}
                    placeholder="150"
                    className="w-full px-3 py-2 bg-zinc-950 border border-zinc-800 rounded-xl text-zinc-100 focus:outline-none focus:border-sky-500"
                  />
                </div>
              )}

              {billingModel === 'POR_PUESTO' && (
                <div>
                  <label className="block text-[11px] font-medium text-zinc-300 mb-1">
                    Precio Cobrado por Puesto (USD/mes)
                  </label>
                  <input
                    type="number"
                    value={seatPrice}
                    onChange={(e) => setSeatPrice(e.target.value)}
                    placeholder="75"
                    className="w-full px-3 py-2 bg-zinc-950 border border-zinc-800 rounded-xl text-zinc-100 focus:outline-none focus:border-sky-500"
                  />
                </div>
              )}

              {billingModel === 'RETAINER_FIJO' && (
                <div>
                  <label className="block text-[11px] font-medium text-zinc-300 mb-1">
                    Fee Fijo Mensual Acordado (USD)
                  </label>
                  <input
                    type="number"
                    value={monthlyFee}
                    onChange={(e) => setMonthlyFee(e.target.value)}
                    placeholder="1200"
                    className="w-full px-3 py-2 bg-zinc-950 border border-zinc-800 rounded-xl text-zinc-100 focus:outline-none focus:border-sky-500"
                  />
                </div>
              )}

              <div>
                <label className="block text-[11px] font-medium text-zinc-300 mb-1">
                  Puestos a Asignar de tu Bolsa ({bolsa.puestos_libres || 0} disponibles)
                </label>
                <input
                  type="number"
                  min="1"
                  max={bolsa.puestos_libres || 1}
                  value={assignedSeats}
                  onChange={(e) => setAssignedSeats(e.target.value)}
                  className="w-full px-3 py-2 bg-zinc-950 border border-zinc-800 rounded-xl text-zinc-100 focus:outline-none focus:border-sky-500"
                />
              </div>

              <div className="pt-3 flex items-center justify-end gap-2 border-t border-zinc-800">
                <button
                  type="button"
                  onClick={() => setIsNewClientModalOpen(false)}
                  className="px-3 py-1.5 rounded-md bg-[#0D0E12] hover:bg-zinc-800 border border-white/[0.08] text-zinc-300 text-xs cursor-pointer transition"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="px-4 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs cursor-pointer shadow-sm transition"
                >
                  {actionLoading ? 'Guardando...' : 'Crear Cliente'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
