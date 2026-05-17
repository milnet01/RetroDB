# Reverse-Proxy Deployment

This document describes the nginx / Caddy / HAProxy configuration required
when running RetroDB behind a reverse proxy with `RETRODB_TRUST_PROXY=1`.

## Why this matters

By default, `request.remote_addr` is the IP that opened the TCP connection
to the WSGI server (waitress / gunicorn). Behind a proxy that's always
`127.0.0.1` or the proxy's internal address — every visitor collapses
into one rate-limit bucket and the IP-based login throttle becomes a
self-DoS + trivial bypass.

`RETRODB_TRUST_PROXY=1` installs Werkzeug's `ProxyFix` middleware, which
rewrites `remote_addr` from the `X-Forwarded-For` header. **This means the
header is now a security boundary.** If your proxy doesn't strip and
re-emit `X-Forwarded-For` from the client, anyone can forge it.

## The trust contract

When `RETRODB_TRUST_PROXY=1` is set:

- `app.py` configures `ProxyFix(x_for=1, x_proto=1, x_host=1, x_prefix=0)`.
- This trusts **exactly one hop** of `X-Forwarded-For` /
  `X-Forwarded-Proto` / `X-Forwarded-Host`.
- The hop must be a proxy you control that:
  1. Terminates TLS (sets `X-Forwarded-Proto: https`).
  2. **Strips any client-supplied `X-Forwarded-For` header and
     re-emits it from the actual peer IP.**
  3. Does not forward `X-Forwarded-Host` from untrusted clients.

If your deployment chains multiple proxies (CDN → LB → app), you must:

- Set `x_for`, `x_proto`, `x_host` to the number of trusted hops in
  the `ProxyFix(...)` call in `app.py` (inside the
  `RETRODB_TRUST_PROXY` branch).
- Audit every hop in the chain for the same strip-and-re-emit guarantee.

## nginx

```nginx
server {
    listen 443 ssl http2;
    server_name retrodb.example.com;

    ssl_certificate     /etc/letsencrypt/live/retrodb.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/retrodb.example.com/privkey.pem;

    client_max_body_size 100m;

    location / {
        proxy_pass http://127.0.0.1:5000;

        # Strip the client-supplied header — never trust it.
        # nginx's `proxy_set_header X-Forwarded-For ...` overwrites; the
        # default $proxy_add_x_forwarded_for would *append* the client
        # value to the real peer IP, which is exactly the attack vector
        # we're guarding against.
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header Host $host;

        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}

# Optional HTTP → HTTPS redirect.
server {
    listen 80;
    server_name retrodb.example.com;
    return 301 https://$host$request_uri;
}
```

Set on the RetroDB process (substitute your `RETRODB_PORT` if you changed the default of `5000`):

```bash
RETRODB_TRUST_PROXY=1 RETRODB_SECURE_COOKIES=true python3 app.py
```

(Or use `./start.sh` / `start.bat` / `start.command` — they exec `app.py` with the env vars from the parent shell.)

## Caddy

Caddy v2 strips and re-emits `X-Forwarded-For` by default with
`reverse_proxy`, so the configuration is brief:

```caddy
retrodb.example.com {
    reverse_proxy 127.0.0.1:5000 {
        header_up X-Real-IP {remote_host}
    }
}
```

## HAProxy

```haproxy
frontend retrodb_https
    bind :443 ssl crt /etc/haproxy/retrodb.pem
    http-request set-header X-Forwarded-Proto https
    # `option forwardfor` adds X-Forwarded-For from the real peer IP and
    # silently overrides any client-supplied value.
    option forwardfor
    default_backend retrodb_app

backend retrodb_app
    server app1 127.0.0.1:5000
```

## Verifying the configuration

After deployment, hit a route that logs `remote_addr` (e.g. an admin page)
and confirm:

1. The logged IP matches your client's public IP, not `127.0.0.1`.
2. Sending a forged `X-Forwarded-For: 1.2.3.4` from the client does **not**
   show `1.2.3.4` in the logs — your proxy is correctly stripping the
   client value.

If the second test fails, IP rate-limiting is bypassable. Fix the proxy
config before exposing the deployment.

## Localhost development

`RETRODB_TRUST_PROXY` is unset by default. On a direct localhost HTTP
deploy (no proxy), leave it that way. Setting it on a no-proxy deploy
makes any forged `X-Forwarded-For` instantly trusted.

## Related

- `app.py` — ProxyFix wiring (inside the `RETRODB_TRUST_PROXY` env-gate; grep `ProxyFix` to find it).
- `services/security.py::rate_limit_login` — the IP-based login throttle
  that depends on a real `remote_addr`.
- Pass 40.16 in `roadmap.md` — the indie-review finding that prompted
  this document.

## Upload limits

Flask caps request bodies at `config.MAX_UPLOAD_BYTES` (see `app.py`). The nginx
example above sets `client_max_body_size 100m;`. **If you raise the Flask
limit, also raise the proxy limit** — otherwise nginx returns 413 before the
request reaches Waitress and the new cap is silently bypassed. Caddy and
HAProxy have their own equivalents (`request_body { max_size … }` /
`http-request deny if { req.body_size gt … }`).
