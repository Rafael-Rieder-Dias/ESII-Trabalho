"""Publica solicitações de reengajamento na fila do RabbitMQ (comunicação assíncrona)."""
from __future__ import annotations

import json
import logging
import time

import pika

log = logging.getLogger(__name__)


class Publicador:
    def __init__(self, url: str, fila: str):
        self.url = url
        self.fila = fila
        self._conexao: pika.BlockingConnection | None = None
        self._canal = None

    def _conectar(self, tentativas: int = 30) -> None:
        for n in range(1, tentativas + 1):
            try:
                self._conexao = pika.BlockingConnection(pika.URLParameters(self.url))
                self._canal = self._conexao.channel()
                self._canal.queue_declare(queue=self.fila, durable=True)
                self._canal.confirm_delivery()  # garante que o broker recebeu
                log.info("Conectado ao RabbitMQ, fila '%s'", self.fila)
                return
            except pika.exceptions.AMQPConnectionError:
                log.warning("RabbitMQ indisponível (tentativa %s/%s), aguardando...", n, tentativas)
                time.sleep(2)
        raise RuntimeError("Não foi possível conectar ao RabbitMQ")

    def publicar(self, mensagem: dict) -> None:
        corpo = json.dumps(mensagem, ensure_ascii=False).encode()
        props = pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,  # persistente
            message_id=mensagem["id"],
        )
        for tentativa in (1, 2):
            try:
                if self._canal is None or self._canal.is_closed:
                    self._conectar()
                self._canal.basic_publish(exchange="", routing_key=self.fila, body=corpo, properties=props)
                return
            except (pika.exceptions.AMQPError, ConnectionError):
                log.warning("Falha ao publicar, reconectando (tentativa %s)", tentativa)
                self._canal = None
                if tentativa == 2:
                    raise

    def fechar(self) -> None:
        """Fecha a conexão ao fim de cada ciclo (evita conexão ociosa por 1h sem heartbeat)."""
        try:
            if self._conexao and self._conexao.is_open:
                self._conexao.close()
        except pika.exceptions.AMQPError:
            pass
        finally:
            self._conexao = None
            self._canal = None
