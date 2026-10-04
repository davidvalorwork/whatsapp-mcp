# Cómo usar el bridge de WhatsApp

El bridge es un programa que se conecta a tu WhatsApp igual que WhatsApp Web, y guarda una
copia del historial en tu computadora. Sirve para que Claude pueda leer chats de proveedores
y bajar las fotos de catálogo que te mandan, sin que tengas que reenviarlas a mano.

Tiene que estar encendido para descargar fotos o enviar mensajes.

## Regla de envío: un mensaje cada cinco segundos

El bridge espera **al menos cinco segundos después de terminar cada intento de envío**
antes de iniciar el siguiente. El límite es global: aplica entre distintos destinatarios,
texto, archivos y notas de voz, incluso si llegan varias solicitudes de la API a la vez.
Las solicitudes esperan su turno; los intentos fallidos también activan la pausa.
Las solicitudes internas de historial que usan el mismo envío respetan este límite.

Esta regla se aplica dentro del ejecutable y no debe omitirse desde scripts o herramientas.
Al enviar lotes, hay que esperar cada respuesta y usar un tiempo de espera suficiente
para las solicitudes en cola. La pausa reduce la frecuencia; no garantiza evitar
restricciones o desvinculaciones de WhatsApp.

## Límite de contactos nuevos — 04/10/2026

- El bridge permite **como máximo cinco números privados nuevos en las últimas 24 horas**;
  es una ventana móvil, no un contador que se reinicia a medianoche.
- Considera nuevo a quien no tiene nombre guardado en la agenda ni mensajes recibidos en
  el chat. Un nombre de perfil o de empresa no demuestra que esté guardado.
- Permite **un primer intento por número**, hasta que llegue una respuesta. Después
  de identificar y reservar el destinatario, los fallos de carga/envío también consumen
  esa oportunidad: no reintentar automáticamente. Una consulta fallida que no logra
  identificar un destinatario de WhatsApp no crea una reserva.
- El contador se guarda en `store/messages.db`, tabla `outbound_contact_attempts`, y
  sobrevive a reinicios. Teléfono y LID se comprueban como el mismo destinatario.
- Un contacto guardado o con mensajes recibidos permite conversar y mantiene la pausa
  global de cinco segundos. El bridge no distingue una respuesta automática de una
  humana: los agentes deben esperar una respuesta sustantiva antes de insistir.
- Un rechazo por este límite devuelve **HTTP 429**; no programar reintentos automáticos
  ni borrar la tabla para eludirlo. Si no puede comprobar el registro, detiene el envío.
- Solo limita envíos hechos desde este bridge; no controla los enviados desde el teléfono.
  Es una política nuestra, **no un umbral seguro publicado por WhatsApp ni una garantía**.

Los mensajes anteriores a instalar la regla no tienen reservas nuevas en esa tabla;
el historial sí evita volver a escribir a un destinatario sin respuesta. Al consultar
talleres, enviar un mensaje corto por un solo trabajo y esperar su presupuesto.

Después de cambiar el código, recompilar desde `whatsapp-bridge`:
`go build -o whatsapp-bridge.exe main.go`, y reiniciar el bridge para aplicar el cambio.

## Los tres comandos

```bash
python ~/Documents/whatsapp-mcp/wa.py status
```

Te dice si está bien con un semáforo:

- **VERDE** — funcionando, no hay nada que hacer.
- **AMARILLO** — funciona, pero hay algo que vale la pena mirar. Te dice qué.
- **ROJO** — no sirve ahora mismo. Te dice por qué.

```bash
python ~/Documents/whatsapp-mcp/wa.py start
```

Lo enciende. Si ya hay uno corriendo, no hace nada (no se duplica).

```bash
python ~/Documents/whatsapp-mcp/wa.py stop
```

Lo apaga. También existe `restart`, que apaga y enciende.

## Buscar el chat de alguien por su número

```bash
python ~/Documents/whatsapp-mcp/wa.py quien "+58 412-0000000"
```

