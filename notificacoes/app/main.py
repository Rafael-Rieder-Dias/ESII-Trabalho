"""Microsserviço de Notificações.

Consome as solicitações da fila, envia o lembrete por SMTP e registra o
resultado. Topologia de filas no RabbitMQ:

  reengajamento.solicitacoes  <- publicada pelo Acompanhamento
  reengajamento.retentativas  <- mensagens que falharam esperam aqui (TTL por
                                 mensagem) e voltam sozinhas para
                                 'solicitacoes' via dead-letter
  reengajamento.falhas        <- mensagens que esgotaram as tentativas ou são
                                 inválidas (para análise manual)

Endpoints HTTP:
  GET /saude    -> status do serviço
  GET /envios   -> registro por solicitação (status, tentativas, último erro)
  GET /eventos  -> histórico de envios, duplicados ignorados e falhas
  POST /admin/limpar -> apaga o registro (só com PERMITIR_LIMPEZA=true, para a demo)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pika

from .email_sender import EnviadorSMTP
from .processador import Processador, Resultado
from .repositorio import Repositorio

logging.basicConfig(level=logging.INFO, format="%(asctime)s [notificacoes] %(levelname)s %(message)s")
logging.getLogger("pika").setLevel(logging.WARNING)
log = logging.getLogger("notificacoes")

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/%2F")
FILA = os.getenv("FILA_SOLICITACOES", "reengajamento.solicitacoes")
FILA_RETENTATIVAS = os.getenv("FILA_RETENTATIVAS", "reengajamento.retentativas")
FILA_FALHAS = os.getenv("FILA_FALHAS", "reengajamento.falhas")
ATRASO_RETENTATIVA_MS = int(os.getenv("ATRASO_RETENTATIVA_SEGUNDOS", "15")) * 1000
MAX_TENTATIVAS = int(os.getenv("MAX_TENTATIVAS", "5"))
BANCO = os.getenv("BANCO_PATH", "/dados/notificacoes.db")
PORTA_HTTP = int(os.getenv("PORTA_HTTP", "8082"))
PERMITIR_LIMPEZA = os.getenv("PERMITIR_LIMPEZA", "false").lower() == "true"


def declarar_topologia(canal) -> None:
    canal.queue_declare(queue=FILA, durable=True)
    canal.queue_declare(
        queue=FILA_RETENTATIVAS,
        durable=True,
        arguments={"x-dead-letter-exchange": "", "x-dead-letter-routing-key": FILA},
    )
    canal.queue_declare(queue=FILA_FALHAS, durable=True)


def publicar(canal, fila: str, corpo: bytes, tentativa: int, expiracao_ms: int | None = None, motivo: str | None = None):
    headers = {"x-tentativa": tentativa}
    if motivo:
        headers["x-motivo"] = motivo
    canal.basic_publish(
        exchange="",
        routing_key=fila,
        body=corpo,
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,
            headers=headers,
            expiration=str(expiracao_ms) if expiracao_ms else None,
        ),
    )


def criar_callback(processador: Processador):
    def callback(canal, metodo, props, corpo: bytes):
        tentativa = int(((props.headers or {}).get("x-tentativa")) or 1)
        try:
            sol = json.loads(corpo)
        except json.JSONDecodeError:
            log.error("Mensagem não é JSON válido; movida para a fila de falhas")
            publicar(canal, FILA_FALHAS, corpo, tentativa, motivo="json_invalido")
            canal.basic_ack(metodo.delivery_tag)
            return

        resultado = processador.processar(sol, tentativa)
        if resultado == Resultado.RETENTAR:
            publicar(canal, FILA_RETENTATIVAS, corpo, tentativa + 1, expiracao_ms=ATRASO_RETENTATIVA_MS)
            log.info("Nova tentativa de %s agendada em %ss", sol.get("id"), ATRASO_RETENTATIVA_MS // 1000)
        elif resultado in (Resultado.ESGOTADO, Resultado.INVALIDA):
            publicar(canal, FILA_FALHAS, corpo, tentativa, motivo=resultado.value)
        # Só confirma (ack) depois de decidir o destino: se o serviço cair no
        # meio, o RabbitMQ reentrega a mensagem.
        canal.basic_ack(metodo.delivery_tag)

    return callback


def consumir(processador: Processador) -> None:
    while True:
        try:
            conexao = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
            canal = conexao.channel()
            declarar_topologia(canal)
            canal.basic_qos(prefetch_count=1)  # uma mensagem por vez
            canal.basic_consume(queue=FILA, on_message_callback=criar_callback(processador))
            log.info("Consumindo a fila '%s' (máx. %s tentativas, %ss entre elas)",
                     FILA, MAX_TENTATIVAS, ATRASO_RETENTATIVA_MS // 1000)
            canal.start_consuming()
        except pika.exceptions.AMQPConnectionError:
            log.warning("RabbitMQ indisponível, reconectando em 3s...")
            time.sleep(3)
        except Exception:
            log.exception("Erro no consumidor, reconectando em 3s...")
            time.sleep(3)


def criar_handler(repo: Repositorio):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, codigo: int, dados) -> None:
            corpo = json.dumps(dados, ensure_ascii=False, indent=2).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):
            if self.path == "/saude":
                self._json(200, {"servico": "notificacoes", "status": "ok"})
            elif self.path == "/envios":
                self._json(200, repo.listar_envios())
            elif self.path == "/eventos":
                self._json(200, repo.listar_eventos())
            else:
                self._json(404, {"erro": "não encontrado"})

        def do_POST(self):
            if self.path == "/admin/limpar" and PERMITIR_LIMPEZA:
                repo.limpar()
                log.warning("Registro de envios apagado via /admin/limpar (modo demonstração)")
                self._json(200, {"ok": True})
            else:
                self._json(404, {"erro": "não encontrado"})

        def log_message(self, *args):
            pass

    return Handler


def main() -> None:
    os.makedirs(os.path.dirname(BANCO) or ".", exist_ok=True)
    repo = Repositorio(BANCO)
    enviador = EnviadorSMTP(
        host=os.getenv("SMTP_HOST", "mailpit"),
        porta=int(os.getenv("SMTP_PORTA", "1025")),
        remetente=os.getenv("SMTP_REMETENTE", "Reengajamento Moodle <nao-responda@reengajamento.local>"),
        fuso=os.getenv("FUSO_HORARIO", "America/Sao_Paulo"),
        usuario=os.getenv("SMTP_USUARIO") or None,
        senha=os.getenv("SMTP_SENHA") or None,
        starttls=os.getenv("SMTP_STARTTLS", "false").lower() == "true",
    )
    processador = Processador(repo, enviador, MAX_TENTATIVAS)
    servidor = ThreadingHTTPServer(("0.0.0.0", PORTA_HTTP), criar_handler(repo))
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    consumir(processador)


if __name__ == "__main__":
    main()
