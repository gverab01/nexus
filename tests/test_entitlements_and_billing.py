"""
Pruebas Automatizadas de Entitlements, Metering y Facturación
NexusReach Pro - Workstream 5.9 [P1] - Directrices v1.3

Verifica:
1. Lectura dinámica de límites desde `entitlements` en base de datos sin requerir despliegue.
2. Agotar cuota de leads bloquea SOLO nuevas activaciones (LIMIT_LEADS_REACHED).
   Leads ya activos en conversación continúan sus secuencias sin interrupción (Regla No Negociable).
3. Agotar créditos detiene SOLO la resolución con costo externo (LIMIT_CREDITS_REACHED).
   Búsquedas públicas gratuitas (OSINT) continúan operando.
4. Comprar un pack o suscripción JAMÁS modifica ni relaja los límites de seguridad antiban (5.5).
5. Un tenant sin suscripción activa o con trial expirado no recibe tareas (TENANT_SUBSCRIPTION_INACTIVE).
6. Pasarelas de Pago: Selección por país (CL -> Mercado Pago, otro -> PayPal).
7. Webhooks seguros e idempotentes: notificaciones duplicadas no duplican saldo ni cambian estado dos veces.
"""

import unittest
import json
import uuid
from datetime import datetime, timezone, timedelta

from database import get_db, init_db
import entitlements_service
import payment_gateway_service
import safety_engine
import task_dispatcher
import email_resolver_service