```
584120000000 -> 123456789@lid
  3 mensajes, 2 fotos
```

Los datos del ejemplo son ficticios. Hace falta porque WhatsApp identifica muchos chats
con un código `@lid`, que no lleva el teléfono por ningún lado. Una búsqueda directa por
número puede devolver vacío aunque el chat exista. Este comando hace la traducción.

Acepta el número como lo tengas anotado: con o sin el 58, con guiones o espacios.

## Si te pide el código QR

Pasa cuando WhatsApp desvincula el dispositivo. El `status` te lo dice con estas palabras:
*"SESIÓN CERRADA. WhatsApp desvinculó este dispositivo"*.

Para arreglarlo corre `python wa.py start` desde una terminal. El QR aparece en esa misma
terminal cuando no hay sesión guardada. En el teléfono:
**WhatsApp → Ajustes → Dispositivos vinculados → Vincular dispositivo**, y escaneas.

Tienes 3 minutos antes de que se cierre solo. Si se cierra, vuelve a correr `start`.

Una vez vinculado, no te lo vuelve a pedir hasta que WhatsApp cierre la sesión otra vez.

Si un alias de PowerShell arranca el bridge oculto y redirige su salida al log, leerlo
con UTF-8 desde la raíz del repositorio para que los bloques del QR no se deformen:

```powershell
Get-Content '.\whatsapp-bridge\bridge.log' -Encoding UTF8 -Tail 100 -Wait
```

Escanear el QR vigente, no una copia vieja del log.

## Qué puede hacer Claude ahora

Ya quedó conectado: Claude tiene 12 herramientas de WhatsApp disponibles en cualquier proyecto.

**Sin pedirte permiso** (son solo de lectura, o bajan un archivo a tu disco):
buscar contactos, listar chats, leer y buscar mensajes, ver el contexto de un mensaje,
y descargar fotos y archivos que te mandaron.

**Pidiéndote permiso siempre** — enviar mensajes, archivos y notas de voz. Cada vez que Claude
intente enviar algo te va a salir un diálogo de confirmación. Además, por la regla que ya tenías
escrita, antes de responder un chat Claude debe mostrarte 4 opciones de texto y esperar a que
elijas una.

Si quieres que Claude nunca pueda enviar nada, cambia `"ask"` por `"deny"` en el bloque de
permisos de `~/.claude/settings.json`.

## Detalles que conviene saber

**Leer funciona aunque el bridge esté apagado, pero con datos viejos.** Claude lee el historial
de la copia local, no de WhatsApp en vivo. Por eso conviene correr `status` antes de pedirle que
revise un chat: si el bridge lleva días apagado, te va a contar lo de hace días sin avisar.

**Descargar fotos sí necesita el bridge encendido.** Es la diferencia práctica más importante.

**Algunas fotos viejas ya no se pueden bajar.** WhatsApp caduca los archivos; el bridge pide que
los vuelvan a subir y espera hasta 45 segundos, pero a veces ya no están. No es un error tuyo.

**La API del bridge escucha solo en esta computadora** (`127.0.0.1:8080`).
Las herramientas MCP se conectan por `localhost`; otros equipos de la red no
pueden llamar directamente a las rutas de envío o descarga.

**El archivo `bridge.log` tiene el texto de tus conversaciones.** No lo subas a ningún repositorio
ni lo compartas. Por eso `status` solo lee de ahí las líneas técnicas de error, nunca los mensajes.

## Si algo no cuadra

Corre `status` primero: casi siempre te dice exactamente qué pasa. Los casos típicos:

| Lo que dice | Qué significa | Qué hacer |
|---|---|---|
| Nadie escucha en el puerto 8080 | Está apagado | `start` |
| SESIÓN CERRADA | WhatsApp desvinculó el dispositivo | `start` y escanear el QR |
| Vivo pero SIN conexión a WhatsApp | Se cayó y no reconectó | `restart` |
| Algo ocupa el puerto pero no responde | Quedó un proceso trancado | `stop` y luego `start` |
