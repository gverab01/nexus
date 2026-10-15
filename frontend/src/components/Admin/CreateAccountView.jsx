import React, { useState } from 'react';
import { 
  UserPlus, 
  User, 
  Building2, 
  Briefcase, 
  Plus, 
  Trash2, 
  CheckCircle2, 
  AlertTriangle, 
  Key, 
  Mail, 
  DollarSign, 
  Calendar, 
  Sparkles, 
  ArrowRight, 
  Copy, 
  Check,
  Lock,
  Layers,
  ChevronRight
} from 'lucide-react';
import { createFullAccount } from '../../services/api';

export default function CreateAccountView({ onNavigateToClients, onEnterWorkspace }) {
  // Tipo de cuenta seleccionado: 'FREELANCER' | 'EMPRESA' | 'AGENCIA'
  const [tipoCuenta, setTipoCuenta] = useState('FREELANCER');
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState(null);
  const [cuentaCreada, setCuentaCreada] = useState(null);
  const [copiedKey, setCopiedKey] = useState(false);

  // Campos comunes
  const [razonSocial, setRazonSocial] = useState('');
  const [adminNombre, setAdminNombre] = useState('');
  const [adminEmail, setAdminEmail] = useState('');
  const [adminPassword, setAdminPassword] = useState('nexus123');
  const [precioUnitario, setPrecioUnitario] = useState(35.0);
  const [periodicidad, setPeriodicidad] = useState('MENSUAL');

  // Campos específicos Empresa
  const [puestosEmpresa, setPuestosEmpresa] = useState(2);
  const [operadoresEmpresa, setOperadoresEmpresa] = useState([
    { nombre: '', email: '', password: 'operador123' }
  ]);

  // Campos específicos Agencia
  const [puestosAgencia, setPuestosAgencia] = useState(10);
  const [clienteInicialAgencia, setClienteInicialAgencia] = useState({
    razon_social: '',
    modelo_cobro: 'POR_PUESTO',
    operadores: [
      { nombre: '', email: '', password: 'operador123' }
    ]
  });

  // Helpers para operadores de Empresa
  function handleAddOperadorEmpresa() {
    setOperadoresEmpresa([
      ...operadoresEmpresa,
      { nombre: '', email: '', password: 'operador123' }
    ]);
  }

  function handleRemoveOperadorEmpresa(index) {
    if (operadoresEmpresa.length <= 1) return;
    setOperadoresEmpresa(operadoresEmpresa.filter((_, i) => i !== index));
  }

  function handleOperadorEmpresaChange(index, field, value) {
    const updated = [...operadoresEmpresa];
    updated[index][field] = value;
    setOperadoresEmpresa(updated);
  }

  // Helpers para operadores del Cliente Inicial de Agencia
  function handleAddOperadorClienteAgencia() {
    setClienteInicialAgencia({
      ...clienteInicialAgencia,
      operadores: [
        ...clienteInicialAgencia.operadores,
        { nombre: '', email: '', password: 'operador123' }
      ]
    });
  }

  function handleRemoveOperadorClienteAgencia(index) {
    if (clienteInicialAgencia.operadores.length <= 1) return;
    setClienteInicialAgencia({
      ...clienteInicialAgencia,
      operadores: clienteInicialAgencia.operadores.filter((_, i) => i !== index)
    });
  }

  function handleOperadorClienteAgenciaChange(index, field, value) {
    const updated = [...clienteInicialAgencia.operadores];
    updated[index][field] = value;
    setClienteInicialAgencia({
      ...clienteInicialAgencia,
      operadores: updated
    });
  }

  function resetForm() {
    setRazonSocial('');
    setAdminNombre('');
    setAdminEmail('');
    setAdminPassword('nexus123');
    setPrecioUnitario(35.0);
    setPeriodicidad('MENSUAL');
    setPuestosEmpresa(2);
    setOperadoresEmpresa([{ nombre: '', email: '', password: 'operador123' }]);
    setClienteInicialAgencia({
      razon_social: '',
      modelo_cobro: 'POR_PUESTO',
      operadores: [{ nombre: '', email: '', password: 'operador123' }]
    });
    setCuentaCreada(null);
    setFeedback(null);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setFeedback(null);

    if (!razonSocial.trim()) {
      setFeedback({ tipo: 'error', mensaje: 'Debes indicar el nombre de la cuenta o razón social.' });
      return;
    }
    if (!adminEmail.trim()) {
      setFeedback({ tipo: 'error', mensaje: 'Debes ingresar el correo del administrador.' });
      return;
    }

    // Validación básica para Empresa
    if (tipoCuenta === 'EMPRESA') {
      const tieneOpInvalido = operadoresEmpresa.some(op => !op.email.trim());
      if (tieneOpInvalido) {
        setFeedback({ tipo: 'error', mensaje: 'Debes ingresar el correo de al menos un operador de la empresa.' });
        return;
      }
    }

    // Validación para Agencia
    if (tipoCuenta === 'AGENCIA' && clienteInicialAgencia.razon_social.trim()) {
      const tieneOpInvalido = clienteInicialAgencia.operadores.some(op => !op.email.trim());
      if (tieneOpInvalido) {
        setFeedback({ tipo: 'error', mensaje: 'Indica el correo para el operador del cliente de la agencia.' });
        return;
      }
    }

    try {
      setLoading(true);

      const payload = {
        tipo_cuenta: tipoCuenta,
        razon_social: razonSocial.trim(),
        admin_nombre: adminNombre.trim() || razonSocial.trim(),
        admin_email: adminEmail.trim(),
        admin_password: adminPassword,
        precio_unitario: Number(precioUnitario),
        periodicidad: periodicidad,
        puestos_contratados: tipoCuenta === 'FREELANCER' 
          ? 1 
          : tipoCuenta === 'EMPRESA' 
          ? Number(puestosEmpresa) 
          : Number(puestosAgencia),
        operadores: tipoCuenta === 'EMPRESA' ? operadoresEmpresa : [],
        cliente_empresa_inicial: (tipoCuenta === 'AGENCIA' && clienteInicialAgencia.razon_social.trim())
          ? clienteInicialAgencia
          : null
      };

      const res = await createFullAccount(payload);
      setCuentaCreada({
        ...res,
        admin_password: adminPassword,
        tipo_label: tipoCuenta === 'FREELANCER' ? 'Usuario Libre (Freelancer)' : tipoCuenta === 'EMPRESA' ? 'Empresa con Operadores' : 'Agencia Multi-Cuenta'
      });
      setFeedback({ tipo: 'success', mensaje: `¡Cuenta "${razonSocial}" creada exitosamente!` });
    } catch (err) {
      setFeedback({ tipo: 'error', mensaje: `Error al crear la cuenta: ${err.message}` });
    } finally {
      setLoading(false);
    }
  }

  function handleCopyCredenciales() {
    if (!cuentaCreada) return;
    const text = `Credenciales NexusReach Pro:\nCuenta: ${cuentaCreada.razon_social}\nTipo: ${cuentaCreada.tipo_label}\nUsuario: ${cuentaCreada.admin_email}\nContraseña: ${cuentaCreada.admin_password}\nID: ${cuentaCreada.tenant_id}`;
    navigator.clipboard.writeText(text);
    setCopiedKey(true);
    setTimeout(() => setCopiedKey(false), 2000);
  }

  return (
    <div className="space-y-6 select-none animate-fadeIn max-w-4xl mx-auto">
      {/* 1. Encabezado */}
      <div>
        <h2 className="text-base font-semibold text-zinc-100 tracking-tight flex items-center gap-2">
          <UserPlus className="w-5 h-5 text-sky-400" />
          <span>Creación de Nuevas Cuentas de Clientes</span>
        </h2>
        <p className="text-xs text-zinc-400 mt-0.5">
          Configura y da de alta clientes monousuario (Freelancer), corporativos (Empresa) o matrices multi-workspace (Agencia).
        </p>
      </div>

      {/* 2. Feedback Alert */}
      {feedback && (
        <div className={`p-3.5 rounded-xl border text-xs flex items-center justify-between gap-3 animate-fadeIn ${
          feedback.tipo === 'success' 
            ? 'bg-emerald-950/20 border-emerald-500/30 text-emerald-300' 
            : 'bg-rose-950/20 border-rose-500/30 text-rose-300'
        }`}>
          <div className="flex items-center gap-2.5">
            {feedback.tipo === 'success' ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            ) : (
              <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
            )}
            <span>{feedback.mensaje}</span>
          </div>
        </div>
      )}

      {/* 3. Pantalla de Éxito si la cuenta fue creada */}
      {cuentaCreada ? (
        <div className="p-6 rounded-xl bg-[#121316] border border-emerald-500/30 space-y-5 animate-fadeIn">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-950/40 border border-emerald-500/40 text-emerald-400 flex items-center justify-center">
              <CheckCircle2 className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-zinc-100">
                ¡Cuenta creada y activada con éxito!
              </h3>
              <p className="text-xs text-zinc-400 mt-0.5">
                La organización ya está registrada en la base de datos con licencia activa y acceso configurado.
              </p>
            </div>
          </div>

          {/* Resumen de Credenciales */}
          <div className="p-4 rounded-lg bg-zinc-900/80 border border-white/[0.06] space-y-2.5 font-mono text-xs">
            <div className="flex justify-between py-1 border-b border-white/[0.05]">
              <span className="text-zinc-500">Razón Social:</span>
              <span className="text-zinc-200 font-semibold">{cuentaCreada.razon_social}</span>
            </div>
            <div className="flex justify-between py-1 border-b border-white/[0.05]">
              <span className="text-zinc-500">Tipo de Cuenta:</span>
              <span className="text-sky-400 font-semibold">{cuentaCreada.tipo_label}</span>
            </div>
            <div className="flex justify-between py-1 border-b border-white/[0.05]">
              <span className="text-zinc-500">ID de Organización:</span>
              <span className="text-zinc-300">{cuentaCreada.tenant_id}</span>
            </div>
            <div className="flex justify-between py-1 border-b border-white/[0.05]">
              <span className="text-zinc-500">Correo Administrador:</span>
              <span className="text-zinc-200">{cuentaCreada.admin_email}</span>
            </div>
            <div className="flex justify-between py-1 border-b border-white/[0.05]">
              <span className="text-zinc-500">Contraseña Asignada:</span>
              <span className="text-amber-300 font-bold">{cuentaCreada.admin_password}</span>
            </div>
            <div className="flex justify-between py-1">
              <span className="text-zinc-500">Puestos / Operadores:</span>
              <span className="text-zinc-300">{cuentaCreada.puestos_contratados} seats ({cuentaCreada.operadores_creados} operadores registrados)</span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 pt-2">
            <button
              onClick={handleCopyCredenciales}
              className="px-3.5 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-750 border border-white/[0.1] text-xs font-medium text-zinc-200 transition cursor-pointer flex items-center gap-1.5"
            >
              {copiedKey ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5 text-zinc-400" />}
              <span>{copiedKey ? 'Copiado al portapapeles' : 'Copiar Credenciales'}</span>
            </button>

            {onEnterWorkspace && (
              <button
                onClick={() => onEnterWorkspace(cuentaCreada.tenant_id, cuentaCreada.razon_social)}
                className="px-3.5 py-2 rounded-lg bg-sky-500/20 hover:bg-sky-500/30 border border-sky-500/40 text-xs font-medium text-sky-200 transition cursor-pointer flex items-center gap-1.5"
              >
                <span>Entrar al Workspace Creado</span>
                <ArrowRight className="w-3.5 h-3.5 text-sky-300" />
              </button>
            )}

            {onNavigateToClients && (
              <button
                onClick={onNavigateToClients}
                className="px-3.5 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-750 border border-white/[0.1] text-xs font-medium text-zinc-300 transition cursor-pointer"
              >
                Ver en Directorio de Clientes
              </button>
            )}

            <button
              onClick={resetForm}
              className="px-3.5 py-2 rounded-lg bg-zinc-900 hover:bg-zinc-850 border border-white/[0.08] text-xs font-medium text-zinc-400 hover:text-zinc-200 transition cursor-pointer ml-auto"
            >
              Crear otra cuenta
            </button>
          </div>
        </div>
      ) : (
        /* 4. Selector de Tipo de Cuenta & Formulario */
        <div className="space-y-6">
          {/* Selector de Tipo (3 Cards) */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-zinc-300 uppercase tracking-wider block">
              1. Selecciona el Tipo de Cuenta
            </label>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {/* Opción 1: Freelancer */}
              <button
                type="button"
                onClick={() => setTipoCuenta('FREELANCER')}
                className={`p-4 rounded-xl text-left border transition cursor-pointer space-y-2 ${
                  tipoCuenta === 'FREELANCER'
                    ? 'bg-purple-950/20 border-purple-500/40 text-purple-200 shadow-xs ring-1 ring-purple-500/30'
                    : 'bg-[#121316] border-white/[0.07] text-zinc-400 hover:border-white/[0.15] hover:text-zinc-200'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="w-8 h-8 rounded-lg bg-purple-950/40 border border-purple-500/30 text-purple-400 flex items-center justify-center">
                    <User className="w-4 h-4" />
                  </div>
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-300">
                    Caso Base
                  </span>
                </div>
                <div>
                  <h4 className="text-xs font-semibold text-zinc-100">Usuario Libre (Freelance)</h4>
                  <p className="text-[11px] text-zinc-500 leading-snug mt-1">
                    Cuenta monousuario para consultores individuales que prospectan con su cuenta propia.
                  </p>
                </div>
              </button>

              {/* Opción 2: Empresa */}
              <button
                type="button"
                onClick={() => setTipoCuenta('EMPRESA')}
                className={`p-4 rounded-xl text-left border transition cursor-pointer space-y-2 ${
                  tipoCuenta === 'EMPRESA'
                    ? 'bg-sky-950/20 border-sky-500/40 text-sky-200 shadow-xs ring-1 ring-sky-500/30'
                    : 'bg-[#121316] border-white/[0.07] text-zinc-400 hover:border-white/[0.15] hover:text-zinc-200'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="w-8 h-8 rounded-lg bg-sky-950/40 border border-sky-500/30 text-sky-400 flex items-center justify-center">
                    <Building2 className="w-4 h-4" />
                  </div>
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-300">
                    Con Operadores
                  </span>
                </div>
                <div>
                  <h4 className="text-xs font-semibold text-zinc-100">Cuenta Empresa</h4>
                  <p className="text-[11px] text-zinc-500 leading-snug mt-1">
                    Cuenta corporativa con administrador y alta inmediata de sus operadores/vendedores.
                  </p>
                </div>
              </button>

              {/* Opción 3: Agencia */}
              <button
                type="button"
                onClick={() => setTipoCuenta('AGENCIA')}
                className={`p-4 rounded-xl text-left border transition cursor-pointer space-y-2 ${
                  tipoCuenta === 'AGENCIA'
                    ? 'bg-amber-950/20 border-amber-500/40 text-amber-200 shadow-xs ring-1 ring-amber-500/30'
                    : 'bg-[#121316] border-white/[0.07] text-zinc-400 hover:border-white/[0.15] hover:text-zinc-200'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="w-8 h-8 rounded-lg bg-amber-950/40 border border-amber-500/30 text-amber-400 flex items-center justify-center">
                    <Briefcase className="w-4 h-4" />
                  </div>
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-300">
                    Caso General
                  </span>
                </div>
                <div>
                  <h4 className="text-xs font-semibold text-zinc-100">Cuenta Agencia</h4>
                  <p className="text-[11px] text-zinc-500 leading-snug mt-1">
                    Matriz con bolsa de puestos, creación de empresas clientes y sus operadores.
                  </p>
                </div>
              </button>
            </div>
          </div>

          {/* Formulario Principal */}
          <form onSubmit={handleSubmit} className="p-5 rounded-xl bg-[#121316] border border-white/[0.07] space-y-5">
            <h3 className="text-xs font-semibold text-zinc-200 uppercase tracking-wider flex items-center gap-2 border-b border-white/[0.06] pb-3">
              <span>2. Datos de la Cuenta ({tipoCuenta === 'FREELANCER' ? 'Usuario Libre' : tipoCuenta === 'EMPRESA' ? 'Empresa' : 'Agencia'})</span>
            </h3>

            {/* Datos Generales */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="text-xs font-medium text-zinc-300 block mb-1.5">
                  {tipoCuenta === 'FREELANCER' ? 'Nombre o Razón Social del Freelancer *' : 'Razón Social de la Organización *'}
                </label>
                <input
                  type="text"
                  required
                  placeholder={tipoCuenta === 'FREELANCER' ? 'ej. Consultoría Rodrigo' : tipoCuenta === 'EMPRESA' ? 'ej. Inmobiliaria Los Andes' : 'ej. Outbound Scale Agency'}
                  value={razonSocial}
                  onChange={(e) => setRazonSocial(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-zinc-900 border border-white/[0.08] text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 transition"
                />
              </div>

              <div>
                <label className="text-xs font-medium text-zinc-300 block mb-1.5">
                  Nombre Completo del Administrador / Titular *
                </label>
                <input
                  type="text"
                  required
                  placeholder="ej. Rodrigo Pérez"
                  value={adminNombre}
                  onChange={(e) => setAdminNombre(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-zinc-900 border border-white/[0.08] text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 transition"
                />
              </div>

              <div>
                <label className="text-xs font-medium text-zinc-300 block mb-1.5">
                  Correo Electrónico de Registro (Login) *
                </label>
                <input
                  type="email"
                  required
                  placeholder="ej. contacto@empresa.cl"
                  value={adminEmail}
                  onChange={(e) => setAdminEmail(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-zinc-900 border border-white/[0.08] text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 transition"
                />
              </div>

              <div>
                <label className="text-xs font-medium text-zinc-300 block mb-1.5">
                  Contraseña Inicial de Acceso *
                </label>
                <input
                  type="text"
                  required
                  value={adminPassword}
                  onChange={(e) => setAdminPassword(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-zinc-900 border border-white/[0.08] text-xs text-zinc-100 font-mono placeholder-zinc-500 focus:outline-none focus:border-zinc-500 transition"
                />
              </div>
            </div>

            {/* Configuración de Facturación y Puestos */}
            <div className="pt-3 border-t border-white/[0.06] grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div>
                <label className="text-xs font-medium text-zinc-300 block mb-1.5">
                  Tarifa por Puesto (USD/mes)
                </label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500 text-xs">$</span>
                  <input
                    type="number"
                    min="0"
                    step="0.5"
                    value={precioUnitario}
                    onChange={(e) => setPrecioUnitario(e.target.value)}
                    className="w-full pl-7 pr-3 py-2 rounded-lg bg-zinc-900 border border-white/[0.08] text-xs text-zinc-100 font-mono focus:outline-none focus:border-zinc-500 transition"
                  />
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-zinc-300 block mb-1.5">
                  Periodicidad de Facturación
                </label>
                <select
                  value={periodicidad}
                  onChange={(e) => setPeriodicidad(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-zinc-900 border border-white/[0.08] text-xs text-zinc-200 focus:outline-none focus:border-zinc-500 transition"
                >
                  <option value="MENSUAL">Mensual (30 días)</option>
                  <option value="ANUAL">Anual (365 días)</option>
                </select>
              </div>

              <div>
                <label className="text-xs font-medium text-zinc-300 block mb-1.5">
                  Puestos Contratados (Seats)
                </label>
                {tipoCuenta === 'FREELANCER' ? (
                  <div className="px-3 py-2 rounded-lg bg-zinc-900/50 border border-white/[0.06] text-xs text-zinc-400 font-mono">
                    1 puesto (Fijo individual)
                  </div>
                ) : tipoCuenta === 'EMPRESA' ? (
                  <input
                    type="number"
                    min={1 + operadoresEmpresa.length}
                    value={puestosEmpresa}
                    onChange={(e) => setPuestosEmpresa(Math.max(1 + operadoresEmpresa.length, Number(e.target.value)))}
                    className="w-full px-3 py-2 rounded-lg bg-zinc-900 border border-white/[0.08] text-xs text-zinc-100 font-mono focus:outline-none focus:border-zinc-500 transition"
                  />
                ) : (
                  <input
                    type="number"
                    min="5"
                    value={puestosAgencia}
                    onChange={(e) => setPuestosAgencia(Math.max(5, Number(e.target.value)))}
                    className="w-full px-3 py-2 rounded-lg bg-zinc-900 border border-white/[0.08] text-xs text-zinc-100 font-mono focus:outline-none focus:border-zinc-500 transition"
                  />
                )}
              </div>
            </div>

            {/* SECCIÓN ESPECÍFICA: OPERADORES DE EMPRESA */}
            {tipoCuenta === 'EMPRESA' && (
              <div className="pt-4 border-t border-white/[0.06] space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <h4 className="text-xs font-semibold text-zinc-200 uppercase tracking-wider flex items-center gap-1.5">
                      <Users className="w-3.5 h-3.5 text-sky-400" />
                      <span>Operadores de la Empresa (Al menos 1 requerido)</span>
                    </h4>
                    <p className="text-[11px] text-zinc-500 mt-0.5">
                      Los operadores usarán estas credenciales para acceder a la prospección dentro del workspace corporativo.
                    </p>
                  </div>

                  <button
                    type="button"
                    onClick={handleAddOperadorEmpresa}
                    className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-zinc-850 hover:bg-zinc-800 border border-zinc-750 text-xs font-medium text-zinc-300 transition cursor-pointer"
                  >
                    <Plus className="w-3 h-3 text-sky-400" />
                    <span>Añadir Operador</span>
                  </button>
                </div>

                <div className="space-y-2.5">
                  {operadoresEmpresa.map((op, idx) => (
                    <div key={idx} className="p-3 rounded-lg bg-zinc-900/60 border border-white/[0.06] flex flex-col sm:flex-row items-center gap-3">
                      <span className="text-[10px] font-mono text-zinc-500 shrink-0">
                        Op #{idx + 1}
                      </span>
                      <input
                        type="text"
                        placeholder="Nombre del Operador"
                        value={op.nombre}
                        onChange={(e) => handleOperadorEmpresaChange(idx, 'nombre', e.target.value)}
                        className="flex-1 px-2.5 py-1.5 rounded-md bg-zinc-900 border border-white/[0.08] text-xs text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
                      />
                      <input
                        type="email"
                        required
                        placeholder="Correo del Operador *"
                        value={op.email}
                        onChange={(e) => handleOperadorEmpresaChange(idx, 'email', e.target.value)}
                        className="flex-1 px-2.5 py-1.5 rounded-md bg-zinc-900 border border-white/[0.08] text-xs text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
                      />
                      <input
                        type="text"
                        placeholder="Contraseña"
                        value={op.password}
                        onChange={(e) => handleOperadorEmpresaChange(idx, 'password', e.target.value)}
                        className="w-32 px-2.5 py-1.5 rounded-md bg-zinc-900 border border-white/[0.08] text-xs text-zinc-200 font-mono focus:outline-none focus:border-zinc-500"
                      />
                      {operadoresEmpresa.length > 1 && (
                        <button
                          type="button"
                          onClick={() => handleRemoveOperadorEmpresa(idx)}
                          className="p-1 rounded text-zinc-500 hover:text-rose-400 hover:bg-rose-950/20 transition cursor-pointer"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* SECCIÓN ESPECÍFICA: AGENCIA (EMPRESA CLIENTE INICIAL & OPERADORES) */}
            {tipoCuenta === 'AGENCIA' && (
              <div className="pt-4 border-t border-white/[0.06] space-y-4">
                <div>
                  <h4 className="text-xs font-semibold text-zinc-200 uppercase tracking-wider flex items-center gap-1.5">
                    <Building2 className="w-3.5 h-3.5 text-amber-400" />
                    <span>Primera Empresa Cliente de la Agencia (Opcional / Inicial)</span>
                  </h4>
                  <p className="text-[11px] text-zinc-500 mt-0.5">
                    Puedes dar de alta de inmediato su primer cliente y asignar sus operadores respectivos.
                  </p>
                </div>

                <div className="p-4 rounded-xl bg-zinc-900/40 border border-white/[0.06] space-y-3">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs font-medium text-zinc-300 block mb-1">
                        Razón Social de la Empresa Cliente
                      </label>
                      <input
                        type="text"
                        placeholder="ej. Colegio San Agustín o Fintech Corp"
                        value={clienteInicialAgencia.razon_social}
                        onChange={(e) => setClienteInicialAgencia({ ...clienteInicialAgencia, razon_social: e.target.value })}
                        className="w-full px-3 py-2 rounded-lg bg-zinc-900 border border-white/[0.08] text-xs text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
                      />
                    </div>

                    <div>
                      <label className="text-xs font-medium text-zinc-300 block mb-1">
                        Modelo de Cobro de la Agencia al Cliente
                      </label>
                      <select
                        value={clienteInicialAgencia.modelo_cobro}
                        onChange={(e) => setClienteInicialAgencia({ ...clienteInicialAgencia, modelo_cobro: e.target.value })}
                        className="w-full px-3 py-2 rounded-lg bg-zinc-900 border border-white/[0.08] text-xs text-zinc-200 focus:outline-none focus:border-zinc-500"
                      >
                        <option value="POR_PUESTO">Cobro Por Puesto ($/seat)</option>
                        <option value="POR_REUNION">Cobro Por Reunión Agendada</option>
                        <option value="FEE_FIJO">Fee Fijo Mensual</option>
                      </select>
                    </div>
                  </div>

                  {clienteInicialAgencia.razon_social.trim() && (
                    <div className="pt-2 border-t border-white/[0.05] space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-medium text-zinc-400">
                          Operadores asignados a este cliente:
                        </span>
                        <button
                          type="button"
                          onClick={handleAddOperadorClienteAgencia}
                          className="flex items-center gap-1 text-[11px] text-amber-400 hover:text-amber-300 cursor-pointer"
                        >
                          <Plus className="w-3 h-3" />
                          <span>Añadir Operador Cliente</span>
                        </button>
                      </div>

                      {clienteInicialAgencia.operadores.map((sop, sidx) => (
                        <div key={sidx} className="flex flex-col sm:flex-row items-center gap-2">
                          <input
                            type="text"
                            placeholder="Nombre Operador"
                            value={sop.nombre}
                            onChange={(e) => handleOperadorClienteAgenciaChange(sidx, 'nombre', e.target.value)}
                            className="flex-1 px-2.5 py-1.5 rounded-md bg-zinc-900 border border-white/[0.08] text-xs text-zinc-200 placeholder-zinc-500"
                          />
                          <input
                            type="email"
                            required
                            placeholder="Correo Operador *"
                            value={sop.email}
                            onChange={(e) => handleOperadorClienteAgenciaChange(sidx, 'email', e.target.value)}
                            className="flex-1 px-2.5 py-1.5 rounded-md bg-zinc-900 border border-white/[0.08] text-xs text-zinc-200 placeholder-zinc-500"
                          />
                          <input
                            type="text"
                            placeholder="Contraseña"
                            value={sop.password}
                            onChange={(e) => handleOperadorClienteAgenciaChange(sidx, 'password', e.target.value)}
                            className="w-28 px-2.5 py-1.5 rounded-md bg-zinc-900 border border-white/[0.08] text-xs text-zinc-200 font-mono"
                          />
                          {clienteInicialAgencia.operadores.length > 1 && (
                            <button
                              type="button"
                              onClick={() => handleRemoveOperadorClienteAgencia(sidx)}
                              className="p-1 rounded text-zinc-500 hover:text-rose-400 cursor-pointer"
                            >
                              <Trash2 className="w-3 h-3" />
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Botón de Submit */}
            <div className="pt-3 border-t border-white/[0.06] flex items-center justify-between">
              <div className="text-xs text-zinc-400 font-mono">
                Facturación proyectada:{' '}
                <span className="font-semibold text-emerald-400">
                  ${(
                    Number(precioUnitario) * 
                    (tipoCuenta === 'FREELANCER' ? 1 : tipoCuenta === 'EMPRESA' ? Number(puestosEmpresa) : Number(puestosAgencia))
                  ).toLocaleString('es-CL')} USD/mes
                </span>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="px-5 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-zinc-950 text-xs font-semibold shadow-sm transition cursor-pointer flex items-center gap-2 disabled:opacity-50"
              >
                {loading ? (
                  <span>Creando cuenta...</span>
                ) : (
                  <>
                    <UserPlus className="w-4 h-4" />
                    <span>Crear Cuenta en Plataforma</span>
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
