"""Control del bridge de WhatsApp: estado, arranque y parada.

    python wa.py status     ¿está sano? (semáforo)
    python wa.py start      arranca el bridge si no hay uno
    python wa.py stop       lo detiene
    python wa.py restart

No lee el contenido de ningún mensaje: del historial solo mira fechas, y del log
solo las líneas de error con formato [Componente NIVEL].
"""
import argparse
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BRIDGE = Path(__file__).resolve().parent / 'whatsapp-bridge'
EXE = BRIDGE / 'whatsapp-bridge.exe'
FUENTE = BRIDGE / 'main.go'
LOG = BRIDGE / 'bridge.log'
DB_MENSAJES = BRIDGE / 'store' / 'messages.db'
DB_SESION = BRIDGE / 'store' / 'whatsapp.db'
PUERTO = 8080

# Solo estas líneas del log se leen. Cualquier otra puede contener texto de conversaciones.
ERROR_LOG = re.compile(r'\[(?:Client|Client/Socket|Database|Send|Message|Download)[^\]]*\s(?:WARN|ERROR)\]\s*(.*)')
RECONECTADO = re.compile(r'\[Client INFO\] Connected to WhatsApp')
GRAVES = (
    'Error reading from websocket',
    'Error reconnecting after autoreconnect sleep',
    'Keepalive timed out',
    'Failed to send keepalive',
    'replaced stream',
    'Device logged out',
    'sending LoggedOut event',
)


def consulta(db, sql, params=()):
    """Abre la base en SOLO LECTURA: el bridge escribe en ella al mismo tiempo."""
    if not db.exists():
        return None
    con = sqlite3.connect(f'file:{db.as_posix()}?mode=ro', uri=True, timeout=5)
    try:
        return con.execute(sql, params).fetchone()
    finally:
        con.close()


def netstat():
    try:
        salida = subprocess.run(['netstat', '-ano'], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return [], []
    escuchando, establecidas = {}, []
    for linea in salida.splitlines():
        campos = linea.split()
        if len(campos) < 4 or not campos[0].startswith('TCP'):
            continue
        estado, pid = campos[-2], campos[-1]
        if estado == 'LISTENING' and campos[1].endswith(f':{PUERTO}'):
            escuchando[pid] = True  # un mismo PID aparece dos veces: IPv4 e IPv6
        elif estado == 'ESTABLISHED':
            establecidas.append((pid, campos[2]))
    return list(escuchando), establecidas


def responde_el_bridge():
    """GET a /api/send: el handler corta por método antes de leer nada. No puede enviar."""
    try:
        urllib.request.urlopen(f'http://127.0.0.1:{PUERTO}/api/send', timeout=5)
    except urllib.error.HTTPError as e:
        return e.code == 405
    except OSError:
        return False
    return False


def errores_recientes(lineas=4000):
    if not LOG.exists():
        return []
    with LOG.open('r', encoding='utf-8', errors='replace') as f:
        cola = f.readlines()[-lineas:]
    graves, ultima_conexion = [], -1
    for i, linea in enumerate(cola):
        if RECONECTADO.search(linea):
            ultima_conexion = i
        m = ERROR_LOG.search(linea)
        if m and any(g in m.group(1) for g in GRAVES):
            graves.append((i, m.group(1)[:90]))
        elif 'REST API server error:' in linea:
            graves.append((i, 'REST API server error (el puerto 8080 estaba ocupado)'))
    return [texto for i, texto in graves if i > ultima_conexion]


def antiguedad_ultimo_mensaje():
    fila = consulta(DB_MENSAJES, 'SELECT MAX(timestamp) FROM messages')
    if not fila or not fila[0]:
        return None
    try:
        visto = datetime.fromisoformat(fila[0])
    except ValueError:
        return None
    if visto.tzinfo is None:
        visto = visto.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - visto).total_seconds())


def quien(numero):
    """Traduce un teléfono al JID de su chat.

    WhatsApp no pone el número dentro de los JIDs con formato
    '@lid'. Para esos, buscar por número en messages.db no encuentra nada; la
    traducción está en la tabla whatsmeow_lid_map de la base de sesión.
    """
    digitos = re.sub(r'\D', '', numero)
    if not digitos:
        print('Pásame un número con código de país (58 para Venezuela).')
        return 1

    directo = consulta(DB_MENSAJES, 'SELECT jid FROM chats WHERE jid LIKE ?', (f'{digitos}@%',))
    if directo:
        jid = directo[0]
    else:
        # Primero el número tal cual; si no, sin código de país.
        fila = consulta(DB_SESION, 'SELECT lid FROM whatsmeow_lid_map WHERE pn LIKE ?', (f'{digitos}%',))
        if not fila and digitos.startswith('0'):
            # Formato local venezolano: sustituir el cero inicial por el código 58.
            digitos = digitos.lstrip('0')
            fila = consulta(DB_SESION, 'SELECT lid FROM whatsmeow_lid_map WHERE pn LIKE ?', (f'%{digitos}%',))
        if not fila and len(digitos) >= 7:
            fila = consulta(DB_SESION, 'SELECT lid FROM whatsmeow_lid_map WHERE pn LIKE ?', (f'%{digitos}%',))
        if not fila:
            print(f'No hay ningún chat para {digitos}.')
            return 1
        jid = fila[0] if '@' in fila[0] else fila[0] + '@lid'

    total = consulta(DB_MENSAJES, 'SELECT COUNT(*) FROM messages WHERE chat_jid = ?', (jid,))
    fotos = consulta(DB_MENSAJES, "SELECT COUNT(*) FROM messages WHERE chat_jid = ? AND media_type = 'image'", (jid,))
    print(f'{digitos} -> {jid}')
    print(f'  {total[0] if total else 0} mensajes, {fotos[0] if fotos else 0} fotos')
    return 0


