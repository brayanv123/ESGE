# Informe de calidad – Dataset Visor de Transparencia Territorial (Bogotá D.C.)

Fecha de consulta de fuentes: 2026-11-16. Fecha de corte del dataset: 2026-09-30. Semilla sintética: 20261116.

> **Advertencia.** Los registros con `tipo_registro = SINTETICO` son ficticios, se generaron solo para probar el prototipo y **no representan la ejecución real de la Alcaldía de Bogotá**. Los registros REALES cubren únicamente el componente de **Presupuestos Participativos** de los Fondos de Desarrollo Local: sus cifras de comprometido no son el presupuesto total de esos proyectos ni son comparables con los totales sintéticos.

## 1. Resumen de volumen

| Tabla | Real | Sintético | Total |
|---|---|---|---|
| proyectos | 744 | 180 | 924 |
| presupuesto_proyectos | 1475 | 378 | 1853 |
| seguimiento_proyectos | 1453 | 577 | 2030 |
| localidades | 20 | 0 | 20 |
| inversion_educacion_localidad (complementaria) | 40 | 0 | 40 |

Proporción real/sintético en proyectos: 80.5% real – 19.5% sintético.

## 2. Transformaciones aplicadas

- **Unidad de proyecto real**: combinación `localidad + Codigo_Proyecto` (los códigos de proyecto de los FDL no se repiten entre localidades: verificado, 0 códigos en más de una localidad). `id_proyecto = FDL{cod_localidad}-{codigo}`.
- **Relación entre tablas oficiales** por identificador oficial (`No_Localidad` + `Codigo_Proyecto` + `Vigencia_Ejecucion`), nunca por nombre. CRP sin propuesta asociada: 0.
- **Homologación de sectores**: unificación de mayúsculas/tildes (p. ej. "CULTURA, RECREACIÓN Y DEPORTE" y "Cultura, recreación y deporte"). Ver hoja *Homologaciones* del diccionario.
- **Homologación de estados** (fuente por propuesta → proyecto, usando la última vigencia del proyecto): Materializada→F; En ejecución/Contratada→E; En proceso de contratación/En formulación/Sin iniciar→P; Imposible ejecución (inviable)/No ejecutada→X. Regla: si hay E → *En ejecución*; si no y hay P → *Programado*; si no y hay F → *Finalizado*; si solo X → *Cancelado*, salvo que el proyecto tenga propuestas materializadas en vigencias anteriores (→ *Finalizado* con cierre parcial). La fuente no reporta *Suspendido*.
- **Valores**: texto "$ 45.000.000" → número COP. Valores inválidos: 0.
- **Fechas**: `d/m/aaaa` → ISO. Fechas inválidas en CRP: 1 (excluidas de los cálculos de fecha, no del valor). CRP cuyo año de registro difiere de la vigencia: 0.
- **Plazo**: la columna mezcla unidades; valores ≤ 36 se interpretan como meses (×30,4 días) y mayores como días. `fecha_fin` real = máx(fecha CRP + plazo) → es una **estimación**.
- **Duplicados exactos** eliminados: propuestas 0, CRP 0.
- **Proyectos con más de un nombre** en la fuente: 7 (se conserva el más frecuente).
- **Presupuesto real**: un registro por proyecto-vigencia; `presupuesto_comprometido` = suma de CRP de PP. Inicial, vigente, obligado y pagado quedan **nulos** (no se inventa ejecución). Proyecto-vigencias reales sin CRP: 419 (comprometido nulo).
- **Seguimiento real**: comprometido acumulado a cada cierre trimestral calculado con las fechas de los CRP (derivado, sin avance físico).
- **Fórmula de ejecución**: `porcentaje_ejecucion_presupuestal = presupuesto_obligado / presupuesto_vigente × 100`.

## 3. Reglas de generación sintética

