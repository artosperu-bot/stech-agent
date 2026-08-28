# Certificación manual de Importar Datos con `PROD-TEST`

La importación masiva **permanece bloqueada** hasta completar esta prueba en Windows contra S-TECH real.

## Precondiciones

- usar exclusivamente SKU exacto `PROD-TEST`;
- elegir un flag reversible y no comercial para la prueba;
- no ejecutar la prueba si `PROD-TEST` no puede restaurarse al valor original;
- conservar los Excel de antes/después y el diff JSON como evidencia local.

## Flujo obligatorio

1. Exportar Items y guardar snapshot A.
2. Registrar todas las columnas de `PROD-TEST`.
3. Generar un import de una sola fila copiando A completo y modificando un único flag reversible.
4. Importar mediante **Agregar / Actualizar**.
5. Exportar Items y guardar snapshot B.
6. Comparar A vs B para `PROD-TEST`: exactamente un campo debe cambiar.
7. Generar el import de restauración desde B cambiando únicamente ese campo a su valor original.
8. Importar la restauración.
9. Exportar Items y guardar snapshot C.
10. Comparar A vs C: cero diferencias.
11. Confirmar visualmente que `PROD-TEST` quedó restaurado.
12. Solo con `unrelated_changes=0`, `restored=True` y confirmación del operador ejecutar `mark_prod_test_certified(...)`.

Si aparece cualquier diferencia no solicitada, **no certificar**. El importador masivo debe seguir bloqueado.
