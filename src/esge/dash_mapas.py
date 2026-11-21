"""Dashboard interactivo de Streamlit para el monitoreo de PQRS y Proyectos de Inversión en Bogotá por Localidades."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import folium
from folium.features import DivIcon
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.express as px
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Image as RLImage, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
import streamlit as st
import streamlit.components.v1 as components

# -----------------------------------------------------------------------------
# Configuración inicial de la página
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Dashboard Bogotá — PQRS y Proyectos de Inversión",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Estilos CSS personalizados para mejorar el diseño del dashboard
st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.1rem;
        font-weight: 800;
        color: #1E293B;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.0rem;
        color: #64748B;
        margin-bottom: 1.2rem;
    }
    .stMetric {
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 10px 14px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.03);
    }
    .card-container {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        margin-bottom: 20px;
    }
    .project-card {
        background-color: #F8FAFC;
        border-left: 4px solid #2563EB;
        border-radius: 6px;
        padding: 12px 16px;
        margin-bottom: 10px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Metadatos y Coordenadas Urbanas de las 20 Localidades de Bogotá
# -----------------------------------------------------------------------------
LOCALIDADES_BOGOTA = {
    "01": {"nombre": "Usaquén", "lat": 4.7300, "lon": -74.0300},
    "02": {"nombre": "Chapinero", "lat": 4.6465, "lon": -74.0600},
    "03": {"nombre": "Santa Fe", "lat": 4.6108451, "lon": -74.0682581},
    "04": {"nombre": "San Cristóbal", "lat": 4.5600, "lon": -74.0850},
    "05": {"nombre": "Usme", "lat": 4.4700, "lon": -74.1200},
    "06": {"nombre": "Tunjuelito", "lat": 4.5750, "lon": -74.1350},
    "07": {"nombre": "Bosa", "lat": 4.6050, "lon": -74.1900},
    "08": {"nombre": "Kennedy", "lat": 4.6300, "lon": -74.1500},
    "09": {"nombre": "Fontibón", "lat": 4.6750, "lon": -74.1400},
    "10": {"nombre": "Engativá", "lat": 4.7000, "lon": -74.1150},
    "11": {"nombre": "Suba", "lat": 4.7450, "lon": -74.0850},
    "12": {"nombre": "Barrios Unidos", "lat": 4.6680, "lon": -74.0750},
    "13": {"nombre": "Teusaquillo", "lat": 4.6400, "lon": -74.0850},
    "14": {"nombre": "Los Mártires", "lat": 4.6050, "lon": -74.0900},
    "15": {"nombre": "Antonio Nariño", "lat": 4.5880, "lon": -74.1000},
    "16": {"nombre": "Puente Aranda", "lat": 4.6180, "lon": -74.1150},
    "17": {"nombre": "La Candelaria", "lat": 4.5917, "lon": -74.0741},
    "18": {"nombre": "Rafael Uribe Uribe", "lat": 4.5650, "lon": -74.1100},
    "19": {"nombre": "Ciudad Bolívar", "lat": 4.5200, "lon": -74.1600},
    "20": {"nombre": "Sumapaz", "lat": 4.0267, "lon": -74.2450},
}

NOMBRE_TO_CODIGO = {info["nombre"]: cod for cod, info in LOCALIDADES_BOGOTA.items()}

# Homologación de nombres en el CSV de PQRS hacia nombres limpios oficiales
SDG_NAME_MAPPING = {
    "ALCALDIA LOCAL DE USAQUEN": "Usaquén",
    "ALCALDIA LOCAL DE CHAPINERO": "Chapinero",
    "ALCALDIA LOCAL DE SANTAFE": "Santa Fe",
    "ALCALDIA LOCAL DE SAN CRISTOBAL": "San Cristóbal",
    "ALCALDIA LOCAL DE USME": "Usme",
    "ALCALDIA LOCAL DE TUNJUELITO": "Tunjuelito",
    "ALCALDIA LOCAL DE BOSA": "Bosa",
    "ALCALDIA LOCAL DE KENNEDY": "Kennedy",
    "ALCALDIA LOCAL DE FONTIBON": "Fontibón",
    "ALCALDIA LOCAL DE ENGATIVA": "Engativá",
    "ALCALDIA LOCAL DE SUBA": "Suba",
    "ALCALDIA LOCAL DE BARRIOS UNIDOS": "Barrios Unidos",
    "ALCALDIA LOCAL DE TEUSAQUILLO": "Teusaquillo",
    "ALCALDIA LOCAL DE MARTIRES": "Los Mártires",
    "ALCALDIA LOCAL DE ANTONIO NARINO": "Antonio Nariño",
    "ALCALDIA LOCAL DE PUENTE ARANDA": "Puente Aranda",
    "ALCALDIA LOCAL DE CANDELARIA": "La Candelaria",
    "ALCALDIA LOCAL DE RAFAEL URIBE URIBE": "Rafael Uribe Uribe",
    "ALCALDIA LOCAL DE CIUDAD BOLIVAR": "Ciudad Bolívar",
    "ALCALDIA LOCAL DE SUMAPAZ": "Sumapaz",
}


# -----------------------------------------------------------------------------
# Carga de GeoJSON de Localidades
# -----------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_geojson_data() -> dict | None:
    """Carga el GeoJSON optimizado con los polígonos de las localidades de Bogotá."""
    geojson_path = Path(__file__).parent / "data" / "localidades_bogota.geojson"
    if geojson_path.exists():
        with open(geojson_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


# -----------------------------------------------------------------------------
# Carga y Procesamiento de Datos Reales de PQRS (SDG 2022-2026)
# -----------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_real_pqrs_raw() -> pd.DataFrame:
    """Carga el archivo CSV completo de PQRS de la Secretaría Distrital de Gobierno."""
    csv_path = Path(__file__).parent / "data" / "pqrs_sdg_2022_2026.csv"
    if not csv_path.exists():
        return pd.DataFrame()

    df = pd.read_csv(csv_path, sep=";", encoding="utf-8", low_memory=False)

    # Mapear nombres de localidad a los nombres limpios oficiales
    df["localidad"] = df["NOMBRE_LOCALIDAD"].map(SDG_NAME_MAPPING)

    # Filtrar solo registros asociados a una de las 20 localidades
    df_loc = df[df["localidad"].notna()].copy()

    # Clasificar el estado en Resueltas, En Trámite o Pendientes
    def categorizar_estado(row):
        if row["ESTADO_ORFEO"] == "TRAMITE CERRADO":
            return "Resueltas"
        elif pd.notna(row["FECHA_RESPUESTA"]):
            return "En Trámite"
        else:
            return "Pendientes"

    df_loc["estado_unificado"] = df_loc.apply(categorizar_estado, axis=1)

    # Homologar tipo de petición simplificado
    def simplificar_tipo(tipo):
        t = str(tipo).upper()
        if "INTERES PARTICULAR" in t:
            return "Petición Particular"
        elif "INTERES GENERAL" in t:
            return "Petición General"
        elif "INFORMACION" in t or "CONSULTA" in t:
            return "Información y Consulta"
        else:
            return "Otras Solicitudes"

    df_loc["tipo_simplificado"] = df_loc["TIPO_PETICION"].apply(simplificar_tipo)
    df_loc["vigencia_str"] = df_loc["VIGENCIA"].fillna(0).astype(int).astype(str)

    return df_loc


def get_pqrs_locality_summary(df_pqrs: pd.DataFrame, vigencia_filtro: str = "Todas") -> pd.DataFrame:
    """Consolida las métricas reales de PQRS por localidad para el mapa y las tarjetas."""
    if df_pqrs.empty:
        return pd.DataFrame()

    # Filtrar por vigencia si aplica
    if vigencia_filtro != "Todas":
        df_f = df_pqrs[df_pqrs["vigencia_str"] == vigencia_filtro].copy()
    else:
        df_f = df_pqrs.copy()

    # Inicializar filas para las 20 localidades garantizadas
    rows = []
    for cod, info in LOCALIDADES_BOGOTA.items():
        loc_name = info["nombre"]
        sub = df_f[df_f["localidad"] == loc_name]

        total_pqrs = len(sub)
        resueltas = int((sub["estado_unificado"] == "Resueltas").sum())
        en_tramite = int((sub["estado_unificado"] == "En Trámite").sum())
        pendientes = int((sub["estado_unificado"] == "Pendientes").sum())

        p_particular = int((sub["tipo_simplificado"] == "Petición Particular").sum())
        p_general = int((sub["tipo_simplificado"] == "Petición General").sum())
        p_info = int((sub["tipo_simplificado"] == "Información y Consulta").sum())
        p_otras = int((sub["tipo_simplificado"] == "Otras Solicitudes").sum())

        rows.append(
            {
                "codigo": cod,
                "localidad": loc_name,
                "lat": info["lat"],
                "lon": info["lon"],
                "total_pqrs": total_pqrs,
                "resueltas": resueltas,
                "en_gestion": en_tramite,
                "pendientes": pendientes,
                "peticiones_particular": p_particular,
                "peticiones_general": p_general,
                "informacion_consultas": p_info,
                "otras_solicitudes": p_otras,
            }
        )

    return pd.DataFrame(rows)


# -----------------------------------------------------------------------------
# Carga y Procesamiento de Datos de Proyectos de Inversión
# -----------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_real_projects_data() -> pd.DataFrame:
    """Carga y cruza la información de proyectos y presupuestos por localidad."""
    proj_path = Path(__file__).parent / "data" / "proyectos.csv"
    pres_path = Path(__file__).parent / "data" / "presupuesto_proyectos.csv"

    if not proj_path.exists() or not pres_path.exists():
        return pd.DataFrame()

    df_p = pd.read_csv(proj_path)
    df_b = pd.read_csv(pres_path)

    # Agregar presupuesto comprometido por proyecto
    b_agg = (
        df_b.groupby("id_proyecto")
        .agg(
            {
                "presupuesto_comprometido": "sum",
                "presupuesto_vigente": "max",
                "presupuesto_pagado": "sum",
                "porcentaje_ejecucion_presupuestal": "mean",
            }
        )
        .reset_index()
    )

    merged = df_p.merge(b_agg, on="id_proyecto", how="left")
    merged["presupuesto_comprometido"] = merged["presupuesto_comprometido"].fillna(0)
    merged["presupuesto_millones"] = merged["presupuesto_comprometido"] / 1_000_000.0

    # Normalizar sector y estado
    merged["sector"] = merged["sector"].fillna("General / Sin sector").str.strip()
    merged["estado_proyecto"] = merged["estado_proyecto"].fillna("Sin especificar").str.strip()

    return merged


def get_top_projects_by_locality(df_projects: pd.DataFrame, localidad: str, top_n: int = 5) -> pd.DataFrame:
    """Obtiene los top N proyectos con mayor presupuesto comprometido en una localidad."""
    if df_projects.empty:
        return pd.DataFrame()

    sub = df_projects[df_projects["localidad"] == localidad].copy()
    if sub.empty:
        return pd.DataFrame()

    # Ordenar por presupuesto comprometido descendente
    sorted_df = sub.sort_values(by="presupuesto_comprometido", ascending=False).head(top_n)
    return sorted_df.reset_index(drop=True)


# -----------------------------------------------------------------------------
# Generación de Gráfico SVG de Torta para Popups de Folium
# -----------------------------------------------------------------------------
def generate_svg_donut(resueltas: int, en_gestion: int, pendientes: int) -> str:
    """Genera un gráfico de dona/torta vectorial SVG directamente en HTML para la tarjeta popup."""
    total = resueltas + en_gestion + pendientes
    if total == 0:
        return ""

    p_res = (resueltas / total) * 100
    p_ges = (en_gestion / total) * 100
    p_pen = (pendientes / total) * 100

    off_ges = -p_res
    off_pen = -(p_res + p_ges)

    svg = f"""
    <svg viewBox="0 0 42 42" style="width: 105px; height: 105px; transform: rotate(-90deg); margin: 6px auto; display: block;">
      <circle cx="21" cy="21" r="15.9155" fill="none" stroke="#E2E8F0" stroke-width="5.5"></circle>
      <circle cx="21" cy="21" r="15.9155" fill="none" stroke="#10B981" stroke-width="5.5"
              stroke-dasharray="{p_res:.1f} {100 - p_res:.1f}" stroke-dashoffset="0"></circle>
      <circle cx="21" cy="21" r="15.9155" fill="none" stroke="#F59E0B" stroke-width="5.5"
              stroke-dasharray="{p_ges:.1f} {100 - p_ges:.1f}" stroke-dashoffset="{off_ges:.1f}"></circle>
      <circle cx="21" cy="21" r="15.9155" fill="none" stroke="#EF4444" stroke-width="5.5"
              stroke-dasharray="{p_pen:.1f} {100 - p_pen:.1f}" stroke-dashoffset="{off_pen:.1f}"></circle>
    </svg>
    """
    return svg


# -----------------------------------------------------------------------------
# Funciones de Exportación: Generar PDF e Imagen PNG con Top Proyectos
# -----------------------------------------------------------------------------
def generate_locality_card_png(row: pd.Series, top_projects: pd.DataFrame) -> bytes:
    """Genera una imagen PNG de alta resolución con el estado de PQRS y el Top de Proyectos de la localidad."""
    fig = plt.figure(figsize=(10.5, 7.0), dpi=180, facecolor="#F8FAFC")
    fig.suptitle(
        f"FICHA TERRITORIAL — LOCALIDAD DE {row['localidad'].upper()}",
        fontsize=15,
        fontweight="bold",
        color="#0F172A",
        y=0.96,
    )

    plt.figtext(
        0.5,
        0.91,
        f"Alcaldía Mayor de Bogotá D.C. | Código: {row['codigo']} | Total PQRS Registradas: {row['total_pqrs']:,}",
        ha="center",
        fontsize=9.5,
        color="#64748B",
        weight="bold",
    )

    # Subplot 1: Gráfico de Torta de PQRS
    ax1 = fig.add_subplot(221)
    labels = ["Resueltas", "En Trámite", "Pendientes"]
    sizes = [row["resueltas"], row["en_gestion"], row["pendientes"]]
    colors_list = ["#10B981", "#F59E0B", "#EF4444"]
    explode = (0.04, 0.04, 0.04)

    wedges, texts, autotexts = ax1.pie(
        sizes,
        labels=labels,
        autopct="%1.1f%%",
        startangle=140,
        colors=colors_list,
        explode=explode,
        textprops=dict(color="#1E293B", weight="bold", fontsize=8.5),
        pctdistance=0.72,
    )
    for at in autotexts:
        at.set_color("white")
        at.set_weight("bold")
        at.set_fontsize(9)

    ax1.set_title("Estado de Atención de PQRS", fontsize=10.5, fontweight="bold", color="#1E293B", pad=6)

    # Subplot 2: Tabla Resumen de PQRS
    ax2 = fig.add_subplot(222)
    ax2.axis("off")

    t_pqrs = row["total_pqrs"] if row["total_pqrs"] > 0 else 1
    table_data_pqrs = [
        ["Categoría de Atención Ciudadana", "Casos", "% Total"],
        ["Peticiones de Interés Particular", f"{row['peticiones_particular']:,}", f"{(row['peticiones_particular']/t_pqrs)*100:.1f}%"],
        ["Peticiones de Interés General", f"{row['peticiones_general']:,}", f"{(row['peticiones_general']/t_pqrs)*100:.1f}%"],
        ["Solicitud de Información y Consultas", f"{row['informacion_consultas']:,}", f"{(row['informacion_consultas']/t_pqrs)*100:.1f}%"],
        ["Otras Solicitudes", f"{row['otras_solicitudes']:,}", f"{(row['otras_solicitudes']/t_pqrs)*100:.1f}%"],
        ["--- ESTADO DE CASOS ---", "---", "---"],
        ["Resueltas (Trámite cerrado)", f"{row['resueltas']:,}", f"{(row['resueltas']/t_pqrs)*100:.1f}%"],
        ["En Trámite (En gestión activa)", f"{row['en_gestion']:,}", f"{(row['en_gestion']/t_pqrs)*100:.1f}%"],
        ["Pendientes (Sin respuesta)", f"{row['pendientes']:,}", f"{(row['pendientes']/t_pqrs)*100:.1f}%"],
    ]

    t1 = ax2.table(cellText=table_data_pqrs, loc="center", cellLoc="left")
    t1.scale(1.05, 1.25)
    t1.auto_set_font_size(False)
    t1.set_fontsize(7.8)

    for (r, c), cell in t1.get_celld().items():
        if r == 0:
            cell.set_facecolor("#1E293B")
            cell.get_text().set_color("white")
            cell.get_text().set_weight("bold")
        elif r == 5:
            cell.set_facecolor("#E2E8F0")
            cell.get_text().set_weight("bold")
        else:
            cell.set_facecolor("#FFFFFF" if r % 2 == 0 else "#F1F5F9")

    # Subplot 3: Tabla con Top 5 Proyectos con Mayor Inversión
    ax3 = fig.add_subplot(212)
    ax3.axis("off")

    table_data_proj = [["#", "Top Proyectos con Mayor Inversión en la Localidad", "Sector", "Estado", "Inversión Comprometida"]]
    if not top_projects.empty:
        for idx, p_row in top_projects.head(5).iterrows():
            nom = (p_row["nombre_proyecto"][:65] + "...") if len(p_row["nombre_proyecto"]) > 65 else p_row["nombre_proyecto"]
            sec = (p_row["sector"][:22] + "...") if len(p_row["sector"]) > 22 else p_row["sector"]
            inv = f"$ {p_row['presupuesto_millones']:,.1f} M" if p_row["presupuesto_millones"] > 0 else "Sin asignar"
            table_data_proj.append([str(idx + 1), nom, sec, p_row["estado_proyecto"], inv])
    else:
        table_data_proj.append(["-", "No hay proyectos reportados en esta localidad", "-", "-", "-"])

    t2 = ax3.table(cellText=table_data_proj, loc="center", cellLoc="left")
    t2.scale(1.05, 1.35)
    t2.auto_set_font_size(False)
    t2.set_fontsize(8.0)

    for (r, c), cell in t2.get_celld().items():
        if r == 0:
            cell.set_facecolor("#1E293B")
            cell.get_text().set_color("white")
            cell.get_text().set_weight("bold")
        else:
            cell.set_facecolor("#FFFFFF" if r % 2 == 0 else "#F1F5F9")

    plt.tight_layout(rect=[0, 0, 1, 0.90])

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def generate_locality_card_pdf(row: pd.Series, top_projects: pd.DataFrame) -> bytes:
    """Genera un reporte PDF formal de la localidad con gráfico de torta y Top 5 de proyectos."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontSize=15,
        textColor=colors.HexColor("#1E293B"),
        spaceAfter=3,
        alignment=1,
    )

    subtitle_style = ParagraphStyle(
        "DocSubTitle",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#64748B"),
        spaceAfter=12,
        alignment=1,
    )

    section_style = ParagraphStyle(
        "SectionHeader",
        parent=styles["Heading2"],
        fontSize=11,
        textColor=colors.HexColor("#1E293B"),
        spaceBefore=10,
        spaceAfter=6,
    )

    story = []
    story.append(
        Paragraph(
            f"<b>FICHA TERRITORIAL: LOCALIDAD DE {row['localidad'].upper()}</b>",
            title_style,
        )
    )
    story.append(
        Paragraph(
            f"Alcaldía Mayor de Bogotá D.C. | Código Localidad: {row['codigo']} | Total PQRS: {row['total_pqrs']:,}",
            subtitle_style,
        )
    )

    # 1. Gráfico de Torta de PQRS para el PDF
    fig, ax = plt.subplots(figsize=(4.0, 3.0), dpi=160)
    labels = ["Resueltas", "En Trámite", "Pendientes"]
    sizes = [row["resueltas"], row["en_gestion"], row["pendientes"]]
    colors_list = ["#10B981", "#F59E0B", "#EF4444"]

    ax.pie(
        sizes,
        labels=labels,
        autopct="%1.1f%%",
        startangle=140,
        colors=colors_list,
        explode=(0.04, 0.04, 0.04),
        textprops=dict(color="#1E293B", weight="bold", fontsize=8.0),
        pctdistance=0.72,
    )
    ax.set_title("Estado de PQRS", fontsize=9.5, fontweight="bold", color="#1E293B")
    plt.tight_layout()

    img_buf = io.BytesIO()
    plt.savefig(img_buf, format="png", dpi=160, bbox_inches="tight", transparent=True)
    plt.close(fig)
    img_buf.seek(0)
    rl_img = RLImage(img_buf, width=220, height=165)

    t_pqrs = row["total_pqrs"] if row["total_pqrs"] > 0 else 1
    table_data_pqrs = [
        ["Categoría / Métrica", "Casos", "% Total"],
        ["Peticiones de Interés Particular", str(row["peticiones_particular"]), f"{(row['peticiones_particular']/t_pqrs)*100:.1f}%"],
        ["Peticiones de Interés General", str(row["peticiones_general"]), f"{(row['peticiones_general']/t_pqrs)*100:.1f}%"],
        ["Información y Consultas", str(row["informacion_consultas"]), f"{(row['informacion_consultas']/t_pqrs)*100:.1f}%"],
        ["--- ESTADO DE ATENCIÓN ---", "---", "---"],
        ["Resueltas", str(row["resueltas"]), f"{(row['resueltas']/t_pqrs)*100:.1f}%"],
        ["En Trámite", str(row["en_gestion"]), f"{(row['en_gestion']/t_pqrs)*100:.1f}%"],
        ["Pendientes", str(row["pendientes"]), f"{(row['pendientes']/t_pqrs)*100:.1f}%"],
        ["TOTAL PQRS", str(row["total_pqrs"]), "100.0%"],
    ]

    t_pqrs_table = Table(table_data_pqrs, colWidths=[175, 55, 65])
    t_pqrs_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.0),
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F8FAFC")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("BACKGROUND", (0, 4), (-1, 4), colors.HexColor("#E2E8F0")),
            ("FONTNAME", (0, 4), (-1, 4), "Helvetica-Bold"),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#1E293B")),
            ("TEXTCOLOR", (0, -1), (-1, -1), colors.whitesmoke),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ])
    )

    pqrs_layout = Table([[rl_img, t_pqrs_table]], colWidths=[235, 305])
    pqrs_layout.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    story.append(pqrs_layout)
    story.append(Spacer(1, 10))

    # 2. Sección Top Proyectos de Inversión
    story.append(Paragraph("<b>Top Proyectos de Inversión en la Localidad</b>", section_style))

    table_data_proj = [["#", "Proyecto de Inversión Destacado", "Sector", "Estado", "Inversión COP"]]
    if not top_projects.empty:
        for idx, p_row in top_projects.head(5).iterrows():
            nom = (p_row["nombre_proyecto"][:58] + "...") if len(p_row["nombre_proyecto"]) > 58 else p_row["nombre_proyecto"]
            sec = (p_row["sector"][:20] + "...") if len(p_row["sector"]) > 20 else p_row["sector"]
            inv = f"$ {p_row['presupuesto_millones']:,.1f} M" if p_row["presupuesto_millones"] > 0 else "Sin asignar"
            table_data_proj.append([str(idx + 1), nom, sec, p_row["estado_proyecto"], inv])
    else:
        table_data_proj.append(["-", "No hay proyectos reportados en esta localidad", "-", "-", "-"])

    t_proj_table = Table(table_data_proj, colWidths=[20, 240, 105, 85, 90])
    t_proj_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F8FAFC")),
        ])
    )
    story.append(t_proj_table)

    doc.build(story)
    return buf.getvalue()


