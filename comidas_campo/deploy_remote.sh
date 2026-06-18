#!/usr/bin/env bash
#
# Se ejecuta EN EL NAS (lo invoca deploy.sh por SSH). No lo corras a mano.
# Recibe como argumento la carpeta temporal con la imagen y los parámetros.
#
set -euo pipefail

# En Synology el binario de docker vive en /usr/local/bin.
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

DEPLOY_DIR="${1:-/tmp/cc_deploy}"
trap 'rm -rf "$DEPLOY_DIR"' EXIT   # limpia siempre, incluso si algo falla

PARAMS="$DEPLOY_DIR/params.env"
[ -f "$PARAMS" ] || { echo "No se encontró $PARAMS" >&2; exit 1; }

# shellcheck disable=SC1090
. "$PARAMS"
# Borra el archivo de parámetros cuanto antes (contiene el SECRET_KEY de respaldo).
if command -v shred >/dev/null 2>&1; then shred -u "$PARAMS" 2>/dev/null || rm -f "$PARAMS"; else rm -f "$PARAMS"; fi

: "${APP_PORT:?}"; : "${BASE_DIR:?}"; : "${CONTAINER_NAME:?}"
: "${IMAGE_NAME:?}"; : "${FALLBACK_SECRET:?}"

DATA_DIR="$BASE_DIR/data"
ENV_FILE="$BASE_DIR/comidas.env"
mkdir -p "$DATA_DIR"

# Reutiliza el SECRET_KEY ya existente para no invalidar las sesiones en cada
# despliegue; sólo usa el de respaldo la primera vez.
SECRET_KEY=""
if [ -f "$ENV_FILE" ]; then
  SECRET_KEY="$(grep '^SECRET_KEY=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)"
fi
[ -n "$SECRET_KEY" ] || SECRET_KEY="$FALLBACK_SECRET"

umask 077
printf 'SECRET_KEY=%s\n' "$SECRET_KEY" > "$ENV_FILE"
# Las contraseñas sólo se escriben si llegaron desde deploy.secrets; si no, el
# contenedor usa las de prueba incrustadas en la imagen.
if [ -n "${SHARED_PASSWORD:-}" ]; then printf 'SHARED_PASSWORD=%s\n' "$SHARED_PASSWORD" >> "$ENV_FILE"; fi
if [ -n "${ADMIN_PASSWORD:-}" ]; then printf 'ADMIN_PASSWORD=%s\n' "$ADMIN_PASSWORD" >> "$ENV_FILE"; fi
chmod 600 "$ENV_FILE"

echo "==> Cargando la imagen en Docker (puede tardar)..."
docker load -i "$DEPLOY_DIR/image.tar.gz"

echo "==> (Re)lanzando el contenedor '$CONTAINER_NAME'..."
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  -p "$APP_PORT:8080" \
  -v "$DATA_DIR:/data" \
  --env-file "$ENV_FILE" \
  "$IMAGE_NAME:latest"

echo "==> Contenedor en marcha. Datos en: $DATA_DIR"

# Borra imágenes viejas sin usar para no llenar el disco (mejor esfuerzo).
docker image prune -f >/dev/null 2>&1 || true
