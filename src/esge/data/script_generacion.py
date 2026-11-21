# -*- coding: utf-8 -*-
"""
script_generacion.py
Construcción del dataset del prototipo "Visor de Transparencia Territorial" – Bogotá D.C.

Etapas:
  1. Descarga de fuentes oficiales (API CKAN de Datos Abiertos Bogotá y servicio ArcGIS de
     Catastro/SDP). Si la red no está disponible, usa la copia local en ./raw/ (caché de la
     consulta del 2026-11-16).
  2. Transformación y homologación de los datos REALES (Presupuestos Participativos – SDP).
  3. Generación de datos SINTÉTICOS reproducibles (semilla fija).
  4. Integración, validaciones de calidad y escritura de entregables.

Uso:
    python script_generacion.py                # usa red si hay, si no la caché ./raw
    python script_generacion.py --offline      # solo caché

Requisitos: pandas, numpy, openpyxl (requests opcional para descarga en línea).
"""
import argparse
import gzip
import io
import json
import math
import os
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

SEED = 20261116
FECHA_CORTE = date(2026, 9, 30)          # corte de los datos oficiales de PP (archivo *_30-09-2026)
FECHA_CONSULTA = "2026-11-16"
BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, "raw")
OUT = BASE

CKAN = "https://datosabiertos.bogota.gov.co/api/3/action"
RES = {
    "pp_avance": "99d01780-ee33-40ff-9f09-2ecd62d9b1d9",
    "pp_comprometido": "7c5d5813-3621-47d7-92bc-fb46957988cb",
}
URL_PP_DATASET = "https://datosabiertos.bogota.gov.co/dataset/presupuestos-participativos-bogota-dc"
URL_PP_AVANCE = f"{URL_PP_DATASET}/resource/{RES['pp_avance']}"
URL_PP_COMP = f"{URL_PP_DATASET}/resource/{RES['pp_comprometido']}"
URL_SED = "https://datosabiertos.bogota.gov.co/dataset/territorializacion-de-la-inversion-en-el-sector-educativo-por-localidad-bogota-d-c"
SED_GEOJSON = {
    2025: URL_SED + "/resource/6c61a008-1cc7-4242-85cb-7d99cf309969/download/inversion12_2025.geojson",
    2024: URL_SED + "/resource/b02dce5e-e946-441d-b1cd-2f303e0abfd4/download/inversion12_2024.geojson",
}
URL_LOC_ARCGIS = ("https://serviciosgis.catastrobogota.gov.co/arcgis/rest/services/ordenamientoterritorial/"
                  "localidad/MapServer/0/query?where=1%3D1&outFields=*&returnGeometry=false&f=json")
URL_LOC_DATASET = "https://datosabiertos.bogota.gov.co/dataset/localidad-bogota-d-c"
URL_POB = ("https://datosabiertos.bogota.gov.co/dataset/0f1fb76a-1595-43d5-9257-0abcc3db908a/resource/"
           "5669484f-dc1d-4457-b1d1-de0a3825b41c/download/202503_localidad_proyeccion_retroproyeccion_poblacion_2005_2035.ods")
URL_POB_DATASET = "https://datosabiertos.bogota.gov.co/dataset/proyecciones-y-retroproyecciones-de-poblacion-2005-2035"

LOCALIDADES = [
    ("01", "Usaquén"), ("02", "Chapinero"), ("03", "Santa Fe"), ("04", "San Cristóbal"), ("05", "Usme"),
    ("06", "Tunjuelito"), ("07", "Bosa"), ("08", "Kennedy"), ("09", "Fontibón"), ("10", "Engativá"),
    ("11", "Suba"), ("12", "Barrios Unidos"), ("13", "Teusaquillo"), ("14", "Los Mártires"),
    ("15", "Antonio Nariño"), ("16", "Puente Aranda"), ("17", "La Candelaria"), ("18", "Rafael Uribe Uribe"),
    ("19", "Ciudad Bolívar"), ("20", "Sumapaz"),
]
LOC_NOMBRE = dict(LOCALIDADES)


# ----------------------------------------------------------------------------------------
# 1. EXTRACCIÓN
# ----------------------------------------------------------------------------------------
def _get(url, binary=False, timeout=60):
    import requests  # noqa
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content if binary else r.json()


def descargar_en_linea():
    """Descarga todas las fuentes desde los portales oficiales. Lanza excepción si no hay red."""
    raw = {"consultado": datetime.utcnow().isoformat()}
    for k, rid in RES.items():
        j = _get(f"{CKAN}/datastore_search?limit=32000&resource_id={rid}")
        recs = j["result"]["records"]
        for r in recs:
            r.pop("_id", None)
        raw[k] = recs
    for y, u in SED_GEOJSON.items():
        raw[f"sed_{y}"] = [f.get("properties") or f.get("attributes") for f in _get(u)["features"]]
    loc = _get(URL_LOC_ARCGIS)
    loc_attrs = [[a["LOCCODIGO"], a["LOCNOMBRE"], a["LOCAADMINI"], a["LOCAREA"]] for a in
                 (f["attributes"] for f in loc["features"])]
    pob = poblacion_desde_ods(_get(URL_POB, binary=True))
    return raw, loc_attrs, pob


def poblacion_desde_ods(content):
    """Suma columnas Hombres_*/Mujeres_* por localidad y año del ODS de SDP."""
    df = pd.read_excel(io.BytesIO(content), engine="odf")
    cols = [c for c in df.columns if str(c).startswith(("Hombres_", "Mujeres_"))]
    df["tot"] = df[cols].sum(axis=1)
    g = df.groupby(["Código Localidad", "AÑO"])["tot"].sum()
    return {f"{int(l)}|{int(y)}": int(v) for (l, y), v in g.items() if int(y) in (2024, 2025, 2026)}


def cargar_cache():
    raw = json.load(open(os.path.join(RAW, "datos_abiertos_bogota_raw.json"), encoding="utf-8"))
    loc_attrs = json.load(open(os.path.join(RAW, "localidades_sdp_arcgis.json"), encoding="utf-8"))["attrs"]
    pob = json.load(open(os.path.join(RAW, "poblacion_localidad_sdp.json"), encoding="utf-8"))["agg"]
    return raw, loc_attrs, pob


# ----------------------------------------------------------------------------------------
# 2. TRANSFORMACIÓN DE DATOS REALES
# ----------------------------------------------------------------------------------------
SECTOR_HOMOLOGADO = {
    "CULTURA, RECREACIÓN Y DEPORTE": "Cultura, recreación y deporte",
    "AMBIENTE": "Ambiente",
    "GOBIERNO": "Gobierno",
    "MUJERES": "Mujeres",
    "DESARROLLO ECONÓMICO, INDUSTRIA Y TURISMO": "Desarrollo económico, industria y turismo",
    "SEGURIDAD, CONVIVENCIA Y JUSTICIA": "Seguridad, convivencia y justicia",
    "HÁBITAT": "Hábitat",
    "MOVILIDAD": "Movilidad",
    "GESTIÓN PÚBLICA": "Gestión pública",
    "GESTIÓN PUBLICA": "Gestión pública",
    "INTEGRACIÓN SOCIAL": "Integración social",
    "SALUD": "Salud",
    "EDUCACIÓN": "Educación",
    "AMBIENTE / DESARROLLO ECONÓMICO": "Ambiente / Desarrollo económico (mixto en la fuente)",
}

# Homologación de estados de propuesta (fuente) -> categoría intermedia
ESTADO_PROPUESTA = {
    "Materializada": "F",
    "En ejecución": "E", "Contratada": "E",
    "En proceso de contratación": "P", "En formulación": "P", "Sin iniciar": "P",
    "Imposible ejecución (inviable)": "X", "No ejecutada": "X",
}


def homologar_estado_proyecto(estados, hubo_materializadas=False):
    """Regla documentada: se evalúan las propuestas de la ÚLTIMA vigencia del proyecto.
    E presente -> En ejecución; si no, P presente -> Programado; si no, F presente -> Finalizado;
    si solo hay X -> Cancelado. (La fuente no reporta 'Suspendido')."""
    s = {ESTADO_PROPUESTA.get(e, "?") for e in estados}
    if "E" in s:
        return "En ejecución"
    if "P" in s:
        return "Programado"
    if "F" in s:
        return "Finalizado"
    if "X" in s:
        # si la última vigencia solo tiene propuestas inviables/no ejecutadas pero hubo propuestas materializadas
        # en vigencias anteriores, el proyecto se considera Finalizado (con cierre parcial), no Cancelado
        return "Finalizado" if hubo_materializadas else "Cancelado"
    return None