# -----------------------------------------------------------------------------
# Cálculo de estilos dinámicos de las bolitas
# -----------------------------------------------------------------------------
def get_bubble_style(count: int, min_val: int, max_val: int, scale_factor: float = 1.0):
    """Calcula el tamaño (diámetro) y color de la bolita según el número de PQRS."""
    norm = 0.0 if max_val == min_val else (count - min_val) / (max_val - min_val)

    min_size = 28 * scale_factor
    max_size = 66 * scale_factor
    size = int(min_size + (norm * (max_size - min_size)))

    font_size = max(11, int(size * 0.36))

    if norm < 0.25:
        bg_color = "linear-gradient(135deg, #10B981 0%, #059669 100%)"
        border_color = "#047857"
    elif norm < 0.55:
        bg_color = "linear-gradient(135deg, #F59E0B 0%, #D97706 100%)"
        border_color = "#B45309"
    elif norm < 0.80:
        bg_color = "linear-gradient(135deg, #F97316 0%, #EA580C 100%)"
        border_color = "#C2410C"
    else:
        bg_color = "linear-gradient(135deg, #EF4444 0%, #DC2626 100%)"
        border_color = "#991B1B"

    return size, font_size, bg_color, border_color


# -----------------------------------------------------------------------------
# Generación en Caché de Fichas PDF para las Tarjetas del Mapa
# -----------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def get_cached_locality_pdfs(df_summary: pd.DataFrame, df_projects: pd.DataFrame) -> dict[str, str]:
    """Genera y almacena en caché las fichas PDF en Base64 para el botón de descarga en las tarjetas emergentes."""
    pdf_dict = {}
    for _, row in df_summary.iterrows():
        top_p = get_top_projects_by_locality(df_projects, row["localidad"], top_n=5)
        pdf_bytes = generate_locality_card_pdf(row, top_p)
        pdf_dict[row["localidad"]] = base64.b64encode(pdf_bytes).decode("utf-8")
    return pdf_dict


