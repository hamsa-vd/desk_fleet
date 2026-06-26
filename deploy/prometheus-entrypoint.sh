#!/bin/sh
# Prometheus does not expand environment variables in its config, so remote_write is appended
# here — and only when all three Grafana Cloud variables are present. With them unset the stack
# runs exactly as before, which is the point: push is for the deployed service, where
# --min-instances 0 means there is nothing to scrape.
set -eu

SOURCE=${PROMETHEUS_CONFIG_SOURCE:-/etc/prometheus/prometheus.yml}
TARGET=${PROMETHEUS_CONFIG_TARGET:-/tmp/prometheus.yml}

cp "$SOURCE" "$TARGET"

if [ -n "${GRAFANA_CLOUD_PROM_URL:-}" ] &&
    [ -n "${GRAFANA_CLOUD_PROM_USER:-}" ] &&
    [ -n "${GRAFANA_CLOUD_PROM_KEY:-}" ]; then
    cat >>"$TARGET" <<EOF

remote_write:
  - url: ${GRAFANA_CLOUD_PROM_URL}
    basic_auth:
      username: "${GRAFANA_CLOUD_PROM_USER}"
      password: "${GRAFANA_CLOUD_PROM_KEY}"
EOF
    echo "remote_write enabled -> ${GRAFANA_CLOUD_PROM_URL}"
else
    echo "remote_write disabled (GRAFANA_CLOUD_* not fully set)"
fi

exec "${PROMETHEUS_BINARY:-/bin/prometheus}" \
    --config.file="$TARGET" \
    --storage.tsdb.path=/prometheus \
    --web.enable-lifecycle \
    "$@"
