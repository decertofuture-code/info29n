#!/usr/bin/env python3
"""
Actualiza site/datos.json con titulares de campaña y prepara un informe diario
de cosas que conviene revisar a mano (casos judiciales, programas, listas).

Publica solo: titulares con enlace (sección Noticias).
Nunca publica solo: medidas de programas ni casos de corrupción. Eso va al informe.
"""
import json, re, sys, html, os
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

RAIZ = Path(__file__).resolve().parent
DATOS = RAIZ / "datos.json"
FUENTES = RAIZ / "fuentes.json"
ESTADO = RAIZ / "estado.json"
INFORME = RAIZ / "informe.md"
UA = "info29n.com (actualizador de noticias; contacto en la web)"
AHORA = datetime.now(timezone.utc)

def descargar(url, timeout=25):
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=timeout) as r:
        return r.read()

def texto(el, *tags):
    for t in tags:
        x = el.find(t)
        if x is not None and (x.text or "").strip():
            return x.text.strip()
        if x is not None and x.get("href"):
            return x.get("href")
    return ""

def fecha_item(raw):
    if not raw:
        return AHORA
    try:
        d = parsedate_to_datetime(raw)
    except Exception:
        try:
            d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return AHORA
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d

def leer_feed(url):
    raiz = ET.fromstring(descargar(url))
    ns = {"a": "http://www.w3.org/2005/Atom"}
    items = raiz.findall(".//item") or raiz.findall(".//a:entry", ns)
    salida = []
    for it in items:
        titulo = texto(it, "title", "{http://www.w3.org/2005/Atom}title")
        enlace = texto(it, "link", "{http://www.w3.org/2005/Atom}link")
        fecha = texto(it, "pubDate", "{http://purl.org/dc/elements/1.1/}date",
                      "{http://www.w3.org/2005/Atom}updated", "{http://www.w3.org/2005/Atom}published")
        if titulo and enlace.startswith("http"):
            salida.append({"titulo": html.unescape(re.sub(r"\s+", " ", titulo)),
                           "url": enlace.strip(), "fecha": fecha_item(fecha)})
    return salida

def patron(palabra, prefijo=False):
    # Si la palabra lleva alguna mayúscula (nombre propio o siglas) se exige igual:
    # así "Sumar" o "Podemos" no coinciden con los verbos "sumar" o "podemos".
    flags = 0 if any(c.isupper() for c in palabra) else re.I
    fin = "" if prefijo else r"(?![\wÁÉÍÓÚÑáéíóúñ])"  # prefijo=True: "candidat" vale para candidato, candidatura...
    return re.compile(r"(?<![\wÁÉÍÓÚÑáéíóúñ])" + re.escape(palabra) + fin, flags)

def inicio_de_frase(titulo, pos):
    antes = titulo[:pos].rstrip()
    return antes == "" or antes[-1] in "¿¡«\"“'(.:;!?"

def partidos_de(titulo, pats, ambiguas, contexto):
    """Partidos mencionados en un titular.
    Las palabras ambiguas (p. ej. "Podemos", que también es un verbo) solo cuentan a principio
    de frase si el titular tiene además alguna palabra de contexto político."""
    hay_contexto = None
    res = []
    for pid, ps in pats.items():
        ok = False
        for palabra, p in ps:
            for m in p.finditer(titulo):
                if palabra in ambiguas and inicio_de_frase(titulo, m.start()):
                    if hay_contexto is None:
                        hay_contexto = any(c.search(titulo) for c in contexto)
                    if not hay_contexto:
                        continue
                ok = True
                break
            if ok:
                break
        if ok:
            res.append(pid)
    return res

def norm(t):
    return re.sub(r"[^\wáéíóúñ]+", " ", t.lower()).strip()

