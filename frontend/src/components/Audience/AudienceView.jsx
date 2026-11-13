import React, { useState } from 'react';
import { Search, UserCheck, ListFilter, Users } from 'lucide-react';
import ProspectsView from '../Prospects/ProspectsView';
import MatchingView from '../Matching/MatchingView';
import ListsView from '../Lists/ListsView';
import LeadsDirectoryView from '../Prospects/LeadsDirectoryView';

export default function AudienceView({
  activeTenantWorkspace = '',
  initialSubTab = 'buscar', // 'buscar' | 'validar' | 'listas' | 'todos'
  matchingCount = 0,
  totalLeadsCount = 0,
  listsCount = 0,
  onExtractionStarted = null,
  onSelectSequence = null,
  onNavigateToTab = null,
}) {
  const [subTab, setSubTab] = useState(initialSubTab);

  const tabs = [
    { id: 'buscar', label: 'Buscar en LinkedIn', icon: Search, badge: null },
    { id: 'validar', label: 'Importar y validar', icon: UserCheck, badge: matchingCount || null },
    { id: 'listas', label: 'Mis listas', icon: ListFilter, badge: listsCount || null },
    { id: 'todos', label: 'Todos los contactos', icon: Users, badge: totalLeadsCount || null },
  ];

  return (
    <div className="space-y-5 font-sans animate-fadeIn">
      {/* Navegación interna limpia de Audiencia */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-white/[0.08] pb-3">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100 tracking-tight">
            Audiencia y preparación de contactos
          </h1>
          <p className="text-xs text-zinc-300 mt-0.5">
            Encuentra decisores, importa o valida tus prospectos y organízalos en listas listas para contactar.
          </p>
        </div>

        <div className="inline-flex flex-wrap gap-1 p-1 rounded-lg bg-[#121316] border border-white/[0.08] self-start sm:self-auto">
          {tabs.map((t) => {
            const Icon = t.icon;
            const active = subTab === t.id;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => setSubTab(t.id)}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition cursor-pointer ${
                  active
                    ? 'bg-white/[0.12] text-white shadow-xs'
                    : 'text-zinc-300 hover:text-white hover:bg-white/[0.04]'
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                <span>{t.label}</span>
                {t.badge !== null && (
                  <span className="px-1.5 py-0.5 rounded bg-white/[0.08] text-[11px] font-mono text-zinc-200 leading-none">
                    {t.badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Subvista activa */}
      {subTab === 'buscar' && (
        <ProspectsView
          onExtractionStarted={onExtractionStarted}
          activeTenantWorkspace={activeTenantWorkspace}
          onNavigateToTab={onNavigateToTab}
        />
      )}

      {subTab === 'validar' && (
        <MatchingView activeTenantWorkspace={activeTenantWorkspace} />
      )}

      {subTab === 'listas' && (
        <ListsView
          activeTenantWorkspace={activeTenantWorkspace}
          onSelectSequence={onSelectSequence}
          onNavigateToSearch={() => setSubTab('buscar')}
        />
      )}

      {subTab === 'todos' && (
        <LeadsDirectoryView
          activeTenantWorkspace={activeTenantWorkspace}
          onOpenLeadSearch={() => setSubTab('buscar')}
        />
      )}
    </div>
  );
}

