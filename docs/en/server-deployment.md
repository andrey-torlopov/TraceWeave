# Install TraceWeave on an Ubuntu 24.04 VPS

*[Русский](../ru/server-deployment.md)*

This guide is for a verified published release. Public application images and the public release manifest are not available yet; the current alternative is a [source build](quick-start.md). A local image ID cannot be pulled on a clean VPS.

## 1. Prepare SSH Access

Use a VPS/VDS with Ubuntu 24.04, sudo access and an architecture supported by the chosen release. Allow disk space for data, backup and new restore volumes. Create a dedicated SSH key **on the operator's computer**:

```sh
ssh-keygen -t ed25519 -f "$HOME/.ssh/traceweave_vps" -C traceweave-vps
cat "$HOME/.ssh/traceweave_vps.pub"
printf 'VPS IP: '
IFS= read -r TW_VPS_IP
printf 'Initial SSH user: '
IFS= read -r TW_ADMIN_USER
ssh -i "$HOME/.ssh/traceweave_vps" "$TW_ADMIN_USER@$TW_VPS_IP"
```

Set a passphrase; add only the public `.pub` line via the provider console, and verify the server fingerprint. Keep the private key on the operator's computer.

Create a dedicated operator **on the VPS**:

```sh
printf 'New operator username: '
IFS= read -r TW_OPERATOR_USER
sudo adduser "$TW_OPERATOR_USER"
sudo usermod -aG sudo "$TW_OPERATOR_USER"
sudo install -d -m 700 -o "$TW_OPERATOR_USER" -g "$TW_OPERATOR_USER" "/home/$TW_OPERATOR_USER/.ssh"
printf 'Full public SSH key line: '
IFS= read -r TW_PUBLIC_KEY
printf '%s
' "$TW_PUBLIC_KEY" | sudo tee "/home/$TW_OPERATOR_USER/.ssh/authorized_keys" >/dev/null
sudo chown "$TW_OPERATOR_USER:$TW_OPERATOR_USER" "/home/$TW_OPERATOR_USER/.ssh/authorized_keys"
sudo chmod 600 "/home/$TW_OPERATOR_USER/.ssh/authorized_keys"
```

Keep the initial session open while testing a second SSH session with the operator and `sudo -v`. Re-enter the IP/user variables in that new operator terminal before connecting.

## 2. Docker, DNS and Ports

On the VPS, install Docker Engine from the official Ubuntu repository, including `docker-compose-plugin`, following the [official installation guide](https://docs.docker.com/engine/install/ubuntu/). Install host Git, curl and Python:

```sh
sudo apt update
sudo apt install git curl python3
sudo usermod -aG docker "$USER"
```

Reconnect to activate the group, then run `docker info`, `docker compose version` and `docker run --rm hello-world`. Docker-group membership gives root-level authority; grant it only to the operator. The server Compose file needs `!override`; the recorded environment used Engine 29.8.2/Compose 5.5.1. Host Swift/Node are unnecessary.

Set a DNS A record to the VPS IPv4; add AAAA only for working IPv6. Provider firewall must permit operator SSH and public TCP 80/443, plus outbound DNS/HTTPS/SMTP. Check port conflicts and Docker's firewall rules. Caddy owns TLS; a separate nginx/certbot is unnecessary.

```sh
printf 'Public domain without scheme, port or path: '
IFS= read -r TW_DOMAIN
getent ahosts "$TW_DOMAIN"
TW_PUBLIC_ORIGIN="https://$TW_DOMAIN"
```

## 3. Bootstrap the Selected Release

Use the exact delivery revision and manifest supplied by the verified release. On the VPS:

```sh
git clone https://github.com/andrey-torlopov/TraceWeave.git "$HOME/TraceWeave"
cd "$HOME/TraceWeave"
printf 'Delivery revision from the release: '
IFS= read -r TW_DELIVERY_REVISION
git checkout --detach "$TW_DELIVERY_REVISION"
export TW_RUNTIME_DIR="$HOME/traceweave-runtime"
umask 077
printf 'Absolute path to verified release manifest: '
IFS= read -r TW_RELEASE_MANIFEST
test -f "$TW_RELEASE_MANIFEST"
printf 'First account email: '
IFS= read -r TW_OWNER_EMAIL
printf 'First account name: '
IFS= read -r TW_OWNER_NAME
printf 'SMTP URL with port, without credentials: '
IFS= read -r TW_SMTP_URL
printf 'SMTP login: '
IFS= read -r TW_SMTP_USER
printf 'Sender email: '
IFS= read -r TW_SMTP_FROM
./bootstrap.sh --release "$TW_RELEASE_MANIFEST" --origin "$TW_PUBLIC_ORIGIN" \
  --email "$TW_OWNER_EMAIL" --name "$TW_OWNER_NAME" \
  --smtp-url "$TW_SMTP_URL" --smtp-user "$TW_SMTP_USER" --smtp-from "$TW_SMTP_FROM"
./traceweave.sh status
curl --fail --show-error "$TW_PUBLIC_ORIGIN/health/ready"
curl --fail --show-error "$TW_PUBLIC_ORIGIN/release.json"
```

Use working `smtp://` STARTTLS or `smtps://` parameters from your provider. Bootstrap prompts privately for the SMTP/account passwords. Confirm the email link before login. Expect phase `ready`, healthy services and valid TLS; do not bypass verification with `curl -k`. Registration is disabled unless explicitly configured.

## 4. Keep the Installation Recoverable

In each new VPS session set `export TW_RUNTIME_DIR="$HOME/traceweave-runtime"` and enter `$HOME/TraceWeave`. Use `stop`, `start`, `status` and `backup`. Move a complete verified backup directory to separate private storage, retaining permissions/checksums; save private secrets/configuration/manifests separately. A backup on the VPS disk alone does not protect against losing that VPS.

Update only with a verified compatible manifest through `./traceweave.sh update --release`. Read preflight and confirm in the TTY. Image rollback requires the same migration history; after a schema change use a compatible fix or restore the pre-update backup. See [Operations](operations.md) and [Releases](releases.md). Do not delete runtime or volumes to recover a failed operation.

---

[Back to documentation](index.md) · [README](../../README.md)
