import unittest
from datetime import datetime, timezone
from database import get_db, init_db
import extractor_engine

class TestNetworkLeadsExtraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    TEST_TENANT = "ten_test_network_ext"

    def setUp(self):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM leads_en_lista WHERE lead_id IN (SELECT id FROM leads WHERE tenant_id = ?)", (self.TEST_TENANT,))
            cursor.execute("DELETE FROM leads_en_secuencia WHERE lead_id IN (SELECT id FROM leads WHERE tenant_id = ?)", (self.TEST_TENANT,))
            cursor.execute("DELETE FROM historial_actividades WHERE lead_id IN (SELECT id FROM leads WHERE tenant_id = ?)", (self.TEST_TENANT,))
            cursor.execute("DELETE FROM leads WHERE tenant_id = ?", (self.TEST_TENANT,))
            cursor.execute("DELETE FROM listas_leads WHERE tenant_id = ?", (self.TEST_TENANT,))
            cursor.execute("DELETE FROM tenants WHERE id = ?", (self.TEST_TENANT,))
            
            now_iso = datetime.now(timezone.utc).isoformat()
            cursor.execute("""
                INSERT OR IGNORE INTO tenants (id, razon_social, estado, created_at, updated_at)
                VALUES (?, 'Tenant Network Test', 'ACTIVO', ?, ?)
            """, (self.TEST_TENANT, now_iso, now_iso))
            conn.commit()

    def tearDown(self):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM leads_en_lista WHERE lead_id IN (SELECT id FROM leads WHERE tenant_id = ?)", (self.TEST_TENANT,))
            cursor.execute("DELETE FROM historial_actividades WHERE lead_id IN (SELECT id FROM leads WHERE tenant_id = ?)", (self.TEST_TENANT,))
            cursor.execute("DELETE FROM leads WHERE tenant_id = ?", (self.TEST_TENANT,))
            cursor.execute("DELETE FROM listas_leads WHERE tenant_id = ?", (self.TEST_TENANT,))
            cursor.execute("DELETE FROM tenants WHERE id = ?", (self.TEST_TENANT,))
            conn.commit()

    def test_01_import_network_leads_preserves_connected_and_sent_states(self):
        """
        Verifica que al importar prospectos descubiertos de la red de LinkedIn:
        - Las conexiones de 1er grado se guardan como 'CONECTADO', grado '1º' y con fecha_conexion.
        - Las invitaciones enviadas se guardan como 'INVITACION_ENVIADA' y grado '2º'.
        - Se asocian al tenant_id activo y a las listas de destino.
        """
        with get_db() as conn:
            cursor = conn.cursor()
            now_iso = datetime.now(timezone.utc).isoformat()
            cursor.execute("""
                INSERT INTO listas_leads (id, tenant_id, nombre, descripcion, created_at, updated_at)
                VALUES ('list_test_net', ?, 'Lista Red LinkedIn', 'Test', ?, ?)
            """, (self.TEST_TENANT, now_iso, now_iso))
            conn.commit()

        leads_to_import = [
            {
                "nombre": "Ana Conectada Rojas",
                "perfil_url": "https://www.linkedin.com/in/ana-conectada-rojas/",
                "cargo_titular": "Directora de Operaciones en Tech Chile",
                "cargo_actual": "Directora de Operaciones",
                "institucion_actual": "Tech Chile",
                "ubicacion": "Santiago, Chile",
                "grado_red": "1º",
                "estado": "CONECTADO",
                "estado_origen": "CONECTADO",
                "tipo_origen": "CONEXION_DIRECTA",
                "tiempo": "Conectado hace 2 días"
            },
            {
                "nombre": "Carlos Invitado Díaz",
                "perfil_url": "https://www.linkedin.com/in/carlos-invitado-diaz/",
                "cargo_titular": "Gerente General en Retail SA",
                "cargo_actual": "Gerente General",
                "institucion_actual": "Retail SA",
                "ubicacion": "Chile",
                "grado_red": "2º",
                "estado": "INVITACION_ENVIADA",
                "estado_origen": "INVITACION_ENVIADA",
                "tipo_origen": "INVITACION_PENDIENTE",
                "tiempo": "Enviada hace 1 semana"
            }
        ]

        res = extractor_engine.import_selected_leads(
            leads_to_import,
            list_id="list_test_net",
            tenant_id=self.TEST_TENANT
        )

        self.assertEqual(res["nuevos_importados"], 2)
        self.assertEqual(res["duplicados_omitidos"], 0)

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM leads WHERE tenant_id = ? ORDER BY nombre ASC", (self.TEST_TENANT,))
            rows = cursor.fetchall()

            self.assertEqual(len(rows), 2)
            ana = rows[0]
            carlos = rows[1]

            # Validar Ana (Conexión)
            self.assertEqual(ana["nombre"], "Ana Conectada Rojas")
            self.assertEqual(ana["estado"], "CONECTADO")
            self.assertEqual(ana["grado_red"], "1º")
            self.assertIsNotNone(ana["fecha_conexion"])

            # Validar Carlos (Invitación enviada)
            self.assertEqual(carlos["nombre"], "Carlos Invitado Díaz")
            self.assertEqual(carlos["estado"], "INVITACION_ENVIADA")
            self.assertEqual(carlos["grado_red"], "2º")

            # Validar asociación a lista
            cursor.execute("SELECT count(*) as total FROM leads_en_lista WHERE lista_id = 'list_test_net'")
            self.assertEqual(cursor.fetchone()["total"], 2)

            # Validar historial de auditoría
            cursor.execute("SELECT count(*) as total FROM historial_actividades WHERE lead_id = ? AND tipo_evento = 'CONEXION_IMPORTADA_MANUAL'", (ana["id"],))
            self.assertEqual(cursor.fetchone()["total"], 1)

            cursor.execute("SELECT count(*) as total FROM historial_actividades WHERE lead_id = ? AND tipo_evento = 'INVITACION_IMPORTADA_MANUAL'", (carlos["id"],))
            self.assertEqual(cursor.fetchone()["total"], 1)

if __name__ == '__main__':
    unittest.main()
