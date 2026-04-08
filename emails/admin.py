from django.contrib import admin

from .models import EmailLog, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "is_admin", "criado_em")
    list_filter = ("is_admin",)
    search_fields = ("user__username", "user__email", "user__first_name", "user__last_name")


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ("email", "usuario", "acao", "status", "criado_em")
    list_filter = ("acao", "status", "criado_em")
    search_fields = ("email", "detalhe", "usuario__username")
