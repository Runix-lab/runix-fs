#!/usr/bin/env bash
set -euo pipefail
cd /smoke
for required in cluster.toml data/meta data/journal data/worker source.bin upload.bin; do
    if [[ ! -e "$required" ]]; then
        echo 'Incomplete stopped-state backup' >&2
        exit 2
    fi
done
export CURVINE_MASTER_HOSTNAME=127.0.0.1
export CURVINE_WORKER_HOSTNAME=127.0.0.1
export CURVINE_JOURNAL_HOSTNAME=127.0.0.1
export CURVINE_CLIENT_HOSTNAME=127.0.0.1
mkdir -p logs
master_pid=''
worker_pid=''
cleanup() {
    if [[ -n "$worker_pid" ]]; then kill "$worker_pid" 2>/dev/null || true; fi
    if [[ -n "$master_pid" ]]; then kill "$master_pid" 2>/dev/null || true; fi
}
trap cleanup EXIT
sha256sum /build/target/debug/curvine-server /build/target/debug/curvine-cli > binary-hashes.txt
/build/target/debug/curvine-server --service master --conf /smoke/cluster.toml > master.out 2>&1 &
master_pid=$!
/build/target/debug/curvine-server --service worker --conf /smoke/cluster.toml > worker.out 2>&1 &
worker_pid=$!
cv() { timeout 30 /build/target/debug/curvine-cli --conf /smoke/cluster.toml "$@"; }
ready=false
for attempt in $(seq 1 40); do
    if ! kill -0 "$master_pid" || ! kill -0 "$worker_pid"; then
        echo 'Restored engine exited before readiness' >&2
        exit 1
    fi
    if cv report json > report.json 2>> readiness.out &&
        python3 -c 'import json; assert json.load(open("report.json"))["available"] > 8388608' 2>> readiness.out; then
        ready=true
        break
    fi
    sleep 1
done
if [[ "$ready" != true ]]; then
    echo 'Restored engine readiness timeout' >&2
    exit 1
fi
cv fs get /runix-synthetic-smoke/source.bin /smoke/restored-source.bin >> operations.out 2>&1
cv fs get /runix-synthetic-smoke/upload.bin /smoke/restored-upload.bin >> operations.out 2>&1
cmp source.bin restored-source.bin
cmp upload.bin restored-upload.bin
echo 'PASS: restored metadata, journal and data read both existing payloads'
dd if=/dev/urandom of=new.bin bs=1048576 count=4 status=none
cv fs put /smoke/new.bin /runix-synthetic-smoke/restored-new.bin >> operations.out 2>&1
cv fs get /runix-synthetic-smoke/restored-new.bin /smoke/new-read.bin >> operations.out 2>&1
cmp new.bin new-read.bin
echo 'PASS: fresh write/read through the restored engine'
