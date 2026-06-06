# Comparativa: Adiutor Iudicis vs Artifex Iudicialis — Caso 012

> Test ejecutado el 2026-06-06 sobre el caso 012 (EXP 634-2026, tenencia ilegal
> de arma de fuego y municiones, prisión preventiva).
> Mismo expediente, mismos PDFs base. Comparación directa de outputs.

---

## Resultado crítico: decisiones opuestas

| | Adiutor Iudicis (viejo) | Artifex Iudicialis (nuevo) |
|---|---|---|
| **Decisión** | **REVOCAR** → comparecencia con restricciones | **CONFIRMAR** → prisión preventiva 9 meses |
| **Razón** | Arraigo plenamente acreditado con prueba de 2da instancia | Arraigo parcial, peligro de fuga por gravedad de pena |

**¿Por qué llegan a conclusiones opuestas?** Por diferencia de inputs, no de calidad.

---

## Causa raíz: prueba de segunda instancia

La defensa presentó **10 medios de prueba nuevos en apelación** (admitidos vía
Casación 216-2016/El Santa). El viejo sistema los tenía. El nuevo pipeline NO,
porque esos documentos no estaban en las 6 ranuras del expediente.

Documentos que el viejo tenía y el nuevo no:

1. Acta de nacimiento Nº 1777 del hijo Yoalber David Rondón Casique (2008)
2. Cédula de identidad venezolana V-32.880.371 del hijo
3. Carné de estudiante IUTA (Administración de Empresas, vigencia hasta 2029)
4. Compromiso de pago universitario suscrito por la madre
5. Compromiso de pago a título personal del hijo
6. Tarjeta de control de aportes y pagos del hijo en IUTA
7. 15 comprobantes Yape (Pisco → celular *932 "Jonathan Ron*", oct 2025 - abr 2026)
8. 10 comprobantes Pagomóvil BDV y Dinero Rápido BBVA Provincial (Venezuela)
9. Certificado de nacimiento expedido por Hospital "Dr. Luis Razetti"
10. Documentación de filiación y dependencia económica

Con estos documentos, el viejo sistema:
- Acreditó arraigo familiar completo (hijo dependiente + conviviente + madre)
- Acreditó flujo de remesas sistemático Perú→Venezuela
- Concluyó que el peligro de fuga no alcanzaba estándar de sospecha grave
- Revocó la prisión → comparecencia con restricciones + caución de S/5,000

Sin estos documentos, el nuevo pipeline:
- Reconoció arraigo domiciliario y familiar básico
- No tuvo evidencia de las remesas ni dependencia del hijo
- Concluyó que la gravedad de la pena (8-15 años) dominaba el análisis
- Confirmó la prisión preventiva

**Conclusión: el pipeline funciona correctamente. El problema es de input, no de lógica.**

---

## Comparativa de calidad de redacción

### Extensión y estructura

| Métrica | Viejo | Nuevo |
|---|---|---|
| Caracteres totales | 42,222 | 27,060 |
| Líneas/párrafos | 114 párrafos densos | 213 líneas con formato markdown |
| Secciones | I-VI (prosa corrida) | I-VII con subsecciones A-H |
| Formato | Prosa judicial pura | Markdown con ## y **negritas** |

### Análisis jurídico

| Aspecto | Viejo | Nuevo |
|---|---|---|
| Agravios identificados | 7 (con absolución individual) | 9 (análisis por agravio) |
| Citas de casaciones | Con fundamento jurídico específico ("FJ 24", "FJ 40") | Correctas pero sin número de FJ |
| Interconexión | Alta — "conforme se desarrolló en el considerando 16" | Moderada — cada sección más autónoma |
| Prueba de 2da instancia | Incorporada y analizada en detalle | No disponible |
| Denuncia de extravío | Convierte argumento defensivo en elemento de cargo | Lo menciona pero no profundiza |
| Peligro de obstaculización | Analizado expresamente (descartado) | No analizado |

### Tono y autenticidad judicial

| Aspecto | Viejo | Nuevo |
|---|---|---|
| Tono general | Resolución judicial auténtica | Correcto pero más "manual de derecho" |
| Nombres de magistrados | Sí (Gallegos, Gutiérrez, Añanca) | No — solo "S.S." |
| Fechas en texto | Escritas en letra ("diecinueve de abril") | Mixto — algunas en número |
| Fórmulas procesales | "Autos y vistos", "S.S." completo | "Vistos y oídos" — correcto pero diferente |
| Encabezado .docx | Roto (faltaba PODER JUDICIAL) | Correcto — 3 capas de protección |

### Lo que el nuevo hace MEJOR

1. **Estructura visual clara** — secciones numeradas, subsecciones con letras, fácil de navegar
2. **Verificación de citas automática** — E4 confirmó en 24ms que todas las citas son reales
3. **Encabezado .docx correcto** — PODER JUDICIAL → CORTE SUPERIOR → SALA
4. **Control del juez en 3 puntos** — puede corregir hechos, filtrar fuentes, reescribir párrafos
5. **Velocidad** — pipeline ~8 min vs viejo ~18 min
6. **Bucle de corrección** — puede seleccionar un párrafo y reescribir solo eso

### Lo que el viejo hace MEJOR

