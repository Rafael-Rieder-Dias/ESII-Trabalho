"""Moodle simulado para desenvolvimento e demonstração.

Implementa as mesmas três funções REST usadas pelo Acompanhamento, com o
mesmo formato de resposta do Moodle real (endpoint
/webservice/rest/server.php, parâmetros wstoken / wsfunction /
moodlewsrestformat=json). Para usar um Moodle de verdade, basta trocar
MOODLE_URL e MOODLE_TOKEN no .env: o código do Acompanhamento não muda.

Os prazos são gerados relativos ao momento em que o serviço sobe (ou ao
último POST /admin/reset), para que a demonstração funcione a qualquer hora.

Rotas de apoio à demo (não existem no Moodle real):
  GET  /admin/estado   -> tarefas, alunos e envios atuais + o que é esperado
  POST /admin/entregar -> {"tarefa_id": 1, "aluno_id": 11} marca como enviado
  POST /admin/tarefas  -> {"nome": "...", "horas": 2} cria tarefa nova sem envios
  POST /admin/reset    -> recria os dados com prazos relativos a agora
"""
from __future__ import annotations

import os
import threading
import time

from flask import Flask, jsonify, request

app = Flask(__name__)
TOKEN = os.getenv("MOODLE_TOKEN", "token-demo")
CURSO = {"id": 101, "fullname": "Engenharia de Software II", "shortname": "ES2-2026-2"}
HORA = 3600
_trava = threading.Lock()
_estado: dict = {}


def semear() -> None:
    agora = int(time.time())
    usuarios = [
        {"id": 11, "username": "ana", "firstname": "Ana", "lastname": "Souza", "email": "ana.souza@exemplo.edu.br", "papel": "student"},
        {"id": 12, "username": "bruno", "firstname": "Bruno", "lastname": "Lima", "email": "bruno.lima@exemplo.edu.br", "papel": "student"},
        {"id": 13, "username": "carla", "firstname": "Carla", "lastname": "Mendes", "email": "carla.mendes@exemplo.edu.br", "papel": "student"},
        {"id": 14, "username": "diego", "firstname": "Diego", "lastname": "Rocha", "email": "diego.rocha@exemplo.edu.br", "papel": "student"},
        {"id": 90, "username": "prof", "firstname": "Professora", "lastname": "Responsável", "email": "prof@exemplo.edu.br", "papel": "editingteacher"},
    ]
    tarefas = [
        # dentro da janela de 24h, individual -> gera lembretes
        {"id": 1, "cmid": 501, "name": "Relatório da Sprint 3", "duedate": agora + 6 * HORA, "teamsubmission": 0},
        {"id": 2, "cmid": 502, "name": "Checklist de validação", "duedate": agora + 20 * HORA, "teamsubmission": 0},
        # casos que devem ser ignorados
        {"id": 3, "cmid": 503, "name": "Diagrama de arquitetura", "duedate": agora + 72 * HORA, "teamsubmission": 0},
        {"id": 4, "cmid": 504, "name": "Questionário 1", "duedate": agora - 24 * HORA, "teamsubmission": 0},
        {"id": 5, "cmid": 505, "name": "Trabalho em grupo", "duedate": agora + 10 * HORA, "teamsubmission": 1},
        {"id": 6, "cmid": 506, "name": "Leitura complementar", "duedate": 0, "teamsubmission": 0},
    ]
    envios = {
        1: {12: "submitted", 13: "draft"},          # Bruno entregou; Carla só rascunho
        2: {11: "submitted", 13: "submitted", 14: "submitted"},  # só Bruno pendente
        3: {}, 4: {}, 5: {}, 6: {},
    }
    with _trava:
        _estado.clear()
        _estado.update({"usuarios": usuarios, "tarefas": tarefas, "envios": envios, "semeado_em": agora})


def erro(codigo: str, mensagem: str):
    # Mesmo formato do Moodle real: HTTP 200 com objeto de exceção.
    return jsonify({"exception": "moodle_exception", "errorcode": codigo, "message": mensagem})


def lista_indexada(form, nome: str) -> list[int]:
    valores = [v for k, v in form.items() if k.startswith(f"{nome}[")]
    return [int(v) for v in valores]


