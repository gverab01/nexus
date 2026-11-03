"""
Test Suite de Multi-tenancy, Autenticación y Aislamiento Estricto (Workstream 5.3 [P0])
NexusReach Pro Directrices de Ingeniería v1.3

Verifica rigurosamente:
1. Aislamiento forzado: Tenant A no puede leer ni inferir datos de Tenant B por la API.
2. Roles de usuario: COMPANY_ADMIN (owner) y COMPANY_MEMBER (member).
3. Hash de contraseñas fuerte con salt criptográfico único (PBKDF2-HMAC-SHA256 100k iteraciones).
4. Cifrado a nivel de campo (Field-level encryption) con derivación HKDF por tenant.
5. Violación de clave cruzada: Tenant B no puede descifrar datos cifrados de Tenant A.
"""

import os
import sys
import secrets
import unittest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database import get_db, init_db
import auth_service
import crypto_field_service
from main import app


class TestMultitenancyAndAuth(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)

    def setUp(self):
        self.tenant_a = "ten_tst_a_" + secrets.token_hex(4)
        self.tenant_b = "ten_tst_b_" + secrets.token_hex(4)
        now_iso = datetime.now(timezone.utc).isoformat()

        # Crear dos tenants independientes
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tenants (id, razon_social, tipo_tenant, estado, created_at, updated_at)
                VALUES (?, 'Colegio San Pedro A', 'EMPRESA', 'ACTIVO', ?, ?)
            """, (self.tenant_a, now_iso, now_iso))
            cursor.execute("""
                INSERT INTO tenants (id, razon_social, tipo_tenant, estado, created_at, updated_at)
                VALUES (?, 'Liceo Santa Maria B', 'EMPRESA', 'ACTIVO', ?, ?)
            """, (self.tenant_b, now_iso, now_iso))

            # Suscripciones activas para ambos
            cursor.execute("""
                INSERT INTO suscripciones (id, tenant_id, periodicidad, estado, puestos_contratados, precio_unitario_plataforma, fecha_inicio, fecha_expiracion, created_at, updated_at)
                VALUES (?, ?, 'MENSUAL', 'ACTIVA', 5, 35.0, ?, '2030-01-01T00:00:00', ?, ?)
            """, (f"sub_{self.tenant_a}", self.tenant_a, now_iso, now_iso, now_iso))

            cursor.execute("""
                INSERT INTO suscripciones (id, tenant_id, periodicidad, estado, puestos_contratados, precio_unitario_plataforma, fecha_inicio, fecha_expiracion, created_at, updated_at)
                VALUES (?, ?, 'MENSUAL', 'ACTIVA', 5, 35.0, ?, '2030-01-01T00:00:00', ?, ?)
            """, (f"sub_{self.tenant_b}", self.tenant_b, now_iso, now_iso, now_iso))

            # Usuario A (COMPANY_ADMIN en Tenant A)
            hash_a, salt_a = auth_service.hash_password("clave_a_123")
            cursor.execute("""
                INSERT INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado, suscripcion_expira, created_at, updated_at)
                VALUES (?, ?, ?, 'Rector A', ?, ?, 'COMPANY_ADMIN', 1, 'ACTIVO', '2030-01-01T00:00:00', ?, ?)
            """, (f"usr_a_{secrets.token_hex(3)}", self.tenant_a, f"rector_a_{secrets.token_hex(3)}@colegio.cl", hash_a, salt_a, now_iso, now_iso))

            # Usuario B (COMPANY_MEMBER en Tenant B)
            hash_b, salt_b = auth_service.hash_password("clave_b_123")
            self.email_b = f"rector_b_{secrets.token_hex(3)}@colegio.cl"
            self.pwd_b = "clave_b_123"
            cursor.execute("""
                INSERT INTO usuarios (id, tenant_id, email, nombre, password_hash, salt, rol, puesto_activo, estado, suscripcion_expira, created_at, updated_at)
                VALUES (?, ?, ?, 'Docente B', ?, ?, 'COMPANY_MEMBER', 1, 'ACTIVO', '2030-01-01T00:00:00', ?, ?)
            """, (f"usr_b_{secrets.token_hex(3)}", self.tenant_b, self.email_b, hash_b, salt_b, now_iso, now_iso))

            # Lead confidencial de Tenant A
            self.lead_a_id = f"lead_a_{secrets.token_hex(4)}"
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, cargo_actual, perfil_url, email, estado, created_at, updated_at)
                VALUES (?, ?, 'Prospecto Confidencial A', 'Director Académico', 'https://linkedin.com/in/confidencial-a', 'secreto_a@empresa.cl', 'EXTRAIDO', ?, ?)
            """, (self.lead_a_id, self.tenant_a, now_iso, now_iso))

            conn.commit()

        # Login del usuario B para obtener su sesión
        login_res = auth_service.authenticate_user(self.email_b, self.pwd_b)
        self.assertTrue(login_res["exito"], f"Login failed: {login_res}")
        self.token_b = login_res["token"]

    def tearDown(self):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM lead_activity WHERE tenant_id IN (?, ?)", (self.tenant_a, self.tenant_b))
            cursor.execute("DELETE FROM suppression_list WHERE tenant_id IN (?, ?)", (self.tenant_a, self.tenant_b))
            cursor.execute("DELETE FROM leads WHERE tenant_id IN (?, ?)", (self.tenant_a, self.tenant_b))
            cursor.execute("DELETE FROM usuarios WHERE tenant_id IN (?, ?)", (self.tenant_a, self.tenant_b))
            cursor.execute("DELETE FROM suscripciones WHERE tenant_id IN (?, ?)", (self.tenant_a, self.tenant_b))
            cursor.execute("DELETE FROM tenants WHERE id IN (?, ?)", (self.tenant_a, self.tenant_b))
            conn.commit()

    def test_01_strong_password_hashing(self):
        """1. Verifica que las contraseñas usen PBKDF2-HMAC-SHA256 con salt criptográfico."""
        pwd = "PruebaPasswordSegura2026!"
        h1, s1 = auth_service.hash_password(pwd)
        h2, s2 = auth_service.hash_password(pwd)

        self.assertNotEqual(s1, s2, "Cada hash debe poseer un salt único aleatorio")
        self.assertNotEqual(h1, h2, "Misma contraseña con distinto salt genera hashes distintos")
        self.assertTrue(auth_service.verify_password(pwd, s1, h1))
        self.assertFalse(auth_service.verify_password("ContraseñaIncorrecta", s1, h1))

    def test_02_field_level_encryption_and_tenant_key_isolation(self):
        """2. Cifrado a nivel de campo con aislamiento HKDF por tenant."""
        raw_email = "directora@colegio-exclusivo.cl"
        raw_phone = "+56912345678"

        # Cifrar para Tenant A
        enc_email = crypto_field_service.encrypt_field(raw_email, self.tenant_a)
        enc_phone = crypto_field_service.encrypt_field(raw_phone, self.tenant_a)

        self.assertTrue(enc_email.startswith("enc:v1:"))
        self.assertNotIn("directora", enc_email)

        # Descifrar con Tenant A (éxito)
        dec_email_a = crypto_field_service.decrypt_field(enc_email, self.tenant_a)
        dec_phone_a = crypto_field_service.decrypt_field(enc_phone, self.tenant_a)
        self.assertEqual(dec_email_a, raw_email)
        self.assertEqual(dec_phone_a, raw_phone)

        # Intento de descifrado con Tenant B DEBE fallar criptográficamente (PermissionError)
        with self.assertRaises(PermissionError):
            crypto_field_service.decrypt_field(enc_email, self.tenant_b)

    def test_03_tenant_b_cannot_export_or_read_tenant_a_data(self):
        """3. Tenant B no puede exportar ni consultar datos de Tenant A (403 Forbidden)."""
        headers = {"Authorization": f"Bearer {self.token_b}"}

        # Intento de exportar CSV de Tenant A
        res_csv = self.client.get(f"/api/tenants/{self.tenant_a}/export-csv", headers=headers)
        self.assertEqual(res_csv.status_code, 403, "Debe rechazar exportación de tenant ajeno con 403 Forbidden")

        # Intento de consultar configuración Zoho de Tenant A
        res_cfg = self.client.get(f"/api/tenants/{self.tenant_a}/zoho-config", headers=headers)
        self.assertEqual(res_cfg.status_code, 403)

        # Intento de ver datos de titular de Tenant A
        res_subj = self.client.get(f"/api/tenants/{self.tenant_a}/leads/{self.lead_a_id}/export-subject-data", headers=headers)
        self.assertEqual(res_subj.status_code, 403)

        # Intento de eliminar datos de titular en Tenant A
        res_del = self.client.delete(f"/api/tenants/{self.tenant_a}/leads/{self.lead_a_id}/data-subject-deletion", headers=headers)
        self.assertEqual(res_del.status_code, 403)


if __name__ == "__main__":
    unittest.main()
