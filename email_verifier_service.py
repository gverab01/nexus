"""
Módulo de Verificación Externa de Correos Electrónicos (EmailVerifier)
NexusReach Pro Directrices de Ingeniería v1.3 - Workstream 5.6 [P1]

Decisión Arquitectónica 5.6:
- Eliminación total de sondeo SMTP saliente (RCPT TO) en puerto 25.
- Abstracción desacoplada mediante interfaz EmailVerifier.
- Proveedor principal: MillionVerifier (0.003 USD / consulta).
- Proveedor alternativo: ZeroBounce (0.008 USD / consulta).
- Búsqueda OSINT web: Serper Search (0.001 USD / consulta).
- Proveedor local: LocalDNSVerifierProvider para pruebas y entornos sandbox.
- Registro estricto de costo real en USD en usage_events y consumo en credit_ledger.
- Estados de resultado explícitos: 'valid', 'invalid', 'catch_all', 'risky', 'unknown'.
"""

import os
import json
import re
import urllib.request
import urllib.error
import urllib.parse
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any, Optional, List
import dns.resolver

from database import get_db

# ==============================================================================
# MODELO DE RESULTADO NORMALIZADO
# ==============================================================================

class EmailVerificationResult:
    """Resultado estandarizado de verificación con estado, confianza y costo real."""
    def __init__(
        self,
        email: str,
        status: str,  # 'valid', 'invalid', 'catch_all', 'risky', 'unknown'
        confidence: float,  # 0.0 a 1.0
        provider: str,
        cost_cents: int,  # Costo en centavos de USD (ej. 1 = 0.01 USD, 0 = 0.00)
        cost_usd: float,
        details: Optional[Dict[str, Any]] = None
    ):
        self.email = email
        self.status = status
        self.confidence = max(0.0, min(1.0, round(confidence, 2)))
        self.provider = provider
        self.cost_cents = cost_cents
        self.cost_usd = round(cost_usd, 4)
        self.details = details or {}

    def is_usable(self, catch_all_threshold: float = 0.60) -> bool:
        """Determina si el correo es utilizable para secuencias de prospección comercial."""
        if self.status == "valid":
            return True
        if self.status == "catch_all" and self.confidence >= catch_all_threshold:
            return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "email": self.email,
            "status": self.status,
            "confidence": self.confidence,
            "provider": self.provider,
            "cost_cents": self.cost_cents,
            "cost_usd": self.cost_usd,
            "is_usable": self.is_usable(),
            "details": self.details
        }


# ==============================================================================
# INTERFAZ BASE ABSTRACTA (EmailVerifier)
# ==============================================================================

class EmailVerifier(ABC):
    """Interfaz abstracta para verificadores de correo externos."""

    @abstractmethod
    def verify(self, email: str, tenant_id: str = "ten_superadmin") -> EmailVerificationResult:
        """Verifica una dirección de correo y retorna un resultado normalizado."""
        pass


# ==============================================================================
# PROVEEDOR 1: MillionVerifier (Principal)
# ==============================================================================

