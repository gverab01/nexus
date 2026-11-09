"""
Tests de Integración de Endpoints REST de la Cola Central en FastAPI (TASK-QUEUE-05)
"""

import unittest
from fastapi.testclient import TestClient
import main

class TestQueueEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        # Login como superadmin o admin
        res = cls.client.post("/api/auth/login", json={"email": "admin@nexusreach.com", "password": "AdminNexus2026!"})
        data = res.json()
        cls.token = data.get("token") or data.get("session_token")
        cls.headers = {"X-Session-Token": cls.token}

    def test_01_get_status(self):
        res = self.client.get("/api/cola-tareas/estado", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("pendientes", data)
        self.assertIn("completadas_hoy", data)

    def test_02_get_and_update_policies(self):
        res = self.client.get("/api/cola-tareas/politicas", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("ok"))
        self.assertIsInstance(data.get("politicas"), list)

        # Actualizar política de LI_INVITE
        res_put = self.client.put(
            "/api/cola-tareas/politicas/LI_INVITE",
            json={"limite_diario": 45, "pausa_min_seg": 210, "pausa_max_seg": 420},
            headers=self.headers
        )
        self.assertEqual(res_put.status_code, 200)
        self.assertEqual(res_put.json()["politica"]["limite_diario"], 45)

        # Restaurar
        res_rst = self.client.post("/api/cola-tareas/politicas/restaurar", headers=self.headers)
        self.assertEqual(res_rst.status_code, 200)

    def test_03_enqueue_and_cancel(self):
        # Obtener un lead de la base
        res_leads = self.client.get("/api/prospectos?tenant_id=ten_primary&limit=1", headers=self.headers)
        leads = res_leads.json().get("prospectos", [])
        if not leads:
            self.skipTest("Sin leads para probar encolamiento")

        lead_id = leads[0]["id"]
        res_enq = self.client.post(
            "/api/cola-tareas/encolar?tenant_id=ten_primary",
            json={"tipo_tarea": "LI_ENRICH", "lead_ids": [lead_id]},
            headers=self.headers
        )
        self.assertEqual(res_enq.status_code, 200)
        self.assertTrue(res_enq.json().get("ok"))

        # Cancelar
        res_can = self.client.post("/api/cola-tareas/cancelar?tenant_id=ten_primary", json={}, headers=self.headers)
        self.assertEqual(res_can.status_code, 200)
        self.assertTrue(res_can.json().get("ok"))

if __name__ == "__main__":
    unittest.main()