- 180 proyectos (`SIN-0001`…), mínimo 4 por localidad y el resto proporcional a √población 2025.
- 16 plantillas por sector/tipo (movilidad, espacio público, educación, salud, seguridad, ambiente, cultura, integración social, mujeres, desarrollo económico, gobierno) con rangos presupuestales log-uniformes diferenciados (p. ej. infraestructura educativa $4.000–35.000 millones; eventos $150–1.800 millones) y un factor por localidad (0,6 Candelaria – 1,4 Ciudad Bolívar), que es un **supuesto** del prototipo.
- Fechas de inicio entre 2024-03 y 2027-06; el estado se deriva de las fechas frente al corte (programado si inicia después del corte, finalizado si termina antes, en ejecución si cruza el corte) y se asignan suspensiones (~13 %) y cancelaciones (~2–4 %) aleatorias.
- Presupuesto distribuido por vigencia según días del proyecto en cada año; vigente = inicial × U(0,85;1,15); comprometido ≤ vigente, obligado ≤ comprometido, pagado ≤ obligado; vigencias futuras sin ejecución.
- Avance físico: 100 % finalizados, 0 % programados, proporcional al tiempo transcurrido en ejecución/suspendidos.
- Seguimiento trimestral acumulado por vigencia; el último corte de cada vigencia coincide con la tabla de presupuesto.

## 4. Validaciones

| Validación | Resultado | Detalle |
|---|---|---|
| id_proyecto único | OK | 924 proyectos |
| Localidades válidas (20 oficiales) | OK | 20 localidades con proyectos |
| Sin presupuestos huérfanos | OK |  |
| Sin seguimientos huérfanos | OK |  |
| Sin duplicados proyecto-vigencia en presupuesto | OK |  |
| Sin duplicados proyecto-fecha_corte en seguimiento | OK |  |
| fecha_inicio válida (2015-2030) | OK | 360 nulos |
| fecha_fin válida (2015-2030) | OK | 364 nulos |
| fecha_inicio <= fecha_fin | OK |  |
| SINT: Finalizado con fecha_fin <= corte | OK |  |
| SINT: Programado con fecha_inicio > corte | OK |  |
| SINT: En ejecución con inicio <= corte < fin | OK |  |
| SINT: Finalizado avance 100% | OK |  |
| SINT: Programado avance 0% | OK |  |
| REAL: Finalizado con fecha_fin estimada <= corte (informativo) | REVISAR | 6 proyectos reales finalizados con fecha fin estimada posterior al corte (no se corrigen) |
| Valores presupuestales >= 0 | OK |  |
| comprometido <= vigente | OK |  |
| obligado <= comprometido | OK |  |
| pagado <= obligado | OK |  |
| % ejecución en [0,100] | OK |  |
| Presupuestos iniciales sintéticos no repetidos | OK |  |
| Seguimiento: acumulados monotónicos dentro de cada vigencia | OK |  |
| Seguimiento: obligado <= comprometido y pagado <= obligado | OK |  |
| REAL: sin ejecución inventada (inicial/vigente/obligado/pagado nulos) | OK |  |
| Todos los registros con tipo_registro | OK |  |

## 5. Cobertura

### Proyectos por localidad

| Cód. | Localidad | Real | Sintético |
|---|---|---|---|
| 01 | Usaquén | 34 | 11 |
| 02 | Chapinero | 36 | 8 |
| 03 | Santa Fe | 36 | 7 |
| 04 | San Cristóbal | 38 | 10 |
| 05 | Usme | 39 | 10 |
| 06 | Tunjuelito | 37 | 8 |
| 07 | Bosa | 36 | 12 |
| 08 | Kennedy | 37 | 13 |
| 09 | Fontibón | 39 | 10 |
| 10 | Engativá | 37 | 12 |
| 11 | Suba | 38 | 14 |
| 12 | Barrios Unidos | 32 | 7 |
| 13 | Teusaquillo | 34 | 7 |
| 14 | Los Mártires | 34 | 7 |
| 15 | Antonio Nariño | 38 | 6 |
| 16 | Puente Aranda | 37 | 8 |
| 17 | La Candelaria | 38 | 5 |
| 18 | Rafael Uribe Uribe | 40 | 9 |
| 19 | Ciudad Bolívar | 38 | 11 |
| 20 | Sumapaz | 46 | 5 |

