// Vista de sucesos de secuencias y auditoría en tiempo real para Operador y Administradores
import React, { useState, useEffect, useRef } from 'react';
import { 
  Terminal, 
  RefreshCw, 
  Trash2, 
  Search, 
  Filter, 
  CheckCircle2, 
  AlertCircle, 
  AlertTriangle, 
  Info, 
  Activity, 
  Layers,
  Clock,
  User,
  ExternalLink,
  GitFork,
  Send,
  Eye,
  Mail,
  MessageSquare,
  PhoneCall,
  ShieldCheck,
  Building,
  UserCheck,
  PauseCircle,
  ChevronDown,
  ChevronRight
} from 'lucide-react';
import { fetchLogs, fetchLogStats, clearLogs, fetchSequenceEvents } from '../../services/api';

export default function ActivityLogsView({ onStatusChange, currentUser }) {
  const [activeSubTab, setActiveSubTab] = useState('sucesos'); // 'sucesos' | 'terminal'
  
  // Sucesos de Secuencias
  const [sucesos, setSucesos] = useState([]);
  const [sucesosStats, setSucesosStats] = useState({ total_sucesos: 0, por_tipo: {} });
  const [selectedEventType, setSelectedEventType] = useState('');
  const [sucesosSearch, setSucesosSearch] = useState('');
  const [loadingSucesos, setLoadingSucesos] = useState(true);

  // Terminal Logs
  const [logs, setLogs] = useState([]);
  const [stats, setStats] = useState({
    total_logs: 0,
    is_extracting_now: false,
    last_extractor_activity: null,
    level_counts: {},
    module_counts: {},
  });
  const [loadingLogs, setLoadingLogs] = useState(true);
  const [selectedModule, setSelectedModule] = useState('');
  const [selectedLevel, setSelectedLevel] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedLogIds, setExpandedLogIds] = useState(new Set());

  // Auto refresco
  const [autoRefresh, setAutoRefresh] = useState(true);

  const intervalRef = useRef(null);
  const searchTimeoutRef = useRef(null);

  const isSuperAdmin = currentUser?.rol === 'SUPER_ADMIN';

  useEffect(() => {
    loadAllData();

    if (autoRefresh) {
      intervalRef.current = setInterval(() => {
        loadAllData(false);
      }, 3500);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [selectedEventType, sucesosSearch, selectedModule, selectedLevel, autoRefresh, activeSubTab]);

  async function loadAllData(showSpinner = true) {
    if (activeSubTab === 'sucesos') {
      await loadSucesosData(showSpinner);
    } else {
      await loadLogsData(showSpinner);
    }
  }

  async function loadSucesosData(showSpinner = true) {
    if (showSpinner) setLoadingSucesos(true);
    try {
      const data = await fetchSequenceEvents({
        tipo_evento: selectedEventType || undefined,
        search: sucesosSearch || undefined,
        limit: 100
      });
      setSucesos(data.sucesos || []);
      setSucesosStats(data.stats || { total_sucesos: 0, por_tipo: {} });
    } catch (err) {
      console.error('Error cargando sucesos de secuencias:', err);
    } finally {
      if (showSpinner) setLoadingSucesos(false);
    }
  }

  async function loadLogsData(showSpinner = true) {
    if (showSpinner) setLoadingLogs(true);
    try {
      const [logsData, statsData] = await Promise.all([
        fetchLogs({
          module: selectedModule,
          level: selectedLevel,
          search: searchQuery,
          limit: 100,
        }),
        fetchLogStats().catch(() => ({})),
      ]);

      setLogs(logsData.logs || []);
      setStats(statsData);

      if (onStatusChange) {
        onStatusChange({
          isExtracting: Boolean(statsData.is_extracting_now),
          totalLogs: statsData.total_logs || 0,
        });
      }
    } catch (err) {
      console.error('Error cargando logs de terminal:', err);
    } finally {
      if (showSpinner) setLoadingLogs(false);
    }
  }

  function handleSucesosSearchChange(e) {
    const val = e.target.value;
    setSucesosSearch(val);
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    searchTimeoutRef.current = setTimeout(() => {
      loadSucesosData(false);
    }, 350);
  }

  function handleTerminalSearchChange(e) {
    const val = e.target.value;
    setSearchQuery(val);
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    searchTimeoutRef.current = setTimeout(() => {
      loadLogsData(false);
    }, 350);
  }

  async function handleClearLogs() {
    if (!confirm('¿Deseas vaciar el historial de eventos del sistema? Esta acción es irreversible.')) return;
    try {
      await clearLogs();
      await loadLogsData();
    } catch (err) {
      alert(`Error al limpiar logs: ${err.message}`);
    }
  }

  function toggleLogDetails(logId) {
    setExpandedLogIds((prev) => {
      const next = new Set(prev);
      if (next.has(logId)) next.delete(logId);
      else next.add(logId);
      return next;
    });
  }

  function formatRelativeTime(isoString) {
    if (!isoString) return 'Reciente';
    try {
      const date = new Date(isoString);
      if (isNaN(date.getTime())) return isoString;
      const now = new Date();
      const diffSec = Math.floor((now - date) / 1000);
      if (diffSec < 60) return `Hace ${Math.max(1, diffSec)}s`;
      const diffMin = Math.floor(diffSec / 60);
      if (diffMin < 60) return `Hace ${diffMin}m`;
      const diffHr = Math.floor(diffMin / 60);
      if (diffHr < 24) return `Hace ${diffHr}h`;
      return date.toLocaleDateString('es-ES', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
    } catch {
      return isoString;
    }
  }

  function getEventBadge(tipo) {
    switch (tipo) {
      case 'VISITA_PERFIL_SECUENCIA':
        return {
          label: 'Visita de Perfil',
          color: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/30',
          icon: Eye
        };
      case 'INVITACION_ENVIADA_SECUENCIA':
        return {
          label: 'Invitación LinkedIn',
          color: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
          icon: UserCheck
        };
      case 'MENSAJE_LINKEDIN_ENVIADO':
        return {
          label: 'Mensaje LinkedIn',
          color: 'bg-sky-500/10 text-sky-400 border-sky-500/30',
          icon: MessageSquare
        };
      case 'CORREO_WORKSPACE_ENVIADO':
        return {
          label: 'Correo Workspace',
          color: 'bg-purple-500/10 text-purple-400 border-purple-500/30',
          icon: Mail
        };
      case 'WHATSAPP_WEB_ENVIADO':
        return {
          label: 'WhatsApp Web',
          color: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
          icon: PhoneCall
        };
      case 'PAUSA_PROGRAMADA':
        return {
          label: 'Pausa Anti-Ban',
          color: 'bg-zinc-800 text-zinc-300 border-zinc-700',
          icon: PauseCircle
        };
      case 'ANTI_COLISION_ACTIVADO':
        return {
          label: 'Cruce Zoho Anti-Colisión',
          color: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
          icon: Building
        };
      case 'CONEXION_ACEPTADA':
        return {
          label: 'Conexión Aceptada',
          color: 'bg-teal-500/10 text-teal-400 border-teal-500/30',
          icon: CheckCircle2
        };
      default:
        return {
          label: tipo.replace('SECUENCIA_', '').replace(/_/g, ' '),
          color: 'bg-zinc-800 text-zinc-300 border-zinc-700',
          icon: Activity
        };
    }
  }

  const modules = ['EXTRACTOR', 'SEQUENCES', 'BROWSER', 'SAFETY', 'LISTS', 'SYSTEM'];
  const levels = ['SUCCESS', 'INFO', 'WARNING', 'ERROR'];

  return (
    <div className="space-y-6">
      {/* Selector de Sub-Vistas (Tabs) */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-zinc-800">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setActiveSubTab('sucesos')}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-medium transition cursor-pointer ${
              activeSubTab === 'sucesos'
                ? 'bg-sky-500 text-zinc-950 shadow-md shadow-sky-500/20 font-semibold'
                : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200 border border-zinc-800'
            }`}
          >
            <GitFork className="w-4 h-4" />
            <span>Sucesos de Secuencias</span>
            {sucesosStats.total_sucesos > 0 && (
              <span className={`px-2 py-0.5 rounded-full text-[10px] ${
                activeSubTab === 'sucesos' ? 'bg-zinc-950/20 text-zinc-950 font-bold' : 'bg-zinc-800 text-zinc-300'
              }`}>
                {sucesosStats.total_sucesos}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveSubTab('terminal')}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-medium transition cursor-pointer ${
              activeSubTab === 'terminal'
                ? 'bg-sky-500 text-zinc-950 shadow-md shadow-sky-500/20 font-semibold'
                : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200 border border-zinc-800'
            }`}
          >
            <Terminal className="w-4 h-4" />
            <span>Logs Técnicos del Sistema</span>
            {stats.total_logs > 0 && (
              <span className={`px-2 py-0.5 rounded-full text-[10px] ${
                activeSubTab === 'terminal' ? 'bg-zinc-950/20 text-zinc-950 font-bold' : 'bg-zinc-800 text-zinc-300'
              }`}>
                {stats.total_logs}
              </span>
            )}
          </button>
        </div>

        {/* Controles de auto-refresco y recarga manual */}
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-zinc-400 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded bg-zinc-950 border-zinc-700 text-sky-500 focus:ring-0"
            />
            <span className="text-[11px]">En vivo (3.5s)</span>
          </label>

          <button
            onClick={() => loadAllData(true)}
            title="Refrescar datos ahora"
            className="p-2 rounded-xl bg-zinc-900 border border-zinc-800 hover:bg-zinc-800 text-zinc-300 transition cursor-pointer"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${(loadingSucesos || loadingLogs) ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* ======================================================== */}
      {/* VISTA 1: SUCESOS DE SECUENCIAS (OPERADOR Y AUDITORÍA)     */}
      {/* ======================================================== */}
      {activeSubTab === 'sucesos' && (
        <div className="space-y-6">
          {/* Métricas Resumen de Sucesos */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="p-3.5 rounded-xl bg-zinc-900/40 border border-zinc-800">
              <div className="flex items-center justify-between text-zinc-500 text-xs mb-1">
                <span>Acciones Totales</span>
                <GitFork className="w-4 h-4 text-sky-400" />
              </div>
              <div className="text-xl font-bold text-zinc-100 font-mono">
                {sucesosStats.total_sucesos || 0}
              </div>
            </div>

            <div className="p-3.5 rounded-xl bg-zinc-900/40 border border-zinc-800">
              <div className="flex items-center justify-between text-zinc-500 text-xs mb-1">
                <span>Perfiles Visitados</span>
                <Eye className="w-4 h-4 text-indigo-400" />
              </div>
              <div className="text-xl font-bold text-indigo-400 font-mono">
                {sucesosStats.por_tipo?.VISITA_PERFIL_SECUENCIA || 0}
              </div>
            </div>

            <div className="p-3.5 rounded-xl bg-zinc-900/40 border border-zinc-800">
              <div className="flex items-center justify-between text-zinc-500 text-xs mb-1">
                <span>Invitaciones Enviadas</span>
                <UserCheck className="w-4 h-4 text-emerald-400" />
              </div>
              <div className="text-xl font-bold text-emerald-400 font-mono">
                {sucesosStats.por_tipo?.INVITACION_ENVIADA_SECUENCIA || 0}
              </div>
            </div>

            <div className="p-3.5 rounded-xl bg-zinc-900/40 border border-zinc-800">
              <div className="flex items-center justify-between text-zinc-500 text-xs mb-1">
                <span>Mensajes Despachados</span>
                <MessageSquare className="w-4 h-4 text-sky-400" />
              </div>
              <div className="text-xl font-bold text-sky-400 font-mono">
                {(sucesosStats.por_tipo?.MENSAJE_LINKEDIN_ENVIADO || 0) + (sucesosStats.por_tipo?.CORREO_WORKSPACE_ENVIADO || 0) + (sucesosStats.por_tipo?.WHATSAPP_WEB_ENVIADO || 0)}
              </div>
            </div>
          </div>

          {/* Filtros de Sucesos */}
          <div className="p-4 rounded-xl bg-zinc-900/30 border border-zinc-800 flex flex-col md:flex-row md:items-center justify-between gap-3">
            <div className="relative w-full md:w-80">
              <Search className="w-3.5 h-3.5 text-zinc-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={sucesosSearch}
                onChange={handleSucesosSearchChange}
                placeholder="Buscar por prospecto, cargo o colegio..."
                className="w-full bg-zinc-950 border border-zinc-800 pl-9 pr-3 py-1.5 rounded-lg text-xs text-zinc-200 placeholder-zinc-500 focus:outline-hidden focus:border-sky-500"
              />
            </div>

            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-[11px] text-zinc-400 mr-1 flex items-center gap-1">
                <Filter className="w-3 h-3" />
                <span>Tipo de Acción:</span>
              </span>
              <button
                onClick={() => setSelectedEventType('')}
                className={`px-2.5 py-1 rounded-md text-[11px] transition cursor-pointer ${
                  selectedEventType === ''
                    ? 'bg-zinc-800 text-white font-medium border border-zinc-700'
                    : 'text-zinc-400 hover:text-zinc-200 bg-zinc-950'
                }`}
              >
                Todas
              </button>
              <button
                onClick={() => setSelectedEventType('VISITA_PERFIL_SECUENCIA')}
                className={`px-2.5 py-1 rounded-md text-[11px] transition cursor-pointer ${
                  selectedEventType === 'VISITA_PERFIL_SECUENCIA'
                    ? 'bg-indigo-950 text-indigo-400 font-medium border border-indigo-800'
                    : 'text-zinc-400 hover:text-zinc-200 bg-zinc-950'
                }`}
              >
                Visitas
              </button>
              <button
                onClick={() => setSelectedEventType('INVITACION_ENVIADA_SECUENCIA')}
                className={`px-2.5 py-1 rounded-md text-[11px] transition cursor-pointer ${
                  selectedEventType === 'INVITACION_ENVIADA_SECUENCIA'
                    ? 'bg-emerald-950 text-emerald-400 font-medium border border-emerald-800'
                    : 'text-zinc-400 hover:text-zinc-200 bg-zinc-950'
                }`}
              >
                Invitaciones
              </button>
              <button
                onClick={() => setSelectedEventType('MENSAJE_LINKEDIN_ENVIADO')}
                className={`px-2.5 py-1 rounded-md text-[11px] transition cursor-pointer ${
                  selectedEventType === 'MENSAJE_LINKEDIN_ENVIADO'
                    ? 'bg-sky-950 text-sky-400 font-medium border border-sky-800'
                    : 'text-zinc-400 hover:text-zinc-200 bg-zinc-950'
                }`}
              >
                Mensajes
              </button>
              <button
                onClick={() => setSelectedEventType('PAUSA_PROGRAMADA')}
                className={`px-2.5 py-1 rounded-md text-[11px] transition cursor-pointer ${
                  selectedEventType === 'PAUSA_PROGRAMADA'
                    ? 'bg-zinc-800 text-zinc-200 font-medium border border-zinc-600'
                    : 'text-zinc-400 hover:text-zinc-200 bg-zinc-950'
                }`}
              >
                Pausas
              </button>
            </div>
          </div>

          {/* Lista Cronológica de Sucesos */}
          <div className="rounded-xl border border-zinc-800 bg-zinc-950 overflow-hidden shadow-xl">
            <div className="px-4 py-3 border-b border-zinc-800/80 bg-zinc-900/60 flex items-center justify-between text-xs">
              <div className="flex items-center gap-2 font-semibold text-zinc-300">
                <Clock className="w-4 h-4 text-sky-400" />
                <span>HISTORIAL DE ACCIONES EJECUTADAS</span>
              </div>
              <span className="text-[11px] text-zinc-500 font-mono">
                {sucesos.length} sucesos registrados
              </span>
            </div>

            <div className="divide-y divide-zinc-900">
              {sucesos.length === 0 ? (
                <div className="py-16 text-center space-y-3">
                  <div className="w-12 h-12 rounded-2xl bg-zinc-900 border border-zinc-800 flex items-center justify-center mx-auto text-zinc-500">
                    <GitFork className="w-6 h-6" />
                  </div>
                  <div className="text-sm font-medium text-zinc-300">
                    Aún no se han ejecutado acciones de secuencias
                  </div>
                  <div className="text-xs text-zinc-500 max-w-sm mx-auto">
                    Cuando las secuencias comiencen a procesar pasos (visitas a perfiles, invitaciones, mensajes o pausas programadas), aparecerán aquí con su timestamp y detalle.
                  </div>
                </div>
              ) : (
                sucesos.map((suceso) => {
                  const badge = getEventBadge(suceso.tipo_evento);
                  const Icon = badge.icon;
                  return (
                    <div key={suceso.id} className="p-4 hover:bg-zinc-900/30 transition flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                      <div className="flex items-start gap-3.5 flex-1 min-w-0">
                        {/* Icono de Acción */}
                        <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 border mt-0.5 ${badge.color}`}>
                          <Icon className="w-4 h-4" />
                        </div>

                        {/* Detalles del Suceso y Lead */}
                        <div className="space-y-1.5 flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className={`px-2 py-0.5 rounded-md text-[10px] font-medium border uppercase tracking-wider ${badge.color}`}>
                              {badge.label}
                            </span>

                            {suceso.lead_nombre && (
                              <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-200">
                                <span>{suceso.lead_nombre}</span>
                                {suceso.perfil_url && (
                                  <a
                                    href={suceso.perfil_url}
                                    target="_blank"
                                    rel="noreferrer"
                                    title="Abrir perfil de LinkedIn"
                                    className="text-zinc-500 hover:text-sky-400 transition"
                                  >
                                    <ExternalLink className="w-3 h-3" />
                                  </a>
                                )}
                              </div>
                            )}

                            {(suceso.cargo_actual || suceso.institucion_actual) && (
                              <span className="text-[11px] text-zinc-400 truncate max-w-xs">
                                · {suceso.cargo_actual || suceso.cargo_titular || ''} {suceso.institucion_actual ? `en ${suceso.institucion_actual}` : ''}
                              </span>
                            )}
                          </div>

                          {/* Descripción / Detalle de la Acción */}
                          <p className="text-xs text-zinc-300 leading-relaxed font-sans">
                            {suceso.descripcion}
                          </p>

                          {/* Metadata adicional si existe */}
                          {suceso.metadata && Object.keys(suceso.metadata).length > 0 && suceso.metadata.secuencia_nombre && (
                            <div className="flex items-center gap-1.5 text-[10px] text-zinc-500 pt-0.5">
                              <span className="text-zinc-600">Secuencia:</span>
                              <span className="text-zinc-400 font-medium">{suceso.metadata.secuencia_nombre}</span>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Timestamp con hora precisa */}
                      <div className="flex sm:flex-col items-center sm:items-end justify-between sm:justify-start gap-1 shrink-0 text-right">
                        <span className="text-xs font-medium text-zinc-300 font-mono">
                          {formatRelativeTime(suceso.timestamp)}
                        </span>
                        <span className="text-[10px] text-zinc-500 font-mono">
                          {suceso.timestamp ? suceso.timestamp.replace('T', ' ').substring(0, 19) : ''}
                        </span>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* VISTA 2: TERMINAL Y TELEMETRÍA TÉCNICA                   */}
      {/* ======================================================== */}
      {activeSubTab === 'terminal' && (
        <div className="space-y-6">
          {/* Banner de Estado del Motor */}
          <div className={`p-4 rounded-xl border transition-all ${
            stats.is_extracting_now
              ? 'bg-emerald-950/30 border-emerald-500/40 shadow-lg shadow-emerald-950/50'
              : 'bg-zinc-900/40 border-zinc-800'
          }`}>
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 border ${
                  stats.is_extracting_now
                    ? 'bg-emerald-500/20 border-emerald-500/30 text-emerald-300'
                    : 'bg-zinc-800 border-zinc-700 text-zinc-400'
                }`}>
                  <Activity className={`w-5 h-5 ${stats.is_extracting_now ? 'animate-pulse' : ''}`} />
                </div>

                <div>
                  <div className="flex items-center gap-2">
                    <span className={`w-2.5 h-2.5 rounded-full ${
                      stats.is_extracting_now ? 'bg-emerald-400 animate-ping' : 'bg-zinc-500'
                    }`} />
                    <h2 className="text-sm font-semibold text-zinc-100">
                      {stats.is_extracting_now
                        ? 'EXTRACCIÓN ACTIVA EN PROCESO'
                        : 'MOTOR EN ESPERA / INACTIVO'}
                    </h2>
                  </div>
                  <p className="text-xs text-zinc-400 mt-0.5">
                    {stats.is_extracting_now
                      ? 'BrowserOS está analizando perfiles y recopilando datos de directivos en vivo.'
                      : `Listo para operar. Última actividad registrada: ${stats.last_extractor_activity || 'Reciente'}`}
                  </p>
                </div>
              </div>

              {/* Estadísticas de Eventos */}
              <div className="flex items-center gap-3 text-xs font-mono self-start sm:self-auto">
                <div className="px-3 py-1.5 rounded-lg bg-zinc-950/80 border border-zinc-800">
                  <span className="text-zinc-500 block text-[10px]">TOTAL EVENTOS</span>
                  <span className="font-semibold text-zinc-200">{stats.total_logs || 0}</span>
                </div>

                <div className="px-3 py-1.5 rounded-lg bg-zinc-950/80 border border-zinc-800">
                  <span className="text-emerald-500 block text-[10px]">ÉXITOS</span>
                  <span className="font-semibold text-emerald-400">
                    {stats.level_counts?.SUCCESS || 0}
                  </span>
                </div>

                <div className="px-3 py-1.5 rounded-lg bg-zinc-950/80 border border-zinc-800">
                  <span className="text-rose-500 block text-[10px]">ERRORES</span>
                  <span className="font-semibold text-rose-400">
                    {stats.level_counts?.ERROR || 0}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Toolbar y Filtros de Logs */}
          <div className="p-4 rounded-xl bg-zinc-900/30 border border-zinc-800 space-y-3">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
              {/* Selector de Módulo */}
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-[11px] text-zinc-400 mr-1 flex items-center gap-1">
                  <Layers className="w-3 h-3" />
                  <span>Módulo:</span>
                </span>
                <button
                  onClick={() => setSelectedModule('')}
                  className={`px-2.5 py-1 rounded-md text-[11px] font-mono transition cursor-pointer ${
                    selectedModule === ''
                      ? 'bg-zinc-800 text-white font-medium border border-zinc-700'
                      : 'text-zinc-400 hover:text-zinc-200 bg-zinc-950'
                  }`}
                >
                  TODOS
                </button>
                {modules.map((m) => (
                  <button
                    key={m}
                    onClick={() => setSelectedModule(m)}
                    className={`px-2 py-1 rounded-md text-[11px] font-mono transition cursor-pointer ${
                      selectedModule === m
                        ? 'bg-sky-950 text-sky-400 font-medium border border-sky-800'
                        : 'text-zinc-400 hover:text-zinc-200 bg-zinc-950'
                    }`}
                  >
                    {m}
                  </button>
                ))}
              </div>

              {/* Selector de Nivel */}
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-[11px] text-zinc-400 mr-1 flex items-center gap-1">
                  <Filter className="w-3 h-3" />
                  <span>Nivel:</span>
                </span>
                <button
                  onClick={() => setSelectedLevel('')}
                  className={`px-2.5 py-1 rounded-md text-[11px] font-mono transition cursor-pointer ${
                    selectedLevel === ''
                      ? 'bg-zinc-800 text-white font-medium border border-zinc-700'
                      : 'text-zinc-400 hover:text-zinc-200 bg-zinc-950'
                  }`}
                >
                  TODOS
                </button>
                {levels.map((lvl) => (
                  <button
                    key={lvl}
                    onClick={() => setSelectedLevel(lvl)}
                    className={`px-2 py-1 rounded-md text-[11px] font-mono transition cursor-pointer ${
                      selectedLevel === lvl
                        ? 'bg-zinc-800 text-white font-medium border border-zinc-700'
                        : 'text-zinc-400 hover:text-zinc-200 bg-zinc-950'
                    }`}
                  >
                    {lvl}
                  </button>
                ))}
              </div>
            </div>

            {/* Búsqueda y Botón Limpiar */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-2 border-t border-zinc-800/80">
              <div className="relative w-full sm:w-80">
                <Search className="w-3.5 h-3.5 text-zinc-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={handleTerminalSearchChange}
                  placeholder="Buscar en mensajes y detalles..."
                  className="bg-zinc-950 border border-zinc-800 pl-8 pr-3 py-1.5 rounded-lg text-xs text-zinc-200 placeholder-zinc-500 w-full focus:outline-hidden focus:border-sky-500 font-sans"
                />
              </div>

              {isSuperAdmin && (
                <button
                  onClick={handleClearLogs}
                  title="Borrar historial global de logs"
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-rose-500/20 text-rose-400 hover:bg-rose-500/10 transition text-xs cursor-pointer"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  <span>Limpiar Logs</span>
                </button>
              )}
            </div>
          </div>

          {/* Terminal Feed */}
          <div className="rounded-xl border border-zinc-800 bg-zinc-950 overflow-hidden shadow-2xl">
            <div className="px-4 py-2.5 border-b border-zinc-800/80 bg-zinc-900/60 flex items-center justify-between text-xs">
              <div className="flex items-center gap-2 font-mono text-zinc-400 text-[11px]">
                <Terminal className="w-3.5 h-3.5 text-sky-400" />
                <span>TERMINAL DE ACTIVIDAD Y TRAZABILIDAD</span>
              </div>
              <span className="font-mono text-[10px] text-zinc-500">
                {logs.length} eventos mostrados
              </span>
            </div>

            <div className="p-3 font-mono text-xs max-h-[600px] overflow-y-auto space-y-1.5 divide-y divide-zinc-900/80">
              {logs.length === 0 ? (
                <div className="py-12 text-center text-zinc-500 text-xs">
                  No hay eventos registrados que coincidan con los filtros actuales.
                </div>
              ) : (
                logs.map((log) => {
                  const levelStyles = {
                    SUCCESS: { text: 'text-emerald-400', badge: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20', icon: CheckCircle2 },
                    INFO: { text: 'text-sky-300', badge: 'bg-sky-500/10 text-sky-400 border-sky-500/20', icon: Info },
                    WARNING: { text: 'text-amber-400', badge: 'bg-amber-500/10 text-amber-400 border-amber-500/20', icon: AlertTriangle },
                    ERROR: { text: 'text-rose-400', badge: 'bg-rose-500/10 text-rose-400 border-rose-500/20', icon: AlertCircle },
                  }[log.level] || { text: 'text-zinc-300', badge: 'bg-zinc-800 text-zinc-400 border-zinc-700', icon: Info };

                  const Icon = levelStyles.icon;
                  const isExpanded = expandedLogIds.has(log.id);
                  const hasDetails = log.details && Object.keys(log.details).length > 0;

                  return (
                    <div key={log.id} className="pt-2 hover:bg-zinc-900/40 p-2 rounded-lg transition">
                      <div className="flex items-start gap-2.5">
                        <Icon className={`w-3.5 h-3.5 shrink-0 mt-0.5 ${levelStyles.text}`} />
                        <span className="text-[11px] text-zinc-500 shrink-0 font-mono">
                          {log.timestamp}
                        </span>
                        <span className="px-1.5 py-0.2 rounded text-[10px] font-mono uppercase bg-zinc-800 text-zinc-300 border border-zinc-700/60 shrink-0">
                          {log.module}
                        </span>
                        <span className={`px-1.5 py-0.2 rounded text-[10px] font-mono uppercase border shrink-0 ${levelStyles.badge}`}>
                          {log.level}
                        </span>
                        <div className="flex-1 text-zinc-200 text-xs font-sans break-words">
                          {log.message}
                        </div>
                        {hasDetails && (
                          <button
                            onClick={() => toggleLogDetails(log.id)}
                            className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-zinc-900 hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 border border-zinc-800 transition cursor-pointer shrink-0 flex items-center gap-1"
                          >
                            {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                            <span>DETALLES</span>
                          </button>
                        )}
                      </div>

                      {isExpanded && hasDetails && (
                        <div className="mt-2 ml-6 p-2.5 rounded-lg bg-zinc-900 border border-zinc-800 text-[11px] font-mono text-zinc-300 overflow-x-auto">
                          <pre>{JSON.stringify(log.details, null, 2)}</pre>
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
