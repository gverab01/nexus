# NexusReach Pro — Playbook de Soporte y Respuestas Estándar (Workstream 5.10)

Este documento define los procedimientos estandarizados de atención técnica para el equipo de soporte de NexusReach Pro. Los agentes de soporte deben seguir estos protocolos para garantizar la seguridad de las cuentas de los clientes y mantener la confidencialidad de los datos (sin solicitar jamás contraseñas ni tokens).

---

## 1. Protocolo ante Cuenta de LinkedIn con Checkpoint, CAPTCHA o Restricción

### Diagnóstico
- **Señal:** El runner local reporta `CHECKPOINT`, `CAPTCHA`, `PIN_VERIFICATION` o `ACCOUNT_RESTRICTED`.
- **Comportamiento automático del sistema:** El motor de seguridad del servidor (`safety_engine.py`) congela inmediatamente la cola de la cuenta afectada en menos de un ciclo de dispatch. Si $\ge 3$ cuentas sufren incidentes en menos de 24 horas, se activa el **Kill-Switch Global**.

### Procedimiento de Atención
1. **Verificación:** Solicitar al usuario que exporte su paquete de diagnóstico desde el menú de la aplicación (`Configuración > Soporte > Exportar Diagnóstico`).
2. **Instrucción al Usuario:**
   > *"Por su seguridad, NexusReach ha pausado automáticamente todos los envíos para proteger su perfil. Por favor, abra la ventana de LinkedIn dentro de la aplicación NexusReach y resuelva el desafío de seguridad (código por correo, SMS o CAPTCHA) directamente en la interfaz oficial."*
3. **Reactivación:**
   - Una vez que el usuario confirme que navega normalmente en LinkedIn:
   - Se ejecuta la reactivación controlada vía endpoint `POST /api/accounts/{account_id}/reactivate`.
   - **Compromiso antiban:** La cuenta reiniciará automáticamente su rampa de calentamiento en el **Día 1 (15 invitaciones/día)** para reconstruir la reputación algorítmica de forma gradual.
4. **Prohibición estricta:** NUNCA solicitar las credenciales ni contraseña de LinkedIn del usuario.

---

## 2. Protocolo ante WhatsApp Web Desconectado

### Diagnóstico
- **Señal:** Estado `SESSION_DISCONNECTED` o alerta de pérdida de sincronización con el teléfono móvil.
- **Comportamiento automático del sistema:** Se activa el Kill-Switch específico del canal de WhatsApp (`whatsapp_kill_switch_activado = 1`). El canal de LinkedIn permanece totalmente operativo sin interrupción.

### Procedimiento de Atención
1. **Causa raíz habitual:** Teléfono móvil sin conexión a internet, apagado, en ahorro de batería extremo o sesión revocada desde la app móvil de WhatsApp.
2. **Instrucción al Usuario:**
   > *"El canal de WhatsApp Web se ha pausado preventivamente para evitar fallos de entrega. Por favor, asegúrese de que su teléfono móvil tenga conexión activa a internet y vuelva a escanear el código QR en la pestaña de WhatsApp de NexusReach."*
3. **Reactivación:** Una vez reestablecida la sesión, el usuario presiona "Reanudar Canal WhatsApp" en la barra de control o el soporte restablece el flag del canal.

---

## 3. Protocolo ante Equipo Apagado o en Suspensión

### Diagnóstico
- **Señal:** Dispositivo en estado `OFFLINE` en el panel de telemetría; los comandos acumulados esperan en cola.

### Procedimiento de Atención
1. **Explicación de Arquitectura:**
   > *"NexusReach Pro utiliza una arquitectura Local-First para maximizar la seguridad de su cuenta. Esto significa que las acciones se ejecutan exclusivamente desde su propia conexión residencial/oficina y su navegador embebido, eliminando el riesgo de proxies compartidos en la nube.*
   >
   > *Por diseño, para que el sistema realice tareas programadas, su computador debe encontrarse encendido y con la aplicación abierta. Si suspende o apaga su equipo, ninguna acción se pierde: las secuencias se reanudan automáticamente tan pronto vuelva a encender su computador."*
2. **Recomendación:** Sugerir desactivar la suspensión automática del equipo durante el horario comercial si desea prospección continua.

---

## 4. Protocolo ante Límite Comercial Alcanzado

### Diagnóstico
- **Señales:** 
  - `LIMIT_LEADS_REACHED`: Se alcanzaron los 500 leads nuevos del ciclo mensual.
  - `LIMIT_CREDITS_REACHED`: Se agotaron los 100 créditos de resolución externa de correos.

### Procedimiento de Atención
1. **Aclaración Crucial (NUNCA se cortan conversaciones en curso):**
   > *"Su cuota mensual de nuevos prospectos se ha completado. Tenga la total tranquilidad de que todas sus conversaciones activas, seguimientos, mensajes de respuesta y secuencias en curso seguirán ejecutándose con normalidad sin interrupción."*
2. **Opciones ofrecidas al usuario:**
   - **Opción A:** Adquirir un Pack Adicional de Leads (+500 leads para el ciclo en curso por 5 USD) desde `Facturación > Comprar Pack`.
   - **Opción B:** Adquirir un Pack de Créditos de Correo (100 créditos por 6 USD o 500 créditos por 28 USD, sin fecha de caducidad).
   - **Opción C:** Esperar la renovación automática de la cuota en el primer día del siguiente ciclo mensual.
3. **Recordatorio Normativo:** Informar con claridad que los packs comerciales otorgan capacidad de volumen en el ciclo, pero **NO alteran los límites de seguridad antiban de 15 a 25 invitaciones diarias**, los cuales son innegociables para resguardar la cuenta.

---

## 5. Protocolo ante Degradación por Cambio de Interfaz (`ACTION_PAUSED_INTERFACE_CHANGE`)

### Diagnóstico
- **Señal:** El canario o el reporte de clientes registró $\ge 3$ fallos consecutivos de selectores DOM en una acción específica (ej. botón Conectar de LinkedIn o Crear Lead de Zoho).

### Procedimiento de Atención
1. **Tranquilidad al cliente:** Informar que la acción específica fue pausada preventivamente por el motor de degradación segura para no generar actividad errática.
2. **Procedimiento del equipo de ingeniería:**
   - Correr la auditoría canario (`POST /api/selectors/canary-run`).
   - Identificar el nuevo selector semántico o ARIA.
   - Publicar el nuevo catálogo firmado (`POST /api/selectors/publish`) mediante Ed25519.
   - La acción se reactiva automáticamente para todos los clientes en tiempo real sin requerir que descarguen un nuevo ejecutable.
