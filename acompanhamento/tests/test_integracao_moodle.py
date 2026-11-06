"""Integração com o Moodle simulado via HTTP real (mesmo formato do Moodle)."""
import importlib.util
import pathlib
import threading

import pytest
from werkzeug.serving import make_server

from app.config import Config
from app.main import Acompanhamento
from app.moodle_client import MoodleClient, MoodleErro

RAIZ = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def moodle():
    spec = importlib.util.spec_from_file_location("moodle_mock", RAIZ / "moodle-mock" / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    srv = make_server("127.0.0.1", 0, mod.app)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield mod, f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


class PublicadorFalso:
    def __init__(self):
        self.mensagens = []

    def publicar(self, m):
        self.mensagens.append(m)

    def fechar(self):
        pass


def test_cliente_le_as_tres_funcoes(moodle):
    mod, url = moodle
    mod.semear()
    cli = MoodleClient(url, "token-demo")
    curso, tarefas = cli.tarefas_do_curso(101)
    assert curso["fullname"] == "Engenharia de Software II"
    assert len(tarefas) == 6
    assert len(cli.usuarios_matriculados(101)) == 5
    envios = cli.envios([1, 2])
    assert {e["userid"] for e in envios[1]} == {12, 13}


def test_token_invalido_vira_erro(moodle):
    _, url = moodle
    with pytest.raises(MoodleErro, match="invalidtoken"):
        MoodleClient(url, "errado").usuarios_matriculados(101)


def test_ciclo_completo_publica_somente_os_pendentes(moodle):
    mod, url = moodle
    mod.semear()
    pub = PublicadorFalso()
    svc = Acompanhamento(Config(moodle_url=url, moodle_url_publica="http://localhost:8000"), MoodleClient(url, "token-demo"), pub)
    r = svc.executar_ciclo()
    assert r["status"] == "ok"
    # T1: Ana, Carla (rascunho), Diego | T2: Bruno. Ignoradas: T3 (72h), T4 (vencida), T5 (grupo), T6 (sem prazo)
    assert sorted(m["id"] for m in pub.mensagens) == ["101:1:11", "101:1:13", "101:1:14", "101:2:12"]

    # Ana entrega a T1 -> no próximo ciclo ela não aparece mais
    mod.app.test_client().post("/admin/entregar", json={"tarefa_id": 1, "aluno_id": 11})
    pub.mensagens.clear()
    svc.executar_ciclo()
    assert sorted(m["id"] for m in pub.mensagens) == ["101:1:13", "101:1:14", "101:2:12"]


def test_falha_no_moodle_nao_derruba_o_servico():
    pub = PublicadorFalso()
    svc = Acompanhamento(Config(), MoodleClient("http://127.0.0.1:1", "x", timeout=1), pub)
    r = svc.executar_ciclo()
    assert r["status"] == "erro" and pub.mensagens == []
