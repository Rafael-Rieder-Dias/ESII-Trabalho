# Registro dos testes

Executado em 06/11/2026. Python 3.13, RabbitMQ 3.x real (instalado localmente). No lugar do Mailpit foi usado um servidor SMTP de teste com a mesma API de leitura (`/api/v1/messages`), porque o ambiente de execução não tinha Docker disponível.

> **A equipe deve repetir a verificação com `docker compose up` e substituir a seção 2 pela saída real:** `python scripts/verificar_criterios.py > docs/registro-verificacao.txt`

## 1. Testes automatizados (pytest)

### Acompanhamento

```
tests/test_integracao_moodle.py::test_cliente_le_as_tres_funcoes PASSED
tests/test_integracao_moodle.py::test_token_invalido_vira_erro PASSED
tests/test_integracao_moodle.py::test_ciclo_completo_publica_somente_os_pendentes PASSED
tests/test_integracao_moodle.py::test_falha_no_moodle_nao_derruba_o_servico PASSED
tests/test_selecao.py::test_criterio1_lembrete_para_tarefa_pendente_dentro_da_janela PASSED
tests/test_selecao.py::test_criterio2_sem_lembrete_para_tarefa_ja_enviada PASSED
tests/test_selecao.py::test_criterio2_sem_lembrete_para_tarefa_fora_da_janela PASSED
tests/test_selecao.py::test_tarefa_vencida_e_sem_prazo_sao_ignoradas PASSED
tests/test_selecao.py::test_limites_da_janela PASSED
tests/test_selecao.py::test_rascunho_conta_como_pendente PASSED
tests/test_selecao.py::test_entrega_em_grupo_fora_do_escopo PASSED
tests/test_selecao.py::test_somente_estudantes_com_email PASSED
tests/test_selecao.py::test_um_lembrete_por_aluno_e_tarefa PASSED
tests/test_selecao.py::test_chave_idempotencia_estavel PASSED
============================== 14 passed in 0.70s ==============================
```

### Notificações

```
tests/test_processador.py::test_envia_e_registra_resultado PASSED
tests/test_processador.py::test_criterio3_reprocessar_solicitacao_concluida_nao_reenvia PASSED
tests/test_processador.py::test_criterio3_persistente_entre_reinicios PASSED
tests/test_processador.py::test_criterio4_falha_registrada_e_nova_tentativa_envia PASSED
tests/test_processador.py::test_criterio4_esgota_tentativas PASSED
tests/test_processador.py::test_mensagem_invalida PASSED
tests/test_processador.py::test_callback_falha_vai_para_fila_de_retentativas_com_atraso PASSED
tests/test_processador.py::test_callback_esgotado_vai_para_fila_de_falhas PASSED
tests/test_processador.py::test_callback_json_invalido_vai_para_fila_de_falhas PASSED
tests/test_processador.py::test_email_tem_nome_tarefa_prazo_no_fuso_e_link PASSED
============================== 10 passed in 0.07s ==============================
```

## 2. Verificação dos critérios de aceite (ponta a ponta)

Serviços reais (Acompanhamento, Notificações, Moodle simulado) conectados a um RabbitMQ real. O SMTP foi derrubado e religado no critério 4. Intervalo de retentativa reduzido para 5 s nesta execução (no `.env` padrão é 15 s).

```
[10:14:36] Verificação dos critérios de aceite — Serviço de reengajamento integrado ao Moodle
[10:14:36] Preparando: recriando dados do Moodle simulado e limpando registros e caixa de entrada
[10:14:38] Executando ciclo do Acompanhamento
[10:14:38] Ciclo: 4 solicitações publicadas -> ['101:1:11', '101:1:13', '101:1:14', '101:2:12']
[10:14:41] E-mails no Mailpit: 4
[10:14:41]    - Lembrete: "Checklist de validação" vence em 07/11/2026 às 06:14
[10:14:41]    - Lembrete: "Relatório da Sprint 3" vence em 06/11/2026 às 16:14
[10:14:41]    - Lembrete: "Relatório da Sprint 3" vence em 06/11/2026 às 16:14
[10:14:41]    - Lembrete: "Relatório da Sprint 3" vence em 06/11/2026 às 16:14
[10:14:41] PASSOU  Critério 1: lembrete para tarefa pendente dentro da janela de 24h  (Relatório da Sprint 3 -> ['ana.souza@exemplo.edu.br', 'carla.mendes@exemplo.edu.br', 'diego.rocha@exemplo.edu.br'])
[10:14:41] PASSOU  Critério 2a: nenhum lembrete para quem já enviou (Bruno na T1; Ana, Carla e Diego na T2)  (destinatários = ['ana.souza@exemplo.edu.br', 'bruno.lima@exemplo.edu.br', 'carla.mendes@exemplo.edu.br', 'diego.rocha@exemplo.edu.br'])
[10:14:41] PASSOU  Critério 2b: nenhum lembrete fora da janela (72h), vencida, em grupo ou sem prazo  (indevidos = [])
[10:14:41] Reprocessando: executando o ciclo de novo (mesmas 4 solicitações voltam para a fila)
[10:14:47] PASSOU  Critério 3: nenhum novo envio ao reprocessar solicitação concluída  (e-mails antes=4 depois=4; eventos 'ignorado_ja_enviado'=8)
[10:14:47] Criada tarefa 7 'Entrega extra (teste de falha)' sem envios. Derrubando o SMTP: (derruba o servidor SMTP de teste)
[10:14:49] PASSOU  Critério 4a: falha de envio registrada (status, tentativa e erro)  (último erro = ConnectionRefusedError: [Errno 111] Connection refused)
[10:14:49] Religando o SMTP: (religa o servidor SMTP de teste)
[10:14:54] PASSOU  Critério 4b: nova tentativa automática envia o lembrete depois que o SMTP volta  (tentativas por solicitação = [2, 2, 2, 2]; e-mails da tarefa extra = 4)

[10:14:54] RESULTADO: 6/6 verificações passaram
```

## 3. Trecho do log do Notificações durante o critério 4

```
2026-11-06 10:14:47,999 [notificacoes] WARNING Falha ao enviar 101:7:11 (tentativa 1/5): [Errno 111] Connection refused
2026-11-06 10:14:48,000 [notificacoes] INFO Nova tentativa de 101:7:11 agendada em 5s
2026-11-06 10:14:53,012 [notificacoes] INFO Lembrete enviado: 101:7:11 -> ana.souza@exemplo.edu.br (tentativa 2)
2026-11-06 10:15:14,486 [notificacoes] INFO Solicitação 101:7:11 já processada: lembrete NÃO reenviado
2026-11-06 10:15:44,506 [notificacoes] INFO Solicitação 101:7:11 já processada: lembrete NÃO reenviado
```
