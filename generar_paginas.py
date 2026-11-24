#!/usr/bin/env python3
"""
Genera páginas fijas (HTML ya escrito, sin depender de JavaScript) a partir de datos.json, para que
Google y las redes sociales puedan leer el contenido:

  partido/<id>/index.html      una página por partido
  tema/<id>/index.html         una página por tema
  comparador/<id>/index.html   una página por pregunta del comparador, con su imagen para compartir
  img/pregunta-<id>.png        la imagen de cada pregunta (1200 x 630)
  sitemap.xml y robots.txt

Las páginas no incluyen noticias ni fechas de actualización automáticas, para que solo cambien
cuando cambia el contenido de verdad (y así no se publique la web en Netlify sin necesidad).
"""
import html, json, shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

RAIZ = Path(__file__).resolve().parent
WEB = "https://info29n.com"
d = json.loads((RAIZ / "datos.json").read_text(encoding="utf-8"))
PARTIDOS, TEMAS = d["partidos"], d["temas"]
MEDIDAS, VOTOS = d.get("medidas", {}), d.get("votaciones", [])
ESTADOS, PREGUNTAS, PROGRAMAS = d.get("estados", {}), d.get("preguntas", []), d.get("programas", {})
NOMBRE = {p["id"]: p["name"] for p in PARTIDOS}
TEMA = {t["id"]: t["name"] for t in TEMAS}
COLOR_PARTIDO = {p["id"]: p.get("color", "#5A6678") for p in PARTIDOS}
# Iconos de cada tema (mismos trazos que en la web interactiva)
ICONO = {
    "vivienda": '<path d="M3 11 12 4l9 7"/><path d="M5 9.5V20h14V9.5"/><path d="M10 20v-5h4v5"/>',
    "economia": '<path d="M3 9h18l-2.2 10.2a1 1 0 0 1-1 .8H6.2a1 1 0 0 1-1-.8z"/><path d="M8 9l3-5M16 9l-3-5M9 13v3M12 13v3M15 13v3"/>',
    "inmigracion": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3.2 3.2 3.2 14.8 0 18M12 3c-3.2 3.2-3.2 14.8 0 18"/>',
    "politica": '<path d="M3 9l9-5 9 5"/><path d="M4 9h16M6 10v7M10 10v7M14 10v7M18 10v7M4 17h16M3 20h18"/>',
    "empleo": '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7M3 12.5h18"/>',
    "sanidad": '<path d="M9.5 3.5h5v6h6v5h-6v6h-5v-6h-6v-5h6z"/>',
}
def icono(tid, cls="ico"):
    return f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">{ICONO[tid]}</svg>' if tid in ICONO else ""
def cuenta(pid, tid):
    n = len(visibles(pid, tid))
    return f"<small>{n} {'medida' if n == 1 else 'medidas'}</small>" if n else ""
def franja():
    return '<div class="franja" aria-hidden="true">' + "".join(f'<i data-tema="{t["id"]}"></i>' for t in TEMAS) + "</div>"
def chip(tid):
    return f'<span class="chip" data-tema="{tid}">{icono(tid)}{e(TEMA.get(tid, ""))}</span>'
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
POSTURA = {"si": ("si", "Sí"), "no": ("no", "No"), "matiz": ("matiz", "Con matices"), "sin": ("sin", "No se pronuncia"), "pend": ("pend", "Programa pendiente de incorporar")}

e = lambda t: html.escape(str(t or ""), quote=True)

def fecha(iso):
    a, m, dd = iso[:10].split("-")
    return f"{int(dd)} de {MESES[int(m) - 1]} de {a}"

def visibles(pid, tid):
    return [m for m in MEDIDAS.get(pid, {}).get(tid, []) if m.get("verificada", True) is not False]

PROG_DE = {p["id"]: p["programa_de"] for p in PARTIDOS if p.get("programa_de")}
PROG_DE_N = {p["id"]: p.get("programa_de_nombre") or NOMBRE.get(p["programa_de"], p["programa_de"]) for p in PARTIDOS if p.get("programa_de")}

def etiqueta(k, pid, corta=False):
    if k == "pend" and pid in PROG_DE:
        return f"Con el {PROG_DE_N[pid]}" if corta else f"Programa del {PROG_DE_N[pid]}"
    return POSTURA[k][1]

