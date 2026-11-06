"""Cliente dos webservices REST do Moodle (comunicação síncrona).

Usa as três funções indicadas no enunciado:
  * mod_assign_get_assignments   -> tarefas e prazos
  * core_enrol_get_enrolled_users -> alunos matriculados
  * mod_assign_get_submissions   -> quem já entregou

Documentação: https://docs.moodle.org/dev/Web_service_API_functions
"""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)


class MoodleErro(RuntimeError):
    pass


class MoodleClient:
    def __init__(self, url_base: str, token: str, timeout: float = 15.0, session: requests.Session | None = None):
        self.endpoint = url_base.rstrip("/") + "/webservice/rest/server.php"
        self.token = token
        self.timeout = timeout
        self.session = session or requests.Session()

    def _chamar(self, funcao: str, params: dict) -> object:
        dados = {"wstoken": self.token, "wsfunction": funcao, "moodlewsrestformat": "json", **params}
        resp = self.session.post(self.endpoint, data=dados, timeout=self.timeout)
        resp.raise_for_status()
        corpo = resp.json()
        # O Moodle responde HTTP 200 mesmo em erro, com um objeto "exception".
        if isinstance(corpo, dict) and "exception" in corpo:
            raise MoodleErro(f"{funcao}: {corpo.get('errorcode')} - {corpo.get('message')}")
        return corpo

    def tarefas_do_curso(self, curso_id: int) -> tuple[dict, list[dict]]:
        corpo = self._chamar("mod_assign_get_assignments", {"courseids[0]": curso_id})
        cursos = corpo.get("courses") or []
        if not cursos:
            raise MoodleErro(f"Curso {curso_id} não encontrado ou sem permissão")
        curso = cursos[0]
        return {"id": curso["id"], "fullname": curso.get("fullname", "")}, curso.get("assignments") or []

    def usuarios_matriculados(self, curso_id: int) -> list[dict]:
        return list(self._chamar("core_enrol_get_enrolled_users", {"courseid": curso_id}))

    def envios(self, tarefa_ids: list[int]) -> dict[int, list[dict]]:
        if not tarefa_ids:
            return {}
        params = {f"assignmentids[{i}]": tid for i, tid in enumerate(tarefa_ids)}
        corpo = self._chamar("mod_assign_get_submissions", params)
        return {int(a["assignmentid"]): a.get("submissions") or [] for a in corpo.get("assignments") or []}
