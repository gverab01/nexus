# NexusReach Pro — Guía de Distribución, Firma de Código y Auto-Actualización (Workstream 5.11)

Esta guía detalla los procesos de empaquetado, firma digital, verificación de integridad y auto-actualización para el cliente desktop de NexusReach Pro en Windows y macOS.

---

## 1. Arquitectura de Distribución Local-First

NexusReach Pro utiliza una arquitectura **Local-First**:
- El cliente Electron aloja tres particiones completamente aisladas (`persist:linkedin`, `persist:whatsapp`, `persist:zoho`).
- La ejecución de acciones y la resolución de interfaces se realiza directamente en el equipo del usuario a través de su propia red residencial o corporativa, eliminando el riesgo de proxies de centro de datos.
- **Requisito Operativo Ineludible:** Para que las secuencias activas sincronicen o despachen acciones, el computador del usuario debe estar encendido y con la sesión iniciada. Si el equipo se apaga o entra en modo suspensión, la cola de tareas se detiene de forma segura y se reanuda automáticamente al reconectar.

---

## 2. Empaquetado Multiplataforma (`electron-builder`)

La configuración reside en [desktop/electron-builder.yml](file:///c:/Users/gabri/OneDrive/Desktop/Proyectos/Linkedin/desktop/electron-builder.yml).

### Comandos de Compilación:
```bash
cd desktop
npm run dist:win   # Genera instalador NSIS para Windows (x64)
npm run dist:mac   # Genera DMG y ZIP para macOS (Apple Silicon y x64)
```

### Exclusiones Estrictas:
El empaquetador excluye explícitamente:
- Scripts de desarrollo (`scratch/**`).
- Pruebas unitarias (`tests/**`).
- Archivos fuente `.py`, `.sql` o `.bat`.
- Dependencias de desarrollo y definiciones `.d.ts`.

---

## 3. Firma de Código y Notarización

### A. Windows (Microsoft Authenticode)
- **Certificado:** Certificado EV (Extended Validation) de firma de código en hardware USB token o Azure Key Vault.
- **Propósito:** Prevenir las alertas de "Windows Defender SmartScreen: Editor desconocido".
- **Sellado de Tiempo:** Servidor RFC 3161 (`http://timestamp.digicert.com`).

### B. macOS (Apple Developer Notarization)
- **Hardened Runtime:** Habilitado obligatoriamente (`hardenedRuntime: true`).
- **Certificado:** `Developer ID Application`.
- **Notarización:** Integrada con `notarytool` mediante variables de entorno:
  - `APPLE_ID`
  - `APPLE_APP_SPECIFIC_PASSWORD`
  - `APPLE_TEAM_ID`

---

## 4. Política de Versión Mínima y Auto-Actualización

### Verificación de Versión en el Servidor (`min_client_version`)
1. El backend mantiene una versión mínima soportada en `observability_service.MIN_CLIENT_VERSION = '1.0.0'`.
2. Durante el registro o handshake de un dispositivo (`POST /api/devices/register`), el cliente reporta su `client_version`.
3. Si la versión es inferior a la mínima permitida, el servidor responde con:
   ```json
   {
       "ok": false,
       "error": "CLIENT_VERSION_DEPRECATED",
       "message": "Su versión de NexusReach Pro está obsoleta. Por favor actualice a la versión 1.3.0.",
       "download_url": "https://releases.nexusreach.io/desktop/"
   }
   ```
4. Ningún comando de automatización es despachado a clientes con versiones obsoletas o no soportadas.

### Rotación de Claves Criptográficas Ed25519
- La clave pública del servidor (`server_public_key.pem`) está embebida en el cliente Electron para verificar la firma de cada comando antes de su ejecución.
- En caso de rotación de clave del servidor:
  1. El cliente admite una lista de claves públicas autorizadas (clave activa + clave en rotación).
  2. La clave secundaria se incorpora en la versión $N-1$ antes de descontinuar la clave principal en la versión $N$.
