import React, { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import TopBar from './components/TopBar';
import SafetyBanner from './components/SafetyBanner';
import ProspectsView from './components/Prospects/ProspectsView';
import ListsView from './components/Lists/ListsView';
import SequencesView from './components/Sequences/SequencesView';
import ActivityLogsView from './components/Logs/ActivityLogsView';
import SuperAdminView from './components/Admin/SuperAdminView';
import AdminClientsView from './components/Admin/AdminClientsView';
import CreateAccountView from './components/Admin/CreateAccountView';
import AgencyPortalView from './components/Agency/AgencyPortalView';
import LoginView from './components/Auth/LoginView';
import SubscriptionModal from './components/Auth/SubscriptionModal';
import { 
  fetchLeadLists, 
  fetchSequences, 
  fetchLogStats, 
  fetchBrowserStatus, 
  fetchSafetyStatus, 
  toggleCampaign, 
  showWorkBrowser,
  checkUserSession,
  logoutUser,
  fetchAgencyFinances
} from './services/api';

function getDefaultTabForUser(user) {
  if (user?.rol === 'SUPER_ADMIN') return 'super_admin';
  if (user?.rol === 'AGENCY_ADMIN') return 'agency_portal';
  return 'prospectos';
}

export default function App() {
  const [currentUser, setCurrentUser] = useState(null);
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);
  const [isSubscriptionModalOpen, setIsSubscriptionModalOpen] = useState(false);

  const [activeTab, setActiveTab] = useState('prospectos');
  const [listsCount, setListsCount] = useState(0);
  const [sequencesCount, setSequencesCount] = useState(0);
  const [logsCount, setLogsCount] = useState(0);
  const [isExtracting, setIsExtracting] = useState(false);
  const [linkedinSessionActive, setLinkedinSessionActive] = useState(false);
  const [campaignActive, setCampaignActive] = useState(true);

  // Workspace seleccionado para Operar (vacío = sede propia de la organización)
  const [selectedWorkspaceTenantId, setSelectedWorkspaceTenantId] = useState('');
  const [selectedWorkspaceName, setSelectedWorkspaceName] = useState('');
  const [agencyClients, setAgencyClients] = useState([]);

  // Verificación inicial de sesión al arrancar la app
  useEffect(() => {
    initAuth();
  }, []);

  async function initAuth() {
    try {
      setIsCheckingAuth(true);
      const user = await checkUserSession();
      setCurrentUser(user);
      setSelectedWorkspaceTenantId('');
      setSelectedWorkspaceName('');
      if (user) {
        setActiveTab(getDefaultTabForUser(user));
      }
    } catch {
      setCurrentUser(null);
    } finally {
      setIsCheckingAuth(false);
    }
  }

  // Cargar cartera de clientes si el usuario logueado es Administrador de Agencia
  useEffect(() => {
    if (currentUser?.rol === 'AGENCY_ADMIN') {
      loadAgencyClients();
    } else {
      setAgencyClients([]);
      setSelectedWorkspaceTenantId('');
      setSelectedWorkspaceName('');
    }
  }, [currentUser]);

  // La consola Super Admin no utiliza logs de prospección
  useEffect(() => {
    if (currentUser?.rol === 'SUPER_ADMIN' && activeTab === 'logs') {
      setActiveTab('super_admin');
    }
  }, [currentUser, activeTab]);

  async function loadAgencyClients() {
    try {
      const agencyId = currentUser?.tenant?.id || 'ten_growthx';
      const data = await fetchAgencyFinances(agencyId);
      if (data?.clientes) {
        setAgencyClients(data.clientes);
      }
    } catch (err) {
      console.error('Error cargando cartera de clientes para el selector de workspace:', err);
    }
  }

  function handleSelectWorkspace(tenantId, name = '') {
    setSelectedWorkspaceTenantId(tenantId || '');
    setSelectedWorkspaceName(name || '');
    if (tenantId) {
      setActiveTab('prospectos');
    }
  }

  function handleExitWorkspace() {
    setSelectedWorkspaceTenantId('');
    setSelectedWorkspaceName('');
    if (currentUser?.rol === 'SUPER_ADMIN') {
      setActiveTab('super_admin');
    } else if (currentUser?.rol === 'AGENCY_ADMIN') {
      setActiveTab('agency_portal');
    }
  }

  // Consulta periódica de contadores y estado de LinkedIn solo si hay usuario autenticado
  useEffect(() => {
    if (!currentUser) return;

    refreshCounters();
    checkConnectionAndCampaign();
    const interval = setInterval(() => {
      refreshCounters();
      checkConnectionAndCampaign();
    }, 6000);
    return () => clearInterval(interval);
  }, [currentUser, selectedWorkspaceTenantId]);

  async function checkConnectionAndCampaign() {
    try {
      const [browser, safety] = await Promise.all([
        fetchBrowserStatus().catch(() => ({})),
        fetchSafetyStatus().catch(() => ({})),
      ]);
      setLinkedinSessionActive(Boolean(browser.sesion_linkedin_activa));
      const isStopped = Boolean(safety.kill_switch?.activado || safety.kill_switch === true);
      setCampaignActive(!isStopped);
    } catch {}
  }

  async function refreshCounters() {
    try {
      const [lists, seqs, logStats] = await Promise.all([
        fetchLeadLists(selectedWorkspaceTenantId).catch(() => []),
        fetchSequences(selectedWorkspaceTenantId).catch(() => []),
        fetchLogStats().catch(() => ({})),
      ]);

      setListsCount(lists.length);
      setSequencesCount(seqs.length);
      setLogsCount(logStats.total_logs || 0);
      setIsExtracting(Boolean(logStats.is_extracting_now));
    } catch (err) {
      console.error('Error actualizando contadores:', err);
    }
  }

  async function handleLoginLinkedin() {
    try {
      await showWorkBrowser('https://www.linkedin.com/login');
      setTimeout(checkConnectionAndCampaign, 2000);
    } catch (err) {
      alert(`Error abriendo login de LinkedIn: ${err.message}`);
    }
  }

  async function handleViewBrowser() {
    try {
      await showWorkBrowser();
      setTimeout(checkConnectionAndCampaign, 1500);
    } catch (err) {
      alert(`Error con el navegador de trabajo: ${err.message}`);
    }
  }

  async function handleToggleCampaign() {
    try {
      const nextState = !campaignActive;
      const res = await toggleCampaign(nextState);
      setCampaignActive(Boolean(res.activa));
    } catch (err) {
      alert(`Error cambiando estado de campaña: ${err.message}`);
    }
  }

  function handleLogStatusChange({ isExtracting: extracting, totalLogs }) {
    setIsExtracting(extracting);
    setLogsCount(totalLogs);
  }

  async function handleLogout() {
    await logoutUser();
    setCurrentUser(null);
    setSelectedWorkspaceTenantId('');
    setSelectedWorkspaceName('');
    setIsSubscriptionModalOpen(false);
  }

  // Pantalla de carga mientras se verifica si existe token en memoria
  if (isCheckingAuth) {
    return (
      <div className="min-h-screen bg-[#090A0C] flex flex-col items-center justify-center p-4 select-none">
        <div className="w-10 h-10 rounded-lg bg-zinc-900 border border-zinc-800 flex items-center justify-center text-zinc-200 font-semibold text-xs tracking-wider mb-3 shadow-xs">
          NR
        </div>
        <div className="flex items-center gap-2 text-[11px] font-mono text-zinc-500">
          <div className="w-3 h-3 border border-zinc-700 border-t-zinc-300 rounded-full animate-spin" />
          <span>Verificando sesión...</span>
        </div>
      </div>
    );
  }

  // Si no está autenticado, renderizar obligatoriamente la pantalla de Login
  if (!currentUser) {
    return (
      <LoginView 
        onLoginSuccess={(user) => {
          setCurrentUser(user);
          setActiveTab(getDefaultTabForUser(user));
        }} 
      />
    );
  }

  return (
    <div className="min-h-screen bg-[#090A0C] text-zinc-100 flex font-sans antialiased overflow-hidden">
      {/* 1. Menú lateral izquierdo (Sidebar) */}
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        listsCount={listsCount}
        sequencesCount={sequencesCount}
        logsCount={logsCount}
        isExtracting={isExtracting}
        linkedinSessionActive={linkedinSessionActive}
        campaignActive={campaignActive}
        onToggleCampaign={handleToggleCampaign}
        onLoginLinkedin={handleLoginLinkedin}
        onViewBrowser={handleViewBrowser}
        currentUser={currentUser}
        selectedWorkspaceTenantId={selectedWorkspaceTenantId}
        selectedWorkspaceName={selectedWorkspaceName}
        onExitWorkspace={handleExitWorkspace}
      />

      {/* 2. Área principal de contenido (derecha) */}
      <div className="flex-1 flex flex-col min-w-0 h-screen overflow-y-auto">
        <TopBar
          activeTab={activeTab}
          linkedinSessionActive={linkedinSessionActive}
          onLoginLinkedin={handleLoginLinkedin}
          onViewBrowser={handleViewBrowser}
          currentUser={currentUser}
          onOpenSubscriptionModal={() => setIsSubscriptionModalOpen(true)}
          onLogout={handleLogout}
          agencyClients={agencyClients}
          selectedWorkspaceTenantId={selectedWorkspaceTenantId}
          selectedWorkspaceName={selectedWorkspaceName}
          onSelectWorkspace={handleSelectWorkspace}
          onExitWorkspace={handleExitWorkspace}
        />

        <main className="flex-1 p-6 space-y-6 max-w-7xl w-full mx-auto">
          {/* Banner de seguridad y límites de prospección (oculto en Consola Master, Clientes y Crear Cuenta) */}
          {!['super_admin', 'admin_clientes', 'admin_crear_cuenta'].includes(activeTab) && (
            <SafetyBanner quotaToday={0} quotaMax={5} />
          )}

          {/* Vistas modulares */}
          {activeTab === 'super_admin' && (
            <SuperAdminView 
              onEnterWorkspace={handleSelectWorkspace} 
              onNavigateToClients={() => setActiveTab('admin_clientes')}
            />
          )}

          {activeTab === 'admin_clientes' && (
            <AdminClientsView 
              onEnterWorkspace={handleSelectWorkspace} 
              onNavigateToCreateAccount={() => setActiveTab('admin_crear_cuenta')}
            />
          )}

          {activeTab === 'admin_crear_cuenta' && (
            <CreateAccountView 
              onEnterWorkspace={handleSelectWorkspace} 
              onNavigateToClients={() => setActiveTab('admin_clientes')}
            />
          )}

          {activeTab === 'agency_portal' && (
            <AgencyPortalView 
              currentUser={currentUser} 
              onSelectWorkspace={handleSelectWorkspace}
            />
          )}

          {activeTab === 'prospectos' && (
            <ProspectsView 
              onExtractionStarted={() => setIsExtracting(true)} 
              activeTenantWorkspace={selectedWorkspaceTenantId}
            />
          )}

          {activeTab === 'listas' && (
            <ListsView 
              onSelectSequence={() => setActiveTab('secuencias')} 
              activeTenantWorkspace={selectedWorkspaceTenantId}
            />
          )}

          {activeTab === 'secuencias' && (
            <SequencesView 
              activeTenantWorkspace={selectedWorkspaceTenantId}
            />
          )}

          {activeTab === 'logs' && (
            <ActivityLogsView onStatusChange={handleLogStatusChange} />
          )}
        </main>
      </div>

      {/* Modal de detalles de suscripción y usuario */}
      <SubscriptionModal
        isOpen={isSubscriptionModalOpen}
        onClose={() => setIsSubscriptionModalOpen(false)}
        currentUser={currentUser}
        onLogout={handleLogout}
        onUserUpdated={(updated) => setCurrentUser(updated)}
      />
    </div>
  );
}
