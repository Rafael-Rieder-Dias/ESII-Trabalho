"""Regra de processamento de uma solicitação, independente do RabbitMQ.

Decide o que fazer com cada mensagem e devolve um resultado; quem fala com a
fila (main.py) apenas executa a decisão. Isso permite testar os critérios de
aceite 3 (sem reenvio) e 4 (falha + nova tentativa) sem infraestrutura.
"""
from __future__ import annotations

import logging
from enum import Enum

from .repositorio import ENVIADO, Repositorio

log = logging.getLogger("notificacoes")

CAMPOS_OBRIGATORIOS = ("id", "aluno_email", "tarefa_nome", "prazo", "link")


class Resultado(str, Enum):
    ENVIADO = "enviado"
    DUPLICADO = "duplicado"        # já enviado antes: não reenviar
    RETENTAR = "retentar"          # falhou, vai para a fila de retentativas
    ESGOTADO = "esgotado"          # falhou MAX vezes, vai para a fila de falhas
    INVALIDA = "invalida"          # mensagem malformada, vai para a fila de falhas


class Processador:
    def __init__(self, repo: Repositorio, enviador, max_tentativas: int = 5):
        self.repo = repo
        self.enviador = enviador
        self.max_tentativas = max_tentativas

    def processar(self, sol: dict, tentativa: int = 1) -> Resultado:
        faltando = [c for c in CAMPOS_OBRIGATORIOS if not sol.get(c)]
        if faltando:
            sid = str(sol.get("id") or "sem-id")
            self.repo.registrar_evento(sid, "mensagem_invalida", tentativa, f"campos ausentes: {faltando}")
            log.error("Mensagem inválida %s: faltam %s", sid, faltando)
            return Resultado.INVALIDA

        sid = sol["id"]
        if self.repo.status(sid) == ENVIADO:
            self.repo.registrar_evento(sid, "ignorado_ja_enviado", tentativa)
            log.info("Solicitação %s já processada: lembrete NÃO reenviado", sid)
            return Resultado.DUPLICADO

        self.repo.iniciar(sid, sol["aluno_email"], sol["tarefa_nome"])
        try:
            self.enviador.enviar(sol)
        except Exception as exc:
            definitiva = tentativa >= self.max_tentativas
            self.repo.marcar_falha(sid, tentativa, f"{type(exc).__name__}: {exc}", definitiva)
            if definitiva:
                log.error("Solicitação %s falhou %s vezes; movida para a fila de falhas", sid, tentativa)
                return Resultado.ESGOTADO
            log.warning("Falha ao enviar %s (tentativa %s/%s): %s", sid, tentativa, self.max_tentativas, exc)
            return Resultado.RETENTAR

        self.repo.marcar_enviado(sid, tentativa)
        log.info("Lembrete enviado: %s -> %s (tentativa %s)", sid, sol["aluno_email"], tentativa)
        return Resultado.ENVIADO
