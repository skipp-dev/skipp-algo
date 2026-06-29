FROM grafana/alloy:v1.17.0

COPY config.alloy /etc/alloy/config.alloy

ENTRYPOINT ["sh", "-c", "exec alloy run --server.http.listen-addr=0.0.0.0:${PORT:-12345} /etc/alloy/config.alloy"]
