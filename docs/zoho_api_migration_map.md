# Mapa de Migración Técnica: Zoho Bridge Transitorio a Zoho CRM REST API v6
**NexusReach Pro — Documento de Arquitectura y Salida Limpia (Workstream 5.2 - Requisito 11)**  
**Versión:** 1.0.0  
**Fecha de Publicación:** Octubre 2026  
**Clasificación:** Confidencial / Arquitectura Interna

---

## 1. Visión y Estrategia de Desacople

El módulo **Zoho Bridge** de NexusReach Pro opera como una solución transitoria y aislada en una partición Chromium independiente (`persist:nexusreach_zoho_bridge`). Su diseño sigue el principio de **Gobernanza 100% en el Servidor**: la decisión de sincronización, deduplicación y cambio de estado se calcula en el backend mediante comandos tipados y firmados (`ZOHO_*`), sin que el cliente tome decisiones de negocio.

Cuando la empresa active credenciales oficiales de desarrollador (Zoho OAuth Client ID / Secret), la migración consistirá en reemplazar el ejecutor del cliente local por llamadas directas HTTP desde el servidor FastAPI a la API REST v6 de Zoho, **sin necesidad de modificar el modelo de base de datos ni los flujos de secuencias**.

---

## 2. Equivalencia de Acciones Tipadas vs Zoho CRM REST API

### 2.1 Acción `ZOHO_FIND_LEAD`

* **Propósito:** Comprueba la existencia previa de un prospecto por correo o nombre completo para evitar colisiones entre representantes y duplicados.
* **Comando Firmado Actual:**
  ```json
  {
    "action": "ZOHO_FIND_LEAD",
    "params": {
      "lead_id": "lead_uuid",
      "name": "Francisca Silva",
      "email": "fsilva@colegiosanpedro.cl"
    }
  }
  ```
* **Llamada Equivalente Oficial (API REST v6):**
  * **Método y URL:** `GET https://www.zohoapis.com/crm/v6/Contacts/search`
  * **Query Params:** `?email=fsilva@colegiosanpedro.cl` (o fallback `?word=Francisca%20Silva`)
  * **Headers:**
    ```http
    Authorization: Zoho-oauthtoken {access_token}
    Content-Type: application/json
    ```
  * **OAuth Scopes Requeridos:** `ZohoCRM.modules.contacts.READ`, `ZohoCRM.modules.leads.READ`
  * **Mapeo de Respuesta:**
    * Si HTTP 204: `{ "found": false }`
    * Si HTTP 200:
      ```json
      {
        "found": true,
        "id": response.data[0].id,
        "entity": "Contact",
        "owner": response.data[0].Owner.name,
        "status": response.data[0].Lead_Status || "Active"
      }
      ```
    * El backend persiste `crm_external_id = response.data[0].id` y `crm_sync_status = "SYNCED"`.

---

### 2.2 Acción `ZOHO_UPSERT_LEAD`

* **Propósito:** Crea o actualiza la ficha del prospecto en Zoho CRM cuando avanza en el embudo comercial.
* **Comando Firmado Actual:**
  ```json
  {
    "action": "ZOHO_UPSERT_LEAD",
    "params": {
      "lead_id": "lead_uuid",
      "data": {
        "first_name": "Francisca",
        "last_name": "Silva",
        "company": "Colegio San Pedro",
        "email": "fsilva@colegiosanpedro.cl",
        "phone": "+56912345678",
        "linkedin_url": "https://www.linkedin.com/in/francisca-silva"
      }
    }
  }
  ```
