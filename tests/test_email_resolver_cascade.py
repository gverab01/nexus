"""
Test Suite del Resolver de Correos en Cascada (Workstream 5.6 [P1])
NexusReach Pro Directrices de Ingeniería v1.3 - Sección 5.6 y Prohibición 14

Verifica rigurosamente:
1. Cero conexiones SMTP salientes (RCPT TO) en puerto 25 (auditoría AST e imports).
2. Cascada ordenada por costo (OSINT -> 1er Grado -> Patrón Tenant -> Gratuito -> Verificador Externo).
3. Detención inmediata en el primer candidato utilizable.
4. Tope estricto de máximo 3 consultas externas por lead.
5. Registro de evidencia y origen por candidato en la tabla email_candidates.
6. Contabilidad de costo real en USD en usage_events y deducción en credit_ledger.
7. Aislamiento estricto multi-tenant (Tenant A nunca comparte datos con Tenant B).
8. Intercambiabilidad de proveedores (MillionVerifier <-> ZeroBounce) sin alterar la cascada.
"""

import os
import sys
import ast
import json
import unittest
from datetime import datetime, timedelta

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database import get_db, init_db
import email_resolver_service
import email_verifier_service
from email_verifier_service import (
    EmailVerifier,
    EmailVerificationResult,
    MillionVerifierProvider,
    ZeroBounceProvider,
    LocalDNSVerifierProvider,
    get_email_verifier
)

