# Estrutura do Projeto

```
├── app.py                      # Aplicação Flask principal (webhook, Bedrock, Telegram)
├── lambda_function.py          # Handler AWS Lambda (versão serverless do bot)
├── start.py                    # Orquestrador local (Flask + ngrok + webhook registration)
├── requirements.txt            # Dependências Python
├── .env                        # Variáveis de ambiente (não versionado)
├── .env.example                # Template de variáveis de ambiente
├── Leograf-Orcamentos.spec     # Config PyInstaller para gerar executável Windows
├── build/                      # Artefatos de build do PyInstaller
├── dist/                       # Executável gerado pelo PyInstaller
└── .kiro/steering/             # Steering files para assistente IA
```

## Arquivos Principais

- `app.py` — Contém toda a lógica do bot: webhook Flask, parsing de mensagens Telegram, invocação do Bedrock com Knowledge Base, roteamento de respostas, histórico de conversa em memória, e envio de mensagens via API Telegram. É o arquivo central do projeto.
- `lambda_function.py` — Versão simplificada para deploy em AWS Lambda. Sem histórico de conversa (stateless), sem Knowledge Base. Mesmo fluxo de triagem mas sem persistência entre mensagens.
- `start.py` — Script de inicialização local. Sobe Flask em thread, inicia ngrok como subprocesso, obtém URL pública e registra webhook no Telegram automaticamente.

## Padrões de Organização

- Projeto flat (sem subpastas de código) — todos os módulos Python na raiz
- Duas versões do bot coexistem: `app.py` (local, stateful) e `lambda_function.py` (serverless, stateless)
- Exceções customizadas definidas no mesmo arquivo que as usa (`TelegramParseError`, `BedrockError`)
- Sem testes automatizados no momento
