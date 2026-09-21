#!/bin/sh
# SIM-0003: exits 4-7 are deliberate halts — replay miss, run cap, model
# never came back, model version drift — not crashes. Fly restarts non-zero
# exits (its on-fail policy), so a halt left as non-zero would restart-loop
# and spend a call each time finding the drift again. Map them to a clean
# exit; the machine stays stopped until an operator redeploys. Anything else
# (a crash, exit 1) keeps its code and still comes back.
#
# SIGTERM has to reach python — the daemon's contract is "finish the tick",
# and a `sh -c` parent would eat the signal — so it runs in the background
# and the trap forwards, rather than `exec` (which would keep the signal
# path but lose the exit code to us).

python -m jeve.sim "$@" &
pid=$!
trap 'kill -TERM "$pid"' TERM
trap 'kill -INT "$pid"' INT

# `wait` returns 128+SIG when the trap fires, while the child is still
# finishing its tick — keep waiting for the real exit code.
wait "$pid"
code=$?
while [ "$code" -gt 128 ]; do
    wait "$pid"
    code=$?
done

if [ "$code" -ge 4 ] && [ "$code" -le 7 ]; then
    echo "sim-entrypoint: deliberate halt (exit $code) — staying stopped" >&2
    exit 0
fi
exit "$code"
