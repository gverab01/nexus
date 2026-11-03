# NexusReach Pro — Directrices de ingeniería para agentes

> Documento operativo para los agentes que construyen la plataforma. Versión 1.3 — octubre 2026. Todas las decisiones de producto están tomadas (sección 8).
> Léelo completo antes de escribir código. Donde diga **DEBE** o **NUNCA**, es obligatorio. Donde diga **DECISIÓN PENDIENTE**, no inventes la respuesta: detente y pregunta al responsable humano.

### Cambios respecto a la v1.2

- **Decisiones cerradas** (sección 8, registro completo): Zoho en `zoho.com`, hosting en AWS (São Paulo), retención de 12 meses, WhatsApp solo con contactos cálidos, proveedores iniciales de correo y búsqueda, cobros con Mercado Pago (Chile) y PayPal (resto del mundo), packs y límites comerciales definitivos para la beta.
- **Cobro (5.9.G):** nueva subsección con los requisitos de integración de Mercado Pago y PayPal.
- **WhatsApp (5.7):** se elimina la opción de envío en frío; no se implementa en esta fase.
- Quedan solo **tres pendientes que no dependen del agente** (sección 8.2). Ninguno bloquea M0–M3.

---

## 0. Cómo debes trabajar con este documento

1. Trabaja por **workstreams** (sección 5), en el orden de prioridad indicado (P0 → P1 → P2). No avances a un P1 si un P0 relacionado está incompleto.
2. Cada workstream tiene **criterios de aceptación**. Una tarea no está terminada hasta cumplirlos y tener pruebas automatizadas.
3. Entrega cambios pequeños y revisables (un PR por tarea coherente), con descripción de qué cambia, por qué y cómo se prueba.
4. No asumas cifras de "seguridad" frente a LinkedIn o WhatsApp como garantizadas. Los valores numéricos de límites son **puntos de partida configurables a calibrar con datos**, no verdades.
5. Si algo de este documento contradice el código actual, **este documento manda**, salvo que detectes un riesgo no previsto. En ese caso, repórtalo antes de actuar.
6. No hagas afirmaciones de marketing en código, textos de UI o documentación como "indetectable", "100 % seguro" o "cero riesgo".
7. **No construyas nada listado en la sección 1.3 (fuera de alcance)**, aunque parezca una mejora natural.
8. **Las decisiones de la sección 8.1 están tomadas.** No las reabras ni las reemplaces por tu criterio. Si encuentras un motivo técnico para cambiar una, repórtalo al responsable humano y espera su respuesta.

### 0.1 Fase 0 obligatoria: auditoría del código existente

La plataforma ya está en gran parte construida. Este documento describe el estado objetivo, no un proyecto desde cero. Antes de escribir código de producción:

1. **Recorre el repositorio** y produce `docs/audit_gap_analysis.md` con una tabla por workstream (5.1 a 5.11): estado (`HECHO` / `PARCIAL` / `FALTA`), archivos y módulos relevantes, riesgos detectados, dependencias y esfuerzo estimado.
2. **No reescribas lo que ya cumple los criterios de aceptación.** Reutiliza y refactoriza lo mínimo necesario. Si un componente existente cumple el requisito de otra manera, documenta la diferencia y no lo cambies sin motivo.
3. **Reporta hallazgos que contradigan este documento** (por ejemplo: secretos en el repositorio, claves de firma en el servidor de aplicación, datos de leads persistidos en el cliente, código que depende de Zoho para decidir flujos).
4. **Compatibilidad con producción:** toda migración de datos DEBE ser reversible y verificable; los cambios de comportamiento van detrás de feature flags cuando haya usuarios activos; respeta la política de versión mínima de cliente (5.8, 5.11) para no dejar clientes instalados sin servicio sin aviso.
5. Entrega el análisis al responsable humano y continúa con el orden de este documento salvo que indique otro.

---

## 1. Contexto y objetivo del producto

NexusReach Pro es una plataforma de prospección B2B multicanal (LinkedIn, WhatsApp Web, correo) con enriquecimiento de datos.

### 1.1 Modelo de negocio decidido

- **Motor, datos y lógica de negocio: 100 % en la nube** (backend, base de datos, secuencias, dispatcher, safety engine, enriquecimiento, metering).
- **Cliente local (Electron): cliente delgado y sin estado.** Solo recibe instrucciones del backend y las ejecuta en un navegador embebido con una partición persistente (la sesión real del usuario en LinkedIn y WhatsApp Web). **No almacena base de datos ni datos de leads en disco.**
- **Precio base: 15 USD/mes por cuenta de LinkedIn conectada.** Una sola oferta con todas las funcionalidades. El crecimiento de ingreso por cliente viene de más cuentas, más capacidad de leads y consumo de créditos de correo (ver 5.9), no de planes con funciones bloqueadas. El precio puede cambiar en el futuro con aviso previo.
- **Comparables de referencia** (precios públicos revisados en octubre 2026 en fuentes de terceros; **verificar en las páginas oficiales antes de usarlos en cualquier texto externo**):
  - Linked Helper (ejecución local, por cuenta): 15 USD/mes el plan Standard y 45 USD/mes el Pro en pago mensual; con facturación anual baja a ~8,25 y ~24,75 USD.
  - Waalaxy (extensión de navegador, por licencia): ~39 EUR/mes el plan de entrada en pago mensual (~19 EUR con facturación anual), con topes de invitaciones por mes y créditos de búsqueda de correo.
  - Dripify (nube, por usuario): 59 / 79 / 99 USD/mes en pago mensual (39 / 59 / 79 con facturación anual).
- **Posicionamiento:** a 15 USD NexusReach iguala el precio de entrada de Linked Helper y queda muy por debajo de las herramientas en la nube. Por eso la ventaja **no es ser barato**, sino: **motor en la nube + WhatsApp + español/LatAm + enriquecimiento de correo con fuentes públicas, todo integrado.**
- **Riesgo económico a vigilar:** con todas las funciones incluidas a tarifa plana, el costo variable (verificación de correos) es lo que puede erosionar el margen. Por eso se mide y se limita mediante créditos (5.9).

### 1.2 Mercado inicial

Usuarios hispanohablantes de LatAm (inicio: Chile) que hacen prospección B2B y usan WhatsApp. Un nicho inicial relevante es el de colegios en Chile, donde buena parte de los datos proviene de **fuentes públicas** (sitios web institucionales), no de LinkedIn. Diseña el enriquecimiento de modo que las fuentes públicas sean ciudadanas de primera clase y LinkedIn sea solo una fuente más.

### 1.3 Fuera de alcance en esta fase (NO implementar)

