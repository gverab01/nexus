"""
Pruebas Unitarias para el Servicio de Cola Central y Políticas de Ritmo (TASK-QUEUE-03)
"""

import unittest
from datetime import datetime
import task_queue_service

class TestTaskQueueService(unittest.TestCase):
    def setUp(self):
        self.tenant_id = "ten_primary"

    def test_01_get_policies(self):
        policies = task_queue_service.get_tenant_policies(self.tenant_id)
        self.assertIsInstance(policies, list)
        self.assertGreaterEqual(len(policies), 10)
        task_types = [p["tipo_tarea"] for p in policies]
        self.assertIn("LI_INVITE", task_types)
        self.assertIn("LI_ENRICH", task_types)
        self.assertIn("LI_VISIT", task_types)

    def test_02_update_policy(self):
        updated = task_queue_service.update_tenant_policy(
            self.tenant_id,
            tipo_tarea="LI_INVITE",
            limite_diario=48,
            pausa_min_seg=200,
            pausa_max_seg=400
        )
        self.assertEqual(updated["limite_diario"], 48)
        self.assertEqual(updated["pausa_min_seg"], 200)
        self.assertEqual(updated["pausa_max_seg"], 400)

        # Restaurar
        restored = task_queue_service.reset_tenant_policies_to_recommended(self.tenant_id)
        pol_invite = next(p for p in restored if p["tipo_tarea"] == "LI_INVITE")
        self.assertEqual(pol_invite["limite_diario"], 50)

    def test_03_enqueue_and_consume_batch(self):
        # Obtener un lead real de la base de datos
        from database import get_db
        real_lead_id = None
        with get_db(tenant_id=self.tenant_id) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM leads WHERE tenant_id = %s LIMIT 1", (self.tenant_id,))
            row = cur.fetchone()
            if row:
                real_lead_id = row["id"]

        if not real_lead_id:
            self.skipTest("No hay leads en la base de datos para la prueba.")

        # Encolar lead real
        res = task_queue_service.enqueue_batch_actions(
            self.tenant_id,
            tipo_tarea="LI_ENRICH",
            lead_ids=[real_lead_id],
            payload={"source": "test"}
        )
        self.assertIn(res["enqueued"], [0, 1])

        # Obtener resumen
        summary = task_queue_service.get_queue_summary(self.tenant_id)
        self.assertIn("pendientes", summary)
        self.assertIn("completadas_hoy", summary)

        # Cancelar tareas de test
        cancelled = task_queue_service.cancel_pending_tasks(self.tenant_id)
        self.assertGreaterEqual(cancelled, 0)

if __name__ == "__main__":
    unittest.main()
