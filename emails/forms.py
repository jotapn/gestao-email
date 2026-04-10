from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
)
from django.contrib.auth.models import User

from .models import WorkspaceSetting

PASSWORD_RULES_HELP = "Minimo de 8 caracteres, letra maiuscula, minuscula, numero e caractere especial."


class SMSPhoneFieldsMixin:
    def clean_sms_phone_fields(self):
        cleaned_data = super().clean()
        ddd = "".join(filter(str.isdigit, cleaned_data.get("telefone_ddd", "")))
        numero = "".join(filter(str.isdigit, cleaned_data.get("telefone_numero", "")))

        cleaned_data["telefone_ddd"] = ddd
        cleaned_data["telefone_numero"] = numero

        if not ddd and not numero:
            return cleaned_data

        if not ddd or not numero:
            message = "Informe DDD e numero para enviar o SMS."
            if not ddd:
                self.add_error("telefone_ddd", message)
            if not numero:
                self.add_error("telefone_numero", message)
            return cleaned_data

        if len(ddd) != 2:
            self.add_error("telefone_ddd", "Informe um DDD valido com 2 digitos.")

        if len(numero) not in {8, 9}:
            self.add_error("telefone_numero", "Informe um numero valido com 8 ou 9 digitos.")

        if not self.errors:
            cleaned_data["telefone_completo"] = f"55{ddd}{numero}"
        return cleaned_data


class EmailCreateForm(SMSPhoneFieldsMixin, forms.Form):
    nome = forms.CharField(
        max_length=50,
        label="Nome",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "contato"}),
    )
    senha = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Senha segura"}),
        min_length=8,
        label="Senha",
        help_text=PASSWORD_RULES_HELP,
    )
    quota = forms.IntegerField(
        initial=1024,
        min_value=0,
        label="Quota (MB)",
        help_text="Use 0 para ilimitado.",
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )
    telefone_ddd = forms.CharField(
        max_length=4,
        required=False,
        label="DDD",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "86",
                "inputmode": "numeric",
                "autocomplete": "tel-area-code",
            }
        ),
    )
    telefone_numero = forms.CharField(
        max_length=20,
        required=False,
        label="Numero",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "99999-9999",
                "inputmode": "numeric",
                "autocomplete": "tel-local",
            }
        ),
    )

    def clean_nome(self):
        nome = self.cleaned_data["nome"].strip().lower()
        if "@" in nome:
            raise forms.ValidationError("Informe apenas o nome antes do dominio.")
        return nome

    def clean(self):
        return self.clean_sms_phone_fields()


class EmailActionForm(forms.Form):
    ACTION_CHOICES = (
        ("suspend_user", "Suspender usuario"),
        ("unsuspend_user", "Reativar usuario"),
        ("change_password", "Alterar senha"),
        ("delete", "Excluir"),
    )

    action = forms.ChoiceField(choices=ACTION_CHOICES)


class EmailPasswordChangeForm(forms.Form):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Nova senha"}),
        min_length=8,
        label="Nova senha",
        help_text=PASSWORD_RULES_HELP,
    )


class AccountSelectForm(forms.Form):
    account = forms.CharField(required=False)
    domain = forms.CharField(required=False)


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Usuario",
        widget=forms.TextInput(attrs={"class": "form-control", "autofocus": True}),
    )
    password = forms.CharField(
        label="Senha",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )


class StyledPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(
        label="E-mail",
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "placeholder": "voce@empresa.com.br",
                "autocomplete": "email",
            }
        ),
    )


class StyledSetPasswordForm(SetPasswordForm):
    new_password1 = forms.CharField(
        label="Nova senha",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Digite a nova senha",
                "autocomplete": "new-password",
            }
        ),
    )
    new_password2 = forms.CharField(
        label="Confirme a nova senha",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Repita a nova senha",
                "autocomplete": "new-password",
            }
        ),
    )