1. **Integración con Zoho CRM por API** (OAuth, sincronización de leads, `Lead_Status`, notas) y con cualquier otro CRM. **Aclaración:** la automatización actual de la interfaz de Zoho NO está fuera de alcance; se mantiene como puente transitorio bajo las reglas de 5.2.
2. **WhatsApp Business Platform / API oficial de Meta** (plantillas, opt-in oficial). El módulo de WhatsApp Web (5.7) se mantiene como está definido.
3. **Planes o niveles de precio visibles.** La oferta es única; la escala se resuelve con capacidad y créditos (5.9).
4. Abstracciones o capas "para el futuro" creadas solo en previsión de lo anterior. Si encuentras código existente que ya implementa parte de estos puntos, **no lo extiendas**; repórtalo en la Fase 0 (el tratamiento del código de Zoho está en 5.2).

La reevaluación de Zoho API y de la API oficial de WhatsApp se hará después del hito M5, con datos reales de clientes.

---

## 2. Principios no negociables

1. **Seguridad del canal de comandos primero.** El cliente ejecuta instrucciones en un navegador con sesiones reales del usuario. Un backend comprometido no debe poder tomar control de las cuentas de los clientes.
2. **Aislamiento total por cliente (tenant).** NUNCA construyas una base de datos compartida o caché de perfiles de LinkedIn entre clientes. Cada dato pertenece a un tenant y solo es visible para él.
3. **Minimización de datos y cumplimiento.** Guarda solo lo necesario, con origen y finalidad registrados, con retención definida y borrado efectivo.
4. **El servidor es la autoridad.** Límites, horarios, curvas de calentamiento y kill-switch se aplican **en el backend**. El cliente no decide cuánto ni cuándo; solo ejecuta lo autorizado.
5. **Honestidad técnica.** Los mecanismos antiban reducen riesgo; no lo eliminan. El sistema debe asumir que las cuentas pueden ser restringidas y degradar de forma segura.
6. **Cada integración usa su vía oficial cuando existe** (correo: API del proveedor del usuario con OAuth). La automatización de la interfaz de Zoho solo se admite como puente transitorio bajo las reglas de 5.2 y NUNCA se extiende a otros CRM. Las integraciones de CRM por API y la API oficial de WhatsApp están fuera de alcance por ahora (1.3).
7. **La seguridad no se vende.** Ningún pago, pack o suscripción aumenta los límites de seguridad de una cuenta (5.5, 5.9).

---

## 3. Arquitectura objetivo

```
┌──────────────────────────── NUBE ─────────────────────────────┐
│  API (FastAPI) · Auth · Billing/Metering · Tenancy             │
│  Sequence Engine · Task Dispatcher · Safety Engine (autoridad) │
│  Enrichment (OSINT + verificadores pagos) · Export CSV         │
│  PostgreSQL multi-tenant · Cola/Scheduler · Observabilidad     │
│  Servicio de firma de comandos (clave privada en KMS/HSM)      │
└───────────────▲───────────────────────────────┬───────────────┘
                │ resultados firmados por device │ comandos firmados
                │ (HTTPS/WebSocket, TLS)         ▼
┌───────────────┴─────────── EQUIPO DEL USUARIO ────────────────┐
│  Electron (cliente delgado, sin BD)                            │
│  Verificador de firma · Validador de esquema · Ejecutor        │
│  Partición Chromium persistente: LinkedIn + WhatsApp Web       │
│  Partición aislada y transitoria: Zoho Bridge (5.2)            │
└────────────────────────────────────────────────────────────────┘
```

Cambios clave respecto al estado actual:

- **SQLite → PostgreSQL** multi-tenant (ver 5.3).
- **Zoho no se integra por API por ahora, pero sigue operando.** La automatización de su interfaz se mantiene como **Zoho Bridge**: un módulo transitorio, en una partición de navegador aislada, que ejecuta solo comandos firmados de una lista cerrada (ver 5.1 y 5.2). El cliente local toca LinkedIn, WhatsApp Web y, solo si el tenant lo activa, Zoho. La deduplicación, la bitácora de interacciones y la exportación CSV pasan a ser funciones internas de la plataforma, lo que reduce la dependencia de Zoho.
- **Sin estado local.** Los datos de leads viven únicamente en memoria del cliente durante la ejecución de una tarea y se descartan. En disco solo permanece la partición de Chromium (cookies/sesión) y la configuración mínima del dispositivo.

---

## 4. Mapa de prioridades

| Prioridad | Workstream |
|---|---|
| **P0** | 5.1 Canal de comandos seguro · 5.2 Zoho Bridge transitorio y funciones internas · 5.3 Multi-tenancy, auth y migración de datos · 5.4 Datos personales y cumplimiento |
| **P1** | 5.5 Antiban y huella · 5.6 Resolver de correos · 5.7 WhatsApp · 5.8 Resiliencia ante cambios de interfaz · 5.9 Facturación, límites comerciales y metering |
| **P2** | 5.10 Observabilidad y soporte · 5.11 Distribución, firma y auto-actualización |

---

## 5. Workstreams

### 5.1 [P0] Canal de comandos seguro (backend → cliente)

**Problema:** el cliente obedece instrucciones del backend dentro de un navegador con sesiones reales. Si el backend se compromete, un atacante controlaría las cuentas de todos los clientes (enviar mensajes, leer chats de WhatsApp).

**Requisitos (DEBE):**

1. **Emparejamiento de dispositivo.** Al instalar, el cliente genera un par de claves (Ed25519) y registra la clave pública asociada a un usuario autenticado. Los dispositivos pueden revocarse desde el panel.
2. **Comandos firmados.** Cada comando lo firma un servicio de firma aislado (clave privada en KMS/HSM, nunca en el servidor de aplicación general). El cliente lleva **fijada (pinned)** la clave pública de verificación, con mecanismo de rotación.
3. **Anti-replay.** Cada comando incluye `command_id`, `nonce`, `issued_at`, `expires_at` (TTL corto, p. ej. ≤ 120 s) y `device_id`. El cliente rechaza comandos caducados o repetidos.
4. **Lista cerrada de acciones.** El cliente solo ejecuta acciones de una **enumeración fija** con parámetros validados por esquema. NUNCA ejecuta JavaScript, selectores arbitrarios para navegar a URLs libres, ni código recibido del servidor.
5. **Allowlist de dominios** en el cliente: `linkedin.com` y `web.whatsapp.com` (y subdominios necesarios) y, **solo si el tenant activa el Zoho Bridge**, el dominio de Zoho CRM del centro de datos de EE. UU. (`zoho.com`, es decir, `crm.zoho.com` y el inicio de sesión de Zoho). El dominio se guarda en la configuración del tenant, nunca llega como parámetro libre de un comando. En la Fase 0, determina la lista **mínima y exacta** de hosts que Zoho necesita (incluidos los de recursos estáticos) observando el tráfico real, y repórtala para aprobación antes de activarla. Todo lo demás se rechaza.
6. **Particiones de navegador separadas** por servicio (LinkedIn, WhatsApp, Zoho). Una sesión no puede leer cookies ni almacenamiento de otra.
7. **Resultados autenticados.** El cliente firma/autentica cada reporte de resultado con su clave de dispositivo.
8. **Kill-switch global y por tenant/dispositivo**, aplicable de inmediato desde el servidor.

