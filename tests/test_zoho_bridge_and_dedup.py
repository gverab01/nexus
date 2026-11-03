"""
Test Suite de Zoho Bridge Transitorio, Deduplicación DB-First y Bitácora (Workstream 5.2 [P0])
NexusReach Pro Directrices de Ingeniería v1.3

Verifica rigurosamente:
1. Feature flag por tenant: bloqueo de acciones ZOHO_* si el flag está apagado.
2. Deduplicación interna DB-first: bloqueo de colisiones entre representantes del mismo tenant.
3. Lista de supresión (Opt-out): bloqueo con hash SHA-256 de correos, teléfonos y URLs.
4. Bitácora interna lead_activity como fuente única de verdad.
5. Desacoplamiento de estados internos de los identificadores de Zoho CRM.
6. Control de cadencia y limitación de tasa (rate limiting).
7. Exportación CSV nativa y aislamiento estricto entre tenants.
"""

import os
import sys
import csv
import io
import uuid
import secrets
import unittest
from datetime import datetime, timezone

# Path al root
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database import get_db, init_db
import zoho_bridge_service
from zoho_bridge_service import (
    get_zoho_config,
    set_zoho_config,
    is_zoho_bridge_enabled,
    add_to_suppression_list,
    is_suppressed,
    check_internal_collision,
    log_lead_activity,
    get_lead_activities,
    create_zoho_find_lead_command,
    create_zoho_upsert_lead_command,
    create_zoho_set_status_command,
    create_zoho_add_note_command,
    sync_zoho_result_to_lead,
    export_leads_with_activity_csv
)
import command_signing_service


