import React, { useState, useEffect } from 'react';
import { 
  Building2, 
  Briefcase,
  Eye,
  Pause,
  Play,
  Clock
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

  useEffect(() => {
    let active = true;
    const check = async () => {
      try {
        const st = await fetchQueueStatus(selectedWorkspaceTenantId);
        if (active) setQueueStatus(st);
      } catch (_) {}
    };
    check();
    const timer = setInterval(check, 10000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [selectedWorkspaceTenantId]);

  const tabLabels = {
    super_admin: 'Plataforma',
    admin_clientes: 'Directorio de clientes',
    admin_crear_cuenta: 'Nueva cuenta',
    agency_portal: 'Portal de agencia',
    prospectos: 'Búsqueda de prospectos',
    leads_directorio: 'Directorio de leads',
    listas: 'Listas y segmentos',
    secuencias: 'Secuencias de outreach',
    dashboard: 'Métricas de rendimiento',
    logs: 'Registro de actividad',
    antiban: 'Seguridad y límites'
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
        {/* Badge Global de Cola Persistente en PostgreSQL */}
        {queueStatus && (queueStatus.pendientes > 0 || queueStatus.en_proceso > 0) && (
          <button
            type="button"
            onClick={() => onNavigateToTab && onNavigateToTab('antiban')}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-indigo-950/60 hover:bg-indigo-900/80 border border-indigo-500/40 text-indigo-300 text-[11px] font-mono transition cursor-pointer"
            title={`Cola central PostgreSQL: ${queueStatus.pendientes} pendientes, ${queueStatus.en_proceso} en curso. Haz clic para ver el configurador y la cola.`}
          >
            <Clock className="w-3 h-3 text-indigo-400 animate-pulse" />
            <span>Cola: {queueStatus.pendientes} pend.</span>
          </button>
        )}

        {/* Toggle de Despacho / Campaña */}
        {onToggleCampaign && (
          <button
            onClick={onToggleCampaign}
            className={`flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-medium transition cursor-pointer border ${
              campaignActive
                ? 'bg-emerald-950/20 border-emerald-600/30 text-emerald-400 hover:bg-emerald-950/40'
                : 'bg-amber-950/20 border-amber-600/30 text-amber-400 hover:bg-amber-950/40'
            }`}
            title={campaignActive ? 'Pausar despacho de tareas' : 'Reanudar despacho de tareas'}
          >
            {campaignActive ? (
              <>
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-status-pulse" />
                <span>Despacho activo</span>
                <Pause className="w-2.5 h-2.5 ml-0.5 opacity-60" />
              </>
            ) : (
              <>
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                <span>Despacho en pausa</span>
                <Play className="w-2.5 h-2.5 ml-0.5 opacity-60" />
              </>
            )}
          </button>
        )}

        {/* Ver Navegador de fondo */}
        {onViewBrowser && (
          <button
            onClick={onViewBrowser}
            className="flex items-center gap-1.5 px-2 py-1 rounded bg-[#14161A] hover:bg-zinc-800 border border-[#22252B] text-zinc-400 hover:text-zinc-200 text-[11px] font-medium transition cursor-pointer"
            title="Mostrar ventana de Chromium automatizado"
          >
            <Eye className="w-3 h-3 text-zinc-400" />
            <span className="hidden sm:inline">Navegador</span>
          </button>
        )}
      </div>
    </header>
  );
}