**Esquema de comando (referencia):**

```json
{
  "command_id": "uuid",
  "tenant_id": "uuid",
  "device_id": "uuid",
  "action": "LI_VISIT_PROFILE | LI_SEND_INVITE | LI_SEND_MESSAGE | LI_SYNC_CONNECTIONS | LI_READ_CONTACT_INFO | WA_SEND_MESSAGE | WA_CHECK_NUMBER | ZOHO_FIND_LEAD | ZOHO_UPSERT_LEAD | ZOHO_SET_STATUS | ZOHO_ADD_NOTE | PAUSE | RESUME",
  "params": { "...": "validados contra el esquema de la acción" },
  "nonce": "string",
  "issued_at": "ISO-8601",
  "expires_at": "ISO-8601",
  "signature": "base64(ed25519)"
}
```

**Criterios de aceptación:**
- Un comando con firma inválida, caducado, repetido, con acción fuera de la enumeración o con dominio fuera de la allowlist es rechazado y registrado.
- Un comando `ZOHO_*` se rechaza si el tenant no tiene el Zoho Bridge activado.
- Pruebas automatizadas para cada caso anterior.
- Revocar un dispositivo impide que acepte nuevos comandos en menos de 60 s.
- La clave privada de firma no existe en el código ni en variables del servidor de aplicación.

---

### 5.2 [P0] Zoho Bridge transitorio y funciones internas

**Decisión:** la integración de Zoho por API sigue **fuera de alcance** (1.3). Hoy la aplicación solo puede operar automatizando la interfaz de Zoho, así que **no se elimina**: se mantiene como un **puente transitorio** con las mismas garantías de seguridad que el resto del cliente. Cuando exista la API, el puente se retira.

**Problema:** `zoho_browser_service.py` hoy decide y ejecuta dentro del cliente, con selectores arbitrarios y sin pasar por el canal firmado. Eso rompe el principio de que el servidor es la autoridad y deja una puerta abierta si el backend se compromete.

**Requisitos (DEBE):**
1. **Gobernado desde la nube.** La lógica de decisión (qué lead buscar, qué estado poner, qué nota agregar) vive en el backend. El cliente solo ejecuta cuatro acciones de lista cerrada, enviadas como comandos firmados (5.1): `ZOHO_FIND_LEAD`, `ZOHO_UPSERT_LEAD`, `ZOHO_SET_STATUS`, `ZOHO_ADD_NOTE`, con parámetros validados por esquema.
2. **Aislamiento.** Partición de navegador propia para Zoho, separada de LinkedIn y WhatsApp. Dominio permitido: solo el del centro de datos de Zoho del tenant (valor inicial: `zoho.com`; 5.1, punto 5). El módulo se activa por tenant con feature flag.
3. **Mínima exposición de datos.** NUNCA crear una acción que lea o exporte registros en masa. `ZOHO_FIND_LEAD` devuelve solo lo necesario para decidir (existe o no, identificador, propietario, estado), sin el registro completo. El resultado va firmado por el dispositivo.
4. **Cadencia controlada.** Ritmo con retardos variables y tope por hora/día definidos en el servidor. Si el módulo detecta cierre de sesión, CAPTCHA, cambio de pantalla o error repetido, se pausa y no reintenta en bucle (6, punto 9).
5. **Selectores como datos.** Los selectores de Zoho siguen el mismo esquema versionado y firmado de 5.8, con canarios contra una cuenta de prueba de Zoho.
6. **Deduplicación interna.** Conserva el comportamiento de evitar colisión de representantes, pero apoyado primero en la base de datos propia: un lead no entra a una secuencia si ya está activo o contactado por otra cuenta del mismo tenant o si está en supresión. La consulta a Zoho (`ZOHO_FIND_LEAD`) queda como verificación adicional, no como única fuente.
7. **Bitácora interna** (`lead_activity`): cada acción relevante queda registrada por lead en la base propia y es visible en la interfaz. Las notas en Zoho (`ZOHO_ADD_NOTE`) son una copia, no la fuente de verdad.
8. **Exportación CSV** de leads con estado y bitácora, con formato estable y documentado, como alternativa manual y como paso previo a la migración a la API.
9. El estado del lead (`status`) NO depende de valores propios de Zoho. Los identificadores o estados de Zoho se guardan en campos nullable (`crm_external_id`) sin acoplar la lógica.
10. Las credenciales de Zoho NUNCA se almacenan: la sesión vive solo en la partición local. Si existen contraseñas, tokens o sesiones de Zoho en el código o la configuración, repórtalos en la Fase 0 para revocarlos.
11. **Preparar la salida:** documenta qué acciones `ZOHO_*` equivalen a qué llamadas de la API de Zoho, para que la migración posterior sea un reemplazo del ejecutor y no un rediseño. No construyas la integración por API ni capas abstractas especulativas (1.3).

**Criterios de aceptación:**
- Ninguna operación de Zoho se ejecuta sin un comando firmado válido; pruebas de rechazo para firma inválida, caducidad, repetición y dominio fuera de la allowlist.
- El cliente no puede navegar a un dominio de Zoho distinto al configurado para el tenant.
- Con el flag apagado no se puede emitir ninguna acción `ZOHO_*`.
- Un fallo repetido del módulo pausa solo la acción afectada y notifica, sin reintentos en bucle.
- Dos cuentas del mismo tenant no pueden activar al mismo lead; un lead en supresión nunca se activa.
- La exportación CSV devuelve solo los leads del tenant, con estado y bitácora.
- No quedan secretos de Zoho en el repositorio ni en los logs.

---

### 5.3 [P0] Multi-tenancy, autenticación y migración a PostgreSQL

**Requisitos:**
1. Migrar de SQLite a **PostgreSQL**. Toda tabla con datos de cliente lleva `tenant_id`.
2. **Aislamiento forzado** a nivel de base de datos (Row-Level Security) además del filtrado en la aplicación. Una consulta sin contexto de tenant no devuelve filas.
3. Autenticación de usuarios (email + contraseña con hash fuerte y/o OAuth), sesiones seguras, recuperación de cuenta. Roles mínimos: `owner`, `member`.
4. Entidades de referencia (ajusta nombres, mantén la separación):
   - `tenants`, `users`, `devices` (clave pública, estado, última conexión, versión de cliente)
   - `linkedin_accounts` (cuenta conectada; **unidad facturable**), `whatsapp_accounts`
   - `leads` (con `source`, `source_url`, `collected_at`, `legal_basis`, `status`, `crm_external_id` nullable), `lead_contacts`, `lead_activity`, `email_candidates` (candidato, evidencia de origen, resultado y costo de verificación)
   - `sequences`, `sequence_steps`, `lead_sequence_state`
   - `commands`, `command_results`, `system_logs`
   - `suppression_list`, `consent_records`
   - `subscriptions`, `entitlements`, `usage_counters`, `usage_events`, `credit_ledger`
