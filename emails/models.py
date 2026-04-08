from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    is_admin = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "perfil de usuario"
        verbose_name_plural = "perfis de usuarios"

    def __str__(self) -> str:
        return f"Perfil de {self.user.username}"


class EmailLog(models.Model):
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="email_logs",
    )
    email = models.EmailField()
    acao = models.CharField(max_length=50)
    status = models.CharField(max_length=20)
    detalhe = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "log de e-mail"
        verbose_name_plural = "logs de e-mails"

    def __str__(self) -> str:
        return f"{self.email} - {self.acao} ({self.status})"


class WorkspaceSetting(models.Model):
    google_workspace_user_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="limite de usuarios do Google Workspace",
    )
    google_workspace_alert_email = models.EmailField(
        blank=True,
        default="sistemas@oratelecom.com.br",
        verbose_name="e-mail de alerta do Google Workspace",
    )
    limit_reached_email_sent_at = models.DateTimeField(null=True, blank=True)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workspace_settings_updates",
    )
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "configuracao do workspace"
        verbose_name_plural = "configuracoes do workspace"

    def __str__(self) -> str:
        return "Configuracao do Google Workspace"

    @classmethod
    def get_solo(cls) -> "WorkspaceSetting":
        instance, _ = cls.objects.get_or_create(pk=1)
        return instance

    def mark_limit_email_sent(self) -> None:
        self.limit_reached_email_sent_at = timezone.now()
        self.save(update_fields=["limit_reached_email_sent_at", "atualizado_em"])

    def clear_limit_email_sent(self) -> None:
        if self.limit_reached_email_sent_at is None:
            return
        self.limit_reached_email_sent_at = None
        self.save(update_fields=["limit_reached_email_sent_at", "atualizado_em"])


@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance, is_admin=instance.is_superuser)
    else:
        profile, _ = UserProfile.objects.get_or_create(user=instance)
        if instance.is_superuser and not profile.is_admin:
            profile.is_admin = True
            profile.save(update_fields=["is_admin"])
