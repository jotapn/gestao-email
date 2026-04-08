from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User

PASSWORD_RULES_HELP = "Minimo de 8 caracteres, letra maiuscula, minuscula, numero e caractere especial."


class EmailCreateForm(forms.Form):
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

    def clean_nome(self):
        nome = self.cleaned_data["nome"].strip().lower()
        if "@" in nome:
            raise forms.ValidationError("Informe apenas o nome antes do dominio.")
        return nome


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


class SystemUserForm(forms.ModelForm):
    first_name = forms.CharField(label="Nome", required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    last_name = forms.CharField(label="Sobrenome", required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    email = forms.EmailField(label="E-mail", required=False, widget=forms.EmailInput(attrs={"class": "form-control"}))
    is_active = forms.BooleanField(label="Usuario ativo", required=False)
    is_admin = forms.BooleanField(label="Administrador do sistema", required=False)
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
        if self.instance.pk:
            self.fields["password"].help_text = "Preencha apenas se quiser redefinir a senha."
            self.fields["is_admin"].initial = getattr(self.instance.profile, "is_admin", False)
        else:
            self.fields["password"].required = True

    def clean_password(self):
        password = self.cleaned_data.get("password", "")
        if not self.instance.pk and not password:
            raise forms.ValidationError("Informe uma senha inicial.")
        return password

    def clean(self):
        cleaned_data = super().clean()
        if self.current_user and self.instance.pk == self.current_user.pk and not cleaned_data.get("is_active", True):
            self.add_error("is_active", "Voce nao pode inativar seu proprio usuario.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        if commit:
            user.save()
            profile = user.profile
            profile.is_admin = self.cleaned_data.get("is_admin", False)
            profile.save()
        return user


class GoogleWorkspaceUserCreateForm(forms.Form):
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

    def clean_nome(self):
        nome = self.cleaned_data["nome"].strip().lower()
        if "@" in nome:
            raise forms.ValidationError("Informe apenas o nome antes do dominio.")
        return nome


class GoogleWorkspaceActionForm(forms.Form):
    ACTION_CHOICES = (
        ("suspend_user", "Suspender usuario"),
        ("unsuspend_user", "Reativar usuario"),
        ("change_password", "Alterar senha"),
        ("delete", "Excluir"),
    )

    action = forms.ChoiceField(choices=ACTION_CHOICES)
