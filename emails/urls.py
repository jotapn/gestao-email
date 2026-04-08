from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("", views.listar_contas, name="account-list"),
    path("google/", views.google_dashboard, name="google-dashboard"),
    path("google/usuarios/", views.listar_usuarios_google, name="google-user-list"),
    path("google/usuarios/criar/", views.criar_usuario_google, name="google-user-create"),
    path("google/usuarios/acao/<path:email>/", views.acao_usuario_google, name="google-user-action"),
    path("google/configuracoes/", views.configurar_workspace, name="workspace-settings"),
    path("conta/<str:account>/", views.listar_emails, name="email-list"),
    path("conta/<str:account>/criar/", views.criar_email, name="email-create"),
    path("conta/<str:account>/acao/<path:email>/", views.acao_email, name="email-action"),
    path("historico/", views.historico, name="email-log"),
    path("usuarios/", views.listar_usuarios, name="user-list"),
    path("usuarios/novo/", views.criar_usuario, name="user-create"),
    path("usuarios/<int:user_id>/editar/", views.editar_usuario, name="user-edit"),
]
