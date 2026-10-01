# Privacidad al publicar

Este proyecto utiliza un historial independiente, un UUID sin nombre personal y
el correo `noreply` de GitHub para autor y committer. No se deben copiar datos de
autenticación, cachés, logs ni directorios privados al repositorio.

## Configurar una copia nueva

Copia tu dirección `noreply` exacta desde **GitHub → Settings → Emails** y úsala en
este repositorio:

```bash
git config --local user.email "TU_DIRECCION_NOREPLY_DE_GITHUB"
git config --local core.hooksPath .githooks
```

Los hooks bloquean commits con archivos privados, patrones de credenciales,
correos personales y metadatos PNG. Antes de cada push también revisan todos los
commits y exigen `noreply` tanto en autor como en committer. Los hooks son locales:
hay que activarlos en cada clon y pueden omitirse; no sustituyen una revisión.

```bash
npm run security:check
python3 scripts/security-check.py --history
```

El control no imprime los valores detectados. Las cadenas `fixture-secret` y
`wrong` son datos ficticios usados por las pruebas. El detector reconoce patrones
conocidos; no garantiza detectar cualquier formato de credencial o dato personal.

## Capturas y paquetes

Las capturas muestran cuotas ficticias y se publican sin texto ni EXIF incrustado.
La prueba de GNOME elimina esos metadatos al exportar las capturas. Para limpiar
otras capturas antes de añadirlas:

```bash
python3 scripts/clean-screenshots.py docs/screenshots
```

También revisa visualmente las imágenes: quitar metadatos no elimina información
visible. El empaquetador revisa los archivos y copia únicamente los componentes
de la extensión; `dist/` se excluye del historial.

## Si se publica una credencial por error

Revócala o rótala primero. Borrar un archivo o reescribir el historial no retira
copias descargadas ni garantiza purgar las cachés del proveedor Git. Evita incluir
el valor de la credencial en un issue, captura o registro de diagnóstico.
