"""
Test Suite de Datos Personales, Cumplimiento y Retención (Ley 21.719 Chile)
NexusReach Pro Directrices de Ingeniería v1.3 - Workstream 5.4 [P0]

Verifica rigurosamente:
1. Registro de origen y base de licitud formal (source, source_url, legal_basis, collected_at).
2. Procesamiento de Opt-out: cancelación de secuencias, estado OPT_OUT y hash SHA-256 en suppression_list.
3. Retención configurable: purga automática de leads inactivos tras 12 meses.
4. Borrado de tenant en cascada (<=30 días tras cancelación): vaciado completo sin registros huérfanos.
5. Ejercicio de derechos del titular (ARCO):
   - Acceso: exportación integral de perfil y bitácora.
   - Supresión / Olvido: borrado definitivo y adición a lista de supresión para evitar re-prospección.
"""

import os
import sys
import secrets
import unittest
from datetime import datetime, timezone, timedelta

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database import get_db, init_db
import privacy_compliance_service
from privacy_compliance_service import (
    register_lead_legal_basis,
    process_opt_out,
    purge_inactive_leads,
    delete_tenant_cascade,
    export_data_subject_profile,
    delete_data_subject_profile
)
import zoho_bridge_service


class TestDataPrivacyCompliance(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.tenant_id = "ten_priv_" + secrets.token_hex(4)
        now_iso = datetime.now(timezone.utc).isoformat()

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tenants (id, razon_social, tipo_tenant, estado, created_at, updated_at)
                VALUES (?, 'Colegio Privacidad SpA', 'EMPRESA', 'ACTIVO', ?, ?)
            """, (self.tenant_id, now_iso, now_iso))

            cursor.execute("""
                INSERT INTO suscripciones (id, tenant_id, periodicidad, estado, puestos_contratados, precio_unitario_plataforma, fecha_inicio, fecha_expiracion, created_at, updated_at)
                VALUES (?, ?, 'MENSUAL', 'ACTIVA', 3, 35.0, ?, '2030-01-01T00:00:00', ?, ?)
            """, (f"sub_{self.tenant_id}", self.tenant_id, now_iso, now_iso, now_iso))

            conn.commit()

    def tearDown(self):
        # Asegurar limpieza completa si el test no ejecutó delete_tenant_cascade
        delete_tenant_cascade(self.tenant_id)

    def test_01_legal_basis_and_provenance_registration(self):
        """1. Registro formal de origen, URL de evidencia y base de licitud por lead."""
        now_iso = datetime.now(timezone.utc).isoformat()
        lead_id = f"lead_{secrets.token_hex(4)}"

        with get_db(tenant_id=self.tenant_id) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, perfil_url, email, estado, created_at, updated_at)
                VALUES (?, ?, 'Vicerrector Académico', 'https://linkedin.com/in/vicerrector', 'vicerrector@universidad.cl', 'EXTRAIDO', ?, ?)
            """, (lead_id, self.tenant_id, now_iso, now_iso))
            conn.commit()

        # Registrar base de licitud conforme a Ley 21.719
        success = register_lead_legal_basis(
            tenant_id=self.tenant_id,
            lead_id=lead_id,
            source="LINKEDIN_SALES_NAVIGATOR",
            source_url="https://linkedin.com/in/vicerrector",
            legal_basis="INTERES_LEGITIMO_B2B",
            evidence_text="Directivo con cargo público en directorio institucional B2B."
        )
        self.assertTrue(success)

        # Verificar que la base de licitud y origen se registraron en el lead
        with get_db(tenant_id=self.tenant_id) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT source, source_url, legal_basis, collected_at FROM leads WHERE id = ?", (lead_id,))
            row = cursor.fetchone()
            self.assertEqual(row["source"], "LINKEDIN_SALES_NAVIGATOR")
            self.assertEqual(row["legal_basis"], "INTERES_LEGITIMO_B2B")
            self.assertIsNotNone(row["collected_at"])

            # Verificar inserción en tabla consent_records
            cursor.execute("SELECT * FROM consent_records WHERE lead_id = ?", (lead_id,))
            con_row = cursor.fetchone()
            self.assertIsNotNone(con_row)
            self.assertEqual(con_row["legal_basis"], "INTERES_LEGITIMO_B2B")

    def test_02_opt_out_cancels_sequence_and_suppresses_identifier(self):
        """2. El procesamiento de Opt-out cancela secuencias activas y añade hash SHA-256."""
        now_iso = datetime.now(timezone.utc).isoformat()
        lead_id = f"lead_{secrets.token_hex(4)}"
        sec_id = f"sec_{secrets.token_hex(4)}"
        email_optout = "baja-inmediata@empresa.cl"

        with get_db(tenant_id=self.tenant_id) as conn:
            cursor = conn.cursor()
            # Crear lead
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, perfil_url, email, estado, created_at, updated_at)
                VALUES (?, ?, 'Prospecto Desistente', 'https://linkedin.com/in/desistente', ?, 'EN_SECUENCIA', ?, ?)
            """, (lead_id, self.tenant_id, email_optout, now_iso, now_iso))

            # Crear secuencia y asignación
            cursor.execute("""
                INSERT INTO secuencias (id, tenant_id, nombre, created_at, updated_at)
                VALUES (?, ?, 'Secuencia Outreach Colegios', ?, ?)
            """, (sec_id, self.tenant_id, now_iso, now_iso))

            cursor.execute("""
                INSERT INTO leads_en_secuencia (id, lead_id, secuencia_id, estado, created_at, updated_at)
                VALUES (?, ?, ?, 'EN_CURSO', ?, ?)
            """, (f"les_{secrets.token_hex(4)}", lead_id, sec_id, now_iso, now_iso))
            conn.commit()

        # Procesar Opt-out
        res = process_opt_out(self.tenant_id, identifier=email_optout, identifier_type="EMAIL", reason="SOLICITO_BAJA")
        self.assertTrue(res["ok"])
        self.assertEqual(res["leads_affected"], 1)
        self.assertEqual(res["sequences_stopped"], 1)

        # Verificar que el lead está marcado como OPT_OUT
        with get_db(tenant_id=self.tenant_id) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT estado FROM leads WHERE id = ?", (lead_id,))
            self.assertEqual(cursor.fetchone()["estado"], "OPT_OUT")

            # Verificar que la secuencia pasó a CANCELADO
            cursor.execute("SELECT estado FROM leads_en_secuencia WHERE lead_id = ?", (lead_id,))
            self.assertEqual(cursor.fetchone()["estado"], "CANCELADO")

        # Verificar que el hash existe en suppression_list
        sup, reason = zoho_bridge_service.is_suppressed(self.tenant_id, email=email_optout)
        self.assertTrue(sup, "Debe ser detectado en lista de supresión")
        self.assertIn("SOLICITO_BAJA", reason)

    def test_03_purge_inactive_leads_older_than_12_months(self):
        """3. Purga periódica de leads sin actividad ni actualización tras 12 meses."""
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        old_14_months_iso = (now_dt - timedelta(days=14 * 30)).isoformat()

        lead_active = f"lead_act_{secrets.token_hex(3)}"
        lead_old = f"lead_old_{secrets.token_hex(3)}"

        with get_db(tenant_id=self.tenant_id) as conn:
            cursor = conn.cursor()
            # Lead reciente (activo)
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, perfil_url, email, estado, created_at, updated_at)
                VALUES (?, ?, 'Lead Reciente', 'https://linkedin.com/in/reciente', 'reciente@colegio.cl', 'EXTRAIDO', ?, ?)
            """, (lead_active, self.tenant_id, now_iso, now_iso))

            # Lead antiguo (>12 meses)
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, perfil_url, email, estado, created_at, updated_at)
                VALUES (?, ?, 'Lead Antiguo Inactivo', 'https://linkedin.com/in/antiguo', 'antiguo@colegio.cl', 'EXTRAIDO', ?, ?)
            """, (lead_old, self.tenant_id, old_14_months_iso, old_14_months_iso))
            conn.commit()

        # Ejecutar purga de inactivos
        purged = purge_inactive_leads(self.tenant_id, months=12)
        self.assertEqual(purged, 1, "Debe purgar exactamente el lead inactivo > 12 meses")

        # Verificar en base de datos
        with get_db(tenant_id=self.tenant_id) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM leads WHERE id = ?", (lead_old,))
            self.assertIsNone(cursor.fetchone(), "El lead antiguo debe haber sido eliminado")

            cursor.execute("SELECT id FROM leads WHERE id = ?", (lead_active,))
            self.assertIsNotNone(cursor.fetchone(), "El lead reciente debe conservarse intacto")

    def test_04_data_subject_rights_export_and_forget(self):
        """4. Ejercicio de Derechos ARCO: Exportación integral y derecho al olvido."""
        now_iso = datetime.now(timezone.utc).isoformat()
        lead_id = f"lead_arco_{secrets.token_hex(3)}"
        email_arco = "titular-arco@colegio.cl"
        url_arco = "https://linkedin.com/in/titular-arco"

        with get_db(tenant_id=self.tenant_id) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, perfil_url, email, estado, created_at, updated_at)
                VALUES (?, ?, 'Titular ARCO', ?, ?, 'EXTRAIDO', ?, ?)
            """, (lead_id, self.tenant_id, url_arco, email_arco, now_iso, now_iso))
            conn.commit()

        register_lead_legal_basis(self.tenant_id, lead_id, source="LINKEDIN", legal_basis="CONSENTIMIENTO_EXPRESO")
        zoho_bridge_service.log_lead_activity(self.tenant_id, lead_id, "PERFIL_CONSULTADO")

        # 1. Derecho de Acceso / Exportación
        profile = export_data_subject_profile(self.tenant_id, lead_id)
        self.assertIsNotNone(profile)
        self.assertEqual(profile["lead"]["id"], lead_id)
        self.assertEqual(len(profile["base_licitud"]), 1)
        self.assertEqual(profile["base_licitud"][0]["legal_basis"], "CONSENTIMIENTO_EXPRESO")
        self.assertEqual(len(profile["actividades"]), 2)  # LEGAL_BASIS_REGISTERED + PERFIL_CONSULTADO

        # 2. Derecho de Supresión / Olvido
        deleted = delete_data_subject_profile(self.tenant_id, lead_id, reason="EJERCICIO_DERECHO_AL_OLVIDO")
        self.assertTrue(deleted)

        # El lead ya no debe existir
        with get_db(tenant_id=self.tenant_id) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM leads WHERE id = ?", (lead_id,))
            self.assertIsNone(cursor.fetchone())

        # Sus identificadores quedan bloqueados permanentemente en suppression_list
        sup_email, _ = zoho_bridge_service.is_suppressed(self.tenant_id, email=email_arco)
        sup_url, _ = zoho_bridge_service.is_suppressed(self.tenant_id, profile_url=url_arco)
        self.assertTrue(sup_email, "El email del titular al olvido queda suprimido")
        self.assertTrue(sup_url, "La URL del titular al olvido queda suprimida")

    def test_05_cascade_tenant_deletion(self):
        """5. Borrado completo de tenant en cascada sin dejar registros huérfanos."""
        now_iso = datetime.now(timezone.utc).isoformat()
        lead_id = f"lead_cas_{secrets.token_hex(3)}"

        with get_db(tenant_id=self.tenant_id) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, perfil_url, email, estado, created_at, updated_at)
                VALUES (?, ?, 'Lead Cascada', 'https://linkedin.com/in/cascada', 'cascada@colegio.cl', 'EXTRAIDO', ?, ?)
            """, (lead_id, self.tenant_id, now_iso, now_iso))
            conn.commit()

        zoho_bridge_service.log_lead_activity(self.tenant_id, lead_id, "TEST_ACTIVITY")

        # Ejecutar borrado en cascada del tenant
        counts = delete_tenant_cascade(self.tenant_id)
        self.assertGreaterEqual(counts.get("tenants", 0), 1)
        self.assertGreaterEqual(counts.get("leads", 0), 1)
        self.assertGreaterEqual(counts.get("lead_activity", 0), 1)

        # Verificar que el tenant y todas sus entidades no existen en absoluto
        with get_db(is_super_admin=True) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM tenants WHERE id = ?", (self.tenant_id,))
            self.assertIsNone(cursor.fetchone())
            cursor.execute("SELECT id FROM leads WHERE tenant_id = ?", (self.tenant_id,))
            self.assertEqual(len(cursor.fetchall()), 0)
            cursor.execute("SELECT id FROM lead_activity WHERE tenant_id = ?", (self.tenant_id,))
            self.assertEqual(len(cursor.fetchall()), 0)


if __name__ == "__main__":
    unittest.main()