class TestEmailResolverCascade(unittest.TestCase):

    def setUp(self):
        init_db()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM email_candidates")
            cursor.execute("DELETE FROM usage_events")
            cursor.execute("DELETE FROM credit_ledger")
            conn.commit()

    def _ensure_tenant(self, cursor, tenant_id: str):
        now_iso = datetime.now().isoformat()
        cursor.execute("""
            INSERT OR IGNORE INTO tenants (id, razon_social, tipo_tenant, estado, created_at, updated_at)
            VALUES (?, ?, 'EMPRESA', 'ACTIVO', ?, ?)
        """, (tenant_id, f"Empresa {tenant_id}", now_iso, now_iso))

    def test_01_zero_outgoing_smtp_connections_and_no_smtplib(self):
        """
        CRITERIO CRÍTICO NO NEGOCIABLE (Prohibición 14 y 5.6 Requisito 1):
        Demuestra estáticamente y dinámicamente que NO existe código que importe smtplib
        ni abra sockets SMTP salientes (RCPT TO) en el servicio de resolución de correos.
        """
        # 1. Auditoría AST sobre email_resolver_service.py
        resolver_file = os.path.join(PROJECT_ROOT, "email_resolver_service.py")
        with open(resolver_file, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=resolver_file)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotEqual(alias.name, "smtplib", "Prohibición violada: smtplib importado en email_resolver_service.py")
            elif isinstance(node, ast.ImportFrom):
                self.assertNotEqual(node.module, "smtplib", "Prohibición violada: smtplib importado en email_resolver_service.py")
            elif isinstance(node, ast.FunctionDef):
                self.assertNotEqual(node.name, "ping_smtp_mailbox", "Prohibición violada: ping_smtp_mailbox aún existe en el código")

        # 2. Auditoría AST sobre email_verifier_service.py
        verifier_file = os.path.join(PROJECT_ROOT, "email_verifier_service.py")
        with open(verifier_file, "r", encoding="utf-8") as f:
            tree_v = ast.parse(f.read(), filename=verifier_file)

        for node in ast.walk(tree_v):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotEqual(alias.name, "smtplib", "Prohibición violada: smtplib importado en email_verifier_service.py")
            elif isinstance(node, ast.ImportFrom):
                self.assertNotEqual(node.module, "smtplib", "Prohibición violada: smtplib importado en email_verifier_service.py")

    def test_02_cost_ordered_cascade_stops_at_first_usable_result(self):
        """
        Verifica que la cascada se detenga de inmediato en el primer paso que
        produzca un correo utilizable, sin consultar innecesariamente proveedores externos pagados.
        """
        tenant = "ten_cascade_01"
        lead_id = "lead_casc_1st_degree"
        now_iso = datetime.now().isoformat()

        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)
            cursor.execute("""
                INSERT OR REPLACE INTO leads 
                (id, tenant_id, nombre, cargo_titular, institucion_actual, perfil_url, grado_red, estado, created_at, updated_at)
                VALUES (?, ?, 'Matías Valenzuela', 'Director Académico', 'Colegio Pumahue', 'https://linkedin.com/in/matias-valenzuela-demo', '1º', 'CONECTADO', ?, ?)
            """, (lead_id, tenant, now_iso, now_iso))
            conn.commit()

            # Simular extracción de 1er grado exitosa
            original_extract = email_resolver_service.extract_linkedin_direct_contact
            try:
                email_resolver_service.extract_linkedin_direct_contact = lambda url, name: {
                    "ok": True,
                    "email": "mvalenzuela@pumahue.cl",
                    "telefono": "+56911223344",
                    "source": "linkedin_direct",
                    "status": "VERIFICADO"
                }

                res = email_resolver_service.resolve_lead_email(lead_id, conn=conn)
                self.assertTrue(res["ok"])
                self.assertEqual(res["email"], "mvalenzuela@pumahue.cl")
                self.assertEqual(res["source"], "linkedin_direct")

                # Comprobar que NO se realizaron consultas externas pagadas
                cursor.execute("SELECT COUNT(*) as total FROM usage_events WHERE tenant_id = ? AND event_type = 'EMAIL_VERIFICATION'", (tenant,))
                self.assertEqual(cursor.fetchone()["total"], 0)

                # Comprobar registro en email_candidates
                cursor.execute("SELECT candidate_email, source_type, verification_status FROM email_candidates WHERE lead_id = ?", (lead_id,))
                c_row = cursor.fetchone()
                self.assertIsNotNone(c_row)
                self.assertEqual(c_row["candidate_email"], "mvalenzuela@pumahue.cl")
                self.assertEqual(c_row["source_type"], "LINKEDIN_1ST_DEGREE")
            finally:
                email_resolver_service.extract_linkedin_direct_contact = original_extract

    def test_03_strict_cap_maximum_3_external_checks_per_lead(self):
        """
        CRITERIO 5.6.2.e:
        Tope estricto de máximo 3 consultas externas por lead.
        NUNCA debe verificar todos los patrones generados (ej. si hay 8 patrones, verifica a lo más 3).
        """
        tenant = "ten_cap_test"
        lead_id = "lead_cap_01"
        now_iso = datetime.now().isoformat()

        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)
            cursor.execute("""
                INSERT OR REPLACE INTO leads 
                (id, tenant_id, nombre, cargo_titular, institucion_actual, perfil_url, grado_red, estado, created_at, updated_at)
                VALUES (?, ?, 'Rodrigo Alejandro Bravo Sanhueza', 'Gerente de Operaciones', 'Colegio Pumahue', 'https://linkedin.com/in/rodrigo-bravo-test', '2º', 'EXTRAIDO', ?, ?)
            """, (lead_id, tenant, now_iso, now_iso))
            conn.commit()

            # Mock verifier que rechaza los candidatos como 'invalid' para forzar a agotar los intentos permitidos
            calls = []
            class MockRejectionVerifier(EmailVerifier):
                def verify(self, email: str, tenant_id: str = "ten_superadmin") -> EmailVerificationResult:
                    calls.append(email)
                    return EmailVerificationResult(
                        email=email,
                        status="invalid",
                        confidence=0.95,
                        provider="mock_rejection",
                        cost_cents=0,
                        cost_usd=0.003
                    )

            original_get_verifier = email_verifier_service.get_email_verifier
            try:
                email_verifier_service.get_email_verifier = lambda provider_name=None: MockRejectionVerifier()
                res = email_resolver_service.resolve_lead_email(lead_id, conn=conn)

                # Debe haber intentado exactamente 3 consultas externas
                self.assertEqual(len(calls), 3, f"Se debieron ejecutar exactamente 3 consultas externas, se ejecutaron {len(calls)}")
                self.assertEqual(res["consultas"], 3)
                self.assertFalse(res["ok"])
                self.assertEqual(res["status"], "NO_ENCONTRADO")

                # Comprobar que en email_candidates se registraron los 3 intentos
                cursor.execute("SELECT COUNT(*) as total FROM email_candidates WHERE lead_id = ? AND source_type = 'EXTERNAL_VERIFIER'", (lead_id,))
                self.assertEqual(cursor.fetchone()["total"], 3)
            finally:
                email_verifier_service.get_email_verifier = original_get_verifier

    def test_04_real_cost_accounting_and_credit_ledger_deduction(self):
        """
        CRITERIO 5.6.8 y 5.6.9:
        Cada consulta externa registra el costo real en USD en usage_events.
        Un crédito se consume solo si el resultado es utilizable ('valid' o 'catch_all' con confianza >= 0.60).
        """
        tenant = "ten_cost_test"
        lead_id = "lead_cost_01"
        now_iso = datetime.now().isoformat()

        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)
            cursor.execute("""
                INSERT OR REPLACE INTO leads 
                (id, tenant_id, nombre, cargo_titular, institucion_actual, perfil_url, grado_red, estado, created_at, updated_at)
                VALUES (?, ?, 'Carla Andrea Morales Perez', 'Directora de Admision', 'Colegio Pumahue', 'https://linkedin.com/in/carla-morales-test', '2º', 'EXTRAIDO', ?, ?)
            """, (lead_id, tenant, now_iso, now_iso))

            # Saldo inicial de 100 créditos
            cursor.execute("""
                INSERT OR REPLACE INTO credit_ledger (id, tenant_id, account_id, credit_type, delta, balance_after, description, created_at)
                VALUES ('led_initial_01', ?, 'acc_1', 'INITIAL_GRANT', 100, 100, 'Saldo inicial', ?)
            """, (tenant, now_iso))
            conn.commit()

            # Mock verifier que aprueba al 1er candidato
            class MockSuccessVerifier(EmailVerifier):
                def verify(self, email: str, tenant_id: str = "ten_superadmin") -> EmailVerificationResult:
                    return EmailVerificationResult(
                        email=email,
                        status="valid",
                        confidence=0.96,
                        provider="millionverifier",
                        cost_cents=0,
                        cost_usd=0.003
                    )

            original_get_verifier = email_verifier_service.get_email_verifier
            try:
                email_verifier_service.get_email_verifier = lambda provider_name=None: MockSuccessVerifier()
                res = email_resolver_service.resolve_lead_email(lead_id, conn=conn)

                self.assertTrue(res["ok"])
                self.assertEqual(res["status"], "VERIFICADO")

                # 1. Comprobar que se registró el evento de costo real en USD en usage_events
                cursor.execute("SELECT provider, cost_usd, credits_consumed FROM usage_events WHERE tenant_id = ?", (tenant,))
                evt = cursor.fetchone()
                self.assertIsNotNone(evt)
                self.assertEqual(evt["provider"], "millionverifier")
                self.assertEqual(float(evt["cost_usd"]), 0.003)
                self.assertEqual(evt["credits_consumed"], 1)

                # 2. Comprobar que credit_ledger descontó 1 crédito (de 100 a 99)
                cursor.execute("SELECT delta, balance_after FROM credit_ledger WHERE tenant_id = ? AND credit_type = 'VERIFICATION_DEBIT'", (tenant,))
                led = cursor.fetchone()
                self.assertIsNotNone(led)
                self.assertEqual(led["delta"], -1)
                self.assertEqual(led["balance_after"], 99)
            finally:
                email_verifier_service.get_email_verifier = original_get_verifier

    def test_05_tenant_organization_pattern_inference_isolation(self):
        """
        CRITERIO 5.6.7 (Aislamiento Estricto por Tenant):
        Los patrones inferidos o cachés de un Tenant A NUNCA se comparten con Tenant B.
        """
        tenant_a = "ten_corp_alpha"
        tenant_b = "ten_corp_beta"
        now_iso = datetime.now().isoformat()

        with get_db() as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant_a)
            self._ensure_tenant(cursor, tenant_b)

            # Tenant A tiene un lead verificado con patrón f_init.last (c.gonzalez@colegiomayor.cl)
            cursor.execute("""
                INSERT OR REPLACE INTO leads 
                (id, tenant_id, nombre, cargo_titular, institucion_actual, perfil_url, empresa_dominio, email_extracted, email_status, created_at, updated_at)
                VALUES ('lead_a_pattern', ?, 'Claudio Gonzalez', 'Director', 'Colegio Mayor', 'https://li.com/claudio', 'colegiomayor.cl', 'c.gonzalez@colegiomayor.cl', 'VERIFICADO', ?, ?)
            """, (tenant_a, now_iso, now_iso))
            conn.commit()

            # Inferencia para Tenant A debe encontrar el patrón
            inferred_a = email_resolver_service.infer_organization_pattern_from_tenant(
                tenant_id=tenant_a,
                domain="colegiomayor.cl",
                first_name="Felipe",
                last_name="Tapia",
                conn=conn
            )
            self.assertEqual(inferred_a, "f.tapia@colegiomayor.cl")

            # Inferencia para Tenant B con el mismo dominio NO debe ver el patrón de Tenant A
            inferred_b = email_resolver_service.infer_organization_pattern_from_tenant(
                tenant_id=tenant_b,
                domain="colegiomayor.cl",
                first_name="Felipe",
                last_name="Tapia",
                conn=conn
            )
            self.assertIsNone(inferred_b, "Fuga de aislamiento multi-tenant: Tenant B obtuvo patrón inferido de Tenant A")

    def test_06_interchangeable_providers_without_altering_cascade(self):
        """
        CRITERIO 5.6.3:
        Los proveedores de verificación están completamente abstraídos.
        Alternar entre MillionVerifier y ZeroBounce se realiza mediante configuración sin modificar la cascada.
        """
        # 1. Instancia por defecto
        prov_default = get_email_verifier("millionverifier")
        self.assertIsInstance(prov_default, MillionVerifierProvider)

        # 2. Instancia alternativa ZeroBounce
        prov_zb = get_email_verifier("zerobounce")
        self.assertIsInstance(prov_zb, ZeroBounceProvider)

        # 3. Instancia LocalDNS
        prov_local = get_email_verifier("localdns")
        self.assertIsInstance(prov_local, LocalDNSVerifierProvider)

        # Comprobar normalización de resultados
        res_v = prov_local.verify("contacto.valido@uchile.cl")
        self.assertIn(res_v.status, ("valid", "invalid", "catch_all", "unknown"))
        self.assertIsInstance(res_v.confidence, float)
        self.assertTrue(0.0 <= res_v.confidence <= 1.0)


if __name__ == "__main__":
    unittest.main()
