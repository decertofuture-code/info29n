#!/usr/bin/env python3
"""
Publica en la cuenta de X del proyecto.

  python publicar_x.py diario    -> fechas del calendario electoral, cuenta atrás y resumen de noticias de ayer
  python publicar_x.py cambios   -> avisos de lo que ha cambiado en datos.json en el último commit (ediciones a mano)

Solo publica de verdad si la variable X_ACTIVO vale "si" y existen las cuatro claves.
Si no, escribe en el registro lo que habría publicado (modo prueba).
Cada post lleva el enlace a la sección correspondiente de la web (en X, un post con enlace cuesta unos 0,20 $).
"""
import base64, hashlib, hmac, json, os, secrets, subprocess, sys, time, urllib.parse
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent
DATOS = RAIZ / "datos.json"
ESTADO = RAIZ / "estado.json"
MADRID = ZoneInfo("Europe/Madrid")
HOY = datetime.now(MADRID).date()
ELECCIONES = date(2026, 11, 29)
MAX_POSTS_POR_EJECUCION = 3
WEB = "https://info29n.com/"

CALENDARIO = {
    "2026-10-31": "Estos días los ayuntamientos sortean quién formará las mesas electorales del 29N. Si te toca, te lo notificarán en mano. Es obligatorio salvo causa justificada, que puedes alegar en los 7 días siguientes a la notificación.",
    "2026-11-09": "Desde hoy, Correos empieza a entregar en mano la documentación del voto por correo a quienes lo han solicitado.",
    "2026-11-13": "Hoy empieza la campaña electoral de las elecciones generales del 29 de noviembre. Termina el viernes 27.",
    "2026-11-16": "Quedan 3 días para pedir el voto por correo: el plazo acaba el jueves 19 de noviembre. Se pide en cualquier oficina de Correos con el DNI o por internet con certificado digital.",
    "2026-11-19": "Hoy es el último día para pedir el voto por correo para el 29N: en cualquier oficina de Correos con el DNI o por internet con certificado digital.",
    "2026-11-25": "Hoy es el último día para enviar el voto por correo desde una oficina de Correos.",
    "2026-11-27": "Hoy termina la campaña electoral. Mañana, sábado, es jornada de reflexión.",
    "2026-11-28": "Jornada de reflexión. Mañana se vota de 9:00 a 20:00. Lleva el original de tu DNI, pasaporte o carné de conducir.",
    "2026-11-29": "Hoy se vota. Los colegios electorales están abiertos de 9:00 a 20:00. Necesitas el original de tu DNI, pasaporte o carné de conducir.",
}
CUENTA_ATRAS = {50, 30, 21, 14, 7, 3}
SECCION_CALENDARIO = {"2026-11-13": "inicio"}  # el resto enlaza a "Cómo votar"

# ---------------------------------------------------------------- X API (OAuth 1.0a)
def pct(s):
    return urllib.parse.quote(str(s), safe="~")

