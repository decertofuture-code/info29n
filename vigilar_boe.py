#!/usr/bin/env python3
"""
Revisa el sumario del BOE de hoy y avisa en el informe diario (informe.md) si se publican
candidaturas a las Cortes Generales o resoluciones de la Junta Electoral Central.
Con ese aviso se rellena a mano el campo "candidato" de cada partido en datos.json.
"""
import json
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent
ESTADO = RAIZ / "estado.json"
INFORME = RAIZ / "informe.md"
HOY = datetime.now(ZoneInfo("Europe/Madrid"))

def items(nodo):
    if isinstance(nodo, dict):
        if "titulo" in nodo and "identificador" in nodo:
            yield nodo
        for v in nodo.values():
            yield from items(v)
    elif isinstance(nodo, list):
        for v in nodo:
            yield from items(v)

def enlace(it):
    for k in ("url_html", "url_pdf"):
        v = it.get(k)
        if isinstance(v, dict):
            v = v.get("texto") or v.get("url")
        if v:
            return v
    return f"https://www.boe.es/diario_boe/txt.php?id={it['identificador']}"

def interesa(t):
    t = t.lower()
    electoral = any(k in t for k in ("congreso de los diputados", "senado", "cortes generales", "elecciones generales"))
    return ("candidatura" in t and electoral) or "junta electoral central" in t

def main():
    url = f"https://www.boe.es/datosabiertos/api/boe/sumario/{HOY:%Y%m%d}"
    try:
        with urlopen(Request(url, headers={"Accept": "application/json", "User-Agent": "info29n.com"}), timeout=30) as r:
            datos = json.loads(r.read())
    except Exception as e:
        print(f"BOE no disponible hoy ({e}). Los domingos no hay BOE.")
        return
    estado = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {}
    vistos = set(estado.get("boe_vistos", []))
    nuevos = [it for it in items(datos) if interesa(it["titulo"]) and it["identificador"] not in vistos]
    if not nuevos:
        print("Nada electoral relevante en el BOE de hoy.")
        return
    lineas = ["## BOE de hoy: publicaciones electorales", "",
              "Si son candidaturas, rellena el campo `candidato` de cada partido en `datos.json` (cabeza de lista por Madrid o el candidato a la presidencia que anuncie el partido).", ""]
    for it in nuevos:
        lineas.append(f"- [ ] [{it['titulo'][:300]}]({enlace(it)})")
        vistos.add(it["identificador"])
    previo = INFORME.read_text(encoding="utf-8") if INFORME.exists() else ""
    INFORME.write_text((previo + "\n" if previo else "") + "\n".join(lineas) + "\n", encoding="utf-8")
    estado["boe_vistos"] = sorted(vistos)[-500:]
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(nuevos)} publicaciones electorales añadidas al informe.")

if __name__ == "__main__":
    main()
