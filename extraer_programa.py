#!/usr/bin/env python3
"""
Extrae las medidas de un programa electoral (PDF o página web) con la API de Claude y prepara un borrador en datos.json.

Uso (normalmente desde GitHub Actions, workflow "Procesar programa"):
  PARTIDO=pp URL_PDF=https://... ANTHROPIC_API_KEY=... python extraer_programa.py

Qué hace:
  1. Descarga el PDF y lee el texto de cada página. Si la dirección es una página web, lee esa página
     y las que cuelgan de la misma sección del sitio (cada página web cuenta como una «página»).
  2. Lo envía a Claude por bloques de páginas y pide, para cada uno de los temas de la web,
     las medidas concretas con una CITA LITERAL y su NÚMERO DE PÁGINA, y la postura del partido
     en las preguntas del comparador si el texto la expresa claramente.
  3. Comprueba automáticamente que cada cita aparece de verdad en la página indicada.
     Las que no se pueden comprobar se marcan como "verificada": false y la web NO las muestra
     hasta que alguien las revise.
  4. Si hay demasiadas medidas en un tema, pide a Claude que elija las más concretas.
  5. Escribe el resultado en datos.json y un informe (informe_programa.md) para revisar antes de publicar.
"""
import base64, io, json, os, re, sys, time, unicodedata
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urldefrag, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

from pypdf import PdfReader, PdfWriter

RAIZ = Path(__file__).resolve().parent
DATOS = RAIZ / "datos.json"
INFORME = RAIZ / "informe_programa.md"
MODELO = os.getenv("MODELO", "claude-sonnet-5-5")
PAGINAS_POR_BLOQUE = int(os.getenv("PAGINAS_POR_BLOQUE", "25"))
MAX_POR_TEMA = int(os.getenv("MAX_POR_TEMA", "10"))
MAX_PAGINAS_WEB = int(os.getenv("MAX_PAGINAS_WEB", "80"))
CAB = {"User-Agent": "Mozilla/5.0 (compatible; info29n.com; +https://info29n.com)", "Accept": "application/pdf,text/html,*/*"}
HOY = datetime.now(ZoneInfo("Europe/Madrid")).date().isoformat()

