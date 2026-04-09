from __future__ import annotations

from typing import Any

import requests
from django.conf import settings
from requests import RequestException
from requests.adapters import HTTPAdapter

try:
    from urllib3 import disable_warnings
    from urllib3.exceptions import InsecureRequestWarning
except ImportError:  # pragma: no cover
    disable_warnings = None
    InsecureRequestWarning = None


class CpanelAPIError(Exception):
    pass


class CpanelClient:
    _shared_session: requests.Session | None = None

    def __init__(self, cpanel_user: str | None = None, domain: str | None = None) -> None:
        self.timeout = settings.REQUEST_TIMEOUT

        self.whm_host = settings.WHM_HOST.rstrip("/") if settings.WHM_HOST else ""
        self.whm_user = settings.WHM_USER
        self.whm_token = settings.WHM_TOKEN
        self.whm_verify_ssl = settings.WHM_VERIFY_SSL

        self.cpanel_host = settings.CPANEL_HOST.rstrip("/") if settings.CPANEL_HOST else ""
        self.cpanel_user = cpanel_user or settings.CPANEL_USER
        self.cpanel_token = settings.CPANEL_TOKEN
        self.domain = domain or settings.CPANEL_DOMAIN
        self.cpanel_verify_ssl = settings.CPANEL_VERIFY_SSL

        self.mode = "whm" if all([self.whm_host, self.whm_user, self.whm_token]) else "cpanel"

        if self.mode != "whm":
            if not all([self.cpanel_host, self.cpanel_user, self.cpanel_token]):
                raise CpanelAPIError(
                    "Configure WHM_HOST/WHM_USER/WHM_TOKEN ou CPANEL_HOST/CPANEL_USER/CPANEL_TOKEN no .env."
                )

        if not self.whm_verify_ssl and disable_warnings and InsecureRequestWarning:
            disable_warnings(InsecureRequestWarning)
        if not self.cpanel_verify_ssl and disable_warnings and InsecureRequestWarning:
            disable_warnings(InsecureRequestWarning)

    @property
    def uses_whm(self) -> bool:
        return self.mode == "whm"

    def _require_domain(self, domain: str | None = None) -> str:
        final_domain = domain or self.domain
        if not final_domain:
            raise CpanelAPIError("Selecione um dominio para gerenciar as caixas de e-mail.")
        return final_domain

    def _request(
        self,
        url: str,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        timeout: int | None = None,
        verify_ssl: bool = True,
    ) -> dict[str, Any]:
        try:
            response = self._get_session().get(
                url,
                params=params or {},
                headers=headers,
                timeout=timeout or self.timeout,
                verify=verify_ssl,
            )
            response.raise_for_status()
            return response.json()
        except RequestException as exc:
            detail = str(exc).strip()
            if detail:
                raise CpanelAPIError(f"Falha na comunicacao com o servidor: {detail}") from exc
            raise CpanelAPIError("Falha na comunicacao com o servidor.") from exc
        except ValueError as exc:
            raise CpanelAPIError("O servidor retornou uma resposta JSON invalida.") from exc

    @classmethod
    def _get_session(cls) -> requests.Session:
        if cls._shared_session is None:
            session = requests.Session()
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            cls._shared_session = session
        return cls._shared_session

    def _whm_get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        url = f"{self.whm_host}/json-api/{endpoint}"
        payload = self._request(
            url=url,
            headers={"Authorization": f"whm {self.whm_user}:{self.whm_token}"},
            params={"api.version": 1, **(params or {})},
            timeout=timeout,
            verify_ssl=self.whm_verify_ssl,
        )
        metadata = payload.get("metadata") or {}
        if metadata.get("result") not in (None, 1):
            raise CpanelAPIError(metadata.get("reason") or "Erro ao executar chamada WHM API.")
        return payload

    def _cpanel_get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        url = f"{self.cpanel_host}/execute/{endpoint}"
        payload = self._request(
            url=url,
            headers={"Authorization": f"cpanel {self.cpanel_user}:{self.cpanel_token}"},
            params=params,
            timeout=timeout,
            verify_ssl=self.cpanel_verify_ssl,
        )
        return self._validate_uapi_payload(payload)

    def _validate_uapi_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        errors = payload.get("errors") or []
        if errors:
            raise CpanelAPIError("; ".join(errors))

        status = payload.get("status")
        if status not in (None, 1):
            raise CpanelAPIError(payload.get("message") or "Resposta invalida da UAPI.")

        return payload

    def _uapi(
        self,
        module: str,
        function: str,
        params: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        if self.uses_whm:
            if not self.cpanel_user:
                raise CpanelAPIError("Selecione uma conta cPanel para gerenciar.")

            payload = self._whm_get(
                "uapi_cpanel",
                {
                    "cpanel.user": self.cpanel_user,
                    "cpanel.module": module,
                    "cpanel.function": function,
                    **(params or {}),
                },
                timeout=timeout,
            )
            data = payload.get("data") or {}
            uapi_payload = data.get("uapi") or {}
            return self._validate_uapi_payload(uapi_payload)

        return self._cpanel_get(f"{module}/{function}", params=params, timeout=timeout)

    def list_accounts(self) -> list[dict[str, Any]]:
        if self.uses_whm:
            payload = self._whm_get("listaccts")
            data = payload.get("data") or {}
            accounts = data.get("acct") or []
            normalized = []
            for item in accounts:
                user = item.get("user")
                domain = item.get("domain")
                if not user or not domain:
                    continue
                if domain.strip().lower() in settings.HIDDEN_CPANEL_DOMAINS:
                    continue
                normalized.append(
                    {
                        **item,
                        "user": user,
                        "domain": domain,
                        "label": f"{user} - {domain}",
                    }
                )
            return normalized

        if self.domain:
            if self.domain.strip().lower() in settings.HIDDEN_CPANEL_DOMAINS:
                return []
            return [
                {
                    "user": self.cpanel_user,
                    "domain": self.domain,
                    "label": f"{self.cpanel_user} - {self.domain}",
                }
            ]
        return []

    def list_emails(self, domain: str | None = None) -> list[dict[str, Any]]:
        payload = self._uapi("Email", "list_pops_with_disk", {"domain": self._require_domain(domain)})
        return payload.get("data") or []

    def create_email(
        self,
        email: str,
        password: str,
        quota: int = 1024,
        domain: str | None = None,
    ) -> dict[str, Any]:
        final_domain = self._require_domain(domain)
        return self._uapi(
            "Email",
            "add_pop",
            {"email": email, "domain": final_domain, "password": password, "quota": quota},
        )

    def suspend_login(self, full_email: str) -> dict[str, Any]:
        return self._uapi("Email", "suspend_login", {"email": full_email})

    def unsuspend_login(self, full_email: str) -> dict[str, Any]:
        return self._uapi("Email", "unsuspend_login", {"email": full_email})

    def suspend_outgoing(self, full_email: str) -> dict[str, Any]:
        return self._uapi("Email", "suspend_outgoing", {"email": full_email})

    def suspend_incoming(self, full_email: str) -> dict[str, Any]:
        return self._uapi("Email", "suspend_incoming", {"email": full_email})

    def unsuspend_incoming(self, full_email: str) -> dict[str, Any]:
        return self._uapi("Email", "unsuspend_incoming", {"email": full_email})

    def unsuspend_outgoing(self, full_email: str) -> dict[str, Any]:
        return self._uapi("Email", "unsuspend_outgoing", {"email": full_email})

    def suspend_user(self, full_email: str) -> dict[str, Any]:
        self.suspend_login(full_email)
        self.suspend_outgoing(full_email)
        self.suspend_incoming(full_email)
        return {"status": 1}

    def unsuspend_user(self, full_email: str) -> dict[str, Any]:
        self.unsuspend_login(full_email)
        self.unsuspend_outgoing(full_email)
        self.unsuspend_incoming(full_email)
        return {"status": 1}

    def change_password(self, email: str, password: str, domain: str) -> dict[str, Any]:
        return self._uapi(
            "Email",
            "passwd_pop",
            {"email": email, "domain": domain, "password": password},
        )

    def delete_email(self, email: str, domain: str) -> dict[str, Any]:
        delete_timeout = max(self.timeout, 60)
        try:
            return self._uapi(
                "Email",
                "delete_pop",
                {"email": email, "domain": domain},
                timeout=delete_timeout,
            )
        except CpanelAPIError as exc:
            message = str(exc)
            if "timed out" not in message.lower():
                raise

            full_email = f"{email}@{domain}"
            try:
                current_emails = self.list_emails(domain)
            except CpanelAPIError:
                raise CpanelAPIError(
                    f"A exclusao de {full_email} excedeu o tempo limite. "
                    "Nao foi possivel confirmar se a conta foi removida."
                ) from exc

            exists = any(item.get("email") == full_email for item in current_emails)
            if not exists:
                return {
                    "status": 1,
                    "data": None,
                    "warnings": [
                        f"O servidor demorou para responder, mas {full_email} nao aparece mais na listagem."
                    ],
                }

            raise CpanelAPIError(
                f"O servidor excedeu o tempo limite ao excluir {full_email}. "
                "A conta ainda aparece na listagem."
            ) from exc
