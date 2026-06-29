FROM grafana/alloy:v1.17.0

COPY config.alloy /etc/alloy/config.alloy

ENTRYPOINT ["sh", "-c", "PORT=\"${PORT:-12345}\"; export PORT; ALLOY_SELF_ADDRESS=\"${ALLOY_SELF_ADDRESS:-127.0.0.1:${PORT}}\"; export ALLOY_SELF_ADDRESS; exec alloy run --server.http.listen-addr=0.0.0.0:${PORT} /etc/alloy/config.alloy"]
