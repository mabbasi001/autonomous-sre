# Agent packaging

## Install layout

| Path | Purpose |
|---|---|
| `/usr/local/bin/sre-agent` | the agent binary |
| `/etc/autonomous-sre/agent.yaml` | local config (`control_plane_url`, `environment`, `state_dir`) |
| `/var/lib/autonomous-sre/` | state: credentials (0600), spool, executed-command record |

## Service account and privileges

The agent runs as a dedicated unprivileged user:

```bash
useradd --system --home /var/lib/autonomous-sre --shell /usr/sbin/nologin sre-agent
install -d -o sre-agent -g sre-agent -m 0700 /var/lib/autonomous-sre
```

Privileged operations go through `sudo -n` with entries scoped to the
exact command per allowlisted unit — never a general grant. For an
allowlist of `nginx`:

```bash
# /etc/sudoers.d/sre-agent  (visudo -cf before installing)
sre-agent ALL=(root) NOPASSWD: /usr/bin/systemctl restart nginx
```

One line per allowlisted service. `service.status`, `http.check` and
journal reads need no sudo; add the `sre-agent` user to the
`systemd-journal` group for `logs.collect_excerpt`:

```bash
usermod -aG systemd-journal sre-agent
```

## systemd unit

```ini
# /etc/systemd/system/sre-agent.service
[Unit]
Description=Autonomous SRE agent
After=network-online.target

[Service]
User=sre-agent
ExecStart=/usr/local/bin/sre-agent -config /etc/autonomous-sre/agent.yaml
Restart=always
RestartSec=5
NoNewPrivileges=no
ProtectSystem=strict
ReadWritePaths=/var/lib/autonomous-sre

[Install]
WantedBy=multi-user.target
```

First start enrolls with a one-time token, then the unit runs without it:

```bash
sudo -u sre-agent /usr/local/bin/sre-agent -config /etc/autonomous-sre/agent.yaml -enroll <token>
systemctl enable --now sre-agent
```