# -----------------------------------------------------------------------------
# Construcción del Mapa de Folium
# -----------------------------------------------------------------------------
def build_map(
    df_summary: pd.DataFrame,
    df_projects: pd.DataFrame,
    geojson_data: dict | None,
    metric_col: str,
    tiles_choice: str,
    scale_factor: float,
    show_boundaries: bool,
    pdf_dict: dict[str, str] | None = None,
) -> folium.Map:
    """Genera el mapa interactivo de Bogotá con las localidades, gráfico de torta y Top 3 proyectos en popup."""
    bogota_center = [4.6550, -74.0950]
    initial_zoom = 11

    tile_configs = {
        "OpenStreetMap (Estándar)": {
            "tiles": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            "attr": "&copy; OpenStreetMap contributors",
        },
        "CartoDB Positron (Limpio)": {
            "tiles": "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
            "attr": "&copy; CARTO",
        },
        "CartoDB Dark (Oscuro)": {
            "tiles": "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
            "attr": "&copy; CARTO",
        },
    }

    selected_tile = tile_configs.get(tiles_choice, tile_configs["OpenStreetMap (Estándar)"])

    m = folium.Map(
        location=bogota_center,
        zoom_start=initial_zoom,
        tiles=None,
        control_scale=True,
    )

    folium.TileLayer(
        tiles=selected_tile["tiles"],
        attr=selected_tile["attr"],
        name=tiles_choice,
        max_zoom=19,
    ).add_to(m)

    m.get_root().header.add_child(
        folium.Element(
            """
            <style>
            .custom-bubble-wrapper {
                background: transparent !important;
                border: none !important;
            }
            .leaflet-container {
                width: 100% !important;
                height: 100% !important;
            }
            </style>
            """
        )
    )

    if show_boundaries and geojson_data:
        def style_function(feature):
            return {
                "fillColor": "#3B82F6",
                "color": "#1E3A8A",
                "weight": 1.6,
                "fillOpacity": 0.08,
                "dashArray": "2, 4",
            }

        def highlight_function(feature):
            return {
                "fillColor": "#2563EB",
                "color": "#1D4ED8",
                "weight": 3,
                "fillOpacity": 0.20,
                "dashArray": "none",
            }

        folium.GeoJson(
            geojson_data,
            name="Límites de Localidades",
            style_function=style_function,
            highlight_function=highlight_function,
            tooltip=folium.GeoJsonTooltip(
                fields=["nombre", "codigo"],
                aliases=["Localidad:", "Código:"],
                style="background-color: #FFFFFF; color: #1E293B; font-weight: 600; border-radius: 6px; padding: 6px;",
            ),
        ).add_to(m)

    min_val = int(df_summary[metric_col].min()) if not df_summary.empty else 0
    max_val = int(df_summary[metric_col].max()) if not df_summary.empty else 100

    for _, row in df_summary.iterrows():
        count = int(row[metric_col])
        size, font_size, bg_color, border_color = get_bubble_style(
            count, min_val, max_val, scale_factor
        )

        svg_donut = generate_svg_donut(
            row["resueltas"], row["en_gestion"], row["pendientes"]
        )

        total_loc = row["total_pqrs"]
        p_res = (row["resueltas"] / total_loc) * 100 if total_loc > 0 else 0
        p_ges = (row["en_gestion"] / total_loc) * 100 if total_loc > 0 else 0
        p_pen = (row["pendientes"] / total_loc) * 100 if total_loc > 0 else 0

        # Obtener Top 3 proyectos para mostrar en el popup
        top3_proj = get_top_projects_by_locality(df_projects, row["localidad"], top_n=3)
        proj_items_html = ""
        if not top3_proj.empty:
            for _, pr in top3_proj.iterrows():
                inv_text = f"${pr['presupuesto_millones']:,.0f}M" if pr["presupuesto_millones"] > 0 else "Sin asignar"
                p_nom = (pr["nombre_proyecto"][:35] + "...") if len(pr["nombre_proyecto"]) > 35 else pr["nombre_proyecto"]
                proj_items_html += f"""
                <div style="margin-bottom: 3px; font-size: 11px; line-height: 1.2;">
                    <b>• {p_nom}</b><br/>
                    <span style="color: #64748B;">{pr['sector']} | {pr['estado_proyecto']} | <b>{inv_text}</b></span>
                </div>
                """
        else:
            proj_items_html = "<div style='font-size: 11px; color: #64748B;'>Sin proyectos reportados</div>"

        # Preparar botón de descarga PDF si está disponible en pdf_dict
        pdf_b64 = pdf_dict.get(row["localidad"], "") if pdf_dict else ""
        if pdf_b64:
            pdf_btn_html = f"""
            <div style="margin-top: 8px;">
                <a href="data:application/pdf;base64,{pdf_b64}" download="Ficha_Territorial_{row['localidad']}.pdf" target="_blank"
                   style="display: flex; align-items: center; justify-content: center; gap: 6px; width: 100%; box-sizing: border-box; background-color: #1E293B; color: #FFFFFF; padding: 7px 10px; border-radius: 6px; text-decoration: none; font-size: 11.5px; font-weight: 700; box-shadow: 0 2px 4px rgba(0,0,0,0.2); cursor: pointer; text-align: center;">
                    📄 Descargar Ficha en PDF
                </a>
            </div>
            """
        else:
            pdf_btn_html = ""

        bubble_html = f"""
        <div style="
            display: flex;
            align-items: center;
            justify-content: center;
            width: {size}px;
            height: {size}px;
            border-radius: 50%;
            background: {bg_color};
            color: #FFFFFF;
            font-weight: 800;
            font-size: {font_size}px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            border: 2px solid #FFFFFF;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.40);
            text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
            cursor: pointer;
            user-select: none;
        ">
            {count:,}
        </div>
        """

        popup_content = f"""
        <div style="font-family: system-ui, sans-serif; width: 250px; color: #0F172A; padding: 2px;">
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #E2E8F0; padding-bottom: 5px; margin-bottom: 6px;">
                <h4 style="margin: 0; color: #1E293B; font-size: 15px; font-weight: 700;">
                    📍 {row['localidad']}
                </h4>
                <span style="background-color: #1E293B; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 600;">
                    Total: {row['total_pqrs']:,}
                </span>
            </div>

            <div style="text-align: center; margin-bottom: 4px;">
                <b style="font-size: 11.5px; color: #475569;">Distribución de PQRS:</b>
                {svg_donut}
            </div>

            <div style="background-color: #F8FAFC; padding: 5px 8px; border-radius: 6px; font-size: 11px; margin-bottom: 6px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
                    <span><span style="color: #10B981;">●</span> Resueltas:</span>
                    <b>{row['resueltas']:,} ({p_res:.1f}%)</b>
                </div>
                <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
                    <span><span style="color: #F59E0B;">●</span> En Trámite:</span>
                    <b>{row['en_gestion']:,} ({p_ges:.1f}%)</b>
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span><span style="color: #EF4444;">●</span> Pendientes:</span>
                    <b>{row['pendientes']:,} ({p_pen:.1f}%)</b>
                </div>
            </div>

            <!-- Resumen Top Proyectos Locales -->
            <div style="border-top: 1px dashed #CBD5E1; padding-top: 5px; margin-bottom: 6px;">
                <b style="font-size: 11.5px; color: #1E293B;">🏗️ Top Proyectos en la Localidad:</b>
                <div style="margin-top: 4px;">
                    {proj_items_html}
                </div>
            </div>

            {pdf_btn_html}
        </div>
        """

        folium.Marker(
            location=[row["lat"], row["lon"]],
            icon=DivIcon(
                icon_size=(size, size),
                icon_anchor=(size // 2, size // 2),
                class_name="custom-bubble-wrapper",
                html=bubble_html,
            ),
            popup=folium.Popup(popup_content, max_width=310),
            tooltip=f"{row['localidad']}: {count:,} PQRS (Clic para ver tarjeta con gráfico y proyectos)",
        ).add_to(m)

    return m


# -----------------------------------------------------------------------------
# Aplicación Principal
# -----------------------------------------------------------------------------
def main():
    # Cargar datos reales
    geojson_data = load_geojson_data()
    df_pqrs_raw = load_real_pqrs_raw()
    df_projects_raw = load_real_projects_data()

    # Barra lateral de configuración y filtros
    with st.sidebar:
        st.title("⚙️ Filtros y Opciones")

        st.subheader("🗓️ Filtro de Vigencia (PQRS)")
        vigencias_disponibles = ["Todas", "2026", "2025", "2024", "2023", "2022"]
        vigencia_filtro = st.selectbox(
            "Selecciona el año de registro:",
            vigencias_disponibles,
            index=0,
            help="Filtra los datos de PQRS por año registrado en Orfeo.",
        )

        st.markdown("---")
        st.subheader("🎯 Métrica en las Bolitas")
        filtro_metrica = st.selectbox(
            "Métrica a visualizar:",
            options=[
                ("total_pqrs", "Total de PQRS"),
                ("resueltas", "PQRS Resueltas (Cerradas)"),
                ("en_gestion", "PQRS En Trámite"),
                ("pendientes", "PQRS Pendientes"),
                ("peticiones_particular", "Peticiones de Interés Particular"),
                ("peticiones_general", "Peticiones de Interés General"),
            ],
            format_func=lambda x: x[1],
            index=0,
        )[0]

        st.markdown("---")
        st.subheader("🗺️ Personalización del Mapa")

        tiles_choice = st.selectbox(
            "Estilo de mapa base:",
            ["OpenStreetMap (Estándar)", "CartoDB Positron (Limpio)", "CartoDB Dark (Oscuro)"],
            index=0,
        )

        scale_factor = st.slider(
            "Escala de tamaño de bolitas:",
            min_value=0.7,
            max_value=1.5,
            value=1.0,
            step=0.1,
            help="Aumenta o disminuye el diámetro de las burbujas.",
        )

        show_boundaries = st.checkbox(
            "Mostrar límites de localidades",
            value=True,
            help="Dibuja el perímetro de las 20 localidades oficiales.",
        )

        st.info("💡 **Tip**: Datos reales integrados de la Secretaría Distrital de Gobierno y Presupuestos Participativos.")

    # Generar resumen de PQRS con el filtro de vigencia seleccionado
    df_summary = get_pqrs_locality_summary(df_pqrs_raw, vigencia_filtro=vigencia_filtro)

    # Encabezado principal
    st.markdown('<div class="main-title">🏛️ Dashboard Territorial Bogotá D.C.</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="sub-title">Monitoreo ciudadano integrado: PQRS distritales ({vigencia_filtro}) y Proyectos de Inversión Local</div>',
        unsafe_allow_html=True,
    )

    # Pestañas principales de navegación del dashboard
    tab_mapa, tab_proyectos, tab_ficha = st.tabs(
        ["🗺️ Mapa y Monitoreo de PQRS", "🏗️ Proyectos de Inversión por Localidad", "📄 Ficha Descargable (PDF / PNG)"]
    )

    # -------------------------------------------------------------------------
    # PESTAÑA 1: MAPA Y MONITOREO DE PQRS
    # -------------------------------------------------------------------------
    with tab_mapa:
        # Métricas KPIs Generales
        total_general = int(df_summary["total_pqrs"].sum())
        total_resueltas = int(df_summary["resueltas"].sum())
        tasa_resolucion = (total_resueltas / total_general * 100) if total_general > 0 else 0

        max_row = df_summary.loc[df_summary["total_pqrs"].idxmax()]
        min_row = df_summary.loc[df_summary["total_pqrs"].idxmin()]

        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        with kpi1:
            st.metric(label="Total PQRS Registradas", value=f"{total_general:,}")
        with kpi2:
            st.metric(
                label="Mayor Volumen",
                value=f"{max_row['localidad']}",
                delta=f"{max_row['total_pqrs']:,} casos",
            )
        with kpi3:
            st.metric(
                label="Menor Volumen",
                value=f"{min_row['localidad']}",
                delta=f"{min_row['total_pqrs']:,} casos",
                delta_color="inverse",
            )
        with kpi4:
            st.metric(label="Tasa de Resolución", value=f"{tasa_resolucion:.1f}%")

        # Leyenda de criticidad
        st.markdown(
            """
            <div style="display: flex; gap: 16px; align-items: center; margin: 8px 0 14px 0; font-size: 0.88rem; flex-wrap: wrap;">
                <b>Nivel de casos:</b>
                <span style="display: inline-flex; align-items: center; gap: 4px;">
                    <span style="width: 12px; height: 12px; border-radius: 50%; background: #10B981; display: inline-block;"></span> Bajo
                </span>
                <span style="display: inline-flex; align-items: center; gap: 4px;">
                    <span style="width: 12px; height: 12px; border-radius: 50%; background: #F59E0B; display: inline-block;"></span> Medio
                </span>
                <span style="display: inline-flex; align-items: center; gap: 4px;">
                    <span style="width: 12px; height: 12px; border-radius: 50%; background: #F97316; display: inline-block;"></span> Alto
                </span>
                <span style="display: inline-flex; align-items: center; gap: 4px;">
                    <span style="width: 12px; height: 12px; border-radius: 50%; background: #EF4444; display: inline-block;"></span> Crítico
                </span>
                <span style="color: #64748B; margin-left: auto;">Oprime cualquier bolita para ver su gráfico de torta y proyectos destacados.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_mapa, col_lateral = st.columns([3, 1.2])

        with col_mapa:
            pdf_dict = get_cached_locality_pdfs(df_summary, df_projects_raw)
            mapa_folium = build_map(
                df_summary=df_summary,
                df_projects=df_projects_raw,
                geojson_data=geojson_data,
                metric_col=filtro_metrica,
                tiles_choice=tiles_choice,
                scale_factor=scale_factor,
                show_boundaries=show_boundaries,
                pdf_dict=pdf_dict,
            )
            mapa_html = mapa_folium.get_root().render()
            components.html(mapa_html, height=620, scrolling=False)

        with col_lateral:
            st.subheader("🏆 Ranking de Localidades")
            top_df = (
                df_summary[["localidad", filtro_metrica]]
                .sort_values(by=filtro_metrica, ascending=False)
                .reset_index(drop=True)
            )
            top_df.columns = ["Localidad", "Casos"]
            st.dataframe(
                top_df,
                use_container_width=True,
                height=570,
                hide_index=True,
            )

        st.markdown("---")
        st.subheader("📊 Distribución y Comparativa de PQRS")
        col_c1, col_c2 = st.columns(2)

        with col_c1:
            st.caption("Casos por localidad ordenados:")
            chart_data = df_summary.sort_values(by=filtro_metrica, ascending=True).set_index("localidad")[filtro_metrica]
            st.bar_chart(chart_data, horizontal=True)

        with col_c2:
            st.caption("Consolidado distrital por Estado de Atención:")
            estados_totales = pd.DataFrame(
                {
                    "Estado": ["Resueltas (Cerradas)", "En Trámite (Activas)", "Pendientes (Sin respuesta)"],
                    "Cantidad": [
                        df_summary["resueltas"].sum(),
                        df_summary["en_gestion"].sum(),
                        df_summary["pendientes"].sum(),
                    ],
                }
            )
            fig_est = px.pie(
                estados_totales,
                values="Cantidad",
                names="Estado",
                color="Estado",
                color_discrete_map={
                    "Resueltas (Cerradas)": "#10B981",
                    "En Trámite (Activas)": "#F59E0B",
                    "Pendientes (Sin respuesta)": "#EF4444",
                },
                hole=0.45,
            )
            fig_est.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=320)
            st.plotly_chart(fig_est, use_container_width=True)

        st.markdown("---")
        # ---------------------------------------------------------------------
        # SECCIÓN INFERIOR DE DESCARGA DIRECTA EN LA PESTAÑA DEL MAPA
        # ---------------------------------------------------------------------
        st.subheader("📥 Ficha Informativa y Descarga Directa de la Localidad")
        st.caption(
            "Consulta la ficha completa de cualquier localidad (gráfico de torta de estados de PQRS, métricas y Top 5 de proyectos) y descárgala en PDF o Imagen al instante sin cambiar de pestaña:"
        )

        col_f_sel_m, _ = st.columns([2, 2])
        with col_f_sel_m:
            lista_locs = sorted(df_summary["localidad"].tolist())
            loc_map_descarga = st.selectbox(
                "📍 Selecciona la Localidad para descargar su Ficha:",
                options=lista_locs,
                index=lista_locs.index("Chapinero") if "Chapinero" in lista_locs else 0,
                key="loc_select_map_tab",
            )

        sel_row_m = df_summary[df_summary["localidad"] == loc_map_descarga].iloc[0]
        top_proyectos_m = get_top_projects_by_locality(df_projects_raw, loc_map_descarga, top_n=5)

        with st.container():
            st.markdown(
                f"""
                <div class="card-container">
                    <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #E2E8F0; padding-bottom: 10px; margin-bottom: 16px;">
                        <h3 style="margin: 0; color: #1E293B;">📍 Ficha Territorial: Localidad de {sel_row_m['localidad']}</h3>
                        <span style="background-color: #1E293B; color: white; padding: 4px 12px; border-radius: 20px; font-weight: bold;">
                            Código: {sel_row_m['codigo']} | Total PQRS: {sel_row_m['total_pqrs']:,}
                        </span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            c_chart_m, c_details_m = st.columns([1.8, 2.2])

            with c_chart_m:
                st.write("##### 📊 Distribución de PQRS (Estados)")
                fig_pie_m = px.pie(
                    values=[sel_row_m["resueltas"], sel_row_m["en_gestion"], sel_row_m["pendientes"]],
                    names=["Resueltas", "En Trámite", "Pendientes"],
                    color=["Resueltas", "En Trámite", "Pendientes"],
                    color_discrete_map={
                        "Resueltas": "#10B981",
                        "En Trámite": "#F59E0B",
                        "Pendientes": "#EF4444",
                    },
                    hole=0.4,
                )
                fig_pie_m.update_traces(textinfo="percent+value", textfont_size=13)
                fig_pie_m.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=280)
                st.plotly_chart(fig_pie_m, use_container_width=True, key=f"pie_{loc_map_descarga}_m")

            with c_details_m:
                st.write("##### 📋 Resumen de Atención Ciudadana")
                m1_m, m2_m, m3_m = st.columns(3)
                with m1_m:
                    st.metric("✅ Resueltas", f"{sel_row_m['resueltas']:,}")
                with m2_m:
                    st.metric("⚙️ En Trámite", f"{sel_row_m['en_gestion']:,}")
                with m3_m:
                    st.metric("⏳ Pendientes", f"{sel_row_m['pendientes']:,}")

                st.markdown("<br/>", unsafe_allow_html=True)
                st.write("**Clasificación de Solicitudes:**")
                st.write(f"• **Peticiones de Interés Particular:** {sel_row_m['peticiones_particular']:,}")
                st.write(f"• **Peticiones de Interés General:** {sel_row_m['peticiones_general']:,}")
                st.write(f"• **Información y Consultas:** {sel_row_m['informacion_consultas']:,}")

            st.write("##### 🏗️ Top 5 Proyectos de Inversión Incluidos en la Ficha:")
            if not top_proyectos_m.empty:
                t_p_show_m = top_proyectos_m[["nombre_proyecto", "sector", "estado_proyecto", "presupuesto_millones"]].copy()
                t_p_show_m.columns = ["Proyecto", "Sector", "Estado", "Inversión (Millones COP)"]
                t_p_show_m["Inversión (Millones COP)"] = t_p_show_m["Inversión (Millones COP)"].apply(lambda x: f"$ {x:,.1f} M")
                st.dataframe(t_p_show_m, use_container_width=True, hide_index=True)

            st.markdown("---")
            st.write("##### 📥 Botones de Descarga Inmediata:")

            col_pdf_m, col_png_m, _ = st.columns([1.5, 1.5, 3])

            pdf_bytes_m = generate_locality_card_pdf(sel_row_m, top_proyectos_m)
            png_bytes_m = generate_locality_card_png(sel_row_m, top_proyectos_m)

            with col_pdf_m:
                st.download_button(
                    label="📄 Descargar Ficha en PDF",
                    data=pdf_bytes_m,
                    file_name=f"Ficha_Territorial_{sel_row_m['localidad']}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key=f"dl_pdf_{loc_map_descarga}_m",
                )

            with col_png_m:
                st.download_button(
                    label="🖼️ Descargar Ficha en Imagen (PNG)",
                    data=png_bytes_m,
                    file_name=f"Ficha_Territorial_{sel_row_m['localidad']}.png",
                    mime="image/png",
                    use_container_width=True,
                    key=f"dl_png_{loc_map_descarga}_m",
                )

    # -------------------------------------------------------------------------
    # PESTAÑA 2: APARTADO DE PROYECTOS POR LOCALIDAD
    # -------------------------------------------------------------------------
    with tab_proyectos:
        st.subheader("🏗️ Proyectos de Inversión Local en Bogotá")
        st.markdown(
            """
            Explora las iniciativas y proyectos de los Fondos de Desarrollo Local (FDL) y Presupuestos Participativos.
            Cualquier ciudadano puede consultar en qué se invierten los recursos de su localidad de forma clara y transparente.
            """
        )

        col_loc_sel, col_tipo_sel = st.columns([2, 2])
        with col_loc_sel:
            lista_localidades = sorted(df_summary["localidad"].tolist())
            loc_seleccionada_p = st.selectbox(
                "📍 Selecciona una Localidad para consultar sus proyectos:",
                options=lista_localidades,
                index=lista_localidades.index("Suba") if "Suba" in lista_localidades else 0,
                key="loc_select_proyectos",
            )

        with col_tipo_sel:
            filtro_tipo_reg = st.selectbox(
                "Filtrar por origen del dato:",
                ["Todos los proyectos", "Solo Oficiales / Reales (Presupuestos Participativos)", "Proyectos Sintéticos"],
                index=0,
            )

        # Filtrar proyectos de la localidad
        sub_p = df_projects_raw[df_projects_raw["localidad"] == loc_seleccionada_p].copy()
        if filtro_tipo_reg == "Solo Oficiales / Reales (Presupuestos Participativos)":
            sub_p = sub_p[sub_p["tipo_registro"] == "REAL"]
        elif filtro_tipo_reg == "Proyectos Sintéticos":
            sub_p = sub_p[sub_p["tipo_registro"] == "SINTETICO"]

        # Métricas de proyectos de la localidad
        tot_proyectos = len(sub_p)
        inversion_total_millones = sub_p["presupuesto_millones"].sum()
        en_ejecucion_cnt = int((sub_p["estado_proyecto"] == "En ejecución").sum())
        finalizados_cnt = int((sub_p["estado_proyecto"] == "Finalizado").sum())

        kp_p1, kp_p2, kp_p3, kp_p4 = st.columns(4)
        with kp_p1:
            st.metric("Total Proyectos", f"{tot_proyectos}")
        with kp_p2:
            st.metric("Inversión Comprometida", f"$ {inversion_total_millones:,.1f} M")
        with kp_p3:
            st.metric("En Ejecución", f"{en_ejecucion_cnt}", delta="Activos")
        with kp_p4:
            st.metric("Finalizados", f"{finalizados_cnt}", delta="Entregados")

        st.markdown("---")

        # Gráficos claros y fáciles de entender
        col_g1, col_g2 = st.columns(2)

        with col_g1:
            st.write("#### 📊 Estado de los Proyectos")
            st.caption("Distribución según la etapa actual de avance del proyecto:")
            if not sub_p.empty:
                estado_counts = sub_p["estado_proyecto"].value_counts().reset_index()
                estado_counts.columns = ["Estado", "Cantidad"]

                color_map_estados = {
                    "Finalizado": "#10B981",
                    "En ejecución": "#2563EB",
                    "Programado": "#64748B",
                    "Suspendido": "#F59E0B",
                    "Cancelado": "#EF4444",
                }

                fig_estados = px.pie(
                    estado_counts,
                    values="Cantidad",
                    names="Estado",
                    color="Estado",
                    color_discrete_map=color_map_estados,
                    hole=0.45,
                )
                fig_estados.update_traces(textinfo="percent+value", textfont_size=12)
                fig_estados.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=320)
                st.plotly_chart(fig_estados, use_container_width=True)
            else:
                st.info("No hay proyectos con el filtro actual.")

        with col_g2:
            st.write("#### 💰 Inversión por Sector")
            st.caption("Presupuesto comprometido en Millones de pesos COP:")
            if not sub_p.empty:
                sector_budget = (
                    sub_p.groupby("sector")["presupuesto_millones"]
                    .sum()
                    .reset_index()
                    .sort_values(by="presupuesto_millones", ascending=True)
                )

                fig_sectores = px.bar(
                    sector_budget,
                    x="presupuesto_millones",
                    y="sector",
                    orientation="h",
                    color="presupuesto_millones",
                    color_continuous_scale="Blues",
                    labels={"presupuesto_millones": "Inversión (Millones COP)", "sector": "Sector"},
                )
                fig_sectores.update_layout(
                    showlegend=False,
                    coloraxis_showscale=False,
                    margin=dict(t=20, b=20, l=20, r=20),
                    height=320,
                )
                st.plotly_chart(fig_sectores, use_container_width=True)
            else:
                st.info("No hay proyectos con el filtro actual.")

        st.markdown("---")

        # Top 5 Proyectos con mayor inversión
        st.write(f"#### 🏆 Top 5 Proyectos con Mayor Inversión en {loc_seleccionada_p}")
        st.caption("Proyectos con mayor impacto presupuestal para la comunidad:")

        top5 = get_top_projects_by_locality(sub_p, loc_seleccionada_p, top_n=5)
        if not top5.empty:
            for idx, p in top5.iterrows():
                with st.container():
                    col_t_nom, col_t_pres = st.columns([3, 1])
                    with col_t_nom:
                        st.markdown(f"**{idx + 1}. {p['nombre_proyecto']}**")
                        st.caption(f"Sector: **{p['sector']}** | Entidad: {p['entidad_responsable']}")
                    with col_t_pres:
                        st.markdown(f"**$ {p['presupuesto_millones']:,.1f} Millones**")
                        badge_color = "#10B981" if p["estado_proyecto"] == "Finalizado" else ("#2563EB" if p["estado_proyecto"] == "En ejecución" else "#64748B")
                        st.markdown(
                            f'<span style="background-color: {badge_color}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px;">{p["estado_proyecto"]}</span>',
                            unsafe_allow_html=True,
                        )
                    if pd.notna(p["descripcion_proyecto"]) and str(p["descripcion_proyecto"]).strip():
                        with st.expander("Ver descripción del proyecto"):
                            st.write(p["descripcion_proyecto"])
                    st.markdown("<hr style='margin: 8px 0; border: none; border-top: 1px solid #E2E8F0;'/>", unsafe_allow_html=True)
        else:
            st.info("No se encontraron proyectos para esta localidad.")

        # Tabla Completa de Proyectos
        st.write("#### 📋 Listado Completo de Proyectos en la Localidad")
        cols_mostrar = ["id_proyecto", "nombre_proyecto", "sector", "estado_proyecto", "presupuesto_millones", "tipo_registro"]
        df_tabla_p = sub_p[cols_mostrar].copy()
        df_tabla_p.columns = ["Código", "Proyecto", "Sector", "Estado", "Inversión (Millones COP)", "Origen"]
        st.dataframe(df_tabla_p.sort_values(by="Inversión (Millones COP)", ascending=False), use_container_width=True, hide_index=True)

    # -------------------------------------------------------------------------
    # PESTAÑA 3: FICHA DESCARGABLE (PDF Y PNG)
    # -------------------------------------------------------------------------
    with tab_ficha:
        st.subheader("📄 Ficha Territorial Descargable por Localidad")
        st.markdown(
            """
            Descarga un reporte consolidado en **PDF corporativo** o **Imagen en alta resolución (PNG)**
            que integra tanto el diagnóstico de PQRS (con su gráfico de torta) como el **Top 5 de proyectos de inversión** de la localidad.
            """
        )

        col_f_sel, _ = st.columns([2, 2])
        with col_f_sel:
            loc_ficha_name = st.selectbox(
                "📍 Selecciona la Localidad para generar su Ficha:",
                options=sorted(df_summary["localidad"].tolist()),
                index=0,
                key="loc_select_ficha",
            )

        sel_row = df_summary[df_summary["localidad"] == loc_ficha_name].iloc[0]
        top_proyectos_loc = get_top_projects_by_locality(df_projects_raw, loc_ficha_name, top_n=5)

        # Vista previa interactiva de la ficha
        with st.container():
            st.markdown(
                f"""
                <div class="card-container">
                    <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #E2E8F0; padding-bottom: 10px; margin-bottom: 16px;">
                        <h3 style="margin: 0; color: #1E293B;">📍 Ficha Territorial: Localidad de {sel_row['localidad']}</h3>
                        <span style="background-color: #1E293B; color: white; padding: 4px 12px; border-radius: 20px; font-weight: bold;">
                            Código: {sel_row['codigo']} | Total PQRS: {sel_row['total_pqrs']:,}
                        </span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            c_chart, c_details = st.columns([1.8, 2.2])

            with c_chart:
                st.write("##### 📊 Distribución de PQRS (Estados)")
                fig_pie_f = px.pie(
                    values=[sel_row["resueltas"], sel_row["en_gestion"], sel_row["pendientes"]],
                    names=["Resueltas", "En Trámite", "Pendientes"],
                    color=["Resueltas", "En Trámite", "Pendientes"],
                    color_discrete_map={
                        "Resueltas": "#10B981",
                        "En Trámite": "#F59E0B",
                        "Pendientes": "#EF4444",
                    },
                    hole=0.4,
                )
                fig_pie_f.update_traces(textinfo="percent+value", textfont_size=13)
                fig_pie_f.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=280)
                st.plotly_chart(fig_pie_f, use_container_width=True)

            with c_details:
                st.write("##### 📋 Métricas de Atención Ciudadana")
                m1, m2, m3 = st.columns(3)
                with m1:
                    st.metric("✅ Resueltas", f"{sel_row['resueltas']:,}")
                with m2:
                    st.metric("⚙️ En Trámite", f"{sel_row['en_gestion']:,}")
                with m3:
                    st.metric("⏳ Pendientes", f"{sel_row['pendientes']:,}")

                st.markdown("<br/>", unsafe_allow_html=True)
                st.write("**Clasificación de Solicitudes:**")
                st.write(f"• **Peticiones de Interés Particular:** {sel_row['peticiones_particular']:,}")
                st.write(f"• **Peticiones de Interés General:** {sel_row['peticiones_general']:,}")
                st.write(f"• **Información y Consultas:** {sel_row['informacion_consultas']:,}")

            # Top proyectos incluidos en la ficha
            st.write("##### 🏗️ Top 5 Proyectos de Inversión Incluidos en la Ficha:")
            if not top_proyectos_loc.empty:
                t_p_show = top_proyectos_loc[["nombre_proyecto", "sector", "estado_proyecto", "presupuesto_millones"]].copy()
                t_p_show.columns = ["Proyecto", "Sector", "Estado", "Inversión (Millones COP)"]
                t_p_show["Inversión (Millones COP)"] = t_p_show["Inversión (Millones COP)"].apply(lambda x: f"$ {x:,.1f} M")
                st.dataframe(t_p_show, use_container_width=True, hide_index=True)

            # Botones de descarga
            st.markdown("---")
            st.write("##### 📥 Descargar Ficha Consolidada:")

            col_pdf_f, col_png_f, _ = st.columns([1.5, 1.5, 3])

            pdf_bytes = generate_locality_card_pdf(sel_row, top_proyectos_loc)
            png_bytes = generate_locality_card_png(sel_row, top_proyectos_loc)

            with col_pdf_f:
                st.download_button(
                    label="📄 Descargar Ficha en PDF",
                    data=pdf_bytes,
                    file_name=f"Ficha_Territorial_{sel_row['localidad']}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )

            with col_png_f:
                st.download_button(
                    label="🖼️ Descargar Ficha en Imagen (PNG)",
                    data=png_bytes,
                    file_name=f"Ficha_Territorial_{sel_row['localidad']}.png",
                    mime="image/png",
                    use_container_width=True,
                )


if __name__ == "__main__":
    main()
