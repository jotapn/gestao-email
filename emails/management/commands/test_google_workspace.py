from django.core.management.base import BaseCommand, CommandError

from emails.services.google_workspace_client import GoogleWorkspaceAPIError, GoogleWorkspaceClient


class Command(BaseCommand):
    help = "Valida a conexao com Google Workspace e lista usuarios do dominio configurado."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10)

    def handle(self, *args, **options):
        try:
            client = GoogleWorkspaceClient()
            users = client.list_users(max_results=options["limit"])
        except GoogleWorkspaceAPIError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Google Workspace OK. {len(users)} usuario(s) retornado(s) para o dominio {client.domain}."
            )
        )
        for user in users:
            status = "suspenso" if user.suspended else "ativo"
            self.stdout.write(f"- {user.primary_email} | {status} | OU {user.org_unit_path}")