5. Migración de datos existentes con script idempotente y verificación de conteos.
6. Cifrado en tránsito (TLS) y en reposo; cifrado a nivel de campo para correos y teléfonos.

**Criterios de aceptación:** prueba automatizada que demuestra que un tenant A no puede leer ni inferir datos del tenant B por ninguna ruta de la API; rollback documentado.

---

### 5.4 [P0] Datos personales y cumplimiento (Chile)

> Contexto (verificar vigente antes de implementar): la Ley 21.719 de Protección de Datos Personales de Chile estaba fijada para entrar en vigor el **1 de diciembre de 2026**; existe un proyecto del Gobierno para postergarla al 1 de diciembre de 2027. Mientras no se apruebe, tómala como fecha vigente. Da derechos de acceso, rectificación, supresión, oposición (incluido marketing directo y perfilamiento comercial), con sanciones relevantes. Esto NO es asesoría legal: validar con abogado (ver 8.2) la calificación de roles (cliente = responsable, NexusReach = encargado) y los textos legales.

**Requisitos de diseño (DEBE):**
1. **Registro de origen y base de licitud** por lead (`source`, `source_url`, `collected_at`, `legal_basis`).
2. **Minimización:** no guardar datos que no se usan en la secuencia. Los teléfonos y correos obtenidos de contactos de 1.er grado se tratan como datos sensibles de negocio (cifrados, con acceso restringido).
3. **Lista de supresión (opt-out):** por tenant, con comparación mediante hash. Todo lead en supresión queda excluido de cualquier canal. Debe respetarse antes de cada envío.
4. **Mecanismo de baja** en cada correo saliente y manejo de respuestas "no me contacten" (detección básica y marcación manual).
5. **Retención configurable:** purga de leads inactivos tras **12 meses sin actividad**, configurable por tenant, y **borrado completo del tenant en ≤ 30 días** tras cancelar la cuenta, incluyendo copias de respaldo en su ciclo normal.
6. **Endpoints de ejercicio de derechos:** exportar y eliminar los datos de un lead concreto.
7. **Auditoría:** `system_logs` sin contenido sensible innecesario; accesos a datos personales registrados.
8. **Prohibido:** reutilizar datos de un tenant para enriquecer a otro, vender o agregar datos entre clientes, o construir un índice global de perfiles de LinkedIn.
9. **Hosting:** AWS con PostgreSQL gestionado y KMS, región por defecto **São Paulo (`sa-east-1`)**. Define la infraestructura como código y la región como parámetro. Si algún servicio requerido no está disponible en esa región, repórtalo y propón `us-east-1`; no cambies de región sin aprobación. La revisión legal de la transferencia internacional de datos es un pendiente del responsable humano (8.2).

**Criterios de aceptación:** un lead en supresión nunca recibe comandos; el borrado de tenant elimina datos en todas las tablas (prueba automatizada); exportación de un lead devuelve todos sus datos.

---

### 5.5 [P1] Antiban y huella digital

**Principio:** el servidor decide; el cliente ejecuta. Los valores son configurables y a calibrar.

**Requisitos:**
1. **Motor de límites en el servidor**, por cuenta de LinkedIn:
   - Curva de calentamiento: punto de partida 15 invitaciones/día, escalando por semanas (p. ej. 18 → 22 → 25) **solo si** los indicadores de salud de la cuenta lo permiten.
   - Retardos con distribución estocástica entre acciones (rango inicial 180–360 s) más micro-pausas.
   - Ventanas de horario laboral y días hábiles **en la zona horaria del usuario**.
2. **Variación por usuario** (para evitar una huella común a todos los clientes): semillas de aleatoriedad y parámetros de tiempos distintos por cuenta, orden de acciones no idéntico, jitter en horarios de inicio/fin, variación en perfil de scroll/cursor.
3. **Kill-switch automático por señales de riesgo:** checkpoint, CAPTCHA, verificación por correo/PIN, aviso de límite alcanzado, restricción de cuenta, caída súbita de tasa de aceptación. Al detectarlo: congelar cola de esa cuenta, notificar al usuario y exigir reactivación manual con calentamiento reducido.
4. **Kill-switch global:** si la tasa de incidentes sube de forma anómala entre cuentas, pausar automáticamente nuevas acciones de riesgo y alertar al equipo (posible cambio de detección de LinkedIn o firma comprometida).
5. **Señales del navegador embebido:** auditar y minimizar diferencias detectables entre el Chromium de Electron y un Chrome normal (user agent, propiedades de automatización, consistencia de idioma/zona horaria/resolución). Documentar lo auditado y repetir tras cada actualización de Electron.
6. **Indicadores de salud por cuenta:** tasa de aceptación, invitaciones pendientes, incidentes recientes. Deben alimentar el motor de límites.
7. **Separación estricta entre límites de seguridad y límites comerciales.** Los límites de este workstream los fija únicamente el safety engine según la salud de la cuenta. NUNCA dependen del plan, de packs comprados ni de ningún pago. Los límites comerciales (5.9) son un sistema distinto y se evalúan por separado; ambos deben aprobar una acción antes de emitirla.

**Criterios de aceptación:** ninguna acción llega al cliente sin autorización del safety engine; simulaciones demuestran que dos cuentas distintas generan distribuciones de tiempo distintas; un evento de checkpoint congela la cola en menos de un ciclo de dispatch; prueba automatizada de que comprar un pack no modifica ningún límite de seguridad.

---

### 5.6 [P1] Resolver de correos: OSINT propio + verificadores externos pagos

**Problema del diseño actual:** la verificación SMTP (`RCPT TO`) masiva desde IPs de usuarios o de tus servidores daña la reputación de la IP, muchos proveedores de internet bloquean el puerto 25 saliente, los proveedores grandes responden de forma poco fiable y los dominios *catch-all* generan falsos positivos. El texto "cero riesgo" es incorrecto.

**Decisión:** se elimina la verificación SMTP propia. La resolución de correos pasa a una **cascada que va de lo gratuito a lo pagado**: investigación OSINT propia sobre fuentes públicas y, solo al final, verificación mediante proveedores externos. Los costos de esos proveedores se miden y se cobran mediante créditos (5.9).

