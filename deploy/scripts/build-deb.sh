#!/usr/bin/env bash
# Build a .deb for the Linux agent. Runs on Linux/CI (needs dpkg-deb).
# Usage: VERSION=0.3.0 deploy/scripts/build-deb.sh
set -euo pipefail

VERSION="${VERSION:-0.0.0-dev}"
ARCH="${ARCH:-amd64}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STAGE="$(mktemp -d)"
PKG="autonomous-sre-agent_${VERSION}_${ARCH}"

# agent binary
mkdir -p "$STAGE/usr/local/bin"
( cd "$ROOT/agent" && GOOS=linux GOARCH="$ARCH" CGO_ENABLED=0 \
    go build -ldflags "-X main.version=$VERSION" -o "$STAGE/usr/local/bin/sre-agent" ./cmd/agent )

# config + state dirs (config shipped as a conffile example)
mkdir -p "$STAGE/etc/autonomous-sre" "$STAGE/var/lib/autonomous-sre"
cp "$ROOT/examples/agent-config/agent.yaml" "$STAGE/etc/autonomous-sre/agent.yaml"

# systemd unit
mkdir -p "$STAGE/lib/systemd/system"
cp "$ROOT/agent/packaging/sre-agent.service" "$STAGE/lib/systemd/system/sre-agent.service"

# control scripts: dedicated user, locked-down state dir, service wiring
mkdir -p "$STAGE/DEBIAN"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: autonomous-sre-agent
Version: ${VERSION}
Architecture: ${ARCH}
Maintainer: autonomous-sre
Depends: systemd
Description: Autonomous SRE VM agent
 Collects host and workload signals and executes policy-controlled,
 typed remediation. Outbound-only to the control plane.
EOF

cat > "$STAGE/DEBIAN/conffiles" <<EOF
/etc/autonomous-sre/agent.yaml
EOF

cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if ! getent passwd sre-agent >/dev/null; then
    useradd --system --home /var/lib/autonomous-sre --shell /usr/sbin/nologin sre-agent
fi
install -d -o sre-agent -g sre-agent -m 0700 /var/lib/autonomous-sre
usermod -aG systemd-journal sre-agent 2>/dev/null || true
systemctl daemon-reload || true
echo "autonomous-sre-agent installed. Enroll, then start:"
echo "  sudo -u sre-agent /usr/local/bin/sre-agent -config /etc/autonomous-sre/agent.yaml -enroll <token>"
echo "  systemctl enable --now sre-agent"
echo "Grant restart rights per allowlisted service in /etc/sudoers.d/sre-agent (see packaging/README.md)."
EOF
chmod 0755 "$STAGE/DEBIAN/postinst"

cat > "$STAGE/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = remove ]; then
    systemctl disable --now sre-agent 2>/dev/null || true
fi
EOF
chmod 0755 "$STAGE/DEBIAN/prerm"

dpkg-deb --build --root-owner-group "$STAGE" "$ROOT/$PKG.deb"
echo "built $ROOT/$PKG.deb"
rm -rf "$STAGE"
