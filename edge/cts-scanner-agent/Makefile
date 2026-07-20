# CTS Scanner Bridge — Build Targets
#
# Two build modes:
#
# build-windows-stub  (cross-compile from any host):
#   Produces a Windows .exe using the StubTransport (no Ranger SDK required).
#   The stub transport is activated by the build constraint: !windows || !cgo
#   Use this in CI to verify the binary compiles for Windows without a
#   physical Canon Ranger SDK.
#
# build-windows-native  (must run ON a Windows build host with Ranger SDK):
#   CGO_ENABLED=1 activates ranger_windows.go (build tag: windows && cgo),
#   which calls the real Canon Ranger COM SDK via CGo.
#   Requires: Canon Ranger SDK headers + .lib in include/lib paths,
#   and a C compiler (MSVC or MinGW-w64) in PATH.
#   Run this target on the teller-PC build agent or Windows CI runner.
#
# Typical deployment flow:
#   Developer machine (Linux/Mac):  make build-windows-stub  → smoke-test exe shape
#   Bank Windows build server:       make build-windows-native → production exe

.PHONY: build build-windows-stub build-windows-native test lint clean

BINARY     := cts-scanner-bridge
LDFLAGS    := -ldflags="-w -s"
WIN_BINARY := $(BINARY).exe

## ── Local (non-Windows) development build with stub transport ────────────────
build:
	go build $(LDFLAGS) -o $(BINARY) .

## ── CI: cross-compile to Windows .exe, stub transport (no CGO) ──────────────
build-windows-stub:
	CGO_ENABLED=0 GOOS=windows GOARCH=amd64 \
		go build $(LDFLAGS) -o $(WIN_BINARY) .
	@echo "✓ $(WIN_BINARY) built with StubTransport (no Ranger SDK)"

## ── Production: native Windows build with real Canon Ranger COM SDK ──────────
## Run this target on a Windows host with Canon Ranger SDK installed.
## Environment variables expected:
##   CGO_CFLAGS  = -I"C:/Program Files/Canon/Ranger SDK/include"
##   CGO_LDFLAGS = -L"C:/Program Files/Canon/Ranger SDK/lib" -lRanger
build-windows-native:
	CGO_ENABLED=1 GOOS=windows GOARCH=amd64 \
		go build $(LDFLAGS) -o $(WIN_BINARY) .
	@echo "✓ $(WIN_BINARY) built with real Canon Ranger COM SDK"

## ── Tests (all platforms) ────────────────────────────────────────────────────
test:
	go test ./... -v -count=1

## ── Lint ─────────────────────────────────────────────────────────────────────
lint:
	golangci-lint run ./...

## ── Clean ────────────────────────────────────────────────────────────────────
clean:
	rm -f $(BINARY) $(WIN_BINARY)
