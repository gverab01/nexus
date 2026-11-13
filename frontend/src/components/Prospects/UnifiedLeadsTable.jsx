// Componente Unificado de Tabla de Prospectos (Directorio, Listas y Secuencias)
// Cumple con Directrices v1.3: Vistas coherentes, columnas gestionables, ordenamiento y paginación
import React, { useState, useEffect, useMemo, useRef } from 'react';
import { 
  Building2, 
  MapPin, 
  Mail, 
  Phone, 
  ExternalLink, 
  Layers, 
  RefreshCw, 
  Eye, 
  Trash2, 
  Clock, 
  ChevronLeft, 
  ChevronRight, 
  ChevronsLeft, 
  ChevronsRight, 
  ChevronUp, 
  ChevronDown, 
  ArrowUpDown, 
  SlidersHorizontal, 
  Check, 
  RotateCcw, 
  X, 
  ArrowUp, 
  ArrowDown, 
  Compass, 
  Users,
  Sparkles
} from 'lucide-react';

// Registro maestro de columnas disponibles
export const ALL_COLUMNS = [
  { id: 'select', label: 'Seleccionar', sortable: false, locked: true },
  { id: 'prospecto', label: 'Prospecto', sortable: true, sortKey: 'nombre' },
  { id: 'cargo', label: 'Cargo Actual', sortable: true, sortKey: 'cargo' },
  { id: 'empresa', label: 'Empresa / Institución', sortable: true, sortKey: 'empresa' },
  { id: 'ubicacion', label: 'Ubicación', sortable: true, sortKey: 'ubicacion' },
  { id: 'email', label: 'Email Directo', sortable: true, sortKey: 'email' },
  { id: 'telefono', label: 'Teléfono', sortable: true, sortKey: 'telefono' },
  { id: 'zoho', label: 'Zoho CRM', sortable: true, sortKey: 'zoho' },
  { id: 'estado', label: 'Estado', sortable: true, sortKey: 'estado' },
  { id: 'paso_cola', label: 'Paso & Cola', sortable: true, sortKey: 'paso_cola' },
  { id: 'listas', label: 'Listas', sortable: true, sortKey: 'listas' },
  { id: 'secuencias', label: 'Secuencias', sortable: true, sortKey: 'secuencias' },
  { id: 'fecha', label: 'Fecha', sortable: true, sortKey: 'fecha' },
  { id: 'acciones', label: 'Acciones', sortable: false, locked: true, align: 'right' },
];

// Configuraciones de columnas por defecto para cada contexto (máx. 5-6 columnas visibles para evitar scroll horizontal)
const DEFAULT_COLUMNS_BY_CONTEXT = {
  directory: ['select', 'prospecto', 'cargo', 'empresa', 'estado', 'acciones'],
  list: ['select', 'prospecto', 'cargo', 'empresa', 'estado', 'acciones'],
  sequence: ['select', 'prospecto', 'empresa', 'paso_cola', 'acciones']
};