### Proyectos por estado

| Estado | Real | Sintético |
|---|---|---|
| Cancelado | 3 | 7 |
| En ejecución | 247 | 65 |
| Finalizado | 144 | 71 |
| Programado | 350 | 27 |
| Suspendido | 0 | 10 |

### Presupuesto por localidad (COP)

| Localidad | Comprometido PP real | Vigente sintético | Comprometido sintético | Obligado sintético |
|---|---|---|---|---|
| Usaquén | $24.014.307.143 | $70.996.775.000 | $21.266.301.000 | $15.006.795.000 |
| Chapinero | $16.099.779.332 | $29.934.838.000 | $21.988.051.000 | $12.882.613.000 |
| Santa Fe | $24.800.404.022 | $20.395.855.000 | $10.653.989.000 | $8.873.768.000 |
| San Cristóbal | $51.205.258.112 | $71.528.986.000 | $47.050.016.000 | $31.674.201.000 |
| Usme | $40.413.533.886 | $37.322.430.000 | $21.349.041.000 | $11.604.974.000 |
| Tunjuelito | $15.145.257.432 | $43.747.931.000 | $23.838.159.000 | $16.393.890.000 |
| Bosa | $59.744.896.471 | $103.779.873.000 | $42.820.901.000 | $23.263.408.000 |
| Kennedy | $85.042.858.557 | $91.104.893.000 | $65.614.066.000 | $53.999.857.000 |
| Fontibón | $21.385.418.556 | $44.097.471.000 | $24.468.240.000 | $23.104.324.000 |
| Engativá | $50.565.728.456 | $23.953.723.000 | $8.899.814.000 | $6.511.165.000 |
| Suba | $68.602.419.218 | $99.671.126.000 | $27.281.411.000 | $17.478.882.000 |
| Barrios Unidos | $13.266.653.588 | $18.187.570.000 | $5.468.223.000 | $2.727.795.000 |
| Teusaquillo | $13.873.205.813 | $27.788.645.000 | $15.590.137.000 | $12.884.068.000 |
| Los Mártires | $15.344.737.286 | $34.627.078.000 | $22.984.752.000 | $15.903.615.000 |
| Antonio Nariño | $13.741.416.748 | $26.374.648.000 | $14.375.432.000 | $9.666.658.000 |
| Puente Aranda | $23.722.234.408 | $23.356.793.000 | $12.637.352.000 | $8.972.761.000 |
| La Candelaria | $9.112.293.276 | $23.999.800.000 | $14.568.536.000 | $13.432.154.000 |
| Rafael Uribe Uribe | $49.832.941.574 | $49.161.227.000 | $18.566.180.000 | $14.028.089.000 |
| Ciudad Bolívar | $54.584.672.337 | $79.216.445.000 | $60.544.993.000 | $46.610.808.000 |
| Sumapaz | $60.675.622.333 | $18.520.353.000 | $8.209.758.000 | $6.554.316.000 |

### Presupuesto por sector (COP)

