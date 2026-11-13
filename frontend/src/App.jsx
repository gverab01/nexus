import React, { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import TopBar from './components/TopBar';
import SafetyBanner from './components/SafetyBanner';
import ToastContainer, { showToast } from './components/Toast';
import ProspectsView from './components/Prospects/ProspectsView';
import ListsView from './components/Lists/ListsView';
import SequencesView from './components/Sequences/SequencesView';
import ActivityLogsView from './components/Activity/ActivityLogsView';
import SuperAdminView from './components/Admin/SuperAdminView';
import AdminClientsView from './components/Admin/AdminClientsView';
import CreateAccountView from './components/Admin/CreateAccountView';
import AgencyPortalView from './components/Agency/AgencyPortalView';
import LoginView from './components/Auth/LoginView';
import SubscriptionModal from './components/Auth/SubscriptionModal';
import LeadsDirectoryView from './components/Prospects/LeadsDirectoryView';
import AntibanSettingsModal from './components/AntibanSettingsModal';
import AntibanSettingsView from './components/Antiban/AntibanSettingsView';
import DashboardView from './components/Dashboard/DashboardView';
import MatchingView from './components/Matching/MatchingView';
import InicioView from './components/Home/InicioView';
import AudienceView from './components/Audience/AudienceView';
import SettingsView from './components/Settings/SettingsView';
import CampaignWizardModal from './components/Sequences/CampaignWizardModal';
import { 
  fetchLeadLists, 
  fetchSequences, 
  fetchLogStats, 
  fetchBrowserStatus, 
  fetchSafetyStatus, 
  toggleCampaign, 
  updateSafetyConfig,
  showWorkBrowser,
  checkUserSession,
  logoutUser,
  fetchAgencyFinances,
  fetchProspects,
  loginZoho,
  logoutZoho,
  fetchMatchingStats
} from './services/api';

function getDefaultTabForUser(user) {
  if (user?.rol === 'SUPER_ADMIN') return 'super_admin';
  if (user?.rol === 'AGENCY_ADMIN') return 'agency_portal';
  return 'inicio';
}

export default function App() {
  const [currentUser, setCurrentUser] = useState(null);
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);
  const [isSubscriptionModalOpen, setIsSubscriptionModalOpen] = useState(false);
  const [isAntibanModalOpen, setIsAntibanModalOpen] = useState(false);
  const [antibanConfig, setAntibanConfig] = useState({
    horario_laboral_activo: true,
    pausas_antiban_activas: true,
    limites_diarios_activos: true,
    limite_linkedin_diario: 5,
    limite_email_workspace_diario: 15,
  });

  const [activeTab, setActiveTab] = useState('inicio');
  const [audienceSubTab, setAudienceSubTab] = useState('buscar');
  const [settingsSubTab, setSettingsSubTab] = useState('canales');
  const [isCampaignWizardOpen, setIsCampaignWizardOpen] = useState(false);
  const [totalLeadsCount, setTotalLeadsCount] = useState(0);
  const [listsCount, setListsCount] = useState(0);
  const [sequencesCount, setSequencesCount] = useState(0);
  const [matchingCount, setMatchingCount] = useState(0);
  const [logsCount, setLogsCount] = useState(0);
  const [isExtracting, setIsExtracting] = useState(false);
  const [linkedinSessionActive, setLinkedinSessionActive] = useState(false);
  const [whatsappSessionActive, setWhatsappSessionActive] = useState(false);
  const [zohoSessionActive, setZohoSessionActive] = useState(false);
  const [campaignActive, setCampaignActive] = useState(true);

  // Workspace seleccionado para Operar (vacío = sede propia de la organización)
  const [selectedWorkspaceTenantId, setSelectedWorkspaceTenantId] = useState('');
  const [selectedWorkspaceName, setSelectedWorkspaceName] = useState('');
  const [agencyClients, setAgencyClients] = useState([]);
  const [selectedSequenceId, setSelectedSequenceId] = useState(null);

  function handleTabChange(nextTab) {
    if (nextTab === 'secuencias' || nextTab === 'campanas') {
      setSelectedSequenceId(null);
      setActiveTab('campanas');
      return;
    }
    if (nextTab === 'prospectos') {
      setAudienceSubTab('buscar');
      setActiveTab('audiencia');
      return;
    }
    if (nextTab === 'matching') {
      setAudienceSubTab('validar');
      setActiveTab('audiencia');
      return;
    }
    if (nextTab === 'listas') {
      setAudienceSubTab('listas');
      setActiveTab('audiencia');
      return;
    }
    if (nextTab === 'leads_directorio') {
      setAudienceSubTab('todos');
      setActiveTab('audiencia');
      return;
    }
    if (nextTab === 'antiban') {
      setSettingsSubTab('proteccion');
      setActiveTab('ajustes');
      return;
    }
    if (nextTab === 'logs') {
      setSettingsSubTab('historial');
      setActiveTab('ajustes');
      return;
    }
    setActiveTab(nextTab);
  }

  // Verificación inicial de sesión al arrancar la app
  useEffect(() => {
    initAuth();

    function handleUnauthorized() {
      setCurrentUser(null);
    }
    window.addEventListener('nexus:unauthorized', handleUnauthorized);
    return () => window.removeEventListener('nexus:unauthorized', handleUnauthorized);
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

  // Sincronización de rol inicial
  useEffect(() => {
    // Mantener la navegación coherente según rol
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

  // Consulta periódica consciente de visibilidad (ahorro de CPU/red cuando la ventana está minimizada u oculta)
  useEffect(() => {
    if (!currentUser) return;

    const runSync = () => {
      refreshCounters();
      checkConnectionAndCampaign();
    };

    runSync();
    const interval = setInterval(() => {
      if (!document.hidden) {
        runSync();
      }
    }, 12000);

    const handleVisibility = () => {
      if (!document.hidden) {
        runSync();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, [currentUser, selectedWorkspaceTenantId]);

  async function checkConnectionAndCampaign() {
    try {
      const [browser, safety] = await Promise.all([
        fetchBrowserStatus().catch(() => ({})),
        fetchSafetyStatus().catch(() => ({})),
      ]);
      setLinkedinSessionActive(Boolean(browser.sesion_linkedin_activa));
      setWhatsappSessionActive(Boolean(browser.sesion_whatsapp_activa));
      setZohoSessionActive(Boolean(browser.sesion_zoho_activa));
      const isStopped = Boolean(safety.kill_switch?.activado || safety.kill_switch === true);
      setCampaignActive(!isStopped);

      if (safety?.configuracion) {
        setAntibanConfig({
          horario_laboral_activo: safety.configuracion.horario_laboral_activo !== '0',
          pausas_antiban_activas: safety.configuracion.pausas_antiban_activas !== '0',
          limites_diarios_activos: safety.configuracion.limites_diarios_activos !== '0',
          limite_linkedin_diario: parseInt(safety.configuracion.limite_linkedin_diario || '5', 10),
          limite_email_workspace_diario: parseInt(safety.configuracion.limite_email_workspace_diario || '15', 10),
        });
      }
    } catch {}
  }

  async function handleToggleAntiban(key) {
    try {
      const currentVal = Boolean(antibanConfig[key]);
      const nextVal = !currentVal;
      setAntibanConfig((prev) => ({ ...prev, [key]: nextVal }));
      await updateSafetyConfig(key, nextVal ? '1' : '0');
      setTimeout(checkConnectionAndCampaign, 500);
    } catch (err) {
      console.error('Error toggling antiban setting:', err);
      checkConnectionAndCampaign();
    }
  }

  async function refreshCounters() {
    try {
      const isAdmin = Boolean(currentUser && ['SUPER_ADMIN', 'AGENCY_ADMIN', 'COMPANY_ADMIN'].includes(currentUser.rol));
      const [lists, seqs, logStats, leadsData, matchStats] = await Promise.all([
        fetchLeadLists(selectedWorkspaceTenantId).catch(() => []),
        fetchSequences(selectedWorkspaceTenantId).catch(() => []),
        fetchLogStats({ silent: true }).catch(() => ({ total_logs: 0, is_extracting_now: false })),
        fetchProspects({ limit: 1, tenantId: selectedWorkspaceTenantId }).catch(() => ({ total: 0 })),
        fetchMatchingStats(selectedWorkspaceTenantId).catch(() => ({ matches_listos: 0, pendientes: 0 })),
      ]);

      setListsCount(lists.length);
      setSequencesCount(seqs.length);
      setLogsCount(logStats?.total_logs || 0);
      setTotalLeadsCount(leadsData?.total || 0);
      setMatchingCount((matchStats?.matches_listos || 0) + (matchStats?.pendientes || 0));
      setIsExtracting(Boolean(logStats?.is_extracting_now));
    } catch (err) {
      console.error('Error actualizando contadores:', err);
    }
  }

  async function handleOpenLinkedin() {
    try {
      const url = linkedinSessionActive ? 'https://www.linkedin.com/feed/' : 'https://www.linkedin.com/login';
      await showWorkBrowser(url, 'linkedin');
      setTimeout(checkConnectionAndCampaign, 1500);
    } catch (err) {
      showToast(`Error abriendo LinkedIn: ${err.message}`, 'error');
    }
  }

  async function handleOpenWhatsApp() {
    try {
      await showWorkBrowser('https://web.whatsapp.com', 'whatsapp');
      setTimeout(checkConnectionAndCampaign, 1500);
    } catch (err) {
      showToast(`Error abriendo WhatsApp Web: ${err.message}`, 'error');
    }
  }

  async function handleLoginLinkedin() {
    return handleOpenLinkedin();
  }

  async function handleLoginWhatsApp() {
    return handleOpenWhatsApp();
  }

  async function handleOpenZoho() {
    try {
      if (zohoSessionActive) {
        await showWorkBrowser('https://crm.zoho.com/crm/org902879914/tab/Home', 'zoho');
      } else {
        await loginZoho();
      }
      setTimeout(checkConnectionAndCampaign, 1500);
    } catch (err) {
      showToast(`Error abriendo Zoho CRM: ${err.message}`, 'error');
    }
  }

  async function handleLoginZoho() {
    try {
      await loginZoho();
      setTimeout(checkConnectionAndCampaign, 1500);
    } catch (err) {
      showToast(`Error conectando con Zoho Accounts: ${err.message}`, 'error');
    }
  }

  async function handleLogoutZoho() {
    try {
      setZohoSessionActive(false);
      await logoutZoho();
      setTimeout(checkConnectionAndCampaign, 2000);
    } catch (err) {
      showToast(`Error cerrando sesión en Zoho: ${err.message}`, 'error');
    }
  }

  async function handleViewBrowser() {
    try {
      await showWorkBrowser(null, 'linkedin');
      setTimeout(checkConnectionAndCampaign, 1500);
    } catch (err) {
      showToast(`Error con el navegador de trabajo: ${err.message}`, 'error');
    }
  }

  async function handleToggleCampaign() {
    try {
      const nextState = !campaignActive;
      const res = await toggleCampaign(nextState);
      const isNowActive = Boolean(res.activa);
      setCampaignActive(isNowActive);
      showToast(
        isNowActive ? 'Campañas reanudadas. Los envíos programados continuarán automáticamente.' : 'Campañas en pausa. No se enviarán nuevos mensajes hasta que las reanudes.',
        isNowActive ? 'success' : 'warning'
      );
    } catch (err) {
      showToast(`Error cambiando estado de campaña: ${err.message}`, 'error');
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
        setActiveTab={handleTabChange}
        totalLeadsCount={totalLeadsCount}
        listsCount={listsCount}
        sequencesCount={sequencesCount}
        matchingCount={matchingCount}
        logsCount={logsCount}
        isExtracting={isExtracting}
        linkedinSessionActive={linkedinSessionActive}
        whatsappSessionActive={whatsappSessionActive}
        zohoSessionActive={zohoSessionActive}
        campaignActive={campaignActive}
        onToggleCampaign={handleToggleCampaign}
        onLoginLinkedin={handleLoginLinkedin}
        onLoginWhatsApp={handleLoginWhatsApp}
        onLoginZoho={handleLoginZoho}
        onOpenLinkedin={handleOpenLinkedin}
        onOpenWhatsApp={handleOpenWhatsApp}
        onOpenZoho={handleOpenZoho}
        onLogoutZoho={handleLogoutZoho}
        onViewBrowser={handleViewBrowser}
        antibanConfig={antibanConfig}
        onToggleAntiban={handleToggleAntiban}
        onOpenAntibanSettings={() => setIsAntibanModalOpen(true)}
        currentUser={currentUser}
        agencyClients={agencyClients}
        selectedWorkspaceTenantId={selectedWorkspaceTenantId}
        selectedWorkspaceName={selectedWorkspaceName}
        onSelectWorkspace={handleSelectWorkspace}
        onExitWorkspace={handleExitWorkspace}
        onOpenSubscriptionModal={() => setIsSubscriptionModalOpen(true)}
        onLogout={handleLogout}
      />

      {/* 2. Área principal de contenido (derecha) */}
      <div className="flex-1 flex flex-col min-w-0 h-screen overflow-hidden bg-[#0E0F12]">
        <TopBar
          activeTab={activeTab}
          campaignActive={campaignActive}
          onToggleCampaign={handleToggleCampaign}
          onViewBrowser={handleViewBrowser}
          currentUser={currentUser}
          agencyClients={agencyClients}
          selectedWorkspaceTenantId={selectedWorkspaceTenantId}
          selectedWorkspaceName={selectedWorkspaceName}
          onSelectWorkspace={handleSelectWorkspace}
          onExitWorkspace={handleExitWorkspace}
          onNavigateToTab={handleTabChange}
        />
        <div className="flex-1 overflow-y-auto min-w-0">
          <main className="p-6 space-y-6 max-w-7xl w-full mx-auto">
            {/* Banner de seguridad contextual (solo activo ante amenazas reales de antiban o checkpoints) */}
          {!['super_admin', 'admin_clientes', 'admin_crear_cuenta'].includes(activeTab) && (
            <SafetyBanner activeTab={activeTab} />
          )}

          {/* Vistas modulares */}
          {activeTab === 'super_admin' && (
            <SuperAdminView 
              onEnterWorkspace={handleSelectWorkspace} 
              onNavigateToClients={() => handleTabChange('admin_clientes')}
            />
          )}

          {activeTab === 'admin_clientes' && (
            <AdminClientsView 
              onEnterWorkspace={handleSelectWorkspace} 
              onNavigateToCreateAccount={() => handleTabChange('admin_crear_cuenta')}
            />
          )}

          {activeTab === 'admin_crear_cuenta' && (
            <CreateAccountView 
              onEnterWorkspace={handleSelectWorkspace} 
              onNavigateToClients={() => handleTabChange('admin_clientes')}
            />
          )}

          {activeTab === 'agency_portal' && (
            <AgencyPortalView 
              currentUser={currentUser} 
              onSelectWorkspace={handleSelectWorkspace}
            />
          )}

          {activeTab === 'inicio' && (
            <InicioView
              activeTenantWorkspace={selectedWorkspaceTenantId}
              linkedinSessionActive={linkedinSessionActive}
              campaignActive={campaignActive}
              sequencesCount={sequencesCount}
              totalLeadsCount={totalLeadsCount}
              onToggleCampaign={handleToggleCampaign}
              onOpenLinkedin={handleOpenLinkedin}
              onNavigateToTab={handleTabChange}
              onOpenCampaignWizard={() => setIsCampaignWizardOpen(true)}
              onOpenFullAnalytics={() => handleTabChange('dashboard')}
            />
          )}

          {activeTab === 'audiencia' && (
            <AudienceView
              key={audienceSubTab}
              activeTenantWorkspace={selectedWorkspaceTenantId}
              initialSubTab={audienceSubTab}
              matchingCount={matchingCount}
              totalLeadsCount={totalLeadsCount}
              listsCount={listsCount}
              onExtractionStarted={() => setIsExtracting(true)}
              onSelectSequence={(seq) => {
                setSelectedSequenceId(seq?.id || null);
                setActiveTab('campanas');
              }}
              onNavigateToTab={handleTabChange}
            />
          )}

          {activeTab === 'campanas' && (
            <SequencesView 
              activeTenantWorkspace={selectedWorkspaceTenantId}
              initialSequenceId={selectedSequenceId}
              onBackToGlobal={() => setSelectedSequenceId(null)}
              onSequencesUpdated={refreshCounters}
            />
          )}

          {activeTab === 'dashboard' && (
            <DashboardView 
              activeTenantWorkspace={selectedWorkspaceTenantId}
              onNavigateToTab={(tab, seqId) => {
                if (seqId) setSelectedSequenceId(seqId);
                handleTabChange(tab);
              }}
            />
          )}

          {activeTab === 'ajustes' && (
            <SettingsView
              key={settingsSubTab}
              activeTenantWorkspace={selectedWorkspaceTenantId}
              initialSubTab={settingsSubTab}
              currentUser={currentUser}
              linkedinSessionActive={linkedinSessionActive}
              whatsappSessionActive={whatsappSessionActive}
              zohoSessionActive={zohoSessionActive}
              onOpenLinkedin={handleOpenLinkedin}
              onOpenWhatsApp={handleOpenWhatsApp}
              onOpenZoho={handleOpenZoho}
              onLogoutZoho={handleLogoutZoho}
              onViewBrowser={handleViewBrowser}
              onLogStatusChange={handleLogStatusChange}
            />
          )}
        </main>
        </div>
      </div>

      {/* Modal de detalles de suscripción y usuario */}
      <SubscriptionModal
        isOpen={isSubscriptionModalOpen}
        onClose={() => setIsSubscriptionModalOpen(false)}
        currentUser={currentUser}
        onLogout={handleLogout}
        onUserUpdated={(updated) => setCurrentUser(updated)}
      />

      {/* Modal de Ajustes Avanzados Antiban */}
      <AntibanSettingsModal
        isOpen={isAntibanModalOpen}
        onClose={() => setIsAntibanModalOpen(false)}
        onSaved={checkConnectionAndCampaign}
      />

      {/* Wizard Guiado para Crear Nueva Campaña */}
      <CampaignWizardModal
        isOpen={isCampaignWizardOpen}
        onClose={() => setIsCampaignWizardOpen(false)}
        activeTenantWorkspace={selectedWorkspaceTenantId}
        onCreated={async (created) => {
          await refreshCounters();
          setSelectedSequenceId(created?.id || null);
          setActiveTab('campanas');
        }}
      />

      {/* Notificaciones no bloqueantes */}
      <ToastContainer />
    </div>
  );
}
