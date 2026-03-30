#!/bin/sh
set -e

cat > /etc/livekit.yaml << EOF
port: ${PORT:-7880}
bind_addresses:
  - ""
rtc:
  tcp_port: 7881
  use_external_ip: true
redis:
  address: ${REDIS_HOST:-redis.railway.internal}:${REDIS_PORT:-6379}
  password: "${REDIS_PASSWORD}"
keys:
  ${LIVEKIT_API_KEY}: ${LIVEKIT_API_SECRET}
logging:
  json: true
  level: info
EOF

exec livekit-server --config /etc/livekit.yaml
