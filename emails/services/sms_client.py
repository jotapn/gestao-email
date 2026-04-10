from urllib.parse import quote, urlencode

import requests
from django.conf import settings


class SMSAPIError(Exception):
    pass


class CapitalMobileSMSClient:
    def __init__(self) -> None:
        self.endpoint = getattr(settings, "CAPITAL_MOBILE_SMS_ENDPOINT", "").strip()
        self.user = getattr(settings, "CAPITAL_MOBILE_SMS_USER", "").strip()
        self.password = getattr(settings, "CAPITAL_MOBILE_SMS_PASSWORD", "")
        self.cookie = getattr(settings, "CAPITAL_MOBILE_SMS_COOKIE", "").strip()
        self.timeout = getattr(settings, "REQUEST_TIMEOUT", 30)
        self.max_length = getattr(settings, "CAPITAL_MOBILE_SMS_MAX_LENGTH", 160)

        if not self.endpoint or not self.user or not self.password:
            raise SMSAPIError(
                "Configure CAPITAL_MOBILE_SMS_ENDPOINT, CAPITAL_MOBILE_SMS_USER e CAPITAL_MOBILE_SMS_PASSWORD."
            )

    def send_sms(self, msisdn: str, text: str) -> str:
        normalized_phone = self._normalize_msisdn(msisdn)
        normalized_text = " ".join((text or "").split())
        if not normalized_text:
            raise SMSAPIError("Texto do SMS nao informado.")
        if len(normalized_text) > self.max_length:
            raise SMSAPIError(
                f"O SMS ultrapassa o limite de {self.max_length} caracteres."
            )

        params = {
            "user": self.user,
            "passwd": self.password,
            "msisdn": normalized_phone,
            "sms_text": normalized_text,
        }
        url = f"{self.endpoint}?{urlencode(params, quote_via=quote, safe='')}"
        headers = {"Cookie": self.cookie} if self.cookie else {}

        try:
            response = requests.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SMSAPIError("Falha ao enviar SMS para a Capital Mobile.") from exc

        body = response.text.strip()
        if not body:
            raise SMSAPIError("A API de SMS retornou uma resposta vazia.")
        return body

    @staticmethod
    def build_welcome_message(email: str, access_url: str | None = None, max_length: int = 160) -> str:
        candidates = [f"Bem-vindo! E-mail: {email}."]
        if access_url:
            candidates.insert(0, f"Bem-vindo! E-mail: {email}. Acesso: {access_url}")
            candidates.insert(1, f"Bem-vindo! {email} Acesso: {access_url}")

        for candidate in candidates:
            normalized = " ".join(candidate.split())
            if len(normalized) <= max_length:
                return normalized

        raise SMSAPIError(f"Nao foi possivel montar um SMS com ate {max_length} caracteres.")

    @staticmethod
    def _normalize_msisdn(msisdn: str) -> str:
        digits = "".join(filter(str.isdigit, msisdn or ""))
        if not digits:
            raise SMSAPIError("Numero de telefone nao informado.")
        if not digits.startswith("55"):
            digits = f"55{digits}"
        if len(digits) not in {12, 13}:
            raise SMSAPIError("Numero de telefone invalido para envio de SMS.")
        return digits
