#!/bin/bash
# カメラサーバー systemd サービスのインストール/アンインストールスクリプト
set -euo pipefail

SERVICE_NAME="camera-server"
SERVICE_FILE="$(cd "$(dirname "$0")" && pwd)/${SERVICE_NAME}.service"
DEST="/etc/systemd/system/${SERVICE_NAME}.service"

usage() {
    echo "Usage: $0 {install|uninstall|status}"
    exit 1
}

install_service() {
    echo "==> サービスをインストールします..."
    sudo cp "$SERVICE_FILE" "$DEST"
    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_NAME"
    sudo systemctl start "$SERVICE_NAME"
    echo "==> 完了！ステータスを確認します..."
    sudo systemctl status "$SERVICE_NAME" --no-pager
}

uninstall_service() {
    echo "==> サービスをアンインストールします..."
    sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    sudo rm -f "$DEST"
    sudo systemctl daemon-reload
    echo "==> アンインストール完了"
}

show_status() {
    sudo systemctl status "$SERVICE_NAME" --no-pager
}

case "${1:-}" in
    install)   install_service ;;
    uninstall) uninstall_service ;;
    status)    show_status ;;
    *)         usage ;;
esac
