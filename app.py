import json
import os
import logging
import boto3
from flask import Flask, request, jsonify
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

APP_VERSION = "0.5.0"

# Histórico de conversa por chat_id: { chat_id: [{"role": "user/assistant", "content": "..."}] }
conversation_history = {}

TELEGRAM_ORCAMENTOS_TOKEN = os.environ.get("TELEGRAM_ORCAMENTOS_TOKEN", "")
TELEGRAM_ORCAMENTISTA_TOKEN = os.environ.get("TELEGRAM_ORCAMENTISTA_TOKEN", "")
CHAT_ID_ORCAMENTISTA = os.environ.get("CHAT_ID_ORCAMENTISTA", "")

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
KB_ID = os.environ.get("KB_ID", "LY3SXOJI2N")

SYSTEM_PROMPT = """Voce eh o Orcamentista Leograf, assistente que valida solicitacoes de orcamento grafico antes de encaminhar ao time de orcamentos.

REGRA ABSOLUTA DE FORMATACAO:
- NUNCA use Markdown na resposta (nada de **, __, `, ```, #, >, etc.)
- Texto puro sempre, sem formatacao

QUANDO O VENDEDOR ENVIAR UMA SAUDACAO (oi, ola, bom dia, boa tarde, etc.) OU MENSAGEM SEM DADOS DE ORCAMENTO:
Responda EXATAMENTE com o texto, sem alterar nada:

(Ola! Sou o Orcamentista Leograf.

Para validar seu pedido, preciso das seguintes informacoes:

- Produto (ex: folder, flyer, cartao de visita)
- Quantidade (volume desejado)
- Formato (dimensoes do material, ex: A4, 20x20cm)
- Papel (ex: couche, offset, triplex)
- Gramatura (peso do papel em g/m2, ex: 115g, 300g)
- Cores (padrao frente x verso, ex: 4x4, 4x0, 1x0)
- Acabamento (ex: laminacao, verniz, dobra, refile)

Pode enviar tudo junto numa mensagem so, tipo:
folder 1000 A4 couche 115g 4x4 dobra simples

Aguardo os dados do seu pedido!)

QUANDO O VENDEDOR ENVIAR DADOS DE ORCAMENTO:
Analise a mensagem e identifique os 7 campos obrigatorios:
1. Produto - tipo de material grafico
2. Quantidade - volume solicitado
3. Formato - dimensao final
4. Papel - material base de impressao
5. Gramatura - peso do papel em g/m2
6. Cores - padrao frente x verso
7. Acabamento - processos apos impressao

Aceite mensagens curtas, fora de ordem, com abreviacoes tecnicas, estilo WhatsApp.

SE FALTAR ALGUM CAMPO, responda assim:

Pendencias identificadas no pedido:
- [campo faltante 1]
- [campo faltante 2]
- [campo faltante 3]
- [campo faltante 4]


Sugestoes tecnicas:
- [sugestao compativel com o produto/papel informado]

Favor complementar as informacoes para continuidade do orcamento.

SE TODOS OS CAMPOS ESTIVEREM PRESENTES, responda assim:

Pedido completo.

Resumo do pedido:
- Produto: [valor]
- Quantidade: [valor]
- Formato: [valor]
- Papel: [valor]
- Gramatura: [valor]
- Cores: [valor]
- Acabamento: [valor]

Encaminhando para analise tecnica.

REGRAS DE VALIDACAO:
- Se houver inconsistencia tecnica, informe (ex: cartao de visita em 90g = gramatura incompativel)
- Se faltar papel, sugira opcoes compativeis com o produto
- Se faltar gramatura, sugira compativeis com o papel
- Nunca escolha pelo vendedor, sempre peca confirmacao

RESTRICOES:
- Nunca calcule precos
- Nunca estime prazo
- Nunca altere dados informados
- Nunca assuma informacoes nao fornecidas
- Nunca ignore inconsistencias tecnicas
- Nunca use formatacao Markdown"""


