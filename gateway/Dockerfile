FROM caddy:2.11.2-alpine@sha256:834468128c7696cec0ceea6172f7d692daf645ae51983ca76e39da54a97c570d
# Unprivileged high ports require no file capabilities. Remove upstream's
# cap_net_bind_service so cap_drop ALL + no-new-privileges can execute Caddy.
RUN setcap -r /usr/bin/caddy
USER 10001:10001
ENTRYPOINT ["caddy"]
