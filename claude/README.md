# Pasta `claude/` — notas de sessão e contexto para o agente

Documentação **complementar** a `docs/` e às regras em `.cursor/rules/`: decisões pontuais, armadilhas de layout de NF/PDF, e lembretes de operação descobertos com o assistente.

## O que vale guardar aqui

- **Notas por tema/data** — ex.: `2026-05-14-nfse-campinas-base-issqn.md` (regex, ordem dos extractors, PDFs de teste).
- **Runbook curto** — passos que não cabem no README principal (flags `main.py`, ordem sync → process → output).
- **Checklist de validação** — o que conferir após mudar `extractors.py` ou SharePoint.

## O que evitar

- Credenciais, tokens, URLs com query secreta, dumps enormes de log (use trecho + referência ao arquivo em `output/`).

## Como ir documentando nas próximas sessões

Peça explicitamente, por exemplo:

- “Adiciona um resumo desta correção em `claude/registro.md`.”
- “Cria `claude/<data>-<assunto>.md` com problema, causa e solução.”
- “Atualiza o README da pasta `claude` com a nova convenção de X.”

No Cursor, `@claude/README.md` ou `@claude/` ajuda o modelo a seguir o mesmo padrão.

## Manutenção

Revise periodicamente: fundir notas antigas em `docs/` quando virarem contrato do projeto, ou apagar duplicatas obsoletas.
