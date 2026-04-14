import json
import os
import logging
import boto3
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# Logging estruturado para CloudWatch
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Variáveis de ambiente
TELEGRAM_ORCAMENTOS_TOKEN = os.environ.get("8629920924:AAGwJVcrZRlaZTzwD8LcFe4H6tjESP1dA-Q")
TELEGRAM_ORCAMENTISTA_TOKEN = os.environ.get("8623843906:AAH4G-OfQAyFGmxBbO4Ya3xoYRbk1F38bcg")
CHAT_ID_ORCAMENTISTA = os.environ.get("6479085067")

# Modelo Bedrock
BEDROCK_MODEL_ID = "anthropic.claude-sonnet-4-6"

SYSTEM_PROMPT = """Você é um agente de triagem de pedidos de orçamento gráfico.

Sua tarefa é analisar mensagens enviadas por vendedores e verificar se o pedido contém os 7 campos obrigatórios:
1. Produto
2. Quantidade
3. Formato
4. Papel
5. Gramatura
6. Cores
7. Acabamento

REGRAS DE RESPOSTA:

Se algum campo estiver faltando ou incompleto, responda EXATAMENTE neste formato:
Pendências identificadas no pedido:
- [liste cada campo faltante]

Por favor, complemente o pedido com as informações acima.

Se todos os 7 campos estiverem presentes e claros, responda EXATAMENTE neste formato:
Pedido completo.

Resumo do pedido:
- Produto: [valor]
- Quantidade: [valor]
- Formato: [valor]
- Papel: [valor]
- Gramatura: [valor]
- Cores: [valor]
- Acabamento: [valor]

Seja objetivo e não adicione texto extra fora desses formatos."""


def lambda_handler(event, context):
    logger.info("Evento recebido: %s", json.dumps(event))

    try:
        body = parse_body(event)
        chat_id, text = parse_telegram_event(body)

        if not text:
            logger.warning("Mensagem sem texto recebida. chat_id=%s", chat_id)
            return ok()

        logger.info("Mensagem recebida. chat_id=%s | texto=%s", chat_id, text)

        ai_response = invoke_bedrock_model(text)
        logger.info("Resposta Bedrock: %s", ai_response)

        route_response(chat_id, ai_response)
        return ok()

    except TelegramParseError as e:
        logger.warning("Payload Telegram inválido: %s", str(e))
        return ok()
    except BedrockError as e:
        logger.error("Falha ao invocar Bedrock: %s", str(e))
        return error(str(e))
    except Exception as e:
        logger.exception("Erro inesperado: %s", str(e))
        return error(str(e))


# --- Parsing ---

def parse_body(event):
    body = event.get("body", "{}")
    if isinstance(body, str):
        return json.loads(body)
    return body or {}


def parse_telegram_event(body):
    message = body.get("message") or body.get("edited_message")
    if not message:
        raise TelegramParseError("Nenhum campo 'message' encontrado no payload")

    chat_id = message.get("chat", {}).get("id")
    if not chat_id:
        raise TelegramParseError("chat_id ausente na mensagem")

    text = message.get("text", "").strip()
    return chat_id, text


# --- Bedrock ---

def invoke_bedrock_model(user_text):
    client = boto3.client("bedrock-runtime")

    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": user_text}
        ]
    }

    try:
        response = client.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(payload)
        )
        result = json.loads(response["body"].read())
        return result["content"][0]["text"].strip()
    except Exception as e:
        raise BedrockError(f"Erro ao invocar modelo: {str(e)}")


# --- Roteamento ---

def route_response(chat_id, ai_response):
    if "Pendências identificadas no pedido:" in ai_response:
        logger.info("Pedido incompleto. Respondendo ao vendedor. chat_id=%s", chat_id)
        send_message_to_telegram(
            token=TELEGRAM_ORCAMENTOS_TOKEN,
            chat_id=chat_id,
            text=ai_response
        )
    elif "Pedido completo." in ai_response:
        logger.info("Pedido completo. Confirmando ao vendedor e encaminhando ao orçamentista.")
        send_message_to_telegram(
            token=TELEGRAM_ORCAMENTOS_TOKEN,
            chat_id=chat_id,
            text="✅ Pedido validado com sucesso! Encaminhando ao orçamentista..."
        )
        forward_to_orcamentista(ai_response)
    else:
        logger.warning("Resposta da IA fora do formato esperado: %s", ai_response)
        send_message_to_telegram(
            token=TELEGRAM_ORCAMENTOS_TOKEN,
            chat_id=chat_id,
            text="⚠️ Não consegui processar seu pedido. Por favor, tente novamente com mais detalhes."
        )


def forward_to_orcamentista(ai_response):
    message = f"📄 *Novo pedido validado automaticamente*\n\nResumo do pedido:\n{ai_response}"
    send_message_to_telegram(
        token=TELEGRAM_ORCAMENTISTA_TOKEN,
        chat_id=CHAT_ID_ORCAMENTISTA,
        text=message,
        parse_mode="Markdown"
    )


# --- Telegram ---

def send_message_to_telegram(token, chat_id, text, parse_mode=None):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"})

    try:
        with urlopen(req, timeout=8) as resp:
            result = json.loads(resp.read())
            if not result.get("ok"):
                logger.error("Telegram API retornou erro: %s", result)
    except HTTPError as e:
        logger.error("HTTPError ao enviar mensagem Telegram: %s", e)
    except URLError as e:
        logger.error("URLError ao enviar mensagem Telegram: %s", e)


# --- Helpers ---

def ok():
    return {"statusCode": 200, "body": "OK"}

def error(msg):
    return {"statusCode": 500, "body": msg}


# --- Exceções customizadas ---

class TelegramParseError(Exception):
    pass

class BedrockError(Exception):
    pass
