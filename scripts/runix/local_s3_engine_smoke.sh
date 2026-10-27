#!/usr/bin/env bash
set -euo pipefail
cd /smoke
export CURVINE_MASTER_HOSTNAME=127.0.0.1
export CURVINE_WORKER_HOSTNAME=127.0.0.1
export CURVINE_JOURNAL_HOSTNAME=127.0.0.1
export CURVINE_CLIENT_HOSTNAME=127.0.0.1
if [[ -e cluster.toml || -e data ]]; then
    echo 'Fresh synthetic runtime directory required' >&2
    exit 2
fi
mkdir -p data logs
cat > cluster.toml <<'TOML'
format_master = false
format_worker = false
cluster_id = "runix-local-s3-synthetic-smoke"
[master]
hostname = "127.0.0.1"
rpc_port = 8995
web_port = 9001
meta_dir = "/smoke/data/meta"
log = { level = "info", log_dir = "/smoke/logs", file_name = "master.log" }
[master.rocksdb]
disable_wal = false
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
master_pid=''
worker_pid=''
cleanup() {
    if [[ -n "$worker_pid" ]]; then kill "$worker_pid" 2>/dev/null || true; fi
    if [[ -n "$master_pid" ]]; then kill "$master_pid" 2>/dev/null || true; fi
}
trap cleanup EXIT
start() {
    /build/target/debug/curvine-server --service master --conf /smoke/cluster.toml >> master.out 2>&1 &
    master_pid=$!
    /build/target/debug/curvine-server --service worker --conf /smoke/cluster.toml >> worker.out 2>&1 &
    worker_pid=$!
}
cv() { timeout 30 /build/target/debug/curvine-cli --conf /smoke/cluster.toml "$@"; }
ready() {
    for attempt in $(seq 1 40); do
        if ! kill -0 "$master_pid" || ! kill -0 "$worker_pid"; then
            echo 'Engine exited before readiness' >&2
            return 1
        fi
        if cv report json > report.json 2>> readiness.out &&
            python3 -c 'import json; assert json.load(open("report.json"))["available"] > 8388608' 2>> readiness.out; then
            return 0
        fi
        sleep 1
    done
    echo 'Engine readiness timeout' >&2
    return 1
}
sha256sum /build/target/debug/curvine-server /build/target/debug/curvine-cli > binary-hashes.txt
start
ready
# CLI output is kept private: mount configuration contains fixture credentials.
cv mount s3://runix-synthetic-smoke /runix-synthetic-smoke \
    --write-type cache_mode --access-mode read_write --read-verify-ufs \
    -c s3.endpoint_url=http://objectstore:9000 -c s3.region_name=us-east-1 \
    -c "s3.credentials.access=$AWS_ACCESS_KEY_ID" \
    -c "s3.credentials.secret=$AWS_SECRET_ACCESS_KEY" \
    -c s3.force.path.style=true > mount.out 2>&1
cv fs get /runix-synthetic-smoke/source.bin /smoke/read-before.bin >> operations.out 2>&1
cmp source.bin read-before.bin
echo 'PASS: real engine read of independently seeded S3-compatible object'
cv fs put /smoke/upload.bin /runix-synthetic-smoke/upload.bin >> operations.out 2>&1
kill -KILL "$worker_pid" "$master_pid"
wait "$worker_pid" 2>/dev/null || true
wait "$master_pid" 2>/dev/null || true
start
ready
cv fs get /runix-synthetic-smoke/source.bin /smoke/read-after.bin >> operations.out 2>&1
cv fs get /runix-synthetic-smoke/upload.bin /smoke/upload-after.bin >> operations.out 2>&1
cmp source.bin read-after.bin
cmp upload.bin upload-after.bin
echo 'PASS: S3-compatible mount and both payloads survive master/worker process restart'
