# Roadmap

## 01 — Foundation Core

Estado: implementado en `feat/product-agent-foundation`.

- modelos canónicos;
- field registry;
- Excel reader dinámico;
- detección de duplicados/conflictos;
- SQLite y migraciones;
- repositorios;
- query/diff/policy;
- task runner/recovery;
- CLI read-only.

## 02 — S-TECH Tools

- mapear selectores estables del Codegen;
- búsqueda por filtro SKU exacto;
- lectura de pestañas Información Básica, Precios/Stock, Multimedia, Características y SEO;
- exportación de Items;
- changesets masivos por Excel;
- verificación después de guardar/importar;
- bloqueo de SKU ambiguos.

## 03 — Research + SEO

- portar el prompt SEO existente como skill versionada;
- extraer cliente genérico para Edge/ChatGPT;
- generación individual y masiva;
- persistencia de prompt runs;
- continuidad con el estado SEO existente.

## 04 — Conversational Agent

- router determinístico + fallback LLM;
- working sets conversacionales (`de esos`, `ahora solo JBL`, etc.);
- planes estructurados;
- confirmaciones por riesgo;
- tareas largas persistentes.

## 05 — UI / Release

- FastAPI local + frontend React;
- chat, catálogo, cambios, tareas y actividad;
- launcher Windows;
- navegadores bajo demanda;
- recovery después de reinicio;
- certificación usando `PROD-TEST` para operaciones reversibles.
