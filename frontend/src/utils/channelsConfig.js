// Gestión de canales integrados por el usuario (flujo progresivo sin saturar la interfaz)
const CHANNELS_STORAGE_KEY = 'nexusreach_enabled_channels';
const ONBOARDING_DISMISSED_KEY = 'nexusreach_onboarding_dismissed';
export const CHANNELS_CHANGED_EVENT = 'nexusreach-channels-changed';

const DEFAULT_CHANNELS = {
  linkedin: true,
  whatsapp: false,
  email: false,
  zoho: false,
};

export function getEnabledChannels() {
  try {
    const raw = localStorage.getItem(CHANNELS_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return { ...DEFAULT_CHANNELS, ...parsed, linkedin: true };
    }
  } catch (e) {
    console.error('Error leyendo canales activos:', e);
  }
  return { ...DEFAULT_CHANNELS };
}

export function setEnabledChannels(nextChannels) {
  const normalized = { ...DEFAULT_CHANNELS, ...nextChannels, linkedin: true };
  try {
    localStorage.setItem(CHANNELS_STORAGE_KEY, JSON.stringify(normalized));
  } catch (e) {
    console.error('Error guardando canales activos:', e);
  }
  window.dispatchEvent(new CustomEvent(CHANNELS_CHANGED_EVENT, { detail: normalized }));
  return normalized;
}

export function toggleEnabledChannel(channelKey) {
  if (channelKey === 'linkedin') return getEnabledChannels();
  const current = getEnabledChannels();
  return setEnabledChannels({ ...current, [channelKey]: !current[channelKey] });
}

export function isOnboardingDismissed() {
  try {
    return localStorage.getItem(ONBOARDING_DISMISSED_KEY) === 'true';
  } catch {
    return false;
  }
}

export function setOnboardingDismissed(value = true) {
  try {
    localStorage.setItem(ONBOARDING_DISMISSED_KEY, value ? 'true' : 'false');
  } catch {}
}