def tipo_por_componente(comp):
    c = (comp or "").upper()
    if any(k in c for k in ("MALLA VIAL", "PARQUE", "INFRAESTRUCTURA", "OBRA", "ESPACIO PÚBLICO", "CONSTRUCCI")):
        return "Infraestructura y espacio público"
    if "DOTACI" in c:
        return "Dotación"
    if any(k in c for k in ("EVENTO", "FESTIVAL")):
        return "Eventos y actividades"
    if any(k in c for k in ("FORMACI", "CAPACITACI", "EDUCACI", "DESARROLLO DE CAPACIDADES")):
        return "Formación y capacitación"
    if any(k in c for k in ("PREVENCI", "CUIDADO", "BIENESTAR", "ATENCI", "APOYO")):
        return "Servicios sociales y prevención"
    if any(k in c for k in ("FORTALECIMIENTO", "TRANSFORMACI", "INDUSTRIA", "PRODUCTIV", "EMPRENDIM")):
        return "Fortalecimiento organizativo y económico"
    if any(k in c for k in ("AGRICULTURA", "HUERTA", "ARBORIZ", "ARBOLADO", "RESTAURACI", "SOSTENIBILIDAD",
                            "CONSUMO", "SEPARACI", "CONECTOR", "CONSERVACI", "RENATURALIZ", "MUROS VERDES",
                            "JARDINER", "RIESGO", "EMERGENCIA", "ACUEDUCTO", "ESTERILIZ")):
        return "Ambiente y gestión del riesgo"
    if any(k in c for k in ("PAZ", "CONVIVENCIA", "SEGURIDAD", "JUSTICIA", "CONFLICT", "ACUERDO", "JUECES")):
        return "Convivencia, paz y justicia"
    if any(k in c for k in ("PEDAG", "SALUD MENTAL", "RECREODEPORTIV", "INICIATIVA", "TURÍST", "TURIST",
                            "TEJIDO EMPRESARIAL", "CONECTIVIDAD", "ASISTENCIA TÉCNICA", "MEDIOS", "VIVIENDA",
                            "REVITALIZ", "ENTREGA DE ELEMENTOS")):
        return "Servicios sociales y prevención" if any(k in c for k in ("SALUD", "PEDAG")) else \
               ("Dotación" if "ENTREGA" in c else
                ("Infraestructura y espacio público" if any(k in c for k in ("VIVIENDA", "REVITALIZ")) else
                 ("Eventos y actividades" if any(k in c for k in ("RECREODEPORTIV",)) else
                  "Fortalecimiento organizativo y económico")))
    if "INTERVENCI" in c:
        return "Intervención territorial"
    return "Otros"


