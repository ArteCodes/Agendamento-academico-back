"""
Teste manual da configuração de e-mail (SMTP).

Uso, a partir da raiz do projeto:

    app\\.venv\\Scripts\\python.exe app\\scripts\\testar_email.py --para aluno@teste.com

O e-mail usa o mesmo serviço das notificações de status (app/services/email.py).
A senha SMTP nunca é exibida. Para desenvolvimento, use Mailtrap ou MailHog.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "app"
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(APP_DIR / ".env")

from app.services import email as email_service  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Envia um e-mail de teste usando a configuração SMTP do app/.env",
    )
    parser.add_argument("--para", required=True, help="destinatário do e-mail de teste")
    parser.add_argument("--nome", default=None, help="nome usado na saudação")
    args = parser.parse_args()

    print("Configuração atual:")
    print(email_service.resumo_configuracao())
    print()

    if not email_service.email_configurado():
        print(
            "Envio desativado. Defina EMAIL_ENABLED=true, SMTP_HOST e SMTP_FROM "
            "em app/.env antes de testar."
        )
        return 1

    if email_service.enviar_email_teste(args.para, args.nome):
        print("OK: e-mail enviado. Confira a caixa do destinatário (ou o Mailtrap/MailHog).")
        return 0

    print("FALHA: não foi possível enviar. Veja a mensagem de erro acima.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
