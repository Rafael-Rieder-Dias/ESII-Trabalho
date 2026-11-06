"""Regras de negócio do Acompanhamento: quem deve receber lembrete.

Funções puras (sem rede, sem relógio implícito) para serem fáceis de testar.

Regras (slides "O que entra e o que fica de fora" e "Critérios de aceite"):
  * só tarefas individuais (teamsubmission == 0);
  * tarefas sem prazo (duedate == 0) são ignoradas;
  * tarefas já vencidas (duedate <= agora) são ignoradas;
  * tarefas que vencem depois de agora + janela são ignoradas;
  * só usuários com papel de estudante e com e-mail;
  * aluno com envio no status "submitted" não recebe lembrete;
  * envio em rascunho ("draft") ou sem envio algum conta como pendente.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable

STATUS_ENVIADO = "submitted"
PAPEL_ESTUDANTE = "student"


@dataclass(frozen=True)
class Solicitacao:
    """Mensagem publicada na fila para o microsserviço de Notificações."""

    id: str  # chave de idempotência: curso:tarefa:aluno
    curso_id: int
    curso_nome: str
    tarefa_id: int
    tarefa_cmid: int
    tarefa_nome: str
    prazo: int  # timestamp Unix (UTC)
    link: str
    aluno_id: int
    aluno_nome: str
    aluno_email: str

    def to_dict(self) -> dict:
        return asdict(self)


def chave_idempotencia(curso_id: int, tarefa_id: int, aluno_id: int) -> str:
    return f"{curso_id}:{tarefa_id}:{aluno_id}"


def tarefa_na_janela(tarefa: dict, agora: int, janela_segundos: int) -> bool:
    prazo = int(tarefa.get("duedate") or 0)
    if prazo == 0:
        return False
    if int(tarefa.get("teamsubmission") or 0) != 0:
        return False
    if int(tarefa.get("nosubmissions") or 0) != 0:
        return False
    return agora < prazo <= agora + janela_segundos


def estudantes(usuarios: Iterable[dict]) -> list[dict]:
    resultado = []
    for u in usuarios:
        papeis = {p.get("shortname") for p in u.get("roles") or []}
        if PAPEL_ESTUDANTE in papeis and u.get("email"):
            resultado.append(u)
    return resultado


def quem_enviou(envios: Iterable[dict]) -> set[int]:
    return {int(e["userid"]) for e in envios if e.get("status") == STATUS_ENVIADO}


def selecionar_pendentes(
    *,
    curso: dict,
    tarefas: Iterable[dict],
    usuarios: Iterable[dict],
    envios_por_tarefa: dict[int, list[dict]],
    agora: int,
    janela_segundos: int,
    url_publica_moodle: str,
) -> list[Solicitacao]:
    alunos = estudantes(usuarios)
    base = url_publica_moodle.rstrip("/")
    solicitacoes: list[Solicitacao] = []
    for tarefa in tarefas:
        if not tarefa_na_janela(tarefa, agora, janela_segundos):
            continue
        tid = int(tarefa["id"])
        enviaram = quem_enviou(envios_por_tarefa.get(tid, []))
        for aluno in alunos:
            aid = int(aluno["id"])
            if aid in enviaram:
                continue
            nome = aluno.get("fullname") or f"{aluno.get('firstname', '')} {aluno.get('lastname', '')}".strip()
            solicitacoes.append(
                Solicitacao(
                    id=chave_idempotencia(int(curso["id"]), tid, aid),
                    curso_id=int(curso["id"]),
                    curso_nome=curso.get("fullname", ""),
                    tarefa_id=tid,
                    tarefa_cmid=int(tarefa.get("cmid") or 0),
                    tarefa_nome=tarefa.get("name", ""),
                    prazo=int(tarefa["duedate"]),
                    link=f"{base}/mod/assign/view.php?id={tarefa.get('cmid')}",
                    aluno_id=aid,
                    aluno_nome=nome,
                    aluno_email=aluno["email"],
                )
            )
    return solicitacoes
