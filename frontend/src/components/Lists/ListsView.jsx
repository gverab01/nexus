// Vista de gestión de listas de prospectos y vinculación con secuencias
import React, { useState, useEffect } from 'react';
import { 
  ListFilter, 
  Plus, 
  Search, 
  Layers, 
  GitFork, 
  Zap, 
  Database, 
  ExternalLink,
  ChevronRight,
  Clock
} from 'lucide-react';
import { fetchLeadLists } from '../../services/api';
import NewListModal from './NewListModal';

export default function ListsView({ onSelectSequence, activeTenantWorkspace = '' }) {
  const [lists, setLists] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterState, setFilterState] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [showNewModal, setShowNewModal] = useState(false);

  useEffect(() => {
    loadLists();
  }, [activeTenantWorkspace]);

  async function loadLists() {
    try {
      setLoading(true);
      const data = await fetchLeadLists(activeTenantWorkspace);
      setLists(data || []);
    } catch (err) {
      console.error('Error cargando listas de leads:', err);
    } finally {
      setLoading(false);
    }
  }

  // Filtrado de listas
  const filteredLists = lists.filter((item) => {
    const matchesState = filterState ? item.estado === filterState : true;
    const matchesSearch = searchQuery
      ? item.nombre.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (item.termino_busqueda && item.termino_busqueda.toLowerCase().includes(searchQuery.toLowerCase()))
      : true;
    return matchesState && matchesSearch;
  });

  // Métricas de listas
  const totalLeads = lists.reduce((acc, curr) => acc + (curr.total_leads || 0), 0);
  const activeLists = lists.filter((l) => l.estado === 'ACTIVA' || l.estado === 'EXTRAYENDO').length;
  const totalConnections = lists.reduce((acc, curr) => acc + (curr.secuencias_conectadas ? curr.secuencias_conectadas.length : 0), 0);

  return (
    <div className="space-y-5 font-sans">
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-zinc-100 tracking-tight">Listas de Leads & Segmentación</h2>
          <p className="text-xs text-zinc-400 mt-0.5">
            Organiza prospectos por listas segmentadas y conéctalas a una o varias secuencias en paralelo.
          </p>
        </div>
        <button
          onClick={() => setShowNewModal(true)}
          className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-medium text-xs shadow-sm transition cursor-pointer self-start sm:self-auto"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>Nueva Lista</span>
        </button>
      </div>

      {/* Tarjetas KPI */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
          <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
            <span className="font-medium text-zinc-300">Total Listas</span>
            <Layers className="w-3.5 h-3.5 text-zinc-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">{lists.length}</div>
          <span className="text-[10px] text-zinc-500 mt-1 block">Audiencias configuradas</span>
        </div>

        <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
          <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
            <span className="font-medium text-zinc-300">Listas Activas</span>
            <Zap className="w-3.5 h-3.5 text-zinc-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">{activeLists}</div>
          <span className="text-[10px] text-emerald-400 mt-1 block font-medium">En extracción o secuencia</span>
        </div>

        <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
          <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
            <span className="font-medium text-zinc-300">Leads en Listas</span>
            <Database className="w-3.5 h-3.5 text-zinc-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">{totalLeads}</div>
          <span className="text-[10px] text-zinc-500 mt-1 block">Directivos clasificados</span>
        </div>

        <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
          <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
            <span className="font-medium text-zinc-300">Conexiones</span>
            <GitFork className="w-3.5 h-3.5 text-zinc-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">{totalConnections}</div>
          <span className="text-[10px] text-zinc-500 mt-1 block">Vínculos de auto-ingreso</span>
        </div>
      </div>

      {/* Toolbar y Filtros */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center bg-[#0D0E12] p-0.5 rounded-md border border-white/[0.08] text-[11px]">
          {[
            { id: '', label: 'Todas' },
            { id: 'ACTIVA', label: 'Activas' },
            { id: 'EXTRAYENDO', label: 'En Extracción' },
            { id: 'DETENIDA', label: 'Detenidas / Fijas' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setFilterState(tab.id)}
              className={`px-3 py-1 rounded transition cursor-pointer ${
                filterState === tab.id
                  ? 'bg-zinc-800 text-zinc-100 font-medium shadow-xs'
                  : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="relative">
          <Search className="w-3.5 h-3.5 text-zinc-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Buscar por nombre o término..."
            className="bg-[#0D0E12] border border-white/[0.08] pl-8 pr-3 py-1.5 rounded-md text-xs text-zinc-100 placeholder-zinc-500 w-full sm:w-64 focus:outline-none focus:border-zinc-500 font-sans"
          />
        </div>
      </div>

      {/* Grilla de Listas */}
      {loading ? (
        <div className="p-12 text-center text-zinc-500 text-xs">Cargando listas...</div>
      ) : filteredLists.length === 0 ? (
        <div className="p-12 rounded-xl border border-zinc-800/80 bg-zinc-900/20 text-center text-zinc-500 text-xs">
          No hay listas de prospectos configuradas con este filtro.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
          {filteredLists.map((item) => {
            const badgeClasses = {
              ACTIVA: 'bg-emerald-950/20 text-emerald-400 border-emerald-500/20',
              EXTRAYENDO: 'bg-white/[0.04] text-zinc-300 border-white/[0.08]',
              DETENIDA: 'bg-white/[0.03] text-zinc-500 border-white/[0.06]',
            }[item.estado] || 'bg-white/[0.04] text-zinc-400 border-white/[0.08]';

            const connectedSeqs = item.secuencias_conectadas || [];

            return (
              <div
                key={item.id}
                className="rounded-xl border border-white/[0.08] bg-[#121316] p-4 space-y-3 hover:border-white/[0.16] transition flex flex-col justify-between"
              >
                <div>
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="font-medium text-zinc-100 text-xs leading-tight">
                      {item.nombre}
                    </h3>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-mono border shrink-0 ${badgeClasses}`}>
                      {item.estado}
                    </span>
                  </div>

                  {item.descripcion && (
                    <p className="text-xs text-zinc-400 mt-1 line-clamp-2">
                      {item.descripcion}
                    </p>
                  )}

                  {item.termino_busqueda && (
                    <div className="mt-2.5 inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-[#0D0E12] border border-white/[0.06] text-[11px] text-zinc-300 font-mono">
                      <Search className="w-3 h-3 text-zinc-500" />
                      <span>{item.termino_busqueda}</span>
                    </div>
                  )}
                </div>

                <div className="pt-2.5 border-t border-white/[0.06] space-y-2">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-zinc-400">Total Prospectos:</span>
                    <span className="font-mono font-medium text-zinc-200">{item.total_leads || 0}</span>
                  </div>

                  <div className="text-[11px] text-zinc-400">
                    <span className="block mb-1">Secuencias vinculadas:</span>
                    <div className="flex flex-wrap gap-1">
                      {connectedSeqs.length === 0 ? (
                        <span className="text-zinc-500 italic text-[10px]">Sin secuencia vinculada</span>
                      ) : (
                        connectedSeqs.map((seq, seqIdx) => {
                          const seqName = typeof seq === 'string' ? seq : (seq.nombre || seq.id);
                          const seqKey = typeof seq === 'string' ? seq : (seq.id || seqIdx);
                          return (
                            <span
                              key={seqKey}
                              className="px-1.5 py-0.5 rounded bg-white/[0.04] text-zinc-300 text-[10px] font-mono border border-white/[0.06]"
                            >
                              {seqName}
                            </span>
                          );
                        })
                      )}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Modal Nueva Lista */}
      {showNewModal && (
        <NewListModal
          onClose={() => setShowNewModal(false)}
          onCreated={loadLists}
          activeTenantWorkspace={activeTenantWorkspace}
        />
      )}
    </div>
  );
}