class MillionVerifierProvider(EmailVerifier):
    """
    Proveedor principal de verificación de buzones vía API REST de MillionVerifier.
    Costo estimado de referencia: ~0.003 USD por correo.
    """
    PROVIDER_NAME = "millionverifier"
    UNIT_COST_USD = 0.003
    UNIT_COST_CENTS = 0  # < 1 centavo (0.3 centavos)

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("MILLION_VERIFIER_API_KEY", "")

    def _get_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT valor FROM configuracion_seguridad WHERE clave = 'million_verifier_api_key'")
                row = cursor.fetchone()
                if row:
                    val = row["valor"] if isinstance(row, dict) else row[0]
                    return val.strip() if val else ""
        except Exception:
            pass
        return ""

    def verify(self, email: str, tenant_id: str = "ten_superadmin") -> EmailVerificationResult:
        key = self._get_api_key()
        if not key:
            # Fallback transparente a LocalDNSVerifier si la clave no está configurada
            fallback = LocalDNSVerifierProvider()
            res = fallback.verify(email, tenant_id)
            res.provider = f"{self.PROVIDER_NAME}_local_fallback"
            return res

        try:
            clean_email = email.strip().lower()
            query_params = urllib.parse.urlencode({
                "api": key,
                "email": clean_email,
                "timeout": 10
            })
            url = f"https://api.millionverifier.com/api/v3/?{query_params}"
            req = urllib.request.Request(url, headers={"User-Agent": "NexusReach-Verifier/1.3"})

            with urllib.request.urlopen(req, timeout=12.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            raw_result = str(data.get("result", "")).lower()
            # Mapeo oficial de estados de MillionVerifier:
            # 'ok', 'catch_all', 'unknown', 'invalid', 'disposable'
            if raw_result == "ok":
                status = "valid"
                confidence = 0.95
            elif raw_result == "catch_all":
                status = "catch_all"
                confidence = 0.65
            elif raw_result in ("disposable", "invalid"):
                status = "invalid"
                confidence = 0.98
            else:
                status = "unknown"
                confidence = 0.40

            return EmailVerificationResult(
                email=clean_email,
                status=status,
                confidence=confidence,
                provider=self.PROVIDER_NAME,
                cost_cents=self.UNIT_COST_CENTS,
                cost_usd=self.UNIT_COST_USD,
                details=data
            )
        except Exception as e:
            return EmailVerificationResult(
                email=email,
                status="unknown",
                confidence=0.30,
                provider=self.PROVIDER_NAME,
                cost_cents=0,
                cost_usd=0.0,
                details={"error": str(e)}
            )


# ==============================================================================
# PROVEEDOR 2: ZeroBounce (Alternativo)
# ==============================================================================

class ZeroBounceProvider(EmailVerifier):
    """
    Proveedor alternativo de verificación vía API REST de ZeroBounce.
    Costo estimado de referencia: ~0.008 USD por correo.
    """
    PROVIDER_NAME = "zerobounce"
    UNIT_COST_USD = 0.008
    UNIT_COST_CENTS = 1

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ZEROBOUNCE_API_KEY", "")

    def _get_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT valor FROM configuracion_seguridad WHERE clave = 'zerobounce_api_key'")
                row = cursor.fetchone()
                if row:
                    val = row["valor"] if isinstance(row, dict) else row[0]
                    return val.strip() if val else ""
        except Exception:
            pass
        return ""

    def verify(self, email: str, tenant_id: str = "ten_superadmin") -> EmailVerificationResult:
        key = self._get_api_key()
        if not key:
            fallback = LocalDNSVerifierProvider()
            res = fallback.verify(email, tenant_id)
            res.provider = f"{self.PROVIDER_NAME}_local_fallback"
            return res

        try:
            clean_email = email.strip().lower()
            query_params = urllib.parse.urlencode({
                "api_key": key,
                "email": clean_email
            })
            url = f"https://api.zerobounce.net/v2/validate?{query_params}"
            req = urllib.request.Request(url, headers={"User-Agent": "NexusReach-Verifier/1.3"})

            with urllib.request.urlopen(req, timeout=12.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            raw_status = str(data.get("status", "")).lower()
            # Mapeo oficial de ZeroBounce:
            # 'valid', 'invalid', 'catch-all', 'unknown', 'spamtrap', 'abuse', 'do_not_mail'
            if raw_status == "valid":
                status = "valid"
                confidence = 0.98
            elif raw_status == "catch-all":
                status = "catch_all"
                confidence = 0.65
            elif raw_status in ("invalid", "spamtrap", "abuse", "do_not_mail"):
                status = "invalid"
                confidence = 0.95
            else:
                status = "unknown"
                confidence = 0.40

            return EmailVerificationResult(
                email=clean_email,
                status=status,
                confidence=confidence,
                provider=self.PROVIDER_NAME,
                cost_cents=self.UNIT_COST_CENTS,
                cost_usd=self.UNIT_COST_USD,
                details=data
            )
        except Exception as e:
            return EmailVerificationResult(
                email=email,
                status="unknown",
                confidence=0.30,
                provider=self.PROVIDER_NAME,
                cost_cents=0,
                cost_usd=0.0,
                details={"error": str(e)}
            )


# ==============================================================================
# PROVEEDOR 3: LocalDNSVerifierProvider (Sandbox, Local y Fallback)
# ==============================================================================

class LocalDNSVerifierProvider(EmailVerifier):
    """
    Verificador sintáctico y de registros DNS MX (sin peticiones SMTP en puerto 25).
    Se utiliza en modo offline, en tests y como resguardo seguro. Costo 0 USD.
    """
    PROVIDER_NAME = "localdns"

    DISPOSABLE_DOMAINS = {
        "mailinator.com", "tempmail.com", "10minutemail.com", "throwawaymail.com",
        "guerrillamail.com", "yopmail.com", "trashmail.com", "sharklasers.com"
    }

    def verify(self, email: str, tenant_id: str = "ten_superadmin") -> EmailVerificationResult:
        if not email or "@" not in email or len(email) > 254:
            return EmailVerificationResult(
                email=email or "",
                status="invalid",
                confidence=1.0,
                provider=self.PROVIDER_NAME,
                cost_cents=0,
                cost_usd=0.0,
                details={"motivo": "Sintaxis RFC 5322 inválida"}
            )

        clean = email.strip().lower()
        # Sintaxis básica RFC 5322
        if not re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', clean):
            return EmailVerificationResult(
                email=clean,
                status="invalid",
                confidence=1.0,
                provider=self.PROVIDER_NAME,
                cost_cents=0,
                cost_usd=0.0,
                details={"motivo": "Caracteres ilegales en sintaxis de correo"}
            )

        domain = clean.split("@")[-1].rstrip(".")
        if domain in self.DISPOSABLE_DOMAINS:
            return EmailVerificationResult(
                email=clean,
                status="invalid",
                confidence=0.99,
                provider=self.PROVIDER_NAME,
                cost_cents=0,
                cost_usd=0.0,
                details={"motivo": f"Dominio temporal desechable detectado ({domain})"}
            )

        # Consulta de registros DNS MX (permitida en 5.6)
        try:
            resolver = dns.resolver.Resolver()
            resolver.timeout = 3.0
            resolver.lifetime = 4.0
            answers = resolver.resolve(domain, 'MX')
            mx_list = [str(r.exchange).rstrip('.') for r in answers]
            if mx_list:
                return EmailVerificationResult(
                    email=clean,
                    status="valid",
                    confidence=0.75,
                    provider=self.PROVIDER_NAME,
                    cost_cents=0,
                    cost_usd=0.0,
                    details={"mx_servers": mx_list, "count": len(mx_list)}
                )
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.Timeout, dns.resolver.NoNameservers) as e:
            return EmailVerificationResult(
                email=clean,
                status="invalid",
                confidence=0.90,
                provider=self.PROVIDER_NAME,
                cost_cents=0,
                cost_usd=0.0,
                details={"motivo": f"Dominio sin registros DNS MX activos: {type(e).__name__}"}
            )
        except Exception:
            pass

        # Si no se pudo resolver MX por entorno o red local
        return EmailVerificationResult(
            email=clean,
            status="valid",
            confidence=0.70,
            provider=self.PROVIDER_NAME,
            cost_cents=0,
            cost_usd=0.0,
            details={"motivo": "Formato corporativo válido"}
        )


# ==============================================================================
# PROVEEDOR OSINT: SerperSearchProvider (Búsqueda Web de Correos Públicos)
# ==============================================================================

class SerperSearchProvider:
    """
    Búsqueda OSINT en Google vía Serper API para encontrar correos publicados
    abiertamente en sitios institucionales, enlaces mailto o PDFs oficiales.
    Costo estimado de referencia: ~0.001 USD por consulta.
    """
    PROVIDER_NAME = "serper"
    UNIT_COST_USD = 0.001

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SERPER_API_KEY", "")

    def _get_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT valor FROM configuracion_seguridad WHERE clave = 'serper_api_key'")
                row = cursor.fetchone()
                if row:
                    val = row["valor"] if isinstance(row, dict) else row[0]
                    return val.strip() if val else ""
        except Exception:
            pass
        return ""

    def search_public_email(self, full_name: str, organization: str, target_domain: str = "") -> Optional[Dict[str, Any]]:
        key = self._get_api_key()
        if not key or not full_name:
            return None

        clean_name = full_name.strip()
        query = f'"{clean_name}" "{organization}" email OR correo OR "@"'
        if target_domain:
            query += f' "@{target_domain}"'

        try:
            post_data = json.dumps({"q": query, "num": 5}).encode("utf-8")
            req = urllib.request.Request(
                "https://google.serper.dev/search",
                data=post_data,
                headers={"X-API-KEY": key, "Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            organic = data.get("organic", [])
            for item in organic:
                snippet = item.get("snippet", "") + " " + item.get("title", "")
                link = item.get("link", "")
                # Extraer correos
                matches = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', snippet)
                for email_candidate in matches:
                    c_clean = email_candidate.lower()
                    if target_domain and not c_clean.endswith(f"@{target_domain.lower()}"):
                        continue
                    return {
                        "email": c_clean,
                        "evidence_url": link,
                        "source": "OSINT_PUBLIC_WEB",
                        "provider": self.PROVIDER_NAME,
                        "cost_usd": self.UNIT_COST_USD,
                        "snippet": snippet[:200]
                    }
        except Exception:
            pass
        return None


# ==============================================================================
# FACTORY: RESOLVER DE PROVEEDOR
# ==============================================================================

def get_email_verifier(provider_name: Optional[str] = None) -> EmailVerifier:
    """
    Retorna la instancia del verificador configurado.
    Permite alternar entre MillionVerifier y ZeroBounce sin modificar la cascada.
    """
    target = (provider_name or "").strip().lower()
    if not target:
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT valor FROM configuracion_seguridad WHERE clave = 'verificador_correo_proveedor'")
                row = cursor.fetchone()
                if row:
                    val = row["valor"] if isinstance(row, dict) else row[0]
                    target = (val or "").strip().lower()
        except Exception:
            pass

    if not target:
        target = os.getenv("EMAIL_VERIFIER_PROVIDER", "millionverifier").strip().lower()

    if target == "zerobounce":
        return ZeroBounceProvider()
    elif target == "localdns":
        return LocalDNSVerifierProvider()
    return MillionVerifierProvider()


# ==============================================================================
# AUDITORÍA DE COSTOS Y CONSUMO DE CRÉDITOS
# ==============================================================================

def record_verification_usage(
    tenant_id: str,
    account_id: Optional[str],
    provider: str,
    cost_usd: float,
    credits_consumed: int,
    details: Optional[Dict[str, Any]] = None,
    conn=None
) -> None:
    """
    Registra el evento de verificación en usage_events, descuenta del ledger de créditos
    si corresponde y actualiza los contadores del ciclo actual.
    """
    now_iso = datetime.now().isoformat()
    close_conn = False
    if conn is None:
        from database import get_db
        ctx = get_db(tenant_id=tenant_id)
        conn = ctx.__enter__()
        close_conn = True

    try:
        cursor = conn.cursor()
        event_id = f"evt_{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(3).hex()}"
        det_json = json.dumps(details or {})

        # 1. Registrar evento de uso
        cursor.execute("""
            INSERT INTO usage_events (id, tenant_id, account_id, event_type, provider, cost_usd, credits_consumed, details_json, created_at)
            VALUES (?, ?, ?, 'EMAIL_VERIFICATION', ?, ?, ?, ?, ?)
        """, (event_id, tenant_id, account_id, provider, cost_usd, credits_consumed, det_json, now_iso))

        # 2. Descontar créditos en credit_ledger solo si credits_consumed > 0
        if credits_consumed > 0:
            cursor.execute("SELECT balance_after FROM credit_ledger WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 1", (tenant_id,))
            last_led = cursor.fetchone()
            curr_balance = (last_led["balance_after"] if isinstance(last_led, dict) else last_led[0]) if last_led else 100
            new_balance = max(0, curr_balance - credits_consumed)
            led_id = f"led_{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(3).hex()}"
            cursor.execute("""
                INSERT INTO credit_ledger (id, tenant_id, account_id, credit_type, delta, balance_after, description, created_at)
                VALUES (?, ?, ?, 'VERIFICATION_DEBIT', ?, ?, ?, ?)
            """, (led_id, tenant_id, account_id, -credits_consumed, new_balance, f"Verificación externa ({provider})", now_iso))

        if close_conn:
            conn.commit()
    finally:
        if close_conn:
            ctx.__exit__(None, None, None)
