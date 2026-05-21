#!/bin/bash
set -e

echo "=== Atualizando sistema ==="
sudo apt update && sudo apt upgrade -y

echo "=== Instalando Python e dependencias ==="
sudo apt install -y python3 python3-pip python3-venv nginx openssl

echo "=== Criando diretorio da aplicacao ==="
sudo mkdir -p /opt/leograf-bot
sudo chown ubuntu:ubuntu /opt/leograf-bot

echo "=== Criando venv ==="
python3 -m venv /opt/leograf-bot/venv

echo "=== Instalando dependencias Python ==="
/opt/leograf-bot/venv/bin/pip install boto3 flask python-dotenv gunicorn

echo "=== Gerando certificado SSL auto-assinado ==="
sudo mkdir -p /etc/nginx/ssl
sudo openssl req -newkey rsa:2048 -sha256 -nodes \
  -keyout /etc/nginx/ssl/bot.key \
  -x509 -days 3650 \
  -out /etc/nginx/ssl/bot.pem \
  -subj "/CN=44.195.91.178"

echo "=== Configurando Nginx como reverse proxy com SSL ==="
sudo tee /etc/nginx/sites-available/leograf-bot > /dev/null <<'NGINX'
server {
    listen 443 ssl;
    server_name 44.195.91.178;

    ssl_certificate /etc/nginx/ssl/bot.pem;
    ssl_certificate_key /etc/nginx/ssl/bot.key;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX

sudo ln -sf /etc/nginx/sites-available/leograf-bot /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

echo "=== Criando servico systemd ==="
sudo tee /etc/systemd/system/leograf-bot.service > /dev/null <<'SERVICE'
[Unit]
Description=Leograf Orcamentos Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/leograf-bot
EnvironmentFile=/opt/leograf-bot/.env
ExecStart=/opt/leograf-bot/venv/bin/gunicorn --bind 127.0.0.1:5000 --workers 2 --timeout 120 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

sudo systemctl daemon-reload
sudo systemctl enable leograf-bot

echo "=== Setup concluido! ==="
echo "Proximo passo: copie app.py e .env para /opt/leograf-bot/ e rode:"
echo "  sudo systemctl start leograf-bot"