| Sector | Tipo | Vigente | Comprometido |
|---|---|---|---|
| Cultura, recreación y deporte | REAL | n.d. | $190.389.155.244 |
| Mujeres | REAL | n.d. | $100.666.585.376 |
| Ambiente | REAL | n.d. | $92.466.657.566 |
| Desarrollo económico, industria y turismo | REAL | n.d. | $92.456.335.415 |
| Movilidad | REAL | n.d. | $75.424.699.153 |
| Gobierno | REAL | n.d. | $52.956.679.977 |
| Hábitat | REAL | n.d. | $38.333.072.015 |
| Seguridad, convivencia y justicia | REAL | n.d. | $24.799.483.758 |
| Gestión pública | REAL | n.d. | $21.609.185.753 |
| Integración social | REAL | n.d. | $13.183.313.134 |
| Ambiente / Desarrollo económico (mixto en la fuente) | REAL | n.d. | $5.021.656.304 |
| Educación | REAL | n.d. | $3.715.734.853 |
| Salud | REAL | n.d. | $151.080.000 |
| Movilidad | SINTETICO | $328.327.303.000 | $174.650.478.000 |
| Educación | SINTETICO | $167.212.973.000 | $68.023.032.000 |
| Hábitat | SINTETICO | $114.430.329.000 | $67.826.922.000 |
| Salud | SINTETICO | $123.965.802.000 | $58.068.904.000 |
| Cultura, recreación y deporte | SINTETICO | $82.270.211.000 | $51.707.680.000 |
| Seguridad, convivencia y justicia | SINTETICO | $37.287.544.000 | $17.534.213.000 |
| Ambiente | SINTETICO | $31.809.074.000 | $16.218.859.000 |
| Integración social | SINTETICO | $23.551.555.000 | $15.703.268.000 |
| Desarrollo económico, industria y turismo | SINTETICO | $14.424.550.000 | $7.600.555.000 |
| Mujeres | SINTETICO | $9.820.309.000 | $7.546.513.000 |
| Gobierno | SINTETICO | $4.666.810.000 | $3.294.928.000 |

### Distribución por vigencia (registros de presupuesto)

| Vigencia | Real | Sintético |
|---|---|---|
| 2021 | 292 | 0 |
| 2022 | 261 | 0 |
| 2023 | 296 | 0 |
| 2024 | 259 | 29 |
| 2025 | 367 | 103 |
| 2026 | 0 | 134 |
| 2027 | 0 | 79 |
| 2028 | 0 | 30 |
| 2029 | 0 | 3 |

## 6. Registros con información crítica faltante

- Proyectos reales sin fecha_inicio/fecha_fin (sin CRP con fecha): 360.
- Proyectos reales sin avance físico: 744 (la fuente no lo publica).
- Proyectos reales sin programa: 744 (la fuente no lo publica).
- Proyectos sin localidad: 0.

## 7. Validación funcional para el visor

| # | Indicador | Cómo se construye | Disponible |
|---|---|---|---|
| 1 | Número total de proyectos | count(proyectos.id_proyecto) | Sí (real + sintético) |
| 2-4 | Finalizados / En ejecución / Programados | count por estado_proyecto | Sí |
| 5 | Presupuesto total asignado | sum(presupuesto_inicial) | Solo sintético |
| 6 | Presupuesto vigente | sum(presupuesto_vigente) | Solo sintético |
| 7 | Comprometido | sum(presupuesto_comprometido) | Sí (real = solo componente PP) |
| 8 | Ejecutado (obligado) | sum(presupuesto_obligado) | Solo sintético |
| 9 | % ejecución | sum(obligado)/sum(vigente) | Solo sintético |
| 10-11 | Distribución de proyectos / presupuesto por localidad | join con localidades | Sí |
| 12 | Proyectos por sector | group by sector | Sí |
| 13 | Proyectos por vigencia | proyectos.vigencia o presupuesto.vigencia | Sí (2021-2027) |
| 14 | Evolución de la inversión | seguimiento_proyectos por fecha_corte | Sí (real: comprometido; sintético: todos) |
| 15 | Comparativo de ejecución entre localidades | presupuesto por localidad | Solo sintético (real: comprometido PP) |

Filtros: localidad, sector, estado_proyecto, vigencia y tipo_registro están presentes en `proyectos` y se propagan a presupuesto/seguimiento por `id_proyecto`. Una localidad seleccionada devuelve sus proyectos con estado, fechas y presupuesto.

**Recomendación para el visor:** mostrar por defecto un selector de `tipo_registro` y no sumar en el mismo KPI cifras REALES (componente PP) con SINTÉTICAS (total proyecto); rotular con `alcance_presupuestal`.
