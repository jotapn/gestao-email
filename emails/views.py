import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives, send_mail
from django.template.loader import render_to_string
from django.core.paginator import EmptyPage, Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import (
    EmailActionForm,
    EmailCreateForm,
    EmailPasswordChangeForm,
    GoogleWorkspaceActionForm,
    GoogleWorkspaceUserCreateForm,
    LoginForm,
    SelfProfileForm,
    StyledPasswordChangeForm,
    SystemUserForm,
    WorkspaceSettingForm,
)
from .models import EmailLog, WorkspaceSetting
from .services.cpanel_client import CpanelAPIError, CpanelClient
from .services.google_workspace_client import GoogleWorkspaceAPIError, GoogleWorkspaceClient
from .services.sms_client import CapitalMobileSMSClient, SMSAPIError

logger = logging.getLogger("emails")
ACCOUNT_STATS_MAX_WORKERS = 8
REMOTE_CACHE_TIMEOUT = 60
EMAIL_LIST_CACHE_TIMEOUT = 30
GOOGLE_USERS_PER_PAGE = 50
EMAILS_PER_PAGE = 25
HISTORY_PER_PAGE = 50
SYSTEM_USERS_PER_PAGE = 25
ACCOUNTS_PER_PAGE = 12
ACCOUNT_PRIORITY_TERMS = (
    "cnxtel",
    "mercadodoprovedo",
    "mercado do provedor",
)


def admin_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not getattr(request.user, "profile", None) or not request.user.profile.can_manage_admin:
            messages.error(request, "Acesso restrito a administradores do sistema.")
            return redirect("account-list")
        return view_func(request, *args, **kwargs)

    return wrapped


def system_admin_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not getattr(request.user, "profile", None) or not request.user.profile.is_system_admin:
            messages.error(request, "Acesso restrito ao admin do sistema.")
            return redirect("account-list")
        return view_func(request, *args, **kwargs)

    return wrapped


def _log_operation(user, email: str, acao: str, status: str, detalhe: str = "") -> None:
    EmailLog.objects.create(usuario=user, email=email, acao=acao, status=status, detalhe=detalhe)


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, (CpanelAPIError, GoogleWorkspaceAPIError, SMSAPIError)):
        return str(exc)
    return "Nao foi possivel concluir a operacao no servidor."


def _email_access_url(domain: str) -> str:
    normalized_domain = (domain or "").strip().lower()
    workspace_domain = (settings.GOOGLE_WORKSPACE_DOMAIN or "").strip().lower()
    if normalized_domain and workspace_domain and normalized_domain == workspace_domain:
        return "https://mail.google.com/"
    return f"https://webmail.{normalized_domain}"


def _cache_get_or_set(cache_key: str, timeout: int, factory):
    if getattr(settings, "IS_TESTING", False):
        return factory()
    cached_value = cache.get(cache_key)
    if cached_value is not None:
        return cached_value
    value = factory()
    cache.set(cache_key, value, timeout)
    return value


def _cpanel_accounts_cache_key() -> str:
    return "cpanel:accounts"


def _cpanel_account_stats_cache_key(account_user: str, domain: str) -> str:
    return f"cpanel:account-stats:{account_user}:{domain}"


def _cpanel_email_list_cache_key(account_user: str, domain: str) -> str:
    return f"cpanel:emails:{account_user}:{domain}"


def _google_users_cache_key() -> str:
    return "google:users"


def _invalidate_cpanel_account_cache(account_user: str | None = None, domain: str | None = None) -> None:
    cache.delete(_cpanel_accounts_cache_key())
    if account_user and domain:
        cache.delete(_cpanel_account_stats_cache_key(account_user, domain))
        cache.delete(_cpanel_email_list_cache_key(account_user, domain))


def _invalidate_google_cache() -> None:
    cache.delete(_google_users_cache_key())


def _get_page_base_query(request, page_param: str = "page") -> str:
    query = request.GET.copy()
    query.pop(page_param, None)
    return query.urlencode()