**Requisitos (DEBE):**
1. **Sin SMTP propio.** NUNCA conectarse por SMTP a servidores de terceros para verificar buzones, ni desde infraestructura propia ni desde equipos de usuarios. Las consultas DNS (por ejemplo, registros MX) sí están permitidas.
2. **Cascada ordenada por costo:**
   a. Correo publicado en fuentes públicas: sitio institucional (páginas de contacto, equipo, enlaces `mailto`, PDFs) y directorios públicos oficiales. Costo casi nulo.
   b. Dato de contacto de 1.er grado, cuando exista.
   c. Inferencia de patrón de dominio a partir de correos ya hallados de la misma organización. Costo nulo.
   d. Controles gratuitos: sintaxis, existencia del dominio y MX, correos genéricos o desechables.
   e. **Verificación externa pagada solo para los candidatos más probables**, con un **tope de consultas por lead** configurable (punto de partida 3). NUNCA verificar todos los patrones posibles.
3. **Proveedores abstraídos.** Define una interfaz `EmailVerifier` con implementaciones intercambiables. **Proveedores iniciales (decisión tomada):** verificador principal MillionVerifier, alternativo ZeroBounce y búsqueda web Serper. **Antes de M4**, compáralos con una muestra de 200–500 correos reales de los colegios objetivo y entrega un informe con precisión, tasa de `unknown`, costo y latencia. Si el informe recomienda cambiar de proveedor principal, solicita aprobación al responsable humano.
4. **Estados de resultado explícitos:** `valid`, `invalid`, `catch_all`, `risky`, `unknown`, con puntaje de confianza. NUNCA tratar `catch_all`/`risky` como válido sin marcarlo.
5. **Evidencia y origen por candidato** (`email_candidates`): URL o fuente, fecha, método (publicado, patrón inferido, verificado) y resultado. Es parte del registro de origen y base de licitud de 5.4.
6. **Reglas de OSINT:**
   - Solo fuentes públicas y abiertas. Respeta `robots.txt`, limita la tasa por dominio y usa un identificador de cliente claro.
   - NUNCA hacer scraping de LinkedIn desde el servidor: los datos de LinkedIn solo se obtienen mediante el cliente y las acciones autorizadas de 5.1.
   - NUNCA usar bases de datos filtradas, compradas de forma dudosa ni accesos tras inicio de sesión que no pertenezcan al usuario.
   - Un correo hallado públicamente sigue siendo dato personal si identifica a una persona: aplican la supresión, la minimización y la retención de 5.4.
7. **Caché solo por tenant (decisión tomada).** El resultado de un correo o persona NUNCA se comparte entre tenants (principio 2). Tampoco se crea una caché global, ni siquiera de metadatos técnicos de dominio. Cualquier excepción futura requiere revisión legal.
8. **Costo medido.** Cada consulta externa registra en `usage_events` y `credit_ledger` el **costo real en USD**, el proveedor y el número de consultas por lead. Registrar también el costo de búsquedas web y proxies usados por el OSINT.
9. **Cobro por consumo (ver 5.9):** un crédito se consume solo cuando el resultado es utilizable (`valid`, o `catch_all` con confianza sobre el umbral configurado); los fallos no se cobran. Los correos tomados de fuentes públicas sin consulta externa no consumen crédito. La regla se lee de `entitlements`, no se codifica en duro.
10. **Calibración continua:** compara el resultado predicho por el verificador con los rebotes reales del usuario para estimar la precisión efectiva de cada proveedor.
11. **Envío de correos:** hacerlo desde el buzón del usuario mediante la API de su proveedor (Gmail/Microsoft) con OAuth, no desde SMTP propio. Incluir enlace de baja y registrar rebotes en la lista de supresión.
12. Detección del dominio oficial de la organización con control de calidad (evitar dominios equivocados) y confirmación del usuario cuando la confianza sea baja.

**Criterios de aceptación:**
- No existe código que abra conexiones SMTP salientes para verificar buzones; prueba automatizada que lo comprueba.
- La cascada se detiene en el primer paso que entrega un resultado utilizable y respeta el tope de consultas externas por lead.
- Pruebas con dominios catch-all, resultados `unknown` y rebotes; los rebotes alimentan la supresión.
- Cada consulta externa deja registrado su costo real y su proveedor.
- Cambiar de proveedor principal es un cambio de configuración, sin modificar la cascada.

---

### 5.7 [P1] WhatsApp

**Riesgos:** automatizar WhatsApp Web va contra sus términos; el mensaje en frío a números obtenidos de LinkedIn es el patrón con más reportes de spam; el costo de un bloqueo es perder el número del usuario.

**Requisitos:**
1. Mantener el módulo de WhatsApp Web **detrás de un feature flag** por tenant, desactivado por defecto, con aviso claro de riesgo y aceptación explícita del usuario.
2. **Defaults conservadores** (valor inicial: ~15 mensajes/día por número, a calibrar) con retardos largos y variables, solo en horario laboral.
3. **Solo contactos "cálidos"**: leads con conexión aceptada en LinkedIn o interacción previa. **NUNCA implementar el envío en frío en esta fase (decisión tomada):** el dispatcher rechaza cualquier acción `WA_SEND_MESSAGE` a un lead que no sea cálido, y no existe interruptor de activación para evitarlo.
4. Verificación de existencia de WhatsApp (`WA_CHECK_NUMBER`) con tope bajo; resultados cacheados por tenant.
5. Detección de señales de riesgo (avisos de restricción, desconexión forzada) y kill-switch específico del canal.
6. **Fuera de alcance:** la WhatsApp Business Platform oficial (1.3). No la implementes ni crees capas especulativas para ella.
7. Respetar la lista de supresión en este canal.

**Criterios de aceptación:** con el flag apagado no se puede emitir ninguna acción `WA_*`; el dispatcher rechaza todo envío a leads no cálidos y no existe ruta de código que lo permita.

---

### 5.8 [P1] Resiliencia ante cambios de interfaz

**Problema:** todo lo que se hace sobre LinkedIn, WhatsApp Web y el Zoho Bridge depende de selectores del DOM y se rompe cuando cambia la interfaz. Es un costo continuo.

**Requisitos:**
1. **Capa de abstracción de selectores:** una definición de acción → estrategia de localización, con múltiples estrategias de respaldo (texto accesible, atributos estables, estructura).
2. **Los selectores son datos, no código.** Pueden actualizarse remotamente como configuración versionada y **firmada** (misma infraestructura de firma que 5.1). NUNCA enviar código ejecutable.
3. **Pruebas de contrato** periódicas contra cuentas de prueba propias (canarios) que verifiquen cada acción y alerten si fallan.
4. **Degradación segura:** si una acción falla repetidamente, pausar esa acción para todos los tenants, notificar y no reintentar en bucle.
5. Versionado de cliente y política de versión mínima soportada por el servidor.
6. Fallos de selector registrados con contexto suficiente (sin datos personales) para diagnóstico rápido.

**Criterios de aceptación:** un cambio simulado de selector se detecta por el canario, pausa la acción afectada y se corrige publicando una nueva configuración firmada sin liberar un binario.

