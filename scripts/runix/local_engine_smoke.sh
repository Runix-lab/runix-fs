#!/usr/bin/env bash
set -euo pipefail
cd /smoke
export CURVINE_MASTER_HOSTNAME=127.0.0.1
export CURVINE_WORKER_HOSTNAME=127.0.0.1
export CURVINE_JOURNAL_HOSTNAME=127.0.0.1
export CURVINE_CLIENT_HOSTNAME=127.0.0.1
mkdir -p data logs
cat > cluster.toml <<'TOML'
format_master = false
format_worker = false
cluster_id = "runix-local-synthetic-smoke"
[master]
hostname = "127.0.0.1"
rpc_port = 8995
web_port = 9001
meta_dir = "/smoke/data/meta"
log = { level = "info", log_dir = "/smoke/logs", file_name = "master.log" }
[journal]
hostname = "127.0.0.1"
rpc_port = 8996
journal_addrs = [{id = 1, hostname = "127.0.0.1", port = 8996}]
journal_dir = "/smoke/data/journal"
[worker]
hostname = "127.0.0.1"
rpc_port = 8997
web_port = 9002
dir_reserved = "0"
data_dir = ["[DISK]/smoke/data/worker"]
log = { level = "info", log_dir = "/smoke/logs", file_name = "worker.log" }
[client]
hostname = "127.0.0.1"
master_addrs = [{hostname = "127.0.0.1", port = 8995}]
replicas = 1
[log]
level = "error"
log_dir = "/smoke/logs"
file_name = "client.log"
TOML
master_pid=""
worker_pid=""
cleanup() {
    if [[ -n "$worker_pid" ]]; then kill "$worker_pid" 2>/dev/null || true; fi
    if [[ -n "$master_pid" ]]; then kill "$master_pid" 2>/dev/null || true; fi
}
trap cleanup EXIT
start_services() {
    /build/target/debug/curvine-server --service master --conf /smoke/cluster.toml >> master.out 2>&1 &
    master_pid=$!
    /build/target/debug/curvine-server --service worker --conf /smoke/cluster.toml >> worker.out 2>&1 &
    worker_pid=$!
}
cli() { timeout 20 /build/target/debug/curvine-cli --conf /smoke/cluster.toml fs "$@"; }
ready() {
    for attempt in $(seq 1 40); do
        if ! kill -0 "$master_pid" || ! kill -0 "$worker_pid"; then
            tail -n 35 master.out worker.out
            return 1
        fi
        if timeout 20 /build/target/debug/curvine-cli --conf /smoke/cluster.toml report json > report.json 2>> readiness.out &&
            python3 -c 'import json; assert json.load(open("report.json"))["available"] > 8388608' 2>> readiness.out; then
            cli mkdir /synthetic >> readiness.out 2>&1
            return 0
        fi
        sleep 2
    done
    tail -n 35 readiness.out master.out worker.out
    return 1
}
start_services
ready
dd if=/dev/urandom of=payload.bin bs=1048576 count=4 status=none
sha256sum payload.bin
cli put /smoke/payload.bin /synthetic/payload.bin
cli get /synthetic/payload.bin /smoke/read-before.bin
cmp payload.bin read-before.bin
echo 'PASS: CLI write and read, 4194304 bytes'
kill -KILL "$worker_pid" "$master_pid"
wait "$worker_pid" 2>/dev/null || true
wait "$master_pid" 2>/dev/null || true
start_services
for attempt in $(seq 1 40); do
    if cli get /synthetic/payload.bin /smoke/read-after.bin >> recovery.out 2>&1; then
        cmp payload.bin read-after.bin
        sha256sum read-before.bin read-after.bin
        echo 'PASS: simultaneous master/worker process-crash recovery'
        exit 0
    fi
    sleep 2
done
tail -n 35 recovery.out master.out worker.out
exit 1
