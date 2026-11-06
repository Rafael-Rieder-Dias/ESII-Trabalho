"""Registro persistente das solicitações processadas (SQLite).

Tabela `envios`: um registro por chave curso:tarefa:aluno. Garante que um
lembrete já enviado não seja reenviado (idempotência).
Tabela `eventos`: histórico de tudo o que aconteceu (envios, duplicados
ignorados, falhas e tentativas). É o "registro do resultado" do enunciado.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone

ENVIADO = "enviado"
FALHOU = "falhou"
PROCESSANDO = "processando"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS envios (
    id            TEXT PRIMARY KEY,
    status        TEXT NOT NULL,
    tentativas    INTEGER NOT NULL DEFAULT 0,
    aluno_email   TEXT,
    tarefa_nome   TEXT,
    ultimo_erro   TEXT,
    criado_em     TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eventos (
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,
    solicitacao_id TEXT NOT NULL,
    evento         TEXT NOT NULL,
    tentativa      INTEGER,
    detalhe        TEXT,
    em             TEXT NOT NULL
);
"""


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Repositorio:
    def __init__(self, caminho: str = ":memory:"):
        self._con = sqlite3.connect(caminho, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._trava = threading.Lock()
        with self._trava, self._con:
            self._con.executescript(ESQUEMA)

    def status(self, sid: str) -> str | None:
        with self._trava:
            linha = self._con.execute("SELECT status FROM envios WHERE id = ?", (sid,)).fetchone()
        return linha["status"] if linha else None

    def iniciar(self, sid: str, email: str, tarefa: str) -> None:
        agora = _agora()
        with self._trava, self._con:
            self._con.execute(
                """INSERT INTO envios (id, status, aluno_email, tarefa_nome, criado_em, atualizado_em)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET status = excluded.status, atualizado_em = excluded.atualizado_em""",
                (sid, PROCESSANDO, email, tarefa, agora, agora),
            )

    def marcar_enviado(self, sid: str, tentativa: int) -> None:
        with self._trava, self._con:
            self._con.execute(
                "UPDATE envios SET status = ?, tentativas = tentativas + 1, ultimo_erro = NULL, atualizado_em = ? WHERE id = ?",
                (ENVIADO, _agora(), sid),
            )
            self._evento(sid, "enviado", tentativa, None)

    def marcar_falha(self, sid: str, tentativa: int, erro: str, definitiva: bool) -> None:
        with self._trava, self._con:
            self._con.execute(
                "UPDATE envios SET status = ?, tentativas = tentativas + 1, ultimo_erro = ?, atualizado_em = ? WHERE id = ?",
                (FALHOU, erro, _agora(), sid),
            )
            self._evento(sid, "falha_definitiva" if definitiva else "falha_vai_tentar_novamente", tentativa, erro)

    def registrar_evento(self, sid: str, evento: str, tentativa: int | None = None, detalhe: str | None = None) -> None:
        with self._trava, self._con:
            self._evento(sid, evento, tentativa, detalhe)

    def _evento(self, sid, evento, tentativa, detalhe) -> None:
        self._con.execute(
            "INSERT INTO eventos (solicitacao_id, evento, tentativa, detalhe, em) VALUES (?, ?, ?, ?, ?)",
            (sid, evento, tentativa, detalhe, _agora()),
        )

    def limpar(self) -> None:
        """Apaga todo o registro. Só exposto via HTTP quando PERMITIR_LIMPEZA=true (demo)."""
        with self._trava, self._con:
            self._con.execute("DELETE FROM envios")
            self._con.execute("DELETE FROM eventos")

    def listar_envios(self) -> list[dict]:
        with self._trava:
            return [dict(l) for l in self._con.execute("SELECT * FROM envios ORDER BY atualizado_em DESC")]

    def listar_eventos(self, limite: int = 200) -> list[dict]:
        with self._trava:
            return [dict(l) for l in self._con.execute("SELECT * FROM eventos ORDER BY seq DESC LIMIT ?", (limite,))]