---

### 5.9 [P1] Facturación, límites comerciales y metering

**Decisión de producto:** una sola oferta de **15 USD/mes por cuenta de LinkedIn conectada**, con todas las funcionalidades. No hay planes visibles ni funciones bloqueadas por nivel. La escala de ingresos viene de tres palancas: más cuentas, más capacidad de leads y consumo de créditos de correo.

#### A. Reglas de diseño de los límites comerciales (DEBE)

1. **Los límites de seguridad (5.5) NUNCA son comerciales.** Ningún pago los modifica. Vender "más invitaciones por día" empuja a los usuarios hacia el riesgo de restricción y contradice los principios 4, 5 y 7. En el mercado, los topes de invitaciones de las herramientas siguen los límites que LinkedIn tolera, no una decisión comercial.
2. **Los límites comerciales solo bloquean nuevas activaciones.** Los leads ya activos continúan sus secuencias, seguimientos y respuestas aunque se haya agotado la cuota. NUNCA cortar una conversación en curso por un límite comercial.
3. **Todo límite es configuración, no código.** Los valores viven en `entitlements` (por suscripción, con valores por defecto globales) y se leen en tiempo de ejecución. Cambiar un límite no requiere desplegar. NUNCA codificar cifras comerciales en duro.
4. **Visibilidad para el usuario:** panel con consumo y límite por ciclo, aviso al 80 % y al 100 %, y motivo explícito en cada rechazo (`LIMIT_LEADS_REACHED`, `LIMIT_CREDITS_REACHED`).
5. **Los límites se evalúan en el servidor**, igual que los de seguridad (principio 4). El cliente no conoce ni aplica cuotas comerciales.

#### B. Límites comerciales iniciales (hipótesis a calibrar, ver D)

| Dimensión | Qué se cuenta | Incluido en los 15 USD | Al agotarse |
|---|---|---|---|
| **Cuenta de LinkedIn** | Unidad de cobro | 1 por suscripción | Cada cuenta adicional es otra suscripción (sin descuento por volumen en el lanzamiento) |
| **Leads activados por ciclo** (límite principal) | Leads distintos que reciben su **primera acción** dentro del ciclo de facturación, en cualquier canal, por cuenta de LinkedIn. No acumulable entre ciclos | **500** | Se bloquean solo nuevas activaciones; se ofrece pack o esperar al nuevo ciclo |
| **Créditos de correo por ciclo** | Un crédito cubre la resolución completa de un lead por OSINT + verificación externa. Se consume solo con **resultado utilizable**; los correos hallados en fuentes públicas sin consulta externa no consumen crédito | **100** | Se detiene solo la resolución con costo externo; el resto del flujo continúa. Se ofrece pack de créditos |
| **Packs adicionales** | Leads: +500 por **5 USD**, válido solo para el ciclo en curso. Créditos: 100 por **6 USD** y 500 por **28 USD**, sin vencimiento | Precios aprobados para la beta | Revisar tras M5 |
| **WhatsApp** | Sin límite comercial; solo límites de seguridad (5.7) | Incluido, tras feature flag | — |
| **Secuencias activas, miembros del equipo** | Topes técnicos anti-abuso (p. ej. 50 secuencias activas), no comerciales | Sin cargo | Rechazo con mensaje claro |

**Por qué estas dimensiones:**
- **Leads activados por ciclo** es la métrica que mejor refleja el valor recibido y es comprensible para el usuario ("500 prospectos nuevos al mes"). Además es independiente de los límites de seguridad. Referencia: LinkedIn limita en la práctica a ~100 invitaciones por semana, con un rango diario seguro de ~15–25 para una cuenta calentada, es decir, ~330–550 leads nuevos al mes por cuenta solo por LinkedIn. Con 500 incluidos, un usuario que prospecta solo por LinkedIn rara vez toca el límite; este se vuelve relevante para quien usa varios canales o fuentes públicas (colegios), que es quien obtiene más valor. Los competidores también limitan por volumen mensual de invitaciones y créditos de correo.
- **Créditos de correo** es el único costo variable material (ver C), por lo que debe medirse y cobrarse por consumo.
- **No se usan** como límite comercial: acciones por día (riesgo, ver A.1), leads almacenados en total (castiga acumular datos y choca con la minimización y la purga de 5.4) ni el número de secuencias (castiga la experimentación).

#### C. Referencia de costos para fijar el precio de packs

Fórmula que el panel interno DEBE poder calcular por cuenta y por pack:

```
precio_pack ≥ (costo_variable_por_unidad × unidades × múltiplo_sobre_costo + comisión_fija) / (1 − comisión_procesador − impuestos_no_recuperables)
```

- **Decisiones tomadas:** múltiplo de 2× sobre el costo real para los créditos y margen de contribución objetivo de 60 % por cuenta. Las cifras del modelo se recalculan con costos medidos tras la beta.
- **Modelo de referencia:** `NexusReach_Modelo_de_Costos.xlsx` calcula el costo por lead, el margen por perfil de cliente, el punto de equilibrio y el precio de los packs. Todos sus valores son supuestos editables; el panel interno debe reemplazarlos por costos reales medidos.
- **Órdenes de magnitud del modelo (hipótesis iniciales, no datos medidos):** con OSINT propio y un verificador de gama media, un lead procesado cuesta del orden de 0,01 a 0,02 USD, y un crédito real, del orden de 0,02 a 0,04 USD. Los finders comerciales con base propia cobran del orden de 0,01 a 0,025 USD por correo encontrado, por lo que el precio de tus créditos debe compararse con esa referencia.
- **Comisión fija por transacción:** a 15 USD, una comisión fija de 0,50 USD por cobro pesa más de 3 puntos porcentuales del precio. Evalúa el cobro anual y packs de tamaño mínimo para no regalar el margen.
- El costo marginal de infraestructura por lead y el tiempo de soporte por cuenta deben **medirse** durante la beta; no los supongas.

#### D. Cómo descubrir y calibrar los límites (DEBE implementarse la medición)

1. **Instrumenta desde el hito M2**, antes de cobrar, para tener datos reales en M5. En `usage_counters`/`usage_events`, por cuenta y por ciclo, registra como mínimo: leads activados (total y por canal), acciones ejecutadas por tipo, créditos consumidos, consultas externas de verificación y su costo real, incidentes de seguridad, y si la cuenta alcanzó algún límite.
2. **Panel interno de calibración:** distribución (percentiles p50, p75, p90, p99) de leads activados y créditos por cuenta y por ciclo, % de cuentas que alcanzan cada límite, conversión a packs, churn posterior a alcanzar un límite y margen estimado por cuenta.
3. **Regla heurística para fijar el límite incluido** (punto de partida, a validar por el responsable humano): ubicarlo cerca del percentil 75–85 de uso de cuentas pagas y saludables, de modo que aproximadamente 15–25 % lo alcance. Si más de ~40 % lo alcanza en el primer ciclo, el límite es demasiado bajo; si menos de ~5 % lo alcanza, es demasiado holgado o la dimensión no sirve para escalar.
4. **Verificación de seguridad:** confirmar que subir un límite comercial no correlaciona con más incidentes de cuenta. Si lo hace, el problema está en 5.5, no en el precio.
5. Revisar los valores en cada trimestre y tras cambios de proveedor de verificación.

