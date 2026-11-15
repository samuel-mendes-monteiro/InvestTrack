"""The emails the app sends, in Portuguese like the web app."""

from html import escape

from investtrack.auth import RESET_MINUTES
from investtrack.sources.email import Email


def password_reset_email(to: str, link: str) -> Email:
    text = (
        "Olá,\n\n"
        "Recebemos um pedido para redefinir a senha da sua conta no InvestTrack.\n"
        f"Para criar uma senha nova, abra o link abaixo (vale por {RESET_MINUTES} minutos "
        "e funciona uma vez só):\n\n"
        f"{link}\n\n"
        "Se não foi você, ignore este e-mail: sua senha continua a mesma.\n"
    )
    html = (
        "<p>Olá,</p>"
        "<p>Recebemos um pedido para redefinir a senha da sua conta no InvestTrack.</p>"
        f'<p><a href="{escape(link)}">Criar uma senha nova</a></p>'
        f"<p>O link vale por {RESET_MINUTES} minutos e funciona uma vez só.</p>"
        "<p>Se não foi você, ignore este e-mail: sua senha continua a mesma.</p>"
    )
    return Email(to=to, subject="Redefinir sua senha do InvestTrack", text=text, html=html)
