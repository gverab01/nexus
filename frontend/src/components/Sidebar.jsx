import React from 'react';
import { 
  Users, 
  ListFilter, 
  GitFork, 
  Terminal, 
  ShieldCheck, 
  LayoutDashboard, 
  Search, 
  LogOut,
  Building2,
  Briefcase,
  Home,
  UserPlus,
  Eye,
  MessageSquare,
  UserCheck,
  Settings
} from 'lucide-react';

export default function Sidebar({
  activeTab,
  setActiveTab,
  totalLeadsCount = 0,
  listsCount = 0,
  sequencesCount = 0,
  matchingCount = 0,
  logsCount = 0,
  isExtracting = false,
  linkedinSessionActive = false,
  whatsappSessionActive = false,
  zohoSessionActive = false,
  campaignActive = true,
  onToggleCampaign,
  onLoginLinkedin,
  onLoginWhatsApp,
  onLoginZoho,
  onOpenLinkedin,
  onOpenWhatsApp,
  onOpenZoho,
  onLogoutZoho = null,
  onViewBrowser,
  antibanConfig = {
    horario_laboral_activo: true,
    pausas_antiban_activas: true,
    limites_diarios_activos: true,
  },
  onToggleAntiban = null,
  onOpenAntibanSettings = null,
  currentUser = null,
  selectedWorkspaceTenantId = '',
  selectedWorkspaceName = '',
  onExitWorkspace = null,
  agencyClients = [],
  onSelectWorkspace = null,
  onOpenSubscriptionModal = null,
  onLogout = null
}) {
  const isSuperAdmin = currentUser?.rol === 'SUPER_ADMIN';
  const isAgencyAdmin = currentUser?.rol === 'AGENCY_ADMIN';
  const isCompanyAdmin = currentUser?.rol === 'COMPANY_ADMIN';
  const isAdmin = isSuperAdmin || isAgencyAdmin || isCompanyAdmin;
  const isInTenantWorkspace = Boolean(selectedWorkspaceTenantId);
  const showProspectingControls = !(isSuperAdmin && !isInTenantWorkspace);

  const allAntibanActive = Boolean(
    antibanConfig?.horario_laboral_activo &&
    antibanConfig?.pausas_antiban_activas &&
    antibanConfig?.limites_diarios_activos
  );

  // Grupos de navegación organizados semánticamente
  const groups = [];

  if (isSuperAdmin && !isInTenantWorkspace) {
    groups.push({
      title: 'Administración',
      items: [
        { id: 'super_admin', label: 'Plataforma', icon: Home, badge: null },
        { id: 'admin_clientes', label: 'Clientes', icon: Users, badge: null },
        { id: 'admin_crear_cuenta', label: 'Crear cuenta', icon: UserPlus, badge: null },
      ]
    });
  } else {
    // Modo Operador / Empresa / Workspace: Navegación Ultra-Limpia en 3 Pilares
    const mainItems = [
      { id: 'inicio', label: 'Inicio', icon: Home, badge: null },
      { id: 'audiencia', label: 'Audiencia', icon: Users, badge: totalLeadsCount || null },
      { id: 'campanas', label: 'Campañas', icon: GitFork, badge: sequencesCount || null },
    ];

    if (isAgencyAdmin && !isInTenantWorkspace) {
      groups.push({
        title: 'Agencia',
        items: [
          { id: 'agency_portal', label: 'Portal clientes', icon: Briefcase, badge: 'seats' }
        ]
      });
    }

    groups.push({ title: 'Flujo comercial', items: mainItems });
  }

  return (
    <aside className="w-[232px] h-screen sticky top-0 bg-[#0E0F12] border-r border-[#22252B] flex flex-col shrink-0 select-none z-30">
      
      {/* 1. Cabecera Minimalista de Marca */}
      <div className="h-11 px-3.5 border-b border-[#22252B] flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-5 h-5 rounded bg-zinc-800 border border-zinc-700/60 flex items-center justify-center text-[10px] font-semibold text-zinc-200 tracking-tight shrink-0">
            NR
          </div>
          <span className="font-medium text-[13px] tracking-tight text-[#F1F3F5] truncate">
            NexusReach
          </span>
        </div>
        <span className="text-[10px] font-mono text-zinc-500 bg-zinc-900 px-1.5 py-0.5 rounded border border-zinc-800">
          pro
        </span>
      </div>

      {/* 2. Banner de Workspace contextual (si aplica) */}
      {selectedWorkspaceTenantId && (
        <div className="mx-2 mt-2 px-2.5 py-1.5 rounded bg-[#14161A] border border-[#22252B] flex items-center justify-between text-xs">
          <div className="flex items-center gap-1.5 min-w-0">
            <Building2 className="w-3 h-3 text-zinc-400 shrink-0" />
            <span className="text-[11px] text-zinc-300 font-medium truncate">
              {selectedWorkspaceName || selectedWorkspaceTenantId}
            </span>
          </div>
          {onExitWorkspace && (
            <button
              onClick={onExitWorkspace}
              className="text-[10px] text-zinc-400 hover:text-white px-1 py-0.5 rounded hover:bg-zinc-800 transition"
              title="Volver al espacio principal"
            >
              Salir
            </button>
          )}
        </div>
      )}

      {/* 3. Menú de Navegación Vertical */}
      <div className="flex-1 overflow-y-auto px-2.5 py-3 space-y-4">
        {groups.map((group, gIdx) => (
          <div key={gIdx} className="space-y-0.5">
            <div className="px-2 pb-1 text-[11px] font-semibold text-zinc-400 tracking-wide">
              {group.title}
            </div>
            {group.items.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setActiveTab(item.id)}
                  className={`w-full flex items-center justify-between px-2.5 py-2 rounded-md text-[13px] transition duration-100 cursor-pointer ${
                    isActive
                      ? 'bg-white/[0.10] text-white font-medium'
                      : 'text-zinc-300 hover:text-white hover:bg-white/[0.04]'
                  }`}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <Icon className={`w-4 h-4 shrink-0 ${isActive ? 'text-white' : 'text-zinc-400'}`} />
                    <span className="truncate">{item.label}</span>
                  </div>

                  {item.badge !== null && (
                    <span
                      className={`text-[11px] font-mono px-1.5 py-0.5 rounded-sm shrink-0 leading-none ${
                        item.badge === 'alerta'
                          ? 'bg-amber-950/50 text-amber-300 border border-amber-500/40'
                          : item.badge === 'vivo'
                          ? 'bg-emerald-950/50 text-emerald-300 border border-emerald-500/40 animate-status-pulse'
                          : isActive
                          ? 'bg-white/[0.14] text-zinc-100'
                          : 'text-zinc-400'
                      }`}
                    >
                      {item.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        ))}
      </div>

      {/* 4. Acceso Discreto a Ajustes (Canales, Límites e Historial) */}
      {showProspectingControls && (
        <div className="p-2.5 border-t border-[#22252B] bg-[#0E0F12]">
          <button
            type="button"
            onClick={() => setActiveTab('ajustes')}
            className={`w-full flex items-center justify-between px-2.5 py-2 rounded-md text-[13px] transition cursor-pointer ${
              activeTab === 'ajustes'
                ? 'bg-white/[0.10] text-white font-medium'
                : 'text-zinc-300 hover:text-white hover:bg-white/[0.04]'
            }`}
          >
            <span className="flex items-center gap-2.5 min-w-0">
              <Settings className={`w-4 h-4 shrink-0 ${activeTab === 'ajustes' ? 'text-white' : 'text-zinc-400'}`} />
              <span className="truncate">Ajustes</span>
            </span>
            <span
              className={`w-2 h-2 rounded-full shrink-0 ${
                linkedinSessionActive && allAntibanActive ? 'bg-emerald-400' : 'bg-amber-400'
              }`}
              title={
                linkedinSessionActive && allAntibanActive
                  ? 'LinkedIn conectado y protección activa'
                  : 'Revisa la conexión de LinkedIn o tus límites'
              }
            />
          </button>
        </div>
      )}

      {/* 5. Perfil de Usuario y Logout */}
      {currentUser && (
        <div className="p-2.5 border-t border-[#22252B] flex items-center justify-between gap-1.5 bg-[#0E0F12]">
          <button
            onClick={onOpenSubscriptionModal}
            className="flex items-center gap-2 min-w-0 flex-1 p-1 rounded hover:bg-white/[0.04] transition cursor-pointer text-left"
            title="Ver detalles de la cuenta y suscripción"
          >
            <div className="w-7 h-7 rounded-full bg-zinc-800 border border-zinc-700 flex items-center justify-center text-[11px] font-semibold text-zinc-200 shrink-0">
              {currentUser.nombre ? currentUser.nombre.substring(0, 2).toUpperCase() : 'US'}
            </div>
            <div className="min-w-0 leading-tight">
              <div className="text-xs text-zinc-100 font-medium truncate">
                {currentUser.nombre || 'Usuario'}
              </div>
              <div className="text-[11px] text-zinc-400 truncate">
                {isSuperAdmin ? 'Superadmin' : isAgencyAdmin ? 'Agencia' : 'Operador'}
              </div>
            </div>
          </button>

          <button
            onClick={onLogout}
            title="Cerrar sesión"
            className="p-2 rounded hover:bg-white/[0.06] text-zinc-400 hover:text-white transition cursor-pointer"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      )}
    </aside>
  );
}
