#!/usr/bin/env python3
"""Verifica os 4 critérios de aceite contra o ambiente rodando (docker compose up).

Uso:   python scripts/verificar_criterios.py
       python scripts/verificar_criterios.py --sem-falha   (pula o critério 4)

Só usa a biblioteca padrão do Python. Pré-requisitos: `docker compose up -d`
com o .env de demonstração (PERMITIR_LIMPEZA=true).

O critério 4 derruba o Mailpit (docker compose stop mailpit) para provocar a
falha de SMTP e depois o religa. Os comandos podem ser trocados pelas
variáveis PARAR_SMTP_CMD e INICIAR_SMTP_CMD.

A saída deste script é o "registro dos testes" (salve com > docs/registro.txt).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

MOODLE = os.getenv("MOODLE_MOCK_URL", "http://localhost:8000")
ACOMP = os.getenv("ACOMPANHAMENTO_URL", "http://localhost:8081")
NOTIF = os.getenv("NOTIFICACOES_URL", "http://localhost:8082")
MAILPIT = os.getenv("MAILPIT_URL", "http://localhost:8025")
PARAR_SMTP = os.getenv("PARAR_SMTP_CMD", "docker compose stop mailpit")
INICIAR_SMTP = os.getenv("INICIAR_SMTP_CMD", "docker compose start mailpit")

resultados: list[tuple[str, bool]] = []


def http(metodo: str, url: str, dados: dict | None = None):
    corpo = json.dumps(dados).encode() if dados is not None else None
    req = urllib.request.Request(url, data=corpo, method=metodo, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        texto = r.read().decode() or "null"
        return json.loads(texto)


def emails() -> list[dict]:
    return http("GET", f"{MAILPIT}/api/v1/messages?limit=500").get("messages") or []


def destinatarios() -> list[str]:
    return sorted(m["To"][0]["Address"] for m in emails())


def esperar(cond, segundos: float, passo: float = 1.0) -> bool:
    fim = time.time() + segundos
    while time.time() < fim:
        try:
            if cond():
                return True
        except Exception:
            pass
        time.sleep(passo)
    return False


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def checar(nome: str, ok: bool, detalhe: str = "") -> None:
    resultados.append((nome, ok))
    log(f"{'PASSOU' if ok else 'FALHOU'}  {nome}" + (f"  ({detalhe})" if detalhe else ""))


def preparar() -> None:
    log("Preparando: recriando dados do Moodle simulado e limpando registros e caixa de entrada")
    http("POST", f"{MOODLE}/admin/reset")
    http("POST", f"{NOTIF}/admin/limpar")
    time.sleep(2)  # deixa a fila escoar mensagens de ciclos automáticos anteriores
    http("POST", f"{NOTIF}/admin/limpar")
    http("DELETE", f"{MAILPIT}/api/v1/messages")


def criterios_1_e_2() -> None:
    log("Executando ciclo do Acompanhamento")
    r = http("POST", f"{ACOMP}/executar")
    log(f"Ciclo: {r.get('solicitacoes_publicadas')} solicitações publicadas -> {r.get('ids')}")
    esperado = sorted(["ana.souza@exemplo.edu.br", "carla.mendes@exemplo.edu.br",
                       "diego.rocha@exemplo.edu.br", "bruno.lima@exemplo.edu.br"])
    esperar(lambda: len(emails()) >= 4, 30)
    time.sleep(2)
    recebidos = destinatarios()
    assuntos = [m["Subject"] for m in emails()]
    log(f"E-mails no Mailpit: {len(recebidos)}")
    for a in sorted(assuntos):
        log(f"   - {a}")

    t1 = sorted(m["To"][0]["Address"] for m in emails() if "Relatório da Sprint 3" in m["Subject"])
    checar("Critério 1: lembrete para tarefa pendente dentro da janela de 24h",
           t1 == ["ana.souza@exemplo.edu.br", "carla.mendes@exemplo.edu.br", "diego.rocha@exemplo.edu.br"],
           f"Relatório da Sprint 3 -> {t1}")
    checar("Critério 2a: nenhum lembrete para quem já enviou (Bruno na T1; Ana, Carla e Diego na T2)",
           recebidos == esperado, f"destinatários = {recebidos}")
    ignoradas = ["Diagrama de arquitetura", "Questionário 1", "Trabalho em grupo", "Leitura complementar"]
    vazou = [a for a in assuntos if any(n in a for n in ignoradas)]
    checar("Critério 2b: nenhum lembrete fora da janela (72h), vencida, em grupo ou sem prazo",
           not vazou, f"indevidos = {vazou}")


def criterio_3() -> None:
    antes = len(emails())
    log("Reprocessando: executando o ciclo de novo (mesmas 4 solicitações voltam para a fila)")
    http("POST", f"{ACOMP}/executar")
    time.sleep(6)
    depois = len(emails())
    ignorados = [e for e in http("GET", f"{NOTIF}/eventos") if e["evento"] == "ignorado_ja_enviado"]
    checar("Critério 3: nenhum novo envio ao reprocessar solicitação concluída",
           depois == antes and len(ignorados) >= 4,
           f"e-mails antes={antes} depois={depois}; eventos 'ignorado_ja_enviado'={len(ignorados)}")


def criterio_4() -> None:
    tarefa = http("POST", f"{MOODLE}/admin/tarefas", {"nome": "Entrega extra (teste de falha)", "horas": 3})
    chaves = {f"101:{tarefa['id']}:{a}" for a in (11, 12, 13, 14)}
    log(f"Criada tarefa {tarefa['id']} '{tarefa['name']}' sem envios. Derrubando o SMTP: {PARAR_SMTP}")
    subprocess.run(PARAR_SMTP, shell=True, check=True)
    try:
        http("POST", f"{ACOMP}/executar")

        def falhas_registradas():
            ev = http("GET", f"{NOTIF}/eventos")
            return {e["solicitacao_id"] for e in ev if e["evento"] == "falha_vai_tentar_novamente"} >= chaves

        ok_falha = esperar(falhas_registradas, 40)
        envios = {e["id"]: e for e in http("GET", f"{NOTIF}/envios") if e["id"] in chaves}
        erros = {e.get("ultimo_erro") for e in envios.values()}
        checar("Critério 4a: falha de envio registrada (status, tentativa e erro)",
               ok_falha and all(e["status"] == "falhou" for e in envios.values()),
               f"último erro = {next(iter(erros), None)}")
    finally:
        log(f"Religando o SMTP: {INICIAR_SMTP}")
        subprocess.run(INICIAR_SMTP, shell=True, check=True)

    def todos_enviados():
        env = {e["id"]: e for e in http("GET", f"{NOTIF}/envios") if e["id"] in chaves}
        return len(env) == 4 and all(e["status"] == "enviado" for e in env.values())

    ok = esperar(todos_enviados, 120, 2)
    envios = [e for e in http("GET", f"{NOTIF}/envios") if e["id"] in chaves]
    tentativas = sorted(e["tentativas"] for e in envios)
    extra = [m for m in emails() if "Entrega extra" in m["Subject"]]
    checar("Critério 4b: nova tentativa automática envia o lembrete depois que o SMTP volta",
           ok and all(t >= 2 for t in tentativas) and len(extra) == 4,
           f"tentativas por solicitação = {tentativas}; e-mails da tarefa extra = {len(extra)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sem-falha", action="store_true", help="não executa o critério 4 (não derruba o SMTP)")
    args = ap.parse_args()
    log("Verificação dos critérios de aceite — Serviço de reengajamento integrado ao Moodle")
    preparar()
    criterios_1_e_2()
    criterio_3()
    if not args.sem_falha:
        criterio_4()
    print()
    aprovados = sum(ok for _, ok in resultados)
    log(f"RESULTADO: {aprovados}/{len(resultados)} verificações passaram")
    return 0 if aprovados == len(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
