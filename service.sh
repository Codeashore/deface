#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"
mkdir -p .runtime
exec 9>.runtime/service.lock
flock -n 9 || { echo "另一个服务管理命令正在执行。"; exit 1; }

pid_file=.runtime/service.pid
log_file=.runtime/service.log
action=${1:-help}
if (( $# )); then shift; fi
port=9000
web=false

usage() {
    echo "用法: $0 start [--port 9000] [--web] | stop | status"
    echo "默认只启动 API；--web 同时开启网页。日志: .runtime/service.log"
}

while (( $# )); do
    case "$1" in
        --web) web=true; shift ;;
        --port)
            if (( $# < 2 )) || [[ ! $2 =~ ^[0-9]{1,5}$ ]] || (( 10#$2 < 1 || 10#$2 > 65535 )); then
                echo "端口必须是 1–65535 的整数。"; exit 1
            fi
            port=$((10#$2)); shift 2 ;;
        *) usage; exit 1 ;;
    esac
done

running() {
    [[ -f $pid_file ]] || return 1
    read -r pid < "$pid_file"
    [[ $pid =~ ^[0-9]+$ ]] || return 1
    # Verify the command as well as the PID before sending any signal.
    [[ $(ps -p "$pid" -o args=) == *"uv run --no-sync uvicorn deface."* ]]
}

case "$action" in
    start)
        if running; then
            echo "服务已运行，PID: $pid。修改参数请先 stop。"; exit 0
        fi
        rm -f "$pid_file"
        command -v uv >/dev/null
        command -v setsid >/dev/null
        command -v curl >/dev/null
        sync_args=()
        run_args=(deface.api:app)
        if $web; then
            sync_args=(--group web)
            run_args=(deface.web:create_app --factory)
            export GRADIO_TEMP_DIR=${GRADIO_TEMP_DIR:-"$PWD/.runtime/gradio"}
            mkdir -p "$GRADIO_TEMP_DIR"
        fi
        uv sync "${sync_args[@]}"
        # Fail early if another service is already listening on this port.
        .venv/bin/python - "$port" <<'PY'
import socket
import sys

with socket.socket() as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", int(sys.argv[1])))
PY
        nohup setsid uv run --no-sync uvicorn "${run_args[@]}" --host 0.0.0.0 --port "$port" \
            > "$log_file" 2>&1 < /dev/null 9>&- &
        pid=$!
        echo "$pid" > "$pid_file"
        for ((attempt = 0; attempt < 30; attempt++)); do
            sleep 1
            if ! running; then
                rm -f "$pid_file"
                echo "启动失败，日志如下："; tail -n 30 "$log_file"; exit 1
            fi
            if curl --noproxy '*' -fsS --max-time 1 "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
                echo "服务已启动，PID: $pid，端口: $port，Web: $web"
                echo "接口文档: http://服务器IP:$port/docs；日志: $PWD/$log_file"
                exit 0
            fi
        done
        echo "服务仍在启动，PID: $pid。请检查 $log_file。"; exit 1
        ;;
    stop)
        if ! running; then
            rm -f "$pid_file"
            echo "服务未运行。"; exit 0
        fi
        # Stop uv and its Uvicorn child together, allowing graceful shutdown.
        kill -TERM -- "-$pid"
        for ((attempt = 0; attempt < 30; attempt++)); do
            if ! running; then
                rm -f "$pid_file"
                echo "服务已停止。"; exit 0
            fi
            sleep 1
        done
        echo "服务尚未退出，请检查 $log_file 后重试。"; exit 1
        ;;
    status)
        if running; then
            echo "服务正在运行，PID: $pid"
            ps -p "$pid" -o args=
        else
            echo "服务未运行。"; exit 1
        fi
        ;;
    help|-h|--help) usage ;;
    *) usage; exit 1 ;;
esac
