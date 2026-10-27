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

## Windows

Cross-compile:

```bash
GOOS=windows GOARCH=amd64 go build -ldflags "-X main.version=<ver>" -o sre-agent.exe ./cmd/agent
```

### Install layout

| Path | Purpose |
|---|---|
| `C:\Program Files\autonomous-sre\sre-agent.exe` | the agent binary |
| `C:\ProgramData\autonomous-sre\agent.yaml` | local config |
| `C:\ProgramData\autonomous-sre\` | state: credentials, spool, executed-command record |

Collection is Windows-aware: Windows services (via SCM) are reported as
`windows.service` events and IIS application pools (via `appcmd`) as
`iis.app_pool`. `service.restart` restarts a Windows service;
`iis.recycle_app_pool` recycles a pool. Both enforce the local
allowlist. Host metrics come from kernel32 (memory/CPU/uptime).

### Service account and privileges

Run under a dedicated low-privilege account, not LocalSystem. Grant it
only what it needs:

```powershell
# state directory locked to the service account + Administrators
icacls "C:\ProgramData\autonomous-sre" /inheritance:r `
  /grant "sre-agent:(OI)(CI)F" "Administrators:(OI)(CI)F"

# per-service restart right (the sudoers analogue), using sc sdset or
# subinacl, scoped to each allowlisted service — never full admin.
```

### Install as a Windows Service

The agent implements the Service Control Manager interface, so it runs
as a native service:

```powershell
# enroll once at the console (one-time token)
& "C:\Program Files\autonomous-sre\sre-agent.exe" `
  -config C:\ProgramData\autonomous-sre\agent.yaml -enroll <token>

# register and start the service
sc.exe create autonomous-sre binPath= "\"C:\Program Files\autonomous-sre\sre-agent.exe\" -config C:\ProgramData\autonomous-sre\agent.yaml" start= auto obj= ".\sre-agent" password= "<pw>"
sc.exe start autonomous-sre
```

The service handles Stop/Shutdown control requests and drains cleanly.
