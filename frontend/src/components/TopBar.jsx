import React from 'react';
import { 
  Users, 
  ListFilter, 
  GitFork, 
  Terminal, 
  Key, 
  Eye, 
  CheckCircle2, 
  ShieldCheck, 
  LogOut, 
  User, 
  Building2, 
  Briefcase,
  ChevronDown,
  Home
} from 'lucide-react';

export default function TopBar({
  activeTab,
  linkedinSessionActive = false,
  onLoginLinkedin,
  onViewBrowser,
  currentUser = null,
  onOpenSubscriptionModal,
  onLogout,
  agencyClients = [],
  selectedWorkspaceTenantId = '',
  selectedWorkspaceName = '',
  onSelectWorkspace = null,
  onExitWorkspace = null
}) {
  const titles = {
    super_admin: {
      title: 'Dashboard de Gestión de Plataforma',
      subtitle: 'Métricas ejecutivas, capacidad de puestos y salud de facturación recurrente',
      icon: Home
    },
    admin_clientes: {
      title: 'Directorio de Clientes',
      subtitle: 'Administración de empresas con operadores, freelancers y agencias con facturación',
      icon: Users
    },
    agency_portal: {
      title: 'Portal de Agencia, Clientes & Unit Economics',
      subtitle: 'Bolsa dinámica de seats, modelos comerciales y calculadora de margen neto',
      icon: Briefcase
    },
    prospectos: {
      title: 'Directorio de Prospectos B2B',
      subtitle: 'Búsqueda en LinkedIn, extracción y enriquecimiento de decisores',
      icon: Users
    },
    listas: {
      title: 'Listas de Leads & Audiencias',
      subtitle: 'Segmentación de prospectos y asignación a flujos de outreach',
      icon: ListFilter
    },
    secuencias: {
      title: 'Secuencias Multicanal & Piloto Automático',
      subtitle: 'Árboles de decisión, invitaciones, mensajes de valor y correos',
      icon: GitFork
    },
    logs: {
      title: 'Registro y Auditoría de Sucesos',
      subtitle: 'Telemetría en tiempo real, eventos del sistema y trazabilidad de operaciones',
      icon: Terminal
    }
  };

  const current = titles[activeTab] || titles.prospectos;
  const CurrentIcon = current.icon;
  const sub = currentUser?.suscripcion || {};
  const isSuperAdmin = currentUser?.rol === 'SUPER_ADMIN';
  const isAgencyAdmin = currentUser?.rol === 'AGENCY_ADMIN';
  const isSubClient = currentUser?.rol === 'COMPANY_MEMBER' || Boolean(currentUser?.tenant?.parent_tenant_id);
  const showProspectingControls = !(isSuperAdmin && !selectedWorkspaceTenantId);

  return (
    <header className="h-12 border-b border-white/[0.06] bg-[#0D0E12] px-5 flex items-center justify-between gap-4 sticky top-0 z-20 select-none">
      {/* Título contextual de la sección */}
      <div className="flex items-center gap-2.5 min-w-0">
        <div className="w-7 h-7 rounded-md bg-zinc-900 border border-zinc-800 flex items-center justify-center text-zinc-300 shrink-0">
          <CurrentIcon className="w-3.5 h-3.5" />
        </div>
        <div className="min-w-0">
          <h1 className="text-xs sm:text-[13px] font-medium text-zinc-100 truncate leading-tight">
            {current.title}
          </h1>
          <p className="text-[11px] text-zinc-500 truncate hidden md:block leading-none mt-0.5">
            {current.subtitle}
          </p>
        </div>
      </div>

      {/* Controles centrales / Selector de Workspace */}
      <div className="flex items-center gap-2 shrink-0">
        {/* Banner de Workspace para Super Admin cuando entra a prospectar en una organización */}
        {isSuperAdmin && selectedWorkspaceTenantId && (
          <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-zinc-900 border border-white/[0.08] text-xs text-zinc-300">
            <Building2 className="w-3.5 h-3.5 text-zinc-400 shrink-0" />
            <span className="text-[11px] text-zinc-500 hidden lg:inline">Workspace:</span>
            <span className="font-medium text-xs text-zinc-200 truncate max-w-[150px]">{selectedWorkspaceName || selectedWorkspaceTenantId}</span>
            {onExitWorkspace && (
              <button
                onClick={onExitWorkspace}
                className="ml-1 px-1.5 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-[10px] font-medium transition cursor-pointer"
                title="Salir del workspace de operador y volver a la Consola Master"
              >
                ← Salir
              </button>
            )}
          </div>
        )}

        {/* Selector de Workspace para Agencia */}
        {isAgencyAdmin && agencyClients.length > 0 && (
          <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-zinc-900 border border-white/[0.08] text-xs text-zinc-300">
            <Briefcase className="w-3.5 h-3.5 text-zinc-400 shrink-0" />
            <span className="text-[11px] text-zinc-500 hidden lg:inline">Workspace:</span>
            <select
              value={selectedWorkspaceTenantId}
              onChange={(e) => onSelectWorkspace && onSelectWorkspace(e.target.value)}
              className="bg-transparent text-zinc-200 font-medium focus:outline-none cursor-pointer text-xs"
            >
              <option value="" className="bg-zinc-950 text-zinc-100">🏢 Sede Agencia (Prospección Propia)</option>
              {agencyClients.map((c) => (
                <option key={c.id} value={c.id} className="bg-zinc-950 text-zinc-100">
                  📁 {c.razon_social}
                </option>
              ))}
            </select>
          </div>
        )}

        {isSubClient && (
          <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-zinc-900 border border-white/[0.08] text-xs text-zinc-300">
            <Building2 className="w-3.5 h-3.5 text-zinc-400 shrink-0" />
            <span className="text-[11px] text-zinc-500">Workspace:</span>
            <span className="text-zinc-200 font-medium text-xs truncate max-w-[150px]">
              {currentUser.tenant?.razon_social || 'Cliente'}
            </span>
          </div>
        )}

        {/* Estado de LinkedIn (Oculto en Consola Master de Super Admin) */}
        {showProspectingControls && (
          linkedinSessionActive ? (
            <div className="flex items-center gap-1.5">
              <div className="hidden md:flex items-center gap-1.5 px-2 py-1 rounded-md bg-zinc-900 border border-white/[0.06] text-xs text-zinc-300">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
                <span className="font-mono text-[11px]">LinkedIn</span>
              </div>
              <button
                onClick={onViewBrowser}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-zinc-850 hover:bg-zinc-800 border border-zinc-750 text-xs text-zinc-300 transition cursor-pointer"
                title="Ver ventana de trabajo en Chromium"
              >
                <Eye className="w-3 h-3 text-zinc-400" />
                <span className="hidden sm:inline text-[11px]">Ver Navegador</span>
              </button>
            </div>
          ) : (
            <button
              onClick={onLoginLinkedin}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-zinc-850 hover:bg-zinc-800 text-zinc-200 border border-zinc-750 text-xs font-medium transition cursor-pointer"
              title="Abre el navegador embebido para iniciar sesión en LinkedIn"
            >
              <Key className="w-3 h-3 text-zinc-400" />
              <span>Conectar LinkedIn</span>
            </button>
          )
        )}

        {/* Chip de Usuario y Suscripción */}
        {currentUser && (
          <div className="flex items-center gap-1.5 pl-1.5 border-l border-zinc-800">
            {isSubClient ? (
              <div
                title={`Operador asignado: ${currentUser.tenant?.razon_social || ''}`}
                className="flex items-center gap-2 px-2 py-1 rounded-md bg-zinc-900/60 border border-white/[0.06] text-left"
              >
                <div className="w-5 h-5 rounded-full bg-zinc-800 border border-zinc-700/80 flex items-center justify-center text-[10px] font-medium text-zinc-200 shrink-0">
                  {currentUser.nombre ? currentUser.nombre.substring(0, 2).toUpperCase() : 'US'}
                </div>
                <div className="hidden lg:block leading-none">
                  <div className="text-[11px] font-medium text-zinc-200 truncate max-w-[120px]">
                    {currentUser.nombre}
                  </div>
                  <div className="text-[9px] font-mono text-zinc-500 mt-0.5 truncate max-w-[100px]">
                    {currentUser.tenant?.razon_social || 'Operador'}
                  </div>
                </div>
              </div>
            ) : (
              <button
                onClick={onOpenSubscriptionModal}
                title="Ver detalles de tu suscripción"
                className="flex items-center gap-2 px-2 py-1 rounded-md bg-zinc-900/60 hover:bg-zinc-800/60 border border-white/[0.06] hover:border-white/[0.12] transition cursor-pointer text-left"
              >
                <div className="w-5 h-5 rounded-full bg-zinc-800 border border-zinc-700/80 flex items-center justify-center text-[10px] font-medium text-zinc-200 shrink-0">
                  {currentUser.nombre ? currentUser.nombre.substring(0, 2).toUpperCase() : 'US'}
                </div>
                <div className="hidden lg:block leading-none">
                  <div className="text-[11px] font-medium text-zinc-200 truncate max-w-[100px]">
                    {currentUser.nombre}
                  </div>
                  <div className="text-[9px] font-mono text-zinc-500 mt-0.5">
                    {isSuperAdmin ? 'Master Root' : `Plan ${sub.plan || 'Pro'}`}
                  </div>
                </div>
              </button>
            )}

            <button
              onClick={onLogout}
              title="Cerrar sesión"
              className="p-1.5 rounded-md bg-zinc-900/60 hover:bg-rose-950/30 hover:text-rose-400 border border-white/[0.06] hover:border-rose-500/30 text-zinc-400 transition cursor-pointer"
            >
              <LogOut className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
