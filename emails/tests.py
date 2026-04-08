from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .forms import EmailCreateForm
from .models import EmailLog, WorkspaceSetting
from .services.cpanel_client import CpanelAPIError, CpanelClient
from .services.google_workspace_client import (
    GoogleWorkspaceClient,
    GoogleWorkspaceUser,
)


class EmailCreateFormTests(TestCase):
    def test_nome_nao_aceita_dominio(self):
        form = EmailCreateForm(data={"nome": "teste@dominio.com", "senha": "12345678", "quota": 100})
        self.assertFalse(form.is_valid())
        self.assertIn("nome", form.errors)


class EmailViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="operador", password="Senha123!")
        self.user.profile.is_admin = False
        self.user.profile.is_system_admin = False
        self.user.profile.save()
        self.admin = User.objects.create_user(username="admin", password="Senha123!")
        self.admin.profile.is_admin = True
        self.admin.profile.is_system_admin = False
        self.admin.profile.save()
        self.system_admin = User.objects.create_user(username="rootadmin", password="Senha123!")
        self.system_admin.profile.is_admin = False
        self.system_admin.profile.is_system_admin = True
        self.system_admin.profile.save()

    @patch("emails.views.CpanelClient")
    def test_home_renderiza_contas(self, client_cls):
        self.client.force_login(self.user)
        client_cls.return_value.list_accounts.return_value = [
            {"user": "admcnxtelco", "domain": "cnxtel.com.br", "label": "admcnxtelco - cnxtel.com.br"}
        ]
        client_cls.return_value.list_emails.return_value = [
            {"email": "ativo@cnxtel.com.br", "suspended_login": 0, "suspended_incoming": 0, "outgoing": 0},
            {"email": "travado@cnxtel.com.br", "suspended_login": 1, "suspended_incoming": 0, "outgoing": 0},
        ]
        response = self.client.get(reverse("account-list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cnxtel.com.br")
        self.assertContains(response, "Criar e-mail")

    @patch("emails.views.CpanelClient")
    def test_lista_renderiza_emails(self, client_cls):
        self.client.force_login(self.user)
        root_client = client_cls.return_value
        managed_client = client_cls.return_value
        root_client.list_accounts.return_value = [
            {"user": "admcnxtelco", "domain": "cnxtel.com.br", "label": "admcnxtelco - cnxtel.com.br"}
        ]
        managed_client.list_emails.return_value = [
            {"email": "contato@exemplo.com", "diskused": 10, "diskquota": 1024}
        ]
        response = self.client.get(reverse("email-list", args=["admcnxtelco"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "contato@exemplo.com")

    @patch("emails.views.CpanelClient")
    def test_lista_filtra_por_busca_e_status(self, client_cls):
        self.client.force_login(self.user)
        root_client = client_cls.return_value
        managed_client = client_cls.return_value
        root_client.list_accounts.return_value = [
            {"user": "admcnxtelco", "domain": "cnxtel.com.br", "label": "admcnxtelco - cnxtel.com.br"}
        ]
        managed_client.list_emails.return_value = [
            {"email": "financeiro@cnxtel.com.br", "suspended_login": 0, "suspended_incoming": 0, "suspended_outgoing": 0},
            {"email": "contato@cnxtel.com.br", "suspended_login": 1, "suspended_incoming": 0, "suspended_outgoing": 0},
        ]
        response = self.client.get(reverse("email-list", args=["admcnxtelco"]), {"q": "contato", "status": "login"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "contato@cnxtel.com.br")
        self.assertNotContains(response, "financeiro@cnxtel.com.br")

    @patch("emails.views.CpanelClient")
    def test_url_da_conta_prioriza_usuario_mesmo_com_sessao_antiga(self, client_cls):
        self.client.force_login(self.user)
        root_client = client_cls.return_value
        managed_client = client_cls.return_value
        root_client.list_accounts.return_value = [
            {"user": "oratelecom", "domain": "oratelecom.com.br", "label": "oratelecom - oratelecom.com.br"},
            {"user": "mercadodoprovedo", "domain": "mercadodoprovedo.com.br", "label": "mercadodoprovedo - mercadodoprovedo.com.br"},
        ]
        managed_client.list_emails.return_value = []
        session = self.client.session
        session["selected_cpanel_user"] = "oratelecom"
        session["selected_cpanel_domain"] = "oratelecom.com.br"
        session.save()
        response = self.client.get(reverse("email-list", args=["mercadodoprovedo"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "mercadodoprovedo.com.br")

    @patch("emails.views.CpanelClient")
    def test_acao_alterar_senha(self, client_cls):
        self.client.force_login(self.user)
        client_cls.return_value.change_password.return_value = {"status": 1}
        response = self.client.post(
            reverse("email-action", args=["admcnxtelco", "contato@cnxtel.com.br"]),
            {"account": "admcnxtelco", "domain": "cnxtel.com.br", "action": "change_password", "password": "Senha1234"},
        )
        self.assertEqual(response.status_code, 302)
        client_cls.return_value.change_password.assert_called_once_with(email="contato", domain="cnxtel.com.br", password="Senha1234")

    @patch("emails.views.CpanelClient")
    def test_suspender_login_nao_acessa_cleaned_data_de_senha(self, client_cls):
        self.client.force_login(self.user)
        client_cls.return_value.suspend_user.return_value = {"status": 1}
        response = self.client.post(
            reverse("email-action", args=["admcnxtelco", "contato@cnxtel.com.br"]),
            {"account": "admcnxtelco", "domain": "cnxtel.com.br", "action": "suspend_user"},
        )
        self.assertEqual(response.status_code, 302)
        client_cls.return_value.suspend_user.assert_called_once_with(full_email="contato@cnxtel.com.br")


class CpanelCompositeActionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="operador2", password="Senha123!")
        self.user.profile.is_admin = False
        self.user.profile.is_system_admin = False
        self.user.profile.save()
        self.admin = User.objects.create_user(username="admin2", password="Senha123!")
        self.admin.profile.is_admin = True
        self.admin.profile.is_system_admin = False
        self.admin.profile.save()
        self.system_admin = User.objects.create_user(username="sysadmin2", password="Senha123!")
        self.system_admin.profile.is_admin = False
        self.system_admin.profile.is_system_admin = True
        self.system_admin.profile.save()

    def test_suspend_user_chama_tres_suspensoes(self):
        client = CpanelClient.__new__(CpanelClient)
        calls = []
        client.suspend_login = lambda email: calls.append(("login", email))
        client.suspend_outgoing = lambda email: calls.append(("outgoing", email))
        client.suspend_incoming = lambda email: calls.append(("incoming", email))

        result = CpanelClient.suspend_user(client, "contato@cnxtel.com.br")

        self.assertEqual(result["status"], 1)
        self.assertEqual(
            calls,
            [
                ("login", "contato@cnxtel.com.br"),
                ("outgoing", "contato@cnxtel.com.br"),
                ("incoming", "contato@cnxtel.com.br"),
            ],
        )

    def test_unsuspend_user_chama_tres_reativacoes(self):
        client = CpanelClient.__new__(CpanelClient)
        calls = []
        client.unsuspend_login = lambda email: calls.append(("login", email))
        client.unsuspend_outgoing = lambda email: calls.append(("outgoing", email))
        client.unsuspend_incoming = lambda email: calls.append(("incoming", email))

        result = CpanelClient.unsuspend_user(client, "contato@cnxtel.com.br")

        self.assertEqual(result["status"], 1)
        self.assertEqual(
            calls,
            [
                ("login", "contato@cnxtel.com.br"),
                ("outgoing", "contato@cnxtel.com.br"),
                ("incoming", "contato@cnxtel.com.br"),
            ],
        )

    def test_logs_exigem_admin(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("email-log"))
        self.assertEqual(response.status_code, 302)

    def test_admin_pode_ver_logs(self):
        EmailLog.objects.create(usuario=self.admin, email="teste@cnxtel.com.br", acao="criado", status="sucesso")
        self.client.force_login(self.admin)
        response = self.client.get(reverse("email-log"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "admin")

    def test_configuracao_workspace_exige_admin(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("workspace-settings"))
        self.assertEqual(response.status_code, 302)

    def test_admin_comum_nao_pode_configurar_workspace(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("workspace-settings"))
        self.assertEqual(response.status_code, 302)

    @patch("emails.views.send_mail")
    def test_admin_cria_usuario_e_dispara_email(self, send_mail_mock):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("user-create"),
            {
                "username": "novo",
                "first_name": "Novo",
                "last_name": "Usuario",
                "email": "novo@cnxtel.com.br",
                "password": "Senha123!",
                "is_active": "on",
                "role": "operator",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="novo").exists())
        send_mail_mock.assert_called_once()

    def test_admin_salva_limite_workspace(self):
        self.client.force_login(self.system_admin)
        response = self.client.post(
            reverse("workspace-settings"),
            {
                "google_workspace_user_limit": 120,
                "google_workspace_alert_email": "sistemas@oratelecom.com.br",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(WorkspaceSetting.get_solo().google_workspace_user_limit, 120)
        self.assertEqual(WorkspaceSetting.get_solo().google_workspace_alert_email, "sistemas@oratelecom.com.br")
        self.assertTrue(EmailLog.objects.filter(acao="configurar workspace google", usuario=self.system_admin).exists())


class CpanelClientTests(TestCase):
    def test_delete_timeout_but_missing_afterwards_is_treated_as_success(self):
        client = CpanelClient.__new__(CpanelClient)
        client.timeout = 30
        client.mode = "cpanel"
        client.domain = "cnxtel.com.br"

        calls = []

        def fake_uapi(module, function, params=None, timeout=None):
            calls.append((module, function, params, timeout))
            if module == "Email" and function == "delete_pop":
                raise CpanelAPIError("Falha na comunicacao com o cPanel: Read timed out.")
            if module == "Email" and function == "list_pops_with_disk":
                return {"data": []}
            raise AssertionError((module, function))

        client._uapi = fake_uapi
        result = CpanelClient.delete_email(client, "teste", "cnxtel.com.br")
        self.assertEqual(result["status"], 1)
        self.assertEqual(calls[0][3], 60)

    def test_delete_timeout_and_email_still_exists_raises_error(self):
        client = CpanelClient.__new__(CpanelClient)
        client.timeout = 30
        client.mode = "cpanel"
        client.domain = "cnxtel.com.br"

        def fake_uapi(module, function, params=None, timeout=None):
            if module == "Email" and function == "delete_pop":
                raise CpanelAPIError("Falha na comunicacao com o cPanel: Read timed out.")
            if module == "Email" and function == "list_pops_with_disk":
                return {"data": [{"email": "teste@cnxtel.com.br"}]}
            raise AssertionError((module, function))

        client._uapi = fake_uapi
        with self.assertRaises(CpanelAPIError):
            CpanelClient.delete_email(client, "teste", "cnxtel.com.br")


class GoogleWorkspaceClientTests(TestCase):
    @patch("emails.services.google_workspace_client.build")
    @patch("emails.services.google_workspace_client.service_account.Credentials.from_service_account_file")
    def test_list_users_normaliza_resposta(self, credentials_mock, build_mock):
        service = MagicMock()
        build_mock.return_value = service
        credentials_mock.return_value = object()
        service.users.return_value.list.return_value.execute.return_value = {
            "users": [
                {
                    "primaryEmail": "ana@oratelecom.com.br",
                    "suspended": False,
                    "orgUnitPath": "/Atendimento",
                    "isAdmin": False,
                    "aliases": ["contato@oratelecom.com.br"],
                    "name": {"fullName": "Ana Silva"},
                }
            ]
        }

        with patch.multiple(
            "django.conf.settings",
            GOOGLE_WORKSPACE_DOMAIN="oratelecom.com.br",
            GOOGLE_WORKSPACE_ADMIN_EMAIL="padua.costa@oratelecom.com.br",
            GOOGLE_SERVICE_ACCOUNT_FILE="C:/credenciais/google.json",
            GOOGLE_WORKSPACE_DEFAULT_ORG_UNIT="",
            GOOGLE_WORKSPACE_LICENSING_ENABLED=False,
            GOOGLE_WORKSPACE_PRODUCT_ID="",
            GOOGLE_WORKSPACE_SKU_ID="",
        ):
            users = GoogleWorkspaceClient().list_users(max_results=5)

        self.assertEqual(len(users), 1)
        self.assertEqual(users[0].primary_email, "ana@oratelecom.com.br")
        self.assertEqual(users[0].aliases, ["contato@oratelecom.com.br"])


class GoogleWorkspaceViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="operador_google", password="Senha123!")
        self.user.profile.is_admin = False
        self.user.profile.is_system_admin = False
        self.user.profile.save()

    @patch("emails.views.GoogleWorkspaceClient")
    def test_google_dashboard_renderiza_indicadores(self, client_cls):
        self.client.force_login(self.user)
        WorkspaceSetting.get_solo().delete()
        client_cls.return_value.list_users.return_value = [
            GoogleWorkspaceUser(
                primary_email="ativo@oratelecom.com.br",
                full_name="Ativo",
                suspended=False,
                org_unit_path="/",
                is_admin=False,
                aliases=[],
            ),
            GoogleWorkspaceUser(
                primary_email="suspenso@oratelecom.com.br",
                full_name="Suspenso",
                suspended=True,
                org_unit_path="/",
                is_admin=False,
                aliases=[],
            ),
        ]

        response = self.client.get(reverse("google-dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Google Workspace")
        self.assertContains(response, "2")

    @patch("emails.views.send_mail")
    @patch("emails.views.GoogleWorkspaceClient")
    def test_google_dashboard_envia_email_quando_atinge_limite(self, client_cls, send_mail_mock):
        self.client.force_login(self.user)
        setting = WorkspaceSetting.get_solo()
        setting.google_workspace_user_limit = 2
        setting.google_workspace_alert_email = "alerta@oratelecom.com.br"
        setting.save()
        client_cls.return_value.list_users.return_value = [
            GoogleWorkspaceUser(
                primary_email="um@oratelecom.com.br",
                full_name="Um",
                suspended=False,
                org_unit_path="/",
                is_admin=False,
                aliases=[],
            ),
            GoogleWorkspaceUser(
                primary_email="dois@oratelecom.com.br",
                full_name="Dois",
                suspended=False,
                org_unit_path="/",
                is_admin=False,
                aliases=[],
            ),
        ]

        response = self.client.get(reverse("google-dashboard"))

        self.assertEqual(response.status_code, 200)
        send_mail_mock.assert_called_once()
        self.assertEqual(send_mail_mock.call_args.kwargs["recipient_list"], ["alerta@oratelecom.com.br"])
        setting.refresh_from_db()
        self.assertIsNotNone(setting.limit_reached_email_sent_at)

    @patch("emails.views.send_mail")
    @patch("emails.views.GoogleWorkspaceClient")
    def test_google_dashboard_mostra_aviso_quando_faltam_duas_vagas(self, client_cls, send_mail_mock):
        self.client.force_login(self.user)
        setting = WorkspaceSetting.get_solo()
        setting.google_workspace_user_limit = 5
        setting.limit_reached_email_sent_at = None
        setting.save()
        client_cls.return_value.list_users.return_value = [
            GoogleWorkspaceUser(
                primary_email="1@oratelecom.com.br",
                full_name="Um",
                suspended=False,
                org_unit_path="/",
                is_admin=False,
                aliases=[],
            ),
            GoogleWorkspaceUser(
                primary_email="2@oratelecom.com.br",
                full_name="Dois",
                suspended=False,
                org_unit_path="/",
                is_admin=False,
                aliases=[],
            ),
            GoogleWorkspaceUser(
                primary_email="3@oratelecom.com.br",
                full_name="Tres",
                suspended=False,
                org_unit_path="/",
                is_admin=False,
                aliases=[],
            ),
        ]

        response = self.client.get(reverse("google-dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "restam 2 vaga")
        send_mail_mock.assert_not_called()

    @patch("emails.views.GoogleWorkspaceClient")
    def test_google_lista_filtra_por_status(self, client_cls):
        self.client.force_login(self.user)
        client_cls.return_value.list_users.return_value = [
            GoogleWorkspaceUser(
                primary_email="ativo@oratelecom.com.br",
                full_name="Ativo",
                suspended=False,
                org_unit_path="/",
                is_admin=False,
                aliases=[],
            ),
            GoogleWorkspaceUser(
                primary_email="suspenso@oratelecom.com.br",
                full_name="Suspenso",
                suspended=True,
                org_unit_path="/",
                is_admin=False,
                aliases=[],
            ),
        ]

        response = self.client.get(reverse("google-user-list"), {"status": "suspended"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "suspenso@oratelecom.com.br")
        self.assertNotContains(response, "ativo@oratelecom.com.br")

    @patch("emails.views.GoogleWorkspaceClient")
    def test_google_cria_usuario(self, client_cls):
        self.client.force_login(self.user)
        client_cls.return_value.create_user.return_value = GoogleWorkspaceUser(
            primary_email="novo@oratelecom.com.br",
            full_name="Novo Usuario",
            suspended=False,
            org_unit_path="/",
            is_admin=False,
            aliases=[],
        )

        response = self.client.post(
            reverse("google-user-create"),
            {
                "nome": "novo",
                "first_name": "Novo",
                "last_name": "Usuario",
                "senha": "Senha123!",
            },
        )

        self.assertEqual(response.status_code, 302)
        client_cls.return_value.create_user.assert_called_once()

    @patch("emails.views.GoogleWorkspaceClient")
    def test_google_suspende_usuario(self, client_cls):
        self.client.force_login(self.user)
        client_cls.return_value.suspend_user.return_value = GoogleWorkspaceUser(
            primary_email="novo@oratelecom.com.br",
            full_name="Novo Usuario",
            suspended=True,
            org_unit_path="/",
            is_admin=False,
            aliases=[],
        )

        response = self.client.post(
            reverse("google-user-action", args=["novo@oratelecom.com.br"]),
            {"action": "suspend_user"},
        )

        self.assertEqual(response.status_code, 302)
        client_cls.return_value.suspend_user.assert_called_once_with(email="novo@oratelecom.com.br")
