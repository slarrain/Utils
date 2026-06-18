# 🏡 Comidas Campo

Aplicación web sencilla (Flask + SQLite) para **dividir la cuenta de la comida**
cuando varias familias van a la casa del campo.

Cada familia registra **cuántas personas llevó cada día** y **cuánto gastó** en
comida. La cuenta total se reparte de forma justa según los **persona-días**
(personas × días) que consumió cada familia, y la app **sugiere los pagos**
necesarios: «La familia A le paga $X a la familia B».

## Cómo funciona el cálculo

Base = **persona-días**: alguien presente 3 días cuenta 3× alguien presente 1 día.

1. `total_gastado` = suma de todos los gastos
2. `total_persona_días` = suma de personas presentes en todos los días
3. `costo_por_persona_día = total_gastado / total_persona_días`
4. **lo que le corresponde** a cada familia = `sus_persona_días × costo_por_persona_día`
5. **saldo** = `lo que pagó − lo que le corresponde` (positivo = le deben; negativo = debe)

Las cuotas se redondean a pesos enteros con el método del *resto mayor*, así que
suman exactamente el total y todos los saldos cierran en cero. Los pagos sugeridos
usan un algoritmo voraz que minimiza la cantidad de transferencias.

## Roles

- **Administrador** (contraseña aparte): crea/configura/cierra eventos y gestiona la
  lista de familias.
- **Familias**: una única contraseña compartida; al entrar, cada persona elige su
  familia y registra su asistencia y sus gastos. Pueden editar y borrar sus datos
  mientras el evento esté abierto.

La **liquidación se muestra a las familias solo cuando el administrador cierra el
evento** (el admin puede previsualizarla antes).

## Variables de entorno

| Variable          | Por defecto                       | Descripción                                  |
|-------------------|-----------------------------------|----------------------------------------------|
| `SHARED_PASSWORD` | `campo` (sólo desarrollo)         | Contraseña compartida para todas las familias |
| `ADMIN_PASSWORD`  | `admin` (sólo desarrollo)         | Contraseña del administrador                  |
| `SECRET_KEY`      | `dev-change-me-please`            | Clave de sesión de Flask (cámbiala en prod)   |
| `DATABASE_URL`    | SQLite en `instance/comidas.db`   | En Docker: `sqlite:////data/comidas.db`       |
| `PORT`            | `5000` (local) / `8080` (Docker)  | Puerto                                        |

> ⚠️ Los valores por defecto son sólo para desarrollo local. Las contraseñas **reales**
> NO viven en el código (para no subirlas a git): ponlas en `deploy.secrets` (ignorado por
> git) y el despliegue las inyecta en el NAS. Ver más abajo.

## Ejecutar localmente

