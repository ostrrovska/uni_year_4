#!/bin/sh
# Lab3
# Compose the live upstream from one algorithm fragment and one pool fragment.
#
# The algorithm and the pool size vary independently (algorithm comparison vs scale-out
# experiment), so they are separate files instead of a 4x3 matrix. Sources are read-only bind
# mounts; the generated targets live in the image's own writable /etc/nginx.
#
#   sh /usr/local/bin/lb-switch [algorithm] [pool-size]
set -eu

ALG="${1:-${LB_ALGORITHM:-round-robin}}"
POOL="${2:-${LB_POOL_SIZE:-3}}"

ALG_SRC="/etc/nginx/algorithms/${ALG}.conf"
POOL_SRC="/etc/nginx/pools/${POOL}.conf"

if [ ! -f "$ALG_SRC" ]; then
    echo "unknown algorithm: ${ALG}" >&2
    exit 1
fi
if [ ! -f "$POOL_SRC" ]; then
    echo "unknown pool size: ${POOL}" >&2
    exit 1
fi

cp "$POOL_SRC" /etc/nginx/pool.conf
cp "$ALG_SRC" /etc/nginx/upstream.conf
# pool is quoted: it is a fragment name, not always a number ("3-aggressive").
printf '{"balancer":"nginx","algorithm":"%s","pool":"%s","changed_at":"%s"}\n' \
    "$ALG" "$POOL" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > /etc/nginx/lb-status.json

# Validate first: a reload with a broken config is a no-op on a running master (the old
# workers keep serving), so validating turns a silent non-switch into a visible error.
nginx -t

# -s, not -f: the image ships an empty /var/run/nginx.pid, so testing for existence alone
# would attempt a reload with no master running and fail with "invalid PID number".
if [ -s /var/run/nginx.pid ]; then
    # Graceful: new workers start on the new config, old workers finish their in-flight
    # requests before exiting. No connection is dropped.
    nginx -s reload
    echo "switched to ${ALG} (pool=${POOL}) and reloaded"
else
    echo "prepared ${ALG} (pool=${POOL}); nginx has not started yet"
fi