def postura(q, pid):
    if pid not in PROGRAMAS:
        return "pend", None
    x = q.get("posturas", {}).get(pid)
    if not x or x.get("verificada") is False or x.get("postura") not in POSTURA:
        return "sin", None
    return x["postura"], x

def voto(v, pid):
    if pid in v.get("si", []): return "si", v.get("yesLabel", "A favor")
    if pid in v.get("no", []): return "no", v.get("noLabel", "En contra")
    return "nd", "Sin dato"

# ------------------------------------------------------------------ plantilla
def pagina(ruta, titulo, descripcion, cuerpo, interactiva, imagen="/og-image.png"):
    url = f"{WEB}/{ruta}"
    doc = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{e(titulo)}</title>
<meta name="description" content="{e(descripcion)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="info29n">
<meta property="og:locale" content="es_ES">
<meta property="og:url" content="{url}">
<meta property="og:title" content="{e(titulo)}">
<meta property="og:description" content="{e(descripcion)}">
<meta property="og:image" content="{WEB}{imagen}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(titulo)}">
<meta name="twitter:description" content="{e(descripcion)}">
<meta name="twitter:image" content="{WEB}{imagen}">
<link rel="preload" href="/atkinson-400.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/estatico.css">
</head>
<body>
<a class="skip" href="#contenido">Saltar al contenido</a>
<header class="top"><a class="brand" href="/">info<b>29n</b></a><a class="go" href="/{interactiva}">Ver en la web interactiva</a></header>
<nav class="secciones" aria-label="Secciones de la web"><a href="/#partidos">Partidos</a><a href="/#programas">Propuestas</a><a href="/#comparador">Comparador</a><a href="/#votaciones">Votaciones</a><a href="/#medios">Noticias</a><a href="/#como-votar">Cómo votar</a></nav>
<main id="contenido">
{cuerpo}
</main>
<footer>
  <p>info29n.com reúne qué propone cada partido, qué ha votado y las últimas noticias sobre él, con enlace a la fuente de cada dato. Sin publicidad y financiada por su responsable. Esta web no pide ni recomienda el voto.</p>
  <nav class="idx" aria-label="Más páginas">{indice()}</nav>
  <p><a href="/#metodo">Cómo hacemos esta web</a> · <a href="/#buzon">Buzón de sugerencias</a> · <a href="/privacidad.html">Política de privacidad</a></p>