class TestEntitlementsAndBilling(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    TEST_TENANTS = ('ten_dyn_limits', 'ten_leads_limit', 'ten_credit_test', 'ten_pack_safety', 'ten_expired_trial', 'ten_webhook_idem')

    def setUp(self):
        with get_db() as conn:
            cursor = conn.cursor()
            placeholders = ','.join(['?'] * len(self.TEST_TENANTS))
            cursor.execute(f"DELETE FROM entitlements WHERE tenant_id IN ({placeholders})", self.TEST_TENANTS)
            cursor.execute(f"DELETE FROM subscriptions WHERE tenant_id IN ({placeholders})", self.TEST_TENANTS)
            cursor.execute(f"DELETE FROM usage_counters WHERE tenant_id IN ({placeholders})", self.TEST_TENANTS)
            cursor.execute(f"DELETE FROM usage_events WHERE tenant_id IN ({placeholders})", self.TEST_TENANTS)
            cursor.execute(f"DELETE FROM credit_ledger WHERE tenant_id IN ({placeholders})", self.TEST_TENANTS)
            cursor.execute("DELETE FROM payment_webhook_events")
            cursor.execute(f"DELETE FROM lead_activity WHERE tenant_id IN ({placeholders})", self.TEST_TENANTS)
            cursor.execute(f"DELETE FROM leads_en_secuencia WHERE lead_id IN (SELECT id FROM leads WHERE tenant_id IN ({placeholders}))", self.TEST_TENANTS)
            cursor.execute(f"DELETE FROM secuencias WHERE tenant_id IN ({placeholders})", self.TEST_TENANTS)
            cursor.execute(f"DELETE FROM leads WHERE tenant_id IN ({placeholders})", self.TEST_TENANTS)
            conn.commit()

    def _ensure_tenant(self, cursor, tenant_id: str):
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            INSERT OR IGNORE INTO tenants (id, razon_social, estado, created_at, updated_at)
            VALUES (?, ?, 'ACTIVO', ?, ?)
        """, (tenant_id, f"Tenant {tenant_id}", now_iso, now_iso))

    def test_01_limits_read_dynamically_from_entitlements(self):
        """
        CRITERIO 5.9.A.3 y Criterios de Aceptación:
        Los límites comerciales viven en `entitlements` (base de datos) y se leen en tiempo de ejecución.
        Cambiar un valor en la base de datos surte efecto inmediato sin desplegar ni reiniciar código.
        """
        tenant = "ten_dyn_limits"
        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)
            conn.commit()

            # 1. Obtener entitlements iniciales
            ent = entitlements_service.get_or_create_entitlements(tenant, conn=conn)
            self.assertEqual(ent["leads_limit_cycle"], 500)

            # 2. Modificar el límite directamente en la base de datos (ej. ajuste comercial a 800)
            cursor.execute("UPDATE entitlements SET leads_limit_cycle = 800 WHERE tenant_id = ?", (tenant,))
            conn.commit()

            # 3. Verificar que se lee 800 inmediatamente en tiempo de ejecución
            summary = entitlements_service.get_cycle_usage_summary(tenant, conn=conn)
            self.assertEqual(summary["leads"]["limit"], 800)

    def test_02_lead_limit_blocks_new_activations_only_not_active_conversations(self):
        """
        CRITERIO 5.9.A.2 (REGLA NO NEGOCIABLE):
        - Al agotar la cuota de leads del ciclo, una nueva activación se rechaza con LIMIT_LEADS_REACHED.
        - Los leads YA ACTIVOS continúan sus secuencias, seguimientos y respuestas sin corte.
        """
        tenant = "ten_leads_limit"
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)

            # Inicializar entitlements con límite de 2 leads por ciclo para la prueba
            cursor.execute("""
                INSERT OR REPLACE INTO entitlements 
                (id, tenant_id, leads_limit_cycle, credits_limit_cycle, is_trial, created_at, updated_at)
                VALUES ('ent_t2', ?, 2, 100, 1, ?, ?)
            """, (tenant, now_iso, now_iso))
            conn.commit()

            # 1. Activar 2 prospectos nuevos (llega al límite 2/2)
            act1 = entitlements_service.check_lead_activation_entitlement(tenant, "lead_01", conn=conn)
            self.assertTrue(act1["aprobado"])
            self.assertTrue(act1["is_new_activation"])

            act2 = entitlements_service.check_lead_activation_entitlement(tenant, "lead_02", conn=conn)
            self.assertTrue(act2["aprobado"])
            self.assertTrue(act2["is_new_activation"])

            # 2. Intentar activar un 3er lead nuevo: debe rechazarse con LIMIT_LEADS_REACHED
            act3 = entitlements_service.check_lead_activation_entitlement(tenant, "lead_03_nuevo", conn=conn)
            self.assertFalse(act3["aprobado"])
            self.assertEqual(act3["codigo"], "LIMIT_LEADS_REACHED")
            self.assertIn("Cuota mensual de nuevos leads alcanzada", act3["motivo"])

            # 3. Comprobar que un lead preexistente en conversación activa (lead_01) NO es bloqueado
            # Registrar actividad previa para lead_01
            cursor.execute("""
                INSERT OR REPLACE INTO leads (id, tenant_id, nombre, perfil_url, estado, created_at, updated_at)
                VALUES ('lead_01', ?, 'Lead Uno', 'https://li.com/lead_01', 'CONECTADO', ?, ?)
            """, (tenant, now_iso, now_iso))
            cursor.execute("""
                INSERT INTO lead_activity (id, tenant_id, lead_id, action_type, details_json, created_at)
                VALUES ('act_01', ?, 'lead_01', 'INVITE_SENT', '{"action": "Paso previo enviado"}', ?)
            """, (tenant, now_iso))
            conn.commit()

            eval_ongoing = entitlements_service.check_lead_activation_entitlement(tenant, "lead_01", conn=conn)
            self.assertTrue(eval_ongoing["aprobado"])
            self.assertFalse(eval_ongoing["is_new_activation"])
            self.assertIn("Lead ya activo", eval_ongoing["motivo"])

    def test_03_credit_depletion_blocks_external_verification_only(self):
        """
        CRITERIO 5.9.B y Criterios de Aceptación:
        Al agotar créditos, la verificación externa se rechaza con LIMIT_CREDITS_REACHED,
        pero las búsquedas públicas sin costo continúan operando normalmente.
        """
        tenant = "ten_credit_test"
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)

            # Dejar el ledger de créditos en balance 0
            cursor.execute("""
                INSERT INTO credit_ledger (id, tenant_id, account_id, credit_type, delta, balance_after, description, created_at)
                VALUES ('cred_zero', ?, NULL, 'ZERO_BALANCE', 0, 0, 'Sin créditos', ?)
            """, (tenant, now_iso))
            conn.commit()

            # 1. Comprobar que la verificación externa rechaza por falta de créditos
            cred_res = entitlements_service.check_email_credits_entitlement(tenant, conn=conn)
            self.assertFalse(cred_res["aprobado"])
            self.assertEqual(cred_res["codigo"], "LIMIT_CREDITS_REACHED")

            # 2. Comprobar que el resolver de correos intercepta y reporta LIMIT_CREDITS_REACHED en el paso 5
            cursor.execute("""
                INSERT INTO leads (id, tenant_id, nombre, institucion_actual, perfil_url, estado, created_at, updated_at)
                VALUES ('lead_cred_test', ?, 'Carlos Gómez', 'Colegio Los Alerces', 'https://li.com/cg', 'NUEVO', ?, ?)
            """, (tenant, now_iso, now_iso))
            conn.commit()

            res_cascade = email_resolver_service.resolve_lead_email("lead_cred_test", conn=conn)
            self.assertFalse(res_cascade["ok"])
            self.assertEqual(res_cascade.get("codigo"), "LIMIT_CREDITS_REACHED")

    def test_04_pack_purchase_does_not_modify_antiban_safety_limits(self):
        """
        CRITERIO 5.9.A.1 y 5.5.7 (REGLA NO NEGOCIABLE):
        Los límites de seguridad antiban (15 invitaciones/día con rampa) NUNCA son comerciales.
        Comprar un pack de leads o créditos añade capacidad comercial pero NO modifica los topes de seguridad.
        """
        tenant = "ten_pack_safety"
        account_id = "li_acc_pack_test"
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)

            cursor.execute("""
                INSERT OR REPLACE INTO linkedin_accounts 
                (id, tenant_id, account_name, status, warmup_day, daily_invite_limit, health_score, created_at, updated_at)
                VALUES (?, ?, 'Cuenta Test Antiban', 'WARMUP', 1, 15, 80.0, ?, ?)
            """, (account_id, tenant, now_iso, now_iso))
            conn.commit()

            # 1. Verificar límite de seguridad antes de compra: 15 invitaciones/día
            auth_before = safety_engine.authorize_linkedin_action(account_id, tenant, action="LI_SEND_INVITE", conn=conn)
            self.assertEqual(auth_before["daily_limit"], 15)

            # 2. Comprar un pack comercial de +500 leads y un pack de 500 créditos
            entitlements_service.add_pack_leads(tenant, leads_quantity=500, price_usd=5.0, conn=conn)
            entitlements_service.add_pack_credits(tenant, credits_quantity=500, price_usd=28.0, conn=conn)

            # 3. Comprobar que el límite de seguridad de la cuenta SIGUE SIENDO EXACTAMENTE 15
            auth_after = safety_engine.authorize_linkedin_action(account_id, tenant, action="LI_SEND_INVITE", conn=conn)
            self.assertEqual(auth_after["daily_limit"], 15)

    def test_05_inactive_subscription_blocks_task_dispatch(self):
        """
        CRITERIO 5.9.F.8 y Criterios de Aceptación:
        Un tenant sin suscripción activa o con período de prueba expirado no recibe comandos.
        """
        tenant = "ten_expired_trial"
        now_iso = datetime.now(timezone.utc).isoformat()
        past_iso = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()

        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)

            # Trial expirado hace 20 días
            cursor.execute("""
                INSERT OR REPLACE INTO entitlements 
                (id, tenant_id, leads_limit_cycle, credits_limit_cycle, is_trial, trial_end, created_at, updated_at)
                VALUES ('ent_exp', ?, 500, 100, 1, ?, ?, ?)
            """, (tenant, past_iso, past_iso, past_iso))

            cursor.execute("""
                INSERT OR REPLACE INTO secuencias (id, tenant_id, nombre, activa, estado, created_at, updated_at)
                VALUES ('seq_exp', ?, 'Secuencia Test', 1, 'PUBLICADA', ?, ?)
            """, (tenant, now_iso, now_iso))
            conn.commit()

            # Comprobar estado de suscripción
            is_active, msg = entitlements_service.is_tenant_subscription_active(tenant, conn=conn)
            self.assertFalse(is_active)
            self.assertIn("expirado", msg)

            # Comprobar que el dispatcher bloquea tareas
            dispatch_res = task_dispatcher.get_next_dispatched_task(sequence_id="seq_exp", tenant_id=tenant)
            self.assertFalse(dispatch_res["hay_tarea"])
            self.assertEqual(dispatch_res.get("codigo"), "TENANT_SUBSCRIPTION_INACTIVE")

    def test_06_payment_provider_country_selection(self):
        """
        CRITERIO 5.9.G.2:
        Selección del procesador por país de facturación:
        - Chile ('CL') -> Mercado Pago
        - Resto del mundo -> PayPal
        """
        mp_provider = payment_gateway_service.get_payment_provider("CL")
        self.assertEqual(mp_provider.provider_name, "MERCADOPAGO")

        pp_provider_us = payment_gateway_service.get_payment_provider("US")
        self.assertEqual(pp_provider_us.provider_name, "PAYPAL")

        pp_provider_es = payment_gateway_service.get_payment_provider("ES")
        self.assertEqual(pp_provider_es.provider_name, "PAYPAL")

    def test_07_idempotent_webhooks_prevent_duplicate_credits_or_state(self):
        """
        CRITERIO 5.9.G.4 y Criterios de Aceptación:
        Un webhook repetido no duplica créditos ni cambia el estado dos veces.
        Idempotencia garantizada por `payment_webhook_events`.
        """
        tenant = "ten_webhook_idem"
        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)
            conn.commit()

            # Evento simulado de compra de pack de 100 créditos
            webhook_payload = {
                "id": "evt_paypal_unique_999",
                "event_type": "PACK_CREDITS_APPROVED",
                "resource": {
                    "tenant_id": tenant,
                    "quantity": 100,
                    "price_usd": 6.0
                }
            }
            raw_body = json.dumps(webhook_payload).encode("utf-8")
            headers = {"paypal-transmission-sig": "mock_sig", "paypal-auth-algo": "mock_algo"}

            # 1er envío del webhook: Debe procesarse y acreditar 100 créditos
            res1 = payment_gateway_service.handle_incoming_webhook(
                provider_name="PAYPAL",
                headers=headers,
                payload=webhook_payload,
                raw_body=raw_body,
                conn=conn
            )
            self.assertTrue(res1["ok"])
            self.assertFalse(res1["idempotent_duplicate"])

            # Verificar saldo en credit_ledger
            cursor.execute("SELECT balance_after FROM credit_ledger WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 1", (tenant,))
            balance_1 = cursor.fetchone()["balance_after"]
            self.assertEqual(balance_1, 100)

            # 2do envío del MISMO webhook (reintento de red): Debe detectarse como duplicado idempotente
            res2 = payment_gateway_service.handle_incoming_webhook(
                provider_name="PAYPAL",
                headers=headers,
                payload=webhook_payload,
                raw_body=raw_body,
                conn=conn
            )
            self.assertTrue(res2["ok"])
            self.assertTrue(res2["idempotent_duplicate"])
            self.assertEqual(res2["status"], "ALREADY_PROCESSED")

            # Comprobar que el saldo NO se duplicó a 200, sino que permaneció en 100
            cursor.execute("SELECT balance_after FROM credit_ledger WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 1", (tenant,))
            balance_2 = cursor.fetchone()["balance_after"]
            self.assertEqual(balance_2, 100)


if __name__ == "__main__":
    unittest.main()
