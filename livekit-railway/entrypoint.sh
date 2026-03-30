#!/bin/sh
set -e

# Extract components from REDIS_URL (redis://user:pass@host:port)
if [ -n "$REDIS_URL" ]; then
  _no_scheme="${REDIS_URL#redis://}"
  REDIS_ADDR="${_no_scheme##*@}"
  _userinfo="${_no_scheme%@*}"
  REDIS_USERNAME="${_userinfo%%:*}"
  REDIS_PASSWORD="${_userinfo#*:}"
else
  REDIS_ADDR="${REDIS_HOST:-redis.railway.internal}:${REDIS_PORT:-6379}"
  REDIS_USERNAME="${REDIS_USERNAME:-default}"
  REDIS_PASSWORD="${REDIS_PASSWORD:-}"
fi

cat > /etc/livekit.yaml << LIVEKIT_YAML
port: ${PORT:-7880}
bind_addresses:
  - ""
rtc:
  tcp_port: 7881
  use_external_ip: true
redis:
  address: ${REDIS_ADDR}
  username: ${REDIS_USERNAME}
  password: "${REDIS_PASSWORD}"
keys:
  ${LIVEKIT_API_KEY}: ${LIVEKIT_API_SECRET}
logging:
  json: true
  level: info
LIVEKIT_YAML

exec /livekit-server --config /etc/livekit.yaml