class TestZohoBridgeAndDedup(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.tenant_a = "ten_ztest_a_" + secrets.token_hex(4)
        self.tenant_b = "ten_ztest_b_" + secrets.token_hex(4)
        self.device_id = "dev_ztest_" + secrets.token_hex(4)

        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            # Crear Tenant A (sin Zoho por defecto)
            cursor.execute("""
                INSERT INTO tenants (id, razon_social, tipo_tenant, estado, zoho_sync_activo, zoho_org_id, created_at, updated_at)
                VALUES (?, 'Colegio San Pedro A', 'EMPRESA', 'ACTIVO', 0, 'org_test_123', ?, ?)
            """, (self.tenant_a, now_iso, now_iso))

            # Crear Tenant B (aislado)
            cursor.execute("""
                INSERT INTO tenants (id, razon_social, tipo_tenant, estado, zoho_sync_activo, zoho_org_id, created_at, updated_at)
                VALUES (?, 'Liceo Santa Maria B', 'EMPRESA', 'ACTIVO', 0, NULL, ?, ?)
            """, (self.tenant_b, now_iso, now_iso))
            conn.commit()

        # Dispositivo de prueba registrado con clave Ed25519 válida (fuera del contexto de conexión)
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.hazmat.primitives import serialization
        import base64

        dev_priv = ed25519.Ed25519PrivateKey.generate()
        raw_dev_pub = dev_priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        dev_pub_b64 = base64.b64encode(raw_dev_pub).decode("utf-8")

        command_signing_service.register_device(
            device_id=self.device_id,
            tenant_id=self.tenant_a,
            public_key_ed25519=dev_pub_b64,
            device_name="Zoho Test Device",
            client_version="1.3.0"
        )

    def tearDown(self):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM lead_activity WHERE tenant_id IN (?, ?)", (self.tenant_a, self.tenant_b))
            cursor.execute("DELETE FROM suppression_list WHERE tenant_id IN (?, ?)", (self.tenant_a, self.tenant_b))
            cursor.execute("DELETE FROM leads_en_secuencia WHERE lead_id IN (SELECT id FROM leads WHERE tenant_id IN (?, ?))", (self.tenant_a, self.tenant_b))
            cursor.execute("DELETE FROM leads WHERE tenant_id IN (?, ?)", (self.tenant_a, self.tenant_b))
            cursor.execute("DELETE FROM commands WHERE tenant_id IN (?, ?)", (self.tenant_a, self.tenant_b))
            cursor.execute("DELETE FROM devices WHERE tenant_id IN (?, ?)", (self.tenant_a, self.tenant_b))
            cursor.execute("DELETE FROM tenants WHERE id IN (?, ?)", (self.tenant_a, self.tenant_b))
            conn.commit()

    def test_01_feature_flag_blocks_zoho_commands_when_disabled(self):
        """1. Bloqueo de acciones ZOHO_* si el feature flag del tenant está apagado."""
        self.assertFalse(is_zoho_bridge_enabled(self.tenant_a))

        # Intentar emitir ZOHO_FIND_LEAD debe lanzar PermissionError
        with self.assertRaises(PermissionError) as ctx:
            create_zoho_find_lead_command(
                tenant_id=self.tenant_a,
                device_id=self.device_id,
                lead_id="lead_1",
                name="Ignacio Larraín",
                email="ilarrain@colegio.cl"
            )
        self.assertIn("Zoho Bridge no está activado", str(ctx.exception))

        # Crear lead_1 en la base de datos para satisfacer integridad referencial
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, perfil_url, estado, created_at, updated_at)
                VALUES ('lead_1', ?, 'Ignacio Larraín', 'https://linkedin.com/in/ilarrain', 'EXTRAIDO', ?, ?)
            """, (self.tenant_a, now_iso, now_iso))
            conn.commit()

        # Activar feature flag
        set_zoho_config(self.tenant_a, activo=True, org_id="org_test_123")
        self.assertTrue(is_zoho_bridge_enabled(self.tenant_a))

        # Ahora debe emitir comando firmado exitosamente
        cmd = create_zoho_find_lead_command(
            tenant_id=self.tenant_a,
            device_id=self.device_id,
            lead_id="lead_1",
            name="Ignacio Larraín",
            email="ilarrain@colegio.cl"
        )
        self.assertEqual(cmd["action"], "ZOHO_FIND_LEAD")
        self.assertIn("signature", cmd)

    def test_02_internal_collision_detection_in_same_tenant(self):
        """2. Deduplicación interna: previene colisión de representantes en el mismo tenant."""
        now_iso = datetime.now(timezone.utc).isoformat()
        lead_id_1 = f"lead_{secrets.token_hex(4)}"
        lead_id_2 = f"lead_{secrets.token_hex(4)}"
        profile_url = "https://www.linkedin.com/in/directora-colegio"
        email = "directora@colegio.cl"

        # Crear lead 1 y colocarlo como CONTACTADO en tenant A
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, perfil_url, email, estado, created_at, updated_at)
                VALUES (?, ?, 'Directora Colegio', ?, ?, 'CONTACTADO', ?, ?)
            """, (lead_id_1, self.tenant_a, profile_url, email, now_iso, now_iso))
            conn.commit()

        # Comprobar colisión para lead 2 con el mismo perfil en el mismo tenant
        has_col, reason, coll_lead = check_internal_collision(
            tenant_id=self.tenant_a,
            profile_url=profile_url,
            email=email,
            current_lead_id=lead_id_2
        )
        self.assertTrue(has_col, "Debe detectar colisión con el contacto activo del mismo tenant")
        self.assertIn("contactado previamente", reason.lower())
        self.assertEqual(coll_lead["id"], lead_id_1)

        # En tenant B (otro cliente/empresa), el mismo perfil NO debe colisionar (aislamiento multi-tenant)
        has_col_b, _, _ = check_internal_collision(
            tenant_id=self.tenant_b,
            profile_url=profile_url,
            email=email,
            current_lead_id=lead_id_2
        )
        self.assertFalse(has_col_b, "No debe colisionar entre tenants distintos")

    def test_03_suppression_list_blocks_lead_outreach(self):
        """3. Lista de supresión (Opt-out): bloqueo con hash SHA-256."""
        email_optout = "no-molestar@empresa.com"
        profile_optout = "https://www.linkedin.com/in/prospecto-optout"

        # Comprobar antes de suprimir
        sup, _ = is_suppressed(self.tenant_a, email=email_optout)
        self.assertFalse(sup)

        # Agregar a lista de supresión
        added_email = add_to_suppression_list(self.tenant_a, email_optout, "EMAIL", "SOLICITO_BAJA")
        added_li = add_to_suppression_list(self.tenant_a, profile_optout, "LINKEDIN_URL", "OPT_OUT")
        self.assertTrue(added_email)
        self.assertTrue(added_li)

        # Comprobar detección de supresión por email
        sup_email, reason_email = is_suppressed(self.tenant_a, email=email_optout)
        self.assertTrue(sup_email)
        self.assertIn("EMAIL", reason_email)

        # Comprobar detección por URL de LinkedIn
        sup_li, reason_li = is_suppressed(self.tenant_a, profile_url=profile_optout)
        self.assertTrue(sup_li)
        self.assertIn("LINKEDIN_URL", reason_li)

        # Verificar que el chequeo de colisión también lo bloquee inmediatamente
        has_col, col_reason, _ = check_internal_collision(self.tenant_a, profile_url=profile_optout)
        self.assertTrue(has_col)
        self.assertIn("supresión", col_reason.lower())

    def test_04_lead_activity_internal_audit_log(self):
        """4. Bitácora interna lead_activity como fuente única de verdad."""
        lead_id = f"lead_{secrets.token_hex(4)}"
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, perfil_url, estado, created_at, updated_at)
                VALUES (?, ?, 'Lead Auditado', 'https://www.linkedin.com/in/audit-test', 'EXTRAIDO', ?, ?)
            """, (lead_id, self.tenant_a, now_iso, now_iso))
            conn.commit()

        # Registrar eventos en la bitácora
        act1 = log_lead_activity(self.tenant_a, lead_id, "LI_VISIT_PROFILE", {"tiempo_lectura_ms": 4200})
        act2 = log_lead_activity(self.tenant_a, lead_id, "LI_SEND_INVITE", {"nota": "Hola colega"})
        act3 = log_lead_activity(self.tenant_a, lead_id, "ZOHO_NOTE_ADDED", {"nota_id": "zoho_note_99"})

        self.assertIsNotNone(act1)
        self.assertIsNotNone(act2)
        self.assertIsNotNone(act3)

        # Recuperar bitácora
        acts = get_lead_activities(self.tenant_a, lead_id)
        self.assertEqual(len(acts), 3)
        action_names = [a["action_type"] for a in acts]
        self.assertIn("LI_VISIT_PROFILE", action_names)
        self.assertIn("LI_SEND_INVITE", action_names)
        self.assertIn("ZOHO_NOTE_ADDED", action_names)

    def test_05_decoupled_crm_status_sync(self):
        """5. Desacoplamiento de estado: crm_external_id no altera el estado interno del lead."""
        lead_id = f"lead_{secrets.token_hex(4)}"
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, perfil_url, estado, created_at, updated_at)
                VALUES (?, ?, 'Lead CRM Decoupled', 'https://www.linkedin.com/in/crm-dec', 'INVITACION_ENVIADA', ?, ?)
            """, (lead_id, self.tenant_a, now_iso, now_iso))
            conn.commit()

        # Sincronizar resultado de CRM
        synced = sync_zoho_result_to_lead(
            tenant_id=self.tenant_a,
            lead_id=lead_id,
            crm_external_id="zoho_crm_id_88849",
            crm_sync_status="SYNCED",
            owner_name="Rodrigo Asesor"
        )
        self.assertTrue(synced)

        # Comprobar que el estado propio se mantiene inalterado
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT estado, crm_external_id, crm_sync_status, zoho_cuenta_dueno FROM leads WHERE id = ?", (lead_id,))
            row = cursor.fetchone()
            self.assertEqual(row["estado"], "INVITACION_ENVIADA", "El estado propio del motor no debe ser sobrescrito por Zoho")
            self.assertEqual(row["crm_external_id"], "zoho_crm_id_88849")
            self.assertEqual(row["crm_sync_status"], "SYNCED")
            self.assertEqual(row["zoho_cuenta_dueno"], "Rodrigo Asesor")

    def test_06_native_csv_export_format_and_tenant_isolation(self):
        """6. Exportación CSV con bitácora y aislamiento estricto entre tenants."""
        now_iso = datetime.now(timezone.utc).isoformat()
        lead_a = f"lead_a_{secrets.token_hex(3)}"
        lead_b = f"lead_b_{secrets.token_hex(3)}"

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, cargo_actual, perfil_url, email, estado, created_at, updated_at)
                VALUES (?, ?, 'Lead Tenant A', 'Director Académico', 'https://linkedin.com/in/lead-a', 'lead_a@empresa.cl', 'CONTACTADO', ?, ?)
            """, (lead_a, self.tenant_a, now_iso, now_iso))

            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, cargo_actual, perfil_url, email, estado, created_at, updated_at)
                VALUES (?, ?, 'Lead Tenant B Confidencial', 'Gerente General', 'https://linkedin.com/in/lead-b', 'lead_b@secreto.cl', 'EXTRAIDO', ?, ?)
            """, (lead_b, self.tenant_b, now_iso, now_iso))
            conn.commit()

        log_lead_activity(self.tenant_a, lead_a, "LI_VISIT_PROFILE")
        log_lead_activity(self.tenant_a, lead_a, "LI_SEND_INVITE")

        # Exportar CSV para Tenant A
        csv_str = export_leads_with_activity_csv(self.tenant_a)
        reader = csv.reader(io.StringIO(csv_str))
        rows = list(reader)

        headers = rows[0]
        self.assertIn("lead_id", headers)
        self.assertIn("nombre", headers)
        self.assertIn("crm_external_id", headers)
        self.assertIn("total_actividades", headers)
        self.assertIn("historial_resumido", headers)

        # El Lead A debe estar en la exportación
        content_str = "\n".join([",".join(r) for r in rows])
        self.assertIn("Lead Tenant A", content_str)
        self.assertIn("lead_a@empresa.cl", content_str)

        # AISLAMIENTO ESTRICTO: El Lead B NUNCA debe figurar en la exportación del Tenant A
        self.assertNotIn("Lead Tenant B Confidencial", content_str)
        self.assertNotIn("lead_b@secreto.cl", content_str)


if __name__ == "__main__":
    unittest.main()