def _redirect_email_list_with_filters(account: str, request) -> str:
    params = {}
    for key in ("q", "status", "page", "sort", "dir"):
        value = (request.POST.get(key) or "").strip()
        if value:
            params[key] = value

    base_url = reverse("email-list", kwargs={"account": account})
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def _redirect_google_user_list_with_filters(request) -> str:
    params = {}
    for key in ("q", "status", "page", "sort", "dir"):
        value = (request.POST.get(key) or "").strip()
        if value:
            params[key] = value

    base_url = reverse("google-user-list")
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def _toggle_sort_direction(current_sort: str, current_dir: str, next_sort: str) -> str:
    if current_sort == next_sort and current_dir == "asc":
        return "desc"
    return "asc"


def _build_sort_query(request, sort_field: str) -> str:
    query = request.GET.copy()
    query["sort"] = sort_field
    query["dir"] = _toggle_sort_direction(
        request.GET.get("sort", "").strip(),
        request.GET.get("dir", "asc").strip(),
        sort_field,
    )
    query.pop("page", None)
    return query.urlencode()


def _sort_indicator(current_sort: str, current_dir: str, field_name: str) -> str:
    if current_sort != field_name:
        return ""
    return "↑" if current_dir == "asc" else "↓"


def _filter_logs(
    logs,
    user_term: str = "",
    email_term: str = "",
    status_filter: str = "",
    date_from: str = "",
    date_to: str = "",
):
    filtered = logs
    if user_term:
        filtered = filtered.filter(usuario__username__icontains=user_term.strip())
    if email_term:
        filtered = filtered.filter(email__icontains=email_term.strip())
    if status_filter:
        filtered = filtered.filter(status=status_filter)
    if date_from:
        filtered = filtered.filter(criado_em__date__gte=date_from)
    if date_to:
        filtered = filtered.filter(criado_em__date__lte=date_to)
    return filtered


def _sort_logs(logs, sort_field: str = "created", direction: str = "desc"):
    field_map = {
        "user": "usuario__username",
        "email": "email",
        "action": "acao",
        "status": "status",
        "created": "criado_em",
    }
    resolved_field = field_map.get(sort_field, "criado_em")
    if direction == "desc":
        resolved_field = f"-{resolved_field}"
    return logs.order_by(resolved_field, "-id")


def _paginate_items(request, items, per_page: int, *, page_param: str = "page"):
    paginator = Paginator(items, per_page)
    page_number = request.GET.get(page_param) or 1
    try:
        page_obj = paginator.page(page_number)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    return page_obj, _get_page_base_query(request, page_param=page_param)


def _account_sort_key(account: dict) -> tuple[int, str]:
    domain = str(account.get("domain") or "").lower()
    user = str(account.get("user") or "").lower()
    haystack = f"{domain} {user}"

    for index, term in enumerate(ACCOUNT_PRIORITY_TERMS):
        if term in haystack:
            return (index, domain)

    return (len(ACCOUNT_PRIORITY_TERMS), domain)


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
        stats_cache_key = _cpanel_account_stats_cache_key(account["user"], account["domain"])
        stats = _cache_get_or_set(
            stats_cache_key,
            REMOTE_CACHE_TIMEOUT,
            lambda: _email_stats(_fetch_cpanel_emails(account["user"], account["domain"])),
        )
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


def _sort_email_items(items, sort_field: str = "email", direction: str = "asc"):
    reverse = direction == "desc"
    if sort_field == "status":
        return sorted(
            items,
            key=lambda item: (
                item["is_suspended"],
                item["full_email"].lower(),
            ),
            reverse=reverse,
        )
    return sorted(items, key=lambda item: item["full_email"].lower(), reverse=reverse)


def _resolve_account_context(request, account_user: str | None = None):
    root_client = CpanelClient()
    accounts = _cache_get_or_set(
        _cpanel_accounts_cache_key(),
        REMOTE_CACHE_TIMEOUT,
        root_client.list_accounts,
    )
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


