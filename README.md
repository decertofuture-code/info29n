# info29n.com

Web informativa sobre las elecciones generales del 29 de noviembre de 2026.

## Cómo está organizado

```
site/                 Lo que se publica en Netlify
  index.html          Diseño y funcionamiento de la web (casi nunca hay que tocarlo)
  datos.json          TODO el contenido: temas, partidos, medidas, votaciones, casos y noticias
  og-image.png        Imagen de la vista previa en redes
scripts/
  actualizar.py       Recoge titulares y prepara el informe diario
  fuentes.json        Medios y palabras clave (editable)
  estado.json         Memoria interna del script (no tocar)
.github/workflows/
  actualizar.yml      Programa la actualización automática
netlify.toml          Le dice a Netlify qué carpeta publicar
```

## Qué se actualiza solo y qué no

- **Solo, varias veces al día:** la pestaña Noticias (titulares con enlace al medio).
- **Nunca solo:** medidas de los programas y casos de corrupción. Cada mañana se crea un
  *issue* en GitHub ("Revisión del dd/mm/aaaa") con lo que conviene revisar. GitHub te lo
  manda por correo.

## Cómo cambiar el contenido a mano

1. En GitHub, abre `site/datos.json` y pulsa el lápiz (Edit).
2. Haz el cambio y pulsa "Commit changes".
3. Netlify publica la nueva versión en un minuto.

Si el JSON queda mal escrito (una coma de más, por ejemplo), la web mostrará un aviso de
error al cargar. Puedes deshacerlo desde el historial del archivo en GitHub.

## Ejecutar la actualización a mano

Pestaña **Actions** → "Actualizar datos" → **Run workflow**.
