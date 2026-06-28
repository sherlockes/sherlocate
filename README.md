# Sherlocate 📍

Sherlocate es una solución de rastreo en tiempo real autohospedada, simple y ligera. Permite recibir datos de ubicación desde la aplicación oficial de Android **Traccar Client**, almacenar la última posición de forma persistente y mostrarla de forma interactiva en una página web única (SPA) con mapas dinámicos de Leaflet.js.

---

## 🛠️ Estructura del Proyecto

El proyecto está compuesto por los siguientes archivos:
*   [main.py](file:///home/sherlockes/docker/sherlocate/main.py): Backend desarrollado en **FastAPI** que gestiona la API de localización y sirve el frontend.
*   [templates/index.html](file:///home/sherlockes/docker/sherlocate/templates/index.html): Frontend SPA con mapa interactivo Leaflet.js, historial de ruta (breadcrumbs), indicador de batería y telemetría.
*   [Dockerfile](file:///home/sherlockes/docker/sherlocate/Dockerfile): Archivo para compilar la imagen de Docker basada en `python:3.11-slim`.
*   [requirements.txt](file:///home/sherlockes/docker/sherlocate/requirements.txt): Dependencias Python.
*   [docker-compose.yml](file:///home/sherlockes/docker/sherlocate/docker-compose.yml): Orquestación de Docker Compose que lee las variables desde un archivo `.env` externo.
*   `.env`: Archivo de configuración local con las contraseñas e identificadores de los dispositivos (no se sube al repositorio).
*   `.env.example`: Plantilla de ejemplo para configurar el archivo `.env`.

---

## 🚀 Despliegue Rápido (Docker Compose)

1.  Copia el archivo de plantilla a tu configuración real:
    ```bash
    cp .env.example .env
    ```
2.  Edita el archivo `.env` con tus dispositivos y contraseñas.
3.  Ejecuta el siguiente comando para compilar e iniciar el contenedor en segundo plano:
    ```bash
    docker compose up -d --build
    ```
4.  El servicio estará disponible en `http://localhost:8000`. Sus datos de posicionamiento se guardarán de forma persistente en la carpeta `./data` de tu servidor.

---

## 🔒 Configuración detrás de Nginx Proxy Manager (NPM)

Si utilizas **Nginx Proxy Manager** para exponer el servicio a Internet con un dominio propio y SSL (HTTPS), configúralo de la siguiente manera:

1.  Añade un nuevo **Proxy Host**.
2.  **Domain Names**: Tu subdominio (ej: `tracker.midominio.com`).
3.  **Scheme**: `http`
4.  **Forward Hostname / IP**: 
    *   Si NPM está en la misma red de Docker que Sherlocate, puedes usar el nombre del contenedor: `sherlocate`
    *   Si NPM está fuera de Docker o en otra red, usa la IP local del servidor (ej: `192.168.1.100` o la IP de docker `172.17.0.1`).
5.  **Forward Port**: `8000`
6.  **Websockets Support**: Desactivado está bien (esta app usa short polling).
7.  **Block Common Exploits**: Activado (recomendado).
8.  En la pestaña **SSL**, solicita un certificado de Let's Encrypt y activa **Force SSL**.

---

## 📱 Configuración en la App de Android (Traccar Client)

Configura la app **Traccar Client** (o cualquier cliente de geolocalización compatible con HTTP) en tu dispositivo Android:

1.  **Dirección del servidor**: 
    *   Introduce la URL de tu endpoint de tracking pasando la contraseña del dispositivo como parámetro URL:
        `http://[IP-DE-TU-SERVIDOR]:8000/api/tracking?password=CONTRASEÑA_DEL_DISPOSITIVO`
        (o usando HTTPS con tu dominio si usas un proxy inverso: `https://midominio.com/api/tracking?password=CONTRASEÑA_DEL_DISPOSITIVO`).
2.  **Identificador del dispositivo**: Introduce el identificador único que definiste en `.env` (ej. `123456`).
3.  **Frecuencia**: Ajusta el intervalo de envío (se recomiendan **5 o 10 segundos** para un rastreo fluido en tiempo real).
4.  **Proveedor de localización**: Selecciona **GPS** o **Mixto** para garantizar la precisión de las coordenadas.
5.  **Inicia el servicio**: Activa el interruptor **"Estado del servicio"** en la pantalla principal.
