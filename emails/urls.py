from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import StyledPasswordResetForm, StyledSetPasswordForm

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path(
        "senha/reset/",
        auth_views.PasswordResetView.as_view(
            form_class=StyledPasswordResetForm,
            template_name="emails/password_reset_form.html",
            html_email_template_name="emails/password_reset_email.html",
            subject_template_name="emails/password_reset_subject.txt",
            success_url="/senha/reset/enviado/",
        ),
        name="password_reset",
    ),
    path(
        "senha/reset/enviado/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="emails/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "senha/redefinir/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            form_class=StyledSetPasswordForm,
            template_name="emails/password_reset_confirm.html",
            success_url="/senha/redefinir/concluido/",
        ),
        name="password_reset_confirm",
    ),
    path(
        "senha/redefinir/concluido/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="emails/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path("logout/", views.logout_view, name="logout"),
    path("", views.listar_contas, name="account-list"),
    path("cpanel/", views.listar_contas_cpanel, name="cpanel-list"),
    path("google/", views.google_dashboard, name="google-dashboard"),
    path("google/usuarios/", views.listar_usuarios_google, name="google-user-list"),
    path("google/usuarios/criar/", views.criar_usuario_google, name="google-user-create"),
    path("google/usuarios/acao/<path:email>/", views.acao_usuario_google, name="google-user-action"),
    path("google/configuracoes/", views.configurar_workspace, name="workspace-settings"),
    path("conta/<str:account>/", views.listar_emails, name="email-list"),
    path("conta/<str:account>/criar/", views.criar_email, name="email-create"),
    path("conta/<str:account>/acao/<path:email>/", views.acao_email, name="email-action"),
    path("historico/", views.historico, name="email-log"),
    path("perfil/", views.meu_perfil, name="my-profile"),
    path("usuarios/", views.listar_usuarios, name="user-list"),
    path("usuarios/novo/", views.criar_usuario, name="user-create"),
    path("usuarios/<int:user_id>/editar/", views.editar_usuario, name="user-edit"),
]
