import React from 'react';
import { 
  Users, 
  ListFilter, 
  GitFork, 
  Terminal, 
  Power, 
  CheckCircle2, 
  Key, 
  Eye, 
  Zap, 
  Sparkles, 
  Building2,
  Briefcase,
  ShieldCheck,
  Home
} from 'lucide-react';

export default function Sidebar({
  activeTab,
  setActiveTab,
  listsCount = 0,
  sequencesCount = 0,
  logsCount = 0,
  isExtracting = false,
  linkedinSessionActive = false,
  campaignActive = true,
  onToggleCampaign,
  onLoginLinkedin,
  onViewBrowser,
  currentUser = null,
  selectedWorkspaceTenantId = '',
  selectedWorkspaceName = '',
  onExitWorkspace = null
}) {
  const isSuperAdmin = currentUser?.rol === 'SUPER_ADMIN';
  const isAgencyAdmin = currentUser?.rol === 'AGENCY_ADMIN';
  const isSubClient = currentUser?.rol === 'COMPANY_MEMBER' || Boolean(currentUser?.tenant?.parent_tenant_id);
  const isInTenantWorkspace = Boolean(selectedWorkspaceTenantId);
  const showProspectingControls = !(isSuperAdmin && !isInTenantWorkspace);

  // Definición de ítems según rol y contexto de workspace
  const navItems = [];

  if (isSuperAdmin) {
    if (isInTenantWorkspace) {
      navItems.push({
        id: 'super_admin',
        label: '← Volver al Inicio',
        icon: Home,
        badge: null
      });
      navItems.push(
        { 
          id: 'prospectos', 
          label: 'Prospectos', 
          icon: Users, 
          badge: null,
          desc: `Directorio de ${selectedWorkspaceName || 'este workspace'}`
        },
        { 
          id: 'listas', 
          label: 'Listas de Leads', 
          icon: ListFilter, 
          badge: listsCount,
          desc: 'Audiencias del workspace'
        },
        { 
          id: 'secuencias', 
          label: 'Secuencias', 
          icon: GitFork, 
          badge: sequencesCount,
          desc: 'Flujos del workspace'
        }
      );
    } else {
      navItems.push(
        {
          id: 'super_admin',
          label: 'Inicio',
          icon: Home,
          badge: null
        },
        {
          id: 'admin_clientes',
          label: 'Clientes',
          icon: Users,
          badge: null
        }
      );
    }
  } else {
    // Para Agencias y Miembros Operadores
    if (isAgencyAdmin) {
      navItems.push({
        id: 'agency_portal',
        label: 'Portal Agencia',
        icon: Briefcase,
        badge: 'ROI',
        desc: 'Bolsa de seats y cartera de clientes'
      });
    }

    navItems.push(
      { 
        id: 'prospectos', 
        label: 'Prospectos', 
        icon: Users, 
        badge: null,
        desc: 'Búsqueda y extracción'
      },
      { 
        id: 'listas', 
        label: 'Listas de Leads', 
        icon: ListFilter, 
        badge: listsCount,
        desc: 'Audiencias y segmentos'
      },
      { 
        id: 'secuencias', 
        label: 'Secuencias', 
        icon: GitFork, 
        badge: sequencesCount,
        desc: 'Flujos multicanal'
      },
      { 
        id: 'logs', 
        label: 'Logs y Actividad', 
        icon: Terminal, 
        badge: isExtracting ? '● VIVO' : logsCount,
        isPulse: isExtracting,
        desc: 'Auditoría en tiempo real'
      }
    );
  }

  return (
    <aside className="w-64 h-screen sticky top-0 bg-[#0D0E12] border-r border-white/[0.06] flex flex-col justify-between shrink-0 select-none z-30">
      {/* 1. Header de Marca (NexusReach Pro) */}
      <div>
        <div className="p-3.5 border-b border-white/[0.06] flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-md bg-zinc-900 border border-zinc-700/70 flex items-center justify-center text-zinc-200 font-semibold text-[11px] tracking-wider shrink-0 shadow-xs">
            NR
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 leading-none">
              <span className="font-medium text-[13px] tracking-tight text-zinc-100">NexusReach</span>
              <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-medium bg-zinc-800 text-zinc-400 border border-zinc-700/50">
                PRO
              </span>
            </div>
            <p className="text-[11px] text-zinc-500 leading-none mt-1 truncate">
              {currentUser?.tenant?.razon_social || 'Suite de Prospección B2B'}
            </p>
          </div>
        </div>

        {/* 2. Menú de Navegación Vertical */}
        <div className="p-2.5 space-y-0.5">
          <div className="px-2.5 pt-2 pb-1.5 text-[10px] font-medium uppercase tracking-wider text-zinc-500">
            Módulos
          </div>
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => {
                  if (item.id === 'super_admin' && isInTenantWorkspace && onExitWorkspace) {
                    onExitWorkspace();
                  } else {
                    setActiveTab(item.id);
                  }
                }}
                className={`w-full flex items-center justify-between px-2.5 py-2 rounded-lg text-xs transition-colors duration-100 cursor-pointer ${
                  isActive
                    ? 'bg-zinc-800/70 text-zinc-100 border border-white/[0.08] font-medium shadow-xs'
                    : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/30 border border-transparent font-normal'
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <Icon className={`w-3.5 h-3.5 shrink-0 ${isActive ? 'text-zinc-100' : 'text-zinc-400'}`} />
                  <span className="truncate">{item.label}</span>
                </div>
                {item.badge !== null && (
                  <span
                    className={`text-[10px] px-1.5 py-0.2 rounded font-mono shrink-0 ${
                      item.isPulse
                        ? 'bg-emerald-950/40 text-emerald-400 border border-emerald-500/30 font-medium'
                        : isActive
                        ? 'bg-zinc-700/80 text-zinc-200'
                        : 'bg-zinc-800/60 text-zinc-500 border border-zinc-800'
                    }`}
                  >
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* 3. Dock Inferior: Conexión de LinkedIn & Control de Campaña (Oculto en Consola Master) */}
      <div className="p-2.5 border-t border-white/[0.06] space-y-2 bg-[#0D0E12]">
        {showProspectingControls ? (
          <>
            {/* Estado de LinkedIn */}
            {linkedinSessionActive ? (
              <div className="p-2.5 rounded-lg bg-zinc-900/60 border border-white/[0.06] space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 text-xs text-zinc-300 font-normal">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0 animate-subtle-dot" />
                    <span className="font-mono text-[11px] text-zinc-300">LinkedIn Conectado</span>
                  </div>
                </div>
                <button
                  onClick={onViewBrowser}
                  className="w-full flex items-center justify-center gap-1.5 py-1 px-2 rounded-md bg-zinc-800/60 hover:bg-zinc-700/60 border border-zinc-700/40 text-[11px] text-zinc-300 transition cursor-pointer"
                  title="Ver ventana de trabajo en Chromium"
                >
                  <Eye className="w-3 h-3 text-zinc-400" />
                  <span>Ver Navegador</span>
                </button>
              </div>
            ) : (
              <button
                onClick={onLoginLinkedin}
                className="w-full flex items-center justify-center gap-2 p-2 rounded-lg bg-zinc-800/80 hover:bg-zinc-700 text-zinc-200 border border-zinc-700/60 text-xs font-medium transition cursor-pointer"
                title="Abre la ventana para iniciar sesión en tu cuenta de LinkedIn"
              >
                <Key className="w-3.5 h-3.5 text-zinc-400 shrink-0" />
                <span>Conectar LinkedIn</span>
              </button>
            )}

            {/* Interruptor Global de Campaña */}
            <button
              onClick={onToggleCampaign}
              className={`w-full flex items-center justify-between px-2.5 py-2 rounded-lg text-xs font-medium border transition cursor-pointer ${
                campaignActive
                  ? 'bg-zinc-900/80 text-zinc-200 border-white/[0.08] hover:bg-zinc-800/60'
                  : 'bg-zinc-900/40 text-zinc-400 border-zinc-800 hover:text-zinc-200 hover:bg-zinc-800/40'
              }`}
              title="Activa o pausa todas las secuencias y envíos"
            >
              <div className="flex items-center gap-2">
                <Power className={`w-3.5 h-3.5 ${campaignActive ? 'text-emerald-400' : 'text-zinc-500'}`} />
                <span>Campaña</span>
              </div>
              <div className="flex items-center gap-1.5 font-mono text-[10px]">
                <span className={`w-1.5 h-1.5 rounded-full ${campaignActive ? 'bg-emerald-400' : 'bg-zinc-600'}`} />
                <span className="text-zinc-400">{campaignActive ? 'ACTIVA' : 'PAUSADA'}</span>
              </div>
            </button>
          </>
        ) : null}

        {/* Versión sutil de la app */}
        <div className="text-center pt-0.5">
          <span className="text-[10px] text-zinc-600 font-mono tracking-tight">NexusReach Pro v1.0 &bull; Local IP</span>
        </div>
      </div>
    </aside>
  );
}