</footer>
</body>
</html>
"""
    destino = RAIZ / ruta / "index.html"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(doc, encoding="utf-8")
    return url

SIMBOLO = {"si": "✓", "no": "✕", "matiz": "≈", "sin": "–", "pend": "…", "coal": "…"}

def indice():
    p = " · ".join(f'<a href="/partido/{x["id"]}/">{e(x["name"])}</a>' for x in PARTIDOS)
    t = " · ".join(f'<a href="/tema/{x["id"]}/">{e(x["name"])}</a>' for x in TEMAS)
    q = " · ".join(f'<a href="/comparador/{x["id"]}/">{e(x["pregunta"])}</a>' for x in PREGUNTAS)
    return f"<p><b>Partidos:</b> {p}</p><p><b>Temas:</b> {t}</p>" + (f"<p><b>Comparador:</b> {q}</p>" if q else "")

def medida_li(m):
    pag = f"Programa, pág. {m['pagina']}" if m.get("pagina") else "Fuente"
    cita = f'<blockquote>«{e(m["cita"])}»</blockquote>' if m.get("cita") else ""
    return f'<li>{e(m["texto"])} <a class="src" href="{e(m["fuente"])}" rel="noopener">{pag}</a>{cita}</li>'

def fila_postura(q, pid):
    k, x = postura(q, pid)
    cita = ""
    if x and x.get("cita"):
        cita = f'<small>«{e(x["cita"])}»' + (f' (pág. {x["pagina"]})' if x.get("pagina") else "") + "</small>"
    return f'<li><span>{e(q["pregunta"])}{cita}</span><span class="badge p-{k}"><i aria-hidden="true">{SIMBOLO.get(k, "")}</i>{etiqueta(k, pid)}</span></li>'

def fila_voto(v, pid):
    c, l = voto(v, pid)
    return (f'<li data-tema="{v["topic"]}"><span><a href="/tema/{v["topic"]}/">{e(v["title"])}</a><small>{fecha(v["date"])} · {e(v["result"])}</small></span>'
            f'<span class="badge v-{c}">{e(l)}</span></li>')

# ------------------------------------------------------------------ páginas por partido
def paginas_partido():
    urls = []
    for p in PARTIDOS:
        pid, n = p["id"], p["name"]
        cand = f"Candidato: {e(p['candidato'])}." if p.get("candidato") else "Candidatura por confirmar."
        if any(visibles(pid, t["id"]) for t in TEMAS):
            prop = "".join(
                f'<section class="card" data-tema="{t["id"]}"><h3 class="th">{icono(t["id"])}<span>{e(t["name"])}</span>{cuenta(pid, t["id"])}</h3>' +
                (f'<ul>{"".join(medida_li(m) for m in visibles(pid, t["id"]))}</ul>' if visibles(pid, t["id"]) else '<p class="muted">Su programa no incluye medidas sobre este tema.</p>') +
                "</section>" for t in TEMAS)
            prop = f'<div class="grid">{prop}</div>'
        elif p.get("programa_nota") and pid not in PROGRAMAS:
            de = p.get("programa_de", "")
            prop = f'<p class="muted">{e(p["programa_nota"])} <a href="/partido/{de}/">Ver las propuestas del {e(p.get("programa_de_nombre") or NOMBRE.get(de, de))}</a>.</p>'
        else:
            prop = '<p class="muted">Aún no hemos incorporado a esta web su programa electoral para el 29N. Cuando lo hagamos, aquí estarán sus medidas por tema, cada una con su cita literal y la página del programa.</p>'
        if pid in PROGRAMAS and PREGUNTAS:
            filas = "".join(fila_postura(q, pid) for q in PREGUNTAS)
            comp = f'<section><h2>Su postura en el comparador</h2><ul class="rows">{filas}</ul></section>'
        else:
            comp = ""
        if p.get("sin_escano"):
            vot = f'<p class="muted">{e(p.get("votos_nota") or "No tenía diputados en el Congreso en esta legislatura, así que no hay votaciones suyas.")}</p>'
        else:
            vot = '<ul class="rows">' + "".join(fila_voto(v, pid) for v in VOTOS) + "</ul>"
        cuerpo = f"""<header class="head phead" style="--pc:{COLOR_PARTIDO[pid]}"><p class="kicker">Elecciones generales del 29 de noviembre</p><h1><span class="p-dot" aria-hidden="true"></span>{e(n)}</h1>
<p class="muted">Se presenta en: {e(p.get("scope", ""))}. {cand}</p>{franja()}</header>
<section><h2>Propuestas</h2>{prop}</section>
{comp}
<section><h2>Qué votó en esta legislatura</h2>{vot}</section>"""
        desc = f"Qué propone {n} para las elecciones del 29 de noviembre, qué ha votado en el Congreso y su postura en las cuestiones clave. Con fuentes."
        urls.append(pagina(f"partido/{pid}/", f"{n}: programa, propuestas y votaciones · 29N", desc, cuerpo, f"#partido-{pid}"))
    return urls

# ------------------------------------------------------------------ páginas por tema
def paginas_tema():
    urls = []
    for t in TEMAS:
        tid = t["id"]
        bloques = []
        for p in PARTIDOS:
            ms = visibles(p["id"], tid)
            if ms:
                cont = f'<ul>{"".join(medida_li(m) for m in ms)}</ul>'
            elif p["id"] in PROGRAMAS:
                cont = '<p class="muted">Su programa no incluye medidas sobre este tema.</p>'
            elif p.get("programa_de"):
                de = p["programa_de"]
                cont = f'<p class="muted">Comparte el programa del {e(p.get("programa_de_nombre") or NOMBRE.get(de, de))}: <a href="/partido/{de}/">ver sus medidas</a>.</p>'
            else:
                cont = '<p class="muted">Programa aún no incorporado a esta web.</p>'
            bloques.append(f'<section class="card" style="--pc:{COLOR_PARTIDO[p["id"]]}"><h3><a class="pn" href="/partido/{p["id"]}/">{e(p["name"])}</a></h3>{cont}</section>')
        vs = [v for v in VOTOS if v["topic"] == tid]
        vot = ""
        for v in vs:
            si = ", ".join(NOMBRE.get(x, x) for x in v.get("si", []))
            no = ", ".join(NOMBRE.get(x, x) for x in v.get("no", []))
            nd = ", ".join(p["name"] for p in PARTIDOS if not p.get("sin_escano") and p["id"] not in v.get("si", []) + v.get("no", []))
            res = "ok" if v["result"].lower().startswith("aprobad") else "ko" if (v["result"].lower().startswith("rechazad") or "decay" in v["result"].lower()) else ""
            vot += f"""<article class="card voto" data-tema="{tid}"><h3>{e(v["title"])}</h3><p class="muted">{fecha(v["date"])}</p><p>{e(v["what"])}</p><p><span class="res {res}">{e(v["result"])}</span></p>
