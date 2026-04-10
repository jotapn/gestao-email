from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import EmailCreateForm, SystemUserForm
from .models import EmailLog, WorkspaceSetting
from .services.cpanel_client import CpanelAPIError, CpanelClient
from .services.google_workspace_client import (
    GoogleWorkspaceClient,
    GoogleWorkspaceUser,
)
from .services.sms_client import CapitalMobileSMSClient


class EmailCreateFormTests(TestCase):
    def test_nome_nao_aceita_dominio(self):
        form = EmailCreateForm(data={"nome": "teste@dominio.com", "senha": "12345678", "quota": 100})
        self.assertFalse(form.is_valid())
        self.assertIn("nome", form.errors)

    def test_telefone_monta_msisdn_quando_ddd_e_numero_sao_informados(self):
        form = EmailCreateForm(
            data={
                "nome": "teste",
                "senha": "Senha123!",
                "quota": 100,
                "telefone_ddd": "(86)",
                "telefone_numero": "9 0018-315",
            }
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["telefone_completo"], "558690018315")

    def test_telefone_exige_ddd_e_numero_juntos(self):
        form = EmailCreateForm(
            data={"nome": "teste", "senha": "Senha123!", "quota": 100, "telefone_ddd": "86"}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("telefone_numero", form.errors)

    def test_google_form_monta_msisdn_quando_ddd_e_numero_sao_informados(self):
        from .forms import GoogleWorkspaceUserCreateForm

        form = GoogleWorkspaceUserCreateForm(
            data={
                "nome": "teste",
                "first_name": "Teste",
                "last_name": "Usuario",
                "senha": "Senha123!",
                "telefone_ddd": "(86)",
                "telefone_numero": "9 0018-315",
            }
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["telefone_completo"], "558690018315")

    def test_admin_comum_nao_ve_opcao_admin_do_sistema_no_formulario(self):
        admin = User.objects.create_user(username="admin_form", password="Senha123!")
        admin.profile.is_admin = True
        admin.profile.is_system_admin = False
        admin.profile.save()

        form = SystemUserForm(current_user=admin)

        self.assertNotIn(("system_admin", "Admin do sistema"), form.fields["role"].choices)


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
    def test_lista_ordena_por_status(self, client_cls):
        self.client.force_login(self.user)
        root_client = client_cls.return_value
        managed_client = client_cls.return_value
        root_client.list_accounts.return_value = [
            {"user": "admcnxtelco", "domain": "cnxtel.com.br", "label": "admcnxtelco - cnxtel.com.br"}
        ]
        managed_client.list_emails.return_value = [
            {"email": "ativo@cnxtel.com.br", "suspended_login": 0, "suspended_incoming": 0, "suspended_outgoing": 0},
            {"email": "suspenso@cnxtel.com.br", "suspended_login": 1, "suspended_incoming": 0, "suspended_outgoing": 0},
        ]

        response = self.client.get(
            reverse("email-list", args=["admcnxtelco"]),
            {"sort": "status", "dir": "desc"},
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertLess(content.index("suspenso@cnxtel.com.br"), content.index("ativo@cnxtel.com.br"))

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

    @patch("emails.views.CapitalMobileSMSClient")
    @patch("emails.views.CpanelClient")
    def test_criar_email_envia_sms_quando_telefone_for_informado(self, client_cls, sms_client_cls):
        self.client.force_login(self.user)
        root_client = client_cls.return_value
        managed_client = client_cls.return_value
        root_client.list_accounts.return_value = [
            {"user": "admcnxtelco", "domain": "cnxtel.com.br", "label": "admcnxtelco - cnxtel.com.br"}
        ]
        managed_client.create_email.return_value = {"status": 1}
        sms_client_cls.return_value.build_welcome_message.return_value = "mensagem sms"

        response = self.client.post(
            reverse("email-create", args=["admcnxtelco"]),
            {
                "account": "admcnxtelco",
                "domain": "cnxtel.com.br",
                "nome": "novo",
                "senha": "Senha123!",
                "quota": 1024,
                "telefone_ddd": "86",
                "telefone_numero": "90018315",
            },
        )

        self.assertEqual(response.status_code, 302)
        managed_client.create_email.assert_called_once_with(
            email="novo", password="Senha123!", quota=1024, domain="cnxtel.com.br"
        )
        sms_client_cls.return_value.build_welcome_message.assert_called_once_with(
            email="novo@cnxtel.com.br",
            access_url="https://webmail.cnxtel.com.br",
            max_length=160,
        )
        sms_client_cls.return_value.send_sms.assert_called_once_with("558690018315", "mensagem sms")

    @patch("emails.views.CapitalMobileSMSClient")
    @patch("emails.views.CpanelClient")
    def test_criar_email_mantem_sucesso_quando_sms_falha(self, client_cls, sms_client_cls):
        self.client.force_login(self.user)
        root_client = client_cls.return_value
        managed_client = client_cls.return_value
        root_client.list_accounts.return_value = [
            {"user": "admcnxtelco", "domain": "cnxtel.com.br", "label": "admcnxtelco - cnxtel.com.br"}
        ]
        managed_client.create_email.return_value = {"status": 1}
        sms_client_cls.return_value.send_sms.side_effect = Exception("falhou")

        response = self.client.post(
            reverse("email-create", args=["admcnxtelco"]),
            {
                "account": "admcnxtelco",
                "domain": "cnxtel.com.br",
                "nome": "novo",
                "senha": "Senha123!",
                "quota": 1024,
                "telefone_ddd": "86",
                "telefone_numero": "90018315",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "E-mail novo@cnxtel.com.br criado com sucesso, mas o SMS nao foi enviado.")

    @override_settings(GOOGLE_WORKSPACE_DOMAIN="oratelecom.com.br")
    def test_sms_helper_usa_link_do_gmail_para_dominio_google(self):
        from .views import _email_access_url

        self.assertEqual(_email_access_url("oratelecom.com.br"), "https://mail.google.com/")

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

    @patch("emails.views.CpanelClient")
    def test_acao_email_preserva_filtros_no_redirect(self, client_cls):
        self.client.force_login(self.user)
        client_cls.return_value.suspend_user.return_value = {"status": 1}

        response = self.client.post(
            reverse("email-action", args=["admcnxtelco", "contato@cnxtel.com.br"]),
            {
                "account": "admcnxtelco",
                "domain": "cnxtel.com.br",
                "action": "suspend_user",
                "q": "emailteste",
                "status": "active",
                "page": "2",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            f"{reverse('email-list', args=['admcnxtelco'])}?q=emailteste&status=active&page=2",
        )

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_password_reset_envia_email_para_usuario_interno(self):
        self.user.email = "operador@cnxtel.com.br"
        self.user.save(update_fields=["email"])

        response = self.client.post(reverse("password_reset"), {"email": "operador@cnxtel.com.br"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("redefini", mail.outbox[0].subject.lower())


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
        self.assertContains(response, '<select id="user" name="user" class="form-select">', html=False)

    def test_logs_filtram_por_usuario_email_status_e_periodo(self):
        EmailLog.objects.create(usuario=self.admin, email="ativo@cnxtel.com.br", acao="criado", status="sucesso")
        EmailLog.objects.create(usuario=self.admin, email="erro@cnxtel.com.br", acao="suspender usuario", status="erro")
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("email-log"),
            {
                "user": "admin",
                "email": "erro@cnxtel.com.br",
                "status": "erro",
                "date_from": timezone.localdate().isoformat(),
                "date_to": timezone.localdate().isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "erro@cnxtel.com.br")
        self.assertNotContains(response, "ativo@cnxtel.com.br")

    def test_logs_ordenam_por_email(self):
        EmailLog.objects.create(usuario=self.admin, email="zeta@cnxtel.com.br", acao="criado", status="sucesso")
        EmailLog.objects.create(usuario=self.admin, email="alfa@cnxtel.com.br", acao="criado", status="sucesso")
        self.client.force_login(self.admin)

        response = self.client.get(reverse("email-log"), {"sort": "email", "dir": "asc"})

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertLess(content.index("alfa@cnxtel.com.br"), content.index("zeta@cnxtel.com.br"))

    def test_configuracao_workspace_exige_admin(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("workspace-settings"))
        self.assertEqual(response.status_code, 302)

    def test_admin_comum_nao_pode_configurar_workspace(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("workspace-settings"))
        self.assertEqual(response.status_code, 302)

    @patch("emails.views.EmailMultiAlternatives")
    def test_admin_cria_usuario_e_dispara_email(self, email_mock):
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
        email_mock.assert_called_once()
        email_mock.return_value.attach_alternative.assert_called_once()
        email_mock.return_value.send.assert_called_once()

    def test_admin_nao_pode_criar_usuario_como_admin_do_sistema(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("user-create"),
            {
                "username": "bloqueado",
                "first_name": "Bloqueado",
                "last_name": "Sistema",
                "email": "bloqueado@cnxtel.com.br",
                "password": "Senha123!",
                "is_active": "on",
                "role": "system_admin",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="bloqueado").exists())
        self.assertContains(response, "system_admin")

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


class SMSClientTests(TestCase):
    def test_build_welcome_message_respeita_limite(self):
        message = CapitalMobileSMSClient.build_welcome_message(
            email="novo@cnxtel.com.br",
            access_url="https://webmail.cnxtel.com.br",
            max_length=160,
        )
        self.assertLessEqual(len(message), 160)
        self.assertIn("novo@cnxtel.com.br", message)


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
    @patch("emails.services.google_workspace_client.service_account.Credentials.from_service_account_info")
    def test_list_users_aceita_credenciais_google_em_variaveis_separadas(self, credentials_mock, build_mock):
        service = MagicMock()
        build_mock.return_value = service
        credentials_mock.return_value = object()
        service.users.return_value.list.return_value.execute.return_value = {"users": []}

        with patch.multiple(
            "django.conf.settings",
            GOOGLE_WORKSPACE_DOMAIN="oratelecom.com.br",
            GOOGLE_WORKSPACE_ADMIN_EMAIL="padua.costa@oratelecom.com.br",
            GOOGLE_SERVICE_ACCOUNT_FILE="",
            GOOGLE_SERVICE_ACCOUNT_JSON="",
            GOOGLE_SERVICE_ACCOUNT_PROJECT_ID="teste",
            GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_ID="abc",
            GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----\\n",
            GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL="bot@teste.iam.gserviceaccount.com",
            GOOGLE_SERVICE_ACCOUNT_CLIENT_ID="123",
            GOOGLE_SERVICE_ACCOUNT_TOKEN_URI="https://oauth2.googleapis.com/token",
            GOOGLE_WORKSPACE_DEFAULT_ORG_UNIT="",
            GOOGLE_WORKSPACE_LICENSING_ENABLED=False,
            GOOGLE_WORKSPACE_PRODUCT_ID="",
            GOOGLE_WORKSPACE_SKU_ID="",
        ):
            GoogleWorkspaceClient().list_users(max_results=5)

        credentials_mock.assert_called_once()

    @patch("emails.services.google_workspace_client.build")
    @patch("emails.services.google_workspace_client.service_account.Credentials.from_service_account_info")
    def test_list_users_aceita_json_em_variavel_de_ambiente(self, credentials_mock, build_mock):
        service = MagicMock()
        build_mock.return_value = service
        credentials_mock.return_value = object()
        service.users.return_value.list.return_value.execute.return_value = {"users": []}

        with patch.multiple(
            "django.conf.settings",
            GOOGLE_WORKSPACE_DOMAIN="oratelecom.com.br",
            GOOGLE_WORKSPACE_ADMIN_EMAIL="padua.costa@oratelecom.com.br",
            GOOGLE_SERVICE_ACCOUNT_FILE="",
            GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account","project_id":"teste","private_key_id":"abc","private_key":"-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----\\n","client_email":"bot@teste.iam.gserviceaccount.com","client_id":"123","token_uri":"https://oauth2.googleapis.com/token"}',
            GOOGLE_SERVICE_ACCOUNT_PROJECT_ID="",
            GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_ID="",
            GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY="",
            GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL="",
            GOOGLE_SERVICE_ACCOUNT_CLIENT_ID="",
            GOOGLE_SERVICE_ACCOUNT_TOKEN_URI="https://oauth2.googleapis.com/token",
            GOOGLE_WORKSPACE_DEFAULT_ORG_UNIT="",
            GOOGLE_WORKSPACE_LICENSING_ENABLED=False,
            GOOGLE_WORKSPACE_PRODUCT_ID="",
            GOOGLE_WORKSPACE_SKU_ID="",
        ):
            GoogleWorkspaceClient().list_users(max_results=5)

        credentials_mock.assert_called_once()

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
            GOOGLE_SERVICE_ACCOUNT_JSON="",
            GOOGLE_SERVICE_ACCOUNT_PROJECT_ID="",
            GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_ID="",
            GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY="",
            GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL="",
            GOOGLE_SERVICE_ACCOUNT_CLIENT_ID="",
            GOOGLE_SERVICE_ACCOUNT_TOKEN_URI="https://oauth2.googleapis.com/token",
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

    @patch("emails.views.CapitalMobileSMSClient")
    @patch("emails.views.GoogleWorkspaceClient")
    def test_google_cria_usuario_envia_sms_quando_telefone_for_informado(self, client_cls, sms_client_cls):
        self.client.force_login(self.user)
        client_cls.return_value.create_user.return_value = GoogleWorkspaceUser(
            primary_email="novo@oratelecom.com.br",
            full_name="Novo Usuario",
            suspended=False,
            org_unit_path="/",
            is_admin=False,
            aliases=[],
        )
        sms_client_cls.return_value.build_welcome_message.return_value = "mensagem sms"

        response = self.client.post(
            reverse("google-user-create"),
            {
                "nome": "novo",
                "first_name": "Novo",
                "last_name": "Usuario",
                "senha": "Senha123!",
                "telefone_ddd": "86",
                "telefone_numero": "90018315",
            },
        )

        self.assertEqual(response.status_code, 302)
        sms_client_cls.return_value.build_welcome_message.assert_called_once_with(
            email="novo@oratelecom.com.br",
            access_url="https://mail.google.com/",
            max_length=160,
        )
        sms_client_cls.return_value.send_sms.assert_called_once_with("558690018315", "mensagem sms")

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

    @patch("emails.views.GoogleWorkspaceClient")
    def test_google_lista_ordena_por_status(self, client_cls):
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

        response = self.client.get(
            reverse("google-user-list"),
            {"sort": "status", "dir": "desc"},
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertLess(content.index("suspenso@oratelecom.com.br"), content.index("ativo@oratelecom.com.br"))