#### E. Palancas de escala futuras (NO implementar ahora)

Documentadas solo para que el modelo de datos de `entitlements` no las bloquee: sincronización con CRM (Zoho) como funcionalidad de pago cuando se retome, panel de equipo con reportes y supresión compartida, descuentos por volumen de cuentas, packs grandes de créditos, soporte prioritario. Se evalúan después de M5.

#### F. Salvaguardas generales

1. **Unidad facturable: cuenta de LinkedIn conectada**, no usuario.
2. **Límites de uso razonable** y cláusula de uso aceptable documentados en los términos; los de seguridad son coherentes con 5.5.
3. **Ledger de créditos** (`credit_ledger`) con costo real por evento, para calcular margen.
4. **Plan anual** con **2 meses gratis** (equivale a ~17 % de descuento, es decir, 150 USD por año). Mejora caja, reduce abandono y diluye la comisión fija por transacción.
5. **Precio de lanzamiento** con campo `price_lock_until` por suscripción: **6 a 12 meses** para los suscriptores de la beta. NUNCA prometer "todas las funciones futuras al mismo precio de por vida" en textos legales ni de marketing; los términos deben permitir cambiar el precio con aviso previo.
6. **Controles de abuso:** suspender cuentas con patrones de spam o con alta tasa de incidentes.
7. **Procesadores de pago (decisión tomada):** Mercado Pago para clientes con país de facturación Chile y PayPal para el resto del mundo. Ver 5.9.G.
8. **Prueba gratuita:** 14 días, sin tarjeta y con cuota reducida (valores iniciales configurables: 100 leads y 20 créditos). Al terminar, el tenant sin suscripción activa no recibe comandos.

#### G. Cobro con Mercado Pago y PayPal (DEBE)

1. **Interfaz `PaymentProvider`** con dos implementaciones (`MercadoPago`, `PayPal`). La lógica de suscripciones, `entitlements` y `credit_ledger` NO depende de un procesador concreto.
2. **Selección por país de facturación** declarado al registrarse: Chile → Mercado Pago; resto del mundo → PayPal. Un tenant tiene un solo procesador activo por suscripción.
3. **Suscripciones recurrentes** mensuales y anuales (2 meses gratis) mediante las funciones de suscripción de cada procesador, con una máquina de estados propia (`trialing`, `active`, `past_due`, `canceled`) sincronizada con el estado reportado por el procesador. Define un período de gracia configurable antes de bloquear comandos.
4. **Webhooks seguros:** verificar la autenticidad de cada notificación con el mecanismo oficial de cada procesador, procesarlas de forma **idempotente** y registrar el evento. NUNCA activar una suscripción solo por un parámetro de redirección del navegador: confirma siempre con el procesador o con el webhook verificado.
5. **Compras de packs** (créditos y leads) como cobros únicos asociados al tenant, con acreditación en `credit_ledger` solo tras confirmación del pago.
6. **Sin datos de tarjeta propios.** Usa los flujos de pago alojados por el procesador. NUNCA almacenar números de tarjeta ni códigos de seguridad.
7. **Reembolsos y contracargos:** registrar el evento, revertir créditos no consumidos y marcar la cuenta para revisión.
8. **Comisiones reales:** registra en `usage_events` la comisión efectiva de cada cobro, para compararla con las hipótesis del modelo de costos.
9. **Ninguno de los dos procesadores actúa como merchant of record.** El IVA y los documentos tributarios los gestiona el responsable humano con su contador (8.2); el agente deja un punto de extensión para emitir y almacenar el documento por cobro, sin implementar la emisión.

**Criterios de aceptación:**
- `usage_events` y `usage_counters` registran acciones, activaciones y consumos por cuenta y ciclo.
- Los límites se leen de `entitlements`; cambiar un valor surte efecto sin desplegar (prueba automatizada).
- Al agotar la cuota de leads, una nueva activación se rechaza con `LIMIT_LEADS_REACHED` y los leads ya activos siguen recibiendo sus pasos.
- Al agotar créditos, la verificación externa se rechaza con `LIMIT_CREDITS_REACHED` y el resto del flujo continúa.
- Prueba automatizada: comprar un pack no cambia ningún límite de seguridad (5.5).
- Un tenant sin suscripción activa no recibe comandos.
- Un webhook repetido no duplica créditos ni cambia el estado dos veces (prueba automatizada).
- Una suscripción nunca se activa sin confirmación verificada del procesador.
- Panel interno con margen estimado por cuenta y distribución de uso.

---

### 5.10 [P2] Observabilidad y soporte

- Métricas por cuenta y globales: acciones ejecutadas, tasa de éxito por acción, tasa de aceptación de invitaciones, incidentes (checkpoint, CAPTCHA, restricciones), latencia de comandos, versión de cliente, leads activados y créditos consumidos por ciclo.
- Tablero interno para el equipo con alertas (picos de incidentes, fallos por acción, caída de canarios).
- Logs estructurados **sin datos personales innecesarios**; correlación por `command_id`.
- Telemetría en el cliente: mantener el Autopilot Banner y los logs visibles para el usuario; enviar al servidor solo lo necesario.
- Diagnóstico exportable por el usuario para soporte, sin credenciales ni contenido de chats.
- Documentar respuestas estándar de soporte (cuenta restringida, checkpoint, WhatsApp desconectado, computador apagado, límite comercial alcanzado).

### 5.11 [P2] Distribución, firma y auto-actualización

- Instaladores para Windows y macOS, **firmados** (certificado de firma de código en Windows; firma y notarización en macOS). Considerar falsos positivos de antivirus y documentar la instalación.
- **Auto-actualización** con verificación de firma y política de versión mínima soportada.
- Rotación de claves de verificación embebidas en el cliente.
- Comunicar al usuario las limitaciones inherentes del modelo local: el equipo debe estar encendido y con sesión activa para ejecutar.

---

## 6. Prohibiciones explícitas (NUNCA)

