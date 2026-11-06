import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    moodle_url: str = os.getenv("MOODLE_URL", "http://moodle-mock:8000")
    moodle_url_publica: str = os.getenv("MOODLE_URL_PUBLICA", os.getenv("MOODLE_URL", "http://localhost:8000"))
    moodle_token: str = os.getenv("MOODLE_TOKEN", "token-demo")
    curso_id: int = int(os.getenv("MOODLE_CURSO_ID", "101"))
    intervalo_segundos: int = int(os.getenv("INTERVALO_SEGUNDOS", "3600"))  # a cada hora (enunciado)
    janela_horas: float = float(os.getenv("JANELA_HORAS", "24"))
    rabbitmq_url: str = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/%2F")
    fila: str = os.getenv("FILA_SOLICITACOES", "reengajamento.solicitacoes")
    porta_http: int = int(os.getenv("PORTA_HTTP", "8081"))
