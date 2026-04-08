import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import (
    EmailActionForm,
    EmailCreateForm,
    EmailPasswordChangeForm,
    GoogleWorkspaceActionForm,
    GoogleWorkspaceUserCreateForm,
    LoginForm,
    SystemUserForm,
)
from .models import EmailLog
from .services.cpanel_client import CpanelAPIError, CpanelClient
from .services.google_workspace_client import GoogleWorkspaceAPIError, GoogleWorkspaceClient

logger = logging.getLogger("emails")
ACCOUNT_STATS_MAX_WORKERS = 8


def admin_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not getattr(request.user, "profile", None) or not request.user.profile.is_admin:
            messages.error(request, "Acesso restrito a administradores do sistema.")
            return redirect("account-list")
        return view_func(request, *args, **kwargs)

    return wrapped


def _log_operation(user, email: str, acao: str, status: str, detalhe: str = "") -> None:
    EmailLog.objects.create(usuario=user, email=email, acao=acao, status=status, detalhe=detalhe)


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, (CpanelAPIError, GoogleWorkspaceAPIError)):
        return str(exc)
    return "Nao foi possivel concluir a operacao no servidor."


def _is_truthy(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_email_item(item):
    full_email = item.get("email") or item.get("txt") or "-"
    login_suspended = any(
        _is_truthy(item.get(key))
        for key in ("suspended_login", "login_suspended", "suspend_login")
    )
    incoming_suspended = any(
        _is_truthy(item.get(key))
        for key in ("suspended_incoming", "incoming_suspended", "hold_incoming", "incoming")
    )
    outgoing_suspended = any(
        _is_truthy(item.get(key))
        for key in ("suspended_outgoing", "outgoing_suspended", "hold_outgoing", "outgoing")
    )
    is_suspended = login_suspended or incoming_suspended or outgoing_suspended
    return {
        **item,
        "full_email": full_email,
        "login_suspended": login_suspended,
        "incoming_suspended": incoming_suspended,
        "outgoing_suspended": outgoing_suspended,
        "is_suspended": is_suspended,
    }


def _email_stats(items):
    normalized = [_normalize_email_item(item) for item in items]
    total = len(normalized)
    fully_active = sum(
        1
        for item in normalized
        if not item["login_suspended"]
        and not item["incoming_suspended"]
        and not item["outgoing_suspended"]
    )
    suspended = sum(1 for item in normalized if item["is_suspended"])
    return {
        "total_emails": total,
        "active_emails": fully_active,
        "suspended_emails": suspended,
    }


def _account_with_stats(account):
    account_view = dict(account)
    try:
        client = CpanelClient(cpanel_user=account["user"], domain=account["domain"])
        stats = _email_stats(client.list_emails(account["domain"]))
    except Exception as exc:
        logger.exception("Erro ao carregar estatisticas da conta %s", account["user"])
        account_view.update(
            {
                "stats_error": _friendly_error(exc),
                "total_emails": None,
                "active_emails": None,
                "suspended_emails": None,
            }
        )
    else:
        account_view.update(stats)
    return account_view


def _filter_email_items(items, search_term: str = "", status_filter: str = ""):
    filtered = items
    if search_term:
        needle = search_term.strip().lower()
        filtered = [item for item in filtered if needle in item["full_email"].lower()]
    if status_filter == "active":
        filtered = [item for item in filtered if not item["is_suspended"]]
    elif status_filter == "suspended":
        filtered = [item for item in filtered if item["is_suspended"]]
    return filtered


def _resolve_account_context(request, account_user: str | None = None):
    root_client = CpanelClient()
    accounts = root_client.list_accounts()
    if not accounts:
        raise CpanelAPIError("Nenhuma conta cPanel disponivel para gerenciamento.")

    requested_user = (
        account_user
        or request.GET.get("account")
        or request.POST.get("account")
        or request.session.get("selected_cpanel_user")
    )
    requested_domain = (
        request.GET.get("domain")
        or request.POST.get("domain")
        or request.session.get("selected_cpanel_domain")
    )
    if account_user:
        requested_domain = None

    selected = None
    for account in accounts:
        if requested_user and account["user"] != requested_user:
            continue
        if requested_domain and account["domain"] != requested_domain:
            continue
        selected = account
        break

    if selected is None:
        selected = accounts[0]

    request.session["selected_cpanel_user"] = selected["user"]
    request.session["selected_cpanel_domain"] = selected["domain"]
    managed_client = CpanelClient(cpanel_user=selected["user"], domain=selected["domain"])
    return managed_client, accounts, selected


def _render_email_list_page(request, account, *, create_form=None, open_create_modal: bool = False):
    emails = []
    error_message = None
    accounts = []
    selected_account = None
    domain = settings.CPANEL_DOMAIN
    search_term = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()

    try:
        client, accounts, selected_account = _resolve_account_context(request, account_user=account)
        domain = selected_account["domain"]
        emails = [_normalize_email_item(item) for item in client.list_emails(domain)]
        emails = _filter_email_items(emails, search_term=search_term, status_filter=status_filter)
    except Exception as exc:
        logger.exception("Erro ao listar e-mails")
        error_message = _friendly_error(exc)
        messages.error(request, error_message)

    context = {
        "emails": emails,
        "domain": domain,
        "accounts": accounts,
        "selected_account": selected_account,
        "action_form": EmailActionForm(),
        "error_message": error_message,
        "search_term": search_term,
        "status_filter": status_filter,
        "filtered_total": len(emails),
        "create_form": create_form or EmailCreateForm(),
        "open_create_modal": open_create_modal or request.GET.get("open_create") == "1",
    }
    return render(request, "emails/list.html", context)


def _google_workspace_stats(users):
    total = len(users)
    suspended = sum(1 for user in users if user.suspended)
    active = total - suspended
    return {
        "total_users": total,
        "active_users": active,
        "suspended_users": suspended,
    }


def _filter_google_users(items, search_term: str = "", status_filter: str = ""):
    filtered = items
    if search_term:
        needle = search_term.strip().lower()
        filtered = [
            item
            for item in filtered
            if needle in item.primary_email.lower() or needle in item.full_name.lower()
        ]
    if status_filter == "active":
        filtered = [item for item in filtered if not item.suspended]
    elif status_filter == "suspended":
        filtered = [item for item in filtered if item.suspended]
    return filtered


def _render_google_user_list_page(request, *, create_form=None, open_create_modal: bool = False):
    users = []
    error_message = None
    search_term = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()

    try:
        client = GoogleWorkspaceClient()
        users = client.list_users(max_results=500)
        users = _filter_google_users(users, search_term=search_term, status_filter=status_filter)
    except Exception as exc:
        logger.exception("Erro ao listar usuarios Google Workspace")
        error_message = _friendly_error(exc)
        messages.error(request, error_message)

    context = {
        "workspace_domain": settings.GOOGLE_WORKSPACE_DOMAIN,
        "users": users,
        "error_message": error_message,
        "search_term": search_term,
        "status_filter": status_filter,
        "filtered_total": len(users),
        "create_form": create_form or GoogleWorkspaceUserCreateForm(),
        "password_form": EmailPasswordChangeForm(),
        "action_form": GoogleWorkspaceActionForm(),
        "open_create_modal": open_create_modal or request.GET.get("open_create") == "1",
    }
    return render(request, "emails/google_users.html", context)


def _send_user_created_email(request, user: User, raw_password: str) -> None:
    if not user.email:
        return

    login_url = request.build_absolute_uri(reverse("login"))
    subject = "Seu acesso ao sistema foi criado"
    message = (
        f"Ola {user.get_full_name() or user.username},\n\n"
        f"Seu acesso ao sistema foi criado.\n\n"
        f"Usuario: {user.username}\n"
        f"Senha inicial: {raw_password}\n"
        f"Login: {login_url}\n\n"
        "Recomendamos alterar sua senha no primeiro acesso."
    )
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("account-list")
    form = LoginForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        return redirect("account-list")
    return render(request, "emails/login.html", {"form": form})


@require_POST
@login_required
def logout_view(request):
    logout(request)
    return redirect("login")


@require_GET
@login_required
def listar_contas(request):
    accounts = []
    error_message = None
    google_summary = None
    try:
        root_client = CpanelClient()
        accounts = root_client.list_accounts()
        max_workers = min(ACCOUNT_STATS_MAX_WORKERS, max(1, len(accounts)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_account_with_stats, account) for account in accounts]
            accounts = [future.result() for future in as_completed(futures)]
        accounts.sort(key=lambda item: item["domain"])
    except Exception as exc:
        logger.exception("Erro ao listar contas cPanel")
        error_message = _friendly_error(exc)
        messages.error(request, error_message)
    try:
        google_client = GoogleWorkspaceClient()
        google_summary = {
            "domain": settings.GOOGLE_WORKSPACE_DOMAIN,
            "admin_email": settings.GOOGLE_WORKSPACE_ADMIN_EMAIL,
            **_google_workspace_stats(google_client.list_users(max_results=500)),
        }
    except Exception as exc:
        logger.exception("Erro ao carregar resumo do Google Workspace")
        google_summary = {
            "domain": settings.GOOGLE_WORKSPACE_DOMAIN,
            "admin_email": settings.GOOGLE_WORKSPACE_ADMIN_EMAIL,
            "stats_error": _friendly_error(exc),
            "total_users": None,
            "active_users": None,
            "suspended_users": None,
        }
    return render(
        request,
        "emails/accounts.html",
        {
            "accounts": accounts,
            "google_summary": google_summary,
            "error_message": error_message,
            "total_accounts": len(accounts),
        },
    )


@require_GET
@login_required
def google_dashboard(request):
    stats = {"total_users": 0, "active_users": 0, "suspended_users": 0}
    error_message = None
    try:
        client = GoogleWorkspaceClient()
        users = client.list_users(max_results=500)
        stats = _google_workspace_stats(users)
    except Exception as exc:
        logger.exception("Erro ao carregar dashboard Google Workspace")
        error_message = _friendly_error(exc)
        messages.error(request, error_message)

    context = {
        "workspace_domain": settings.GOOGLE_WORKSPACE_DOMAIN,
        "workspace_admin_email": settings.GOOGLE_WORKSPACE_ADMIN_EMAIL,
        "error_message": error_message,
        **stats,
    }
    return render(request, "emails/google_dashboard.html", context)


@require_GET
@login_required
def listar_usuarios_google(request):
    return _render_google_user_list_page(request)


@require_http_methods(["GET", "POST"])
@login_required
def criar_usuario_google(request):
    form = GoogleWorkspaceUserCreateForm(request.POST or None)
    if request.method == "GET":
        return redirect(f"{reverse('google-user-list')}?open_create=1")

    if form.is_valid():
        nome = form.cleaned_data["nome"]
        first_name = form.cleaned_data["first_name"]
        last_name = form.cleaned_data["last_name"]
        senha = form.cleaned_data["senha"]
        full_email = f"{nome}@{settings.GOOGLE_WORKSPACE_DOMAIN}"
        try:
            client = GoogleWorkspaceClient()
            client.create_user(
                primary_email=full_email,
                password=senha,
                first_name=first_name,
                last_name=last_name,
            )
        except Exception as exc:
            detalhe = _friendly_error(exc)
            logger.exception("Erro ao criar usuario Google %s", full_email)
            _log_operation(request.user, full_email, "google criar usuario", "erro", detalhe)
            messages.error(request, detalhe)
        else:
            _log_operation(request.user, full_email, "google criar usuario", "sucesso")
            messages.success(request, f"Usuario Google {full_email} criado com sucesso.")
            return redirect("google-user-list")

    return _render_google_user_list_page(request, create_form=form, open_create_modal=True)


@require_POST
@login_required
def acao_usuario_google(request, email):
    form = GoogleWorkspaceActionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Acao invalida.")
        return redirect("google-user-list")

    action = form.cleaned_data["action"]
    password_form = EmailPasswordChangeForm(request.POST if action == "change_password" else None)
    if action == "change_password" and not password_form.is_valid():
        messages.error(request, "Informe uma nova senha valida com no minimo 8 caracteres.")
        return redirect("google-user-list")

    try:
        client = GoogleWorkspaceClient()
    except Exception as exc:
        detalhe = _friendly_error(exc)
        logger.exception("Erro ao preparar acao Google '%s' para %s", action, email)
        _log_operation(request.user, email, f"google {action}", "erro", detalhe)
        messages.error(request, detalhe)
        return redirect("google-user-list")

    action_map = {
        "suspend_user": ("google suspender usuario", client.suspend_user, {"email": email}),
        "unsuspend_user": ("google reativar usuario", client.unsuspend_user, {"email": email}),
        "delete": ("google excluir usuario", client.delete_user, {"email": email}),
    }
    if action == "change_password":
        action_map["change_password"] = (
            "google alterar senha",
            client.update_password,
            {"email": email, "password": password_form.cleaned_data["password"]},
        )
    label, handler, params = action_map[action]

    try:
        handler(**params)
    except Exception as exc:
        detalhe = _friendly_error(exc)
        logger.exception("Erro ao executar acao Google '%s' para %s", action, email)
        _log_operation(request.user, email, label, "erro", detalhe)
        messages.error(request, detalhe)
    else:
        _log_operation(request.user, email, label, "sucesso")
        messages.success(request, f"Acao '{label}' executada para {email}.")
    return redirect("google-user-list")


@require_GET
@login_required
def listar_emails(request, account):
    return _render_email_list_page(request, account)


@require_http_methods(["GET", "POST"])
@login_required
def criar_email(request, account):
    form = EmailCreateForm(request.POST or None)
    if request.method == "GET":
        return redirect(f"{reverse('email-list', kwargs={'account': account})}?open_create=1")

    try:
        client, _, selected_account = _resolve_account_context(request, account_user=account)
        domain = selected_account["domain"]
    except Exception as exc:
        logger.exception("Erro ao resolver conta cPanel para criacao")
        messages.error(request, _friendly_error(exc))
        return _render_email_list_page(request, account, create_form=form, open_create_modal=True)

    if form.is_valid():
        nome = form.cleaned_data["nome"]
        senha = form.cleaned_data["senha"]
        quota = form.cleaned_data["quota"]
        full_email = f"{nome}@{domain}"
        try:
            client.create_email(email=nome, password=senha, quota=quota, domain=domain)
        except Exception as exc:
            detalhe = _friendly_error(exc)
            logger.exception("Erro ao criar e-mail %s", full_email)
            _log_operation(request.user, full_email, "criado", "erro", detalhe)
            messages.error(request, detalhe)
        else:
            _log_operation(request.user, full_email, "criado", "sucesso", f"Quota: {quota} MB")
            messages.success(request, f"E-mail {full_email} criado com sucesso.")
            return redirect("email-list", account=selected_account["user"])
    return _render_email_list_page(request, account, create_form=form, open_create_modal=True)


@require_POST
@login_required
def acao_email(request, account, email):
    form = EmailActionForm(request.POST)
    full_email = email
    if not form.is_valid():
        messages.error(request, "Acao invalida.")
        return redirect("email-list", account=account)

    action = form.cleaned_data["action"]
    domain = request.POST.get("domain") or request.session.get("selected_cpanel_domain") or settings.CPANEL_DOMAIN
    account = request.POST.get("account") or request.session.get("selected_cpanel_user") or account
    if not domain:
        messages.error(request, "Dominio nao informado.")
        return redirect("email-list", account=account)
    if "@" not in full_email:
        full_email = f"{full_email}@{domain}"

    password_form = EmailPasswordChangeForm(request.POST if action == "change_password" else None)
    if action == "change_password" and not password_form.is_valid():
        messages.error(request, "Informe uma nova senha valida com no minimo 8 caracteres.")
        return redirect("email-list", account=account)

    try:
        client = CpanelClient(cpanel_user=account, domain=domain)
    except Exception as exc:
        detalhe = _friendly_error(exc)
        logger.exception("Erro ao preparar acao '%s' para %s", action, full_email)
        _log_operation(request.user, full_email, action, "erro", detalhe)
        messages.error(request, detalhe)
        return redirect("email-list", account=account)

    action_map = {
        "suspend_user": ("suspender usuario", client.suspend_user, {"full_email": full_email}),
        "unsuspend_user": ("reativar usuario", client.unsuspend_user, {"full_email": full_email}),
        "delete": ("excluir", client.delete_email, {"email": full_email.split("@")[0], "domain": domain}),
    }
    if action == "change_password":
        action_map["change_password"] = (
            "alterar senha",
            client.change_password,
            {"email": full_email.split("@")[0], "domain": domain, "password": password_form.cleaned_data["password"]},
        )
    label, handler, params = action_map[action]

    try:
        handler(**params)
    except Exception as exc:
        detalhe = _friendly_error(exc)
        logger.exception("Erro ao executar '%s' para %s", action, full_email)
        _log_operation(request.user, full_email, label, "erro", detalhe)
        messages.error(request, detalhe)
    else:
        _log_operation(request.user, full_email, label, "sucesso")
        messages.success(request, f"Acao '{label}' executada para {full_email}.")
    return redirect("email-list", account=account)


@require_GET
@admin_required
def historico(request):
    logs = EmailLog.objects.select_related("usuario").all()
    return render(request, "emails/detail.html", {"logs": logs})


@require_GET
@admin_required
def listar_usuarios(request):
    users = User.objects.select_related("profile").order_by("username")
    return render(request, "emails/users.html", {"users": users})


@require_http_methods(["GET", "POST"])
@admin_required
def criar_usuario(request):
    form = SystemUserForm(request.POST or None, current_user=request.user)
    if request.method == "POST" and form.is_valid():
        raw_password = form.cleaned_data.get("password", "")
        user = form.save()
        if user.email:
            try:
                _send_user_created_email(request, user, raw_password)
            except Exception:
                logger.exception("Erro ao enviar e-mail de boas-vindas para %s", user.username)
                messages.warning(
                    request,
                    f"Usuario {user.username} criado, mas o e-mail de acesso nao foi enviado.",
                )
            else:
                messages.success(request, f"Usuario {user.username} criado e e-mail enviado com sucesso.")
                return redirect("user-list")
        messages.success(request, f"Usuario {user.username} criado com sucesso.")
        return redirect("user-list")
    return render(request, "emails/user_form.html", {"form": form, "page_title": "Novo usuario"})


@require_http_methods(["GET", "POST"])
@admin_required
def editar_usuario(request, user_id):
    target_user = get_object_or_404(User.objects.select_related("profile"), pk=user_id)
    form = SystemUserForm(request.POST or None, instance=target_user, current_user=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(request, f"Usuario {user.username} atualizado com sucesso.")
        return redirect("user-list")
    return render(request, "emails/user_form.html", {"form": form, "page_title": f"Editar usuario: {target_user.username}", "target_user": target_user})
