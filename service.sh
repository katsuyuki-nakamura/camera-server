#!/bin/bash
# カメラサーバー systemd サービスのインストール/アンインストールスクリプト
set -euo pipefail

SERVICE_NAME="camera-server"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_FILE="${SCRIPT_DIR}/${SERVICE_NAME}.service"
UDEV_RULES_FILE="${SCRIPT_DIR}/99-camera-server.rules"
DEST="/etc/systemd/system/${SERVICE_NAME}.service"
UDEV_DEST="/etc/udev/rules.d/99-camera-server.rules"

usage() {
    echo "Usage: $0 {install|uninstall|status}"
    exit 1
}

install_udev_rules() {
    if [[ -f "$UDEV_RULES_FILE" ]]; then
        echo "==> udev ルールをインストールします..."
        sudo cp "$UDEV_RULES_FILE" "$UDEV_DEST"
        sudo udevadm control --reload-rules
        sudo udevadm trigger --subsystem-match=video4linux
        echo "==> udev ルールを反映しました"
    fi
}

uninstall_udev_rules() {
    if [[ -f "$UDEV_DEST" ]]; then
        echo "==> udev ルールを削除します..."
        sudo rm -f "$UDEV_DEST"
        sudo udevadm control --reload-rules
        echo "==> udev ルールを削除しました"
    fi
}

install_service() {
    install_udev_rules
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
    uninstall_udev_rules
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