export default function UnifiedLeadsTable({
  data = [],
  context = 'directory', // 'directory' | 'list' | 'sequence'
  loading = false,
  onOpenLead,
  // Selección múltiple
  selectedLeadIds,
  onToggleLead,
  onToggleSelectAll,
  // Acciones individuales
  onSyncLinkedIn,
  onResolveEmail,
  onDeleteLead,
  onRemoveFromList,
  // Estados de carga por lead
  syncingLeadIds = new Set(),
  activeSyncingLeadId = null,
  resolvingLeadIds = new Set(),
  actionInProgress = false,
  // Filtros interactivos por clic en badge
  onFilterByList,
  onFilterBySequence,
  // Paginación
  clientSidePagination = false,
  currentPage = 1,
  pageSize = 25,
  totalItems,
  onPageChange,
  onPageSizeChange,
  // Ordenamiento externo opcional
  externalSortColumn,
  externalSortDirection,
  onSortChange,
  // Empty State personalizado
  emptyTitle = 'No se encontraron prospectos',
  emptySubtitle = 'No hay datos disponibles para mostrar con los filtros aplicados.',
  emptyAction = null,
  tableTitle = null
}) {
  const storageKey = `nexusreach_table_cols_${context}`;

  // Inicializar columnas visibles y orden desde localStorage o defaults
  const [columnConfig, setColumnConfig] = useState(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed.order) && Array.isArray(parsed.visible)) {
          return parsed;
        }
      }
    } catch (e) {
      console.warn('Error leyendo configuración de columnas:', e);
    }
    const defaults = DEFAULT_COLUMNS_BY_CONTEXT[context] || DEFAULT_COLUMNS_BY_CONTEXT.directory;
    const allIds = ALL_COLUMNS.map(c => c.id);
    return {
      order: allIds,
      visible: defaults
    };
  });

  const [showColumnManager, setShowColumnManager] = useState(false);
  const columnManagerRef = useRef(null);

  // Ordenamiento local cuando no es manejado externamente
  const [internalSortColumn, setInternalSortColumn] = useState('prospecto');
  const [internalSortDirection, setInternalSortDirection] = useState(null); // 'asc' | 'desc' | null

  // Paginación local si clientSidePagination es true
  const [localCurrentPage, setLocalCurrentPage] = useState(1);
  const [localPageSize, setLocalPageSize] = useState(pageSize || 25);

  const activePage = clientSidePagination ? localCurrentPage : currentPage;
  const activePageSize = clientSidePagination ? localPageSize : pageSize;

  const currentSortCol = externalSortColumn !== undefined ? externalSortColumn : internalSortColumn;
  const currentSortDir = externalSortDirection !== undefined ? externalSortDirection : internalSortDirection;

  // Persistir cambios en localStorage
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(columnConfig));
    } catch (e) {
      console.warn('Error guardando configuración de columnas:', e);
    }
  }, [columnConfig, storageKey]);

  // Cerrar popover de columnas al hacer clic afuera
  useEffect(() => {
    function handleClickOutside(e) {
      if (columnManagerRef.current && !columnManagerRef.current.contains(e.target)) {
        setShowColumnManager(false);
      }
    }
    if (showColumnManager) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showColumnManager]);

  // Manejar cambio de visibilidad de columna
  function toggleColumnVisibility(colId) {
    if (colId === 'select' || colId === 'acciones') return; // Bloqueadas
    setColumnConfig(prev => {
      const isVisible = prev.visible.includes(colId);
      const newVisible = isVisible 
        ? prev.visible.filter(id => id !== colId)
        : [...prev.visible, colId];
      return { ...prev, visible: newVisible };
    });
  }

  // Mover columna arriba / izquierda en orden
  function moveColumn(colId, direction) {
    setColumnConfig(prev => {
      const order = [...prev.order];
      const index = order.indexOf(colId);
      if (index === -1) return prev;
      const targetIndex = direction === 'up' ? index - 1 : index + 1;
      if (targetIndex < 0 || targetIndex >= order.length) return prev;
      // No mover 'select' o 'acciones' fuera de los extremos si están bloqueadas
      if (order[targetIndex] === 'select' && direction === 'up') return prev;
      if (order[targetIndex] === 'acciones' && direction === 'down') return prev;

      const temp = order[index];
      order[index] = order[targetIndex];
      order[targetIndex] = temp;
      return { ...prev, order };
    });
  }

  // Restablecer columnas por defecto
  function resetColumnsToDefault() {
    const defaults = DEFAULT_COLUMNS_BY_CONTEXT[context] || DEFAULT_COLUMNS_BY_CONTEXT.directory;
    const allIds = ALL_COLUMNS.map(c => c.id);
    setColumnConfig({
      order: allIds,
      visible: defaults
    });
  }

  // Columnas activas ordenadas
  const visibleColumns = useMemo(() => {
    const colMap = new Map(ALL_COLUMNS.map(c => [c.id, c]));
    return columnConfig.order
      .filter(id => columnConfig.visible.includes(id))
      .map(id => colMap.get(id))
      .filter(Boolean);
  }, [columnConfig]);

  // Manejador de clic en encabezado para ordenar
  function handleHeaderSort(colId) {
    const colDef = ALL_COLUMNS.find(c => c.id === colId);
    if (!colDef || !colDef.sortable) return;

    let nextDir = 'asc';
    if (currentSortCol === colId) {
      if (currentSortDir === 'asc') nextDir = 'desc';
      else if (currentSortDir === 'desc') nextDir = null;
      else nextDir = 'asc';
    }

    if (onSortChange) {
      onSortChange({ column: nextDir ? colId : null, direction: nextDir });
    } else {
      setInternalSortColumn(nextDir ? colId : null);
      setInternalSortDirection(nextDir);
      if (clientSidePagination) setLocalCurrentPage(1);
    }
  }

  // Extracción de valor para ordenamiento en memoria
  function getLeadValueForSort(lead, colId) {
    if (!lead) return '';
    switch (colId) {
      case 'prospecto':
        return lead.nombre || '';
      case 'cargo':
        return lead.cargo_actual || lead.cargo_titular || lead.cargo || '';
      case 'empresa':
        return lead.institucion_actual || lead.institucion || lead.empresa || '';
      case 'ubicacion':
        return lead.ubicacion || '';
      case 'email':
        return lead.email_directo || lead.email_extracted || lead.email || lead.email_zoho || '';
      case 'telefono':
        return lead.telefono_directo || lead.telefono || '';
      case 'zoho':
        if (lead.zoho_cuenta_es_cliente) return '1_cliente';
        if (lead.zoho_id || lead.email_zoho) return '2_zoho';
        return '3_nocruzado';
      case 'estado':
        return lead.estado || '';
      case 'paso_cola':
        return `${lead.paso_actual || 0}_${lead.cola_estado || ''}`;
      case 'listas':
        return (lead.listas || []).length;
      case 'secuencias':
        return (lead.secuencias || []).length;
      case 'fecha':
        return lead.fecha_ingreso_lista || lead.created_at || lead.fecha_extraccion || (lead.ultima_actividad?.timestamp) || '';
      default:
        return '';
    }
  }

  // Datos ordenados (en memoria si no está controlado externamente)
  const sortedData = useMemo(() => {
    if (!currentSortCol || !currentSortDir || onSortChange) {
      return data;
    }
    const cloned = [...data];
    cloned.sort((a, b) => {
      const valA = getLeadValueForSort(a, currentSortCol);
      const valB = getLeadValueForSort(b, currentSortCol);

      if (valA === '' || valA === null || valA === undefined) return 1;
      if (valB === '' || valB === null || valB === undefined) return -1;

      let comp = 0;
      if (typeof valA === 'number' && typeof valB === 'number') {
        comp = valA - valB;
      } else {
        comp = String(valA).localeCompare(String(valB), 'es', { sensitivity: 'base', numeric: true });
      }
      return currentSortDir === 'asc' ? comp : -comp;
    });
    return cloned;
  }, [data, currentSortCol, currentSortDir, onSortChange]);

  // Datos paginados
  const totalCount = totalItems !== undefined ? totalItems : sortedData.length;
  const totalPages = Math.max(1, Math.ceil(totalCount / activePageSize));

  const displayRows = useMemo(() => {
    if (!clientSidePagination) {
      return sortedData;
    }
    const start = (activePage - 1) * activePageSize;
    return sortedData.slice(start, start + activePageSize);
  }, [sortedData, clientSidePagination, activePage, activePageSize]);

  // Helpers de navegación de página
  function handlePageSelect(p) {
    const pageNum = Math.max(1, Math.min(p, totalPages));
    if (clientSidePagination) {
      setLocalCurrentPage(pageNum);
    } else if (onPageChange) {
      onPageChange(pageNum);
    }
  }

  function handlePageSizeSelect(size) {
    if (clientSidePagination) {
      setLocalPageSize(size);
      setLocalCurrentPage(1);
    } else if (onPageSizeChange) {
      onPageSizeChange(size);
    }
  }

  // Generador de números de página inteligente
  const paginationRange = useMemo(() => {
    const delta = 1;
    const range = [];
    const rangeWithDots = [];
    let l;

    for (let i = 1; i <= totalPages; i++) {
      if (i === 1 || i === totalPages || (i >= activePage - delta && i <= activePage + delta)) {
        range.push(i);
      }
    }

    for (let i of range) {
      if (l) {
        if (i - l === 2) {
          rangeWithDots.push(l + 1);
        } else if (i - l !== 1) {
          rangeWithDots.push('...');
        }
      }
      rangeWithDots.push(i);
      l = i;
    }
    return rangeWithDots;
  }, [totalPages, activePage]);

  // Helpers de renderizado visual
  function getLeadInitials(nombre) {
    if (!nombre) return 'P';
    return nombre
      .split(' ')
      .filter(Boolean)
      .slice(0, 2)
      .map(n => n[0])
      .join('')
      .toUpperCase() || 'P';
  }

  function formatRelativeTime(isoString) {
    if (!isoString) return '—';
    try {
      const d = new Date(isoString);
      if (isNaN(d.getTime())) return '—';
      const diffMs = Date.now() - d.getTime();
      const diffMins = Math.floor(diffMs / 60000);
      const diffHours = Math.floor(diffMins / 60);
      const diffDays = Math.floor(diffHours / 24);

      if (diffMins < 2) return 'Ahora mismo';
      if (diffMins < 60) return `Hace ${diffMins} min`;
      if (diffHours < 24) return `Hace ${diffHours} h`;
      if (diffDays === 1) return 'Ayer';
      if (diffDays < 7) return `Hace ${diffDays} d`;
      return d.toLocaleDateString('es-CL', { day: '2-digit', month: 'short' });
    } catch {
      return '—';
    }
  }

  function getLeadStatusBadge(estado) {
    switch (estado) {
      case 'EXTRAIDO':
        return { label: 'Sin contactar', className: 'bg-zinc-800 text-zinc-300 border-zinc-700' };
      case 'PERFIL_VISITADO':
        return { label: 'Visitado', className: 'bg-slate-800 text-slate-300 border-slate-700' };
      case 'INVITACION_ENVIADA':
        return { label: 'Invitación Enviada', className: 'bg-blue-950/50 text-blue-300 border-blue-500/30' };
      case 'CONECTADO':
        return { label: 'Conectado', className: 'bg-emerald-950/50 text-emerald-300 border-emerald-500/30' };
      case 'MENSAJE_ENVIADO':
        return { label: 'Mensaje Enviado', className: 'bg-cyan-950/50 text-cyan-300 border-cyan-500/30' };
      case 'RESPONDIÓ':
      case 'RESPONDIO':
        return { label: 'Respondió', className: 'bg-amber-950/60 text-amber-300 border-amber-500/40' };
      case 'REUNIÓN_AGENDADA':
      case 'REUNION_AGENDADA':
        return { label: 'Reunión Agendada', className: 'bg-purple-950/60 text-purple-300 border-purple-500/40' };
      default:
        return { label: estado || 'Sin contactar', className: 'bg-zinc-800 text-zinc-300 border-zinc-700' };
    }
  }

  function getQueueStatusBadge(lead) {
    const raw = lead.cola_estado || lead.queue_status || (lead.en_cola ? 'EN_ESPERA' : 'EN_ESPERA');
    switch (raw) {
      case 'EN_ESPERA':
        return { label: 'En espera', badgeClass: 'bg-sky-950/40 text-sky-300 border-sky-500/30' };
      case 'PROCESANDO':
        return { label: 'Procesando', badgeClass: 'bg-amber-950/40 text-amber-300 border-amber-500/30 animate-pulse' };
      case 'COMPLETADO':
        return { label: 'Completado', badgeClass: 'bg-emerald-950/40 text-emerald-300 border-emerald-500/30' };
      case 'PAUSADO':
        return { label: 'Pausado', badgeClass: 'bg-zinc-800 text-zinc-400 border-zinc-700' };
      case 'RESPONDIO':
        return { label: 'Respondido', badgeClass: 'bg-purple-950/40 text-purple-300 border-purple-500/30' };
      default:
        return { label: raw, badgeClass: 'bg-zinc-800 text-zinc-400 border-zinc-700' };
    }
  }

  const isAllPageSelected = displayRows.length > 0 && selectedLeadIds && displayRows.every(l => selectedLeadIds.has(l.id || l.lead_id));

  return (
    <div className="rounded-lg border border-[#22252B] bg-[#14161A] overflow-hidden flex flex-col">
      {/* Barra Superior de la Tabla: Contador, Selector de Columnas y Paginación rápida */}
      <div className="px-3.5 py-2 bg-[#0E0F12] border-b border-[#22252B] flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          {onToggleSelectAll && (
            <input
              type="checkbox"
              checked={Boolean(isAllPageSelected)}
              onChange={onToggleSelectAll}
              className="w-4 h-4 rounded border-zinc-700 bg-zinc-900 text-zinc-100 focus:ring-0 cursor-pointer accent-sky-400 shrink-0"
              title="Seleccionar todos los prospectos de esta página"
            />
          )}

          <div className="flex items-center gap-2">
            {tableTitle && (
              <span className="text-xs font-semibold text-zinc-200">{tableTitle} &bull;</span>
            )}
            <span className="text-xs font-semibold text-zinc-300">
              {selectedLeadIds && selectedLeadIds.size > 0 
                ? `${selectedLeadIds.size} seleccionados de ${displayRows.length} en esta página`
                : `Mostrando ${displayRows.length} de ${totalCount} prospectos`
              }
            </span>
          </div>
        </div>

        {/* Acciones de Cabecera: Selector de Columnas & Filas por página */}
        <div className="flex items-center gap-2 relative">
          {/* Botón Gestión de Columnas */}
          <div className="relative" ref={columnManagerRef}>
            <button
              type="button"
              onClick={() => setShowColumnManager(!showColumnManager)}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-medium transition cursor-pointer ${
                showColumnManager 
                  ? 'bg-zinc-800 text-white border-white/20' 
                  : 'bg-zinc-900 hover:bg-zinc-800 text-zinc-300 border-white/[0.08]'
              }`}
              title="Gestionar visibilidad y orden de columnas"
            >
              <SlidersHorizontal className="w-3.5 h-3.5 text-zinc-400" />
              <span>Columnas</span>
              <span className="px-1.5 py-0.2 rounded bg-zinc-800 text-[10px] text-zinc-300 font-mono border border-white/[0.06]">
                {visibleColumns.length}
              </span>
            </button>

            {/* Popover / Menú de Gestión de Columnas */}
            {showColumnManager && (
              <div className="absolute right-0 mt-2 w-72 rounded-xl bg-[#0D0E12] border border-white/[0.1] shadow-2xl p-3 z-50 animate-fadeIn space-y-3">
                <div className="flex items-center justify-between pb-2 border-b border-white/[0.06]">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-200">
                    <SlidersHorizontal className="w-3.5 h-3.5 text-sky-400" />
                    <span>Personalizar Columnas</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowColumnManager(false)}
                    className="p-1 rounded text-zinc-400 hover:text-white hover:bg-zinc-800 transition cursor-pointer"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>

                <div className="text-[11px] text-zinc-400">
                  Marca las columnas que deseas visualizar y utiliza las flechas para reordenarlas:
                </div>

                <div className="max-h-60 overflow-y-auto space-y-1 pr-1 divide-y divide-white/[0.03]">
                  {columnConfig.order.map((colId) => {
                    const colDef = ALL_COLUMNS.find(c => c.id === colId);
                    if (!colDef) return null;
                    const isVisible = columnConfig.visible.includes(colId);
                    const isLocked = Boolean(colDef.locked);

                    return (
                      <div 
                        key={colId} 
                        className="flex items-center justify-between py-1.5 px-1 hover:bg-white/[0.02] rounded text-xs"
                      >
                        <label className={`flex items-center gap-2 cursor-pointer select-none flex-1 ${isLocked ? 'opacity-60 cursor-not-allowed' : ''}`}>
                          <input
                            type="checkbox"
                            checked={isVisible}
                            disabled={isLocked}
                            onChange={() => toggleColumnVisibility(colId)}
                            className="w-3.5 h-3.5 rounded border-zinc-700 bg-zinc-900 text-sky-400 accent-sky-400 cursor-pointer"
                          />
                          <span className={`${isVisible ? 'text-zinc-200 font-medium' : 'text-zinc-500'}`}>
                            {colDef.label}
                          </span>
                        </label>

                        {!isLocked && (
                          <div className="flex items-center gap-0.5">
                            <button
                              type="button"
                              onClick={() => moveColumn(colId, 'up')}
                              className="p-1 rounded text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800 transition cursor-pointer"
                              title="Mover arriba / izquierda"
                            >
                              <ArrowUp className="w-3 h-3" />
                            </button>
                            <button
                              type="button"
                              onClick={() => moveColumn(colId, 'down')}
                              className="p-1 rounded text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800 transition cursor-pointer"
                              title="Mover abajo / derecha"
                            >
                              <ArrowDown className="w-3 h-3" />
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                <div className="pt-2 border-t border-white/[0.06] flex items-center justify-between">
                  <button
                    type="button"
                    onClick={resetColumnsToDefault}
                    className="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-white transition cursor-pointer underline"
                  >
                    <RotateCcw className="w-3 h-3" />
                    <span>Restablecer</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setShowColumnManager(false)}
                    className="px-2.5 py-1 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-medium transition cursor-pointer"
                  >
                    Listo
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Selector de Filas por Página */}
          <div className="flex items-center gap-1.5 text-xs text-zinc-400">
            <span className="text-[11px] text-zinc-500 hidden sm:inline">Filas:</span>
            <select
              value={activePageSize}
              onChange={(e) => handlePageSizeSelect(Number(e.target.value))}
              className="py-1 px-2 rounded-lg bg-zinc-900 border border-white/[0.08] text-xs text-zinc-200 focus:outline-none focus:border-white/20 cursor-pointer"
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </div>
        </div>
      </div>

      {/* Tabla Principal */}
      <div className="overflow-x-auto min-h-[300px] flex-1">
        {loading ? (
          <div className="p-20 text-center space-y-3">
            <RefreshCw className="w-8 h-8 text-sky-400 animate-spin mx-auto" />
            <p className="text-xs text-zinc-400 font-medium">Cargando prospectos...</p>
          </div>
        ) : displayRows.length === 0 ? (
          <div className="p-16 text-center space-y-3">
            <Users className="w-10 h-10 text-zinc-600 mx-auto" />
            <p className="text-sm text-zinc-300 font-semibold">{emptyTitle}</p>
            <p className="text-xs text-zinc-500 max-w-md mx-auto">{emptySubtitle}</p>
            {emptyAction && <div className="pt-2">{emptyAction}</div>}
          </div>
        ) : (
          <table className="w-full text-left text-xs border-collapse">
            <thead className="bg-[#0E0F12] text-zinc-400 font-medium border-b border-[#22252B] text-[11px] sticky top-0 z-10 select-none">
              <tr>
                {visibleColumns.map((col) => {
                  const isSorted = currentSortCol === col.id;
                  const isSelect = col.id === 'select';
                  const isAcciones = col.id === 'acciones';

                  if (isSelect) {
                    return (
                      <th key={col.id} className="py-2.5 px-3.5 w-10 text-center">
                        {onToggleSelectAll && (
                          <input
                            type="checkbox"
                            checked={Boolean(isAllPageSelected)}
                            onChange={onToggleSelectAll}
                            className="w-4 h-4 rounded border-zinc-700 bg-zinc-900 text-blue-500 focus:ring-0 cursor-pointer accent-blue-600"
                            title="Seleccionar todos"
                          />
                        )}
                      </th>
                    );
                  }

                  return (
                    <th
                      key={col.id}
                      onClick={() => col.sortable && handleHeaderSort(col.id)}
                      className={`py-2 px-3.5 transition text-[11px] font-medium ${col.align === 'right' ? 'text-right' : 'text-left'} ${
                        col.sortable ? 'cursor-pointer hover:text-zinc-200 group' : ''
                      } ${isSorted ? 'text-zinc-100 font-semibold bg-white/[0.02]' : 'text-zinc-400'}`}
                    >
                      <div className={`inline-flex items-center gap-1.5 ${col.align === 'right' ? 'justify-end' : 'justify-start'}`}>
                        <span>{col.label}</span>
                        {col.sortable && (
                          <span className="shrink-0">
                            {isSorted && currentSortDir === 'asc' ? (
                              <ChevronUp className="w-3.5 h-3.5 text-blue-400" />
                            ) : isSorted && currentSortDir === 'desc' ? (
                              <ChevronDown className="w-3.5 h-3.5 text-blue-400" />
                            ) : (
                              <ArrowUpDown className="w-3 h-3 text-zinc-600 opacity-0 group-hover:opacity-100 transition" />
                            )}
                          </span>
                        )}
                      </div>
                    </th>
                  );
                })}
              </tr>
            </thead>

            <tbody className="divide-y divide-[#22252B]/60">
              {displayRows.map((lead, idx) => {
                const leadId = lead.id || lead.lead_id || `lead-${idx}`;
                const isSelected = selectedLeadIds ? selectedLeadIds.has(leadId) : false;
                const initials = getLeadInitials(lead.nombre);
                const isSyncingThis = syncingLeadIds.has(leadId);
                const isActiveSyncing = activeSyncingLeadId === leadId;
                const isQueuedSyncing = isSyncingThis && !isActiveSyncing;
                const isResolvingThis = resolvingLeadIds.has(leadId);

                // Normalización de datos del lead
                const leadEmail = lead.email_directo || lead.email_extracted || lead.email || lead.email_zoho;
                const hasEmail = Boolean(leadEmail && leadEmail !== 'No declarado');
                const hasZoho = Boolean(lead.zoho_id || lead.email_zoho || lead.zoho_synced_at);
                const isZohoClient = Boolean(lead.zoho_cuenta_es_cliente);
                const qStatus = getQueueStatusBadge(lead);
                const statusBadge = getLeadStatusBadge(lead.estado);

                return (
                  <tr
                    key={leadId}
                    onClick={() => onOpenLead && onOpenLead(lead)}
                    className={`hover:bg-white/[0.025] transition cursor-pointer group ${
                      isSelected ? 'bg-blue-950/20 border-l-2 border-l-blue-500' : ''
                    }`}
                  >
                    {visibleColumns.map((col) => {
                      switch (col.id) {
                        case 'select':
                          return (
                            <td 
                              key={col.id} 
                              className="py-2 px-3.5 text-center"
                              onClick={(e) => e.stopPropagation()}
                            >
                              {onToggleLead && (
                                <input
                                  type="checkbox"
                                  checked={isSelected}
                                  onChange={() => onToggleLead(leadId)}
                                  className="w-3.5 h-3.5 rounded border-zinc-700 bg-zinc-900 text-blue-500 focus:ring-0 cursor-pointer accent-blue-600"
                                />
                              )}
                            </td>
                          );

                        case 'prospecto':
                          return (
                            <td key={col.id} className="py-2.5 px-3.5">
                              <div className="flex items-center gap-2.5 min-w-[200px]">
                                <div className="w-7 h-7 rounded-full bg-[#1A1D23] border border-[#22252B] flex items-center justify-center text-[10px] font-medium text-zinc-300 shrink-0 group-hover:border-zinc-500 transition">
                                  {initials}
                                </div>
                                <div className="min-w-0">
                                  <div className="font-medium text-[13px] text-zinc-100 group-hover:text-blue-400 transition-colors flex items-center gap-1.5 flex-wrap">
                                    <span className="truncate">{lead.nombre || 'Prospecto sin nombre'}</span>
                                    {lead.grado_red && (
                                      <span className="text-[10px] font-mono px-1 py-0.2 rounded bg-zinc-900 text-zinc-400 border border-[#22252B]">
                                        {lead.grado_red}
                                      </span>
                                    )}
                                  </div>
                                  <div className="text-[11px] text-zinc-400 truncate max-w-xs mt-0.5">
                                    {lead.cargo_actual || lead.cargo_titular || lead.cargo || 'Profesional'}
                                  </div>
                                </div>
                              </div>
                            </td>
                          );

                        case 'cargo':
                          return (
                            <td key={col.id} className="py-3 px-3.5 text-zinc-300 max-w-[220px] truncate">
                              <span className="truncate block" title={lead.cargo_actual || lead.cargo_titular || lead.cargo || '—'}>
                                {lead.cargo_actual || lead.cargo_titular || lead.cargo || '—'}
                              </span>
                            </td>
                          );

                        case 'empresa':
                          return (
                            <td key={col.id} className="py-3 px-3.5 text-zinc-300 max-w-[200px] truncate">
                              <div className="flex items-center gap-1.5 truncate">
                                <Building2 className="w-3.5 h-3.5 text-zinc-500 shrink-0" />
                                <span className="truncate" title={lead.institucion_actual || lead.institucion || lead.empresa || '—'}>
                                  {lead.institucion_actual || lead.institucion || lead.empresa || '—'}
                                </span>
                              </div>
                            </td>
                          );

                        case 'ubicacion':
                          return (
                            <td key={col.id} className="py-3 px-3.5 text-zinc-400 max-w-[160px] truncate text-[11px]">
                              <div className="flex items-center gap-1.5 truncate">
                                <MapPin className="w-3.5 h-3.5 text-zinc-600 shrink-0" />
                                <span className="truncate">{lead.ubicacion || '—'}</span>
                              </div>
                            </td>
                          );

                        case 'email':
                          return (
                            <td key={col.id} className="py-3 px-3.5 font-mono text-[11px] max-w-[200px]">
                              {hasEmail ? (
                                <div className="flex flex-col gap-0.5">
                                  <div className="flex items-center gap-1 truncate text-zinc-200">
                                    <Mail className="w-3 h-3 text-sky-400 shrink-0" />
                                    <span className="truncate" title={leadEmail}>{leadEmail}</span>
                                  </div>
                                  <div className="flex items-center gap-1 flex-wrap">
                                    {lead.email_status && (
                                      <span className={`px-1 py-0.2 rounded text-[9px] font-sans border ${
                                        lead.email_status === 'VERIFICADO'
                                          ? 'bg-emerald-950/80 text-emerald-300 border-emerald-500/40'
                                          : lead.email_status === 'PROBABLE'
                                          ? 'bg-amber-950/80 text-amber-300 border-amber-500/40'
                                          : 'bg-zinc-900 text-zinc-400 border-zinc-700'
                                      }`}>
                                        {lead.email_status}
                                      </span>
                                    )}
                                    {lead.email_zoho && (
                                      <span className="px-1 py-0.2 rounded text-[9px] font-sans border bg-emerald-950/80 text-emerald-300 border-emerald-500/40">
                                        ZOHO
                                      </span>
                                    )}
                                  </div>
                                </div>
                              ) : (
                                <div className="flex items-center gap-1.5">
                                  <span className="text-zinc-500 italic text-[11px]">No resuelto</span>
                                  {onResolveEmail && (
                                    <button
                                      type="button"
                                      onClick={(e) => onResolveEmail(e, lead)}
                                      disabled={isResolvingThis}
                                      className="p-1 rounded hover:bg-emerald-950/40 text-zinc-400 hover:text-emerald-300 transition cursor-pointer"
                                      title="Resolver correo en cascada (Waterfall DNS MX)"
                                    >
                                      <Mail className={`w-3 h-3 ${isResolvingThis ? 'animate-spin text-emerald-400' : ''}`} />
                                    </button>
                                  )}
                                </div>
                              )}
                            </td>
                          );

                        case 'telefono':
                          return (
                            <td key={col.id} className="py-3 px-3.5 text-zinc-400 text-[11px] font-mono">
                              {lead.telefono_directo || lead.telefono ? (
                                <div className="flex items-center gap-1">
                                  <Phone className="w-3 h-3 text-emerald-400 shrink-0" />
                                  <span>{lead.telefono_directo || lead.telefono}</span>
                                </div>
                              ) : (
                                <span className="text-zinc-600">—</span>
                              )}
                            </td>
                          );

                        case 'zoho':
                          return (
                            <td key={col.id} className="py-3 px-3.5">
                              {hasZoho ? (
                                <div className="flex flex-col gap-0.5 max-w-[150px]">
                                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono border self-start ${
                                    isZohoClient
                                      ? 'bg-emerald-950/70 text-emerald-300 border-emerald-500/40'
                                      : 'bg-amber-950/60 text-amber-300 border-amber-500/30'
                                  }`}>
                                    <Compass className="w-2.5 h-2.5 shrink-0" />
                                    <span>{isZohoClient ? 'Cliente Activo' : `Zoho: ${lead.zoho_entidad_tipo || 'Lead'}`}</span>
                                  </span>
                                  {lead.zoho_cuenta_nombre && (
                                    <span className="text-[10px] text-zinc-400 truncate mt-0.5" title={lead.zoho_cuenta_nombre}>
                                      {lead.zoho_cuenta_nombre}
                                    </span>
                                  )}
                                </div>
                              ) : (
                                <span className="text-[10px] text-zinc-600 font-mono">No cruzado</span>
                              )}
                            </td>
                          );

                        case 'estado':
                          return (
                            <td key={col.id} className="py-3 px-3.5">
                              <span className={`px-2 py-0.5 rounded text-[10px] font-mono border inline-block ${statusBadge.className}`}>
                                {statusBadge.label}
                              </span>
                            </td>
                          );

                        case 'paso_cola':
                          return (
                            <td key={col.id} className="py-3 px-3.5">
                              <div className="flex flex-col gap-1">
                                <div className="font-mono text-sky-400 text-xs font-medium">
                                  Paso #{lead.paso_actual || 1}
                                  {lead.paso_etiqueta && (
                                    <span className="text-[10px] text-zinc-400 font-sans ml-1 truncate">
                                      &bull; {lead.paso_etiqueta}
                                    </span>
                                  )}
                                </div>
                                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-mono border self-start ${qStatus.badgeClass}`}>
                                  {qStatus.label}
                                </span>
                              </div>
                            </td>
                          );

                        case 'listas':
                          return (
                            <td key={col.id} className="py-3 px-3.5">
                              <div className="flex items-center gap-1 flex-wrap max-w-[200px]">
                                {lead.listas && lead.listas.length > 0 ? (
                                  lead.listas.map((lst) => (
                                    <span
                                      key={lst.id}
                                      onClick={(e) => {
                                        if (onFilterByList) {
                                          e.stopPropagation();
                                          onFilterByList(lst.id);
                                        }
                                      }}
                                      className="text-[10px] px-2 py-0.5 rounded bg-blue-950/40 text-blue-300 border border-blue-500/20 font-mono flex items-center gap-1 hover:bg-blue-900/50 transition cursor-pointer"
                                      title={`Filtrar por lista: ${lst.nombre}`}
                                    >
                                      <Layers className="w-2.5 h-2.5 text-blue-400 shrink-0" />
                                      <span className="truncate max-w-[100px]">{lst.nombre}</span>
                                    </span>
                                  ))
                                ) : (
                                  <span className="text-[10px] text-zinc-600 italic">Sin lista</span>
                                )}
                              </div>
                            </td>
                          );

                        case 'secuencias':
                          return (
                            <td key={col.id} className="py-3 px-3.5">
                              <div className="flex items-center gap-1 flex-wrap max-w-[200px]">
                                {lead.secuencias && lead.secuencias.length > 0 ? (
                                  lead.secuencias.map((seq) => (
                                    <span
                                      key={seq.id}
                                      onClick={(e) => {
                                        if (onFilterBySequence) {
                                          e.stopPropagation();
                                          onFilterBySequence(seq.id);
                                        }
                                      }}
                                      className="text-[10px] px-2 py-0.5 rounded bg-purple-950/40 text-purple-300 border border-purple-500/20 font-mono flex items-center gap-1 hover:bg-purple-900/50 transition cursor-pointer"
                                      title={`Secuencia: ${seq.nombre}`}
                                    >
                                      <span className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse shrink-0" />
                                      <span className="truncate max-w-[100px]">{seq.nombre}</span>
                                    </span>
                                  ))
                                ) : (
                                  <span className="text-[10px] text-zinc-600 italic">Sin secuencia</span>
                                )}
                              </div>
                            </td>
                          );

                        case 'fecha':
                          const rawDate = lead.fecha_ingreso_lista || lead.created_at || lead.fecha_extraccion || (lead.ultima_actividad?.timestamp);
                          return (
                            <td key={col.id} className="py-3 px-3.5 text-zinc-500 text-[11px] font-mono whitespace-nowrap">
                              <span title={rawDate ? new Date(rawDate).toLocaleString() : ''}>
                                {formatRelativeTime(rawDate)}
                              </span>
                            </td>
                          );

                        case 'acciones':
                          return (
                            <td key={col.id} className="py-3 px-3.5 text-right whitespace-nowrap">
                              <div 
                                className="flex items-center justify-end gap-1"
                                onClick={(e) => e.stopPropagation()}
                              >
                                {/* Sincronizar LinkedIn en Vivo */}
                                {onSyncLinkedIn && (
                                  <button
                                    type="button"
                                    onClick={(e) => onSyncLinkedIn(e, lead)}
                                    disabled={isSyncingThis || actionInProgress}
                                    className={`p-1.5 rounded transition cursor-pointer disabled:opacity-50 ${
                                      isActiveSyncing
                                        ? 'bg-emerald-950/70 text-emerald-400 border border-emerald-500/40 shadow-sm shadow-emerald-950/50'
                                        : isQueuedSyncing
                                        ? 'bg-amber-950/40 text-amber-400 border border-amber-500/30'
                                        : 'hover:bg-emerald-950/30 text-zinc-400 hover:text-emerald-400'
                                    }`}
                                    title={
                                      isActiveSyncing
                                        ? 'Sincronizando con LinkedIn en vivo...'
                                        : isQueuedSyncing
                                        ? 'En cola de sincronización...'
                                        : 'Sincronizar cargo actual y empresa con LinkedIn'
                                    }
                                  >
                                    {isActiveSyncing ? (
                                      <RefreshCw className="w-3.5 h-3.5 animate-spin text-emerald-400" />
                                    ) : isQueuedSyncing ? (
                                      <Clock className="w-3.5 h-3.5 animate-pulse text-amber-400" />
                                    ) : (
                                      <RefreshCw className="w-3.5 h-3.5" />
                                    )}
                                  </button>
                                )}

                                {/* Resolver Correo en Cascada */}
                                {onResolveEmail && (
                                  <button
                                    type="button"
                                    onClick={(e) => onResolveEmail(e, lead)}
                                    disabled={isResolvingThis || actionInProgress}
                                    className={`p-1.5 rounded transition cursor-pointer disabled:opacity-50 ${
                                      hasEmail
                                        ? 'hover:bg-emerald-950/40 text-emerald-400'
                                        : 'hover:bg-zinc-800 text-zinc-400 hover:text-emerald-300'
                                    }`}
                                    title={hasEmail ? 'Re-verificar correo corporativo' : 'Resolver correo corporativo en cascada (DNS MX)'}
                                  >
                                    <Mail className={`w-3.5 h-3.5 ${isResolvingThis ? 'animate-spin text-emerald-400' : ''}`} />
                                  </button>
                                )}

                                {/* Perfil de LinkedIn Externo */}
                                {lead.perfil_url && (
                                  <a
                                    href={lead.perfil_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="p-1.5 rounded hover:bg-zinc-800 text-zinc-400 hover:text-sky-300 transition"
                                    title="Abrir perfil de LinkedIn"
                                  >
                                    <ExternalLink className="w-3.5 h-3.5" />
                                  </a>
                                )}

                                {/* Abrir Ficha Completa */}
                                <button
                                  type="button"
                                  onClick={() => onOpenLead && onOpenLead(lead)}
                                  className="p-1.5 rounded hover:bg-zinc-800 text-zinc-400 hover:text-white transition cursor-pointer"
                                  title="Ver ficha completa del prospecto"
                                >
                                  <Eye className="w-3.5 h-3.5" />
                                </button>

                                {/* Quitar de lista o Eliminar */}
                                {onRemoveFromList && (
                                  <button
                                    type="button"
                                    onClick={(e) => onRemoveFromList(e, lead)}
                                    disabled={actionInProgress}
                                    className="p-1.5 rounded hover:bg-red-950/30 text-zinc-500 hover:text-red-400 transition cursor-pointer"
                                    title="Quitar prospecto de esta lista"
                                  >
                                    <Trash2 className="w-3.5 h-3.5" />
                                  </button>
                                )}

                                {onDeleteLead && (
                                  <button
                                    type="button"
                                    onClick={(e) => onDeleteLead(e, lead.id || lead.lead_id)}
                                    disabled={actionInProgress}
                                    className="p-1.5 rounded hover:bg-red-950/30 text-zinc-500 hover:text-red-400 transition cursor-pointer"
                                    title="Eliminar prospecto permanentemente"
                                  >
                                    <Trash2 className="w-3.5 h-3.5" />
                                  </button>
                                )}
                              </div>
                            </td>
                          );

                        default:
                          return null;
                      }
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Barra Inferior: Paginación Completa */}
      {!loading && totalCount > 0 && (
        <div className="p-3 bg-[#0D0E12] border-t border-white/[0.06] flex items-center justify-between gap-3 flex-wrap">
          <div className="text-xs text-zinc-400">
            Página <span className="text-zinc-200 font-semibold">{activePage}</span> de{' '}
            <span className="text-zinc-200 font-semibold">{totalPages}</span> ({totalCount} prospectos totales)
          </div>

          <div className="flex items-center gap-1">
            {/* Primera página */}
            <button
              type="button"
              disabled={activePage <= 1}
              onClick={() => handlePageSelect(1)}
              className="p-1.5 rounded bg-zinc-900 border border-white/[0.06] text-zinc-400 hover:text-white disabled:opacity-40 disabled:hover:text-zinc-400 transition cursor-pointer disabled:cursor-not-allowed"
              title="Primera página"
            >
              <ChevronsLeft className="w-3.5 h-3.5" />
            </button>

            {/* Página anterior */}
            <button
              type="button"
              disabled={activePage <= 1}
              onClick={() => handlePageSelect(activePage - 1)}
              className="p-1.5 rounded bg-zinc-900 border border-white/[0.06] text-zinc-400 hover:text-white disabled:opacity-40 disabled:hover:text-zinc-400 transition cursor-pointer disabled:cursor-not-allowed"
              title="Página anterior"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>

            {/* Números de página */}
            {paginationRange.map((pageItem, index) => {
              if (pageItem === '...') {
                return (
                  <span key={`dots-${index}`} className="px-2 py-1 text-xs text-zinc-600 select-none">
                    ...
                  </span>
                );
              }
              const isCurrent = pageItem === activePage;
              return (
                <button
                  key={pageItem}
                  type="button"
                  onClick={() => handlePageSelect(pageItem)}
                  className={`min-w-[28px] h-7 px-2 rounded text-xs font-semibold transition cursor-pointer ${
                    isCurrent
                      ? 'bg-white text-zinc-950 shadow'
                      : 'bg-zinc-900 hover:bg-zinc-800 text-zinc-300 border border-white/[0.06]'
                  }`}
                >
                  {pageItem}
                </button>
              );
            })}

            {/* Página siguiente */}
            <button
              type="button"
              disabled={activePage >= totalPages}
              onClick={() => handlePageSelect(activePage + 1)}
              className="p-1.5 rounded bg-zinc-900 border border-white/[0.06] text-zinc-400 hover:text-white disabled:opacity-40 disabled:hover:text-zinc-400 transition cursor-pointer disabled:cursor-not-allowed"
              title="Página siguiente"
            >
              <ChevronRight className="w-3.5 h-3.5" />
            </button>

            {/* Última página */}
            <button
              type="button"
              disabled={activePage >= totalPages}
              onClick={() => handlePageSelect(totalPages)}
              className="p-1.5 rounded bg-zinc-900 border border-white/[0.06] text-zinc-400 hover:text-white disabled:opacity-40 disabled:hover:text-zinc-400 transition cursor-pointer disabled:cursor-not-allowed"
              title="Última página"
            >
              <ChevronsRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