def pid_del_bridge():
    escuchando, _ = netstat()
    return escuchando[0] if escuchando else None


def status(silencioso=False):
    def di(*a):
        if not silencioso:
            print(*a)

    problemas = []
    avisos = []

    sesion = consulta(DB_SESION, 'SELECT COUNT(*) FROM whatsmeow_device')
    if sesion is None:
        problemas.append('No existe la base de sesión. El bridge nunca se ha vinculado.')
    elif sesion[0] == 0:
        problemas.append('SESIÓN CERRADA. WhatsApp desvinculó este dispositivo: hay que escanear el QR otra vez.')

    escuchando, establecidas = netstat()
    if not escuchando:
        problemas.append(f'Nadie escucha en el puerto {PUERTO}: el bridge no está corriendo.')
    else:
        pid = escuchando[0]
        if len(escuchando) > 1:
            avisos.append(f'Hay {len(escuchando)} procesos en el puerto {PUERTO}. Debería haber uno solo.')
        if not responde_el_bridge():
            problemas.append(f'Algo ocupa el puerto {PUERTO} pero no responde como el bridge.')
        elif not any(p == pid and dest.rsplit(':', 1)[-1] in {'443', '5222'}
                     for p, dest in establecidas):
            problemas.append('El bridge está vivo pero SIN conexión a WhatsApp. Hay que reiniciarlo.')

    for error in errores_recientes()[-3:]:
        avisos.append(f'En el log, después de la última conexión: {error}')

    edad = antiguedad_ultimo_mensaje()
    if edad is not None and edad > 6 * 3600:
        avisos.append(f'El mensaje más reciente es de hace {edad / 3600:.1f} horas. De madrugada es normal.')

    if EXE.exists() and FUENTE.exists() and EXE.stat().st_mtime < FUENTE.stat().st_mtime:
        avisos.append('whatsapp-bridge.exe es más viejo que main.go. Recompilar: go build -o whatsapp-bridge.exe main.go')

    if problemas:
        di('ROJO — el bridge no sirve ahora mismo')
        for p in problemas:
            di('  *', p)
    elif avisos:
        di('AMARILLO — funciona, pero revisa esto')
    else:
        di('VERDE — el bridge está sano')

    for a in avisos:
        di('  -', a)

    if not problemas:
        if edad is not None:
            di(f'  Último mensaje recibido hace {edad / 60:.0f} min.')
        total = consulta(DB_MENSAJES, 'SELECT COUNT(*) FROM messages')
        if total:
            di(f'  Historial local: {total[0]} mensajes.')
    return 0 if not problemas else 1


def start():
    if pid_del_bridge():
        print('Ya hay un bridge corriendo. Nada que hacer.')
        return status()
    if not EXE.exists():
        print(f'No existe {EXE}. Compílalo con: go build -o whatsapp-bridge.exe main.go')
        return 1

    sesion = consulta(DB_SESION, 'SELECT COUNT(*) FROM whatsmeow_device')
    sin_sesion = sesion is None or sesion[0] == 0
    if sin_sesion:
        print('No hay sesión guardada: el bridge va a mostrar un código QR para escanear.')
        print('Se abre en primer plano. Escanéalo desde WhatsApp > Dispositivos vinculados.')
        print('Tienes 3 minutos antes de que se cierre solo.\n')
        return subprocess.call([str(EXE)], cwd=str(BRIDGE))

    log = LOG.open('a', encoding='utf-8')
    proc = subprocess.Popen(
        [str(EXE)], cwd=str(BRIDGE), stdout=log, stderr=log,
        creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0),
    )
    print(f'Arrancando el bridge (PID {proc.pid})...')
    for _ in range(30):
        time.sleep(1)
        if pid_del_bridge():
            break
    else:
        print('No llegó a abrir el puerto. Revisa bridge.log.')
        return 1
    return status()


def stop():
    pid = pid_del_bridge()
    if not pid:
        print('No hay ningún bridge corriendo.')
        return 0
    # Se mata el proceso que realmente escucha en 8080. Si se arrancó con `go run`,
    # matar el go.exe lanzador deja al bridge huérfano ocupando el puerto.
    subprocess.run(['taskkill', '/PID', pid, '/F'], capture_output=True)
    for _ in range(10):
        time.sleep(0.5)
        if not pid_del_bridge():
            print(f'Bridge detenido (PID {pid}).')
            return 0
    print(f'El PID {pid} sigue ocupando el puerto {PUERTO}.')
    return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('accion', choices=['status', 'start', 'stop', 'restart', 'quien'])
    parser.add_argument('numero', nargs='?', help='Teléfono a buscar, solo para "quien"')
    args = parser.parse_args()
    accion = args.accion

    if accion == 'quien':
        sys.exit(quien(args.numero or ''))
    elif accion == 'status':
        sys.exit(status())
    elif accion == 'start':
        sys.exit(start())
    elif accion == 'stop':
        sys.exit(stop())
    else:
        stop()
        sys.exit(start())
