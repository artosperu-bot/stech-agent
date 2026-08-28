# Arquitectura — STECH Product Agent

## Principio

**Inteligencia para decidir; código determinístico para ejecutar; verificación para confirmar.**

El modelo de lenguaje no controla libremente el navegador. Interpreta la instrucción y genera un plan estructurado. El ejecutor usa herramientas registradas y verificables.

## Identidad

- La identidad canónica de un producto es el SKU exacto.
- El SKU se conserva como texto.
- Nombre, marca, modelo, color y categoría son verificaciones secundarias.
- Si el mismo SKU aparece varias veces con valores incompatibles, el producto queda `ambiguous` y sus `conflict_fields` se conservan.
- Las futuras herramientas de escritura deberán bloquear SKU ambiguos hasta resolver el conflicto.

## Capas

1. **Catalog Core**: snapshots Excel, normalización, consultas y diffs.
2. **Persistent State**: SQLite, sesiones, working sets, tareas, changesets y auditoría.
3. **Policy Engine**: allowlist de acciones/campos y nivel de riesgo.
4. **S-TECH Tools**: exportar, buscar SKU exacto, leer producto, editar campos, importar cambios y verificar.
5. **Research Skills**: SEO, descripción, características, especificaciones y clasificación.
6. **Conversational Agent**: entiende órdenes, mantiene el conjunto de trabajo y selecciona tools.
7. **Desktop UI**: chat, catálogo, tareas, cambios, logs y confirmaciones.

## Seguridad

No existe acción de eliminación en producción. Los cambios masivos sensibles requieren propuesta y confirmación. Los cambios se limitan a una máscara explícita de campos y se auditan antes/después.
