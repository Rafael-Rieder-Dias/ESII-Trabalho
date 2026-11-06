"""Testes das regras de seleção (critérios de aceite 1 e 2)."""
from app.selecao import chave_idempotencia, selecionar_pendentes

AGORA = 1_800_000_000
H = 3600
CURSO = {"id": 101, "fullname": "Engenharia de Software II"}


def aluno(uid, email=True, papel="student"):
    return {"id": uid, "fullname": f"Aluno {uid}", "email": f"a{uid}@x.br" if email else "",
            "roles": [{"shortname": papel}]}


def tarefa(tid, prazo, grupo=0):
    return {"id": tid, "cmid": 500 + tid, "name": f"T{tid}", "duedate": prazo, "teamsubmission": grupo}


def selecionar(tarefas, usuarios, envios=None, janela=24 * H):
    return selecionar_pendentes(curso=CURSO, tarefas=tarefas, usuarios=usuarios, envios_por_tarefa=envios or {},
                                agora=AGORA, janela_segundos=janela, url_publica_moodle="http://moodle/")


def ids(sols):
    return sorted(s.id for s in sols)


def test_criterio1_lembrete_para_tarefa_pendente_dentro_da_janela():
    sols = selecionar([tarefa(1, AGORA + 6 * H)], [aluno(11)])
    assert ids(sols) == ["101:1:11"]
    s = sols[0]
    assert s.aluno_email == "a11@x.br"
    assert s.link == "http://moodle/mod/assign/view.php?id=501"
    assert s.prazo == AGORA + 6 * H


def test_criterio2_sem_lembrete_para_tarefa_ja_enviada():
    envios = {1: [{"userid": 11, "status": "submitted"}]}
    assert selecionar([tarefa(1, AGORA + 6 * H)], [aluno(11), aluno(12)], envios) == selecionar(
        [tarefa(1, AGORA + 6 * H)], [aluno(12)])


def test_criterio2_sem_lembrete_para_tarefa_fora_da_janela():
    assert selecionar([tarefa(1, AGORA + 25 * H)], [aluno(11)]) == []


def test_tarefa_vencida_e_sem_prazo_sao_ignoradas():
    assert selecionar([tarefa(1, AGORA - H), tarefa(2, 0), tarefa(3, AGORA)], [aluno(11)]) == []


def test_limites_da_janela():
    # exatamente 24h: entra; 24h + 1s: fica de fora
    assert ids(selecionar([tarefa(1, AGORA + 24 * H)], [aluno(11)])) == ["101:1:11"]
    assert selecionar([tarefa(1, AGORA + 24 * H + 1)], [aluno(11)]) == []


def test_rascunho_conta_como_pendente():
    envios = {1: [{"userid": 11, "status": "draft"}, {"userid": 12, "status": "new"}]}
    assert ids(selecionar([tarefa(1, AGORA + H)], [aluno(11), aluno(12)], envios)) == ["101:1:11", "101:1:12"]


def test_entrega_em_grupo_fora_do_escopo():
    assert selecionar([tarefa(1, AGORA + H, grupo=1)], [aluno(11)]) == []


def test_somente_estudantes_com_email():
    usuarios = [aluno(11), aluno(12, email=False), aluno(90, papel="editingteacher")]
    assert ids(selecionar([tarefa(1, AGORA + H)], usuarios)) == ["101:1:11"]


def test_um_lembrete_por_aluno_e_tarefa():
    sols = selecionar([tarefa(1, AGORA + H), tarefa(2, AGORA + 2 * H)], [aluno(11), aluno(12)])
    assert ids(sols) == ["101:1:11", "101:1:12", "101:2:11", "101:2:12"]
    assert len(set(ids(sols))) == len(sols)


def test_chave_idempotencia_estavel():
    assert chave_idempotencia(101, 1, 11) == "101:1:11"