def main():
    fuentes = json.loads(FUENTES.read_text(encoding="utf-8"))
    datos = json.loads(DATOS.read_text(encoding="utf-8"))
    estado = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {}
    pats = {pid: [(w, patron(w)) for w in ws] for pid, ws in fuentes["partidos"].items()}
    ambiguas = set(fuentes.get("ambiguas", []))
    contexto = [patron(w, prefijo=True) for w in fuentes.get("contexto_politico", [])]
    clasificar = lambda t: partidos_de(t, pats, ambiguas, contexto)
    revisar = [patron(w, prefijo=True) for w in fuentes.get("revisar", [])]

    # Se vuelven a clasificar las noticias ya publicadas por si han cambiado las reglas;
    # las que ya no mencionan a ningún partido se retiran.
    previas_orig = datos.get("noticias", [])
    previas = []
    for n in previas_orig:
        ps = clasificar(n["titulo"])
        if ps:
            previas.append({**n, "partidos": ps})
    vistos_url = {n["url"] for n in previas}
    vistos_tit = {norm(n["titulo"]) for n in previas}
    nuevas, fallos, para_revisar = [], [], []

    for f in fuentes["feeds"]:
        try:
            items = leer_feed(f["url"])
        except Exception as e:
            fallos.append(f"{f['medio']}: {type(e).__name__} {e}"[:200])
            continue
        for it in items:
            partidos = clasificar(it["titulo"])
            if not partidos:
                continue
            if it["url"] in vistos_url or norm(it["titulo"]) in vistos_tit:
                continue
            vistos_url.add(it["url"]); vistos_tit.add(norm(it["titulo"]))
            n = {"titulo": it["titulo"], "medio": f["medio"], "url": it["url"],
                 "fecha": it["fecha"].astimezone(timezone.utc).isoformat(timespec="minutes"),
                 "partidos": partidos}
            nuevas.append(n)
            if any(p.search(it["titulo"]) for p in revisar):
                para_revisar.append(n)

    limite = AHORA - timedelta(days=fuentes.get("dias_a_conservar", 14))
    todas = [n for n in previas + nuevas if datetime.fromisoformat(n["fecha"]) >= limite]
    todas.sort(key=lambda n: n["fecha"], reverse=True)
    todas = todas[: fuentes.get("max_noticias", 300)]

    cambiado = todas != previas_orig
    if cambiado:
        datos["noticias"] = todas
        datos["actualizado"] = AHORA.isoformat(timespec="minutes")
        DATOS.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    ca_nuevos, ca_error = [], None  # Casos Aislados desactivado

    # --- Informe diario ---
    pid2name = {p["id"]: p["name"] for p in datos["partidos"]}
    lineas = []
    if para_revisar:
        lineas.append("## Titulares que pueden afectar a programas, listas o casos judiciales\n")
        lineas.append("Ya están publicados en Noticias. Revisa si hay que actualizar Propuestas o Corrupción.\n")
        for n in para_revisar:
            ps = ", ".join(pid2name.get(p, p) for p in n["partidos"])
            lineas.append(f"- [ ] [{n['titulo']}]({n['url']}) · {n['medio']} · {ps}")
        lineas.append("")
    if ca_nuevos:
        lineas.append("## Casos Aislados: casos nuevos o actualizados\n")
        lineas.append("Solo como pista. Antes de añadir nada, comprueba el estado judicial en prensa o en la resolución.\n")
        for nombre, fecha, url in ca_nuevos:
            lineas.append(f"- [ ] [{nombre}]({url}) · actualizado el {fecha}")
        lineas.append("")
    if fallos or ca_error:
        lineas.append("## Fuentes que han fallado\n")
        for f in fallos:
            lineas.append(f"- {f}")
        if ca_error:
            lineas.append(f"- Casos Aislados: {ca_error}")
        lineas.append("")
    if lineas:
        cab = f"Noticias nuevas en esta ejecución: {len(nuevas)}. Total publicadas: {len(todas)}.\n"
        INFORME.write_text(cab + "\n" + "\n".join(lineas), encoding="utf-8")
    elif INFORME.exists():
        INFORME.unlink()

    print(f"nuevas={len(nuevas)} total={len(todas)} revisar={len(para_revisar)} "
          f"casos_aislados={len(ca_nuevos)} fallos={len(fallos)} cambiado={cambiado}")

if __name__ == "__main__":
    sys.exit(main())
