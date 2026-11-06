# Roteiro da demonstração (checkpoint de Validação, 06/11)

Tempo estimado: 8 a 10 minutos.

> **Windows (PowerShell):** troque `curl` por `curl.exe` em todos os comandos. No
> PowerShell, `curl` sozinho é outro comando e não aceita `-X POST`.

## Antes de entrar na sala (5 min)

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps            # todos "running"; rabbitmq "healthy"
```

Deixe abertas quatro abas no navegador:

1. http://localhost:8025 (Mailpit)
2. http://localhost:15672 (RabbitMQ, guest/guest), aba **Queues**
3. http://localhost:8082/envios
4. http://localhost:8000/admin/estado

E um terminal com `docker compose logs -f acompanhamento notificacoes`.

Zere tudo antes de começar:

```bash
curl -X POST http://localhost:8000/admin/reset
curl -X POST http://localhost:8082/admin/limpar
curl -X DELETE http://localhost:8025/api/v1/messages
```

## 1. O problema e a arquitetura (1 min)

Mostre o diagrama do README. Fale: Moodle ⇄ Acompanhamento é **síncrono** (REST);
Acompanhamento → Notificações é **assíncrono** (fila RabbitMQ); tudo em **contêineres**.

## 2. Critérios 1 e 2: quem recebe e quem não recebe (2 min)

Mostre `/admin/estado` e explique a tabela de tarefas (README, seção "Dados do Moodle simulado").

```bash
curl -X POST http://localhost:8081/executar
```

No Mailpit aparecem **4 e-mails**: Ana, Carla e Diego (Relatório da Sprint 3) e Bruno
(Checklist). Abra um e mostre nome da tarefa, prazo no horário de Brasília e link.

Destaque quem **não** recebeu: Bruno na tarefa 1 (já entregou), Carla recebeu porque só
tem rascunho, nada das tarefas de 72h, vencida, em grupo ou sem prazo, e a professora.

## 3. Critério 3: reprocessar não reenvia (1 min)

```bash
curl -X POST http://localhost:8081/executar
```

Mailpit continua com 4. Em http://localhost:8082/eventos aparecem os eventos
`ignorado_ja_enviado`. Explique a chave `curso:tarefa:aluno`.

## 4. Critério 4: falha e nova tentativa (2 min)

```bash
curl -X POST http://localhost:8000/admin/tarefas -H "Content-Type: application/json" -d "{\"nome\":\"Entrega extra\",\"horas\":3}"
docker compose stop mailpit
curl -X POST http://localhost:8081/executar
```

- Logs: `Falha ao enviar ... Connection refused` e `Nova tentativa ... agendada em 15s`.
- RabbitMQ: mensagens passando por `reengajamento.retentativas`.
- `/envios`: status `falhou`, `tentativas`, `ultimo_erro`.

```bash
docker compose start mailpit
```

Em até ~15 s os 4 e-mails da "Entrega extra" chegam e `/envios` mostra `enviado`
com `tentativas` ≥ 2.

## 5. Fechamento (1 min)

```bash
python scripts/verificar_criterios.py
```

Mostra os 6 `PASSOU` automaticamente. Se faltar tempo, rode só este passo.

Próximos passos até 20/11: testar contra um Moodle real, vídeo e relatório individual.

## Se algo der errado

| Sintoma | O que fazer |
|---|---|
| Nenhum e-mail | `docker compose logs acompanhamento`: se aparecer erro de conexão com o Moodle, `docker compose restart acompanhamento` |
| `/admin/limpar` dá 404 | falta `PERMITIR_LIMPEZA=true` no `.env`; depois `docker compose up -d` |
| Porta ocupada | outra aplicação usa 8000/8025/5672; pare-a ou troque a porta em `docker-compose.yml` |
| Quer recomeçar do zero | `docker compose down -v && docker compose up -d --build` |
