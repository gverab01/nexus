import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import email_resolver_service
from database import get_db

with get_db() as conn:
    c = conn.cursor()
    c.execute("SELECT id, nombre, cargo_titular, institucion_actual, grado_red FROM leads LIMIT 3")
    leads = c.fetchall()

print(f"Testing resolution on {len(leads)} sample leads:")
for l in leads:
    print(f"\n--- Testing: {l['nombre']} ({l['institucion_actual']}) Grado: {l['grado_red']} ---")
    res = email_resolver_service.resolve_lead_email(l['id'], force_refresh=True)
    print("Result:", res)
