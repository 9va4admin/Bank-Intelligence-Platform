# Multi-stage build — final image is scratch (no OS, no shell, no attack surface).
# CGO_ENABLED=0 ensures pure-Go binary (modernc.org/sqlite is pure Go).

FROM golang:1.22-alpine AS builder
WORKDIR /build

# Download dependencies before copying source — Docker layer cache benefits.
COPY go.mod go.sum ./
RUN go mod download

COPY . .

ARG VERSION=dev
ARG GIT_SHA=unknown

RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build \
    -ldflags="-w -s -X main.version=${VERSION} -X main.gitSHA=${GIT_SHA}" \
    -o ej-agent \
    .

# Verify the binary is statically linked (no shared libs — scratch base requires this).
RUN file ej-agent | grep -q "statically linked"

# ── Runtime image — scratch base ─────────────────────────────────────────────
FROM scratch

# CA certificates for mTLS to central (scratch has none by default).
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/

# The binary only.
COPY --from=builder /build/ej-agent /ej-agent

# Non-root UID 1000 (cannot use RUN useradd in scratch — set numerically).
USER 1000:1000

# MCP server port — bank firewall must allow inbound from ASTRA support workstation.
EXPOSE 8443

# Health check via MCP server liveness endpoint.
# Note: scratch has no curl/wget — health check uses the binary's own probe flag.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD ["/ej-agent", "-health-check"]

ENTRYPOINT ["/ej-agent"]