def cabecera_oauth(metodo, url, claves):
    p = {
        "oauth_consumer_key": claves["ck"], "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1", "oauth_timestamp": str(int(time.time())),
        "oauth_token": claves["at"], "oauth_version": "1.0",
    }
    base = "&".join([metodo.upper(), pct(url), pct("&".join(f"{pct(k)}={pct(v)}" for k, v in sorted(p.items())))])
    llave = f"{pct(claves['cs'])}&{pct(claves['as'])}"
    p["oauth_signature"] = base64.b64encode(hmac.new(llave.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{pct(k)}="{pct(v)}"' for k, v in sorted(p.items()))

def claves_x():
    c = {"ck": os.getenv("X_API_KEY"), "cs": os.getenv("X_API_SECRET"),
         "at": os.getenv("X_ACCESS_TOKEN"), "as": os.getenv("X_ACCESS_SECRET")}
    return c if all(c.values()) else None

def publicar(texto, seccion=""):
    # X cuenta cualquier enlace como 23 caracteres.
    enlace = WEB + (f"#{seccion}" if seccion else "")
    texto = texto.strip()
    if len(texto) > 280 - 24:
        texto = texto[:280 - 25].rstrip() + "…"
    texto = f"{texto}\n{enlace}"
    claves = claves_x()
    if os.getenv("X_ACTIVO", "").lower() != "si" or not claves:
        print(f"[PRUEBA, no publicado] {texto}")
        return False  # en modo prueba no se marca como publicado
    url = "https://api.x.com/2/tweets"
    req = Request(url, data=json.dumps({"text": texto}).encode(), method="POST",
                  headers={"Authorization": cabecera_oauth("POST", url, claves), "Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30) as r:
            print(f"[PUBLICADO] {texto}  -> {r.read().decode()[:200]}")
            return True
    except HTTPError as e:
        print(f"[ERROR {e.code}] {e.read().decode()[:400]}\nTexto: {texto}")
        return False

# ---------------------------------------------------------------- modo diario
def diario():
    datos = json.loads(DATOS.read_text(encoding="utf-8"))
    estado = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {}
    hechos = estado.setdefault("x_publicados", [])
    posts = []

    clave = HOY.isoformat()
    if clave in CALENDARIO and f"cal:{clave}" not in hechos:
        posts.append((f"cal:{clave}", CALENDARIO[clave], SECCION_CALENDARIO.get(clave, "como-votar")))
    faltan = (ELECCIONES - HOY).days
    if faltan in CUENTA_ATRAS and f"cuenta:{faltan}" not in hechos:
        posts.append((f"cuenta:{faltan}", f"Faltan {faltan} días para las elecciones generales del 29 de noviembre. Propuestas, votaciones y casos judiciales de cada partido, con fuentes:", "inicio"))

    ayer = HOY - timedelta(days=1)
    if f"resumen:{ayer}" not in hechos:
        n = sum(1 for x in datos.get("noticias", [])
                if datetime.fromisoformat(x["fecha"]).astimezone(MADRID).date() == ayer)
        if n >= 5:
            posts.append((f"resumen:{ayer}",
                          f"Ayer se publicaron {n} titulares sobre los partidos y la campaña en los medios que seguimos. "
                          "Los tienes todos, con enlace a cada noticia, aquí:", "medios"))

    for clave_post, texto, seccion in posts[:MAX_POSTS_POR_EJECUCION]:
        if publicar(texto, seccion):
            hechos.append(clave_post)
    estado["x_publicados"] = hechos[-200:]
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# ---------------------------------------------------------------- modo cambios
def version_anterior():
    try:
        return json.loads(subprocess.run(["git", "show", "HEAD^:datos.json"], cwd=RAIZ,
                                         capture_output=True, text=True, check=True).stdout)
    except Exception:
        return None

def cambios():
    nuevo = json.loads(DATOS.read_text(encoding="utf-8"))
    viejo = version_anterior()
    if viejo is None:
        print("No hay versión anterior con la que comparar.")
        return
    nombre = {p["id"]: p["name"] for p in nuevo.get("partidos", [])}
    tema = {t["id"]: t["name"] for t in nuevo.get("temas", [])}
    estados = nuevo.get("estados", {})
    avisos = []

    # Medidas de los programas
    mv, mn = viejo.get("medidas", {}), nuevo.get("medidas", {})
    for pid in mn:
        for tid, lista in mn[pid].items():
            antes = mv.get(pid, {}).get(tid, [])
            if lista == antes:
                continue
            extra = len(lista) - len(antes)
            if extra > 0:
                avisos.append((f"Añadidas {extra} {'medida' if extra == 1 else 'medidas'} de {nombre.get(pid, pid)} sobre {tema.get(tid, tid).lower()} en la sección de propuestas.", "programas"))
            else:
                avisos.append((f"Actualizadas las propuestas de {nombre.get(pid, pid)} sobre {tema.get(tid, tid).lower()}.", "programas"))

    # Votaciones
    vistas = {v["title"] for v in viejo.get("votaciones", [])}
    for v in nuevo.get("votaciones", []):
        if v["title"] not in vistas:
            avisos.append((f"Nueva votación en la web: {v['title']}. Puedes ver qué votó cada partido.", "votaciones"))

    # Casos judiciales
    antes = {(c["party"], c["title"]): c for c in viejo.get("casos", [])}
    for c in nuevo.get("casos", []):
        k = (c["party"], c["title"])
        if k not in antes:
            avisos.append((f"Nuevo caso en la sección de corrupción: {c['title']} ({nombre.get(c['party'], c['party'])}). "
                           f"Estado: {estados.get(c['status'], c['status']).lower()}.", "corrupcion"))
        elif antes[k].get("status") != c.get("status"):
            avisos.append((f"Actualizado el estado del caso {c['title']}: {estados.get(c['status'], c['status']).lower()}.", "corrupcion"))

    if not avisos:
        print("Sin cambios que anunciar (las noticias no se anuncian una a una).")
        return
    if len(avisos) > MAX_POSTS_POR_EJECUCION:
        publicar(f"Hemos actualizado la web con {len(avisos)} cambios en propuestas, votaciones o casos judiciales. Todo, con sus fuentes:")
    else:
        for texto, seccion in avisos:
            publicar(texto, seccion)

if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else ""
    {"diario": diario, "cambios": cambios}.get(modo, lambda: sys.exit("Uso: publicar_x.py diario|cambios"))()
