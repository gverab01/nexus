import React, { useState, useEffect } from 'react';
import { 
  Users, 
  ListFilter, 
  GitFork, 
  Terminal, 
  Compass, 
  Power, 
  FileText, 
  CheckCircle2, 
  AlertCircle,
  Key,
  Eye
} from 'lucide-react';
import { fetchBrowserStatus, launchBrowser, toggleCampaign, fetchSafetyStatus, showWorkBrowser } from '../services/api';

export default function Header({ 
  activeTab, 
  setActiveTab, 
  listsCount = 0, 
  sequencesCount = 0, 
  logsCount = 0,
  isExtracting = false 
}) {
  const [browserOnline, setBrowserOnline] = useState(false);
  const [browserMotor, setBrowserMotor] = useState('');
  const [isElectron, setIsElectron] = useState(false);
  const [linkedinSessionActive, setLinkedinSessionActive] = useState(false);
  const [checkingBrowser, setCheckingBrowser] = useState(false);
  const [campaignActive, setCampaignActive] = useState(true);
  const [launchingBrowser, setLaunchingBrowser] = useState(false);

  // Consulta inicial y periódica del estado del navegador de trabajo y campaña
  useEffect(() => {
    checkBrowserConnection();
    checkCampaignStatus();
    const interval = setInterval(checkBrowserConnection, 8000);
    return () => clearInterval(interval);
  }, []);

  async function checkCampaignStatus() {
    try {
      const data = await fetchSafetyStatus();
      const isStopped = Boolean(data.kill_switch?.activado || data.kill_switch === true);
      setCampaignActive(!isStopped);
    } catch {
      setCampaignActive(true);
    }
  }

  async function checkBrowserConnection() {
    try {
      setCheckingBrowser(true);
      const data = await fetchBrowserStatus();
      setBrowserOnline(Boolean(data.online || data.activo));
      setIsElectron(Boolean(data.is_electron));
      setBrowserMotor(data.motor || (data.online ? 'Activo' : 'Inactivo'));
      setLinkedinSessionActive(Boolean(data.sesion_linkedin_activa));
    } catch {
      setBrowserOnline(false);
      setIsElectron(false);
      setBrowserMotor('Inactivo');
      setLinkedinSessionActive(false);
    } finally {
      setCheckingBrowser(false);
    }
  }

  async function handleLoginLinkedin() {
    try {
      setLaunchingBrowser(true);
      await showWorkBrowser('https://www.linkedin.com/login');
      setTimeout(checkBrowserConnection, 2000);
    } catch (err) {
      alert(`Error abriendo login de LinkedIn: ${err.message}`);
    } finally {
      setLaunchingBrowser(false);
    }
  }

  async function handleViewBrowser() {
    try {
      setLaunchingBrowser(true);
      if (isElectron) {
        await showWorkBrowser();
      } else {
        await launchBrowser();
      }
      setTimeout(checkBrowserConnection, 1500);
    } catch (err) {
      alert(`Error con el navegador de trabajo: ${err.message}`);
    } finally {
      setLaunchingBrowser(false);
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

  const navItems = [
    { id: 'prospectos', label: 'Prospectos', icon: Users, badge: null },
    { id: 'listas', label: 'Listas de Leads', icon: ListFilter, badge: listsCount },
    { id: 'secuencias', label: 'Secuencias', icon: GitFork, badge: sequencesCount },
    { 
      id: 'logs', 
      label: 'Logs y Actividad', 
      icon: Terminal, 
      badge: isExtracting ? '● VIVO' : logsCount, 
      isPulse: isExtracting 
    },
  ];

  return (
    <header className="sticky top-0 z-40 border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between gap-4">
        {/* Brand / Logo */}
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-sky-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-sky-500/20 text-white font-bold text-sm tracking-tighter">
            DL
          </div>
          <div className="hidden sm:block">
            <div className="flex items-center gap-1.5 leading-none">
              <span className="font-semibold text-sm tracking-tight text-zinc-100">Dripify</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded font-mono font-medium bg-zinc-800 text-sky-400 border border-zinc-700/60">
                Local
              </span>
            </div>
            <p className="text-[11px] text-zinc-400 leading-none mt-1">Suite de Prospección B2B Multicanal</p>
          </div>
        </div>

        {/* Navigation Tabs */}
        <nav className="flex items-center gap-1 bg-zinc-900/70 p-1 rounded-xl border border-zinc-800">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`relative flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-150 cursor-pointer ${
                  isActive
                    ? 'bg-zinc-800 text-white shadow-sm shadow-black/40 border border-zinc-700/60'
                    : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40'
                }`}
              >
                <Icon className={`w-3.5 h-3.5 ${isActive ? 'text-sky-400' : 'text-zinc-400'}`} />
                <span>{item.label}</span>
                {item.badge !== null && (
                  <span
                    className={`text-[10px] px-1.5 py-0.2 rounded-full font-mono transition-colors ${
                      item.isPulse
                        ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 animate-pulse'
                        : isActive
                        ? 'bg-zinc-700 text-zinc-200'
                        : 'bg-zinc-800 text-zinc-400'
                    }`}
                  >
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        {/* Global Controls & Status */}
        <div className="flex items-center gap-2.5">
          {/* Browser Indicator */}
          <button
            onClick={checkBrowserConnection}
            title={browserMotor}
            className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800 text-xs text-zinc-300 hover:border-zinc-700 transition cursor-pointer"
          >
            <span
              className={`w-2 h-2 rounded-full ${
                browserOnline ? 'bg-emerald-400 shadow-sm shadow-emerald-400' : 'bg-rose-500'
              } ${checkingBrowser ? 'animate-ping' : ''}`}
            />
            <span className="hidden md:inline text-[11px] font-mono">
              {browserOnline ? (isElectron ? 'Chromium Aislado' : 'BrowserOS Activo') : 'Navegador Off'}
            </span>
          </button>

          {/* Login de LinkedIn / Estado de Conexión en Electron */}
          {isElectron && (
            !linkedinSessionActive ? (
              <button
                onClick={handleLoginLinkedin}
                disabled={launchingBrowser}
                title="Abre la ventana de trabajo en Chromium para ingresar tus credenciales de LinkedIn"
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 text-xs font-semibold shadow-sm shadow-amber-500/20 transition cursor-pointer animate-pulse"
              >
                <Key className="w-3.5 h-3.5 text-amber-400" />
                <span>🔑 Iniciar Sesión en LinkedIn</span>
              </button>
            ) : (
              <div 
                title="Sesión de LinkedIn autenticada y persistente en Chromium"
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-xs text-emerald-300"
              >
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                <span className="hidden md:inline font-mono text-[11px]">LinkedIn Conectado</span>
              </div>
            )
          )}

          {/* Launch / View Work Browser Button */}
          <button
            onClick={handleViewBrowser}
            disabled={launchingBrowser}
            title={isElectron ? 'Ver o traer al frente la ventana de Chromium embebido' : 'Iniciar sesiones de trabajo'}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 hover:border-zinc-700 text-xs text-zinc-200 transition cursor-pointer"
          >
            {isElectron ? (
              <Eye className={`w-3.5 h-3.5 text-sky-400 ${launchingBrowser ? 'animate-spin' : ''}`} />
            ) : (
              <Compass className={`w-3.5 h-3.5 text-sky-400 ${launchingBrowser ? 'animate-spin' : ''}`} />
            )}
            <span className="hidden lg:inline text-[11px]">
              {isElectron ? 'Ver Navegador' : 'Abrir LinkedIn & Zoho'}
            </span>
          </button>

          {/* Campaign Global Toggle */}
          <button
            onClick={handleToggleCampaign}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition cursor-pointer ${
              campaignActive
                ? 'bg-emerald-600/20 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-600/30'
                : 'bg-zinc-900 text-zinc-400 border border-zinc-800 hover:text-zinc-200 hover:bg-zinc-800'
            }`}
          >
            <Power className={`w-3.5 h-3.5 ${campaignActive ? 'text-emerald-400' : 'text-zinc-400'}`} />
            <span className="font-mono text-[11px]">
              {campaignActive ? 'ACTIVA' : 'PAUSADA'}
            </span>
          </button>

          {/* API Docs link */}
          <a
            href="/docs"
            target="_blank"
            rel="noopener noreferrer"
            title="Documentación interactiva Swagger"
            className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60 transition"
          >
            <FileText className="w-4 h-4" />
          </a>
        </div>
      </div>
    </header>
  );
}
