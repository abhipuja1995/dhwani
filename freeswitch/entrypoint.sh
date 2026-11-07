#!/bin/sh
set -e

CERT_DIR=/etc/freeswitch/tls

# Generate self-signed TLS cert for WSS if not present
if [ ! -f "$CERT_DIR/wss.pem" ] && command -v openssl >/dev/null 2>&1; then
  mkdir -p "$CERT_DIR"
  openssl req -x509 -newkey rsa:4096 -keyout "$CERT_DIR/wss.key" \
    -out "$CERT_DIR/wss.crt" -days 3650 -nodes \
    -subj "/CN=${FS_DOMAIN:-localhost}" \
    -addext "subjectAltName=DNS:${FS_DOMAIN:-localhost},IP:127.0.0.1" 2>/dev/null
  cat "$CERT_DIR/wss.crt" "$CERT_DIR/wss.key" > "$CERT_DIR/wss.pem"
  cp "$CERT_DIR/wss.pem" "$CERT_DIR/agent.pem"
  cp "$CERT_DIR/wss.crt" "$CERT_DIR/cafile.pem"
  echo "[entrypoint] TLS cert generated for ${FS_DOMAIN:-localhost}"
elif [ ! -f "$CERT_DIR/wss.pem" ]; then
  echo "[entrypoint] openssl not available; skipping TLS cert generation"
fi

exec "$@"
