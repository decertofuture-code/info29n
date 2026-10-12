#!/usr/bin/env python3
"""
Publica en X los anuncios de novedades de la web que estén en anuncios.json y aún no se hayan publicado.
Cada anuncio se publica como un hilo: el primer post y los siguientes como respuestas.

Formato de anuncios.json:
  {"anuncios": [
    {"id": "nombre-unico", "hilo": [
      {"texto": "Primer post…", "seccion": "inicio"},
      {"texto": "Segundo post…", "seccion": "comparador"}
    ]}
  ]}
"seccion" es la pestaña a la que enlaza el post (inicio, partidos, programas, comparador, votaciones,
corrupcion, medios, como-votar, metodo, buzon) o "" para enlazar a la portada.
Si un hilo se corta a medias, la siguiente ejecución lo continúa donde se quedó.
"""
import json, os, sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
from publicar_x import cabecera_oauth, claves_x, WEB

ANUNCIOS = RAIZ / "anuncios.json"
ESTADO = RAIZ / "estado.json"

def preparar(texto, seccion):
    enlace = WEB + (f"#{seccion}" if seccion else "")
    texto = texto.strip()
    if len(texto) > 280 - 24:
        texto = texto[:280 - 25].rstrip() + "…"
    return f"{texto}\n{enlace}"

def enviar(texto, responder_a=None):
    claves = claves_x()
    if os.getenv("X_ACTIVO", "").lower() != "si" or not claves:
        print(f"[PRUEBA, no publicado]{' (respuesta)' if responder_a else ''} {texto}\n")
        return None
    url = "https://api.x.com/2/tweets"
    cuerpo = {"text": texto}
    if responder_a:
        cuerpo["reply"] = {"in_reply_to_tweet_id": responder_a}
    req = Request(url, data=json.dumps(cuerpo).encode(), method="POST",
                  headers={"Authorization": cabecera_oauth("POST", url, claves), "Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30) as r:
            tid = json.loads(r.read())["data"]["id"]
            print(f"[PUBLICADO {tid}] {texto}\n")
            return tid
    except HTTPError as e:
        print(f"[ERROR {e.code}] {e.read().decode()[:400]}\nTexto: {texto}")
        return None

def main():
    anuncios = json.loads(ANUNCIOS.read_text(encoding="utf-8")).get("anuncios", [])
    estado = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {}
    hechos = estado.setdefault("anuncios", {})   # id -> lista de ids de los posts ya publicados
    pendientes = [a for a in anuncios if len(hechos.get(a["id"], [])) < len(a["hilo"])]
    if not pendientes:
        print("No hay anuncios pendientes.")
        return
    if os.getenv("X_ACTIVO", "").lower() != "si" or not claves_x():
        print("MODO PRUEBA: esto es lo que se publicaría (no se publica nada).\n")
        for a in pendientes:
            print(f"== {a['id']} ==")
            for i, post in enumerate(a["hilo"][len(hechos.get(a['id'], [])):]):
                print(f"[{'respuesta' if i or hechos.get(a['id']) else 'primer post'}] {preparar(post['texto'], post.get('seccion', ''))}\n")
        return
    for a in pendientes:
        publicados = hechos.get(a["id"], [])
        print(f"== {a['id']} ({len(publicados)}/{len(a['hilo'])} ya publicados) ==")
        for post in a["hilo"][len(publicados):]:
            tid = enviar(preparar(post["texto"], post.get("seccion", "")), publicados[-1] if publicados else None)
            if not tid:
                break
            publicados.append(tid)
        if publicados:
            hechos[a["id"]] = publicados
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
