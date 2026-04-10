# Sistema de Gestao de E-mails

Aplicacao web em Django para administrar contas de e-mail em servidores cPanel/WHM e usuarios do Google Workspace.

O sistema centraliza operacoes administrativas em uma interface unica, com autenticacao local do Django, historico de acoes e controle de perfis de acesso.

## O que o sistema faz

- Lista contas cPanel disponiveis para gerenciamento.
- Lista caixas de e-mail por conta, com busca e filtro por status.
- Cria contas de e-mail no cPanel.
- Suspende, reativa, altera senha e exclui contas de e-mail.
- Lista usuarios do Google Workspace.
- Cria, suspende, reativa, altera senha e exclui usuarios do Google Workspace.
- Controla limite interno de usuarios do Google Workspace e envia alerta por e-mail ao atingir o limite.
- Gerencia usuarios internos do sistema com perfis `Operador`, `Admin` e `Admin do sistema`.
- Registra historico local das operacoes executadas.

## Stack

- Python 3.11+
- Django 5.2
- Django REST Framework
- Requests
- Google Admin SDK / Licensing API
- SQLite ou MySQL

## Requisitos

- Python 3.11 ou superior
- `pip`
- Acesso a pelo menos uma destas integracoes:
  - WHM com token de API
  - cPanel com token UAPI
  - Google Workspace com service account e domain-wide delegation

## Instalacao

1. Crie e ative um ambiente virtual.
2. Instale as dependencias:

```bash
pip install -r requirements.txt
```

3. Crie um arquivo `.env` na raiz do projeto.
4. Execute as migracoes:

```bash
python manage.py migrate
```

5. Crie o primeiro usuario administrativo:

```bash
python manage.py createsuperuser
```

6. Inicie a aplicacao:

```bash
python manage.py runserver
```

## Configuracao do `.env`

As variaveis abaixo cobrem os modos suportados pelo projeto. Nem todas sao obrigatorias ao mesmo tempo.

### Basico

```env
SECRET_KEY=troque-esta-chave
DEBUG=False
ALLOWED_HOSTS=127.0.0.1,localhost,intranet.seu-dominio.local,10.0.0.15
CSRF_TRUSTED_ORIGINS=http://intranet.seu-dominio.local,http://10.0.0.15
APP_PORT=8001
USE_PROXY_SSL_HEADER=False
SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
SECURE_HSTS_SECONDS=0
SECURE_HSTS_INCLUDE_SUBDOMAINS=False
SECURE_HSTS_PRELOAD=False
REQUEST_TIMEOUT=30
```

### Banco de dados

Por padrao, o projeto usa SQLite.

```env
DB_ENGINE=sqlite
SQLITE_PATH=/app/data/db.sqlite3
```

Para MySQL:

```env
DB_ENGINE=mysql
DB_NAME=seu_banco
DB_USER=seu_usuario
DB_PASSWORD=sua_senha
DB_HOST=127.0.0.1
DB_PORT=3306
```

### Modo recomendado: WHM

Quando `WHM_HOST`, `WHM_USER` e `WHM_TOKEN` estao configurados, o sistema entra em modo `WHM` e descobre automaticamente as contas cPanel.

```env
WHM_HOST=https://seu-whm.com:2087
WHM_USER=root
WHM_TOKEN=seu_token_whm
WHM_VERIFY_SSL=True
HIDDEN_CPANEL_DOMAINS=dominio-interno.com.br,outro-dominio.com.br
```

### Modo alternativo: cPanel direto

Use este modo quando nao houver acesso ao WHM. Nesse caso, a aplicacao gerencia uma unica conta cPanel.

```env
CPANEL_HOST=https://seu-cpanel.com:2083
CPANEL_USER=usuario_cpanel
CPANEL_TOKEN=seu_token_uapi
CPANEL_DOMAIN=seudominio.com.br
CPANEL_VERIFY_SSL=True
```

### SMS de boas-vindas

Ao criar uma conta de e-mail, a tela permite informar `DDD` e `numero`. Quando ambos sao preenchidos, o sistema envia um SMS de boas-vindas com o e-mail criado e o link de acesso.

```env
CAPITAL_MOBILE_SMS_ENDPOINT=https://portal.capitalmobile.com.br/post/index.php
CAPITAL_MOBILE_SMS_USER=seu_usuario
CAPITAL_MOBILE_SMS_PASSWORD=sua_senha
CAPITAL_MOBILE_SMS_COOKIE=
CAPITAL_MOBILE_SMS_MAX_LENGTH=160
```

- Para dominios cPanel, o link enviado no SMS usa `https://webmail.seu-dominio.com.br`.
- Para o dominio configurado em `GOOGLE_WORKSPACE_DOMAIN`, o link enviado no SMS usa `https://mail.google.com/`.

### Envio de e-mails do sistema

Usado para notificacoes, incluindo envio de credenciais de usuarios internos e alertas do Google Workspace.

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.seudominio.com.br
EMAIL_PORT=465
EMAIL_HOST_USER=usuario@seudominio.com.br
EMAIL_HOST_PASSWORD=sua_senha
EMAIL_USE_TLS=False
EMAIL_USE_SSL=True
DEFAULT_FROM_EMAIL=usuario@seudominio.com.br
```

Para desenvolvimento, voce pode usar o backend de console:

```env
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

### Google Workspace

Para habilitar o modulo Google Workspace:

