// Vista de auditoría y log de sucesos en tiempo real con telemetría de BrowserOS y estado del extractor
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
  Compass, 
  Sparkles,
  ChevronDown,
  ChevronRight,
  Clock,
  Layers
} from 'lucide-react';
import { fetchLogs, fetchLogStats, clearLogs } from '../../services/api';

export default function ActivityLogsView({ onStatusChange }) {
  const [logs, setLogs] = useState([]);
  const [stats, setStats] = useState({
    total_logs: 0,
    is_extracting_now: false,
    last_extractor_activity: null,
    level_counts: {},
    module_counts: {},
  });
  const [loading, setLoading] = useState(true);
  
  // Filtros
  const [selectedModule, setSelectedModule] = useState('');
  const [selectedLevel, setSelectedLevel] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(true);
  
  // Elementos expandidos de detalles JSON
  const [expandedLogIds, setExpandedLogIds] = useState(new Set());

  // Ref para almacenar el intervalo de auto-refresco y debounce de búsqueda
  const intervalRef = useRef(null);
  const searchTimeoutRef = useRef(null);
  const queryRef = useRef(searchQuery);
  queryRef.current = searchQuery;

  useEffect(() => {
    loadLogsAndStats();

    if (autoRefresh) {
      intervalRef.current = setInterval(() => loadLogsAndStats(), 3000);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [selectedModule, selectedLevel, autoRefresh]);

  async function loadLogsAndStats(queryOverride) {
    const q = queryOverride !== undefined ? queryOverride : queryRef.current;
    try {
      const [logsData, statsData] = await Promise.all([
        fetchLogs({
          module: selectedModule,
          level: selectedLevel,
          search: q,
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
      console.error('Error cargando logs de sucesos:', err);
    } finally {
      setLoading(false);
    }
  }

  function handleSearchChange(e) {
    const val = e.target.value;
    setSearchQuery(val);
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    searchTimeoutRef.current = setTimeout(() => {
      loadLogsAndStats(val);
    }, 350);
  }

  async function handleClearLogs() {
    if (!confirm('¿Deseas vaciar el historial de eventos y logs registrados?')) return;
    try {
      await clearLogs();
      await loadLogsAndStats();
    } catch (err) {
      alert(`Error al limpiar logs: ${err.message}`);
    }
  }

  function toggleLogDetails(logId) {
    setExpandedLogIds((prev) => {
      const next = new Set(prev);
      if (next.has(logId)) {
        next.delete(logId);
      } else {
        next.add(logId);
      }
      return next;
    });
  }

  const modules = ['EXTRACTOR', 'SEQUENCES', 'BROWSER', 'SAFETY', 'LISTS', 'SYSTEM'];
  const levels = ['SUCCESS', 'INFO', 'WARNING', 'ERROR'];

  return (
    <div className="space-y-6">
      {/* Banner Principal de Estado de Ejecución */}
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

        {/* Búsqueda y Botones de Acción */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-2 border-t border-zinc-800/80">
          <div className="relative w-full sm:w-80">
            <Search className="w-3.5 h-3.5 text-zinc-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Buscar en mensajes y detalles..."
              className="bg-zinc-950 border border-zinc-800 pl-8 pr-3 py-1.5 rounded-lg text-xs text-zinc-200 placeholder-zinc-500 w-full focus:outline-hidden focus:border-sky-500 font-sans"
            />
          </div>

          <div className="flex items-center gap-2 self-end sm:self-auto">
            {/* Toggle de Auto-Refresco */}
            <label className="flex items-center gap-1.5 text-xs text-zinc-400 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="rounded bg-zinc-950 border-zinc-700 text-sky-500 focus:ring-0"
              />
              <span className="text-[11px]">Auto-refrescar (2.5s)</span>
            </label>

            {/* Botón Refrescar Manual */}
            <button
              onClick={loadLogsAndStats}
              title="Refrescar logs ahora"
              className="p-1.5 rounded-lg bg-zinc-950 border border-zinc-800 hover:bg-zinc-800 text-zinc-300 transition cursor-pointer"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>

            {/* Botón Limpiar Historial */}
            <button
              onClick={handleClearLogs}
              title="Borrar historial de logs"
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-rose-500/20 text-rose-400 hover:bg-rose-500/10 transition text-xs cursor-pointer"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span>Limpiar</span>
            </button>
          </div>
        </div>
      </div>

      {/* Terminal / Feed de Eventos */}
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
                    {/* Icono de Nivel */}
                    <Icon className={`w-3.5 h-3.5 shrink-0 mt-0.5 ${levelStyles.text}`} />

                    {/* Timestamp con formato preciso */}
                    <span className="text-[11px] text-zinc-500 shrink-0 font-mono">
                      {log.timestamp}
                    </span>

                    {/* Módulo Badge */}
                    <span className="px-1.5 py-0.2 rounded text-[10px] font-mono uppercase bg-zinc-800 text-zinc-300 border border-zinc-700/60 shrink-0">
                      {log.module}
                    </span>

                    {/* Nivel Badge */}
                    <span className={`px-1.5 py-0.2 rounded text-[10px] font-mono uppercase border shrink-0 ${levelStyles.badge}`}>
                      {log.level}
                    </span>

                    {/* Mensaje Principal */}
                    <div className="flex-1 text-zinc-200 text-xs font-sans break-words">
                      {log.message}
                    </div>

                    {/* Botón de expansión para Detalles JSON */}
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

                  {/* Detalle JSON desplegable */}
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
  );
}
