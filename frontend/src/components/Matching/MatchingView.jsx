// Vista interactiva del Buzón de Staging, Matching y Descubrimiento en LinkedIn
import React, { useState, useEffect } from 'react';
import { 
  UserPlus, 
  FileSpreadsheet, 
  RefreshCw, 
  Search, 
  ExternalLink, 
  CheckCircle2, 
  XCircle, 
  AlertCircle, 
  Sparkles, 
  Building2, 
  Mail, 
  Briefcase, 
  Trash2, 
  ArrowRight, 
  ChevronDown, 
  UserCheck, 
  Eye,
  Filter,
  Users
} from 'lucide-react';
import { 
  fetchMatchingLeads, 
  fetchMatchingStats, 
  searchCandidateForStagingLead, 
  discardStagingLead, 
  deleteStagingLead,
  importZohoStagingLeads,
  showWorkBrowser 
} from '../../services/api';
import NewManualLeadModal from './NewManualLeadModal';
import ImportFileModal from './ImportFileModal';
import ConfirmMatchModal from './ConfirmMatchModal';

export default function MatchingView({ activeTenantWorkspace = '' }) {
  const [leads, setLeads] = useState([]);
  const [stats, setStats] = useState({ total: 0, pendientes: 0, matches_listos: 0, sin_resultados: 0, validados: 0, descartados: 0 });
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState('MATCH_ENCONTRADO'); // Por defecto mostrar los listos para validar
  const [searchTerm, setSearchTerm] = useState('');
  
  // Modales
  const [showManualModal, setShowManualModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [selectedLeadToConfirm, setSelectedLeadToConfirm] = useState(null);

  // Estados de acción en curso
  const [searchingIds, setSearchingIds] = useState(new Set());
  const [importingZoho, setImportingZoho] = useState(false);
  const [expandedAltId, setExpandedAltId] = useState(null);

  useEffect(() => {
    loadData();
  }, [activeTenantWorkspace, filterStatus, searchTerm]);

  async function loadData() {
    try {
      setLoading(true);
      const [leadsData, statsData] = await Promise.all([
        fetchMatchingLeads({
          tenantId: activeTenantWorkspace,
          estado: filterStatus,
          search: searchTerm,
          limit: 100
        }),
        fetchMatchingStats(activeTenantWorkspace)
      ]);
      setLeads(leadsData.leads || []);
      setStats(statsData || { total: 0, pendientes: 0, matches_listos: 0, sin_resultados: 0, validados: 0, descartados: 0 });
    } catch (err) {
      console.error('Error cargando buzón de matching:', err);
    } finally {
      setLoading(false);
    }
  }

  async function handleSearchCandidate(leadId) {
    try {
      setSearchingIds(prev => new Set(prev).add(leadId));
      const res = await searchCandidateForStagingLead(leadId);
      if (res && res.estado === 'SIN_RESULTADOS') {
        alert(res.mensaje || 'No se localizaron perfiles de LinkedIn para este prospecto.');
      }
      await loadData();
    } catch (err) {
      alert(`Error en búsqueda: ${err.message}`);
    } finally {
      setSearchingIds(prev => {
        const next = new Set(prev);
        next.delete(leadId);
        return next;
      });
    }
  }

  async function handleSelectAlternativeCandidate(lead, altCand) {
    // Intercambiar el candidato principal por uno alternativo seleccionado
    lead.candidato_nombre = altCand.nombre;
    lead.candidato_url = altCand.perfil_url;
    lead.candidato_titular = altCand.cargo_titular;
    lead.candidato_cargo = altCand.cargo_actual;
    lead.candidato_institucion = altCand.institucion_actual;
    lead.candidato_ubicacion = altCand.ubicacion;
    lead.candidato_grado = altCand.grado_red;
    lead.score_coincidencia = altCand.score;
    setExpandedAltId(null);
    setSelectedLeadToConfirm({ ...lead });
  }

  async function handleDiscard(leadId) {
    if (!confirm('¿Deseas marcar este prospecto como descartado?')) return;
    try {
      await discardStagingLead(leadId);
      await loadData();
    } catch (err) {
      alert(`Error al descartar: ${err.message}`);
    }
  }

  async function handleDelete(leadId) {
    if (!confirm('¿Eliminar definitivamente este prospecto del buzón?')) return;
    try {
      await deleteStagingLead(leadId);
      await loadData();
    } catch (err) {
      alert(`Error eliminando: ${err.message}`);
    }
  }

  async function handleImportFromZoho() {
    if (!confirm('¿Deseas consultar e importar contactos de Zoho CRM que no tengan LinkedIn vinculado?')) return;
    try {
      setImportingZoho(true);
      const res = await importZohoStagingLeads({ tenant_id: activeTenantWorkspace, max_registros: 50 });
      alert(`Sincronización con Zoho completada:\n• ${res.importados || 0} nuevos contactos agregados al buzón\n• ${res.ignorados || 0} ya existían o sin datos suficientes.`);
      await loadData();
    } catch (err) {
      alert(`Error importando desde Zoho: ${err.message}`);
    } finally {
      setImportingZoho(false);
    }
  }

  async function handleOpenProfileInBrowser(url) {
    if (!url) return;
    try {
      await showWorkBrowser(url, 'linkedin');
    } catch (err) {
      window.open(url, '_blank');
    }
  }

  return (
    <div className="space-y-6 font-sans">
      {/* 1. Header Principal y Acciones de Entrada */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-white/[0.06] pb-4">
        <div>
          <h1 className="text-base font-semibold text-zinc-100 flex items-center gap-2">
            <UserCheck className="w-4 h-4 text-emerald-400" />
            <span>Descubrimiento & Matching en LinkedIn</span>
          </h1>
          <p className="text-xs text-zinc-400 mt-0.5">
            Ingresa nombres y colegios (Manual, CSV o Zoho) para descubrir perfiles en LinkedIn y validarlos con certeza humana.
          </p>
        </div>

        {/* Botones de Entrada */}
        <div className="flex items-center gap-2 shrink-0 flex-wrap">
          {/* Ingreso Manual Uno a Uno */}
          <button
            onClick={() => setShowManualModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 font-semibold text-xs transition cursor-pointer shadow-sm"
          >
            <UserPlus className="w-3.5 h-3.5" />
            <span>+ Ingreso Manual</span>
          </button>

          {/* Importación Archivo */}
          <button
            onClick={() => setShowImportModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-[#121316] hover:bg-zinc-800 border border-white/[0.08] text-zinc-200 font-medium text-xs transition cursor-pointer"
          >
            <FileSpreadsheet className="w-3.5 h-3.5 text-zinc-400" />
            <span>Importar CSV/Excel</span>
          </button>

          {/* Importar desde Zoho CRM */}
          <button
            onClick={handleImportFromZoho}
            disabled={importingZoho}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-[#121316] hover:bg-zinc-800 border border-white/[0.08] text-amber-300 font-medium text-xs transition cursor-pointer disabled:opacity-50"
            title="Extraer contactos institucionales desde Zoho CRM"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${importingZoho ? 'animate-spin' : ''}`} />
            <span>{importingZoho ? 'Consultando Zoho...' : 'Importar de Zoho'}</span>
          </button>
        </div>
      </div>

      {/* 2. Bloque de Métricas del Buzón */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3.5">
        <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
          <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
            <span className="font-medium text-zinc-300">Total en Buzón</span>
            <Users className="w-3.5 h-3.5 text-zinc-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">
            {stats.total}
          </div>
          <span className="text-[10px] text-zinc-500 mt-1 block">Prospectos en proceso de matching</span>
        </div>

        <div className="p-3.5 rounded-xl bg-[#121316] border border-emerald-500/20 bg-emerald-950/10">
          <div className="flex items-center justify-between text-emerald-400 text-xs mb-1.5">
            <span className="font-medium text-emerald-300">Coincidencias Listas</span>
            <Sparkles className="w-3.5 h-3.5 text-emerald-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-emerald-400">
            {stats.matches_listos}
          </div>
          <span className="text-[10px] text-emerald-400/80 mt-1 block font-medium">Aguardando tu validación humana</span>
        </div>

        <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
          <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
            <span className="font-medium text-zinc-300">Pendientes de Búsqueda</span>
            <Search className="w-3.5 h-3.5 text-sky-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">
            {stats.pendientes}
          </div>
          <span className="text-[10px] text-zinc-500 mt-1 block">Listos para rastrear en LinkedIn</span>
        </div>

        <div className="p-3.5 rounded-xl bg-[#121316] border border-white/[0.08]">
          <div className="flex items-center justify-between text-zinc-400 text-xs mb-1.5">
            <span className="font-medium text-zinc-300">Validados & Promovidos</span>
            <CheckCircle2 className="w-3.5 h-3.5 text-teal-400" />
          </div>
          <div className="text-xl font-semibold font-mono tracking-tight text-zinc-100">
            {stats.validados}
          </div>
          <span className="text-[10px] text-zinc-500 mt-1 block">Incorporados al Directorio / Listas</span>
        </div>
      </div>

      {/* 3. Filtros y Búsqueda */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-1">
        {/* Pestañas de filtrado */}
        <div className="flex items-center gap-1 bg-[#121316] p-1 rounded-lg border border-white/[0.06] text-xs flex-wrap">
          <button
            onClick={() => setFilterStatus('MATCH_ENCONTRADO')}
            className={`px-3 py-1 rounded-md transition cursor-pointer flex items-center gap-1.5 ${
              filterStatus === 'MATCH_ENCONTRADO'
                ? 'bg-zinc-800 text-emerald-300 font-semibold shadow-xs'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Sparkles className="w-3 h-3 text-emerald-400" />
            <span>Listos para Validar ({stats.matches_listos})</span>
          </button>

          <button
            onClick={() => setFilterStatus('PENDIENTE')}
            className={`px-3 py-1 rounded-md transition cursor-pointer ${
              filterStatus === 'PENDIENTE'
                ? 'bg-zinc-800 text-zinc-100 font-medium'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            Pendientes ({stats.pendientes})
          </button>

          <button
            onClick={() => setFilterStatus('SIN_RESULTADOS')}
            className={`px-3 py-1 rounded-md transition cursor-pointer ${
              filterStatus === 'SIN_RESULTADOS'
                ? 'bg-zinc-800 text-amber-300 font-medium'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            Sin Resultados ({stats.sin_resultados})
          </button>

          <button
            onClick={() => setFilterStatus('VALIDADO')}
            className={`px-3 py-1 rounded-md transition cursor-pointer ${
              filterStatus === 'VALIDADO'
                ? 'bg-zinc-800 text-teal-300 font-medium'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            Validados ({stats.validados})
          </button>

          <button
            onClick={() => setFilterStatus('TODOS')}
            className={`px-3 py-1 rounded-md transition cursor-pointer ${
              filterStatus === 'TODOS'
                ? 'bg-zinc-800 text-zinc-200 font-medium'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            Todos ({stats.total})
          </button>
        </div>

        {/* Input de Búsqueda */}
        <div className="relative min-w-[220px]">
          <Search className="w-3.5 h-3.5 text-zinc-500 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Buscar por nombre, colegio o email..."
            className="w-full pl-8 pr-3 py-1.5 bg-[#121316] border border-white/[0.08] rounded-lg text-xs text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
          />
        </div>
      </div>

      {/* 4. Lista Comparadora Lado a Lado */}
      {loading ? (
        <div className="p-12 text-center text-zinc-500 text-xs font-mono">
          Cargando prospectos del buzón...
        </div>
      ) : leads.length === 0 ? (
        <div className="p-12 rounded-xl border border-white/[0.08] bg-[#121316] text-center space-y-3">
          <div className="w-10 h-10 rounded-xl bg-white/[0.04] border border-white/[0.08] mx-auto flex items-center justify-center text-zinc-400">
            <UserCheck className="w-5 h-5" />
          </div>
          <div className="space-y-1">
            <h3 className="text-xs font-semibold text-zinc-200">No hay prospectos en esta vista</h3>
            <p className="text-[11px] text-zinc-500 max-w-sm mx-auto">
              {searchTerm
                ? 'Prueba limpiando el término de búsqueda.'
                : 'Agrega prospectos con "+ Ingreso Manual", importa un CSV o conecta tus contactos desde Zoho.'}
            </p>
          </div>
          <div className="pt-2 flex items-center justify-center gap-2">
            <button
              onClick={() => setShowManualModal(true)}
              className="px-3.5 py-1.5 rounded-lg bg-white hover:bg-zinc-200 text-zinc-950 font-semibold text-xs transition cursor-pointer shadow-sm"
            >
              + Ingreso Manual
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {leads.map((item) => {
            const isSearching = searchingIds.has(item.id);
            const hasMatch = item.estado === 'MATCH_ENCONTRADO';
            const isValidated = item.estado === 'VALIDADO';
            const isDiscarded = item.estado === 'DESCARTADO';
            const alternatives = item.candidatos_alternativos || [];

            return (
              <div 
                key={item.id}
                className="p-4 rounded-xl bg-[#121316] border border-white/[0.08] hover:border-white/[0.14] transition grid grid-cols-1 lg:grid-cols-12 gap-4 items-center shadow-xs"
              >
                {/* COLUMNA 1: Datos de Origen (Zoho / CSV / Manual) - 4 cols */}
                <div className="lg:col-span-5 space-y-2 border-b lg:border-b-0 lg:border-r border-white/[0.06] pb-3 lg:pb-0 lg:pr-4">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded-md bg-white/[0.05] border border-white/[0.08] text-[10px] font-mono font-medium text-zinc-300">
                      {item.origen || 'MANUAL'}
                    </span>
                    <h3 className="text-xs font-semibold text-zinc-100 truncate">
                      {item.nombre}
                    </h3>
                  </div>

                  <div className="space-y-1 text-[11px] text-zinc-400">
                    <div className="flex items-center gap-1.5 truncate">
                      <Building2 className="w-3.5 h-3.5 text-zinc-500 shrink-0" />
                      <span className="font-medium text-zinc-300 truncate">{item.institucion || 'Colegio no especificado'}</span>
                    </div>

                    {item.email && (
                      <div className="flex items-center gap-1.5 truncate">
                        <Mail className="w-3.5 h-3.5 text-sky-400 shrink-0" />
                        <span className="font-mono text-sky-300 truncate">{item.email}</span>
                      </div>
                    )}

                    {item.cargo_declarado && (
                      <div className="flex items-center gap-1.5 truncate">
                        <Briefcase className="w-3.5 h-3.5 text-zinc-500 shrink-0" />
                        <span className="text-zinc-400 truncate">{item.cargo_declarado}</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* COLUMNA 2: Candidato LinkedIn Encontrado - 5 cols */}
                <div className="lg:col-span-5 space-y-2">
                  {hasMatch ? (
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-1.5 truncate">
                          <span className="w-2 h-2 rounded-full bg-emerald-400 shrink-0" />
                          <span className="text-xs font-semibold text-zinc-100 truncate">
                            {item.candidato_nombre}
                          </span>
                          {item.candidato_grado && (
                            <span className="px-1.5 py-0.2 rounded bg-zinc-800 text-[10px] font-mono text-zinc-400 border border-zinc-700">
                              {item.candidato_grado}
                            </span>
                          )}
                        </div>

                        {/* Badge de afinidad */}
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-mono border font-semibold shrink-0 ${
                          item.score_coincidencia >= 75
                            ? 'bg-emerald-950/60 text-emerald-300 border-emerald-500/40'
                            : 'bg-amber-950/60 text-amber-300 border-amber-500/40'
                        }`}>
                          {item.score_coincidencia}% Coincidencia
                        </span>
                      </div>

                      <p className="text-[11px] text-zinc-400 line-clamp-2">
                        {item.candidato_titular || 'Sin titular declarado en LinkedIn'}
                      </p>

                      <div className="flex items-center gap-3 text-[11px]">
                        {item.candidato_url && (
                          <button
                            type="button"
                            onClick={() => handleOpenProfileInBrowser(item.candidato_url)}
                            className="text-sky-400 hover:text-sky-300 transition flex items-center gap-1 cursor-pointer font-medium"
                          >
                            <Eye className="w-3 h-3" />
                            <span>Ver perfil en navegador</span>
                          </button>
                        )}

                        {alternatives.length > 0 && (
                          <div className="relative">
                            <button
                              type="button"
                              onClick={() => setExpandedAltId(expandedAltId === item.id ? null : item.id)}
                              className="text-amber-400 hover:text-amber-300 transition flex items-center gap-1 cursor-pointer"
                            >
                              <span>{alternatives.length} alternativos</span>
                              <ChevronDown className="w-3 h-3" />
                            </button>

                            {/* Dropdown de alternativos */}
                            {expandedAltId === item.id && (
                              <div className="absolute left-0 top-6 z-20 w-72 bg-[#0D0E12] border border-white/[0.12] rounded-lg shadow-2xl p-2 space-y-1.5 animate-fadeIn">
                                <span className="text-[10px] font-mono text-zinc-500 uppercase px-1.5 block">
                                  Candidatos alternativos:
                                </span>
                                {alternatives.map((alt, idx) => (
                                  <div 
                                    key={idx}
                                    onClick={() => handleSelectAlternativeCandidate(item, alt)}
                                    className="p-2 rounded-md hover:bg-zinc-800/80 cursor-pointer transition text-left space-y-0.5"
                                  >
                                    <div className="flex items-center justify-between text-[11px] font-medium text-zinc-200">
                                      <span className="truncate">{alt.nombre}</span>
                                      <span className="text-zinc-500 font-mono text-[10px]">{alt.score}%</span>
                                    </div>
                                    <p className="text-[10px] text-zinc-400 line-clamp-1">{alt.cargo_titular}</p>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  ) : isValidated ? (
                    <div className="flex items-center gap-2 text-xs text-teal-400 font-medium">
                      <CheckCircle2 className="w-4 h-4 text-teal-400" />
                      <span>Validado y promovido al Directorio oficial</span>
                    </div>
                  ) : isDiscarded ? (
                    <div className="flex items-center gap-2 text-xs text-zinc-500">
                      <XCircle className="w-4 h-4 text-zinc-500" />
                      <span>Descartado por el usuario</span>
                    </div>
                  ) : item.estado === 'SIN_RESULTADOS' ? (
                    <div className="text-xs text-amber-400/90 space-y-1">
                      <div className="flex items-center gap-1.5">
                        <AlertCircle className="w-3.5 h-3.5" />
                        <span className="font-medium">Sin perfil coincidente directo</span>
                      </div>
                      <p className="text-[10px] text-zinc-500">
                        Prueba ajustando el nombre o buscando nuevamente con el cargo.
                      </p>
                    </div>
                  ) : (
                    <div className="text-xs text-zinc-500 flex items-center gap-1.5">
                      <Search className="w-3.5 h-3.5" />
                      <span>Búsqueda pendiente de ejecución</span>
                    </div>
                  )}
                </div>

                {/* COLUMNA 3: Acciones Rápidas - 2 cols */}
                <div className="lg:col-span-2 flex items-center justify-end gap-1.5">
                  {hasMatch ? (
                    <>
                      {/* Botón Confirmar y Promover */}
                      <button
                        onClick={() => setSelectedLeadToConfirm(item)}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-md bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-semibold text-xs shadow-sm transition cursor-pointer"
                        title="Confirmar que es la persona correcta y agregar a NexusReach"
                      >
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>Validar</span>
                      </button>

                      <button
                        onClick={() => handleDiscard(item.id)}
                        className="p-1.5 rounded-md hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition cursor-pointer"
                        title="Descartar este candidato"
                      >
                        <XCircle className="w-3.5 h-3.5" />
                      </button>
                    </>
                  ) : (
                    <>
                      {/* Botón Buscar en LinkedIn */}
                      <button
                        onClick={() => handleSearchCandidate(item.id)}
                        disabled={isSearching}
                        className="flex items-center gap-1 px-2.5 py-1.5 rounded-md bg-sky-950/60 hover:bg-sky-900/80 text-sky-300 border border-sky-500/30 text-xs font-medium transition cursor-pointer disabled:opacity-50"
                        title="Rastrear coincidencia en LinkedIn"
                      >
                        <Search className={`w-3.5 h-3.5 ${isSearching ? 'animate-spin' : ''}`} />
                        <span>{isSearching ? 'Buscando...' : 'Buscar'}</span>
                      </button>

                      <button
                        onClick={() => handleDelete(item.id)}
                        className="p-1.5 rounded-md hover:bg-red-950/40 text-zinc-500 hover:text-red-400 transition cursor-pointer"
                        title="Eliminar del buzón"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Modales */}
      {showManualModal && (
        <NewManualLeadModal
          onClose={() => setShowManualModal(false)}
          onCreated={loadData}
          activeTenantWorkspace={activeTenantWorkspace}
        />
      )}

      {showImportModal && (
        <ImportFileModal
          onClose={() => setShowImportModal(false)}
          onImported={loadData}
          activeTenantWorkspace={activeTenantWorkspace}
        />
      )}

      {selectedLeadToConfirm && (
        <ConfirmMatchModal
          lead={selectedLeadToConfirm}
          onClose={() => setSelectedLeadToConfirm(null)}
          onConfirmed={loadData}
          activeTenantWorkspace={activeTenantWorkspace}
        />
      )}
    </div>
  );
}

