# Sistema Django de Gerenciamento de E-mails via cPanel e WHM

Sistema web em Django para listar, criar, suspender e excluir contas de e-mail.

O sistema suporta dois modos:

- `WHM`: descobre varias contas cPanel automaticamente e executa a UAPI via WHM API 1
- `cPanel direto`: conecta em uma unica conta cPanel como fallback

## Requisitos

- Python 3.11+
- WHM com token de API ou uma conta cPanel com token UAPI

## Configuracao

1. Crie e ative uma virtualenv.
2. Instale as dependencias:

```bash
pip install -r requirements.txt
```

3. Copie `.env.example` para `.env` e ajuste os valores.

### Modo recomendado: WHM

```env
SECRET_KEY=troque-esta-chave
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost
WHM_HOST=https://seu-whm.com:2087
WHM_USER=root
WHM_TOKEN=seu_token_whm
WHM_VERIFY_SSL=True
HIDDEN_CPANEL_DOMAINS=oratelecom.com.br,outrodominio.com.br
REQUEST_TIMEOUT=30
```

### Modo alternativo: cPanel direto

```env
SECRET_KEY=troque-esta-chave
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost
WHM_HOST=
WHM_USER=
WHM_TOKEN=
WHM_VERIFY_SSL=True
HIDDEN_CPANEL_DOMAINS=oratelecom.com.br
CPANEL_HOST=https://seuhost.com:2083
CPANEL_USER=usuario_cpanel
CPANEL_TOKEN=seu_token_aqui
CPANEL_DOMAIN=seudominio.com
CPANEL_VERIFY_SSL=True
REQUEST_TIMEOUT=30
```

4. Rode as migracoes:

```bash
python manage.py migrate
```

## Execucao

```bash
python manage.py runserver
```

## Como gerar o token no WHM

1. Entre no WHM com o usuario `root` ou um reseller com permissao suficiente.
2. Abra `Development` > `Manage API Tokens`.
3. Crie um token e guarde o valor, porque a interface nao mostra o token novamente depois.
4. Salve os dados em `WHM_HOST`, `WHM_USER` e `WHM_TOKEN`.

## Fluxo no modo WHM

- o sistema consulta as contas via `listaccts`
- voce escolhe a conta cPanel pela interface
- as acoes de e-mail sao executadas via `uapi_cpanel` no usuario selecionado
- isso elimina a necessidade de trocar `.env` para cada cPanel
- domínios em `HIDDEN_CPANEL_DOMAINS` nao aparecem na interface

## Funcionalidades

- Listagem de caixas com status e quota
- Seletor de conta cPanel quando usar WHM
- Criacao de e-mail por formulario
- Suspensao de login, envio e recebimento
- Exclusao com confirmacao
- Historico local de operacoes em SQLite
