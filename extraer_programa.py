#!/usr/bin/env python3
"""
Extrae las medidas de un programa electoral (PDF) con la API de Claude y prepara un borrador en datos.json.

Uso (normalmente desde GitHub Actions, workflow "Procesar programa"):
  PARTIDO=pp URL_PDF=https://... ANTHROPIC_API_KEY=... python extraer_programa.py

Qué hace:
  1. Descarga el PDF y lee el texto de cada página.
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
from pathlib import Path
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

def claude(system, contenido, max_tokens=8000):
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
            return json.loads(texto)
        except HTTPError as e:
            msg = e.read().decode()[:300]
            if e.code in (429, 500, 502, 503, 529) and intento < 3:
                time.sleep(20 * (intento + 1)); continue
            sys.exit(f"Error de la API ({e.code}): {msg}")
        except json.JSONDecodeError:
            if intento < 3:
                continue
            sys.exit("La respuesta de Claude no era JSON válido.")

SYSTEM = """Eres un analista que extrae información de programas electorales españoles para una web informativa y estrictamente neutral.
Reglas obligatorias:
- Solo extraes lo que el texto dice. No interpretas, no valoras, no completas con conocimiento propio.
- "cita" es una copia LITERAL y exacta de un fragmento del texto (máximo 300 caracteres), sin cambiar ni una palabra.
- "pagina" es el número de página donde aparece la cita, según las marcas === Página N ===.
- "texto" resume la medida en una frase neutra de máximo 200 caracteres que empieza por un verbo en infinitivo
  (por ejemplo: "Crear…", "Bajar…", "Ampliar…"). Sin adjetivos valorativos ni lenguaje de campaña.
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
    pdf_bytes = urlopen(Request(url, headers={"User-Agent": "info29n.com"}), timeout=120).read()
    lector = PdfReader(io.BytesIO(pdf_bytes))
    textos = [(pg.extract_text() or "") for pg in lector.pages]
    n = len(textos)
    media = sum(len(t) for t in textos) / max(n, 1)
    modo_pdf = media < 300   # PDF escaneado o con poco texto: se envía el PDF a Claude en lugar del texto
    print(f"{n} páginas, {int(media)} caracteres por página de media. Modo: {'PDF' if modo_pdf else 'texto'}")

    medidas, posturas = [], []
    for ini in range(0, n, PAGINAS_POR_BLOQUE):
        fin = min(ini + PAGINAS_POR_BLOQUE, n)
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
            contenido = instrucciones(temas, preguntas, ini+1, fin) + "\n\nTEXTO:\n" + bloque
        r = claude(SYSTEM, contenido)
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
        final[t["id"]] = [{"texto": m["texto"].strip(), "cita": m["cita"].strip(), "pagina": m["pagina"],
                           "fuente": f"{url}#page={m['pagina']}" if m["pagina"] else url,
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
        pos_final[q["id"]] = {"postura": p["postura"], "cita": p["cita"].strip(), "pagina": p["pagina"],
                              "fuente": f"{url}#page={p['pagina']}" if p["pagina"] else url,
                              "fecha": HOY, "verificada": p["verificada"]}

    # Guardar en datos.json
    datos.setdefault("medidas", {})[partido] = final
    datos.setdefault("programas", {})[partido] = {"url": url, "fecha": HOY, "paginas": n}
    for q in datos.get("preguntas", []):
        q.setdefault("posturas", {})[partido] = pos_final[q["id"]]
    DATOS.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Informe para revisar
    total = sum(len(v) for v in final.values())
    sin_verificar = [(t, m) for t, ms in final.items() for m in ms if not m["verificada"]]
    nombre_tema = {t["id"]: t["name"] for t in temas}
    L = [f"## Programa de {nombres[partido]}", "",
         f"- PDF: {url} ({n} páginas, modo {'PDF' if modo_pdf else 'texto'})",
         f"- Medidas extraídas: **{total}** · sin verificar: **{len(sin_verificar)}**",
         f"- Modelo: `{MODELO}`", "",
         "Al aprobar (Merge) este cambio, las medidas se publican en la web y se anuncia en X.",
         "**Las medidas marcadas como no verificadas no se muestran en la web** hasta que alguien compruebe la cita",
         "y cambie su `\"verificada\": false` por `true` en `datos.json`.", ""]
    for t in temas:
        L.append(f"### {t['name']} ({len(final[t['id']])})")
        for m in final[t["id"]]:
            marca = "✅" if m["verificada"] else "⚠️ **sin verificar**"
            L.append(f"- {marca} {m['texto']} — pág. {m['pagina']}\n  > {m['cita']}")
        L.append("")
    L.append("### Comparador")
    for q in preguntas:
        p = pos_final[q["id"]]
        etiqueta = {"si": "Sí", "no": "No", "matiz": "Con matices", "sin": "No se pronuncia"}[p["postura"]]
        linea = f"- {q['pregunta']} → **{etiqueta}**"
        if p["postura"] != "sin":
            linea += f" (pág. {p['pagina']}{'' if p['verificada'] else ', ⚠️ sin verificar'})\n  > {p['cita']}"
        L.append(linea)
    if conflictos:
        L += ["", "### ⚠️ Posturas contradictorias detectadas (revisar a mano)"]
        for q, ps in conflictos:
            L.append(f"- {q['pregunta']}: " + "; ".join(f"{p['postura']} (pág. {p['pagina']})" for p in ps))
    INFORME.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"Listo: {total} medidas, {len(sin_verificar)} sin verificar, {len(conflictos)} contradicciones.")

if __name__ == "__main__":
    main()
