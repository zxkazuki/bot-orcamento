import subprocess
import threading
import time
import json
import sys
import os
from multiprocessing import freeze_support
from urllib.request import urlopen, Request
from urllib.error import URLError
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

PORT = 5000
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_ORCAMENTOS_TOKEN", "")


def start_flask():
    from app import app
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


def get_ngrok_url(retries=10, delay=1.5):
    for i in range(retries):
        try:
            with urlopen("http://localhost:4040/api/tunnels", timeout=3) as resp:
                data = json.loads(resp.read())
                for t in data.get("tunnels", []):
                    if t.get("proto") == "https":
                        return t["public_url"]
        except Exception:
            pass
        print(f"  Aguardando ngrok... ({i+1}/{retries})")
        time.sleep(delay)
    return None


def register_webhook(ngrok_url):
    endpoint = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
    payload = json.dumps({"url": f"{ngrok_url}/webhook"}).encode("utf-8")
    req = Request(endpoint, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except Exception as e:
        print(f"  Erro ao registrar webhook: {e}")
        return False


def main():
    load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)
    global TELEGRAM_TOKEN
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_ORCAMENTOS_TOKEN", "")

    print("=" * 50)
    print("  Leograf Orcamentos v0.5.0 - Iniciando...")
    print("=" * 50)

    # Sobe Flask em thread
    print("\n[1/3] Iniciando servidor Flask...")
    t = threading.Thread(target=start_flask, daemon=True)
    t.start()
    time.sleep(2)
    print("  Flask rodando em http://localhost:5000")

    # Sobe ngrok em subprocesso
    print("\n[2/3] Iniciando ngrok...")
    ngrok_proc = subprocess.Popen(
        ["ngrok", "http", str(PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(3)

    # Pega URL publica
    print("\n[3/3] Obtendo URL publica do ngrok...")
    ngrok_url = get_ngrok_url()

    if not ngrok_url:
        print("\n❌ Nao foi possivel obter a URL do ngrok.")
        print("   Verifique se o ngrok esta instalado e autenticado.")
        input("\nPressione ENTER para fechar...")
        ngrok_proc.terminate()
        return

    print(f"  URL publica: {ngrok_url}")

    # Registra webhook
    print("  Registrando webhook no Telegram...")
    ok = register_webhook(ngrok_url)

    if ok:
        print(f"\n✅ Webhook registrado: {ngrok_url}/webhook")
    else:
        print(f"\n⚠️  Registre manualmente: {ngrok_url}/webhook")

    print("\n" + "=" * 50)
    print("  Bot rodando. Pressione Ctrl+C para encerrar.")
    print("=" * 50)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nEncerrando...")
    finally:
        ngrok_proc.terminate()


if __name__ == "__main__":
    freeze_support()
    main()
