#!/usr/bin/env python3
"""
Parche de una sola vez sobre datos.json (se puede ejecutar varias veces sin duplicar nada):
  - añade las votaciones de economía y sanidad
  - añade el campo "candidato" a cada partido
  - añade las preguntas del comparador "¿Quién propone qué?"
  - crea el apartado "programas" (se rellena al procesar cada programa electoral)
"""
import json
from pathlib import Path

RUTA = Path(__file__).resolve().parent / "datos.json"
d = json.loads(RUTA.read_text(encoding="utf-8"))

VOTOS_NUEVOS = [
    {"topic": "economia", "title": "Decreto ómnibus: revalorización de las pensiones y escudo social", "date": "2026-01-27",
     "what": "Real decreto-ley que subía las pensiones un 2,7 % para 2026, prorrogaba la suspensión de desahucios a colectivos vulnerables y congelaba las cuotas de los autónomos, entre otras medidas. PP, Vox y Junts dijeron apoyar la subida de las pensiones, pero rechazaron que se votara junto al resto de medidas.",
     "result": "Rechazado: 171 votos a favor y 178 en contra.", "yesLabel": "A favor", "noLabel": "En contra",
     "si": ["psoe", "sumar", "erc", "bildu", "pnv", "podemos", "bng"], "no": ["pp", "vox", "junts", "upn"],
     "src": "https://www.eleconomista.es/economia/noticias/13746778/01/26/el-congreso-rechaza-el-decreto-omnibus-por-el-que-se-revalorizan-las-pensiones-para-2026.html"},
    {"topic": "sanidad", "title": "Ley de creación de la Agencia Estatal de Salud Pública", "date": "2025-03-20",
     "what": "Votación final en el Pleno del proyecto de ley para crear una agencia estatal de salud pública. PP y Junts, que la habían apoyado en comisión, votaron en contra en protesta por la tramitación de otra ley.",
     "result": "Rechazada: 167 votos a favor, 176 en contra y 2 abstenciones.", "yesLabel": "A favor", "noLabel": "En contra",
     "si": ["psoe", "sumar"], "no": ["pp", "vox", "junts"],
     "src": "https://www.infosalus.com/actualidad/noticia-congreso-tumba-agencia-estatal-salud-publica-votos-contra-pp-vox-junts-20250320122634.html"},
]

PREGUNTAS = [
    {"id": "alquiler", "tema": "vivienda", "pregunta": "¿Limitar por ley el precio del alquiler en zonas tensionadas?",
     "explicacion": "Topes o índices de referencia obligatorios para los precios del alquiler en zonas con precios muy altos."},
    {"id": "grandes-tenedores", "tema": "vivienda", "pregunta": "¿Poner límites a la compra de vivienda por grandes propietarios y fondos de inversión?",
     "explicacion": "Prohibiciones, cupos o impuestos especiales para que empresas o personas con muchas viviendas compren más."},
    {"id": "irpf", "tema": "economia", "pregunta": "¿Bajar el IRPF de forma general?",
     "explicacion": "Rebaja del impuesto sobre la renta para todos o la mayoría de los contribuyentes, no solo deducciones concretas."},
    {"id": "grandes-fortunas", "tema": "economia", "pregunta": "¿Mantener el impuesto estatal sobre las grandes fortunas?",
     "explicacion": "Que siga existiendo el impuesto que el Estado cobra a los patrimonios más altos, en lugar de suprimirlo."},
    {"id": "regularizacion", "tema": "inmigracion", "pregunta": "¿Regularizar de forma extraordinaria a inmigrantes en situación irregular?",
     "explicacion": "Procesos excepcionales para dar permiso de residencia y trabajo a personas que ya viven en España sin papeles."},
    {"id": "indultos", "tema": "politica", "pregunta": "¿Prohibir por ley los indultos por delitos de corrupción?",
     "explicacion": "Que el Gobierno no pueda indultar a personas condenadas por delitos de corrupción, como la malversación o el cohecho."},
    {"id": "jornada", "tema": "empleo", "pregunta": "¿Reducir por ley la jornada laboral máxima?",
     "explicacion": "Bajar la jornada máxima legal (actualmente 40 horas semanales) sin reducción de sueldo."},
    {"id": "listas-espera", "tema": "sanidad", "pregunta": "¿Fijar por ley tiempos máximos de espera en la sanidad pública?",
     "explicacion": "Plazos máximos garantizados para operaciones, pruebas o consultas con el especialista en todo el Sistema Nacional de Salud."},
]

cambios = []
vistas = {v["title"] for v in d.get("votaciones", [])}
for v in VOTOS_NUEVOS:
    if v["title"] not in vistas:
        d.setdefault("votaciones", []).append(v); cambios.append(f"votación: {v['title']}")
for p in d.get("partidos", []):
    if "candidato" not in p:
        p["candidato"] = None; cambios.append(f"candidato: {p['id']}")
existentes = {q["id"]: q for q in d.get("preguntas", [])}
for q in PREGUNTAS:
    if q["id"] not in existentes:
        d.setdefault("preguntas", []).append({**q, "posturas": {}}); cambios.append(f"pregunta: {q['id']}")
    else:
        e = existentes[q["id"]]
        if any(e.get(k) != q[k] for k in ("tema", "pregunta", "explicacion")):
            if any(v.get("postura") not in (None, "sin") for v in e.get("posturas", {}).values()):
                cambios.append(f"AVISO: no se cambia «{q['id']}» porque ya tiene posturas; habría que reprocesar los programas")
                continue
            e.update({k: q[k] for k in ("tema", "pregunta", "explicacion")}); cambios.append(f"pregunta reformulada: {q['id']}")
if "debates" not in d:
    d["debates"] = []; cambios.append("apartado debates")
if "programas" not in d:
    d["programas"] = {}; cambios.append("apartado programas")

RUTA.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("Cambios:", *cambios, sep="\n - ") if cambios else print("Nada que cambiar.")
