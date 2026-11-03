# Auditoría de Huella Digital y Señales de Navegador Embebido
**NexusReach Pro - Workstream 5.5 [P1] Antiban y Huella Digital**

---

## 1. Objetivo y Principio Rector
Minimizar y neutralizar toda diferencia detectable entre el motor Chromium de Electron y un navegador Google Chrome de escritorio convencional, eliminando banderas de automatización y garantizando coherencia en telemetría de usuario.

---

## 2. Matriz de Auditoría de Huella (Chromium vs Chrome Convencional)

| Señal / Propiedad | Valor por Defecto en Electron | Configuración NexusReach Pro | Estado de Neutralización |
| :--- | :--- | :--- | :---: |
| **`navigator.webdriver`** | `true` en testing / flag blink | Definido como `undefined` vía stealth injection | **NEUTRALIZADO** |
| **Blink Automation Flags** | `AutomationControlled` activo | Desactivado vía `--disable-blink-features=AutomationControlled` | **NEUTRALIZADO** |
| **User Agent** | Incluye `Electron/X.Y.Z` | Sobrescrito a Chrome 130 Win64 limpio sin token de Electron | **NEUTRALIZADO** |
| **Objeto `window.chrome`** | Incompleto o ausente | Emulado con `runtime`, `loadTimes`, `csi`, `app` | **NEUTRALIZADO** |
| **`navigator.languages`** | Según sistema base | Forzado a lista regional: `['es-CL', 'es', 'en-US', 'en']` | **NEUTRALIZADO** |
| **`navigator.plugins`** | Lista vacía (0 plugins) | Emulado con Chrome PDF Viewer y Chromium PDF Viewer | **NEUTRALIZADO** |
| **Permissions API** | Query devuelve error o mock | Normalizado con delegación a `Notification.permission` | **NEUTRALIZADO** |
| **Zona Horaria y Locale** | Consistente con OS | Heredado del sistema host del usuario (`America/Santiago`) | **CONSISTENTE** |

---

## 3. Protocolo de Re-Auditoría
Tras cada actualización de versión de Node.js o Electron:
1. Inspeccionar `navigator.webdriver` mediante `executeJavaScript`.
2. Verificar que `window.chrome.runtime` responda sin excepciones.
3. Evaluar la prueba de detección en páginas de diagnóstico (ej. CreepJS / Bot.SannySoft).