* **Llamada Equivalente Oficial (API REST v6):**
  * **Método y URL:** `POST https://www.zohoapis.com/crm/v6/Leads/upsert`
  * **Headers:**
    ```http
    Authorization: Zoho-oauthtoken {access_token}
    Content-Type: application/json
    ```
  * **Cuerpo JSON:**
    ```json
    {
      "data": [
        {
          "First_Name": "Francisca",
          "Last_Name": "Silva",
          "Company": "Colegio San Pedro",
          "Email": "fsilva@colegiosanpedro.cl",
          "Phone": "+56912345678",
          "LinkedIn_URL": "https://www.linkedin.com/in/francisca-silva",
          "Lead_Source": "NexusReach Pro LinkedIn Outreach"
        }
      ],
      "duplicate_check_fields": ["Email", "LinkedIn_URL"]
    }
    ```
  * **OAuth Scopes Requeridos:** `ZohoCRM.modules.leads.CREATE`, `ZohoCRM.modules.leads.UPDATE`
  * **Mapeo de Respuesta:** Retorna `details.id`, el cual se almacena en `leads.crm_external_id`.

---

### 2.3 Acción `ZOHO_SET_STATUS`

* **Propósito:** Sincroniza el cambio de estado en el CRM (ej. *Contactado*, *En Conversación*, *No Calificado*).
* **Comando Firmado Actual:**
  ```json
  {
    "action": "ZOHO_SET_STATUS",
    "params": {
      "lead_id": "lead_uuid",
      "crm_external_id": "5429182000012345678",
      "status": "Contacted"
    }
  }
  ```
* **Llamada Equivalente Oficial (API REST v6):**
  * **Método y URL:** `PUT https://www.zohoapis.com/crm/v6/Leads/{crm_external_id}`
  * **Headers:**
    ```http
    Authorization: Zoho-oauthtoken {access_token}
    Content-Type: application/json
    ```
  * **Cuerpo JSON:**
    ```json
    {
      "data": [
        {
          "Lead_Status": "Contacted"
        }
      ]
    }
    ```
  * **OAuth Scopes Requeridos:** `ZohoCRM.modules.leads.UPDATE`

---

### 2.4 Acción `ZOHO_ADD_NOTE`

* **Propósito:** Adjunta una nota de auditoría o resumen de interacción en la ficha del lead en Zoho como copia secundaria (la bitácora interna `lead_activity` permanece como fuente de verdad).
* **Comando Firmado Actual:**
  ```json
  {
    "action": "ZOHO_ADD_NOTE",
    "params": {
      "lead_id": "lead_uuid",
      "crm_external_id": "5429182000012345678",
      "title": "Invitación LinkedIn Aceptada",
      "content": "El prospecto aceptó la solicitud de conexión el 21/10/2026. Mensaje de bienvenida enviado."
    }
  }
  ```
* **Llamada Equivalente Oficial (API REST v6):**
  * **Método y URL:** `POST https://www.zohoapis.com/crm/v6/Leads/{crm_external_id}/Notes`
  * **Headers:**
    ```http
    Authorization: Zoho-oauthtoken {access_token}
    Content-Type: application/json
    ```
  * **Cuerpo JSON:**
    ```json
    {
      "data": [
        {
          "Note_Title": "Invitación LinkedIn Aceptada",
          "Note_Content": "El prospecto aceptó la solicitud de conexión el 21/10/2026. Mensaje de bienvenida enviado."
        }
      ]
    }
    ```
  * **OAuth Scopes Requeridos:** `ZohoCRM.modules.notes.CREATE`

---

## 3. Plan de Retiro del Puente Transitorio (Zero Downtime)

1. **Paso 1 (Configuración de Credenciales):** Incorporar en la tabla `tenants` las columnas `zoho_client_id`, `zoho_client_secret` y `zoho_refresh_token` cifradas con KMS.
2. **Paso 2 (Feature Flag de Transición):** Configurar el conmutador por tenant: `zoho_mode = 'API' | 'BRIDGE' | 'DISABLED'`.
3. **Paso 3 (Conmutación):** En `task_dispatcher.py`, si `zoho_mode == 'API'`, invocar un cliente REST asíncrono (`zoho_api_client.py`) en lugar de despachar comandos al runner local.
4. **Paso 4 (Deprecación):** Retirar la partición `persist:nexusreach_zoho_bridge` del Electron cliente una vez que todos los tenants utilicen la API.
