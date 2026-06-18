#!/usr/bin/env bash
#
# Despliegue de Comidas Campo al NAS Synology con un solo comando.
#
#   ./deploy.sh
#
# Qué hace:
#   1. Construye la imagen Docker en TU computador.
#   2. La transfiere al NAS por SSH (sin usar scp/SFTP, que en Synology suele fallar).
#   3. (Re)lanza el contenedor con tu volumen de datos y el puerto elegido.
#
# Configúralo en deploy.conf. Es idempotente: vuelve a correrlo para redesplegar.
# Con autenticación por contraseña sólo te la pedirá UNA vez (multiplexa la conexión).
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
: "${APP_PORT:?Falta APP_PORT en deploy.conf}"
: "${NAS_DATA_DIR:?Falta NAS_DATA_DIR en deploy.conf}"
: "${CONTAINER_NAME:?Falta CONTAINER_NAME en deploy.conf}"
: "${IMAGE_NAME:?Falta IMAGE_NAME en deploy.conf}"
USE_SUDO="${USE_SUDO:-yes}"

# --- Cargar contraseñas reales (fuera de git) ------------------------------- #
SECRETS="$SCRIPT_DIR/deploy.secrets"
if [ -f "$SECRETS" ]; then
  # shellcheck disable=SC1090
  . "$SECRETS"
fi
SHARED_PASSWORD="${SHARED_PASSWORD:-}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
if [ -z "$SHARED_PASSWORD" ] || [ -z "$ADMIN_PASSWORD" ]; then
  echo "AVISO: faltan contraseñas en deploy.secrets; la app usará las de prueba"
  echo "       incrustadas (campo/admin). Crea deploy.secrets (cp deploy.secrets.example ...)."
fi

# --- Comprobar herramientas locales ----------------------------------------- #
for tool in docker ssh tar gzip; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: falta '$tool' en tu computador."; exit 1; }
done

REMOTE="$NAS_USER@$NAS_HOST"
REMOTE_DIR="/tmp/cc_deploy_$$"

TMP="$(mktemp -d)"
# Conexión SSH multiplexada: te autenticas una vez y todo lo demás la reutiliza.
CTRL="$TMP/cc-ctrl.sock"
SSHM=(ssh -o ControlMaster=auto -o ControlPath="$CTRL" -o ControlPersist=3600 -p "$NAS_SSH_PORT")

cleanup() {
  "${SSHM[@]}" -O exit "$REMOTE" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

if [ "$USE_SUDO" = "yes" ]; then SUDO_PREFIX="sudo "; else SUDO_PREFIX=""; fi

echo "==> Conectando al NAS $REMOTE (te pedirá la contraseña una sola vez)..."
"${SSHM[@]}" -o ConnectTimeout=15 "$REMOTE" true

echo "==> Construyendo la imagen '$IMAGE_NAME:latest' localmente..."
docker build -t "$IMAGE_NAME:latest" "$SCRIPT_DIR"

echo "==> Empaquetando la imagen..."
docker save "$IMAGE_NAME:latest" | gzip > "$TMP/image.tar.gz"
echo "    Tamaño: $(du -h "$TMP/image.tar.gz" | cut -f1)"

# SECRET_KEY de respaldo: sólo se usa la PRIMERA vez; luego el NAS reutiliza el suyo.
if command -v openssl >/dev/null 2>&1; then
  FALLBACK_SECRET="$(openssl rand -hex 32)"
else
  FALLBACK_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
fi

cat > "$TMP/params.env" <<PARAMS
APP_PORT=$APP_PORT
BASE_DIR=$NAS_DATA_DIR
CONTAINER_NAME=$CONTAINER_NAME
IMAGE_NAME=$IMAGE_NAME
FALLBACK_SECRET=$FALLBACK_SECRET
SHARED_PASSWORD=$SHARED_PASSWORD
ADMIN_PASSWORD=$ADMIN_PASSWORD
PARAMS

cp "$SCRIPT_DIR/deploy_remote.sh" "$TMP/remote.sh"

echo "==> Enviando imagen y scripts al NAS ($REMOTE_DIR)..."
# Transferimos por el canal de ejecución de SSH (no SFTP): tar local -> tar remoto.
"${SSHM[@]}" "$REMOTE" "mkdir -p '$REMOTE_DIR'"
tar -cf - -C "$TMP" image.tar.gz params.env remote.sh \
  | "${SSHM[@]}" "$REMOTE" "tar -xf - -C '$REMOTE_DIR'"

echo "==> Ejecutando el despliegue en el NAS..."
# IMPORTANTE: el comando de trabajo se ejecuta SIN pseudo-terminal (-t). Con -t,
# 'docker run -d' sobre SSH deja la sesión colgada aunque el contenedor sí arranca.
# Si hace falta sudo, cacheamos la contraseña antes (eso sí necesita -t, pero es
# instantáneo) y el trabajo corre con las credenciales ya en caché.
if [ "$USE_SUDO" = "yes" ]; then
  echo "    Autenticando sudo (te pedirá la contraseña de '$NAS_USER' una vez)..."
  "${SSHM[@]}" -t "$REMOTE" "sudo -v"
  "${SSHM[@]}" "$REMOTE" "sudo bash '$REMOTE_DIR/remote.sh' '$REMOTE_DIR'"
else
  "${SSHM[@]}" "$REMOTE" "bash '$REMOTE_DIR/remote.sh' '$REMOTE_DIR'"
fi

URL="http://$NAS_HOST:$APP_PORT/"
echo ""
echo "==> Comprobando que la app responda en $URL ..."
if command -v curl >/dev/null 2>&1; then
  ok=""
  for _ in $(seq 1 15); do
    if curl -fsS -o /dev/null "${URL}login" 2>/dev/null; then ok=1; break; fi
    sleep 1
  done
  if [ "$ok" = 1 ]; then
    echo "    Responde correctamente. ✅"
  else
    echo "    Aún no responde; revisa los logs:  ssh ${REMOTE} '${SUDO_PREFIX}docker logs ${CONTAINER_NAME}'"
  fi
fi

echo ""
echo "✅ Despliegue terminado."
echo "   App:   $URL"
echo "   Datos: ${NAS_DATA_DIR}/data   (en el NAS)"