def ws_get_assignments(form):
    ids = lista_indexada(form, "courseids") or [CURSO["id"]]
    if CURSO["id"] not in ids:
        return jsonify({"courses": [], "warnings": []})
    tarefas = [
        {**t, "course": CURSO["id"], "nosubmissions": 0, "allowsubmissionsfromdate": 0, "cutoffdate": 0, "intro": ""}
        for t in _estado["tarefas"]
    ]
    return jsonify({"courses": [{**CURSO, "assignments": tarefas}], "warnings": []})


def ws_enrolled_users(form):
    if int(form.get("courseid", 0)) != CURSO["id"]:
        return erro("invalidrecord", "Curso não encontrado")
    saida = []
    for u in _estado["usuarios"]:
        saida.append({
            "id": u["id"], "username": u["username"], "firstname": u["firstname"], "lastname": u["lastname"],
            "fullname": f"{u['firstname']} {u['lastname']}", "email": u["email"],
            "roles": [{"roleid": 5 if u["papel"] == "student" else 3, "name": "", "shortname": u["papel"], "sortorder": 0}],
        })
    return jsonify(saida)


def ws_get_submissions(form):
    ids = lista_indexada(form, "assignmentids")
    assignments = []
    for tid in ids:
        envios = _estado["envios"].get(tid, {})
        subs = [
            {"id": tid * 1000 + uid, "userid": uid, "status": st, "timemodified": _estado["semeado_em"], "attemptnumber": 0}
            for uid, st in envios.items()
        ]
        assignments.append({"assignmentid": tid, "submissions": subs})
    return jsonify({"assignments": assignments, "warnings": []})


FUNCOES = {
    "mod_assign_get_assignments": ws_get_assignments,
    "core_enrol_get_enrolled_users": ws_enrolled_users,
    "mod_assign_get_submissions": ws_get_submissions,
}


@app.route("/webservice/rest/server.php", methods=["GET", "POST"])
def rest():
    form = request.values
    if form.get("wstoken") != TOKEN:
        return erro("invalidtoken", "Token inválido")
    funcao = FUNCOES.get(form.get("wsfunction", ""))
    if not funcao:
        return erro("accessexception", "Função não habilitada para este token")
    with _trava:
        return funcao(form)


@app.get("/mod/assign/view.php")
def ver_tarefa():
    tid = request.args.get("id", type=int)
    tarefa = next((t for t in _estado["tarefas"] if t["cmid"] == tid), None)
    nome = tarefa["name"] if tarefa else "Tarefa não encontrada"
    return f"<h1>{nome}</h1><p>Página simulada da tarefa no Moodle (cmid={tid}).</p>"


@app.get("/admin/estado")
def estado():
    with _trava:
        return jsonify(_estado)


@app.post("/admin/entregar")
def entregar():
    dados = request.get_json(force=True)
    tid, uid = int(dados["tarefa_id"]), int(dados["aluno_id"])
    with _trava:
        _estado["envios"].setdefault(tid, {})[uid] = dados.get("status", "submitted")
    return jsonify({"ok": True, "tarefa_id": tid, "aluno_id": uid})


@app.post("/admin/tarefas")
def nova_tarefa():
    """Cria uma tarefa individual que vence em `horas` (padrão 2h), sem envios."""
    dados = request.get_json(silent=True) or {}
    with _trava:
        tid = max(t["id"] for t in _estado["tarefas"]) + 1
        tarefa = {"id": tid, "cmid": 500 + tid, "name": dados.get("nome", f"Tarefa extra {tid}"),
                  "duedate": int(time.time() + float(dados.get("horas", 2)) * HORA), "teamsubmission": 0}
        _estado["tarefas"].append(tarefa)
        _estado["envios"][tid] = {}
    return jsonify(tarefa)


@app.post("/admin/reset")
def reset():
    semear()
    return jsonify({"ok": True, "semeado_em": _estado["semeado_em"]})


@app.get("/saude")
def saude():
    return jsonify({"servico": "moodle-mock", "status": "ok"})


semear()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORTA", "8000")))
