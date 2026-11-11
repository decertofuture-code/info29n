#!/usr/bin/env python3
"""
Busca en las webs oficiales de los partidos el PDF de su programa electoral para las generales del 29N.

Para cada partido que todavía no tiene programa en datos.json:
  1. Lee las páginas de fuentes.json → "webs_partidos" y las páginas enlazadas desde ellas que
     parecen de programa o elecciones (un nivel).
  2. Reúne los enlaces a PDF del dominio oficial del partido.
  3. Pide a Claude que diga cuál de ellos es el programa completo de las generales de 2026 (o ninguno).
  4. Descarta los PDF que ya se procesaron en una propuesta de cambio anterior (abierta o cerrada).

Escribe los encontrados en encontrados.txt («partido url» por línea). El workflow
vigilar_programas.yml los extrae con extraer_programa.py y abre una propuesta de cambio para revisar.
"""
import json, os, re, sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

RAIZ = Path(__file__).resolve().parent
SALIDA = RAIZ / "encontrados.txt"
MODELO = os.getenv("MODELO", "claude-sonnet-5-5")
UA = "Mozilla/5.0 (compatible; info29n.com; +https://info29n.com)"
PISTAS = re.compile(r"program|eleccion|elecciones|eleccions|eleccions|xerais|generales|generals|hauteskunde|29n|29-n|congres|congreso|2026", re.I)


class Enlaces(HTMLParser):
    def __init__(self, base):
        super().__init__(); self.base = base; self.links = []; self._a = None; self._txt = []
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._a = urljoin(self.base, href.strip()); self._txt = []
    def handle_data(self, data):
        if self._a:
            self._txt.append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self._a:
            self.links.append((self._a, " ".join(" ".join(self._txt).split())[:150])); self._a = None


def leer(url, limite=3_000_000):
    with urlopen(Request(url, headers={"User-Agent": UA}), timeout=30) as r:
        return r.headers.get("Content-Type", ""), r.read(limite)


def enlaces(url):
    try:
        tipo, cuerpo = leer(url)
    except Exception as e:
        print(f"    no se pudo leer {url}: {e}")
        return []
    if "html" not in tipo:
        return []
    p = Enlaces(url)
    try:
        p.feed(cuerpo.decode("utf-8", "replace"))
    except Exception:
        pass
    return p.links


def dominio(u):
    h = urlparse(u).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def oficial(u, dominios):
    h = dominio(u)
    return any(h == d or h.endswith("." + d) for d in dominios)


def es_pdf(u):
    return urlparse(u).path.lower().endswith(".pdf")


def candidatos(paginas):
    dominios = {dominio(p) for p in paginas}
    pdfs, vistas, cola = {}, set(), list(paginas)
    for nivel in range(2):
        siguiente = []
        for pag in cola:
            if pag in vistas:
                continue
            vistas.add(pag)
            for u, txt in enlaces(pag):
                if not oficial(u, dominios):
                    continue
                if es_pdf(u):
                    pdfs.setdefault(u, {"url": u, "texto": txt, "pagina": pag})
                elif nivel == 0 and PISTAS.search(u + " " + txt):
                    siguiente.append(u.split("#")[0])
        cola = list(dict.fromkeys(siguiente))[:15]
    return list(pdfs.values())


def claude(prompt):
    cuerpo = {"model": MODELO, "max_tokens": 600, "messages": [{"role": "user", "content": prompt}]}
    req = Request("https://api.anthropic.com/v1/messages", data=json.dumps(cuerpo).encode(), method="POST",
                  headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
                           "content-type": "application/json"})
    with urlopen(req, timeout=120) as r:
        datos = json.loads(r.read())
    texto = "".join(b.get("text", "") for b in datos.get("content", []) if b.get("type") == "text")
    a, b = texto.find("{"), texto.rfind("}")
    return json.loads(texto[a:b + 1]) if a != -1 else {}


def elegir(nombre, pdfs):
    lista = "\n".join(f'{i}. {p["url"]} | texto del enlace: "{p["texto"]}" | encontrado en: {p["pagina"]}'
                      for i, p in enumerate(pdfs))
    r = claude(f"""Estos son enlaces a PDF de la web oficial de {nombre}.
¿Alguno es su PROGRAMA ELECTORAL COMPLETO para las elecciones generales (Congreso y Senado) del 29 de noviembre de 2026?
No valen programas autonómicos, municipales o europeos, ni de elecciones anteriores, ni resúmenes, folletos o programas por sectores.
Si no estás seguro, responde null.
Devuelve solo este JSON: {{"indice": <número o null>, "motivo": "<una frase>"}}

{lista}""")
    i = r.get("indice")
    print(f"    Claude: {r.get('indice')} — {r.get('motivo', '')}")
    return pdfs[i]["url"] if isinstance(i, int) and 0 <= i < len(pdfs) else None


def ya_propuestos():
    """URLs de PDF que ya aparecen en propuestas de cambio anteriores (para no repetirlas)."""
    repo, token = os.getenv("GITHUB_REPOSITORY"), os.getenv("GITHUB_TOKEN")
    if not repo or not token:
        return set()
    urls, pagina = set(), 1
    while pagina <= 5:
        req = Request(f"https://api.github.com/repos/{repo}/pulls?state=all&per_page=100&page={pagina}",
                      headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
        with urlopen(req, timeout=30) as r:
            prs = json.loads(r.read())
        for pr in prs:
            urls.update(re.findall(r"PDF: (\S+)", pr.get("body") or ""))
        if len(prs) < 100:
            break
        pagina += 1
    return urls


def main():
    datos = json.loads((RAIZ / "datos.json").read_text(encoding="utf-8"))
    webs = json.loads((RAIZ / "fuentes.json").read_text(encoding="utf-8")).get("webs_partidos", {})
    hechos = set((datos.get("programas") or {}).keys())
    vistos = ya_propuestos()
    solo = set(filter(None, os.getenv("SOLO_PARTIDOS", "").replace(",", " ").split()))
    encontrados = []
    for p in datos["partidos"]:
        pid = p["id"]
        if pid in hechos or (solo and pid not in solo) or not webs.get(pid):
            continue
        print(f"{p['name']}:")
        pdfs = candidatos(webs[pid])
        print(f"    {len(pdfs)} PDF en su web")
        if not pdfs:
            continue
        url = elegir(p["name"], pdfs[:80])
        if not url:
            continue
        if url in vistos:
            print(f"    ya propuesto antes: {url}")
            continue
        try:
            tipo, cabecera = leer(url, 8)
        except Exception as e:
            print(f"    el PDF no responde: {e}")
            continue
        if not cabecera.startswith(b"%PDF"):
            print(f"    no es un PDF: {url}")
            continue
        print(f"    PROGRAMA ENCONTRADO: {url}")
        encontrados.append(f"{pid} {url}")
    SALIDA.write_text("\n".join(encontrados) + ("\n" if encontrados else ""), encoding="utf-8")
    print(f"\n{len(encontrados)} programa(s) nuevo(s).")


if __name__ == "__main__":
    main()
