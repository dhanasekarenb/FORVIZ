#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="forviz.service"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}"
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROBOT_USER="$(id -un)"
PYTHON_BIN="$(command -v python3)"

install_service() {
    local temp_file
    temp_file="$(mktemp)"
    trap 'rm -f -- "$temp_file"' RETURN

    cat >"$temp_file" <<EOF
[Unit]
Description=FORVIZ face-tracking robot
After=pigpiod.service

[Service]
Type=simple
User=${ROBOT_USER}
WorkingDirectory=${PROJECT_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${PYTHON_BIN} ${PROJECT_DIR}/pi_tracker.py --mirror-eye --headless --gain-tilt 60
Restart=on-failure
RestartSec=3
KillSignal=SIGINT
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
EOF

    sudo install -m 0644 "$temp_file" "$SERVICE_FILE"
    sudo systemctl daemon-reload
    sudo systemctl enable --now "$SERVICE_NAME"
    echo "FORVIZ now starts automatically at boot."
    echo "View it with: bash robot_service.sh status"
}

case "${1:-status}" in
    install)
        install_service
        ;;
    start|stop|restart|status)
        sudo systemctl "$1" "$SERVICE_NAME"
        ;;
    logs)
        sudo journalctl -u "$SERVICE_NAME" -f
        ;;
    disable)
        sudo systemctl disable --now "$SERVICE_NAME"
        echo "Automatic startup disabled; the service file is still installed."
        ;;
    enable)
        sudo systemctl enable --now "$SERVICE_NAME"
        ;;
    remove)
        sudo systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
        sudo rm -f -- "$SERVICE_FILE"
        sudo systemctl daemon-reload
        echo "FORVIZ automatic startup removed."
        ;;
    *)
        echo "Usage: bash robot_service.sh {install|start|stop|restart|status|logs|disable|enable|remove}" >&2
        exit 2
        ;;
esac
