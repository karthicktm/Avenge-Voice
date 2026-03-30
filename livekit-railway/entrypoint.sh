#!/bin/sh
set -e

# Extract components from REDIS_URL (redis://user:pass@host:port)
if [ -n "$REDIS_URL" ]; then
  _no_scheme="${REDIS_URL#redis://}"
  LK_REDIS_ADDR="${_no_scheme##*@}"
  _userinfo="${_no_scheme%@*}"
  LK_REDIS_USER="${_userinfo%%:*}"
  LK_REDIS_PASS="${_userinfo#*:}"
else
  LK_REDIS_ADDR="${REDIS_HOST:-redis.railway.internal}:${REDIS_PORT:-6379}"
  LK_REDIS_USER="${REDIS_USERNAME:-default}"
  LK_REDIS_PASS="${REDIS_PASSWORD:-}"
fi

# Unset Railway-injected Redis env vars so livekit-server uses only the YAML config
unset REDIS_HOST REDIS_PORT REDIS_URL REDIS_PASSWORD REDIS_USERNAME

cat > /etc/livekit.yaml << LIVEKIT_YAML
port: ${PORT:-7880}
bind_addresses:
  - ""
rtc:
  tcp_port: 7881
  use_external_ip: true
redis:
  address: ${LK_REDIS_ADDR}
  username: ${LK_REDIS_USER}
  password: "${LK_REDIS_PASS}"
keys:
  ${LIVEKIT_API_KEY}: ${LIVEKIT_API_SECRET}
logging:
  json: true
  level: info
LIVEKIT_YAML

exec /livekit-server --config /etc/livekit.yaml