1. NUNCA almacenar contraseñas de LinkedIn, WhatsApp u otras plataformas de los usuarios. La sesión vive solo en la partición local del cliente.
2. NUNCA ejecutar código remoto arbitrario en el cliente.
3. NUNCA compartir, cachear o agregar datos de leads entre tenants.
4. NUNCA automatizar la interfaz de ningún CRM distinto de Zoho, ni ampliar el Zoho Bridge más allá de las acciones y reglas de 5.1 y 5.2.
5. NUNCA presentar los resultados de verificación de correo como certeza absoluta.
6. NUNCA enviar mensajes de WhatsApp en frío.
7. NUNCA incluir en la interfaz o la documentación promesas de "indetectable" o "sin riesgo".
8. NUNCA registrar tokens, contraseñas, contenido de chats ni claves en logs.
9. NUNCA reintentar indefinidamente ante un checkpoint, CAPTCHA o restricción.
10. NUNCA implementar en esta fase la integración con Zoho API ni con la API oficial de WhatsApp Business (sección 1.3). El Zoho Bridge por interfaz sí está vigente (5.2).
11. NUNCA aumentar un límite de seguridad por plan, pack o pago (5.5, 5.9).
12. NUNCA codificar en duro cifras comerciales (límites, créditos, precios); deben leerse de configuración (`entitlements`).
13. NUNCA cortar secuencias ya activas por agotar un límite comercial.
14. NUNCA verificar correos por SMTP propio (`RCPT TO`), ni desde servidores propios ni desde equipos de usuarios.
15. NUNCA hacer scraping de LinkedIn desde el servidor.
16. NUNCA usar bases de datos filtradas o de procedencia dudosa para obtener correos.
17. NUNCA permitir que un comando `ZOHO_*` lea o exporte registros en masa.

---

## 7. Hitos sugeridos

| Hito | Contenido | Resultado esperado |
|---|---|---|
| **M0** | Fase 0: auditoría y `audit_gap_analysis.md` (0.1) | Mapa claro de qué existe, qué falta y qué riesgos hay |
| **M1** | 5.1 canal firmado + 5.2 Zoho Bridge gobernado desde la nube, deduplicación interna, bitácora y exportación CSV | Cliente delgado que solo ejecuta comandos firmados, incluido Zoho; sin decisiones locales |
| **M2** | 5.3 PostgreSQL multi-tenant + auth + 5.4 base de cumplimiento (origen, supresión, borrado) + **instrumentación de uso de 5.9.D** | Plataforma lista para varios clientes con aislamiento verificado y datos de uso acumulándose |
| **M3** | 5.5 antiban en servidor + 5.8 selectores como datos + canarios | Operación estable y variación por usuario |
| **M4** | 5.6 OSINT + verificadores pagos + 5.7 WhatsApp (flag) + 5.9 límites comerciales, `entitlements`, ledger y cobro con Mercado Pago y PayPal | Producto cobrable con costos variables controlados |
| **M5** | 5.10 + 5.11 y beta cerrada con 10–20 clientes de pago + calibración de límites (5.9.D) | Datos reales de uso, churn, incidentes y margen antes de fijar límites y precio definitivos; reevaluación de Zoho API y WhatsApp API |

---

## 8. Decisiones

### 8.1 Decisiones tomadas (registro; no reabrir sin aprobación)

| # | Tema | Decisión |
|---|---|---|
| 1 | Zoho | Centro de datos de EE. UU. (`zoho.com`). Se usa el Zoho Bridge transitorio (5.2) |
| 2 | Hosting | AWS, PostgreSQL gestionado y KMS; región por defecto São Paulo (`sa-east-1`) |
| 3 | Retención | Purga a los 12 meses sin actividad, configurable por tenant |
| 4 | Límites de seguridad | Los de 5.5 (15 invitaciones/día con calentamiento, retardos de 180–360 s); WhatsApp ~15 mensajes/día solo a contactos cálidos. Configurables y a calibrar |
| 5 | WhatsApp | Solo contactos cálidos; el envío en frío no se implementa |
| 6 | Consumo de créditos | Solo por resultado utilizable; las fuentes públicas sin consulta externa no consumen |
| 7 | Proveedores de correo y búsqueda | MillionVerifier (principal), ZeroBounce (alternativo), Serper (búsqueda); comparación con 200–500 correos reales antes de M4 |
| 8 | Caché de metadatos de dominio | No hay caché global; todo por tenant |
| 9 | Procesadores de pago | Mercado Pago (Chile) y PayPal (resto del mundo) |
| 10 | Precio base | 15 USD por cuenta de LinkedIn conectada, con `price_lock_until` de 6 a 12 meses en la beta |
| 11 | Límites incluidos | 500 leads activados y 100 créditos de correo por ciclo |
| 12 | Packs | Leads: +500 por 5 USD (solo el ciclo). Créditos: 100 por 6 USD y 500 por 28 USD (sin vencimiento) |
| 13 | Márgenes y ofertas | Múltiplo 2× sobre costo en créditos; margen de contribución objetivo 60 %; anual con 2 meses gratis; sin descuento por volumen; prueba de 14 días sin tarjeta (100 leads y 20 créditos) |
| 14 | Textos legales | Los redacta un abogado; el agente usa textos provisionales marcados como tales |
| 15 | Zoho API y WhatsApp API | Se reevalúan después de M5, o antes si el Zoho Bridge se rompe más de 2 veces al mes |

### 8.2 Pendientes que no dependen del agente (no bloquean M0–M3)

1. **Textos legales** (términos de servicio, política de privacidad, acuerdo de tratamiento de datos, cláusula de uso aceptable), incluida la revisión de la transferencia internacional de datos. Deben estar listos **antes de la beta de pago (M5)**. Los requiere un abogado.
2. **Facturación en Chile:** moneda de cobro con Mercado Pago (pesos chilenos con regla de conversión desde el precio en USD, o cobro en USD), IVA y documentos tributarios electrónicos. Los define el responsable humano con su contador. Deben cerrarse **antes de M4**.
3. **Tarifas reales de Mercado Pago y PayPal** para tu cuenta. Verifícalas en cada panel y actualiza la hoja `Supuestos` del modelo de costos. Deben cerrarse **antes de M4**.

Mientras estén abiertos, el agente NO inventa respuestas: usa textos provisionales, mantiene la moneda y las tarifas como configuración y deja los puntos de extensión descritos en 5.9.G.

---

## 9. Definición de "terminado" para cada entrega

- Cumple los criterios de aceptación del workstream.
- Pruebas automatizadas (unitarias y de integración) incluidas y pasando.
- Sin secretos en el código; configuración por variables de entorno/gestor de secretos.
- Documentación breve actualizada (qué hace, cómo se configura, cómo se prueba).
- Sin regresión en las prohibiciones de la sección 6.
- Migraciones reversibles y cambios de comportamiento tras feature flag cuando haya usuarios activos (0.1).
- Riesgos nuevos detectados reportados explícitamente en la descripción del PR.

---

*Este documento resume el análisis de arquitectura, modelo de negocio y riesgos de la plataforma. No constituye asesoría legal ni financiera; las referencias normativas y de precios deben verificarse con fuentes vigentes antes de implementar.*
