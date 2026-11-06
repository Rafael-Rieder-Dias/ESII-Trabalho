"""Testes do processamento: critérios de aceite 3 (sem reenvio) e 4 (falhas e nova tentativa)."""
import json

from app.email_sender import formatar_prazo, montar_email
from app.main import FILA_FALHAS, FILA_RETENTATIVAS, criar_callback
from app.processador import Processador, Resultado
from app.repositorio import ENVIADO, FALHOU, Repositorio

SOL = {"id": "101:1:11", "curso_id": 101, "curso_nome": "ES2", "tarefa_id": 1, "tarefa_cmid": 501,
       "tarefa_nome": "Relatório", "prazo": 1_800_000_000, "link": "http://m/mod/assign/view.php?id=501",
       "aluno_id": 11, "aluno_nome": "Ana Souza", "aluno_email": "ana@x.br"}


class EnviadorFalso:
    def __init__(self, falhas=0):
        self.falhas_restantes = falhas
        self.enviados = []

    def enviar(self, sol):
        if self.falhas_restantes > 0:
            self.falhas_restantes -= 1
            raise ConnectionRefusedError("SMTP fora do ar")
        self.enviados.append(sol["id"])


def test_envia_e_registra_resultado():
    repo, env = Repositorio(), EnviadorFalso()
    assert Processador(repo, env).processar(SOL) == Resultado.ENVIADO
    assert env.enviados == ["101:1:11"]
    assert repo.status("101:1:11") == ENVIADO
    assert repo.listar_eventos()[0]["evento"] == "enviado"


def test_criterio3_reprocessar_solicitacao_concluida_nao_reenvia():
    repo, env = Repositorio(), EnviadorFalso()
    p = Processador(repo, env)
    p.processar(SOL)
    assert p.processar(SOL) == Resultado.DUPLICADO
    assert p.processar(dict(SOL)) == Resultado.DUPLICADO
    assert env.enviados == ["101:1:11"]  # um único e-mail
    assert [e["evento"] for e in repo.listar_eventos()].count("ignorado_ja_enviado") == 2


def test_criterio3_persistente_entre_reinicios(tmp_path):
    banco = str(tmp_path / "n.db")
    Processador(Repositorio(banco), EnviadorFalso()).processar(SOL)
    env = EnviadorFalso()
    assert Processador(Repositorio(banco), env).processar(SOL) == Resultado.DUPLICADO
    assert env.enviados == []


def test_criterio4_falha_registrada_e_nova_tentativa_envia():
    repo, env = Repositorio(), EnviadorFalso(falhas=2)
    p = Processador(repo, env, max_tentativas=5)
    assert p.processar(SOL, 1) == Resultado.RETENTAR
    assert repo.status("101:1:11") == FALHOU
    assert "SMTP fora do ar" in repo.listar_envios()[0]["ultimo_erro"]
    assert p.processar(SOL, 2) == Resultado.RETENTAR
    assert p.processar(SOL, 3) == Resultado.ENVIADO
    reg = repo.listar_envios()[0]
    assert reg["status"] == ENVIADO and reg["tentativas"] == 3 and reg["ultimo_erro"] is None
    eventos = [e["evento"] for e in reversed(repo.listar_eventos())]
    assert eventos == ["falha_vai_tentar_novamente", "falha_vai_tentar_novamente", "enviado"]


def test_criterio4_esgota_tentativas():
    repo = Repositorio()
    p = Processador(repo, EnviadorFalso(falhas=99), max_tentativas=3)
    assert [p.processar(SOL, t) for t in (1, 2, 3)] == [Resultado.RETENTAR, Resultado.RETENTAR, Resultado.ESGOTADO]
    assert repo.listar_eventos()[0]["evento"] == "falha_definitiva"


def test_mensagem_invalida():
    assert Processador(Repositorio(), EnviadorFalso()).processar({"id": "x"}) == Resultado.INVALIDA


# --- comportamento junto à fila (RabbitMQ simulado) -----------------------

class Metodo:
    delivery_tag = 7


class Props:
    def __init__(self, tentativa=None):
        self.headers = {"x-tentativa": tentativa} if tentativa else None


class CanalFalso:
    def __init__(self):
        self.publicadas, self.acks = [], []

    def basic_publish(self, exchange, routing_key, body, properties):
        self.publicadas.append((routing_key, properties.headers, properties.expiration))

    def basic_ack(self, tag):
        self.acks.append(tag)


def test_callback_falha_vai_para_fila_de_retentativas_com_atraso():
    canal = CanalFalso()
    cb = criar_callback(Processador(Repositorio(), EnviadorFalso(falhas=1)))
    cb(canal, Metodo, Props(), json.dumps(SOL).encode())
    fila, headers, expiracao = canal.publicadas[0]
    assert fila == FILA_RETENTATIVAS and headers["x-tentativa"] == 2 and int(expiracao) > 0
    assert canal.acks == [7]


def test_callback_esgotado_vai_para_fila_de_falhas():
    canal = CanalFalso()
    cb = criar_callback(Processador(Repositorio(), EnviadorFalso(falhas=99), max_tentativas=2))
    cb(canal, Metodo, Props(tentativa=2), json.dumps(SOL).encode())
    assert canal.publicadas[0][0] == FILA_FALHAS and canal.acks == [7]


def test_callback_json_invalido_vai_para_fila_de_falhas():
    canal = CanalFalso()
    criar_callback(Processador(Repositorio(), EnviadorFalso()))(canal, Metodo, Props(), b"nao-json")
    assert canal.publicadas[0][0] == FILA_FALHAS and canal.acks == [7]


def test_email_tem_nome_tarefa_prazo_no_fuso_e_link():
    # 1_800_000_000 = 15/01/2027 08:00 UTC = 05:00 em São Paulo
    assert formatar_prazo(1_800_000_000, "America/Sao_Paulo") == "15/01/2027 às 05:00"
    msg = montar_email(SOL, "rem@x", "America/Sao_Paulo")
    corpo = msg.get_content()
    assert msg["To"] == "ana@x.br" and "Relatório" in msg["Subject"]
    assert "Olá, Ana!" in corpo and "15/01/2027 às 05:00" in corpo and SOL["link"] in corpo