# ------------------------------------------------------------------ utilidades
def norm(t):
    t = unicodedata.normalize("NFKC", t or "")
    t = re.sub(r"-\s*\n\s*", "", t)            # palabras cortadas con guion al final de línea
    t = t.lower().replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    t = re.sub(r"[^\w%€$.,;:'\" ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()

def cita_en_pagina(cita, textos, pagina):
    c = norm(cita)
    if len(c) < 12:
        return False
    for p in (pagina, pagina - 1, pagina + 1):
        if 1 <= p <= len(textos) and c in norm(textos[p - 1]):
            return True
    # tolerancia: la cita puede saltar de una página a la siguiente
    if 1 <= pagina < len(textos) and c in norm(textos[pagina - 1] + " " + textos[pagina]):
        return True
    return False

class RespuestaNoValida(Exception):
    pass

def claude(system, contenido, max_tokens=16000):
    clave = os.environ["ANTHROPIC_API_KEY"]
    cuerpo = {"model": MODELO, "max_tokens": max_tokens, "system": system,
              "messages": [{"role": "user", "content": contenido}]}
    for intento in range(4):
        req = Request("https://api.anthropic.com/v1/messages", data=json.dumps(cuerpo).encode(), method="POST",
                      headers={"x-api-key": clave, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        try:
            with urlopen(req, timeout=300) as r:
                datos = json.loads(r.read())
            texto = "".join(b.get("text", "") for b in datos.get("content", []) if b.get("type") == "text")
            texto = re.sub(r"^```(?:json)?|```$", "", texto.strip(), flags=re.M).strip()
            if datos.get("stop_reason") == "max_tokens":
                raise RespuestaNoValida("respuesta cortada por longitud")
            a, b = texto.find("{"), texto.rfind("}")
            if a != -1 and b > a:
                texto = texto[a:b + 1]
            return json.loads(texto)
        except HTTPError as e:
            msg = e.read().decode()[:300]
            if e.code in (429, 500, 502, 503, 529) and intento < 3:
                time.sleep(20 * (intento + 1)); continue
            sys.exit(f"Error de la API ({e.code}): {msg}")
        except json.JSONDecodeError:
            if intento < 3:
                continue
            raise RespuestaNoValida("la respuesta no era JSON válido")

SYSTEM = """Eres un analista que extrae información de programas electorales españoles para una web informativa y estrictamente neutral.
Reglas obligatorias:
- Solo extraes lo que el texto dice. No interpretas, no valoras, no completas con conocimiento propio.
- "cita" es una copia LITERAL y exacta de un fragmento del texto (máximo 300 caracteres), sin cambiar ni una palabra.
- "pagina" es el número de página donde aparece la cita, según las marcas === Página N ===.
- "texto" resume la medida en una frase neutra de máximo 200 caracteres que empieza por un verbo en infinitivo
  (por ejemplo: "Crear…", "Bajar…", "Ampliar…"). Sin adjetivos valorativos ni lenguaje de campaña.
- Si el programa está en catalán, gallego, euskera u otra lengua, "cita" va en la lengua original (copia literal)
  y "texto" va SIEMPRE en castellano.
- Prefieres medidas concretas y comprobables (cifras, leyes, plazos, organismos) frente a declaraciones genéricas.
- Respondes únicamente con JSON válido, sin texto antes ni después."""

def instrucciones(temas, preguntas, pag_ini, pag_fin):
    lista_temas = "\n".join(f'- "{t["id"]}": {t["name"]} ({t.get("desc","")})' for t in temas)
    lista_preg = "\n".join(f'- "{q["id"]}": {q["pregunta"]} ({q["explicacion"]})' for q in preguntas)
    return f"""Analiza las páginas {pag_ini} a {pag_fin} del programa electoral.

TEMAS (usa exactamente estos identificadores):
{lista_temas}

1) Extrae TODAS las medidas concretas de estas páginas que encajen en alguno de los temas.
   Si una medida no encaja en ningún tema, ignórala.

2) PREGUNTAS DEL COMPARADOR. Solo si el texto expresa una postura clara y explícita sobre alguna, indícala:
{lista_preg}
   postura: "si" (a favor), "no" (en contra) o "matiz" (a favor solo en parte o con condiciones).
   Si estas páginas no dicen nada claro sobre una pregunta, no la incluyas.

Devuelve exactamente este JSON:
{{"medidas":[{{"tema":"...","texto":"...","cita":"...","pagina":0}}],
  "posturas":[{{"pregunta":"...","postura":"si|no|matiz","cita":"...","pagina":0}}]}}"""


# ------------------------------------------------------------------ programas publicados como web
BLOQUES = {"p", "div", "li", "ul", "ol", "section", "article", "br", "tr", "table", "blockquote",
           "h1", "h2", "h3", "h4", "h5", "h6", "header", "main", "dd", "dt"}
IGNORAR = {"script", "style", "noscript", "svg", "nav", "footer", "form", "iframe", "template"}

class LectorHTML(HTMLParser):
    """Saca el texto visible y los enlaces de una página HTML (solo con la librería estándar)."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes, self.enlaces, self.oculto = [], [], 0
    def handle_starttag(self, tag, attrs):
        if tag in IGNORAR:
            self.oculto += 1
        elif tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.enlaces.append(href)
        if tag in BLOQUES:
            self.partes.append("\n")
    def handle_endtag(self, tag):
        if tag in IGNORAR and self.oculto:
            self.oculto -= 1
        if tag in BLOQUES:
            self.partes.append("\n")
    def handle_data(self, data):
        if not self.oculto:
            self.partes.append(data)
    def texto(self):
        t = re.sub(r"[ \t\r\f\v]+", " ", "".join(self.partes))
        return re.sub(r"\n\s*\n+", "\n", t).strip()

def leer_web(url_inicio, html_inicio):
    """Recorre las páginas del programa: la inicial y las enlazadas que cuelgan de la misma sección del sitio
    (por ejemplo, todo lo que está bajo /programa/). Devuelve dos listas paralelas: textos y direcciones."""
    base = urlparse(url_inicio)
    ruta = base.path if base.path.endswith("/") else base.path.rsplit("/", 1)[0] + "/"
    partes = [x for x in ruta.split("/") if x]
    # Si la dirección es una subpágina (p. ej. /programa/todas/), la sección es su primer nivel (/programa/).
    prefijo = "/" + partes[0] + "/" if partes else "/"
    textos, urls, vistos, cola = [], [], {urldefrag(url_inicio)[0]}, [(url_inicio, html_inicio)]
    while cola and len(urls) < MAX_PAGINAS_WEB:
        url, html = cola.pop(0)
        if html is None:
            try:
                with urlopen(Request(url, headers=CAB), timeout=60) as r:
                    if "html" not in r.headers.get("Content-Type", ""):
                        continue
                    html = r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
                time.sleep(0.5)
            except Exception as e:
                print(f"    no se pudo leer {url}: {e}")
                continue
        lector = LectorHTML(); lector.feed(html)
        texto = lector.texto()
        if len(texto) > 80 and texto not in textos:
            textos.append(texto); urls.append(url)
        for href in lector.enlaces:
            u = urldefrag(urljoin(url, href))[0]
            p = urlparse(u)
            if p.netloc == base.netloc and p.path.startswith(prefijo) and u not in vistos \
                    and not re.search(r"\.(pdf|jpe?g|png|gif|svg|webp|zip|docx?)$", p.path, re.I):
                vistos.add(u); cola.append((u, None))
    return textos, urls

# ------------------------------------------------------------------ programa
def main():
    partido = os.environ["PARTIDO"].strip()
    url = os.environ["URL_PDF"].strip()
    datos = json.loads(DATOS.read_text(encoding="utf-8"))
    nombres = {p["id"]: p["name"] for p in datos["partidos"]}
    if partido not in nombres:
        sys.exit(f"Partido desconocido: {partido}. Opciones: {', '.join(nombres)}")
    temas, preguntas = datos["temas"], datos.get("preguntas", [])
    ids_temas = {t["id"] for t in temas}
    ids_preg = {q["id"] for q in preguntas}

    print(f"Descargando {url}")
    with urlopen(Request(url, headers=CAB), timeout=120) as r:
        tipo, contenido_url = r.headers.get("Content-Type", ""), r.read()
        juego = r.headers.get_content_charset() or "utf-8"
    es_web = not contenido_url.lstrip()[:5].startswith(b"%PDF")
    lector, modo_pdf, urls_pag = None, False, []
    if es_web:
        # Programa publicado como páginas web en lugar de PDF: cada página web cuenta como una «página».
        if "html" not in tipo and not contenido_url.lstrip()[:1] == b"<":
            sys.exit(f"La dirección no devuelve un PDF ni una página web (tipo: {tipo}, {len(contenido_url)} bytes).")
        textos, urls_pag = leer_web(url, contenido_url.decode(juego, "replace"))
        n = len(textos)
        if not n:
            sys.exit("No se ha encontrado texto en la página web del programa.")
        print(f"{n} páginas web leídas, {int(sum(len(t) for t in textos) / n)} caracteres por página de media. Modo: web")
        for u in urls_pag:
            print(f"    {u}")
    else:
        lector = PdfReader(io.BytesIO(contenido_url))
        textos = [(pg.extract_text() or "") for pg in lector.pages]
        n = len(textos)
        media = sum(len(t) for t in textos) / max(n, 1)
        modo_pdf = media < 300   # PDF escaneado o con poco texto: se envía el PDF a Claude en lugar del texto
        print(f"{n} páginas, {int(media)} caracteres por página de media. Modo: {'PDF' if modo_pdf else 'texto'}")

    def fuente(pag):
        if es_web:
            return urls_pag[pag - 1] if 1 <= pag <= n else url
        return f"{url}#page={pag}" if pag else url

    medidas, posturas = [], []
    pendientes = [(ini, min(ini + PAGINAS_POR_BLOQUE, n)) for ini in range(0, n, PAGINAS_POR_BLOQUE)]
    while pendientes:
        ini, fin = pendientes.pop(0)
        print(f"  Páginas {ini+1}-{fin}…")
        if modo_pdf:
            w = PdfWriter()
            for i in range(ini, fin):
                w.add_page(lector.pages[i])
            buf = io.BytesIO(); w.write(buf)
            contenido = [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                         "data": base64.b64encode(buf.getvalue()).decode()}},
                         {"type": "text", "text": f"La primera página de este documento es la página {ini+1} del programa; "
                                                  f"numera las páginas a partir de ahí.\n\n" + instrucciones(temas, preguntas, ini+1, fin)}]
        else:
            bloque = "\n\n".join(f"=== Página {i+1} ===\n{textos[i]}" for i in range(ini, fin))
            aviso = ("Este programa está publicado como páginas web: cada «Página N» es una página web distinta del "
                     "programa (puede haber páginas de índice que repiten resúmenes de otras).\n\n") if es_web else ""
            contenido = aviso + instrucciones(temas, preguntas, ini+1, fin) + "\n\nTEXTO:\n" + bloque
        try:
            r = claude(SYSTEM, contenido)
        except RespuestaNoValida as e:
            # Bloques muy densos: se parten por la mitad y se vuelven a pedir.
            if fin - ini > 3:
                mitad = (ini + fin) // 2
                print(f"    {e}; se divide en {ini+1}-{mitad} y {mitad+1}-{fin}")
                pendientes[:0] = [(ini, mitad), (mitad, fin)]
                continue
            sys.exit(f"Páginas {ini+1}-{fin}: {e}.")
        medidas += [m for m in r.get("medidas", []) if m.get("tema") in ids_temas and m.get("cita") and m.get("texto")]
        posturas += [q for q in r.get("posturas", []) if q.get("pregunta") in ids_preg and q.get("postura") in ("si", "no", "matiz")]

    # Verificación de citas
    for m in medidas + posturas:
        try:
            m["pagina"] = int(m.get("pagina") or 0)
        except (TypeError, ValueError):
            m["pagina"] = 0
        # Se verifica contra el texto del PDF siempre que la página tenga texto legible (también en modo PDF).
        m["verificada"] = cita_en_pagina(m["cita"], textos, m["pagina"])

    # Selección si un tema tiene demasiadas medidas
    final = {}
    for t in temas:
        lista = [m for m in medidas if m["tema"] == t["id"]]
        lista.sort(key=lambda m: not m["verificada"])
        if len(lista) > MAX_POR_TEMA:
            opciones = "\n".join(f"{i}. {m['texto']}" for i, m in enumerate(lista))
            r = claude(SYSTEM, f"""Estas son medidas del programa sobre "{t['name']}". Elige como máximo {MAX_POR_TEMA}:
las más concretas y representativas, sin repetir ideas parecidas y prefiriendo las primeras de la lista en caso de duda.
Devuelve exactamente este JSON: {{"elegidas":[índices]}}

{opciones}""", max_tokens=1000)
            idx = [i for i in r.get("elegidas", []) if isinstance(i, int) and 0 <= i < len(lista)][:MAX_POR_TEMA]
            lista = [lista[i] for i in sorted(set(idx))] or lista[:MAX_POR_TEMA]
        final[t["id"]] = [{"texto": m["texto"].strip(), "cita": m["cita"].strip(), "pagina": 0 if es_web else m["pagina"],
                           "fuente": fuente(m["pagina"]),
                           "fecha": HOY, "verificada": m["verificada"]} for m in lista]

    # Comparador: una postura por pregunta (prioridad a las verificadas); se señalan las contradicciones
    conflictos, pos_final = [], {}
    for q in preguntas:
        ps = sorted([p for p in posturas if p["pregunta"] == q["id"]], key=lambda p: not p["verificada"])
        if not ps:
            pos_final[q["id"]] = {"postura": "sin", "fecha": HOY}
            continue
        if len({p["postura"] for p in ps}) > 1:
            conflictos.append((q, ps))
        p = ps[0]
        pos_final[q["id"]] = {"postura": p["postura"], "cita": p["cita"].strip(), "pagina": 0 if es_web else p["pagina"],
                              "fuente": fuente(p["pagina"]),
                              "fecha": HOY, "verificada": p["verificada"]}

    # Guardar en datos.json
    datos.setdefault("medidas", {})[partido] = final
    datos.setdefault("programas", {})[partido] = ({"url": url, "fecha": HOY, "formato": "web", "paginas": None}
                                                  if es_web else {"url": url, "fecha": HOY, "paginas": n})
    for q in datos.get("preguntas", []):
        q.setdefault("posturas", {})[partido] = pos_final[q["id"]]
    DATOS.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Informe para revisar
    total = sum(len(v) for v in final.values())
    sin_verificar = [(t, m) for t, ms in final.items() for m in ms if not m["verificada"]]
    nombre_tema = {t["id"]: t["name"] for t in temas}
    L = [f"## Programa de {nombres[partido]}", "",
         (f"- Web: {url} ({n} páginas web leídas; cada medida enlaza a la página donde está su cita)" if es_web
          else f"- PDF: {url} ({n} páginas, modo {'PDF' if modo_pdf else 'texto'})"),
         f"- Medidas extraídas: **{total}** · sin verificar: **{len(sin_verificar)}**",
         f"- Modelo: `{MODELO}`", "",
         "Al aprobar (Merge) este cambio, las medidas se publican en la web y se anuncia en X.",
         "**Las medidas marcadas como no verificadas no se muestran en la web** hasta que alguien compruebe la cita",
         "y cambie su `\"verificada\": false` por `true` en `datos.json`.", ""]
    for t in temas:
        L.append(f"### {t['name']} ({len(final[t['id']])})")
        for m in final[t["id"]]:
            marca = "✅" if m["verificada"] else "⚠️ **sin verificar**"
            donde = m["fuente"] if es_web else f"pág. {m['pagina']}"
            L.append(f"- {marca} {m['texto']} — {donde}\n  > {m['cita']}")
        L.append("")
    L.append("### Comparador")
    for q in preguntas:
        p = pos_final[q["id"]]
        etiqueta = {"si": "Sí", "no": "No", "matiz": "Con matices", "sin": "No se pronuncia"}[p["postura"]]
        linea = f"- {q['pregunta']} → **{etiqueta}**"
        if p["postura"] != "sin":
            donde = p["fuente"] if es_web else f"pág. {p['pagina']}"
            linea += f" ({donde}{'' if p['verificada'] else ', ⚠️ sin verificar'})\n  > {p['cita']}"
        L.append(linea)
    if conflictos:
        L += ["", "### ⚠️ Posturas contradictorias detectadas (revisar a mano)"]
        for q, ps in conflictos:
            L.append(f"- {q['pregunta']}: " + "; ".join(f"{p['postura']} (pág. {p['pagina']})" for p in ps))
    INFORME.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"Listo: {total} medidas, {len(sin_verificar)} sin verificar, {len(conflictos)} contradicciones.")

if __name__ == "__main__":
    main()
