from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class GoogleWorkspaceAPIError(Exception):
    pass


@dataclass(frozen=True)
class GoogleWorkspaceUser:
    primary_email: str
    full_name: str
    suspended: bool
    org_unit_path: str
    is_admin: bool
    aliases: list[str]


class GoogleWorkspaceClient:
    DIRECTORY_SCOPES = (
        "https://www.googleapis.com/auth/admin.directory.user",
        "https://www.googleapis.com/auth/admin.directory.user.alias",
    )
    LICENSING_SCOPES = ("https://www.googleapis.com/auth/apps.licensing",)

    def __init__(self) -> None:
        self.domain = settings.GOOGLE_WORKSPACE_DOMAIN
        self.admin_email = settings.GOOGLE_WORKSPACE_ADMIN_EMAIL
        self.service_account_file = settings.GOOGLE_SERVICE_ACCOUNT_FILE
        self.service_account_json = settings.GOOGLE_SERVICE_ACCOUNT_JSON
        self.service_account_project_id = settings.GOOGLE_SERVICE_ACCOUNT_PROJECT_ID
        self.service_account_private_key_id = settings.GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_ID
        self.service_account_private_key = settings.GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY
        self.service_account_client_email = settings.GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL
        self.service_account_client_id = settings.GOOGLE_SERVICE_ACCOUNT_CLIENT_ID
        self.service_account_token_uri = settings.GOOGLE_SERVICE_ACCOUNT_TOKEN_URI
        self.default_org_unit = settings.GOOGLE_WORKSPACE_DEFAULT_ORG_UNIT
        self.licensing_enabled = settings.GOOGLE_WORKSPACE_LICENSING_ENABLED
        self.product_id = settings.GOOGLE_WORKSPACE_PRODUCT_ID
        self.sku_id = settings.GOOGLE_WORKSPACE_SKU_ID

        if not self.domain or not self.admin_email or not self._has_service_account_source():
            raise GoogleWorkspaceAPIError(
                "Configure GOOGLE_WORKSPACE_DOMAIN, GOOGLE_WORKSPACE_ADMIN_EMAIL e uma credencial Google via GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SERVICE_ACCOUNT_FILE ou variaveis separadas."
            )

    def _has_service_account_source(self) -> bool:
        if self.service_account_json or self.service_account_file:
            return True
        return all(
            [
                self.service_account_project_id,
                self.service_account_private_key_id,
                self.service_account_private_key,
                self.service_account_client_email,
                self.service_account_client_id,
                self.service_account_token_uri,
            ]
        )

    def _service_account_info_from_env(self) -> dict[str, str]:
        return {
            "type": "service_account",
            "project_id": self.service_account_project_id,
            "private_key_id": self.service_account_private_key_id,
            "private_key": self.service_account_private_key.replace("\\n", "\n"),
            "client_email": self.service_account_client_email,
            "client_id": self.service_account_client_id,
            "token_uri": self.service_account_token_uri,
        }

    def _build_credentials(self, scopes: tuple[str, ...]):
        try:
            if self.service_account_json:
                info = json.loads(self.service_account_json)
                return service_account.Credentials.from_service_account_info(
                    info,
                    scopes=list(scopes),
                    subject=self.admin_email,
                )
            if (
                self.service_account_project_id
                and self.service_account_private_key_id
                and self.service_account_private_key
                and self.service_account_client_email
                and self.service_account_client_id
            ):
                info = self._service_account_info_from_env()
                return service_account.Credentials.from_service_account_info(
                    info,
                    scopes=list(scopes),
                    subject=self.admin_email,
                )
            return service_account.Credentials.from_service_account_file(
                self.service_account_file,
                scopes=list(scopes),
                subject=self.admin_email,
            )
        except json.JSONDecodeError as exc:
            raise GoogleWorkspaceAPIError(
                f"GOOGLE_SERVICE_ACCOUNT_JSON contem JSON invalido: {exc}"
            ) from exc
        except OSError as exc:
            raise GoogleWorkspaceAPIError(
                f"Nao foi possivel ler o arquivo da service account: {exc}"
            ) from exc
        except Exception as exc:  # pragma: no cover
            raise GoogleWorkspaceAPIError(
                f"Nao foi possivel carregar as credenciais Google: {exc}"
            ) from exc

    def _directory_service(self):
        credentials = self._build_credentials(self.DIRECTORY_SCOPES)
        return build("admin", "directory_v1", credentials=credentials, cache_discovery=False)

    def _licensing_service(self):
        credentials = self._build_credentials(self.LICENSING_SCOPES)
        return build("licensing", "v1", credentials=credentials, cache_discovery=False)

    def _execute(self, request):
        try:
            return request.execute()
        except HttpError as exc:
            detail = exc.reason or str(exc)
            raise GoogleWorkspaceAPIError(f"Google Workspace API retornou erro: {detail}") from exc
        except Exception as exc:
            raise GoogleWorkspaceAPIError(f"Falha ao comunicar com Google Workspace: {exc}") from exc

    def _normalize_user(self, payload: dict[str, Any]) -> GoogleWorkspaceUser:
        name = payload.get("name") or {}
        aliases = payload.get("aliases") or []
        return GoogleWorkspaceUser(
            primary_email=payload.get("primaryEmail", ""),
            full_name=name.get("fullName", ""),
            suspended=bool(payload.get("suspended")),
            org_unit_path=payload.get("orgUnitPath") or "/",
            is_admin=bool(payload.get("isAdmin")),
            aliases=aliases,
        )

    def list_users(self, max_results: int = 50, query: str | None = None) -> list[GoogleWorkspaceUser]:
        service = self._directory_service()
        page_size = min(max_results, 500) if max_results else 500
        params: dict[str, Any] = {
            "customer": "my_customer",
            "orderBy": "email",
            "maxResults": page_size,
        }
        if query:
            params["query"] = query

        users: list[GoogleWorkspaceUser] = []
        next_page_token: str | None = None

        while True:
            page_params = dict(params)
            if next_page_token:
                page_params["pageToken"] = next_page_token

            response = self._execute(service.users().list(**page_params))
            users.extend(
                self._normalize_user(item)
                for item in (response.get("users") or [])
            )

            if max_results and len(users) >= max_results:
                return users[:max_results]

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                return users

    def get_user(self, email: str) -> GoogleWorkspaceUser:
        service = self._directory_service()
        response = self._execute(service.users().get(userKey=email))
        return self._normalize_user(response)

    def create_user(
        self,
        primary_email: str,
        password: str,
        first_name: str,
        last_name: str,
        *,
        org_unit_path: str | None = None,
        change_password_at_next_login: bool = True,
    ) -> GoogleWorkspaceUser:
        service = self._directory_service()
        body = {
            "primaryEmail": primary_email,
            "name": {
                "givenName": first_name,
                "familyName": last_name,
            },
            "password": password,
            "changePasswordAtNextLogin": change_password_at_next_login,
        }
        final_org_unit = org_unit_path or self.default_org_unit
        if final_org_unit:
            body["orgUnitPath"] = final_org_unit
        response = self._execute(service.users().insert(body=body))
        user = self._normalize_user(response)
        if self.licensing_enabled:
            self.assign_license(user.primary_email)
        return user

    def update_password(self, email: str, password: str, *, force_reset: bool = True) -> GoogleWorkspaceUser:
        service = self._directory_service()
        response = self._execute(
            service.users().update(
                userKey=email,
                body={
                    "password": password,
                    "changePasswordAtNextLogin": force_reset,
                },
            )
        )
        return self._normalize_user(response)

    def suspend_user(self, email: str) -> GoogleWorkspaceUser:
        service = self._directory_service()
        response = self._execute(service.users().update(userKey=email, body={"suspended": True}))
        return self._normalize_user(response)

    def unsuspend_user(self, email: str) -> GoogleWorkspaceUser:
        service = self._directory_service()
        response = self._execute(service.users().update(userKey=email, body={"suspended": False}))
        return self._normalize_user(response)

    def delete_user(self, email: str) -> None:
        service = self._directory_service()
        self._execute(service.users().delete(userKey=email))

    def list_aliases(self, email: str) -> list[str]:
        service = self._directory_service()
        response = self._execute(service.users().aliases().list(userKey=email))
        aliases = response.get("aliases") or []
        return [item.get("alias") for item in aliases if item.get("alias")]

    def add_alias(self, email: str, alias: str) -> list[str]:
        service = self._directory_service()
        self._execute(service.users().aliases().insert(userKey=email, body={"alias": alias}))
        return self.list_aliases(email)

    def remove_alias(self, email: str, alias: str) -> list[str]:
        service = self._directory_service()
        self._execute(service.users().aliases().delete(userKey=email, alias=alias))
        return self.list_aliases(email)

    def assign_license(self, email: str) -> None:
        if not self.licensing_enabled:
            return
        if not self.product_id or not self.sku_id:
            raise GoogleWorkspaceAPIError(
                "Configure GOOGLE_WORKSPACE_PRODUCT_ID e GOOGLE_WORKSPACE_SKU_ID para atribuir licencas."
            )
        service = self._licensing_service()
        self._execute(
            service.licenseAssignments().insert(
                productId=self.product_id,
                skuId=self.sku_id,
                body={"userId": email},
            )
        )