```env
GOOGLE_WORKSPACE_DOMAIN=seudominio.com.br
GOOGLE_WORKSPACE_ADMIN_EMAIL=admin@seudominio.com.br
GOOGLE_SERVICE_ACCOUNT_FILE=assets/service_account.json
GOOGLE_SERVICE_ACCOUNT_JSON=
GOOGLE_SERVICE_ACCOUNT_PROJECT_ID=seu-project-id
GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_ID=sua-private-key-id
GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n
GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL=bot@seu-projeto.iam.gserviceaccount.com
GOOGLE_SERVICE_ACCOUNT_CLIENT_ID=1234567890
GOOGLE_SERVICE_ACCOUNT_TOKEN_URI=https://oauth2.googleapis.com/token
GOOGLE_WORKSPACE_DEFAULT_ORG_UNIT=
GOOGLE_WORKSPACE_LICENSING_ENABLED=False
GOOGLE_WORKSPACE_PRODUCT_ID=
GOOGLE_WORKSPACE_SKU_ID=
```

Se `GOOGLE_WORKSPACE_LICENSING_ENABLED=True`, tambem e necessario informar `GOOGLE_WORKSPACE_PRODUCT_ID` e `GOOGLE_WORKSPACE_SKU_ID`.

No Coolify, a forma mais pratica e usar as credenciais Google em variaveis separadas. `GOOGLE_SERVICE_ACCOUNT_JSON` e `GOOGLE_SERVICE_ACCOUNT_FILE` continuam disponiveis como alternativas.

## Como o sistema escolhe o modo cPanel

- Se `WHM_HOST`, `WHM_USER` e `WHM_TOKEN` estiverem preenchidos, o sistema usa `WHM`.
- Caso contrario, tenta operar em `cPanel direto`.
- Se nenhum dos dois blocos estiver configurado corretamente, as telas de cPanel exibirao erro de configuracao.

## Perfis de acesso

O projeto usa autenticacao local do Django e cria automaticamente um perfil para cada usuario.

- `Operador`: acessa as operacoes de e-mail e Google Workspace.
- `Admin`: possui acesso adicional ao historico e ao cadastro de usuarios internos.
- `Admin do sistema`: possui todas as permissoes, incluindo configuracao do Google Workspace.

Usuarios criados com `createsuperuser` sao registrados como `Admin do sistema`.

## Fluxos principais

### cPanel / WHM

- A pagina inicial lista as contas cPanel disponiveis.
- Em modo `WHM`, a listagem vem da chamada `listaccts`.
- Ao entrar em uma conta, as operacoes de caixa postal sao executadas via UAPI.
- Dominios definidos em `HIDDEN_CPANEL_DOMAINS` nao aparecem na interface.

### Google Workspace

- A tela de dashboard mostra totais de usuarios ativos e suspensos.
- A listagem permite busca e filtro por status.
- O cadastro de usuario usa a Admin SDK Directory API.
- O sistema pode atribuir licenca automaticamente quando essa opcao estiver habilitada.
- Um limite interno de usuarios pode ser configurado pela interface; ao atingir o limite, um e-mail de alerta e enviado uma unica vez ate que o limite seja alterado ou normalizado.

## Regras de senha na interface

Atualmente, os formularios validam senha com minimo de 8 caracteres e exibem orientacao visual recomendando uso de:

- letra maiuscula
- letra minuscula
- numero
- caractere especial

## Estrutura principal

```text
config/                  Configuracao do projeto Django
emails/                  App principal
emails/services/         Integracoes com cPanel/WHM e Google Workspace
emails/templates/        Templates HTML
emails/management/       Comandos auxiliares
requirements.txt         Dependencias Python
README.md                Documentacao do projeto
```

## Comandos uteis

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
python manage.py test
python manage.py test_google_workspace
```

## Deploy com Docker

Arquivos adicionados para deploy:

- `Dockerfile`
- `docker-compose.yml`
- `entrypoint.sh`
- `.dockerignore`

Fluxo basico:

```bash
docker compose build
docker compose up -d
```

A aplicacao sobe exposta na porta `8001`.

### Deploy em intranet via Coolify

Para uso em intranet da empresa, via HTTP e hospedado no Coolify:

- mantenha `SECURE_SSL_REDIRECT=False`
- mantenha `SESSION_COOKIE_SECURE=False`
- mantenha `CSRF_COOKIE_SECURE=False`
- mantenha `SECURE_HSTS_SECONDS=0`
- use `CSRF_TRUSTED_ORIGINS` com enderecos `http://...`
- ajuste `ALLOWED_HOSTS` com hostname interno e IP da intranet
- cadastre as variaveis no painel do Coolify; o `docker-compose.yml` nao depende mais de `env_file: .env`
- configure no Coolify a porta publica apontando para a porta interna `8001`

O container:

- executa `migrate` ao iniciar
- executa `collectstatic`
- sobe a aplicacao com `gunicorn`
- serve arquivos estaticos com `whitenoise`

Para uso com SQLite em container, o `docker-compose.yml` ja aponta `SQLITE_PATH=/app/data/db.sqlite3` com volume persistente.

## Observacoes operacionais

- `WHM_VERIFY_SSL=False` e `CPANEL_VERIFY_SSL=False` devem ser usados apenas em ambientes controlados.
- O Google Workspace pode usar credenciais em variaveis separadas, `GOOGLE_SERVICE_ACCOUNT_JSON` ou, alternativamente, um arquivo em `GOOGLE_SERVICE_ACCOUNT_FILE`.
- O historico de operacoes e salvo no banco local da aplicacao.
- A exclusao de caixa postal no cPanel possui tratamento para timeout e tenta validar se a conta realmente saiu da listagem.

## Proximos cuidados recomendados

- Nao versionar `.env`, tokens, senhas SMTP ou credenciais Google.
- Manter `DEBUG=False` em producao.
- Restringir `ALLOWED_HOSTS` aos hosts reais do ambiente.
- Configurar SMTP funcional se houver envio de notificacoes reais.