class SystemUserForm(forms.ModelForm):
    ROLE_CHOICES = (
        ("operator", "Operador"),
        ("admin", "Admin"),
        ("system_admin", "Admin do sistema"),
    )

    first_name = forms.CharField(label="Nome", required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    last_name = forms.CharField(label="Sobrenome", required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    email = forms.EmailField(label="E-mail", required=False, widget=forms.EmailInput(attrs={"class": "form-control"}))
    is_active = forms.BooleanField(label="Usuario ativo", required=False)
    role = forms.ChoiceField(label="Perfil", choices=ROLE_CHOICES, widget=forms.Select(attrs={"class": "form-select"}))
    password = forms.CharField(
        label="Senha inicial",
        required=False,
        min_length=8,
        help_text=PASSWORD_RULES_HELP,
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "is_active")
        widgets = {"username": forms.TextInput(attrs={"class": "form-control"})}
        labels = {"username": "Usuario"}

    def __init__(self, *args, **kwargs):
        self.current_user = kwargs.pop("current_user", None)
        super().__init__(*args, **kwargs)
        if not getattr(getattr(self.current_user, "profile", None), "is_system_admin", False):
            self.fields["role"].choices = tuple(
                choice for choice in self.ROLE_CHOICES if choice[0] != "system_admin"
            )
        if self.instance.pk:
            self.fields["password"].help_text = "Preencha apenas se quiser redefinir a senha."
            self.fields["role"].initial = getattr(self.instance.profile, "role", "operator")
        else:
            self.fields["password"].required = True
            self.fields["role"].initial = "operator"

    def clean_password(self):
        password = self.cleaned_data.get("password", "")
        if not self.instance.pk and not password:
            raise forms.ValidationError("Informe uma senha inicial.")
        return password

    def clean(self):
        cleaned_data = super().clean()
        if (
            self.current_user
            and cleaned_data.get("role") == "system_admin"
            and not getattr(getattr(self.current_user, "profile", None), "is_system_admin", False)
        ):
            self.add_error("role", "Apenas admins do sistema podem atribuir esse perfil.")
        if self.current_user and self.instance.pk == self.current_user.pk and not cleaned_data.get("is_active", True):
            self.add_error("is_active", "Voce nao pode inativar seu proprio usuario.")
        if (
            self.current_user
            and self.instance.pk == self.current_user.pk
            and getattr(self.current_user.profile, "is_system_admin", False)
            and cleaned_data.get("role") != "system_admin"
        ):
            self.add_error("role", "Voce nao pode remover seu proprio perfil de admin do sistema.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        if commit:
            user.save()
            profile = user.profile
            role = self.cleaned_data.get("role", "operator")
            profile.is_admin = role == "admin"
            profile.is_system_admin = role == "system_admin"
            profile.save()
        return user


class SelfProfileForm(forms.ModelForm):
    username = forms.CharField(
        label="Usuario",
        disabled=True,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "readonly": True}),
    )
    first_name = forms.CharField(
        label="Nome",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    last_name = forms.CharField(
        label="Sobrenome",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    email = forms.EmailField(
        label="E-mail",
        required=False,
        widget=forms.EmailInput(attrs={"class": "form-control"}),
    )

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email")


class StyledPasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(
        label="Senha atual",
        strip=False,
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "autocomplete": "current-password"}
        ),
    )
    new_password1 = forms.CharField(
        label="Nova senha",
        strip=False,
        help_text=PASSWORD_RULES_HELP,
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "autocomplete": "new-password"}
        ),
    )
    new_password2 = forms.CharField(
        label="Confirme a nova senha",
        strip=False,
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "autocomplete": "new-password"}
        ),
    )


class GoogleWorkspaceUserCreateForm(SMSPhoneFieldsMixin, forms.Form):
    nome = forms.CharField(
        max_length=50,
        label="Nome do e-mail",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "contato"}),
    )
    first_name = forms.CharField(
        max_length=150,
        label="Nome",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Joao"}),
    )
    last_name = forms.CharField(
        max_length=150,
        label="Sobrenome",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Silva"}),
    )
    senha = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Senha segura"}),
        min_length=8,
        label="Senha",
        help_text=PASSWORD_RULES_HELP,
    )
    telefone_ddd = forms.CharField(
        max_length=4,
        required=False,
        label="DDD",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "86",
                "inputmode": "numeric",
                "autocomplete": "tel-area-code",
            }
        ),
    )
    telefone_numero = forms.CharField(
        max_length=20,
        required=False,
        label="Numero",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "99999-9999",
                "inputmode": "numeric",
                "autocomplete": "tel-local",
            }
        ),
    )

    def clean_nome(self):
        nome = self.cleaned_data["nome"].strip().lower()
        if "@" in nome:
            raise forms.ValidationError("Informe apenas o nome antes do dominio.")
        return nome

    def clean(self):
        return self.clean_sms_phone_fields()


class GoogleWorkspaceActionForm(forms.Form):
    ACTION_CHOICES = (
        ("suspend_user", "Suspender usuario"),
        ("unsuspend_user", "Reativar usuario"),
        ("change_password", "Alterar senha"),
        ("delete", "Excluir"),
    )

    action = forms.ChoiceField(choices=ACTION_CHOICES)


class WorkspaceSettingForm(forms.ModelForm):
    class Meta:
        model = WorkspaceSetting
        fields = ("google_workspace_user_limit", "google_workspace_alert_email")
        labels = {
            "google_workspace_user_limit": "Limite de usuarios do Google Workspace",
            "google_workspace_alert_email": "E-mail para alerta de limite",
        }
        widgets = {
            "google_workspace_user_limit": forms.NumberInput(
                attrs={"class": "form-control", "min": "0", "placeholder": "Ex: 120"}
            ),
            "google_workspace_alert_email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "sistemas@oratelecom.com.br"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["google_workspace_user_limit"].help_text = (
            "Quantidade maxima de usuarios permitida para controle interno."
        )
        self.fields["google_workspace_alert_email"].help_text = (
            "Destinatario que recebera o aviso quando o limite for atingido."
        )