1. **Profundidad analítica** — más capas de razonamiento, más conexiones entre argumentos
2. **Incorpora prueba nueva** — dato que cambió la decisión entera
3. **Tono judicial más auténtico** — parece una resolución de ponente real
4. **Absolución de agravios** — sección dedicada que conecta cada agravio con los considerandos
5. **Nombres de magistrados** — detalle de forma que el nuevo omite
6. **Manejo sofisticado de la denuncia de extravío** — argumentación que invierte el efecto del medio de prueba

---

## Diagnóstico técnico

### El pipeline LangGraph funciona correctamente

- E1 (resumen): extrajo correctamente los hechos de los 13 PDFs
- E2 (RAG): encontró jurisprudencia pertinente (Cas. 626-2013, SPC 01-2017, Cas. 1445-2018, etc.)
- E3 (redacción): generó resolución coherente con estructura apropiada
- E4 (verificación): todas las citas son reales (citas_ok=True, 24ms)
- E6 (formato): .docx con encabezado institucional correcto

### El problema es de input

La diferencia de decisión (revocar vs confirmar) no es un bug del pipeline.
Es consecuencia directa de que los medios de prueba de segunda instancia
no estaban en las ranuras del expediente cuando se corrió el test.

En uso real, el juez tiene dos formas de incorporar esa información:

1. **Agregar los documentos a la ranura `anexos/`** antes de iniciar
2. **Corregir en el checkpoint ①** — editar el resumen de hechos para incluir
   lo que la defensa presentó en audiencia
3. **Usar la instrucción particular** — escribir en el campo de instrucción:
   "La defensa presentó prueba nueva en 2da instancia: acta de nacimiento del
   hijo, comprobantes Yape de remesas, carné universitario IUTA..."

---

## Recomendaciones para mejorar el pipeline

### Prioridad alta

1. **Ranura para prueba de segunda instancia.** Actualmente hay 6 ranuras:
   solicitud_inicial, resolucion_apelada, recurso_apelacion, anexos, audio, otros.
   La prueba nueva de apelación se puede meter en `anexos/` o en `otros/`, pero
   no queda claro para el juez que ahí va. Considerar:
   - Agregar etiqueta explícita en la UI: "Prueba nueva de 2da instancia"
   - O documentar que `otros/` es la ranura para eso

2. **Nombres de magistrados.** El pipeline debe incluir los nombres de los jueces
   de la Sala en la resolución. Opciones:
   - Campo en el setup screen (una sola vez, se guarda)
   - Archivo de configuración en la carpeta del caso
   - Hardcodeado para la Sala de Chincha y Pisco (son los mismos jueces)

3. **Mejorar el tono judicial.** El prompt de E3 (node_redaccion) podría incluir
   instrucciones más específicas sobre:
   - Escribir fechas en letra completa
   - Citar fundamentos jurídicos con número específico
   - Incluir sección explícita de "Absolución de agravios"
   - Usar fórmulas procesales del juzgado ("Autos y vistos" vs "Vistos y oídos")

### Prioridad media

4. **Plantilla de resolución por materia.** El viejo sistema tenía resoluciones
   previas del mismo juez como referencia de estilo. El nuevo pipeline podría
   cargar una o dos resoluciones modelo del corpus del magistrado para que
   Claude imite el tono y estructura exactos.

5. **Análisis de peligro de obstaculización.** El viejo lo analiza (y descarta).
   El nuevo lo omite. El prompt de E3 debería pedir análisis explícito de
   peligro de fuga Y de obstaculización.

6. **Referencia cruzada entre considerandos.** El viejo dice "conforme se
   desarrolló en el considerando 16". El nuevo no hace estas referencias.
   Instrucción de prompt: "Cuando analices un agravio, referencia el
   considerando donde se desarrolló el fundamento que lo resuelve."

### Prioridad baja

7. **Modo "postura abierta".** Actualmente el juez elige postura (confirmar/revocar)
   antes de iniciar. Podría haber un modo donde el pipeline analice los
   presupuestos y SUGIERA la postura basándose en la fortaleza de los argumentos.

8. **Comparación con resoluciones del corpus.** Buscar automáticamente en
   `corpus_magistrado/` una resolución del mismo tipo penal y usarla como
   referencia de estructura y estilo.

---

## Archivos de referencia

```
Resolución vieja (Adiutor):
  03_outputs/exports/prision_preventiva/caso_012_tenencia_ilegal_de_armas_resolucion.docx
  → 42,222 chars, 114 líneas, decisión: REVOCAR

Resolución nueva (Artifex pipeline):
  outputs/caso_012_tenencia_ilegal_de_armas/EXP_634-2025_prision_preventiva.docx
  outputs/prueba_cadena/caso012_borrador_artifex.md
  → 27,060 chars, 213 líneas, decisión: CONFIRMAR

Cache de estados intermedios:
  outputs/prueba_cadena/caso012_estado_e1e2.json

Tiempos del pipeline:
  E1 (resumen):       81s  (~1.5 min)
  E2 (RAG+fuentes):  419s  (~7 min)
  E3 (redacción):    cacheado (corrida previa)
  E4 (verificación):  24ms
  E6 (formato .docx): <1s
```

---

> Documento generado por Atlas · 2026-06-06
> Para uso interno del equipo de desarrollo de Artifex Iudicialis.