WELCOME_MESSAGE = """Ola! Sou o Orcamentista Leograf.

Para validar seu pedido, preciso das seguintes informacoes:

- Produto (ex: folder, flyer, cartao de visita)
- Quantidade (volume desejado)
- Formato (dimensoes do material, ex: A4, 20x20cm)
- Papel (ex: couche, offset, triplex)
- Gramatura (peso do papel em g/m2, ex: 115g, 300g)
- Cores (padrao frente x verso, ex: 4x4, 4x0, 1x0)
- Acabamento (ex: laminacao, verniz, dobra, refile)

Pode enviar tudo junto numa mensagem so, tipo:
folder 1000 A4 couche 115g 4x4 dobra simples

Aguardo os dados do seu pedido!"""


@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.get_json(silent=True) or {}
    logger.info("Payload recebido: %s", json.dumps(body, ensure_ascii=False))

    try:
        chat_id, text = parse_telegram_event(body)
    except TelegramParseError as e:
        logger.warning("Payload inválido: %s", str(e))
        return jsonify({"ok": True})

    if not text:
        logger.warning("Mensagem sem texto. chat_id=%s", chat_id)
        return jsonify({"ok": True})

    # Comandos de controle
    if text.lower() in ["/start", "/novo", "/reiniciar", "/clear"]:
        conversation_history.pop(chat_id, None)
        send_message_to_telegram(
            token=TELEGRAM_ORCAMENTOS_TOKEN,
            chat_id=chat_id,
            text="🔄 Conversa reiniciada. Pode enviar seu pedido de orçamento."
        )
        return jsonify({"ok": True})

    logger.info("Mensagem recebida | chat_id=%s | texto=%s", chat_id, text)

    # Adiciona mensagem do usuário ao histórico
    history = conversation_history.setdefault(chat_id, [])

    # Primeira interação do chat (sem resposta anterior) → manda mensagem padrão
    has_assistant_reply = any(m["role"] == "assistant" for m in history)
    logger.info("chat_id=%s | historico=%d msgs | has_assistant=%s", chat_id, len(history), has_assistant_reply)
    if not has_assistant_reply:
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": WELCOME_MESSAGE})
        send_message_to_telegram(
            token=TELEGRAM_ORCAMENTOS_TOKEN,
            chat_id=chat_id,
            text=WELCOME_MESSAGE
        )
        return jsonify({"ok": True})
        send_message_to_telegram(
            token=TELEGRAM_ORCAMENTOS_TOKEN,
            chat_id=chat_id,
            text=WELCOME_MESSAGE
        )
        return jsonify({"ok": True})

    history.append({"role": "user", "content": text})

    try:
        ai_response = invoke_bedrock_with_kb(history)
        logger.info("Resposta Bedrock: %s", ai_response)

        # Adiciona resposta da IA ao histórico
        history.append({"role": "assistant", "content": ai_response})

        route_response(chat_id, ai_response)

        # Limpa histórico se pedido foi concluído
        if "Pedido completo." in ai_response:
            conversation_history.pop(chat_id, None)
            logger.info("Histórico limpo após pedido completo. chat_id=%s", chat_id)

    except BedrockError as e:
        logger.error("Falha Bedrock: %s", str(e))
        send_message_to_telegram(
            token=TELEGRAM_ORCAMENTOS_TOKEN,
            chat_id=chat_id,
            text="❌ Erro ao processar seu pedido. Tente novamente em instantes."
        )

    return jsonify({"ok": True})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": APP_VERSION})


# --- Parsing ---

def parse_telegram_event(body):
    message = body.get("message") or body.get("edited_message")
    if not message:
        raise TelegramParseError("Campo 'message' ausente no payload")

    chat_id = message.get("chat", {}).get("id")
    if not chat_id:
        raise TelegramParseError("chat_id ausente")

    text = message.get("text", "").strip()
    return chat_id, text


# --- Bedrock + Knowledge Base ---