def quarter_end(d):
    m = ((d.month - 1) // 3 + 1) * 3
    return (pd.Timestamp(date(d.year, m, 1)) + pd.offsets.MonthEnd(0)).date()


def quarter_ends(start, end):
    """Cierres trimestrales desde el trimestre de `start` hasta `end` (inclusive)."""
    out, c = [], quarter_end(start)
    while c <= end:
        out.append(c)
        c = quarter_end(c + timedelta(days=1))
    return out


def parse_fecha(s):
    try:
        d, m, y = str(s).strip().split("/")
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def parse_valor(s):
    t = "".join(ch for ch in str(s or "") if ch.isdigit() or ch == ",")
    t = t.split(",")[0]
    return float(t) if t else None


def plazo_dias(p):
    """La columna Plazo mezcla unidades: valores <= 36 se interpretan como meses, mayores como días."""
    try:
        v = float(str(p).strip())
    except Exception:
        return None
    if v <= 0:
        return None
    return v * 30.4 if v <= 36 else v


def transformar_reales(raw, log):
    A = pd.DataFrame(raw["pp_avance"])
    C = pd.DataFrame(raw["pp_comprometido"])
    for df in (A, C):
        for c in df.columns:
            if df[c].dtype == object or pd.api.types.is_string_dtype(df[c]):
                df[c] = df[c].astype(str).str.strip()
        df["codigo_localidad"] = df["No_Localidad"].astype(int).map("{:02d}".format)
        df["id_proyecto"] = "FDL" + df["codigo_localidad"] + "-" + df["Codigo_Proyecto"]
        df["vigencia"] = df["Vigencia_Ejecucion"].astype(int)
    log["reales_propuestas"] = len(A)
    log["reales_crp"] = len(C)
    log["dup_propuestas"] = int(A.duplicated().sum())
    log["dup_crp"] = int(C.duplicated().sum())
    A = A.drop_duplicates()
    C = C.drop_duplicates()

    C["fecha_registro"] = C["Fecha_Registro"].map(parse_fecha)
    C["valor"] = C["Valor_CRP_Asignado_presupuestos_participativos"].map(parse_valor)
    C["plazo_dias"] = C["Plazo"].map(plazo_dias)
    log["crp_fecha_invalida"] = int(C["fecha_registro"].isna().sum())
    log["crp_valor_invalido"] = int(C["valor"].isna().sum())
    log["crp_vigencia_vs_anio_registro_distinto"] = int(
        sum(1 for f, v in zip(C["fecha_registro"], C["vigencia"]) if f and f.year != v))
    C["fecha_fin_est"] = [f + timedelta(days=int(p)) if f and p and p == p else None
                          for f, p in zip(C["fecha_registro"], C["plazo_dias"])]
    log["crp_huerfanos"] = int((~C["id_proyecto"].isin(A["id_proyecto"])).sum())

    proyectos = []
    for pid, g in A.groupby("id_proyecto"):
        ult = g["vigencia"].max()
        gu = g[g["vigencia"] == ult]
        comp = Counter(g["Componente_proyecto"]).most_common(1)[0][0]
        sectores = sorted({SECTOR_HOMOLOGADO.get(s.upper(), s) for s in g["Sector"]})
        entidades = sorted(set(g["Entidad"]))
        nombres = Counter(g["Nombre_Proyecto"]).most_common()
        c = C[C["id_proyecto"] == pid]
        fi = min([f for f in c["fecha_registro"] if f], default=None)
        ff = max([f for f in c["fecha_fin_est"] if f], default=None)
        estados_ult = list(gu["Estado_propuesta"])
        n_mat = sum(ESTADO_PROPUESTA.get(e) == "F" for e in g["Estado_propuesta"])
        pobl = pd.to_numeric(g["Total_poblacion_beneficiada_en_la_ejecucion"].str.replace(".", "", regex=False)
                             .str.replace(",", "", regex=False), errors="coerce").sum()
        cl = g["codigo_localidad"].iloc[0]
        metas = sorted(set(g["Meta_proyecto"]))
        desc = ("Proyecto de inversión local con componente de Presupuestos Participativos. Metas asociadas: "
                + " | ".join(metas[:3]) + (" | …" if len(metas) > 3 else ""))
        proyectos.append(dict(
            id_proyecto=pid,
            codigo_proyecto_oficial=g["Codigo_Proyecto"].iloc[0],
            nombre_proyecto=nombres[0][0],
            descripcion_proyecto=desc[:600],
            entidad_responsable=f"Alcaldía Local de {LOC_NOMBRE[cl]} – Fondo de Desarrollo Local",
            entidad_sector_rector="; ".join(entidades),
            sector=Counter(SECTOR_HOMOLOGADO.get(x.upper(), x) for x in g["Sector"]).most_common(1)[0][0],
            sectores_fuente="; ".join(sectores),
            programa=None,
            componente_principal=comp,
            localidad=LOC_NOMBRE[cl],
            codigo_localidad=cl,
            fecha_inicio=fi, fecha_fin=ff,
            vigencia=int(ult),
            vigencias_ejecucion=";".join(str(v) for v in sorted(g["vigencia"].unique())),
            estado_fuente="; ".join(f"{k}: {v}" for k, v in Counter(estados_ult).most_common()),
            estado_proyecto=homologar_estado_proyecto(estados_ult, n_mat > 0),
            porcentaje_avance=None,
            porcentaje_propuestas_materializadas=round(100 * n_mat / len(g), 1),
            num_propuestas_ciudadanas=int(len(g)),
            num_metas=int(g["Cod_meta_proyecto_extendida"].nunique()),
            poblacion_beneficiada_reportada=int(pobl) if pobl == pobl else None,
            tipo_proyecto=tipo_por_componente(comp),
            fuente_dato="SDP – Presupuestos Participativos Bogotá D.C. (Estado de avance propuestas priorizadas; "
                        "Presupuesto comprometido por meta proyecto)",
            url_fuente=URL_PP_AVANCE,
            tipo_registro="REAL",
            nivel_confiabilidad="Oficial parcialmente completo",
            campos_derivados="entidad_responsable; sector (homologado); estado_proyecto (homologado); "
                             "fecha_inicio/fecha_fin (estimadas desde CRP); tipo_proyecto; descripcion_proyecto",
        ))
    P = pd.DataFrame(proyectos)
    log["nombres_multiples_por_proyecto"] = int(A.groupby("id_proyecto")["Nombre_Proyecto"].nunique().gt(1).sum())

    # Presupuesto real: un registro por proyecto-vigencia
    pres = []
    pv = A.groupby(["id_proyecto", "vigencia"]).size().reset_index()[["id_proyecto", "vigencia"]]
    csum = C.groupby(["id_proyecto", "vigencia"]).agg(comp=("valor", "sum"), n=("valor", "size")).reset_index()
    pv = pv.merge(csum, on=["id_proyecto", "vigencia"], how="outer")
    for _, r in pv.iterrows():
        cl = r["id_proyecto"][3:5]
        pres.append(dict(
            id_proyecto=r["id_proyecto"], localidad=LOC_NOMBRE[cl], codigo_localidad=cl, vigencia=int(r["vigencia"]),
            alcance_presupuestal="Componente Presupuestos Participativos (suma de CRP)",
            presupuesto_inicial=None, presupuesto_vigente=None,
            presupuesto_comprometido=float(r["comp"]) if r["comp"] == r["comp"] else None,
            presupuesto_obligado=None, presupuesto_pagado=None,
            porcentaje_ejecucion_presupuestal=None,
            num_compromisos_crp=int(r["n"]) if r["n"] == r["n"] else 0,
            tipo_registro="REAL", nivel_confiabilidad="Oficial parcialmente completo",
            fuente_dato="SDP – Presupuesto comprometido por meta proyecto y propuestas financiadas",
            url_fuente=URL_PP_COMP,
        ))
    PR = pd.DataFrame(pres)

    # Seguimiento real: comprometido acumulado a cada cierre trimestral (derivado de fechas de CRP)
    seg = []
    for (pid, vig), g in C.groupby(["id_proyecto", "vigencia"]):
        fechas = [f for f in g["fecha_registro"] if f]
        if not fechas:
            continue
        fmax = max(fechas + [date(vig, 12, 31)])
        cortes = [c for c in quarter_ends(min(fechas + [date(vig, 1, 1)]), quarter_end(fmax)) if c <= FECHA_CORTE]
        prev = None
        for c in cortes:
            v = float(g.loc[[bool(f and f <= c) for f in g["fecha_registro"]], "valor"].sum())
            if v == 0 or v == prev:
                prev = v if v else prev
                continue
            prev = v
            seg.append(dict(id_proyecto=pid, fecha_corte=c, vigencia=int(vig), porcentaje_avance_fisico=None,
                            presupuesto_vigente=None, presupuesto_comprometido=v, presupuesto_obligado=None,
                            presupuesto_pagado=None, tipo_registro="REAL",
                            nivel_confiabilidad="Oficial parcialmente completo",
                            nota="Comprometido acumulado de CRP de Presupuestos Participativos registrados hasta la fecha de corte"))
    S = pd.DataFrame(seg)
    return P, PR, S


# ----------------------------------------------------------------------------------------
# 3. DATOS SINTÉTICOS
# ----------------------------------------------------------------------------------------
PLANTILLAS = [
    # sector, tipo_proyecto, programa (genérico), entidad distrital, rango COP (min,max), meses (min,max), plantillas de nombre
    ("Movilidad", "Infraestructura vial", "Movilidad local segura y sostenible", "Instituto de Desarrollo Urbano - IDU",
     (3.0e9, 28e9), (10, 30), ["Rehabilitación de la malla vial local del sector {b}",
                               "Construcción de andenes y cicloinfraestructura en el eje {b}",
                               "Mantenimiento de vías locales y puentes peatonales en {b}"]),
    ("Hábitat", "Espacio público", "Espacio público vital y accesible", "Departamento Administrativo de la Defensoría del Espacio Público - DADEP",
     (1.2e9, 14e9), (8, 24), ["Recuperación del espacio público del entorno de {b}",
                              "Adecuación de alamedas y plazoletas en {b}",
                              "Mejoramiento integral de entornos barriales en {b}"]),
    ("Cultura, recreación y deporte", "Infraestructura y espacio público", "Parques y escenarios para la vida",
     "Instituto Distrital de Recreación y Deporte - IDRD", (8e8, 12e9), (8, 22),
     ["Construcción y dotación del parque vecinal {b}", "Adecuación de escenario deportivo en {b}"]),
    ("Educación", "Infraestructura educativa", "Ambientes de aprendizaje dignos", "Secretaría de Educación del Distrito",
     (4e9, 35e9), (12, 30), ["Ampliación y adecuación de sede educativa distrital en {b}",
                             "Reforzamiento estructural de colegio distrital en {b}"]),
    ("Educación", "Dotación", "Ambientes de aprendizaje dignos", "Secretaría de Educación del Distrito",
     (2e8, 2.5e9), (4, 10), ["Dotación tecnológica para colegios distritales de {loc}",
                             "Dotación de laboratorios y bibliotecas escolares en {loc}"]),
    ("Salud", "Infraestructura de salud", "Salud cercana al territorio", "Secretaría Distrital de Salud",
     (5e9, 32e9), (14, 30), ["Construcción de centro de atención prioritaria en salud en {b}",
                             "Adecuación de unidad de servicios de salud en {b}"]),
    ("Salud", "Servicios sociales y prevención", "Salud cercana al territorio", "Secretaría Distrital de Salud",
     (3e8, 3e9), (6, 12), ["Ayudas técnicas para personas con discapacidad en {loc}",
                           "Estrategia local de salud mental comunitaria en {loc}"]),
    ("Seguridad, convivencia y justicia", "Dotación", "Territorios seguros y en convivencia",
     "Secretaría Distrital de Seguridad, Convivencia y Justicia", (8e8, 6e9), (6, 14),
     ["Ampliación del sistema de videovigilancia en {b}", "Dotación para organismos de seguridad en {loc}"]),
    ("Seguridad, convivencia y justicia", "Servicios sociales y prevención", "Territorios seguros y en convivencia",
     "Secretaría Distrital de Seguridad, Convivencia y Justicia", (2e8, 1.8e9), (5, 11),
     ["Estrategia de prevención de violencias y convivencia en {loc}", "Gestores de convivencia para {b}"]),
    ("Ambiente", "Intervención territorial", "Territorio verde y resiliente", "Secretaría Distrital de Ambiente",
     (3e8, 4.5e9), (6, 18), ["Restauración ecológica de la ronda de quebrada en {b}",
                             "Plantación y mantenimiento de arbolado urbano en {loc}",
                             "Agricultura urbana y huertas comunitarias en {loc}"]),
    ("Ambiente", "Infraestructura y espacio público", "Territorio verde y resiliente", "Instituto Distrital de Gestión de Riesgos y Cambio Climático - IDIGER",
     (1e9, 9e9), (8, 20), ["Obras de mitigación de riesgo en el sector {b}"]),
    ("Cultura, recreación y deporte", "Eventos y actividades", "Cultura y deporte para el encuentro",
     "Secretaría Distrital de Cultura, Recreación y Deporte", (1.5e8, 1.8e9), (4, 10),
     ["Festival local de las artes de {loc}", "Escuelas de formación deportiva en {loc}",
      "Circulación de agrupaciones culturales de {loc}"]),
    ("Integración social", "Servicios sociales y prevención", "Cuidado e inclusión social", "Secretaría Distrital de Integración Social",
     (4e8, 4.5e9), (6, 12), ["Apoyo económico tipo C para personas mayores de {loc}",
                             "Estrategia de cuidado para la primera infancia en {loc}",
                             "Atención integral a población en riesgo social en {loc}"]),
    ("Mujeres", "Servicios sociales y prevención", "Cuidado e inclusión social", "Secretaría Distrital de la Mujer",
     (2e8, 1.5e9), (5, 11), ["Prevención de violencias contra las mujeres en {loc}",
                             "Fortalecimiento de la manzana del cuidado en {loc}"]),
    ("Desarrollo económico, industria y turismo", "Fortalecimiento organizativo y económico", "Reactivación económica local",
     "Secretaría Distrital de Desarrollo Económico", (3e8, 3.5e9), (5, 12),
     ["Fortalecimiento de micro y pequeñas empresas de {loc}", "Apoyo a emprendimientos de economía popular en {loc}"]),
    ("Gobierno", "Fortalecimiento organizativo y económico", "Gobierno local abierto", "Secretaría Distrital de Gobierno",
     (2e8, 2.5e9), (6, 12), ["Fortalecimiento de organizaciones sociales y comunales de {loc}",
                             "Dotación de salones comunales de {loc}"]),
]
PESO_PLANTILLA = [10, 8, 7, 5, 4, 4, 4, 4, 4, 5, 3, 7, 7, 4, 5, 4]
FACTOR_LOC = {  # factor de escala presupuestal sintético (supuesto: mayor en localidades grandes/vulnerables)
    "01": 0.95, "02": 0.8, "03": 0.9, "04": 1.15, "05": 1.25, "06": 0.9, "07": 1.3, "08": 1.3, "09": 0.95,
    "10": 1.1, "11": 1.2, "12": 0.8, "13": 0.7, "14": 0.75, "15": 0.7, "16": 0.85, "17": 0.6, "18": 1.1,
    "19": 1.4, "20": 0.7,
}
SECTORES_BARRIO = ["norte", "sur", "oriental", "occidental", "central", "alto", "bajo"]


def _round_money(x):
    return float(round(x / 1000.0) * 1000)


def months_between(a, b):
    return (b - a).days / 30.4


def generar_sinteticos(n, poblacion, log):
    rng = np.random.default_rng(SEED)
    pobs = np.array([poblacion.get(f"{int(c)}|2025", 1) for c, _ in LOCALIDADES], dtype=float)
    w = 4 + (n - 80) * (np.sqrt(pobs) / np.sqrt(pobs).sum())      # mínimo 4 por localidad
    cnt = np.floor(w).astype(int)
    while cnt.sum() < n:
        cnt[np.argmax(w - cnt)] += 1
    locs = [c for (c, _), k in zip(LOCALIDADES, cnt) for _ in range(k)]
    rng.shuffle(locs)
    pw = np.array(PESO_PLANTILLA, float) / sum(PESO_PLANTILLA)
    usados = set()
    proyectos, pres, seg = [], [], []
    for i, cl in enumerate(locs, start=1):
        t = PLANTILLAS[rng.choice(len(PLANTILLAS), p=pw)]
        sector, tipo, programa, ent_d, (bmin, bmax), (mmin, mmax), nombres = t
        loc = LOC_NOMBRE[cl]
        b = f"{rng.choice(SECTORES_BARRIO)} de {loc}"
        nombre = rng.choice(nombres).format(b=b, loc=loc)
        k = 2
        base_nombre = nombre
        while nombre in usados:
            nombre = f"{base_nombre} – fase {k}"; k += 1
        usados.add(nombre)
        local = rng.random() < 0.65
        entidad = f"Alcaldía Local de {loc} – Fondo de Desarrollo Local" if local else ent_d
        # fechas: inicio entre 2024-02 y 2027-06 (sesgo hacia 2024-2025)
        u = rng.beta(2.0, 1.9)
        inicio = date(2024, 3, 1) + timedelta(days=int(u * (date(2027, 6, 30) - date(2024, 3, 1)).days))
        dur = int(rng.uniform(mmin, mmax) * 30.4)
        fin = inicio + timedelta(days=dur)
        # estado por fechas + eventos de suspensión/cancelación
        if inicio > FECHA_CORTE:
            estado = "Programado"
        elif fin <= FECHA_CORTE:
            estado = "Cancelado" if rng.random() < 0.04 else "Finalizado"
        else:
            r = rng.random()
            estado = "Suspendido" if r < 0.13 else ("Cancelado" if r < 0.15 else "En ejecución")
        elapsed = max(0.0, min(1.0, (FECHA_CORTE - inicio).days / max(1, (fin - inicio).days)))
        if estado == "Finalizado":
            avance = 100.0
        elif estado == "Programado":
            avance = 0.0
        elif estado == "En ejecución":
            avance = float(np.clip(elapsed * 100 + rng.normal(-5, 8), 5, 95))
        elif estado == "Suspendido":
            avance = float(np.clip(elapsed * 60 + rng.normal(0, 6), 5, 80))
        else:  # Cancelado
            avance = float(np.clip(rng.uniform(0, 35) * min(1, elapsed * 2), 0, 35))
        avance = round(avance, 1)
        total = math.exp(rng.uniform(math.log(bmin), math.log(bmax))) * FACTOR_LOC[cl]
        pid = f"SIN-{i:04d}"
        # distribución del presupuesto por vigencias (proporcional a días del proyecto en cada año)
        years = list(range(inicio.year, fin.year + 1))
        dias = []
        for y in years:
            a = max(inicio, date(y, 1, 1)); z = min(fin, date(y, 12, 31))
            dias.append(max(1, (z - a).days + 1))
        fr = np.array(dias, float) / sum(dias)
        filas_vig = []
        for y, f in zip(years, fr):
            ini = _round_money(total * f * rng.uniform(0.97, 1.03))
            while ini in usados:
                ini += 1000
            usados.add(ini)
            vig = _round_money(ini * rng.uniform(0.85, 1.15))
            fin_y = min(fin, date(y, 12, 31))
            if y > FECHA_CORTE.year or estado == "Programado":
                comp = _round_money(vig * rng.uniform(0, 0.3)) if (estado == "Programado" and y == FECHA_CORTE.year) else 0.0
                obl = pag = 0.0
            elif y < FECHA_CORTE.year or fin_y <= FECHA_CORTE:
                # vigencia cerrada o tramo terminado antes del corte
                if estado == "Cancelado":
                    comp = _round_money(vig * rng.uniform(0.05, 0.45)); obl = _round_money(comp * rng.uniform(0.3, 0.9))
                elif estado == "Suspendido":
                    comp = _round_money(vig * rng.uniform(0.6, 0.95)); obl = _round_money(comp * rng.uniform(0.4, 0.8))
                else:
                    comp = _round_money(vig * rng.uniform(0.9, 1.0)); obl = _round_money(comp * rng.uniform(0.82, 0.99))
                pag = _round_money(obl * rng.uniform(0.85, 1.0))
            else:  # vigencia en curso al corte
                if estado == "Cancelado":
                    comp = _round_money(vig * rng.uniform(0.0, 0.3)); obl = _round_money(comp * rng.uniform(0.0, 0.6))
                elif estado == "Suspendido":
                    comp = _round_money(vig * rng.uniform(0.4, 0.85)); obl = _round_money(comp * rng.uniform(0.2, 0.55))
                else:
                    comp = _round_money(vig * rng.uniform(0.55, 0.97)); obl = _round_money(comp * rng.uniform(0.25, 0.7))
                pag = _round_money(obl * rng.uniform(0.7, 0.95))
            comp, obl, pag = min(comp, vig), min(obl, comp), min(pag, obl)
            pct = round(100 * obl / vig, 2) if vig > 0 else None
            filas_vig.append(dict(id_proyecto=pid, localidad=loc, codigo_localidad=cl, vigencia=y,
                                  alcance_presupuestal="Total del proyecto (sintético)",
                                  presupuesto_inicial=ini, presupuesto_vigente=vig, presupuesto_comprometido=comp,
                                  presupuesto_obligado=obl, presupuesto_pagado=pag,
                                  porcentaje_ejecucion_presupuestal=pct, num_compromisos_crp=None,
                                  tipo_registro="SINTETICO", nivel_confiabilidad="Sintético",
                                  fuente_dato="Generación sintética (script_generacion.py, semilla %d)" % SEED,
                                  url_fuente=None))
        pres += filas_vig
        # seguimiento trimestral
        fin_ref = min(FECHA_CORTE, fin)
        cortes = [] if estado == "Programado" else [
            d for d in quarter_ends(inicio, quarter_end(fin_ref)) if d <= FECHA_CORTE]
        for ce in cortes:
            fv = next(x for x in filas_vig if x["vigencia"] == ce.year) if any(x["vigencia"] == ce.year for x in filas_vig) else None
            if fv is None:
                continue
            a = max(inicio, date(ce.year, 1, 1)); z_end = min(fin_ref, date(ce.year, 12, 31))
            f = 1.0 if ce >= z_end else max(0.0, min(1.0, (ce - a).days / max(1, (z_end - a).days)))
            g_av = max(0.0, min(1.0, (ce - inicio).days / max(1, (fin_ref - inicio).days)))
            av = round(avance * (g_av ** 1.1), 1) if ce < fin_ref else avance
            seg.append(dict(id_proyecto=pid, fecha_corte=ce, vigencia=ce.year, porcentaje_avance_fisico=av,
                            presupuesto_vigente=fv["presupuesto_vigente"],
                            presupuesto_comprometido=_round_money(fv["presupuesto_comprometido"] * f),
                            presupuesto_obligado=_round_money(fv["presupuesto_obligado"] * f ** 1.3),
                            presupuesto_pagado=_round_money(fv["presupuesto_pagado"] * f ** 1.5),
                            tipo_registro="SINTETICO", nivel_confiabilidad="Sintético",
                            nota="Serie trimestral sintética"))
        proyectos.append(dict(
            id_proyecto=pid, codigo_proyecto_oficial=None, nombre_proyecto=nombre,
            descripcion_proyecto=f"[Registro sintético – no corresponde a un proyecto real] {tipo} del sector {sector.lower()} "
                                 f"en la localidad de {loc}, construido para pruebas del prototipo.",
            entidad_responsable=entidad, entidad_sector_rector=ent_d, sector=sector, sectores_fuente=None, programa=programa,
            componente_principal=None, localidad=loc, codigo_localidad=cl, fecha_inicio=inicio, fecha_fin=fin,
            vigencia=min(max(years), max(FECHA_CORTE.year, min(years))) if estado != "Programado" else min(years),
            vigencias_ejecucion=";".join(map(str, years)), estado_fuente=None, estado_proyecto=estado,
            porcentaje_avance=avance, porcentaje_propuestas_materializadas=None, num_propuestas_ciudadanas=None,
            num_metas=None, poblacion_beneficiada_reportada=None, tipo_proyecto=tipo,
            fuente_dato="Generación sintética (script_generacion.py, semilla %d)" % SEED, url_fuente=None,
            tipo_registro="SINTETICO", nivel_confiabilidad="Sintético", campos_derivados="Todos (sintético)"))
    return pd.DataFrame(proyectos), pd.DataFrame(pres), pd.DataFrame(seg)


# ----------------------------------------------------------------------------------------
# 4. LOCALIDADES Y TABLA COMPLEMENTARIA SED
# ----------------------------------------------------------------------------------------
def construir_localidades(loc_attrs, pob):
    area = {a[0]: (a[3], a[2]) for a in loc_attrs}
    rows = []
    for c, n in LOCALIDADES:
        rows.append(dict(codigo_localidad=c, nombre_localidad=n,
                         poblacion=pob.get(f"{int(c)}|2025"), poblacion_anio=2025,
                         poblacion_2026=pob.get(f"{int(c)}|2026"),
                         area_m2=round(area[c][0], 1), area_km2=round(area[c][0] / 1e6, 3),
                         acto_administrativo=area[c][1],
                         fuente_poblacion="SDP – Proyecciones y retroproyecciones de población por localidad 2005-2035 (versión 2025-03)",
                         url_poblacion=URL_POB_DATASET,
                         fuente_area="SDP/IDECA – Localidad Bogotá D.C. (atributo LOCAREA, servicio ArcGIS)",
                         url_area=URL_LOC_DATASET, tipo_registro="REAL", nivel_confiabilidad="Oficial verificado"))
    return pd.DataFrame(rows)


def construir_sed(raw):
    rows = []
    for y in (2024, 2025):
        for p in raw.get(f"sed_{y}", []):
            cl = str(p["COD_LOCA"]).zfill(2)
            asig = p.get("R_ASIGNADOS", p.get("R_ASIGNADO"))   # el esquema cambia entre versiones
            ejec = p.get("R_EJECUTADOS", p.get("R_EJECUTAD"))
            rows.append(dict(codigo_localidad=cl, localidad=LOC_NOMBRE.get(cl), vigencia=y, sector="Educación",
                             entidad="Secretaría de Educación del Distrito", recursos_asignados=asig,
                             recursos_ejecutados=ejec, recursos_girados=p["R_GIRADOS"],
                             porcentaje_ejecucion=round(100 * ejec / asig, 2) if asig else None,
                             fecha_corte=str(p.get("Fecha", ""))[:10], tipo_registro="REAL",
                             nivel_confiabilidad="Oficial verificado",
                             fuente_dato="SED – Territorialización de la inversión en el sector educativo por localidad",
                             url_fuente=URL_SED))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------
# 5. VALIDACIONES
# ----------------------------------------------------------------------------------------
def validar(P, PR, S, L):
    v = []
    def chk(nombre, ok, detalle=""):
        v.append(dict(validacion=nombre, resultado="OK" if ok else "REVISAR", detalle=detalle))
    chk("id_proyecto único", P["id_proyecto"].is_unique, f"{len(P)} proyectos")
    chk("Localidades válidas (20 oficiales)", set(P["codigo_localidad"]) <= set(L["codigo_localidad"]),
        f"{P['codigo_localidad'].nunique()} localidades con proyectos")
    chk("Sin presupuestos huérfanos", PR["id_proyecto"].isin(P["id_proyecto"]).all())
    chk("Sin seguimientos huérfanos", S["id_proyecto"].isin(P["id_proyecto"]).all())
    chk("Sin duplicados proyecto-vigencia en presupuesto", not PR.duplicated(["id_proyecto", "vigencia"]).any())
    chk("Sin duplicados proyecto-fecha_corte en seguimiento", not S.duplicated(["id_proyecto", "fecha_corte"]).any())
    for col in ("fecha_inicio", "fecha_fin"):
        x = P[col].dropna()
        chk(f"{col} válida (2015-2030)", x.map(lambda d: date(2015, 1, 1) <= d <= date(2030, 12, 31)).all(),
            f"{P[col].isna().sum()} nulos")
    fi_ff = P.dropna(subset=["fecha_inicio", "fecha_fin"])
    chk("fecha_inicio <= fecha_fin", (fi_ff["fecha_inicio"] <= fi_ff["fecha_fin"]).all())
    syn = P[P.tipo_registro == "SINTETICO"]; real = P[P.tipo_registro == "REAL"]
    chk("SINT: Finalizado con fecha_fin <= corte", (syn[syn.estado_proyecto == "Finalizado"]["fecha_fin"] <= FECHA_CORTE).all())
    chk("SINT: Programado con fecha_inicio > corte", (syn[syn.estado_proyecto == "Programado"]["fecha_inicio"] > FECHA_CORTE).all())
    chk("SINT: En ejecución con inicio <= corte < fin",
        ((syn[syn.estado_proyecto == "En ejecución"]["fecha_inicio"] <= FECHA_CORTE) &
         (syn[syn.estado_proyecto == "En ejecución"]["fecha_fin"] > FECHA_CORTE)).all())
    chk("SINT: Finalizado avance 100%", (syn[syn.estado_proyecto == "Finalizado"]["porcentaje_avance"] == 100).all())
    chk("SINT: Programado avance 0%", (syn[syn.estado_proyecto == "Programado"]["porcentaje_avance"] == 0).all())
    rf = real[(real.estado_proyecto == "Finalizado") & real.fecha_fin.notna()]
    n_inc = int((rf["fecha_fin"] > FECHA_CORTE).sum())
    chk("REAL: Finalizado con fecha_fin estimada <= corte (informativo)", n_inc == 0,
        f"{n_inc} proyectos reales finalizados con fecha fin estimada posterior al corte (no se corrigen)")
    p = PR
    num = ["presupuesto_inicial", "presupuesto_vigente", "presupuesto_comprometido", "presupuesto_obligado", "presupuesto_pagado"]
    chk("Valores presupuestales >= 0", (p[num].fillna(0) >= 0).all().all())
    s2 = p[p.tipo_registro == "SINTETICO"]
    chk("comprometido <= vigente", (s2.presupuesto_comprometido <= s2.presupuesto_vigente).all())
    chk("obligado <= comprometido", (s2.presupuesto_obligado <= s2.presupuesto_comprometido).all())
    chk("pagado <= obligado", (s2.presupuesto_pagado <= s2.presupuesto_obligado).all())
    pc = p.porcentaje_ejecucion_presupuestal.dropna()
    chk("% ejecución en [0,100]", ((pc >= 0) & (pc <= 100)).all())
    chk("Presupuestos iniciales sintéticos no repetidos", s2.presupuesto_inicial.is_unique)
    ss = S[S.tipo_registro == "SINTETICO"].sort_values(["id_proyecto", "fecha_corte"])
    mono = all((g[c].diff().fillna(0) >= -1).all() for _, g in ss.groupby(["id_proyecto", "vigencia"])
               for c in ("presupuesto_comprometido", "presupuesto_obligado", "presupuesto_pagado"))
    chk("Seguimiento: acumulados monotónicos dentro de cada vigencia", mono)
    chk("Seguimiento: obligado <= comprometido y pagado <= obligado",
        ((ss.presupuesto_obligado <= ss.presupuesto_comprometido) & (ss.presupuesto_pagado <= ss.presupuesto_obligado)).all())
    chk("REAL: sin ejecución inventada (inicial/vigente/obligado/pagado nulos)",
        p[p.tipo_registro == "REAL"][["presupuesto_inicial", "presupuesto_vigente", "presupuesto_obligado", "presupuesto_pagado"]].isna().all().all())
    chk("Todos los registros con tipo_registro", P.tipo_registro.isin(["REAL", "SINTETICO"]).all() and PR.tipo_registro.isin(["REAL", "SINTETICO"]).all())
    return pd.DataFrame(v)


# ----------------------------------------------------------------------------------------
# 6. DOCUMENTACIÓN (diccionario, inventario, informe)
# ----------------------------------------------------------------------------------------
def diccionario():
    R, S_, D = "REAL", "SINTETICO", "DERIVADO"
    pp = "SDP Presupuestos Participativos"
    filas = [
        # tabla, campo, descripción, tipo, formato, valores, fuente, origen
        ("proyectos", "id_proyecto", "Identificador único del proyecto. Reales: FDL{cód. localidad}-{cód. proyecto oficial}; sintéticos: SIN-####", "texto", "FDL##-#### / SIN-####", "Único", f"{pp} / sintético", f"{D} (real) / {S_}"),
        ("proyectos", "codigo_proyecto_oficial", "Código del proyecto de inversión local en la fuente oficial", "texto", "####", "Nulo en sintéticos", pp, R),
        ("proyectos", "nombre_proyecto", "Nombre del proyecto (el más frecuente en la fuente)", "texto", "", "", f"{pp} / sintético", f"{R} / {S_}"),
        ("proyectos", "descripcion_proyecto", "Descripción. Reales: construida con las metas oficiales del proyecto. Sintéticos: inicia con la marca [Registro sintético]", "texto", "", "", f"{pp} / sintético", f"{D} / {S_}"),
        ("proyectos", "entidad_responsable", "Entidad que ejecuta. Reales: Alcaldía Local – FDL (los proyectos de PP son de los FDL)", "texto", "", "", "Derivado de localidad", f"{D} / {S_}"),
        ("proyectos", "entidad_sector_rector", "Entidad(es) del sector reportadas en la fuente (rector sectorial)", "texto", "Separador ';'", "", f"{pp} (campo Entidad)", f"{R} / {S_}"),
        ("proyectos", "sector", "Sector de inversión homologado", "texto", "", "Ver hoja Homologaciones", f"{pp} (campo Sector)", f"{D} / {S_}"),
        ("proyectos", "sectores_fuente", "Todos los sectores homologados con los que aparece el proyecto en la fuente (cuando son varios, 'sector' toma el más frecuente)", "texto", "Separador ';'", "", pp, D),
        ("proyectos", "programa", "Programa de inversión. No disponible en la fuente real; genérico en sintéticos", "texto", "", "Nulo en reales", "sintético", S_),
        ("proyectos", "componente_principal", "Componente del proyecto más frecuente en la fuente", "texto", "", "Nulo en sintéticos", pp, R),
        ("proyectos", "localidad", "Nombre oficial de la localidad", "texto", "", "20 localidades", "Catálogo localidades", R),
        ("proyectos", "codigo_localidad", "Código oficial de localidad (2 dígitos)", "texto", "01..20", "01..20", "Catálogo localidades", R),
        ("proyectos", "fecha_inicio", "Reales: fecha del primer CRP registrado. Sintéticos: fecha de inicio simulada", "fecha", "AAAA-MM-DD", "", f"{pp} (Fecha_Registro)", f"{D} / {S_}"),
        ("proyectos", "fecha_fin", "Reales: máx(fecha CRP + plazo). Sintéticos: fecha de fin simulada", "fecha", "AAAA-MM-DD", "", f"{pp} (Fecha_Registro, Plazo)", f"{D} / {S_}"),
        ("proyectos", "vigencia", "Vigencia de referencia: última vigencia con información (reales) / vigencia vigente al corte (sintéticos)", "entero", "AAAA", "2021-2027", f"{pp} / sintético", f"{R} / {S_}"),
        ("proyectos", "vigencias_ejecucion", "Todas las vigencias con registros del proyecto", "texto", "AAAA;AAAA", "", f"{pp} / sintético", f"{R} / {S_}"),
        ("proyectos", "estado_fuente", "Conteo de estados de propuestas en la última vigencia, tal como vienen en la fuente", "texto", "", "", pp, R),
        ("proyectos", "estado_proyecto", "Estado homologado del proyecto", "texto", "", "Finalizado; En ejecución; Programado; Suspendido; Cancelado", f"{pp} / sintético", f"{D} / {S_}"),
        ("proyectos", "porcentaje_avance", "Avance físico (%). No disponible en la fuente real (nulo); sintético en registros sintéticos", "decimal", "0-100", "0-100", "sintético", S_),
        ("proyectos", "porcentaje_propuestas_materializadas", "Indicador proxy: % de propuestas ciudadanas del proyecto en estado Materializada (todas las vigencias). NO es avance físico", "decimal", "0-100", "0-100", pp, D),
        ("proyectos", "num_propuestas_ciudadanas", "Número de propuestas ciudadanas priorizadas asociadas", "entero", "", "", pp, D),
        ("proyectos", "num_metas", "Número de metas de proyecto distintas", "entero", "", "", pp, D),
        ("proyectos", "poblacion_beneficiada_reportada", "Suma de población beneficiada reportada por propuesta (puede contener doble conteo entre propuestas)", "entero", "", "", pp, D),
        ("proyectos", "tipo_proyecto", "Tipología del proyecto (reales: clasificada desde el componente)", "texto", "", "", f"{pp} / sintético", f"{D} / {S_}"),
        ("proyectos", "fuente_dato", "Fuente del registro", "texto", "", "", "", R),
        ("proyectos", "url_fuente", "URL del recurso oficial (nulo en sintéticos)", "texto", "URL", "", "", R),
        ("proyectos", "tipo_registro", "Origen del registro", "texto", "", "REAL; SINTETICO", "", D),
        ("proyectos", "nivel_confiabilidad", "Nivel de confiabilidad", "texto", "", "Oficial verificado; Oficial parcialmente completo; Sintético", "", D),
        ("proyectos", "campos_derivados", "Campos completados o derivados en este registro", "texto", "", "", "", D),
        ("presupuesto_proyectos", "id_proyecto", "Llave a proyectos", "texto", "", "", "", D),
        ("presupuesto_proyectos", "localidad / codigo_localidad", "Localidad del registro", "texto", "", "20 localidades", "", R),
        ("presupuesto_proyectos", "vigencia", "Año fiscal", "entero", "AAAA", "2021-2027", "", f"{R} / {S_}"),
        ("presupuesto_proyectos", "alcance_presupuestal", "Qué cubre la cifra: reales = solo componente de Presupuestos Participativos; sintéticos = total del proyecto", "texto", "", "", "", D),
        ("presupuesto_proyectos", "presupuesto_inicial", "Apropiación aprobada inicialmente (COP). Nulo en reales", "decimal", "COP", ">=0", "sintético", S_),
        ("presupuesto_proyectos", "presupuesto_vigente", "Apropiación disponible tras modificaciones (COP). Nulo en reales", "decimal", "COP", ">=0", "sintético", S_),
        ("presupuesto_proyectos", "presupuesto_comprometido", "Recursos con registro presupuestal (COP). Reales: suma de Valor_CRP_Asignado_presupuestos_participativos", "decimal", "COP", "<= vigente", f"{pp} (CRP) / sintético", f"{R} / {S_}"),
        ("presupuesto_proyectos", "presupuesto_obligado", "Obligaciones reconocidas (COP). Nulo en reales", "decimal", "COP", "<= comprometido", "sintético", S_),
        ("presupuesto_proyectos", "presupuesto_pagado", "Giros / pagos realizados (COP). Nulo en reales", "decimal", "COP", "<= obligado", "sintético", S_),
        ("presupuesto_proyectos", "porcentaje_ejecucion_presupuestal", "Fórmula: presupuesto_obligado / presupuesto_vigente × 100. Nulo si falta alguno", "decimal", "0-100", "0-100", "", D),
        ("presupuesto_proyectos", "num_compromisos_crp", "Número de CRP sumados (reales)", "entero", "", "", pp, D),
        ("presupuesto_proyectos", "tipo_registro / nivel_confiabilidad / fuente_dato / url_fuente", "Trazabilidad del registro", "texto", "", "", "", D),
        ("localidades", "codigo_localidad", "Código oficial", "texto", "01..20", "", "SDP/IDECA", R),
        ("localidades", "nombre_localidad", "Nombre oficial", "texto", "", "", "SDP", R),
        ("localidades", "poblacion", "Población proyectada 2025 (suma de hombres y mujeres, todas las áreas)", "entero", "personas", "", "SDP proyecciones 2005-2035", D),
        ("localidades", "poblacion_2026", "Población proyectada 2026", "entero", "personas", "", "SDP proyecciones 2005-2035", D),
        ("localidades", "area_m2 / area_km2", "Área de la localidad (atributo LOCAREA, m²) y su conversión a km²", "decimal", "m² / km²", "", "SDP/IDECA servicio ArcGIS", f"{R} / {D}"),
        ("localidades", "acto_administrativo", "Acto que define los límites", "texto", "", "", "SDP/IDECA", R),
        ("seguimiento_proyectos", "id_proyecto", "Llave a proyectos", "texto", "", "", "", D),
        ("seguimiento_proyectos", "fecha_corte", "Cierre trimestral (o fecha del último CRP si es posterior al año de la vigencia)", "fecha", "AAAA-MM-DD", "<= 2026-09-30", "", D),
        ("seguimiento_proyectos", "vigencia", "Vigencia a la que corresponden los valores", "entero", "AAAA", "", "", D),
        ("seguimiento_proyectos", "porcentaje_avance_fisico", "Avance físico acumulado (%). Nulo en reales", "decimal", "0-100", "", "sintético", S_),
        ("seguimiento_proyectos", "presupuesto_vigente / comprometido / obligado / pagado", "Valores acumulados de la vigencia a la fecha de corte (COP). Reales: solo comprometido (CRP de PP acumulados)", "decimal", "COP", "", f"{pp} / sintético", f"{D} / {S_}"),
        ("seguimiento_proyectos", "tipo_registro / nivel_confiabilidad / nota", "Trazabilidad", "texto", "", "", "", D),
        ("inversion_educacion_localidad", "recursos_asignados / ejecutados / girados", "Inversión territorializada del sector educativo por localidad (COP), tal como la publica la SED", "decimal", "COP", "", "SED territorialización", R),
        ("inversion_educacion_localidad", "porcentaje_ejecucion", "recursos_ejecutados / recursos_asignados × 100", "decimal", "0-100", "", "", D),
    ]
    return pd.DataFrame(filas, columns=["tabla", "campo", "descripcion", "tipo_dato", "formato", "valores_permitidos", "fuente", "origen (real/sintético/derivado)"])


def inventario(log):
    U, D = "Utilizado", "Descartado"
    f = FECHA_CONSULTA
    rows = [
        ("Presupuestos Participativos Bogotá D.C. – Estado de avance propuestas priorizadas", "Secretaría Distrital de Planeación (SDP)", URL_PP_AVANCE, f,
         "Vigencia_Ejecucion, No_Localidad, Nombre_Localidad, Sector, Entidad, Codigo_Proyecto, Nombre_Proyecto, Meta, Componente, Estado_propuesta, Población beneficiada",
         log["reales_propuestas"], "2021-2025 (archivo con corte 30-09-2026)",
         "Solo cubre el componente de Presupuestos Participativos de los FDL; no trae avance físico ni presupuesto total del proyecto; estados a nivel de propuesta, no de proyecto; sectores con mayúsculas inconsistentes.", U + " (fuente principal de proyectos reales)"),
        ("Presupuestos Participativos Bogotá D.C. – Presupuesto comprometido por meta proyecto y propuestas financiadas", "Secretaría Distrital de Planeación (SDP)", URL_PP_COMP, f,
         "No_Localidad, Codigo_Proyecto, Vigencia, No_CRP, Fecha_Registro, Plazo, Valor_CRP_Asignado_presupuestos_participativos, Modalidad",
         log["reales_crp"], "2021-2025 (2025 con solo 73 CRP)",
         "Valores son CRP (compromisos) del componente PP, no apropiación ni pagos; Plazo con unidades mixtas (meses/días); 1 fecha inválida; valores en texto con formato '$ 45.000.000'.", U + " (presupuesto comprometido y seguimiento)"),
        ("Localidad. Bogotá D.C.", "SDP / IDECA (servicio ArcGIS Catastro)", URL_LOC_DATASET, f, "LOCCODIGO, LOCNOMBRE, LOCAREA, LOCAADMINI", 20, "Vigente (actualizado 2023-02-28)",
         "El GeoJSON descargable no trae atributos (properties nulas); se consultó el servicio ArcGIS REST.", U + " (área y catálogo)"),
        ("Proyecciones y retroproyecciones de población 2005-2035 por localidad", "Secretaría Distrital de Planeación (SDP)", URL_POB_DATASET, f,
         "Código Localidad, AÑO, Hombres_*, Mujeres_* (sumados)", 60, "2024-2026 extraídos (fuente 2005-2035)",
         "Archivo ODS de 1,8 MB; se agregó por localidad y año.", U + " (población)"),
        ("Territorialización de la inversión en el sector educativo por localidad", "Secretaría de Educación del Distrito (SED)", URL_SED, f,
         "COD_LOCA, R_ASIGNADOS, R_EJECUTADOS, R_GIRADOS, Fecha", 40, "2024 y 2025 (corte 31-12)",
         "Agregado por localidad (no por proyecto): no puede integrarse a la tabla de proyectos sin duplicar; se entrega como tabla complementaria.", U + " (tabla complementaria inversion_educacion_localidad.csv)"),
        ("Informe de gastos e inversiones Bogotá D.C.", "Secretaría Distrital de Hacienda (SDH)", "https://datosabiertos.bogota.gov.co/dataset/informe-de-gastos-e-inversiones-bogota", f,
         "Vigencia, Entidad, Programa de financiación, Rubro, valores mensuales acumulados", "No extraído (13.769 filas en 2024-12)", "2012-2025",
         "Nivel entidad/rubro sin localidad ni identificador de proyecto de inversión local; no permite territorializar.", D),
        ("Concepto de gastos de los Fondos de Desarrollo Local (salud)", "Secretaría Distrital de Salud (SDS)", "https://datosabiertos.bogota.gov.co/dataset/concepto-de-gastos-de-los-fondos-de-desarrollo-local", f,
         "Objeto_de_gasto, Localidad, Personas_beneficiadas, Presupuesto_asignado, Anio", "No extraído (941 filas)", "2016 en adelante",
         "Granularidad por concepto de gasto, sin código de proyecto; presupuesto en 0 en registros revisados.", D),
        ("Ranking de ejecución acumulada de PAC – Fondos de Desarrollo Local", "Secretaría Distrital de Hacienda (SDH)", "https://datosabiertos.bogota.gov.co/dataset/ranking-acumulado-vigencia-recursos-ejecutados-pac-fondos-desarrollo-local-bogota-d-c", f,
         "PAC programado/ejecutado por FDL", "No extraído", "2019-2025",
         "Información de tesorería (PAC) agregada por FDL, no por proyecto; el recurso más reciente solo contiene metadatos.", D),
        ("Obras distritales", "Secretaría General", "https://datosabiertos.bogota.gov.co/dataset/obras-distritales", f, "Frentes de obra (geoservicio)", "No extraído", "Hasta 2019",
         "Sin actualización desde 2020; solo servicios geográficos.", D),
        ("Proyectos. Bogotá D.C. (POT ruralidad)", "Secretaría Distrital de Planeación (SDP)", "https://datosabiertos.bogota.gov.co/dataset/proyectos-bogota-d-c", f, "Proyectos POT rurales", "No extraído", "2023",
         "Son proyectos de ordenamiento territorial, no proyectos de inversión con presupuesto.", D),
        ("SECOP II – Contratos Electrónicos", "Colombia Compra Eficiente (datos.gov.co)", "https://www.datos.gov.co/d/jbjy-vk9h", f,
         "nombre_entidad, valor_del_contrato, valor_pagado, fechas, objeto", "No extraído (16.965 contratos de entidades 'Fondo de Desarrollo Local')", "Continuo",
         "No contiene código de proyecto de inversión: el vínculo contrato-proyecto solo sería por texto; además el valor del contrato no equivale al presupuesto del proyecto.", D + " (posible extensión futura)"),
        ("Portal 'Datos para la Transparencia' / Mapa de Inversiones Bogotá", "Alcaldía Mayor / SDG", "https://bogota.gov.co/mi-ciudad/gobierno/accede-al-portal-datos-de-bogota-transparencia-e-investigaciones-2025", f,
         "Tableros de ejecución presupuestal de alcaldías locales", "No extraído", "-",
         "Tableros de visualización, no conjunto de datos descargable identificado en esta consulta.", D + " (referencia funcional)"),
    ]
    return pd.DataFrame(rows, columns=["nombre_conjunto", "entidad_responsable", "url", "fecha_consulta", "variables_aprovechadas",
                                       "registros_extraidos", "cobertura_temporal", "limitaciones", "decision"])


def fmt_cop(x):
    return f"${x:,.0f}".replace(",", ".")


def informe(P, PR, S, L, V, log, sed):
    r = P[P.tipo_registro == "REAL"]; s = P[P.tipo_registro == "SINTETICO"]
    md = []
    md.append("# Informe de calidad – Dataset Visor de Transparencia Territorial (Bogotá D.C.)\n")
    md.append(f"Fecha de consulta de fuentes: {FECHA_CONSULTA}. Fecha de corte del dataset: {FECHA_CORTE}. Semilla sintética: {SEED}.\n")
    md.append("> **Advertencia.** Los registros con `tipo_registro = SINTETICO` son ficticios, se generaron solo para probar el prototipo y **no representan la ejecución real de la Alcaldía de Bogotá**. "
              "Los registros REALES cubren únicamente el componente de **Presupuestos Participativos** de los Fondos de Desarrollo Local: sus cifras de comprometido no son el presupuesto total de esos proyectos ni son comparables con los totales sintéticos.\n")
    md.append("## 1. Resumen de volumen\n")
    md.append(f"| Tabla | Real | Sintético | Total |\n|---|---|---|---|")
    for nm, df in (("proyectos", P), ("presupuesto_proyectos", PR), ("seguimiento_proyectos", S)):
        a = int((df.tipo_registro == "REAL").sum()); b = int((df.tipo_registro == "SINTETICO").sum())
        md.append(f"| {nm} | {a} | {b} | {a+b} |")
    md.append(f"| localidades | {len(L)} | 0 | {len(L)} |")
    md.append(f"| inversion_educacion_localidad (complementaria) | {len(sed)} | 0 | {len(sed)} |\n")
    md.append(f"Proporción real/sintético en proyectos: {100*len(r)/len(P):.1f}% real – {100*len(s)/len(P):.1f}% sintético.\n")
    md.append("## 2. Transformaciones aplicadas\n")
    md.append("""- **Unidad de proyecto real**: combinación `localidad + Codigo_Proyecto` (los códigos de proyecto de los FDL no se repiten entre localidades: verificado, 0 códigos en más de una localidad). `id_proyecto = FDL{cod_localidad}-{codigo}`.
- **Relación entre tablas oficiales** por identificador oficial (`No_Localidad` + `Codigo_Proyecto` + `Vigencia_Ejecucion`), nunca por nombre. CRP sin propuesta asociada: %d.
- **Homologación de sectores**: unificación de mayúsculas/tildes (p. ej. "CULTURA, RECREACIÓN Y DEPORTE" y "Cultura, recreación y deporte"). Ver hoja *Homologaciones* del diccionario.
- **Homologación de estados** (fuente por propuesta → proyecto, usando la última vigencia del proyecto): Materializada→F; En ejecución/Contratada→E; En proceso de contratación/En formulación/Sin iniciar→P; Imposible ejecución (inviable)/No ejecutada→X. Regla: si hay E → *En ejecución*; si no y hay P → *Programado*; si no y hay F → *Finalizado*; si solo X → *Cancelado*, salvo que el proyecto tenga propuestas materializadas en vigencias anteriores (→ *Finalizado* con cierre parcial). La fuente no reporta *Suspendido*.
- **Valores**: texto "$ 45.000.000" → número COP. Valores inválidos: %d.
- **Fechas**: `d/m/aaaa` → ISO. Fechas inválidas en CRP: %d (excluidas de los cálculos de fecha, no del valor). CRP cuyo año de registro difiere de la vigencia: %d.
- **Plazo**: la columna mezcla unidades; valores ≤ 36 se interpretan como meses (×30,4 días) y mayores como días. `fecha_fin` real = máx(fecha CRP + plazo) → es una **estimación**.
- **Duplicados exactos** eliminados: propuestas %d, CRP %d.
- **Proyectos con más de un nombre** en la fuente: %d (se conserva el más frecuente).
- **Presupuesto real**: un registro por proyecto-vigencia; `presupuesto_comprometido` = suma de CRP de PP. Inicial, vigente, obligado y pagado quedan **nulos** (no se inventa ejecución). Proyecto-vigencias reales sin CRP: %d (comprometido nulo).
- **Seguimiento real**: comprometido acumulado a cada cierre trimestral calculado con las fechas de los CRP (derivado, sin avance físico).
- **Fórmula de ejecución**: `porcentaje_ejecucion_presupuestal = presupuesto_obligado / presupuesto_vigente × 100`.
""" % (log["crp_huerfanos"], log["crp_valor_invalido"], log["crp_fecha_invalida"], log["crp_vigencia_vs_anio_registro_distinto"],
       log["dup_propuestas"], log["dup_crp"], log["nombres_multiples_por_proyecto"], int(PR[(PR.tipo_registro=='REAL') & PR.presupuesto_comprometido.isna()].shape[0])))
    md.append("## 3. Reglas de generación sintética\n")
    md.append("""- 180 proyectos (`SIN-0001`…), mínimo 4 por localidad y el resto proporcional a √población 2025.
- 16 plantillas por sector/tipo (movilidad, espacio público, educación, salud, seguridad, ambiente, cultura, integración social, mujeres, desarrollo económico, gobierno) con rangos presupuestales log-uniformes diferenciados (p. ej. infraestructura educativa $4.000–35.000 millones; eventos $150–1.800 millones) y un factor por localidad (0,6 Candelaria – 1,4 Ciudad Bolívar), que es un **supuesto** del prototipo.
- Fechas de inicio entre 2024-03 y 2027-06; el estado se deriva de las fechas frente al corte (programado si inicia después del corte, finalizado si termina antes, en ejecución si cruza el corte) y se asignan suspensiones (~13 %) y cancelaciones (~2–4 %) aleatorias.
- Presupuesto distribuido por vigencia según días del proyecto en cada año; vigente = inicial × U(0,85;1,15); comprometido ≤ vigente, obligado ≤ comprometido, pagado ≤ obligado; vigencias futuras sin ejecución.
- Avance físico: 100 % finalizados, 0 % programados, proporcional al tiempo transcurrido en ejecución/suspendidos.
- Seguimiento trimestral acumulado por vigencia; el último corte de cada vigencia coincide con la tabla de presupuesto.
""")
    md.append("## 4. Validaciones\n")
    md.append("| Validación | Resultado | Detalle |\n|---|---|---|")
    for _, x in V.iterrows():
        md.append(f"| {x.validacion} | {x.resultado} | {x.detalle} |")
    md.append("\n## 5. Cobertura\n")
    md.append("### Proyectos por localidad\n")
    t = P.groupby(["codigo_localidad", "localidad", "tipo_registro"]).size().unstack(fill_value=0).reset_index()
    md.append("| Cód. | Localidad | Real | Sintético |\n|---|---|---|---|")
    for _, x in t.iterrows():
        md.append(f"| {x.codigo_localidad} | {x.localidad} | {x.get('REAL',0)} | {x.get('SINTETICO',0)} |")
    md.append("\n### Proyectos por estado\n")
    t = P.groupby(["estado_proyecto", "tipo_registro"]).size().unstack(fill_value=0)
    md.append("| Estado | Real | Sintético |\n|---|---|---|")
    for k, x in t.iterrows():
        md.append(f"| {k} | {x.get('REAL',0)} | {x.get('SINTETICO',0)} |")
    md.append("\n### Presupuesto por localidad (COP)\n")
    md.append("| Localidad | Comprometido PP real | Vigente sintético | Comprometido sintético | Obligado sintético |\n|---|---|---|---|---|")
    g = PR.groupby(["localidad", "tipo_registro"])[["presupuesto_vigente", "presupuesto_comprometido", "presupuesto_obligado"]].sum()
    for loc in [n for _, n in LOCALIDADES]:
        rr = g.loc[(loc, "REAL")] if (loc, "REAL") in g.index else None
        ss = g.loc[(loc, "SINTETICO")] if (loc, "SINTETICO") in g.index else None
        md.append(f"| {loc} | {fmt_cop(rr.presupuesto_comprometido) if rr is not None else '-'} | "
                  f"{fmt_cop(ss.presupuesto_vigente) if ss is not None else '-'} | {fmt_cop(ss.presupuesto_comprometido) if ss is not None else '-'} | "
                  f"{fmt_cop(ss.presupuesto_obligado) if ss is not None else '-'} |")
    md.append("\n### Presupuesto por sector (COP)\n")
    m = PR.merge(P[["id_proyecto", "sector"]], on="id_proyecto")
    g = m.groupby(["sector", "tipo_registro"])[["presupuesto_comprometido", "presupuesto_vigente"]].sum().reset_index()
    md.append("| Sector | Tipo | Vigente | Comprometido |\n|---|---|---|---|")
    for _, x in g.sort_values(["tipo_registro", "presupuesto_comprometido"], ascending=[True, False]).iterrows():
        md.append(f"| {x.sector} | {x.tipo_registro} | {fmt_cop(x.presupuesto_vigente) if x.tipo_registro=='SINTETICO' else 'n.d.'} | {fmt_cop(x.presupuesto_comprometido)} |")
    md.append("\n### Distribución por vigencia (registros de presupuesto)\n")
    t = PR.groupby(["vigencia", "tipo_registro"]).size().unstack(fill_value=0)
    md.append("| Vigencia | Real | Sintético |\n|---|---|---|")
    for k, x in t.iterrows():
        md.append(f"| {k} | {x.get('REAL',0)} | {x.get('SINTETICO',0)} |")
    md.append("\n## 6. Registros con información crítica faltante\n")
    md.append(f"- Proyectos reales sin fecha_inicio/fecha_fin (sin CRP con fecha): {int(r.fecha_inicio.isna().sum())}.")
    md.append(f"- Proyectos reales sin avance físico: {len(r)} (la fuente no lo publica).")
    md.append(f"- Proyectos reales sin programa: {len(r)} (la fuente no lo publica).")
    md.append(f"- Proyectos sin localidad: {int(P.codigo_localidad.isna().sum())}.")
    md.append("\n## 7. Validación funcional para el visor\n")
    md.append("""| # | Indicador | Cómo se construye | Disponible |
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
""")
    return "\n".join(md)


# ----------------------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--n-sinteticos", type=int, default=180)
    a = ap.parse_args()
    log = {}
    raw = loc_attrs = pob = None
    if not a.offline:
        try:
            raw, loc_attrs, pob = descargar_en_linea()
            log["modo"] = "en línea"
        except Exception as e:
            print("Descarga en línea no disponible (%s); se usa la caché ./raw" % type(e).__name__)
    if raw is None:
        raw, loc_attrs, pob = cargar_cache()
        log["modo"] = "caché local (consulta %s)" % raw.get("consultado", FECHA_CONSULTA)

    L = construir_localidades(loc_attrs, pob)
    Pr, PRr, Sr = transformar_reales(raw, log)
    Ps, PRs, Ss = generar_sinteticos(a.n_sinteticos, pob, log)
    P = pd.concat([Pr, Ps], ignore_index=True)
    PR = pd.concat([PRr, PRs], ignore_index=True)
    S = pd.concat([Sr, Ss], ignore_index=True).sort_values(["id_proyecto", "fecha_corte"]).reset_index(drop=True)
    SED = construir_sed(raw)
    V = validar(P, PR, S, L)

    orden_p = ["id_proyecto", "nombre_proyecto", "descripcion_proyecto", "entidad_responsable", "sector", "programa",
               "localidad", "codigo_localidad", "fecha_inicio", "fecha_fin", "vigencia", "estado_proyecto",
               "porcentaje_avance", "tipo_proyecto", "fuente_dato", "url_fuente", "tipo_registro", "nivel_confiabilidad",
               "codigo_proyecto_oficial", "sectores_fuente", "entidad_sector_rector", "componente_principal", "vigencias_ejecucion",
               "estado_fuente", "porcentaje_propuestas_materializadas", "num_propuestas_ciudadanas", "num_metas",
               "poblacion_beneficiada_reportada", "campos_derivados"]
    P = P[orden_p]
    orden_b = ["id_proyecto", "localidad", "codigo_localidad", "vigencia", "presupuesto_inicial", "presupuesto_vigente",
               "presupuesto_comprometido", "presupuesto_obligado", "presupuesto_pagado",
               "porcentaje_ejecucion_presupuestal", "tipo_registro", "fuente_dato", "nivel_confiabilidad",
               "alcance_presupuestal", "num_compromisos_crp", "url_fuente"]
    PR = PR[orden_b]
    for df, name in ((P, "proyectos.csv"), (PR, "presupuesto_proyectos.csv"), (L, "localidades.csv"),
                     (S, "seguimiento_proyectos.csv"), (SED, "inversion_educacion_localidad.csv")):
        df.to_csv(os.path.join(OUT, name), index=False, encoding="utf-8-sig")

    # Excel de documentación
    hom_s = pd.DataFrame(sorted(SECTOR_HOMOLOGADO.items()), columns=["valor_fuente (mayúsculas)", "sector_homologado"])
    hom_e = pd.DataFrame([(k, v, {"F": "Finalizado", "E": "En ejecución", "P": "Programado", "X": "Cancelado"}[v])
                          for k, v in ESTADO_PROPUESTA.items()], columns=["estado_propuesta_fuente", "categoria", "estado_proyecto (si es la categoría dominante)"])
    with pd.ExcelWriter(os.path.join(OUT, "diccionario_datos.xlsx"), engine="openpyxl") as w:
        diccionario().to_excel(w, "Diccionario", index=False)
        hom_s.to_excel(w, "Homologaciones", index=False, startrow=0)
        hom_e.to_excel(w, "Homologaciones", index=False, startrow=len(hom_s) + 3)
    with pd.ExcelWriter(os.path.join(OUT, "inventario_fuentes.xlsx"), engine="openpyxl") as w:
        inventario(log).to_excel(w, "Inventario", index=False)
    for fn in ("diccionario_datos.xlsx", "inventario_fuentes.xlsx"):
        formatear_xlsx(os.path.join(OUT, fn))
    open(os.path.join(OUT, "informe_calidad.md"), "w", encoding="utf-8").write(informe(P, PR, S, L, V, log, SED))
    print(json.dumps({"modo": log["modo"], "proyectos": len(P), "reales": int((P.tipo_registro == 'REAL').sum()),
                      "sinteticos": int((P.tipo_registro == 'SINTETICO').sum()), "presupuesto": len(PR),
                      "seguimiento": len(S), "validaciones_revisar": V[V.resultado != "OK"].validacion.tolist()},
                     ensure_ascii=False, indent=1))


def formatear_xlsx(path):
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = load_workbook(path)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                c.font = Font(name="Arial", size=10, bold=c.font.bold)
                c.alignment = Alignment(wrap_text=True, vertical="top")
        for c in ws[1]:
            c.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F4E79")
        for col in ws.columns:
            L_ = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(60, max(12, L_ * 0.9))
        ws.freeze_panes = "A2"
    wb.save(path)


if __name__ == "__main__":
    main()
