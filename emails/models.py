from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


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


@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance, is_admin=instance.is_superuser)
    else:
        profile, _ = UserProfile.objects.get_or_create(user=instance)
        if instance.is_superuser and not profile.is_admin:
            profile.is_admin = True
            profile.save(update_fields=["is_admin"])
