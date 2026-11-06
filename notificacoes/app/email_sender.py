"""Montagem e envio do e-mail de lembrete por SMTP (Mailpit nos testes)."""
from __future__ import annotations

import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo


def formatar_prazo(ts: int, fuso: str) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ZoneInfo(fuso)).strftime("%d/%m/%Y às %H:%M")


def montar_email(sol: dict, remetente: str, fuso: str) -> EmailMessage:
    prazo = formatar_prazo(int(sol["prazo"]), fuso)
    msg = EmailMessage()
    msg["From"] = remetente
    msg["To"] = sol["aluno_email"]
    msg["Subject"] = f"Lembrete: \"{sol['tarefa_nome']}\" vence em {prazo}"
    msg["X-Reengajamento-Id"] = sol["id"]
    primeiro_nome = (sol.get("aluno_nome") or "").split(" ")[0] or "estudante"
    msg.set_content(
        f"Olá, {primeiro_nome}!\n\n"
        f"A tarefa \"{sol['tarefa_nome']}\" da disciplina {sol.get('curso_nome', '')} "
        f"ainda não tem um envio seu e o prazo termina em {prazo}.\n\n"
        f"Acesse a tarefa: {sol['link']}\n\n"
        "Se você já está finalizando, ótimo! Este é só um lembrete para não perder o prazo.\n\n"
        "— Serviço de reengajamento da disciplina\n"
    )
    return msg


class EnviadorSMTP:
    def __init__(self, host: str, porta: int, remetente: str, fuso: str, timeout: float = 10.0,
                 usuario: str | None = None, senha: str | None = None, starttls: bool = False):
        self.host, self.porta, self.remetente, self.fuso = host, porta, remetente, fuso
        self.timeout, self.usuario, self.senha, self.starttls = timeout, usuario, senha, starttls

    def enviar(self, sol: dict) -> None:
        msg = montar_email(sol, self.remetente, self.fuso)
        with smtplib.SMTP(self.host, self.porta, timeout=self.timeout) as smtp:
            if self.starttls:
                smtp.starttls()
            if self.usuario:
                smtp.login(self.usuario, self.senha or "")
            smtp.send_message(msg)
