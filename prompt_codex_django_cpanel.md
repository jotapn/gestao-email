# Prompt para o Codex — Sistema Django de Gerenciamento de E-mails via cPanel UAPI

## 🧱 STACK E REQUISITOS

- Python 3.11+
- Django 5.x
- Django REST Framework (para API interna, se necessário)
- `requests` (para chamadas à UAPI do cPanel)
- `python-decouple` (variáveis de ambiente via `.env`)
- Bootstrap 5 via CDN (templates HTML simples e funcionais)
- SQLite em desenvolvimento

---

## 🔐 CONFIGURAÇÕES (.env)

O sistema deve ler as seguintes variáveis de ambiente:

```env
CPANEL_HOST=https://seuhost.com:2083
CPANEL_USER=usuario_cpanel
CPANEL_TOKEN=seu_token_aqui
CPANEL_DOMAIN=seudominio.com
```

---

## 📦 ESTRUTURA DE APPS

Crie um app chamado `emails` com a seguinte estrutura:

```
emails/
├── services/
│   └── cpanel_client.py   ← client de integração com a UAPI
├── models.py              ← log/histórico de operações
├── views.py
├── urls.py
├── forms.py
└── templates/emails/
    ├── base.html
    ├── list.html
    ├── create.html
    └── detail.html
```

---

## 🔌 CPANEL CLIENT (`emails/services/cpanel_client.py`)

Crie uma classe `CpanelClient` com os seguintes métodos:

```python
class CpanelClient:
    def __init__(self):
        # Lê host, user e token do .env via python-decouple

    def _get(self, endpoint: str, params: dict = None) -> dict:
        # GET em https://HOST/execute/ENDPOINT
        # Header: Authorization: cpanel USUARIO:TOKEN
        # verify=False (configurável via .env)

    def list_emails(self, domain: str) -> list:
        # Endpoint: Email/list_pops_with_disk

    def create_email(self, email: str, password: str, quota: int = 1024) -> dict:
        # Endpoint: Email/add_pop

    def suspend_login(self, full_email: str) -> dict:
        # Endpoint: Email/suspend_login

    def unsuspend_login(self, full_email: str) -> dict:
        # Endpoint: Email/unsuspend_login

    def suspend_outgoing(self, full_email: str) -> dict:
        # Endpoint: Email/suspend_outgoing

    def suspend_incoming(self, full_email: str) -> dict:
        # Endpoint: Email/suspend_incoming

    def delete_email(self, email: str, domain: str) -> dict:
        # Endpoint: Email/delete_pop
```

> Todas as chamadas usam HTTPS e verificam o campo `errors` na resposta JSON da UAPI.

---

## 🖥️ VIEWS E FUNCIONALIDADES

### 1. Listar e-mails — `GET /`
- Chama `list_emails()` e exibe em tabela responsiva
- Colunas: **E-mail | Quota usada/total | Status | Ações**

### 2. Criar e-mail — `GET /POST /criar/`
- Formulário com campos: nome (sem domínio), senha, quota (MB)
- Domínio fixo vindo do `.env`
- Validação básica (senha mínimo 8 caracteres)
- Feedback via Django `messages`

### 3. Ações sobre e-mail — `POST /acao/<email>/`
- Botões de ação disponíveis:
  - Suspender login
  - Reativar login
  - Suspender envio
  - Suspender recebimento
  - Excluir (com confirmação via modal Bootstrap)
- Redireciona para lista após ação com mensagem de feedback

---

## 📋 FORMULÁRIOS (`forms.py`)

```python
class EmailCreateForm(forms.Form):
    nome   = forms.CharField(max_length=50)
    senha  = forms.CharField(widget=forms.PasswordInput, min_length=8)
    quota  = forms.IntegerField(initial=1024, min_value=0)  # 0 = ilimitado
```

---

## 🗄️ MODEL DE HISTÓRICO (`models.py`)

```python
class EmailLog(models.Model):
    email      = models.EmailField()
    acao       = models.CharField(max_length=50)   # "criado", "suspenso", "excluído"
    status     = models.CharField(max_length=20)   # "sucesso" ou "erro"
    detalhe    = models.TextField(blank=True)
    criado_em  = models.DateTimeField(auto_now_add=True)
```

---

## 🌐 URLS (`emails/urls.py`)

```python
urlpatterns = [
    path("",                  views.listar_emails, name="email-list"),
    path("criar/",            views.criar_email,   name="email-create"),
    path("acao/<str:email>/", views.acao_email,    name="email-action"),
    path("historico/",        views.historico,     name="email-log"),
]
```

---

## 🎨 TEMPLATES

Use **Bootstrap 5 via CDN**. Os templates devem conter:

| Template | Descrição |
|---|---|
| `base.html` | Navbar, bloco de mensagens Django, footer |
| `list.html` | Tabela responsiva com badge de status e botões de ação |
| `create.html` | Formulário centralizado com validação |
| Modal Bootstrap | Confirmação de exclusão antes de deletar |

---

## ⚠️ TRATAMENTO DE ERROS

- Envolver todas as chamadas ao `CpanelClient` em `try/except`
- Exibir mensagens amigáveis via Django `messages`
- Logar erros no console com o módulo `logging` do Django
- Verificar e tratar o campo `errors` na resposta JSON da UAPI

---

## 📁 ENTREGÁVEIS ESPERADOS

1. Projeto Django completo e funcional
2. Arquivo `.env.example` com todas as variáveis necessárias
3. `requirements.txt`
4. `README.md` com:
   - Como configurar o `.env`
   - Como rodar: `python manage.py runserver`
   - Como criar o token no painel do cPanel

---

## ✅ REFERÊNCIA RÁPIDA — ENDPOINTS UAPI

| Ação | Endpoint |
|---|---|
| Listar e-mails | `Email/list_pops_with_disk` |
| Criar e-mail | `Email/add_pop` |
| Suspender login | `Email/suspend_login` |
| Reativar login | `Email/unsuspend_login` |
| Suspender envio | `Email/suspend_outgoing` |
| Suspender recebimento | `Email/suspend_incoming` |
| Excluir e-mail | `Email/delete_pop` |

> **Base URL:** `https://SEU_HOST:2083/execute/`  
> **Header:** `Authorization: cpanel USUARIO:TOKEN`

---

## 🚀 CRITÉRIOS DE QUALIDADE

- Nenhuma credencial hardcoded no código
- Código organizado em funções/métodos reutilizáveis
- Usar apenas a UAPI (nunca a API 2 legada do cPanel)
- Sempre HTTPS nas chamadas ao cPanel
- Compatível com **Python 3.11+** e **Django 5.x**
