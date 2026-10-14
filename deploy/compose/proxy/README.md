# TLS reverse proxy (stub)

The MVP deployment puts the API and dashboard behind a TLS-terminating
reverse proxy (README §12). Not wired into the dev compose file — local
development talks plain HTTP on localhost.

`Caddyfile` is the starting point for the internal deployment: set the
real hostname, and Caddy handles certificates (internal CA or ACME,
per the org's setup). Enable by adding a `proxy` service to a
deployment-specific compose override:

```yaml
  proxy:
    image: caddy:2-alpine
    ports: ["443:443"]
    volumes:
      - ./proxy/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
```

Hardening (headers, rate limits at the edge, admin-off) happens in
feature 15.
