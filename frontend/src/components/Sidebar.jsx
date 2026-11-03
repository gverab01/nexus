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
  MessageSquare
} from 'lucide-react';

export default function Sidebar({
  activeTab,
  setActiveTab,
  totalLeadsCount = 0,
  listsCount = 0,
  sequencesCount = 0,
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
    // Modo Operador / Empresa / Workspace
    const prospectingItems = [
      { id: 'prospectos', label: 'Búsqueda', icon: Search, badge: null },
      { id: 'leads_directorio', label: 'Directorio', icon: Users, badge: totalLeadsCount || null },
      { id: 'listas', label: 'Listas', icon: ListFilter, badge: listsCount || null },
    ];

    const automationItems = [
      { id: 'secuencias', label: 'Secuencias', icon: GitFork, badge: sequencesCount || null },
      { id: 'dashboard', label: 'Métricas', icon: LayoutDashboard, badge: null },
    ];

    const systemItems = [
      { id: 'antiban', label: 'Seguridad', icon: ShieldCheck, badge: allAntibanActive ? 'ok' : 'alerta' },
      { id: 'logs', label: 'Actividad', icon: Terminal, badge: isExtracting ? 'vivo' : logsCount || null },
    ];

    if (isAgencyAdmin && !isInTenantWorkspace) {
      groups.push({
        title: 'Agencia',
        items: [
          { id: 'agency_portal', label: 'Portal clientes', icon: Briefcase, badge: 'seats' }
        ]
      });
    }

    groups.push(
      { title: 'Prospección', items: prospectingItems },
      { title: 'Automatización', items: automationItems },
      { title: 'Sistema', items: systemItems }
    );
  }

  return (
    <aside className="w-[216px] h-screen sticky top-0 bg-[#0E0F12] border-r border-[#22252B] flex flex-col shrink-0 select-none z-30">
      
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
      <div className="flex-1 overflow-y-auto px-2 py-3 space-y-4">
        {groups.map((group, gIdx) => (
          <div key={gIdx} className="space-y-0.5">
            <div className="px-2 pb-1 text-[10px] font-medium text-zinc-500 tracking-wider">
              {group.title}
            </div>
            {group.items.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setActiveTab(item.id)}
                  className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-md text-[13px] transition duration-100 cursor-pointer ${
                    isActive
                      ? 'bg-white/[0.08] text-white font-medium'
                      : 'text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.03]'
                  }`}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <Icon className={`w-3.5 h-3.5 shrink-0 ${isActive ? 'text-white' : 'text-zinc-400'}`} />
                    <span className="truncate">{item.label}</span>
                  </div>

                  {item.badge !== null && (
                    <span
                      className={`text-[10px] font-mono px-1.5 py-0.5 rounded-sm shrink-0 leading-none ${
                        item.badge === 'alerta'
                          ? 'bg-amber-950/40 text-amber-400 border border-amber-600/30'
                          : item.badge === 'vivo'
                          ? 'bg-emerald-950/40 text-emerald-400 border border-emerald-600/30 animate-status-pulse'
                          : isActive
                          ? 'bg-white/[0.1] text-zinc-200'
                          : 'text-zinc-500'
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

      {/* 4. Dock Inferior de Canales (LinkedIn, WhatsApp, Zoho) */}
      {showProspectingControls && (
        <div className="p-2 border-t border-[#22252B] bg-[#0E0F12]">
          <div className="px-1.5 pb-1 flex items-center justify-between text-[10px] text-zinc-500 font-medium">
            <span>Canales de prospección</span>
            {onViewBrowser && (
              <button
                onClick={onViewBrowser}
                className="text-zinc-500 hover:text-zinc-300 transition cursor-pointer"
                title="Ver navegador de fondo"
              >
                <Eye className="w-3 h-3" />
              </button>
            )}
          </div>

          <div className="grid grid-cols-3 gap-1">
            {/* LinkedIn */}
            <button
              onClick={onOpenLinkedin || onLoginLinkedin}
              className={`flex items-center justify-center gap-1.5 py-1.5 px-1 rounded border text-[11px] font-medium transition cursor-pointer ${
                linkedinSessionActive
                  ? 'bg-sky-950/30 border-sky-800/40 text-sky-300 hover:bg-sky-900/40'
                  : 'bg-[#14161A] border-[#22252B] text-zinc-400 hover:text-zinc-200 hover:border-zinc-700'
              }`}
              title={linkedinSessionActive ? 'LinkedIn activo (click para abrir ventana)' : 'Conectar cuenta de LinkedIn'}
            >
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${linkedinSessionActive ? 'bg-sky-400' : 'bg-zinc-600'}`} />
              <span className="truncate">LinkedIn</span>
            </button>

            {/* WhatsApp */}
            <button
              onClick={onOpenWhatsApp || onLoginWhatsApp}
              className={`flex items-center justify-center gap-1.5 py-1.5 px-1 rounded border text-[11px] font-medium transition cursor-pointer ${
                whatsappSessionActive
                  ? 'bg-emerald-950/30 border-emerald-800/40 text-emerald-300 hover:bg-emerald-900/40'
                  : 'bg-[#14161A] border-[#22252B] text-zinc-400 hover:text-zinc-200 hover:border-zinc-700'
              }`}
              title={whatsappSessionActive ? 'WhatsApp Web activo' : 'Vincular WhatsApp mediante código QR'}
            >
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${whatsappSessionActive ? 'bg-emerald-400' : 'bg-zinc-600'}`} />
              <span className="truncate">WhatsApp</span>
            </button>

            {/* Zoho */}
            <button
              onClick={zohoSessionActive ? onOpenZoho : (onLoginZoho || onOpenZoho)}
              className={`flex items-center justify-center gap-1.5 py-1.5 px-1 rounded border text-[11px] font-medium transition cursor-pointer ${
                zohoSessionActive
                  ? 'bg-amber-950/30 border-amber-800/40 text-amber-300 hover:bg-amber-900/40'
                  : 'bg-[#14161A] border-[#22252B] text-zinc-400 hover:text-zinc-200 hover:border-zinc-700'
              }`}
              title={zohoSessionActive ? 'Zoho CRM sincronizado' : 'Conectar cuenta de Zoho CRM'}
            >
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${zohoSessionActive ? 'bg-amber-400' : 'bg-zinc-600'}`} />
              <span className="truncate">Zoho</span>
            </button>
          </div>
        </div>
      )}

      {/* 5. Perfil de Usuario y Logout */}
      {currentUser && (
        <div className="p-2 border-t border-[#22252B] flex items-center justify-between gap-1.5 bg-[#0E0F12]">
          <button
            onClick={onOpenSubscriptionModal}
            className="flex items-center gap-2 min-w-0 flex-1 p-1 rounded hover:bg-white/[0.04] transition cursor-pointer text-left"
            title="Ver detalles de la cuenta y suscripción"
          >
            <div className="w-6 h-6 rounded-full bg-zinc-800 border border-zinc-700 flex items-center justify-center text-[10px] font-semibold text-zinc-300 shrink-0">
              {currentUser.nombre ? currentUser.nombre.substring(0, 2).toUpperCase() : 'US'}
            </div>
            <div className="min-w-0 leading-tight">
              <div className="text-xs text-zinc-200 font-medium truncate">
                {currentUser.nombre || 'Usuario'}
              </div>
              <div className="text-[10px] text-zinc-500 truncate">
                {isSuperAdmin ? 'Superadmin' : isAgencyAdmin ? 'Agencia' : 'Operador'}
              </div>
            </div>
          </button>

          <button
            onClick={onLogout}
            title="Cerrar sesión"
            className="p-1.5 rounded hover:bg-white/[0.06] text-zinc-500 hover:text-zinc-200 transition cursor-pointer"
          >
            <LogOut className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </aside>
  );
}
