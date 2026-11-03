import os
import json
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
from database import get_db
import safety_engine
import whatsapp_safety_engine

# ==============================================================================
# SERVICIO DE DASHBOARD, MÉTRICAS Y ANALÍTICA B2B (NexusReach Pro)
# ==============================================================================

def get_dashboard_metrics(tenant_id: Optional[str] = None, sequence_id: Optional[str] = None, list_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Calcula de forma agregada e integral todas las métricas de prospección,
    embudo de conversión, cupos antiban y salud multicanal para el Dashboard.

    Args:
        tenant_id (Optional[str]): Filtrar por organización o None para global.
        sequence_id (Optional[str]): Filtrar por una secuencia específica o None.
        list_id (Optional[str]): Filtrar por una lista de leads específica o None.

    Returns:
        Dict[str, Any]: Estructura jerárquica con KPIs, embudo y estado de canales.
    """
    today_iso = date.today().isoformat()
    now_iso = datetime.now().isoformat()

    with get_db() as conn:
        cursor = conn.cursor()

        # ----------------------------------------------------------------------
        # 1. Filtros base para tabla 'leads'
        # ----------------------------------------------------------------------
        lead_where = ["1=1"]
        lead_params = []
        if tenant_id:
            lead_where.append("l.tenant_id = ?")
            lead_params.append(tenant_id)
        if list_id:
            lead_where.append("l.id IN (SELECT lead_id FROM leads_en_lista WHERE lista_id = ?)")
            lead_params.append(list_id)
        if sequence_id:
            lead_where.append("l.id IN (SELECT lead_id FROM leads_en_secuencia WHERE secuencia_id = ?)")
            lead_params.append(sequence_id)

        lead_where_sql = " AND ".join(lead_where)

        # Total de leads en la base completa (filtrado por tenant/lista/secuencia)
        cursor.execute(f"SELECT COUNT(*) as total FROM leads l WHERE {lead_where_sql}", lead_params)
        total_leads_base = cursor.fetchone()["total"]

        # Total absoluto en la base de datos (sin filtro de lista/secuencia para contexto global)
        if tenant_id:
            cursor.execute("SELECT COUNT(*) as total FROM leads WHERE tenant_id = ?", (tenant_id,))
            total_leads_absoluto = cursor.fetchone()["total"]
        else:
            cursor.execute("SELECT COUNT(*) as total FROM leads")
            total_leads_absoluto = cursor.fetchone()["total"]

        # ----------------------------------------------------------------------
        # 2. Cobertura de correos electrónicos
        # ----------------------------------------------------------------------
        cursor.execute(f"""
            SELECT 
                COUNT(*) as total_con_email,
                SUM(CASE WHEN (l.email_zoho IS NOT NULL AND l.email_zoho != '') THEN 1 ELSE 0 END) as con_email_zoho,
                SUM(CASE WHEN (l.email_extracted IS NOT NULL AND l.email_extracted != '') THEN 1 ELSE 0 END) as con_email_linkedin,
                SUM(CASE WHEN ((l.email IS NOT NULL AND l.email != '') AND (l.email_zoho IS NULL OR l.email_zoho = '') AND (l.email_extracted IS NULL OR l.email_extracted = '')) THEN 1 ELSE 0 END) as con_email_manual
            FROM leads l
            WHERE {lead_where_sql} AND (
                (l.email IS NOT NULL AND l.email != '') OR 
                (l.email_zoho IS NOT NULL AND l.email_zoho != '') OR 
                (l.email_extracted IS NOT NULL AND l.email_extracted != '')
            )
        """, lead_params)
        email_stats = cursor.fetchone() or {}
        total_con_email = email_stats.get("total_con_email", 0) or 0
        con_email_zoho = email_stats.get("con_email_zoho", 0) or 0
        con_email_linkedin = email_stats.get("con_email_linkedin", 0) or 0
        con_email_manual = email_stats.get("con_email_manual", 0) or 0

        cobertura_email_pct = round((total_con_email / total_leads_base * 100), 1) if total_leads_base > 0 else 0

        # ----------------------------------------------------------------------
        # 3. Métricas de Secuencias y Avance
        # ----------------------------------------------------------------------
        seq_where = ["1=1"]
        seq_params = []
        if tenant_id:
            seq_where.append("s.tenant_id = ?")
            seq_params.append(tenant_id)
        if sequence_id:
            seq_where.append("ls.secuencia_id = ?")
            seq_params.append(sequence_id)
        if list_id:
            seq_where.append("ls.lead_id IN (SELECT lead_id FROM leads_en_lista WHERE lista_id = ?)")
            seq_params.append(list_id)

        seq_where_sql = " AND ".join(seq_where)

        cursor.execute(f"""
            SELECT 
                COUNT(*) as total_inscritos,
                SUM(CASE WHEN ls.estado = 'EN_CURSO' THEN 1 ELSE 0 END) as total_en_curso,
                SUM(CASE WHEN ls.estado IN ('COMPLETADO', 'FINALIZADA') THEN 1 ELSE 0 END) as total_completados
            FROM leads_en_secuencia ls
            JOIN secuencias s ON s.id = ls.secuencia_id
            WHERE {seq_where_sql}
        """, seq_params)
        seq_stats = cursor.fetchone() or {}
        total_leads_secuencia = seq_stats.get("total_inscritos", 0) or 0
        total_en_curso = seq_stats.get("total_en_curso", 0) or 0
        total_completados = seq_stats.get("total_completados", 0) or 0

        tasa_finalizacion_pct = round((total_completados / total_leads_secuencia * 100), 1) if total_leads_secuencia > 0 else 0

        # ----------------------------------------------------------------------
        # 4. Métricas de Invitaciones y Conexiones (LinkedIn)
        # ----------------------------------------------------------------------
        cursor.execute(f"""
            SELECT 
                COUNT(*) as enviadas,
                SUM(CASE WHEN l.fecha_invitacion LIKE ? THEN 1 ELSE 0 END) as enviadas_hoy,
                SUM(CASE WHEN l.estado IN ('CONECTADO', 'MENSAJE_ENVIADO', 'RESPONDIÓ', 'REUNIÓN_AGENDADA') OR l.fecha_conexion IS NOT NULL THEN 1 ELSE 0 END) as aceptadas
            FROM leads l
            WHERE {lead_where_sql} AND (l.fecha_invitacion IS NOT NULL OR l.estado IN ('INVITACION_ENVIADA', 'CONECTADO', 'MENSAJE_ENVIADO', 'RESPONDIÓ', 'REUNIÓN_AGENDADA'))
        """, [f"{today_iso}%"] + lead_params)
        inv_stats = cursor.fetchone() or {}
        invitaciones_enviadas = inv_stats.get("enviadas", 0) or 0
        invitaciones_hoy = inv_stats.get("enviadas_hoy", 0) or 0
        invitaciones_aceptadas = inv_stats.get("aceptadas", 0) or 0

        tasa_aceptacion_pct = round((invitaciones_aceptadas / invitaciones_enviadas * 100), 1) if invitaciones_enviadas > 0 else 0

        # ----------------------------------------------------------------------
        # 5. Métricas de Mensajes y Conversaciones
        # ----------------------------------------------------------------------
        cursor.execute(f"""
            SELECT 
                SUM(CASE WHEN l.estado IN ('MENSAJE_ENVIADO', 'RESPONDIÓ', 'REUNIÓN_AGENDADA') THEN 1 ELSE 0 END) as mensajes_enviados,
                SUM(CASE WHEN l.estado IN ('RESPONDIÓ', 'REUNIÓN_AGENDADA') THEN 1 ELSE 0 END) as mensajes_recibidos,
                SUM(CASE WHEN l.estado = 'REUNIÓN_AGENDADA' THEN 1 ELSE 0 END) as reuniones_agendadas
            FROM leads l
            WHERE {lead_where_sql}
        """, lead_params)
        msg_stats = cursor.fetchone() or {}
        mensajes_enviados = msg_stats.get("mensajes_enviados", 0) or 0
        mensajes_recibidos = msg_stats.get("mensajes_recibidos", 0) or 0
        reuniones_agendadas = msg_stats.get("reuniones_agendadas", 0) or 0

        tasa_respuesta_pct = round((mensajes_recibidos / mensajes_enviados * 100), 1) if mensajes_enviados > 0 else 0
        tasa_reunion_pct = round((reuniones_agendadas / invitaciones_aceptadas * 100), 1) if invitaciones_aceptadas > 0 else 0

        # ----------------------------------------------------------------------
        # 6. Cruce de Inteligencia Zoho CRM
        # ----------------------------------------------------------------------
        cursor.execute(f"""
            SELECT 
                COUNT(*) as sincronizados,
                SUM(CASE WHEN l.zoho_cuenta_es_cliente = 1 THEN 1 ELSE 0 END) as clientes_activos,
                SUM(CASE WHEN (l.zoho_tratos_info IS NOT NULL AND l.zoho_tratos_info != '' AND l.zoho_tratos_info != '[]') THEN 1 ELSE 0 END) as con_tratos
            FROM leads l
            WHERE {lead_where_sql} AND l.zoho_id IS NOT NULL
        """, lead_params)
        zoho_stats = cursor.fetchone() or {}
        zoho_sincronizados = zoho_stats.get("sincronizados", 0) or 0
        zoho_clientes = zoho_stats.get("clientes_activos", 0) or 0
        zoho_con_tratos = zoho_stats.get("con_tratos", 0) or 0

        # ----------------------------------------------------------------------
        # 7. Diagnósticos Antiban y Curva Warm-up
        # ----------------------------------------------------------------------
        warmup_status = safety_engine.get_linkedin_warmup_status(conn)
        cupo_diario_hoy = warmup_status.get("limite_sugerido", 8)
        cupo_restante_hoy = max(0, cupo_diario_hoy - invitaciones_hoy)
        cupo_usado_pct = round((invitaciones_hoy / cupo_diario_hoy * 100), 1) if cupo_diario_hoy > 0 else 100

        search_usage = safety_engine.get_linkedin_search_usage(conn)
        wa_usage = whatsapp_safety_engine.get_whatsapp_daily_usage(conn)

        # ----------------------------------------------------------------------
        # 8. Embudo de Conversión (Funnel Stages)
        # ----------------------------------------------------------------------
        cursor.execute(f"""
            SELECT 
                SUM(CASE WHEN l.estado IN ('PERFIL_VISITADO', 'INVITACION_ENVIADA', 'CONECTADO', 'MENSAJE_ENVIADO', 'RESPONDIÓ', 'REUNIÓN_AGENDADA') THEN 1 ELSE 0 END) as perfiles_visitados
            FROM leads l
            WHERE {lead_where_sql}
        """, lead_params)
        visitados_row = cursor.fetchone() or {}
        perfiles_visitados = visitados_row.get("perfiles_visitados", 0) or 0

        funnel = [
            {"etapa": "Base de Prospectos", "cantidad": total_leads_base, "color": "#6366f1", "desc": "Total en base de datos"},
            {"etapa": "Enrolados en Flujo", "cantidad": total_leads_secuencia, "color": "#8b5cf6", "desc": "Ingresados a secuencias"},
            {"etapa": "Perfiles Visitados", "cantidad": perfiles_visitados, "color": "#0ea5e9", "desc": "Paso 1 completado"},
            {"etapa": "Invitaciones Enviadas", "cantidad": invitaciones_enviadas, "color": "#06b6d4", "desc": "Solicitudes emitidas"},
            {"etapa": "Conectados", "cantidad": invitaciones_aceptadas, "color": "#10b981", "desc": "Red de 1er grado"},
            {"etapa": "Mensajes Enviados", "cantidad": mensajes_enviados, "color": "#3b82f6", "desc": "Outreach conversacional"},
            {"etapa": "Respondieron", "cantidad": mensajes_recibidos, "color": "#f59e0b", "desc": "Interacción activa"},
            {"etapa": "Reunión Agendada", "cantidad": reuniones_agendadas, "color": "#ec4899", "desc": "Oportunidades de alto valor"}
        ]

        # ----------------------------------------------------------------------
        # 9. Listado de Secuencias para selector y tabla comparativa
        # ----------------------------------------------------------------------
        sec_filter = "s.tenant_id = ?" if tenant_id else "1=1"
        sec_filter_params = [tenant_id] if tenant_id else []
        cursor.execute(f"""
            SELECT 
                s.id, s.nombre, s.estado, s.activa,
                (SELECT COUNT(*) FROM leads_en_secuencia WHERE secuencia_id = s.id) as total_leads,
                (SELECT COUNT(*) FROM leads_en_secuencia WHERE secuencia_id = s.id AND estado = 'EN_CURSO') as en_curso,
                (SELECT COUNT(*) FROM leads_en_secuencia WHERE secuencia_id = s.id AND estado IN ('COMPLETADO', 'FINALIZADA')) as completados,
                (SELECT COUNT(*) FROM leads_en_secuencia ls JOIN leads l ON ls.lead_id = l.id WHERE ls.secuencia_id = s.id AND l.estado IN ('CONECTADO', 'MENSAJE_ENVIADO', 'RESPONDIÓ', 'REUNIÓN_AGENDADA')) as conectados
            FROM secuencias s
            WHERE {sec_filter}
            ORDER BY s.created_at DESC
        """, sec_filter_params)
        secuencias_list = [dict(r) for r in cursor.fetchall()]

        # ----------------------------------------------------------------------
        # 10. Listado de Listas de Prospectos
        # ----------------------------------------------------------------------
        list_filter = "l.tenant_id = ?" if tenant_id else "1=1"
        list_filter_params = [tenant_id] if tenant_id else []
        cursor.execute(f"""
            SELECT 
                l.id, l.nombre, l.estado,
                (SELECT COUNT(*) FROM leads_en_lista WHERE lista_id = l.id) as total_leads
            FROM listas_leads l
            WHERE {list_filter}
            ORDER BY l.created_at DESC
        """, list_filter_params)
        listas_list = [dict(r) for r in cursor.fetchall()]

        return {
            "fecha_reporte": now_iso,
            "metricas_clave": {
                # a. Cantidad de invitaciones enviadas
                "invitaciones_enviadas": invitaciones_enviadas,
                # b. Cupo de invitaciones del día según plan antiban
                "cupo_invitaciones_hoy": cupo_diario_hoy,
                "invitaciones_hoy": invitaciones_hoy,
                "cupo_restante_hoy": cupo_restante_hoy,
                "cupo_usado_pct": cupo_usado_pct,
                # c. Cantidad de invitaciones aceptadas
                "invitaciones_aceptadas": invitaciones_aceptadas,
                # d. Cantidad de leads en la secuencia
                "total_leads_secuencia": total_leads_secuencia,
                "leads_en_curso": total_en_curso,
                # e. Cantidad de leads que terminaron todos los pasos
                "leads_completados": total_completados,
                "tasa_finalizacion_pct": tasa_finalizacion_pct,
                # f. % de invitaciones aceptadas
                "tasa_aceptacion_pct": tasa_aceptacion_pct,
                # g. Cantidad de mensajes enviados
                "mensajes_enviados": mensajes_enviados,
                # h. Cantidad de mensajes recibidos
                "mensajes_recibidos": mensajes_recibidos,
                "tasa_respuesta_pct": tasa_respuesta_pct,
                # i. Leads con correo electrónico registrado (desglose)
                "leads_con_email": total_con_email,
                "cobertura_email_pct": cobertura_email_pct,
                "email_por_fuente": {
                    "zoho_crm": con_email_zoho,
                    "linkedin_waterfall": con_email_linkedin,
                    "manual": con_email_manual
                },
                # j. Leads en secuencia
                "leads_secuencia_actual": total_leads_secuencia,
                # k. Leads en base completa
                "total_leads_base": total_leads_base,
                "total_leads_absoluto": total_leads_absoluto,
                # KPIs adicionales de alto valor
                "reuniones_agendadas": reuniones_agendadas,
                "tasa_reunion_pct": tasa_reunion_pct,
                "perfiles_visitados": perfiles_visitados
            },
            "zoho_crm_kpis": {
                "sincronizados": zoho_sincronizados,
                "clientes_activos": zoho_clientes,
                "con_tratos": zoho_con_tratos,
                "con_email_zoho": con_email_zoho
            },
            "antiban_salud": {
                "linkedin": {
                    "warmup_activo": warmup_status.get("activo", True),
                    "semana": warmup_status.get("semana", 1),
                    "dia_actual": warmup_status.get("dia_actual", 1),
                    "limite_hoy": cupo_diario_hoy,
                    "enviadas_hoy": invitaciones_hoy,
                    "cupo_restante": cupo_restante_hoy,
                    "busquedas_mes": search_usage.get("busquedas_mes", 0),
                    "busquedas_limite_alerta": search_usage.get("umbral_alerta", 80),
                    "busquedas_limite_max": search_usage.get("umbral_bloqueo", 100),
                    "alerta_busquedas": search_usage.get("alerta_limite", False)
                },
                "whatsapp": {
                    "cuota_diaria": wa_usage.get("cuota_diaria", 15),
                    "enviados_hoy": wa_usage.get("enviados_hoy", 0),
                    "cupo_restante": wa_usage.get("cupo_restante", 15),
                    "mecanografia_biometrica": True,
                    "cero_links_frio": True
                }
            },
            "funnel": funnel,
            "secuencias": secuencias_list,
            "listas": listas_list
        }
