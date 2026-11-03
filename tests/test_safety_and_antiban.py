"""
Test Suite de Antiban, Huella Digital y Motor de Seguridad (NexusReach Pro)
Directrices para Agentes v1.3 - Workstream 5.5 [P1]

Verifica:
1. Variación estocástica y semillas por cuenta (distribución de tiempo y jitter diferentes).
2. Curva de calentamiento adaptativa (15/día -> 18 -> 22 -> 25) condicionada a health score.
3. Congelamiento inmediato de la cola (< 1 ciclo) ante señales de riesgo (checkpoint, CAPTCHA, PIN, restricción).
4. Kill-switch global automático si >= 3 cuentas distintas sufren incidentes críticos en < 24h.
5. Reactivación manual tras resolución humana reiniciando calentamiento a 15/día y warmup_day = 1.
6. Separación estricta (5.5.7): comprar packs comerciales o subir de plan NUNCA altera límites de seguridad ni pausas.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database import get_db, init_db
import safety_engine

class TestSafetyAndAntiban(unittest.TestCase):

    def setUp(self):
        init_db()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE configuracion_seguridad SET valor = '0' WHERE clave = 'kill_switch_activado'")
            cursor.execute("UPDATE configuracion_seguridad SET valor = '' WHERE clave = 'kill_switch_motivo'")
            cursor.execute("UPDATE configuracion_seguridad SET valor = '0' WHERE clave = 'horario_laboral_activo'")
            cursor.execute("UPDATE configuracion_seguridad SET valor = '1' WHERE clave = 'pausas_antiban_activas'")
            cursor.execute("DELETE FROM system_logs WHERE module = 'ANTIBAN_SAFETY'")
            conn.commit()

    def _ensure_tenant(self, cursor, tenant_id: str):
        now_iso = datetime.now().isoformat()
        cursor.execute("""
            INSERT OR IGNORE INTO tenants (id, razon_social, tipo_tenant, estado, created_at, updated_at)
            VALUES (?, ?, 'EMPRESA', 'ACTIVO', ?, ?)
        """, (tenant_id, f"Empresa {tenant_id}", now_iso, now_iso))

    def test_distinct_delay_distributions_and_jitter_per_account(self):
        """Verifica que dos cuentas distintas generen distribuciones de tiempo y jitter diferentes (evitando huella única)."""
        acc_a = "li_acc_alpha_123"
        acc_b = "li_acc_beta_987"

        params_a = safety_engine.get_account_safety_parameters(acc_a)
        params_b = safety_engine.get_account_safety_parameters(acc_b)

        # Parámetros deterministas por semilla de cuenta deben ser distintos
        self.assertTrue(params_a["min_delay_sec"] != params_b["min_delay_sec"] or params_a["max_delay_sec"] != params_b["max_delay_sec"])
        self.assertTrue(params_a["start_jitter_minutes"] != params_b["start_jitter_minutes"] or params_a["end_jitter_minutes"] != params_b["end_jitter_minutes"])

        # Muestras de retardos estocásticos calculados
        delays_a = [safety_engine.calculate_per_account_delay(acc_a) for _ in range(15)]
        delays_b = [safety_engine.calculate_per_account_delay(acc_b) for _ in range(15)]

        avg_a = sum(delays_a) / len(delays_a)
        avg_b = sum(delays_b) / len(delays_b)

        # Las medias y distribuciones no deben ser idénticas
        self.assertGreater(abs(avg_a - avg_b), 0.1)
        # Todos deben respetar los rangos seguros
        self.assertTrue(all(d >= 10.0 for d in delays_a))
        self.assertTrue(all(d >= 10.0 for d in delays_b))

    def test_adaptive_warmup_starts_at_15_and_scales_with_health(self):
        """Verifica que el calentamiento comience en 15/día y solo escale si el health score lo permite."""
        tenant = "ten_warmup_test"
        acc_id = "acc_warmup_01"
        now_iso = datetime.now().isoformat()

        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)
            cursor.execute("""
                INSERT OR REPLACE INTO linkedin_accounts 
                (id, tenant_id, account_name, status, warmup_day, daily_invite_limit, health_score, created_at, updated_at)
                VALUES (?, ?, 'User Warmup', 'WARMUP', 1, 15, 85.0, ?, ?)
            """, (acc_id, tenant, now_iso, now_iso))
            conn.commit()

            # Semana 1 (warmup_day = 1): Límite base 15
            info_w1 = safety_engine.calculate_adaptive_warmup_limit(acc_id, tenant, conn=conn)
            self.assertEqual(info_w1["limite_diario"], 15)
            self.assertEqual(info_w1["semana"], 1)

            # Avance a Semana 2 con buena salud (85.0 >= 70.0) -> escala a 18
            cursor.execute("UPDATE linkedin_accounts SET warmup_day = 8, health_score = 85.0 WHERE id = ?", (acc_id,))
            conn.commit()
            info_w2_healthy = safety_engine.calculate_adaptive_warmup_limit(acc_id, tenant, conn=conn)
            self.assertEqual(info_w2_healthy["limite_diario"], 18)
            self.assertTrue(info_w2_healthy["escalamiento_permitido"])

            # Semana 2 con mala salud (health_score = 55.0 < 70.0) -> bloquea escalamiento y retiene en 15
            cursor.execute("UPDATE linkedin_accounts SET warmup_day = 8, health_score = 55.0 WHERE id = ?", (acc_id,))
            conn.commit()
            info_w2_unhealthy = safety_engine.calculate_adaptive_warmup_limit(acc_id, tenant, conn=conn)
            self.assertEqual(info_w2_unhealthy["limite_diario"], 15)
            self.assertFalse(info_w2_unhealthy["escalamiento_permitido"])
            self.assertIn("salud", info_w2_unhealthy["motivo"].lower())

            # Semana 3 con salud excelente (health_score = 88.0 >= 75.0) -> escala a 22
            cursor.execute("UPDATE linkedin_accounts SET warmup_day = 15, health_score = 88.0 WHERE id = ?", (acc_id,))
            conn.commit()
            info_w3 = safety_engine.calculate_adaptive_warmup_limit(acc_id, tenant, conn=conn)
            self.assertEqual(info_w3["limite_diario"], 22)

            # Semana 4+ con salud excelente (health_score = 92.0 >= 80.0) -> escala a 25 (techo seguro de prospección)
            cursor.execute("UPDATE linkedin_accounts SET warmup_day = 22, health_score = 92.0 WHERE id = ?", (acc_id,))
            conn.commit()
            info_w4 = safety_engine.calculate_adaptive_warmup_limit(acc_id, tenant, conn=conn)
            self.assertEqual(info_w4["limite_diario"], 25)

    def test_checkpoint_signal_freezes_account_queue_immediately(self):
        """Verifica que un evento de checkpoint congele la cola de la cuenta en < 1 ciclo de dispatch."""
        tenant = "ten_freeze_test"
        acc_id = "acc_freeze_01"
        now_iso = datetime.now().isoformat()

        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)
            cursor.execute("""
                INSERT OR REPLACE INTO linkedin_accounts 
                (id, tenant_id, account_name, status, warmup_day, daily_invite_limit, health_score, created_at, updated_at)
                VALUES (?, ?, 'User Freeze', 'ACTIVE', 10, 18, 90.0, ?, ?)
            """, (acc_id, tenant, now_iso, now_iso))
            conn.commit()

            # Antes de la señal: autorizada
            auth_before = safety_engine.authorize_linkedin_action(acc_id, tenant, "LI_SEND_INVITE", conn=conn)
            self.assertTrue(auth_before["autorizado"])

            # Se recibe señal de CHECKPOINT
            res = safety_engine.report_risk_signal(acc_id, tenant, "CHECKPOINT", details={"url": "https://linkedin.com/checkpoint/challenge"}, conn=conn)
            self.assertTrue(res["ok"])
            self.assertEqual(res["new_status"], "CHECKPOINT")
            self.assertTrue(res["cola_congelada"])

            # Inmediatamente después: denegada con motivo ACCOUNT_CHECKPOINT
            auth_after = safety_engine.authorize_linkedin_action(acc_id, tenant, "LI_SEND_INVITE", conn=conn)
            self.assertFalse(auth_after["autorizado"])
            self.assertIn("CHECKPOINT", auth_after["codigo"])

    def test_aggregate_anomaly_triggers_global_kill_switch(self):
        """Verifica que si >= 3 cuentas distintas sufren incidentes críticos en < 24h se dispare el kill-switch global."""
        tenant = "ten_anomaly_test"
        now_iso = datetime.now().isoformat()

        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)
            # Crear 3 cuentas
            for i in range(1, 4):
                cursor.execute("""
                    INSERT OR REPLACE INTO linkedin_accounts 
                    (id, tenant_id, account_name, status, warmup_day, daily_invite_limit, health_score, created_at, updated_at)
                    VALUES (?, ?, ?, 'ACTIVE', 5, 15, 80.0, ?, ?)
                """, (f"acc_incident_{i}", tenant, f"Account {i}", now_iso, now_iso))
            conn.commit()

            # 1er incidente
            res1 = safety_engine.report_risk_signal("acc_incident_1", tenant, "CAPTCHA", conn=conn)
            self.assertFalse(res1["global_kill_switch_triggered"])

            # 2do incidente
            res2 = safety_engine.report_risk_signal("acc_incident_2", tenant, "RESTRICTED", conn=conn)
            self.assertFalse(res2["global_kill_switch_triggered"])

            # 3er incidente en cuenta distinta dentro de 24h
            res3 = safety_engine.report_risk_signal("acc_incident_3", tenant, "CHECKPOINT", conn=conn)
            self.assertTrue(res3["global_kill_switch_triggered"])

            # Comprobar que el Kill-Switch global se activó
            cfg = safety_engine.get_all_safety_config(conn=conn)
            self.assertEqual(cfg.get("kill_switch_activado"), "1")
            self.assertIn("anómala de incidentes múltiples", cfg.get("kill_switch_motivo", ""))

            # Ninguna cuenta (incluso sana) debe poder emitir acciones ahora
            auth_global = safety_engine.authorize_linkedin_action("acc_healthy_other", tenant, "LI_SEND_INVITE", conn=conn)
            self.assertFalse(auth_global["autorizado"])
            self.assertEqual(auth_global["codigo"], "GLOBAL_KILL_SWITCH_ACTIVE")

    def test_manual_reactivation_resets_warmup_to_day_1(self):
        """Verifica que la reactivación manual reinicie el calentamiento a 15/día y warmup_day = 1."""
        tenant = "ten_react_test"
        acc_id = "acc_react_01"
        now_iso = datetime.now().isoformat()

        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)
            cursor.execute("""
                INSERT OR REPLACE INTO linkedin_accounts 
                (id, tenant_id, account_name, status, warmup_day, daily_invite_limit, health_score, created_at, updated_at)
                VALUES (?, ?, 'User Reactivate', 'CHECKPOINT', 20, 25, 30.0, ?, ?)
            """, (acc_id, tenant, now_iso, now_iso))
            conn.commit()

            # Ejecutar reactivación
            react_res = safety_engine.reactivate_account(acc_id, tenant, conn=conn)
            self.assertTrue(react_res["ok"])
            self.assertEqual(react_res["status"], "WARMUP")
            self.assertEqual(react_res["warmup_day"], 1)
            self.assertEqual(react_res["daily_invite_limit"], 15)

            # Comprobar estado en BD
            cursor.execute("SELECT status, warmup_day, daily_invite_limit FROM linkedin_accounts WHERE id = ?", (acc_id,))
            row = cursor.fetchone()
            self.assertEqual(row["status"], "WARMUP")
            self.assertEqual(row["warmup_day"], 1)
            self.assertEqual(row["daily_invite_limit"], 15)

    def test_commercial_quota_purchase_does_not_alter_safety_limits(self):
        """
        CRITERIO 5.5.7 NO NEGOCIABLE:
        Comprar un pack comercial o subir de plan NUNCA debe modificar los límites de seguridad ni las pausas.
        """
        tenant = "ten_commercial_test"
        acc_id = "acc_comm_01"
        now_iso = datetime.now().isoformat()

        with get_db(tenant_id=tenant) as conn:
            cursor = conn.cursor()
            self._ensure_tenant(cursor, tenant)
            cursor.execute("""
                INSERT OR REPLACE INTO linkedin_accounts 
                (id, tenant_id, account_name, status, warmup_day, daily_invite_limit, health_score, created_at, updated_at)
                VALUES (?, ?, 'User Commercial', 'WARMUP', 1, 15, 80.0, ?, ?)
            """, (acc_id, tenant, now_iso, now_iso))
            # Suscripción inicial
            exp_iso = (datetime.now() + timedelta(days=30)).isoformat()
            cursor.execute("""
                INSERT OR REPLACE INTO suscripciones (id, tenant_id, periodicidad, estado, puestos_contratados, precio_unitario_plataforma, fecha_inicio, fecha_expiracion, created_at, updated_at)
                VALUES ('sub_test_01', ?, 'MENSUAL', 'ACTIVA', 1, 35.0, ?, ?, ?, ?)
            """, (tenant, now_iso, exp_iso, now_iso, now_iso))
            conn.commit()

            # Límite de seguridad inicial
            safety_before = safety_engine.calculate_adaptive_warmup_limit(acc_id, tenant, conn=conn)
            self.assertEqual(safety_before["limite_diario"], 15)

            # Cliente compra pack Enterprise con 50 puestos y 10,000 créditos
            cursor.execute("""
                UPDATE suscripciones 
                SET puestos_contratados = 50, precio_unitario_plataforma = 99.0 
                WHERE tenant_id = ?
            """, (tenant,))
            import secrets
            cred_id = f"cred_test_{secrets.token_hex(4)}"
            cursor.execute("""
                INSERT OR REPLACE INTO credit_ledger (id, tenant_id, account_id, credit_type, delta, balance_after, description, created_at)
                VALUES (?, ?, ?, 'PURCHASE', 10000, 10000, 'Mega Pack 10k Credits', ?)
            """, (cred_id, tenant, acc_id, now_iso))
            conn.commit()

            # Validación 1: Cuota comercial está aprobada
            comm_eval = safety_engine.check_commercial_quota(tenant, "LI_SEND_INVITE", conn=conn)
            self.assertTrue(comm_eval["aprobado"])

            # Validación 2: El límite del safety engine sigue siendo estrictamente 15/día
            safety_after = safety_engine.calculate_adaptive_warmup_limit(acc_id, tenant, conn=conn)
            self.assertEqual(safety_after["limite_diario"], 15)
            self.assertEqual(safety_after["semana"], 1)

            # Validación 3: Las pausas estocásticas del motor de seguridad no se aceleraron
            delays_after = [safety_engine.calculate_per_account_delay(acc_id) for _ in range(5)]
            self.assertTrue(all(d >= 10.0 for d in delays_after))

            # Comprobar que la cuota de invitaciones hoy sigue aplicando el límite de 15
            cursor.execute("UPDATE linkedin_accounts SET invites_sent_today = 15 WHERE id = ?", (acc_id,))
            conn.commit()

            auth_blocked = safety_engine.authorize_linkedin_action(acc_id, tenant, "LI_SEND_INVITE", conn=conn)
            self.assertFalse(auth_blocked["autorizado"])
            self.assertEqual(auth_blocked["codigo"], "CUOTA_DIARIA_COMPLETA")
            self.assertEqual(auth_blocked["limite_diario"], 15)


if __name__ == "__main__":
    unittest.main()
