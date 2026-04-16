# Tech Stack

## Linguagem
- Python 3.x

## Frameworks e Bibliotecas
- Flask — servidor HTTP (webhook Telegram)
- boto3 — AWS SDK (Bedrock Runtime, Bedrock Agent Runtime)
- python-dotenv — carregamento de variáveis de ambiente via `.env`
- urllib (stdlib) — chamadas HTTP para a API do Telegram
- logging (stdlib) — logs estruturados
- re (stdlib) — strip de Markdown nas respostas

## Serviços AWS
- Amazon Bedrock — modelo Claude (anthropic.claude-sonnet-4-6) para IA conversacional
- Bedrock Knowledge Base — RAG para contexto adicional ao modelo
- AWS Lambda — deploy serverless (lambda_function.py)

## Infraestrutura
- Duas modalidades de execução:
  1. Local: Flask + ngrok (start.py orquestra Flask, ngrok e registro de webhook)
  2. Lambda: handler em lambda_function.py para deploy serverless
- PyInstaller — empacotamento em executável Windows (Leograf-Orcamentos.spec)

## Variáveis de Ambiente
Definidas em `.env` (ver `.env.example`):
- `TELEGRAM_ORCAMENTOS_TOKEN` — token do bot de vendedores
- `TELEGRAM_ORCAMENTISTA_TOKEN` — token do bot do orçamentista
- `CHAT_ID_ORCAMENTISTA` — chat ID destino do orçamentista
- `AWS_REGION` — região AWS (default: us-east-1)
- `KB_ID` — ID do Knowledge Base Bedrock

## Comandos Úteis

```bash
# Instalar dependências
pip install -r requirements.txt

# Rodar localmente (Flask + ngrok + webhook)
python start.py

# Rodar só o Flask (sem ngrok)
python app.py

# Empacotar executável Windows
pyinstaller Leograf-Orcamentos.spec
```
