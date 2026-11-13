import React, { useState, useEffect } from 'react';
import { 
  Building2, 
  Briefcase,
  Eye,
  Pause,
  Play,
  Clock,
  Sun,
  Moon
} from 'lucide-react';
import { fetchQueueStatus } from '../services/api';

export default function TopBar({
  activeTab,
  campaignActive = true,
  onToggleCampaign = null,
  onViewBrowser = null,
  currentUser = null,
  agencyClients = [],
  selectedWorkspaceTenantId = '',
  selectedWorkspaceName = '',
  onSelectWorkspace = null,
  onExitWorkspace = null,
  onNavigateToTab = null
}) {
  const isSuperAdmin = currentUser?.rol === 'SUPER_ADMIN';
  const isAgencyAdmin = currentUser?.rol === 'AGENCY_ADMIN';

  const [queueStatus, setQueueStatus] = useState(null);
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem('nexusreach_theme') || 'dark';
    } catch {
      return 'dark';
    }
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem('nexusreach_theme', theme);
    } catch {}
  }, [theme]);

  useEffect(() => {
    let active = true;
    const check = async () => {
      if (document.hidden) return;
      try {
        const st = await fetchQueueStatus(selectedWorkspaceTenantId);
        if (active) setQueueStatus(st);
      } catch (_) {}
    };
    check();
    const timer = setInterval(check, 15000);
    const onVis = () => { if (!document.hidden) check(); };
    document.addEventListener('visibilitychange', onVis);
    return () => {
      active = false;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [selectedWorkspaceTenantId]);

  const tabLabels = {
    super_admin: 'Plataforma',
    admin_clientes: 'Directorio de clientes',
    admin_crear_cuenta: 'Nueva cuenta',
    agency_portal: 'Portal de agencia',
    inicio: 'Inicio · Hoy',
    audiencia: 'Audiencia y contactos',
    campanas: 'Campañas',
    ajustes: 'Ajustes y canales',
    prospectos: 'Audiencia · Buscar',
    matching: 'Audiencia · Validar',
    leads_directorio: 'Audiencia · Contactos',
    listas: 'Audiencia · Listas',
    secuencias: 'Campañas',
    dashboard: 'Resultados y KPIs',
    logs: 'Ajustes · Historial',
    antiban: 'Ajustes · Protección'
  };

  const currentTitle = tabLabels[activeTab] || 'Workspace';

  return (
    <header className="h-10 border-b border-[#22252B] bg-[#0E0F12] px-4 flex items-center justify-between shrink-0 select-none z-20">
      
      {/* 1. Izquierda: Título contextual / Breadcrumb */}
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-[13px] font-medium text-[#F1F3F5] truncate">
          {currentTitle}
        </span>
      </div>

      {/* 2. Centro: Selector de Workspace (para agencias o superadmins) */}
      <div className="flex items-center gap-2">
        {isAgencyAdmin && agencyClients.length > 0 && (
          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-[#14161A] border border-[#22252B] text-xs">
            <Briefcase className="w-3 h-3 text-zinc-400 shrink-0" />
            <select
              value={selectedWorkspaceTenantId}
              onChange={(e) => onSelectWorkspace && onSelectWorkspace(e.target.value)}
              className="bg-transparent text-zinc-300 text-[11px] focus:outline-none cursor-pointer"
            >
              <option value="" className="bg-[#14161A] text-zinc-200">Sede propia</option>
              {agencyClients.map((c) => (
                <option key={c.id} value={c.id} className="bg-[#14161A] text-zinc-200">
                  {c.razon_social}
                </option>
              ))}
            </select>
          </div>
        )}

        {isSuperAdmin && selectedWorkspaceTenantId && (
          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-[#14161A] border border-[#22252B] text-xs">
            <Building2 className="w-3 h-3 text-zinc-400 shrink-0" />
            <span className="text-[11px] text-zinc-300 truncate max-w-[140px]">
              {selectedWorkspaceName || selectedWorkspaceTenantId}
            </span>
            {onExitWorkspace && (
              <button
                onClick={onExitWorkspace}
                className="text-[10px] text-zinc-400 hover:text-white transition ml-1"
                title="Volver a consola principal"
              >
                Salir
              </button>
            )}
          </div>
        )}
      </div>

      {/* 3. Derecha: Controles de Acción (Despacho y Navegador de fondo) */}
      <div className="flex items-center gap-2 shrink-0">
        {/* Badge Global de Envíos Programados */}
        {queueStatus && (queueStatus.pendientes > 0 || queueStatus.en_proceso > 0) && (
          <button
            type="button"
            onClick={() => onNavigateToTab && onNavigateToTab('antiban')}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-indigo-950/60 hover:bg-indigo-900/80 border border-indigo-500/40 text-indigo-200 text-xs font-medium transition cursor-pointer"
            title={`Tienes ${queueStatus.pendientes} envíos programados y ${queueStatus.en_proceso} en curso. Haz clic para revisar límites y horarios.`}
          >
            <Clock className="w-3.5 h-3.5 text-indigo-400 animate-pulse" />
            <span>Envíos programados: {queueStatus.pendientes}</span>
          </button>
        )}

        {/* Control Maestro de Campañas */}
        {onToggleCampaign && (
          <button
            onClick={onToggleCampaign}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition cursor-pointer border ${
              campaignActive
                ? 'bg-emerald-950/30 border-emerald-600/40 text-emerald-300 hover:bg-emerald-950/50'
                : 'bg-amber-950/30 border-amber-600/40 text-amber-300 hover:bg-amber-950/50'
            }`}
            title={campaignActive ? 'Pausar todos los envíos automáticos' : 'Reanudar envíos automáticos'}
          >
            {campaignActive ? (
              <>
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-status-pulse" />
                <span>Campaña activa</span>
                <Pause className="w-3 h-3 ml-0.5 opacity-80" />
              </>
            ) : (
              <>
                <span className="w-2 h-2 rounded-full bg-amber-400" />
                <span>Campaña en pausa</span>
                <Play className="w-3 h-3 ml-0.5 opacity-80" />
              </>
            )}
          </button>
        )}

        {/* Selector de Tema (Oscuro / Claro) */}
        <button
          type="button"
          onClick={() => setTheme((prev) => (prev === 'light' ? 'dark' : 'light'))}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-[#14161A] hover:bg-zinc-800 border border-[#22252B] text-zinc-300 hover:text-white text-xs font-medium transition cursor-pointer"
          title={theme === 'light' ? 'Cambiar a modo oscuro' : 'Cambiar a modo claro (oficina)'}
          aria-label="Cambiar tema visual"
        >
          {theme === 'light' ? (
            <Moon className="w-3.5 h-3.5 text-zinc-300" />
          ) : (
            <Sun className="w-3.5 h-3.5 text-zinc-300" />
          )}
        </button>

        {/* Ver Navegador de fondo */}
        {onViewBrowser && (
          <button
            onClick={onViewBrowser}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-[#14161A] hover:bg-zinc-800 border border-[#22252B] text-zinc-300 hover:text-white text-xs font-medium transition cursor-pointer"
            title="Mostrar ventana de Chromium automatizado"
          >
            <Eye className="w-3.5 h-3.5 text-zinc-300" />
            <span className="hidden sm:inline">Navegador</span>
          </button>
        )}
      </div>
    </header>
  );
}