```bash
cd comidas_campo
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Abre http://localhost:5000 — en local usa las contraseñas de desarrollo `campo` (familias)
y `admin` (administrador). Las contraseñas reales se usan sólo en el NAS (ver `deploy.secrets`).

Correr los tests:

```bash
pip install pytest
pytest tests/
```

## Desplegar en el NAS con un solo comando (recomendado)

Hay un script que hace todo: construye la imagen en tu computador, la envía al NAS y
(re)lanza el contenedor. Es **idempotente**: para actualizar, vuelve a correrlo.

**Requisitos previos (una sola vez):**
- Docker instalado en tu computador.
- SSH habilitado en el NAS (DSM → Panel de control → Terminal y SNMP → *Habilitar SSH*).
- Container Manager (Docker) instalado en el NAS.
- Tu usuario del NAS puede ejecutar `sudo docker` (normal en Synology).

**Configura una vez:**
- `deploy.conf` (ya viene con tus datos: `192.168.1.200`, usuario `santiago`, puerto
  `9876`, carpeta `/volume1/docker/comidas-campo`). No contiene contraseñas.
- `deploy.secrets` (ignorado por git) con las contraseñas reales. Copia la plantilla:
  ```bash
  cp deploy.secrets.example deploy.secrets   # y edita las contraseñas
  ```

**Despliega:**
```bash
cd comidas_campo
./deploy.sh
```

Cuando termine, la app queda en **http://192.168.1.200:9876/**. Te puede pedir la
contraseña de SSH y/o de `sudo` del NAS. La base de datos vive en
`/volume1/docker/comidas-campo/data/comidas.db`.

> El `SECRET_KEY` se genera solo la primera vez y se guarda en el NAS
> (`/volume1/docker/comidas-campo/comidas.env`), así que se mantiene estable entre
> despliegues y no invalida las sesiones. Las contraseñas (de `deploy.secrets`) también
> se escriben en ese archivo del NAS (permisos `600`) y se pasan al contenedor con
> `--env-file`. Nunca quedan en el código ni en git.

Archivos del despliegue: `deploy.sh` (corre en tu PC), `deploy_remote.sh` (corre en el
NAS) y `deploy.conf` (tu configuración).

### Servirlo en el puerto 80

Para evitar escribir el puerto, usa el proxy inverso de DSM (ver más abajo) apuntando a
`localhost:9876`.

---

## Desplegar a mano (alternativa)

La app va dentro de un contenedor Docker y la base de datos SQLite vive en una carpeta
del NAS para que **persista y se respalde**.

### 1. Probar el contenedor en tu PC

```bash
docker build -t comidas-campo .
docker run --rm -p 8080:8080 \
  -v "$PWD/data_local:/data" \
  -e SECRET_KEY="pon-algo-largo-y-aleatorio" \
  -e SHARED_PASSWORD="tu-clave-familia" \
  -e ADMIN_PASSWORD="tu-clave-admin" \
  comidas-campo
```

Visita http://localhost:8080. La base de datos queda en `./data_local/comidas.db`.

### 2. En el NAS con **Container Manager**

1. Instala **Container Manager** desde el Centro de paquetes.
2. Sube el código al NAS (carpeta compartida) o sube la imagen:
   - **Opción A (build en el NAS):** copia esta carpeta al NAS, crea un *Proyecto* en
     Container Manager apuntando al `Dockerfile`.
   - **Opción B (imagen pre-armada):** `docker save comidas-campo -o comidas.tar`,
     súbela y en Container Manager → *Imagen* → *Importar*.
3. Crea el contenedor con:
   - **Puerto:** host `8080` → contenedor `8080`.
   - **Volumen:** crea una carpeta en el NAS (p. ej. `/docker/comidas-campo/data`) y
     **móntala en `/data`** (ahí queda `comidas.db`).
   - **Variables de entorno:** `SECRET_KEY`, `SHARED_PASSWORD`, `ADMIN_PASSWORD`.
4. Inicia el contenedor. Pruébalo en `http://192.168.1.200:8080`.

### 3. Servirlo en `http://192.168.1.200/` (puerto 80)

Usa el proxy inverso integrado de DSM para no tener que escribir el puerto:

**Panel de control → Portal de inicio de sesión → Avanzado → Proxy inverso → Crear**

- Origen:  HTTP · `192.168.1.200` (o tu hostname) · puerto **80**
- Destino: HTTP · `localhost` · puerto **8080**

Listo: la app responde en **http://192.168.1.200/**.

## Estructura

```
app.py             Configuración, filtros y rutas de Flask
models.py          Modelos SQLAlchemy (Family, Event, Participation, Attendance, Expense)
calculations.py    Lógica pura de reparto y liquidación (testeada)
templates/         Vistas Jinja2 (en español)
static/style.css   Estilos
tests/             Tests de la lógica de cálculo
Dockerfile         Imagen para Container Manager
```

## Pendientes / posibles mejoras (v2)

- Contraseña por familia (en vez de una compartida) para atribuir cambios.
- Historial de cambios / auditoría.
- Exportar la liquidación a PDF o CSV.
- Protección CSRF (hoy se omite por simplicidad; pensado para una red local de confianza).
- Editar las familias participantes de un evento ya creado.
