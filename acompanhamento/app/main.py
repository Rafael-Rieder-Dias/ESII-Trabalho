"""Microsserviço de Acompanhamento.

A cada INTERVALO_SEGUNDOS consulta o Moodle, identifica alunos com tarefas
pendentes que vencem dentro de JANELA_HORAS e publica uma solicitação de
reengajamento por aluno e tarefa na fila.

Endpoints HTTP (para operação e demonstração):
  GET  /saude     -> status do serviço
  GET  /ultimo    -> resultado do último ciclo
  POST /executar  -> executa um ciclo imediatamente
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import Config
from .moodle_client import MoodleClient
from .publicador import Publicador
from .selecao import selecionar_pendentes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [acompanhamento] %(levelname)s %(message)s")
logging.getLogger("pika").setLevel(logging.WARNING)
log = logging.getLogger("acompanhamento")


class Acompanhamento:
    def __init__(self, cfg: Config, moodle: MoodleClient, publicador: Publicador, relogio=time.time):
        self.cfg = cfg
        self.moodle = moodle
        self.publicador = publicador
        self.relogio = relogio
        self._trava = threading.Lock()
        self.ultimo: dict = {"status": "nunca executado"}

    def executar_ciclo(self) -> dict:
        with self._trava:
            inicio = datetime.now(timezone.utc).isoformat()
            agora = int(self.relogio())
            try:
                curso, tarefas = self.moodle.tarefas_do_curso(self.cfg.curso_id)
                usuarios = self.moodle.usuarios_matriculados(self.cfg.curso_id)
                envios = self.moodle.envios([int(t["id"]) for t in tarefas])
                solicitacoes = selecionar_pendentes(
                    curso=curso,
                    tarefas=tarefas,
                    usuarios=usuarios,
                    envios_por_tarefa=envios,
                    agora=agora,
                    janela_segundos=int(self.cfg.janela_horas * 3600),
                    url_publica_moodle=self.cfg.moodle_url_publica,
                )
                for s in solicitacoes:
                    self.publicador.publicar(s.to_dict())
                    log.info("Publicada solicitação %s (%s -> %s)", s.id, s.tarefa_nome, s.aluno_email)
                self.ultimo = {
                    "status": "ok",
                    "executado_em": inicio,
                    "tarefas_no_curso": len(tarefas),
                    "solicitacoes_publicadas": len(solicitacoes),
                    "ids": [s.id for s in solicitacoes],
                }
                log.info("Ciclo concluído: %s solicitações publicadas", len(solicitacoes))
            except Exception as exc:  # o ciclo nunca derruba o serviço
                log.exception("Falha no ciclo de acompanhamento")
                self.ultimo = {"status": "erro", "executado_em": inicio, "erro": str(exc)}
            finally:
                self.publicador.fechar()
            return self.ultimo

    def laco(self, parar: threading.Event) -> None:
        while not parar.is_set():
            self.executar_ciclo()
            parar.wait(self.cfg.intervalo_segundos)


def criar_handler(servico: Acompanhamento):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, codigo: int, dados: dict) -> None:
            corpo = json.dumps(dados, ensure_ascii=False, indent=2).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):
            if self.path == "/saude":
                self._json(200, {"servico": "acompanhamento", "status": "ok"})
            elif self.path == "/ultimo":
                self._json(200, servico.ultimo)
            else:
                self._json(404, {"erro": "não encontrado"})

        def do_POST(self):
            if self.path == "/executar":
                self._json(200, servico.executar_ciclo())
            else:
                self._json(404, {"erro": "não encontrado"})

        def log_message(self, *args):
            pass

    return Handler


def main() -> None:
    cfg = Config()
    log.info("Iniciando: curso=%s intervalo=%ss janela=%sh", cfg.curso_id, cfg.intervalo_segundos, cfg.janela_horas)
    servico = Acompanhamento(cfg, MoodleClient(cfg.moodle_url, cfg.moodle_token), Publicador(cfg.rabbitmq_url, cfg.fila))
    parar = threading.Event()
    threading.Thread(target=servico.laco, args=(parar,), daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", cfg.porta_http), criar_handler(servico)).serve_forever()


if __name__ == "__main__":
    main()
