#!/bin/bash
# Deploy systemd timer for 4 AM IST (22:30 UTC) daily data pipeline
# Run on EC2: sudo bash scripts/setup_cron.sh

set -e

APP_DIR="/home/ubuntu/ArthaSamriddhiAI"
VENV="${APP_DIR}/.venv/bin"
DB_PATH="${APP_DIR}/artha.db"

# Service
cat > /etc/systemd/system/artha-pipeline.service << EOF
[Unit]
Description=ArthaSamriddhiAI Daily Data Pipeline
After=network.target

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=${APP_DIR}
ExecStart=/bin/bash -c "${VENV}/python scripts/run_pipeline.py --all --db-url sqlite+aiosqlite:///${DB_PATH} && ${VENV}/python scripts/refresh_cache.py ${DB_PATH}"
Environment=PATH=${VENV}:/usr/bin
StandardOutput=journal
StandardError=journal
TimeoutStartSec=1800
EOF

# Timer — 4 AM IST = 22:30 UTC
cat > /etc/systemd/system/artha-pipeline.timer << EOF
[Unit]
Description=Run ArthaSamriddhiAI data pipeline daily at 4 AM IST

[Timer]
OnCalendar=*-*-* 22:30:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable artha-pipeline.timer
systemctl start artha-pipeline.timer

echo "Timer installed. Next run:"
systemctl list-timers artha-pipeline.timer --no-pager
