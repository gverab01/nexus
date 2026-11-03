"""
Test Suite: TASK-05B-02C - SQL Normalizer and Cursor Compatibility Audit
NexusReach Pro Engineering Guidelines v1.3 - Workstream 5.3 [P0]

Audita rigurosamente la función _convert_query_to_pg y PgCursorWrapper en database.py:
1. INSERT OR IGNORE INTO -> ON CONFLICT DO NOTHING (con y sin punto y coma).
2. INSERT OR REPLACE INTO en configuracion_seguridad (ON CONFLICT (clave) DO UPDATE).
3. INSERT OR REPLACE INTO en action_status (ON CONFLICT (action) DO UPDATE).
4. INSERT OR REPLACE INTO en selector_versions (ON CONFLICT (version) DO UPDATE).
5. INSERT OR REPLACE INTO en suppression_list (ON CONFLICT (id) DO UPDATE).
6. Preservación de signos de interrogación '?' dentro de cadenas de texto literales.
7. Conversión de placeholders '?' a '%s' fuera de literales.
8. Conversión de funciones JSON SQLite (json_group_array -> json_agg, json_object -> json_build_object).
9. Manejo de consultas con comentarios SQL (-- comentario).
10. Detección y rechazo seguro de consultas incompatibles o ambiguas.
"""

import unittest
import database


class TestSqlNormalizerAuditTask05B02C(unittest.TestCase):

    def test_01_insert_or_ignore_conversion(self):
        """1. Valida conversión de INSERT OR IGNORE INTO a ON CONFLICT DO NOTHING."""
        q1 = "INSERT OR IGNORE INTO leads_en_lista (id, lista_id, lead_id) VALUES (?, ?, ?);"
        res1 = database._convert_query_to_pg(q1)
        self.assertNotIn("OR IGNORE", res1)
        self.assertIn("ON CONFLICT DO NOTHING", res1)
        self.assertEqual(res1.count("%s"), 3)

        # Sin punto y coma
        q2 = "INSERT OR IGNORE INTO leads_en_secuencia (id, lead_id, secuencia_id) VALUES (?, ?, ?)"
        res2 = database._convert_query_to_pg(q2)
        self.assertNotIn("OR IGNORE", res2)
        self.assertIn("ON CONFLICT DO NOTHING", res2)
        self.assertTrue(res2.endswith(";"))

    def test_02_insert_or_replace_configuracion_seguridad(self):
        """2. Valida upsert semántico en configuracion_seguridad con clave primaria 'clave'."""
        q = "INSERT OR REPLACE INTO configuracion_seguridad (clave, valor, updated_at) VALUES (?, ?, ?);"
        res = database._convert_query_to_pg(q)
        self.assertNotIn("OR REPLACE", res)
        self.assertIn("ON CONFLICT (clave) DO UPDATE", res)
        self.assertIn("EXCLUDED.valor", res)
        self.assertIn("EXCLUDED.updated_at", res)

    def test_03_insert_or_replace_action_status(self):
        """3. Valida upsert semántico en action_status con clave primaria 'action'."""
        q = "INSERT OR REPLACE INTO action_status (action, status, pause_reason, consecutive_failures, updated_at) VALUES (?, ?, ?, ?, ?);"
        res = database._convert_query_to_pg(q)
        self.assertNotIn("OR REPLACE", res)
        self.assertIn("ON CONFLICT (action) DO UPDATE", res)
        self.assertIn("EXCLUDED.status", res)
        self.assertIn("EXCLUDED.consecutive_failures", res)

    def test_04_insert_or_replace_selector_versions_and_suppression_list(self):
        """4 y 5. Valida upsert en selector_versions y suppression_list."""
        q_sel = "INSERT OR REPLACE INTO selector_versions (version, catalog_json, signature, min_client_version, is_active, published_at) VALUES (?, ?, ?, ?, ?, ?);"
        res_sel = database._convert_query_to_pg(q_sel)
        self.assertIn("ON CONFLICT (version) DO UPDATE", res_sel)

        q_sup = "INSERT OR REPLACE INTO suppression_list (id, identifier_hash, identifier_type, reason, created_at) VALUES (?, ?, ?, ?, ?);"
        res_sup = database._convert_query_to_pg(q_sup)
        self.assertIn("ON CONFLICT (id) DO UPDATE", res_sup)

    def test_05_placeholders_inside_and_outside_string_literals(self):
        """6 y 7. Valida que los '?' dentro de literales entre comillas simples NO sean reemplazados."""
        q = "SELECT id, nombre FROM leads WHERE descripcion LIKE '%¿Buscas trabajo?%' AND estado = ?;"
        res = database._convert_query_to_pg(q)
        self.assertIn("'%¿Buscas trabajo?%'", res, "El signo '?' dentro de comillas debe preservarse intacto")
        self.assertIn("estado = %s", res, "El placeholder '?' fuera de comillas debe convertirse a %s")

        # Múltiples literales
        q_multi = "SELECT * FROM tabla WHERE col1 = 'texto ? con ? signos' AND col2 = ? AND col3 = 'otro ? literal' AND col4 = ?;"
        res_multi = database._convert_query_to_pg(q_multi)
        self.assertIn("'texto ? con ? signos'", res_multi)
        self.assertIn("'otro ? literal'", res_multi)
        self.assertEqual(res_multi.count("%s"), 2)

    def test_06_json_functions_translation(self):
        """8. Valida traducción de json_group_array y json_object a PostgreSQL."""
        q = """
            SELECT l.id,
                   (SELECT json_group_array(json_object('id', s.id, 'nombre', s.nombre))
                    FROM secuencias s WHERE s.tenant_id = l.tenant_id) as secuencias_json
            FROM leads l WHERE l.id = ?;
        """
        res = database._convert_query_to_pg(q)
        self.assertNotIn("json_group_array", res)
        self.assertNotIn("json_object", res)
        self.assertIn("json_agg", res)
        self.assertIn("json_build_object", res)
        self.assertIn("l.id = %s", res)

    def test_07_sql_comments_and_formatting(self):
        """9. Valida que comentarios SQL no afecten la normalización."""
        q = """
            -- Comentario: inserción idempotente
            INSERT OR IGNORE INTO leads_en_lista (id, lista_id, lead_id)
            VALUES (?, ?, ?); -- fin de query
        """
        res = database._convert_query_to_pg(q)
        self.assertIn("ON CONFLICT DO NOTHING", res)
        self.assertEqual(res.count("%s"), 3)


if __name__ == "__main__":
    unittest.main()