<dl class="dl"><dt class="v-si">{e(v.get("yesLabel","A favor"))}</dt><dd>{e(si)}</dd><dt class="v-no">{e(v.get("noLabel","En contra"))}</dt><dd>{e(no)}</dd>{f'<dt class="v-nd">Sin dato</dt><dd>{e(nd)}</dd>' if nd else ''}</dl>
<p class="srcs"><a href="{e(v["src"])}" rel="noopener">Ver la noticia de la votación</a></p></article>"""
        qs = [q for q in PREGUNTAS if q["tema"] == tid]
        comp = "".join(f'<li><a href="/comparador/{q["id"]}/">{e(q["pregunta"])}</a></li>' for q in qs)
        cuerpo = f"""<header class="head tema-head" data-tema="{tid}">{icono(tid, "ico-grande")}<div><p class="kicker">Elecciones generales del 29 de noviembre</p><h1>{e(t["name"])}: qué propone cada partido</h1>
<p class="muted">{e(t.get("desc",""))}</p></div></header>
<section><h2>Propuestas de cada partido</h2><div class="grid" data-tema="{tid}">{"".join(bloques)}</div></section>
{f'<section><h2>En el comparador</h2><ul class="links">{comp}</ul></section>' if comp else ''}
{f'<section><h2>Qué se votó en el Congreso</h2>{vot}</section>' if vot else ''}"""
        desc = f"{t['name']}: qué propone cada partido para las elecciones del 29 de noviembre y qué votó en el Congreso. Con la cita y la página de cada programa."
        urls.append(pagina(f"tema/{tid}/", f"{t['name']}: qué propone cada partido · 29N", desc, cuerpo, f"#tema-{tid}"))
    return urls

# ------------------------------------------------------------------ comparador + imágenes
def fuente(bold, size):
    return ImageFont.truetype(str(RAIZ / f"Atkinson-{'Bold' if bold else 'Regular'}.ttf"), size)

COLOR = {"si": "#1E7B4C", "no": "#B3261E", "matiz": "#8A6D1F", "sin": "#5A6678", "pend": "#8A93A3"}
CORTO = {"pp": "PP", "cc": "CC", "bildu": "EH Bildu", "salf": "SALF", "fo": "F. Obrero", "sumar": "F. Amplio", "adelante": "Adelante"}
TIRA = ["#2457C5", "#7C3AED", "#0E7C7B", "#7C5E3C", "#B45F06", "#8E2D5A", "#4B53BC", "#C2410C"]

def partir(draw, texto, f, ancho):
    lineas, actual = [], ""
    for w in texto.split():
        prueba = f"{actual} {w}".strip()
        if draw.textlength(prueba, font=f) <= ancho:
            actual = prueba
        else:
            lineas.append(actual); actual = w
    return lineas + [actual]

def imagen_pregunta(q):
    W, H = 1200, 630
    im = Image.new("RGB", (W, H), "#F6F7F9"); dr = ImageDraw.Draw(im)
    for i, c in enumerate(TIRA):
        dr.rectangle([i * W // len(TIRA), 0, (i + 1) * W // len(TIRA), 12], fill=c)
    dr.text((60, 44), f"COMPARADOR · {TEMA.get(q['tema'], '').upper()}", font=fuente(True, 24), fill="#5A6678")
    size = 46
    while True:
        lin = partir(dr, q["pregunta"], fuente(True, size), W - 120)
        if len(lin) <= 2 or size <= 34: break
        size -= 4
    y = 82
    for l in lin[:3]:
        dr.text((60, y), l, font=fuente(True, size), fill="#1B2A41"); y += int(size * 1.15)
    y += 18
    cols, fil = 3, (len(PARTIDOS) + 2) // 3
    cw, rh = (W - 120) // cols, min(80, (H - y - 80) // max(fil, 1))
    fn, fb = fuente(True, 27), fuente(True, 21)
    for i, p in enumerate(PARTIDOS):
        k, _ = postura(q, p["id"])
        x0, y0 = 60 + (i % cols) * cw, y + (i // cols) * rh
        nombre = CORTO.get(p["id"], p["name"])
        dr.text((x0, y0 + 8), nombre, font=fn, fill="#1B2A41")
        lab = POSTURA[k][1] if k != "pend" else (etiqueta(k, p["id"], True) if p["id"] in PROG_DE else "Pendiente")
        tw = dr.textlength(lab, font=fb)
        bx1 = x0 + cw - 24; bx0 = bx1 - tw - 28
        if k == "pend":
            dr.rounded_rectangle([bx0, y0 + 6, bx1, y0 + 42], radius=18, outline=COLOR[k], width=2)
            dr.text((bx0 + 14, y0 + 13), lab, font=fb, fill=COLOR[k])
        else:
            dr.rounded_rectangle([bx0, y0 + 6, bx1, y0 + 42], radius=18, fill=COLOR[k])
            dr.text((bx0 + 14, y0 + 13), lab, font=fb, fill="#FFFFFF")
    dr.text((60, H - 56), "Según su programa electoral, con la cita literal en", font=fuente(False, 22), fill="#5A6678")
    dr.text((W - 60 - dr.textlength("info29n.com", font=fuente(True, 30)), H - 62), "info29n.com", font=fuente(True, 30), fill="#2457C5")
    destino = RAIZ / "img" / f"pregunta-{q['id']}.png"
    destino.parent.mkdir(exist_ok=True)
    im.save(destino, optimize=True)
    return f"/img/pregunta-{q['id']}.png"

def paginas_comparador():
    urls = []
    for q in PREGUNTAS:
        img = imagen_pregunta(q)
        filas = ""
        for p in PARTIDOS:
            k, x = postura(q, p["id"])
            cita = ""
            if x and x.get("cita"):
                enlace = f' <a class="src" href="{e(x.get("fuente"))}" rel="noopener">{"Programa, pág. " + str(x.get("pagina")) if x.get("pagina") else "Fuente"}</a>' if x.get("fuente") else ""
                cita = f'<blockquote>«{e(x["cita"])}»{enlace}</blockquote>'

            filas += f'<li style="--pc:{COLOR_PARTIDO[p["id"]]}"><span><a class="pn" href="/partido/{p["id"]}/">{e(p["name"])}</a>{cita}</span><span class="badge p-{k}"><i aria-hidden="true">{SIMBOLO.get(k, "")}</i>{etiqueta(k, p["id"])}</span></li>'
        n = len(PROGRAMAS)
        estado = f"Programas analizados: {n} de {len(PARTIDOS)}." if n else "Todavía no se ha publicado ningún programa. Las posturas aparecerán a medida que los partidos los presenten."
        cuerpo = f"""<header class="head" data-tema="{q["tema"]}"><p class="kicker">Comparador · <a class="chip" href="/tema/{q["tema"]}/">{icono(q["tema"])}{e(TEMA.get(q["tema"], ""))}</a></p><h1>{e(q["pregunta"])}</h1>
<p class="muted">{e(q["explicacion"])}</p><p class="note">{estado} La postura se basa solo en lo que dice el programa electoral de cada partido.</p></header>
<ul class="rows cmp" data-tema="{q["tema"]}">{filas}</ul>"""
        desc = f"{q['pregunta']} La postura de cada partido para el 29N según su programa electoral, con la cita literal."
        urls.append(pagina(f"comparador/{q['id']}/", f"{q['pregunta']} · Qué responde cada partido · 29N", desc, cuerpo, f"#pregunta-{q['id']}", img))
    return urls

# ------------------------------------------------------------------ principal
def main():
    for carpeta in ("partido", "tema", "comparador", "img"):
        shutil.rmtree(RAIZ / carpeta, ignore_errors=True)
    urls = [f"{WEB}/"] + paginas_partido() + paginas_tema() + paginas_comparador()
    (RAIZ / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
        "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls) + "</urlset>\n", encoding="utf-8")
    (RAIZ / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {WEB}/sitemap.xml\n", encoding="utf-8")
    print(f"{len(urls)} páginas generadas.")

if __name__ == "__main__":
    main()