def _fetch_cpanel_emails(account_user: str, domain: str):
    cache_key = _cpanel_email_list_cache_key(account_user, domain)
    return _cache_get_or_set(
        cache_key,
        EMAIL_LIST_CACHE_TIMEOUT,
        lambda: CpanelClient(cpanel_user=account_user, domain=domain).list_emails(domain),
    )


def _fetch_google_users(max_results: int = 1000):
    return _cache_get_or_set(
        _google_users_cache_key(),
        REMOTE_CACHE_TIMEOUT,
        lambda: GoogleWorkspaceClient().list_users(max_results=max_results),
    )


def _render_email_list_page(request, account, *, create_form=None, open_create_modal: bool = False):
    emails = []
    error_message = None
    accounts = []
    selected_account = None
    domain = settings.CPANEL_DOMAIN
    search_term = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()
    sort_field = request.GET.get("sort", "email").strip()
    sort_direction = request.GET.get("dir", "asc").strip()
    if sort_field not in {"email", "status"}:
        sort_field = "email"
    if sort_direction not in {"asc", "desc"}:
        sort_direction = "asc"

    try:
        client, accounts, selected_account = _resolve_account_context(request, account_user=account)
        domain = selected_account["domain"]
        emails = [
            _normalize_email_item(item)
            for item in _fetch_cpanel_emails(selected_account["user"], domain)
        ]
        emails = _filter_email_items(emails, search_term=search_term, status_filter=status_filter)
        emails = _sort_email_items(emails, sort_field=sort_field, direction=sort_direction)
    except Exception as exc:
        logger.exception("Erro ao listar e-mails")
        error_message = _friendly_error(exc)
        messages.error(request, error_message)

    page_obj, page_query = _paginate_items(request, emails, EMAILS_PER_PAGE)
    context = {
        "emails": page_obj.object_list,
        "page_obj": page_obj,
        "page_query": page_query,
        "domain": domain,
        "accounts": accounts,
        "selected_account": selected_account,
        "action_form": EmailActionForm(),
        "error_message": error_message,
        "search_term": search_term,
        "status_filter": status_filter,
        "sort_field": sort_field,
        "sort_direction": sort_direction,
        "email_sort_query": _build_sort_query(request, "email"),
        "status_sort_query": _build_sort_query(request, "status"),
        "email_sort_indicator": _sort_indicator(sort_field, sort_direction, "email"),
        "status_sort_indicator": _sort_indicator(sort_field, sort_direction, "status"),
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


def _sort_google_users(items, sort_field: str = "email", direction: str = "asc"):
    reverse = direction == "desc"
    if sort_field == "status":
        return sorted(
            items,
            key=lambda item: (
                item.suspended,
                item.primary_email.lower(),
            ),
            reverse=reverse,
        )
    return sorted(items, key=lambda item: item.primary_email.lower(), reverse=reverse)


def _render_google_user_list_page(request, *, create_form=None, open_create_modal: bool = False):
    users = []
    error_message = None
    search_term = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()
    sort_field = request.GET.get("sort", "email").strip()
    sort_direction = request.GET.get("dir", "asc").strip()
    if sort_field not in {"email", "status"}:
        sort_field = "email"
    if sort_direction not in {"asc", "desc"}:
        sort_direction = "asc"

    try:
        users = _fetch_google_users()
        users = _filter_google_users(users, search_term=search_term, status_filter=status_filter)
        users = _sort_google_users(users, sort_field=sort_field, direction=sort_direction)
    except Exception as exc:
        logger.exception("Erro ao listar usuarios Google Workspace")
        error_message = _friendly_error(exc)
        messages.error(request, error_message)

    page_obj, page_query = _paginate_items(request, users, GOOGLE_USERS_PER_PAGE)
    context = {
        "workspace_domain": settings.GOOGLE_WORKSPACE_DOMAIN,
        "users": page_obj.object_list,
        "page_obj": page_obj,
        "page_query": page_query,
        "error_message": error_message,
        "search_term": search_term,
        "status_filter": status_filter,
        "sort_field": sort_field,
        "sort_direction": sort_direction,
        "email_sort_query": _build_sort_query(request, "email"),
        "status_sort_query": _build_sort_query(request, "status"),
        "email_sort_indicator": _sort_indicator(sort_field, sort_direction, "email"),
        "status_sort_indicator": _sort_indicator(sort_field, sort_direction, "status"),
        "filtered_total": len(users),
        "create_form": create_form or GoogleWorkspaceUserCreateForm(),
        "password_form": EmailPasswordChangeForm(),
        "action_form": GoogleWorkspaceActionForm(),
        "open_create_modal": open_create_modal or request.GET.get("open_create") == "1",
    }
    return render(request, "emails/google_users.html", context)


def _workspace_limit_status(total_users: int, setting: WorkspaceSetting | None) -> dict | None:
    if not setting or setting.google_workspace_user_limit is None:
        return None

    limit = setting.google_workspace_user_limit
    remaining = max(limit - total_users, 0)
    reached = total_users >= limit
    warning = not reached and remaining <= 2
    return {
        "limit": limit,
        "used": total_users,
        "remaining": remaining,
        "reached": reached,
        "warning": warning,
    }


def _maybe_send_workspace_limit_email(setting: WorkspaceSetting, limit_status: dict | None) -> None:
    if not limit_status:
        setting.clear_limit_email_sent()
        return

    if limit_status["reached"]:
        if setting.limit_reached_email_sent_at:
            return
        send_mail(
            subject="Limite do Google Workspace atingido",
            message=(
                "O limite configurado para usuarios do Google Workspace foi atingido.\n\n"
                f"Limite: {limit_status['limit']}\n"
                f"Em uso: {limit_status['used']}\n"
                f"Data: {timezone.localtime().strftime('%d/%m/%Y %H:%M:%S')}\n"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[setting.google_workspace_alert_email or "sistemas@oratelecom.com.br"],
            fail_silently=False,
        )
        setting.mark_limit_email_sent()
        return

    setting.clear_limit_email_sent()


def _send_user_created_email(request, user: User, raw_password: str) -> None:
    if not user.email:
        return

    login_url = request.build_absolute_uri(reverse("login"))
    full_name = user.get_full_name() or user.username
    subject = "Seu acesso ao sistema foi criado"
    context = {
        "full_name": full_name,
        "username": user.username,
        "password": raw_password,
        "login_url": login_url,
    }
    text_message = (
        f"Ola {full_name},\n\n"
        f"Seu acesso ao sistema foi criado.\n\n"
        f"Usuario: {user.username}\n"
        f"Senha inicial: {raw_password}\n"
        f"Login: {login_url}\n\n"
        "Recomendamos alterar sua senha no primeiro acesso."
    )
    html_message = render_to_string("emails/user_created_email.html", context)
    email = EmailMultiAlternatives(
        subject=subject,
        body=text_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    email.attach_alternative(html_message, "text/html")
    email.send(fail_silently=False)


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


@require_http_methods(["GET", "POST"])
@login_required
def meu_perfil(request):
    profile_form = SelfProfileForm(instance=request.user)
    password_form = StyledPasswordChangeForm(user=request.user)

    if request.method == "POST":
        form_type = request.POST.get("form_type")
        if form_type == "profile":
            profile_form = SelfProfileForm(request.POST, instance=request.user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Seus dados foram atualizados com sucesso.")
                return redirect("my-profile")
        elif form_type == "password":
            password_form = StyledPasswordChangeForm(user=request.user, data=request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Sua senha foi atualizada com sucesso.")
                return redirect("my-profile")
        else:
            messages.error(request, "Formulario invalido.")

    return render(
        request,
        "emails/profile.html",
        {"profile_form": profile_form, "password_form": password_form},
    )


def _load_cpanel_accounts():
    accounts = []
    error_message = None
    try:
        root_client = CpanelClient()
        accounts = _cache_get_or_set(
            _cpanel_accounts_cache_key(),
            REMOTE_CACHE_TIMEOUT,
            root_client.list_accounts,
        )
        max_workers = min(ACCOUNT_STATS_MAX_WORKERS, max(1, len(accounts)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_account_with_stats, account) for account in accounts]
            accounts = [future.result() for future in as_completed(futures)]
        accounts.sort(key=_account_sort_key)
    except Exception as exc:
        logger.exception("Erro ao listar contas cPanel")
        error_message = _friendly_error(exc)
    return accounts, error_message


@require_GET
@login_required
def listar_contas(request):
    accounts, error_message = _load_cpanel_accounts()
    google_summary = None
    workspace_setting = WorkspaceSetting.get_solo()
    if error_message:
        messages.error(request, error_message)
    try:
        google_users = _fetch_google_users()
        limit_status = _workspace_limit_status(len(google_users), workspace_setting)
        try:
            _maybe_send_workspace_limit_email(workspace_setting, limit_status)
        except Exception:
            logger.exception("Erro ao enviar alerta de limite do Google Workspace")
        google_summary = {
            "domain": settings.GOOGLE_WORKSPACE_DOMAIN,
            "admin_email": settings.GOOGLE_WORKSPACE_ADMIN_EMAIL,
            "limit_status": limit_status,
            **_google_workspace_stats(google_users),
        }
    except Exception as exc:
        logger.exception("Erro ao carregar resumo do Google Workspace")
        google_summary = {
            "domain": settings.GOOGLE_WORKSPACE_DOMAIN,
            "admin_email": settings.GOOGLE_WORKSPACE_ADMIN_EMAIL,
            "limit_status": None,
            "stats_error": _friendly_error(exc),
            "total_users": None,
            "active_users": None,
            "suspended_users": None,
        }
    page_obj, page_query = _paginate_items(request, accounts, ACCOUNTS_PER_PAGE)
    return render(
        request,
        "emails/accounts.html",
        {
            "accounts": page_obj.object_list,
            "page_obj": page_obj,
            "page_query": page_query,
            "google_summary": google_summary,
            "error_message": error_message,
            "total_accounts": len(accounts),
        },
    )


@require_GET
@login_required
def listar_contas_cpanel(request):
    accounts, error_message = _load_cpanel_accounts()
    if error_message:
        messages.error(request, error_message)
    page_obj, page_query = _paginate_items(request, accounts, ACCOUNTS_PER_PAGE)
    return render(
        request,
        "emails/accounts.html",
        {
            "accounts": page_obj.object_list,
            "page_obj": page_obj,
            "page_query": page_query,
            "google_summary": None,
            "error_message": error_message,
            "total_accounts": len(accounts),
            "page_title": "Contas cPanel",
            "page_heading": "Contas cPanel",
            "page_subtitle": "Selecione uma conta cPanel para ver e gerenciar os e-mails.",
        },
    )


@require_GET
@login_required
def google_dashboard(request):
    stats = {"total_users": 0, "active_users": 0, "suspended_users": 0}
    error_message = None
    limit_status = None
    workspace_setting = WorkspaceSetting.get_solo()
    try:
        users = _fetch_google_users()
        stats = _google_workspace_stats(users)
        limit_status = _workspace_limit_status(len(users), workspace_setting)
        try:
            _maybe_send_workspace_limit_email(workspace_setting, limit_status)
        except Exception:
            logger.exception("Erro ao enviar alerta de limite do Google Workspace")
    except Exception as exc:
        logger.exception("Erro ao carregar dashboard Google Workspace")
        error_message = _friendly_error(exc)
        messages.error(request, error_message)

    context = {
        "workspace_domain": settings.GOOGLE_WORKSPACE_DOMAIN,
        "workspace_admin_email": settings.GOOGLE_WORKSPACE_ADMIN_EMAIL,
        "limit_status": limit_status,
        "error_message": error_message,
        **stats,
    }
    return render(request, "emails/google_dashboard.html", context)


@require_http_methods(["GET", "POST"])
@system_admin_required
def configurar_workspace(request):
    setting = WorkspaceSetting.get_solo()
    previous_limit = setting.google_workspace_user_limit
    previous_email = setting.google_workspace_alert_email
    form = WorkspaceSettingForm(request.POST or None, instance=setting)
    if request.method == "POST" and form.is_valid():
        setting = form.save(commit=False)
        setting.atualizado_por = request.user
        if (
            previous_limit != setting.google_workspace_user_limit
            or previous_email != setting.google_workspace_alert_email
        ):
            setting.limit_reached_email_sent_at = None
        setting.save()
        detalhe = (
            f"Limite anterior: {previous_limit if previous_limit is not None else '-'} | "
            f"Novo limite: {setting.google_workspace_user_limit if setting.google_workspace_user_limit is not None else '-'} | "
            f"E-mail anterior: {previous_email or '-'} | "
            f"Novo e-mail: {setting.google_workspace_alert_email or '-'}"
        )
        _log_operation(
            request.user,
            setting.google_workspace_alert_email or "workspace@oratelecom.com.br",
            "configurar workspace google",
            "sucesso",
            detalhe,
        )
        messages.success(request, "Configuracao do Google Workspace atualizada com sucesso.")
        return redirect("workspace-settings")

    return render(
        request,
        "emails/workspace_settings.html",
        {"form": form, "page_title": "Configuracao do Google Workspace"},
    )


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
        telefone = form.cleaned_data.get("telefone_completo")
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
            _invalidate_google_cache()
            _log_operation(request.user, full_email, "google criar usuario", "sucesso")
            if telefone:
                try:
                    sms_client = CapitalMobileSMSClient()
                    sms_text = sms_client.build_welcome_message(
                        email=full_email,
                        access_url=_email_access_url(settings.GOOGLE_WORKSPACE_DOMAIN),
                        max_length=settings.CAPITAL_MOBILE_SMS_MAX_LENGTH,
                    )
                    sms_client.send_sms(telefone, sms_text)
                except Exception as exc:
                    detalhe = _friendly_error(exc)
                    logger.exception("Erro ao enviar SMS de boas-vindas para usuario Google %s", full_email)
                    _log_operation(request.user, full_email, "google sms boas-vindas", "erro", detalhe)
                    messages.warning(
                        request,
                        f"Usuario Google {full_email} criado com sucesso, mas o SMS nao foi enviado. {detalhe}",
                    )
                else:
                    _log_operation(
                        request.user,
                        full_email,
                        "google sms boas-vindas",
                        "sucesso",
                        f"Telefone: {telefone}",
                    )
                    messages.success(request, f"Usuario Google {full_email} criado com sucesso e SMS enviado.")
            else:
                messages.success(request, f"Usuario Google {full_email} criado com sucesso.")
            return redirect("google-user-list")

    return _render_google_user_list_page(request, create_form=form, open_create_modal=True)


@require_POST
@login_required
def acao_usuario_google(request, email):
    form = GoogleWorkspaceActionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Acao invalida.")
        return redirect(_redirect_google_user_list_with_filters(request))

    action = form.cleaned_data["action"]
    can_manage_email_admin_actions = bool(
        getattr(getattr(request.user, "profile", None), "can_manage_admin", False)
    )
    if action == "delete" and not can_manage_email_admin_actions:
        messages.error(
            request,
            "Apenas usuarios com perfil de admin podem excluir contas de e-mail.",
        )
        return redirect(_redirect_google_user_list_with_filters(request))
    password_form = EmailPasswordChangeForm(request.POST if action == "change_password" else None)
    if action == "change_password" and not password_form.is_valid():
        messages.error(request, "Informe uma nova senha valida com no minimo 8 caracteres.")
        return redirect(_redirect_google_user_list_with_filters(request))

    try:
        client = GoogleWorkspaceClient()
    except Exception as exc:
        detalhe = _friendly_error(exc)
        logger.exception("Erro ao preparar acao Google '%s' para %s", action, email)
        _log_operation(request.user, email, f"google {action}", "erro", detalhe)
        messages.error(request, detalhe)
        return redirect(_redirect_google_user_list_with_filters(request))

    action_map = {
        "suspend_user": (
            "google suspender usuario",
            client.suspend_user,
            {"email": email},
            f"Usuário Google {email} suspenso com sucesso.",
        ),
        "unsuspend_user": (
            "google reativar usuario",
            client.unsuspend_user,
            {"email": email},
            f"Usuário Google {email} reativado com sucesso.",
        ),
        "delete": (
            "google excluir usuario",
            client.delete_user,
            {"email": email},
            f"Usuário Google {email} excluído com sucesso.",
        ),
    }
    if action == "change_password":
        action_map["change_password"] = (
            "google alterar senha",
            client.update_password,
            {"email": email, "password": password_form.cleaned_data["password"]},
            f"Senha do usuário Google {email} alterada com sucesso.",
        )
    label, handler, params, success_message = action_map[action]

    try:
        handler(**params)
    except Exception as exc:
        detalhe = _friendly_error(exc)
        logger.exception("Erro ao executar acao Google '%s' para %s", action, email)
        _log_operation(request.user, email, label, "erro", detalhe)
        messages.error(request, detalhe)
    else:
        _invalidate_google_cache()
        _log_operation(request.user, email, label, "sucesso")
        messages.success(request, success_message)
    return redirect(_redirect_google_user_list_with_filters(request))


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
        telefone = form.cleaned_data.get("telefone_completo")
        full_email = f"{nome}@{domain}"
        try:
            client.create_email(email=nome, password=senha, quota=quota, domain=domain)
        except Exception as exc:
            detalhe = _friendly_error(exc)
            logger.exception("Erro ao criar e-mail %s", full_email)
            _log_operation(request.user, full_email, "criado", "erro", detalhe)
            messages.error(request, detalhe)
        else:
            _invalidate_cpanel_account_cache(selected_account["user"], domain)
            _log_operation(request.user, full_email, "criado", "sucesso", f"Quota: {quota} MB")
            if telefone:
                try:
                    sms_client = CapitalMobileSMSClient()
                    sms_text = sms_client.build_welcome_message(
                        email=full_email,
                        access_url=_email_access_url(domain),
                        max_length=settings.CAPITAL_MOBILE_SMS_MAX_LENGTH,
                    )
                    sms_client.send_sms(telefone, sms_text)
                except Exception as exc:
                    detalhe = _friendly_error(exc)
                    logger.exception("Erro ao enviar SMS de boas-vindas para %s", full_email)
                    _log_operation(request.user, full_email, "sms boas-vindas", "erro", detalhe)
                    messages.warning(
                        request,
                        f"E-mail {full_email} criado com sucesso, mas o SMS nao foi enviado. {detalhe}",
                    )
                else:
                    _log_operation(request.user, full_email, "sms boas-vindas", "sucesso", f"Telefone: {telefone}")
                    messages.success(request, f"E-mail {full_email} criado com sucesso e SMS enviado.")
            else:
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
        return redirect(_redirect_email_list_with_filters(account, request))

    action = form.cleaned_data["action"]
    domain = request.POST.get("domain") or request.session.get("selected_cpanel_domain") or settings.CPANEL_DOMAIN
    account = request.POST.get("account") or request.session.get("selected_cpanel_user") or account
    if not domain:
        messages.error(request, "Dominio nao informado.")
        return redirect(_redirect_email_list_with_filters(account, request))
    if "@" not in full_email:
        full_email = f"{full_email}@{domain}"

    password_form = EmailPasswordChangeForm(request.POST if action == "change_password" else None)
    if action == "change_password" and not password_form.is_valid():
        messages.error(request, "Informe uma nova senha valida com no minimo 8 caracteres.")
        return redirect(_redirect_email_list_with_filters(account, request))

    try:
        client = CpanelClient(cpanel_user=account, domain=domain)
    except Exception as exc:
        detalhe = _friendly_error(exc)
        logger.exception("Erro ao preparar acao '%s' para %s", action, full_email)
        _log_operation(request.user, full_email, action, "erro", detalhe)
        messages.error(request, detalhe)
        return redirect(_redirect_email_list_with_filters(account, request))

    action_map = {
        "suspend_user": (
            "suspender usuario",
            client.suspend_user,
            {"full_email": full_email},
            f"Usuário {full_email} suspenso com sucesso.",
        ),
        "unsuspend_user": (
            "reativar usuario",
            client.unsuspend_user,
            {"full_email": full_email},
            f"Usuário {full_email} reativado com sucesso.",
        ),
        "delete": (
            "excluir",
            client.delete_email,
            {"email": full_email.split("@")[0], "domain": domain},
            f"Conta {full_email} excluída com sucesso.",
        ),
    }
    if action == "change_password":
        action_map["change_password"] = (
            "alterar senha",
            client.change_password,
            {"email": full_email.split("@")[0], "domain": domain, "password": password_form.cleaned_data["password"]},
            f"Senha de {full_email} alterada com sucesso.",
        )
    label, handler, params, success_message = action_map[action]

    try:
        handler(**params)
    except Exception as exc:
        detalhe = _friendly_error(exc)
        logger.exception("Erro ao executar '%s' para %s", action, full_email)
        _log_operation(request.user, full_email, label, "erro", detalhe)
        messages.error(request, detalhe)
    else:
        _invalidate_cpanel_account_cache(account, domain)
        _log_operation(request.user, full_email, label, "sucesso")
        messages.success(request, success_message)
    return redirect(_redirect_email_list_with_filters(account, request))


@require_GET
@admin_required
def historico(request):
    logs = EmailLog.objects.select_related("usuario").all()
    user_term = request.GET.get("user", "").strip()
    email_term = request.GET.get("email", "").strip()
    status_filter = request.GET.get("status", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    sort_field = request.GET.get("sort", "created").strip()
    sort_direction = request.GET.get("dir", "desc").strip()
    if sort_field not in {"user", "email", "action", "status", "created"}:
        sort_field = "created"
    if sort_direction not in {"asc", "desc"}:
        sort_direction = "desc"
    available_users = User.objects.filter(email_logs__isnull=False).order_by("username").distinct()
    logs = _filter_logs(
        logs,
        user_term=user_term,
        email_term=email_term,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
    )
    logs = _sort_logs(logs, sort_field=sort_field, direction=sort_direction)
    page_obj, page_query = _paginate_items(request, logs, HISTORY_PER_PAGE)
    return render(
        request,
        "emails/detail.html",
        {
            "logs": page_obj.object_list,
            "page_obj": page_obj,
            "page_query": page_query,
            "user_term": user_term,
            "available_users": available_users,
            "email_term": email_term,
            "status_filter": status_filter,
            "date_from": date_from,
            "date_to": date_to,
            "sort_field": sort_field,
            "sort_direction": sort_direction,
            "user_sort_query": _build_sort_query(request, "user"),
            "email_sort_query": _build_sort_query(request, "email"),
            "action_sort_query": _build_sort_query(request, "action"),
            "status_sort_query": _build_sort_query(request, "status"),
            "created_sort_query": _build_sort_query(request, "created"),
            "user_sort_indicator": _sort_indicator(sort_field, sort_direction, "user"),
            "email_sort_indicator": _sort_indicator(sort_field, sort_direction, "email"),
            "action_sort_indicator": _sort_indicator(sort_field, sort_direction, "action"),
            "status_sort_indicator": _sort_indicator(sort_field, sort_direction, "status"),
            "created_sort_indicator": _sort_indicator(sort_field, sort_direction, "created"),
            "filtered_total": logs.count(),
        },
    )


@require_GET
@admin_required
def listar_usuarios(request):
    users = User.objects.select_related("profile").order_by("username")
    page_obj, page_query = _paginate_items(request, users, SYSTEM_USERS_PER_PAGE)
    return render(
        request,
        "emails/users.html",
        {"users": page_obj.object_list, "page_obj": page_obj, "page_query": page_query},
    )


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
