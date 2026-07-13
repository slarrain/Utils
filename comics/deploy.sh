#!/usr/bin/env bash
#
# Despliegue de comics-bot al NAS Synology con un solo comando.
#
#   ./deploy.sh
#
# Qué hace:
#   1. Construye la imagen Docker en TU computador.
#   2. La transfiere al NAS por SSH (sin scp/SFTP, que en Synology suele fallar).
#   3. (Re)lanza el contenedor con los volúmenes y credenciales.
#
# Configúralo en deploy.conf y deploy.secrets. Es idempotente.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- Cargar configuración --------------------------------------------------- #
CONF="$SCRIPT_DIR/deploy.conf"
[ -f "$CONF" ] || { echo "ERROR: no existe $CONF"; exit 1; }
# shellcheck disable=SC1090
. "$CONF"

: "${NAS_HOST:?Falta NAS_HOST en deploy.conf}"
: "${NAS_USER:?Falta NAS_USER en deploy.conf}"
: "${NAS_SSH_PORT:?Falta NAS_SSH_PORT en deploy.conf}"
: "${CONTAINER_NAME:?Falta CONTAINER_NAME en deploy.conf}"
: "${IMAGE_NAME:?Falta IMAGE_NAME en deploy.conf}"
: "${NAS_DATA_DIR:?Falta NAS_DATA_DIR en deploy.conf}"
: "${NAS_INBOX_DIR:?Falta NAS_INBOX_DIR en deploy.conf}"
: "${NAS_LIBRARY_DIR:?Falta NAS_LIBRARY_DIR en deploy.conf}"
: "${JD_DOWNLOAD_ROOT:?Falta JD_DOWNLOAD_ROOT en deploy.conf}"
: "${KOMGA_URL:?Falta KOMGA_URL en deploy.conf}"
USE_SUDO="${USE_SUDO:-yes}"

# --- Cargar credenciales reales (fuera de git) ------------------------------- #
SECRETS="$SCRIPT_DIR/deploy.secrets"
[ -f "$SECRETS" ] || { echo "ERROR: no existe $SECRETS (cp deploy.secrets.example deploy.secrets)"; exit 1; }
# shellcheck disable=SC1090
. "$SECRETS"

: "${TELEGRAM_API_ID:?Falta TELEGRAM_API_ID en deploy.secrets}"
: "${TELEGRAM_API_HASH:?Falta TELEGRAM_API_HASH en deploy.secrets}"
: "${COMICVINE_API_KEY:?Falta COMICVINE_API_KEY en deploy.secrets}"
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
  echo "ERROR: falta TELEGRAM_BOT_TOKEN en deploy.secrets."
  echo "       Crea un bot con @BotFather en Telegram y pega el token."
  exit 1
fi

# --- Comprobar herramientas locales ----------------------------------------- #
for tool in docker ssh tar gzip; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: falta '$tool' en tu computador."; exit 1; }
done

REMOTE="$NAS_USER@$NAS_HOST"
REMOTE_DIR="/tmp/comicsbot_deploy_$$"

TMP="$(mktemp -d)"
CTRL="$TMP/cb-ctrl.sock"
SSHM=(ssh -o ControlMaster=auto -o ControlPath="$CTRL" -o ControlPersist=3600 -p "$NAS_SSH_PORT")

cleanup() {
  "${SSHM[@]}" -O exit "$REMOTE" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

echo "==> Conectando al NAS $REMOTE (te pedirá la contraseña una sola vez)..."
"${SSHM[@]}" -n -o ConnectTimeout=15 "$REMOTE" true

SUDO_PASS=""
if [ "$USE_SUDO" = "yes" ]; then
  read -rsp "Contraseña de sudo de '$NAS_USER' en el NAS: " SUDO_PASS
  echo
fi

echo "==> Construyendo la imagen '$IMAGE_NAME:latest' localmente..."
docker build -t "$IMAGE_NAME:latest" "$SCRIPT_DIR"

echo "==> Empaquetando la imagen..."
docker save "$IMAGE_NAME:latest" | gzip > "$TMP/image.tar.gz"
echo "    Tamaño: $(du -h "$TMP/image.tar.gz" | cut -f1)"

cat > "$TMP/params.env" <<PARAMS
CONTAINER_NAME=$CONTAINER_NAME
IMAGE_NAME=$IMAGE_NAME
NAS_DATA_DIR=$NAS_DATA_DIR
NAS_INBOX_DIR=$NAS_INBOX_DIR
NAS_LIBRARY_DIR=$NAS_LIBRARY_DIR
JD_DOWNLOAD_ROOT=$JD_DOWNLOAD_ROOT
KOMGA_URL=$KOMGA_URL
TELEGRAM_API_ID=$TELEGRAM_API_ID
TELEGRAM_API_HASH=$TELEGRAM_API_HASH
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_OWNER_ID=${TELEGRAM_OWNER_ID:-}
COMICVINE_API_KEY=$COMICVINE_API_KEY
KOMGA_EMAIL=${KOMGA_EMAIL:-}
KOMGA_PASSWORD=${KOMGA_PASSWORD:-}
MYJD_EMAIL=${MYJD_EMAIL:-}
MYJD_PASSWORD=${MYJD_PASSWORD:-}
MYJD_DEVICE=${MYJD_DEVICE:-NAS}
PARAMS

cp "$SCRIPT_DIR/deploy_remote.sh" "$TMP/remote.sh"

echo "==> Enviando imagen y scripts al NAS ($REMOTE_DIR)..."
"${SSHM[@]}" "$REMOTE" "mkdir -p '$REMOTE_DIR'"
tar -cf - -C "$TMP" image.tar.gz params.env remote.sh \
  | "${SSHM[@]}" "$REMOTE" "tar -xf - -C '$REMOTE_DIR'"

echo "==> Ejecutando el despliegue en el NAS..."
if [ "$USE_SUDO" = "yes" ]; then
  printf '%s\n' "$SUDO_PASS" | "${SSHM[@]}" "$REMOTE" "sudo -S -p '' bash '$REMOTE_DIR/remote.sh' '$REMOTE_DIR'"
else
  "${SSHM[@]}" "$REMOTE" "bash '$REMOTE_DIR/remote.sh' '$REMOTE_DIR'"
fi

echo ""
echo "✅ Despliegue terminado."
echo "   Logs:  ssh $REMOTE 'sudo docker logs -f $CONTAINER_NAME'"
echo "   Ahora en Telegram: envía /start a tu bot para reclamarlo como dueño."
