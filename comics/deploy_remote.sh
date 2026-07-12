#!/usr/bin/env bash
#
# Se ejecuta EN EL NAS (lo invoca deploy.sh por SSH). No lo corras a mano.
#
set -euo pipefail

export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

DEPLOY_DIR="${1:-/tmp/comicsbot_deploy}"
trap 'rm -rf "$DEPLOY_DIR"' EXIT

PARAMS="$DEPLOY_DIR/params.env"
[ -f "$PARAMS" ] || { echo "No se encontró $PARAMS" >&2; exit 1; }

# shellcheck disable=SC1090
. "$PARAMS"
if command -v shred >/dev/null 2>&1; then shred -u "$PARAMS" 2>/dev/null || rm -f "$PARAMS"; else rm -f "$PARAMS"; fi

: "${CONTAINER_NAME:?}"; : "${IMAGE_NAME:?}"
: "${NAS_DATA_DIR:?}"; : "${NAS_INBOX_DIR:?}"; : "${NAS_LIBRARY_DIR:?}"

DATA_DIR="$NAS_DATA_DIR/data"
ENV_FILE="$NAS_DATA_DIR/comicsbot.env"
mkdir -p "$DATA_DIR" "$NAS_INBOX_DIR/telegram" "$NAS_INBOX_DIR/folderwatch" "$NAS_INBOX_DIR/failed" "$NAS_INBOX_DIR/tagged"

umask 077
cat > "$ENV_FILE" <<ENV
TELEGRAM_API_ID=$TELEGRAM_API_ID
TELEGRAM_API_HASH=$TELEGRAM_API_HASH
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_OWNER_ID=$TELEGRAM_OWNER_ID
COMICVINE_API_KEY=$COMICVINE_API_KEY
KOMGA_URL=$KOMGA_URL
KOMGA_EMAIL=$KOMGA_EMAIL
KOMGA_PASSWORD=$KOMGA_PASSWORD
JD_DOWNLOAD_ROOT=$JD_DOWNLOAD_ROOT
ENV
chmod 600 "$ENV_FILE"

echo "==> Cargando la imagen en Docker (puede tardar)..."
docker load -i "$DEPLOY_DIR/image.tar.gz"

echo "==> (Re)lanzando el contenedor '$CONTAINER_NAME'..."
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  -v "$DATA_DIR:/data" \
  -v "$NAS_INBOX_DIR:/inbox" \
  -v "$NAS_LIBRARY_DIR:/library" \
  --env-file "$ENV_FILE" \
  "$IMAGE_NAME:latest"

sleep 3
echo "==> Últimas líneas del log:"
docker logs --tail 10 "$CONTAINER_NAME" 2>&1 || true

docker image prune -f >/dev/null 2>&1 || true
echo "==> Listo."