def invoke_bedrock_with_kb(history):
    """
    Faz retrieve no Knowledge Base e passa o contexto pro modelo via invoke_model.
    """
    user_text = history[-1]["content"]

    # Passo 1: Buscar contexto no Knowledge Base
    kb_context = ""
    try:
        kb_client = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)
        retrieve_response = kb_client.retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": user_text},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": 5
                }
            }
        )
        results = retrieve_response.get("retrievalResults", [])
        if results:
            chunks = [r["content"]["text"] for r in results if r.get("content", {}).get("text")]
            kb_context = "\n\n".join(chunks)
            logger.info("KB retornou %d resultados.", len(chunks))
        else:
            logger.info("KB não retornou resultados.")
    except Exception as e:
        logger.warning("KB retrieve falhou: %s", str(e))

    # Passo 2: Chamar modelo com contexto do KB + histórico
    system_with_kb = SYSTEM_PROMPT
    if kb_context:
        system_with_kb += f"\n\nCONTEXTO DA BASE DE CONHECIMENTO:\n{kb_context}"

    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "system": system_with_kb,
        "messages": history
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
        raise BedrockError(str(e))


# --- Roteamento ---

def route_response(chat_id, ai_response):
    if "Pendências identificadas no pedido:" in ai_response:
        logger.info("Pedido incompleto → respondendo vendedor. chat_id=%s", chat_id)
        send_message_to_telegram(
            token=TELEGRAM_ORCAMENTOS_TOKEN,
            chat_id=chat_id,
            text=ai_response
        )
    elif "Pedido completo." in ai_response:
        logger.info("Pedido completo → confirmando vendedor e encaminhando orçamentista.")
        send_message_to_telegram(
            token=TELEGRAM_ORCAMENTOS_TOKEN,
            chat_id=chat_id,
            text="✅ Pedido validado! Encaminhando ao orçamentista..."
        )
        forward_to_orcamentista(ai_response)
    else:
        logger.warning("Resposta fora do formato esperado: %s", ai_response)
        send_message_to_telegram(
            token=TELEGRAM_ORCAMENTOS_TOKEN,
            chat_id=chat_id,
            text=ai_response
        )


def forward_to_orcamentista(ai_response):
    message = f"📄 *Novo pedido validado automaticamente*\n\n{ai_response}"
    send_message_to_telegram(
        token=TELEGRAM_ORCAMENTISTA_TOKEN,
        chat_id=CHAT_ID_ORCAMENTISTA,
        text=message,
        parse_mode="Markdown"
    )


# --- Telegram ---

import re


def strip_markdown(text):
    """Remove formatação Markdown para exibição limpa no Telegram."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)   # **negrito**
    text = re.sub(r'__(.+?)__', r'\1', text)        # __negrito__
    text = re.sub(r'\*(.+?)\*', r'\1', text)        # *itálico*
    text = re.sub(r'_(.+?)_', r'\1', text)          # _itálico_
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)  # ```bloco```
    text = re.sub(r'`(.+?)`', r'\1', text)          # `código`
    return text


def send_message_to_telegram(token, chat_id, text, parse_mode=None):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    if not parse_mode:
        text = strip_markdown(text)
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"})

    try:
        with urlopen(req, timeout=8) as resp:
            result = json.loads(resp.read())
            if not result.get("ok"):
                logger.error("Telegram API erro: %s", result)
            else:
                logger.info("Mensagem enviada com sucesso. chat_id=%s", chat_id)
    except HTTPError as e:
        logger.error("HTTPError Telegram: %s", e)
    except URLError as e:
        logger.error("URLError Telegram: %s", e)


# --- Exceções ---

class TelegramParseError(Exception):
    pass

class BedrockError(Exception):
    pass


if __name__ == "__main__":
    logger.info("Leograf Orcamentos v%s - Iniciando servidor na porta 5000...", APP_VERSION)
    app.run(host="0.0.0.0", port=5000, debug=False)
