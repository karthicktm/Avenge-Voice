#!/bin/sh
set -e

# Parse REDIS_URL if provided (redis://user:pass@host:port)
if [ -n "$REDIS_URL" ]; then
  # Strip scheme
  _rest="${REDIS_URL#redis://}"
  # Extract userinfo (before @)
  _userinfo="${_rest%@*}"
  # Extract host:port (after @)
  _hostport="${_rest##*@}"
  # Extract username and password
  REDIS_USERNAME="${_userinfo%%:*}"
  REDIS_PASSWORD="${_userinfo#*:}"
  REDIS_ADDR="$_hostport"
else
  REDIS_ADDR="${REDIS_HOST:-redis.railway.internal}:6379"
  REDIS_USERNAME="${REDIS_USERNAME:-default}"
fi

cat > /etc/livekit.yaml << EOF
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
EOF

exec /livekit-server --config /etc/livekit.yaml
