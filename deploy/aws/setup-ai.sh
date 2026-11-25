#!/usr/bin/env bash
# Cai rag-api len Ubuntu 24.04/26.04 (EC2), Python 3.12 qua uv. Dung: sudo bash setup-ai.sh <ten-mien>
set -euo pipefail
HOST="${1:?Dung: sudo bash setup-ai.sh <ten-mien>   vi du ai.fet3d.io.vn hoac 13-229-10-20.sslip.io}"
APP=/opt/fire3d-ai
SRC=/home/ubuntu

echo "== 1/6 Cai goi he thong"
# Mirror dang dong bo co the bao loi vai file index -> khong dung lai vi chuyen do
apt-get update -q || echo "(canh bao: apt update loi mot phan, van tiep tuc)"
apt-get install -y -q unzip curl gnupg ca-certificates
# uv: tai Python 3.12 rieng, khong phu thuoc Python cua he dieu hanh
export UV_PYTHON_INSTALL_DIR=/opt/uv-python
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh

echo "== 2/6 Cai Caddy (HTTPS tu dong)"
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' -o /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q || true
  apt-get install -y -q caddy
fi

echo "== 3/6 Chep code va env"
id fire3d >/dev/null 2>&1 || useradd --system --home-dir "$APP" --shell /usr/sbin/nologin fire3d
mkdir -p "$APP/data"
unzip -oq "$SRC/rag-api-deploy.zip" -d "$APP"
install -m 600 "$SRC/rag-api-server.env" "$APP/.env"

echo "== 4/6 Cai thu vien Python (vai phut)"
[ -x "$APP/.venv/bin/python" ] || uv venv --python 3.12 "$APP/.venv"
uv pip install -q --python "$APP/.venv/bin/python" -r "$APP/requirements.txt"
chmod -R a+rX /opt/uv-python
chown -R fire3d:fire3d "$APP"

# Swap 2 GB: model embedding cuc bo (~0,5 GB RAM) chay cung uvicorn tren may 2 GB
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
# EMBED_PROVIDER=local: tai model truoc (~130 MB) de cau hoi dau tien khong phai cho tai
if grep -q '^EMBED_PROVIDER=local' "$APP/.env"; then
  echo "   tai model embedding cuc bo"
  MODEL_DIR="$(sed -n 's/^LOCAL_MODEL_DIR=//p' "$APP/.env")"
  (cd "$APP" && sudo -u fire3d HF_HUB_DISABLE_PROGRESS_BARS=1 "$APP/.venv/bin/python" -c \
    "import sys; from app.llm.local_embedding import load_model; load_model(sys.argv[1])" "${MODEL_DIR:-data/models}")
fi

echo "== 5/6 Tao service, lich housekeeping, Caddy"
cat > /etc/systemd/system/fire3d-ai.service <<EOF
[Unit]
Description=Fire3D AI rag-api
After=network-online.target
Wants=network-online.target

[Service]
User=fire3d
WorkingDirectory=$APP
EnvironmentFile=$APP/.env
ExecStart=$APP/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/fire3d-ai-housekeeping.service <<EOF
[Unit]
Description=Fire3D AI knowledge housekeeping

[Service]
Type=oneshot
User=fire3d
WorkingDirectory=$APP
EnvironmentFile=$APP/.env
ExecStart=$APP/.venv/bin/python -m app.index.housekeeping
EOF

cat > /etc/systemd/system/fire3d-ai-housekeeping.timer <<EOF
[Unit]
Description=Fire3D AI housekeeping hang ngay

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Tai lieu knowledge source (PDF/MD/TXT) dat o /var/www/fire3d-kb, AI tai lai qua https://$HOST/kb/<ten-file>
mkdir -p /var/www/fire3d-kb
chmod 755 /var/www/fire3d-kb
cat > /etc/caddy/Caddyfile <<EOF
$HOST {
    handle_path /kb/* {
        root * /var/www/fire3d-kb
        file_server
    }
    handle {
        reverse_proxy 127.0.0.1:8000
    }
}
EOF

systemctl daemon-reload
systemctl enable --now fire3d-ai.service fire3d-ai-housekeeping.timer
systemctl restart fire3d-ai.service
systemctl restart caddy

echo "== 6/6 Kiem tra"
for i in $(seq 1 30); do
  if curl -fs http://127.0.0.1:8000/health >/dev/null; then break; fi
  sleep 2
done
echo "health: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)"
echo "ready : $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/ready)  ($(curl -s http://127.0.0.1:8000/ready))"
echo "Xong. Thu tu may ban: https://$HOST/health va https://$HOST/ready"
echo "Log: sudo journalctl -u fire3d-ai -n 100 --no-pager   |   sudo journalctl -u caddy -n 50 --no-pager"
