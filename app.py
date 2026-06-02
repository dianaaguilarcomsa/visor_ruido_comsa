import streamlit as st
import folium
from folium.plugins import Draw, Fullscreen, MeasureControl, Geocoder
from streamlit_folium import st_folium  # ¡Esta era la importación que faltaba!
import math
import zipfile
import io
import json
import re
import xml.etree.ElementTree as ET
import pandas as pd
from shapely.geometry import Point, LineString, Polygon as ShapelyPolygon
from shapely.ops import unary_union
from branca.element import Template, MacroElement

st.set_page_config(page_title="Visor Mapas de Ruido", layout="wide")

st.markdown("""
<style>
.stApp { background-color: var(--background-color); }
[data-testid="stHeader"] { background-color: transparent !important; }
[data-testid="stSidebar"] { background-color: var(--secondary-background-color); border-right: 1px solid var(--border-color); }
[data-testid="stMetric"] { background-color: var(--secondary-background-color); padding: 15px 20px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); border-left: 5px solid #0093D0; transition: transform 0.2s ease-in-out; }
[data-testid="stMetric"]:hover { transform: translateY(-2px); box-shadow: 0 6px 14px rgba(0,0,0,0.1); }
[data-testid="stExpander"] { background-color: var(--secondary-background-color); border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.03); border: 1px solid var(--border-color); margin-bottom: 10px; }
.stButton > button { border-radius: 8px !important; font-weight: 600 !important; transition: all 0.3s ease !important; }
h1, h2, h3, h4, h5, h6, p, span, label, div { color: var(--text-color); }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div style="display: flex; align-items: center; gap: 40px; font-family: 'Segoe UI', system-ui, sans-serif; margin-bottom: 25px; background-color: var(--secondary-background-color); padding: 15px 20px; border-radius: 10px; border: 1px solid var(--border-color); border-bottom: 4px solid #E3182D; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
    <div style="display: flex; flex-direction: column; align-items: flex-start; min-width: 120px;">
        <div style="display: flex; gap: 6px; margin-bottom: 2px;">
            <div style="width: 22px; height: 22px; background-color: #E3182D; border-radius: 50%;"></div>
            <div style="width: 22px; height: 22px; background-color: #0093D0; border-radius: 50%;"></div>
        </div>
        <div style="color: var(--text-color); font-size: 28px; font-weight: 900; line-height: 1; letter-spacing: -1px;">COMSA</div>
        <div style="color: var(--text-color); opacity: 0.8; font-size: 11px; font-weight: 600; letter-spacing: 0.5px;">CORPORACIÓN</div>
    </div>
    <div style="border-left: 2px solid var(--border-color); padding-left: 30px;">
        <h1 style="color: var(--text-color); margin: 0; font-size: 2.2rem; font-weight: 800; letter-spacing: -0.5px;">Visor Mapas de Ruido</h1>
    </div>
</div>
""", unsafe_allow_html=True)

# Inicialización BLINDADA
if "mis_dibujos" not in st.session_state:
    st.session_state["mis_dibujos"] = []
if "map_version" not in st.session_state:
    st.session_state["map_version"] = 0
if "map_center" not in st.session_state:
    st.session_state["map_center"] = [40.4410, -3.6908]
if "map_zoom" not in st.session_state:
    st.session_state["map_zoom"] = 15

# Capturar estado del mapa
map_key_actual = f"visor_mapa_{st.session_state['map_version']}"
if map_key_actual in st.session_state and st.session_state[map_key_actual]:
    datos_mapa = st.session_state[map_key_actual]
    if isinstance(datos_mapa, dict):
        if datos_mapa.get("center"):
            st.session_state["map_center"] = [datos_mapa["center"]["lat"], datos_mapa["center"]["lng"]]
        if datos_mapa.get("zoom"):
            st.session_state["map_zoom"] = datos_mapa["zoom"]

malla_fina_config = [
    {"min": 30, "color": "#00FF00"}, {"min": 35, "color": "#66B24D"},
    {"min": 40, "color": "#99CC33"}, {"min": 45, "color": "#D8F2A0"},
    {"min": 50, "color": "#FFFF00"}, {"min": 55, "color": "#FFE6AA"},
    {"min": 60, "color": "#FFAA33"}, {"min": 65, "color": "#FF3333"},
    {"min": 70, "color": "#CC3333"}, {"min": 75, "color": "#FF00FF"},
    {"min": 80, "color": "#295180"}
]

@st.cache_data
def cargar_maquinas():
    try:
        return pd.read_csv("maquinaria.csv")
    except:
        return pd.DataFrame({"Nombre_Maquina": ["Máquina Genérica"], "dB_1m": [90.0]})

df_maq = cargar_maquinas()
lista_maquinas = df_maq['Nombre_Maquina'].tolist() + ["➕ Otra (Manual)"]

for idx, feature in enumerate(st.session_state["mis_dibujos"]):
    tipo = feature["geometry"]["type"]
    if "properties" not in feature: feature["properties"] = {}
    if "name" not in feature["properties"]:
        prefix = "Foco" if tipo == "Point" else "Pantalla" if tipo == "LineString" else "Población"
        feature["properties"]["name"] = f"{prefix} {idx+1}"
    if tipo == "Point" and "maq" not in feature["properties"]:
        feature["properties"]["maq"] = {}
    if tipo == "LineString" and "aten" not in feature["properties"]:
        feature["properties"]["aten"] = 15.0
    if tipo == "Polygon" and "umbral" not in feature["properties"]:
        feature["properties"]["umbral"] = 65.0
        feature["properties"]["uso_nombre"] = "Residencial"

def sumar_decibelios(dic_maq):
    if not dic_maq: return 0
    return 10 * math.log10(sum(10 ** (db / 10) for db in dic_maq.values()))

def calcular_radio(origen, umbral, aten):
    if origen - aten <= umbral: return 0
    return 10 ** ((origen - umbral - aten) / 20)

def distancia_haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2, d_phi, d_lam = map(math.radians, [lat1, lat2, lat2-lat1, lon2-lon1])
    a = math.sin(d_phi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(d_lam/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

def parsear_kml_a_dibujos(kml_texto):
    dibujos = []
    try:
        kml_limpio = re.sub(r'xmlns="[^"]+"', '', kml_texto)
        root = ET.fromstring(kml_limpio)
        for placemark in root.iter('Placemark'):
            name_tag = placemark.find('name')
            nombre = name_tag.text if name_tag is not None else "Elemento Importado"
            pt = placemark.find('.//Point')
            if pt is not None:
                coord_tag = pt.find('coordinates')
                if coord_tag is not None:
                    coords = coord_tag.text.strip().split()
                    if coords:
                        lon, lat = map(float, coords[0].split(',')[:2])
                        dibujos.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": {"name": nombre, "maq": {}}})
                        continue
            ls = placemark.find('.//LineString')
            if ls is not None:
                coord_tag = ls.find('coordinates')
                if coord_tag is not None:
                    pares = coord_tag.text.strip().split()
                    coords_list = [[float(p.split(',')[0]), float(p.split(',')[1])] for p in pares if len(p.split(',')) >= 2]
                    if coords_list:
                        dibujos.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords_list}, "properties": {"name": nombre, "aten": 15.0}})
                        continue
            poly = placemark.find('.//Polygon')
            if poly is not None:
                coord_tag = poly.find('.//coordinates')
                if coord_tag is not None:
                    pares = coord_tag.text.strip().split()
                    coords_list = [[float(p.split(',')[0]), float(p.split(',')[1])] for p in pares if len(p.split(',')) >= 2]
                    if coords_list:
                        dibujos.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [coords_list]}, "properties": {"name": nombre, "umbral": 65.0, "uso_nombre": "Residencial"}})
                        continue
    except Exception as e:
        st.error(f"Error parseando KML: {e}")
    return dibujos

@st.cache_data(show_spinner=False)
def generar_isofona_con_sombra(foco_lat, foco_lon, emision_foco, umbral_banda, pantallas_data_json, focos_all_json, r_earth=6378137.0):
    pantallas_data = json.loads(pantallas_data_json)
    focos_all = json.loads(focos_all_json)
    coords = []
    foco_pt = Point(foco_lon, foco_lat)
    radio_base = calcular_radio(emision_foco, umbral_banda, 0)
    if radio_base <= 0: return []
    emision_total_all = 10 * math.log10(sum(10**(f["emision"]/10) for f in focos_all)) if focos_all else emision_foco
    r_max_posible = calcular_radio(emision_total_all, umbral_banda, 0)
    for angle in range(361):
        rad = math.radians(angle)
        r_max_libre = radio_base
        if len(focos_all) > 1 and r_max_posible > radio_base:
            low = radio_base
            high = r_max_posible + 5
            for _ in range(12):
                mid = (low + high) / 2
                d_lon = math.degrees(mid * math.cos(rad) / (r_earth * math.cos(math.radians(foco_lat))))
                d_lat = math.degrees(mid * math.sin(rad) / r_earth)
                ruidos_pto = []
                for f in focos_all:
                    dist = distancia_haversine(f["coords"][1], f["coords"][0], foco_lat + d_lat, foco_lon + d_lon)
                    val = f["emision"] - 20 * math.log10(dist) if dist > 1 else f["emision"]
                    ruidos_pto.append(val)
                tot = 10 * math.log10(sum(10**(x/10) for x in ruidos_pto)) if ruidos_pto else 0
                if tot >= umbral_banda: low = mid
                else: high = mid
            r_max_libre = low
        d_lon_max = math.degrees(r_max_libre * math.cos(rad) / (r_earth * math.cos(math.radians(foco_lat))))
        d_lat_max = math.degrees(r_max_libre * math.sin(rad) / r_earth)
        punto_max = Point(foco_lon + d_lon_max, foco_lat + d_lat_max)
        rayo = LineString([foco_pt, punto_max])
        radio_final = r_max_libre
        for p in pantallas_data:
            pantalla_line = LineString(p["coords"])
            if rayo.intersects(pantalla_line):
                interseccion = rayo.intersection(pantalla_line)
                pt_int = interseccion if interseccion.geom_type == 'Point' else interseccion.geoms[0]
                d_muro = distancia_haversine(foco_lat, foco_lon, pt_int.y, pt_int.x)
                pt_closest = pantalla_line.interpolate(pantalla_line.project(foco_pt))
                d_min_wall = distancia_haversine(foco_lat, foco_lon, pt_closest.y, pt_closest.x)
                radio_aten = r_max_libre * (10 ** (-p["aten"] / 20))
                if radio_aten <= d_min_wall: radio_final = min(radio_final, d_muro)
                else:
                    d_extra = radio_aten - d_min_wall
                    radio_final = min(radio_final, d_muro + d_extra)
        d_lon_final = math.degrees(radio_final * math.cos(rad) / (r_earth * math.cos(math.radians(foco_lat))))
        d_lat_final = math.degrees(radio_final * math.sin(rad) / r_earth)
        coords.append([foco_lat + d_lat_final, foco_lon + d_lon_final])
    return coords

def hex_to_kml_color(hex_color, alpha="60"):
    colores_basicos = {"green": "00ff00", "orange": "00a5ff", "red": "0000ff"}
    hex_clean = colores_basicos.get(hex_color.lower(), hex_color.replace("#", ""))
    if len(hex_clean) == 6:
        r, g, b = hex_clean[0:2], hex_clean[2:4], hex_clean[4:6]
        return f"{alpha}{b}{g}{r}"
    return f"{alpha}ffffff"

def generar_kmz(focos_list, pantallas_list, poblaciones_list, isofonas_list):
    kml = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2">', '<Document>', '<name>Resultados Visor Acústico COMSA</name>']
    if isofonas_list:
        kml.append('<Folder><name>Mapas de Ondas de Ruido (Círculos)</name>')
        for iso in isofonas_list:
            kml_color = hex_to_kml_color(iso["color"], alpha="50")
            kml.append('<Placemark>')
            kml.append(f'<name>{iso["name"]}</name>')
            kml.append(f'<Style><PolyStyle><color>{kml_color}</color><fill>1</fill><outline>1</outline></PolyStyle><LineStyle><color>{kml_color}</color><width>1</width></LineStyle></Style>')
            kml.append('<Polygon><outerBoundaryIs><LinearRing><coordinates>')
            coord_str = " ".join([f"{lon},{lat},0" for lat, lon in iso["coords"]])
            coord_str += f" {iso['coords'][0][1]},{iso['coords'][0][0]},0"
            kml.append(coord_str)
            kml.append('</coordinates></LinearRing></outerBoundaryIs></Polygon>')
            kml.append('</Placemark>')
        kml.append('</Folder>')
    for f in focos_list:
        lon, lat = f["coords"]
        kml.append('<Placemark>')
        kml.append(f'<name>{f["name"]}</name>')
        kml.append(f'<description>Foco Acústico\nEmisión: {f["emision"]:.1f} dB</description>')
        kml.append(f'<Point><coordinates>{lon},{lat},0</coordinates></Point>')
        kml.append('</Placemark>')
    for p in pantallas_list:
        kml.append('<Placemark>')
        kml.append(f'<name>{p["name"]}</name>')
        kml.append(f'<description>Pantalla Acústica\nAtenuación: {p["aten"]:.1f} dB</description>')
        kml.append('<Style><LineStyle><color>ffffff00</color><width>6</width></LineStyle></Style>')
        kml.append('<LineString><coordinates>')
        kml.append(" ".join([f"{lon},{lat},0" for lon, lat in p["coords"]]))
        kml.append('</coordinates></LineString>')
        kml.append('</Placemark>')
    for pob in poblaciones_list:
        kml.append('<Placemark>')
        kml.append(f'<name>{pob["name"]}</name>')
        kml.append(f'<description>Núcleo Receptor | Umbral: {pob.get("umbral", 65.0)} dB</description>')
        kml.append('<Style><PolyStyle><color>7f00ff00</color><fill>1</fill><outline>1</outline></PolyStyle><LineStyle><color>ff00ff00</color><width>2</width></LineStyle></Style>')
        kml.append('<Polygon><outerBoundaryIs><LinearRing><coordinates>')
        kml.append(" ".join([f"{lon},{lat},0" for lon, lat in pob["coords"]]))
        kml.append(f' {pob["coords"][0][0]},{pob["coords"][0][1]},0')
        kml.append('</coordinates></LinearRing></outerBoundaryIs></Polygon>')
        kml.append('</Placemark>')
    kml.append('</Document></kml>')
    kmz_buffer = io.BytesIO()
    with zipfile.ZipFile(kmz_buffer, 'w', zipfile.ZIP_DEFLATED) as zf: zf.writestr('doc.kml', "\n".join(kml))
    kmz_buffer.seek(0)
    return kmz_buffer

with st.sidebar:
    st.title("⚙️ Panel de Control")

    with st.expander("💾 Gestión de Proyectos", expanded=True):
        if st.session_state["mis_dibujos"]:
            json_proyecto = json.dumps(st.session_state["mis_dibujos"], indent=2)
            st.download_button("💾 Guardar Proyecto (.json)", data=json_proyecto, file_name="proyecto_ruido.json", mime="application/json", use_container_width=True)
        st.write("---")
        archivo_cargado = st.file_uploader("📂 Importar Proyecto (.json, .kmz)", type=["json", "kmz"])
        if archivo_cargado is not None:
            nombre_arch = archivo_cargado.name.lower()
            if nombre_arch.endswith('.json'):
                try:
                    datos = json.load(archivo_cargado)
                    if st.button("Aplicar JSON Cargado", use_container_width=True):
                        st.session_state["mis_dibujos"] = datos
                        st.session_state["map_version"] += 1
                        st.rerun()
                except Exception as e:
                    st.error(f"Error al leer JSON: {e}")
            elif nombre_arch.endswith('.kmz'):
                try:
                    with zipfile.ZipFile(archivo_cargado) as zf:
                        kml_internos = [f for f in zf.namelist() if f.endswith('.kml')]
                        if kml_internos:
                            kml_texto = zf.read(kml_internos[0]).decode('utf-8')
                            dibujos_kml = parsear_kml_a_dibujos(kml_texto)
                            if dibujos_kml:
                                st.success(f"Detectados {len(dibujos_kml)} elementos en el KMZ.")
                                if st.button("Aplicar KMZ Cargado", use_container_width=True):
                                    st.session_state["mis_dibujos"] = dibujos_kml
                                    if dibujos_kml[0]["geometry"]["coordinates"]:
                                        c = dibujos_kml[0]["geometry"]["coordinates"]
                                        if dibujos_kml[0]["geometry"]["type"] == "Point":
                                            st.session_state["map_center"] = [c[1], c[0]]
                                        else:
                                            st.session_state["map_center"] = [c[0][1], c[0][0]] if isinstance(c[0], list) else [c[1], c[0]]
                                    st.session_state["map_version"] += 1
                                    st.rerun()
                            else:
                                st.warning("No se encontraron geometrías válidas en el KMZ.")
                        else:
                            st.error("KMZ inválido (Falta archivo KML interno).")
                except Exception as e:
                    st.error(f"Error descomprimiendo KMZ: {e}")

    with st.expander("🗺️ Interruptores de Capas y Fondos", expanded=True):
        activar_catastro = st.checkbox("🏢 Activar capa de Catastro", value=False)
        activar_siose = st.checkbox("🗺️ Activar capa de Usos del Suelo (SIOSE)", value=False)
        activar_ambientales = st.checkbox("🌲 Activar Espacios Protegidos y Fauna Sensible", value=False)
        activar_fluviales = st.checkbox("💧 Activar capa de Zonas Fluviales", value=False)
        activar_transportes = st.checkbox("🛣️ Activar capa de Infraestructuras de Transporte", value=False)
        st.write("---")
        idx_fondo_defecto = 1 if activar_ambientales else 0
        fondo_seleccionado = st.radio(
            "Fondo del Mapa Base:",
            ["OpenStreetMap (Color Tradicional)", "Fondo Gris Claro (Simplificado)", "Satélite (Esri World Imagery)", "Topográfico (OpenTopoMap)"],
            index=idx_fondo_defecto
        )

    with st.expander("📚 Leyendas Capas Oficiales", expanded=False):
        st.markdown("**Límites Legales de Ruido (España / ADIF):**")
        # Corrección: Uso de min-width para cuadraditos y textos más cortos para evitar saltos de línea
        st.markdown("""
        <div style="font-size: 12px; font-family: 'Segoe UI', system-ui, sans-serif; line-height: 1.5;">
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: #E6004D; margin-right: 8px; border: 1px solid #ccc;"></div><b>Rojo oscuro:</b> Res. Continuo (D:65/N:55)</div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: #FF0000; margin-right: 8px; border: 1px solid #ccc;"></div><b>Rojo vivo:</b> Res. Discontinuo (D:65/N:55)</div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: #CC4DF2; margin-right: 8px; border: 1px solid #ccc;"></div><b>Morado:</b> Industriales (D:75/N:65)</div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: #CC0066; margin-right: 8px; border: 1px solid #ccc;"></div><b>Granate:</b> Inf. Transporte / ADIF</div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: #FFA6FF; margin-right: 8px; border: 1px solid #ccc;"></div><b>Rosa:</b> Dotacional (D:60/N:50)</div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: #A6FF80; margin-right: 8px; border: 1px solid #ccc;"></div><b>Verde Pistacho:</b> Recreativo (D:73/N:63)</div>
            
            <hr style="margin: 8px 0; border: 0; border-top: 1px solid #ddd;">
            <div style="color: #666; font-size: 11px; margin-bottom: 4px; font-weight: bold;">Capa Ambiental (EEA Natura 2000 & CDDA)</div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: repeating-linear-gradient(45deg, #FF9800, #FF9800 2px, transparent 2px, transparent 4px); margin-right: 8px; border: 1px solid #FF9800;"></div><b>Trama Naranja:</b> ZEPA (Aves) - 55 dB</div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: repeating-linear-gradient(45deg, #4CAF50, #4CAF50 2px, transparent 2px, transparent 4px); margin-right: 8px; border: 1px solid #4CAF50;"></div><b>Trama Verde:</b> LIC / ZEC (Hábitats) - 55 dB</div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: rgba(156, 39, 176, 0.6); margin-right: 8px; border: 1px solid #9C27B0;"></div><b>Morado:</b> Espacios Protegidos CDDA - 55 dB</div>
            <hr style="margin: 8px 0; border: 0; border-top: 1px solid #ddd;">
            
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: #E6CCCC; margin-right: 8px; border: 1px solid #ccc;"></div><b>Gris/Marrón:</b> Obras o extracción</div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: #FFFFA8; margin-right: 8px; border: 1px solid #ccc;"></div><b>Amarillo:</b> Tierras de Cultivo</div>
            <div style="display: flex; align-items: center;"><div style="min-width: 15px; height: 15px; background: #00CCF2; margin-right: 8px; border: 1px solid #ccc;"></div><b>Azul:</b> Cursos de agua</div>
        </div>
        """, unsafe_allow_html=True)

    with st.expander("📜 1. Fondo de Isófonas Global", expanded=True):
        tipo_malla = st.radio("Estilo de Visualización:", ["Malla Básica (Semáforo)", "Malla Fina (Intervalos 5dB)"])
        activar_umbral_global = st.checkbox("Mostrar línea de límite común voluntaria", value=True)
        umbral_referencia = st.number_input("Umbral de Referencia / Límite Común (dB):", value=65.0, step=1.0)

    with st.expander("🏷️ 2. Configuración de Elementos", expanded=True):
        if not st.session_state["mis_dibujos"]: st.info("Dibuja elementos en el mapa para configurar sus propiedades.")
        else:
            for idx, feature in enumerate(st.session_state["mis_dibujos"]):
                tipo = feature["geometry"]["type"]
                props = feature["properties"]
                icono = "📍" if tipo == "Point" else "〰️" if tipo == "LineString" else "⬟"
                col_tit, col_del = st.columns([5, 1])
                with col_tit: st.markdown(f"**{icono} Elemento {idx+1} ({props['name']})**")
                with col_del:
                    if st.button("🗑️", key=f"borrar_elem_{idx}"):
                        st.session_state["mis_dibujos"].pop(idx)
                        st.session_state["map_version"] += 1
                        st.rerun()
                props["name"] = st.text_input(f"Nombre {icono}", value=props["name"], key=f"name_{idx}")
                if tipo == "Point":
                    for m, db in list(props["maq"].items()):
                        col_m, col_b = st.columns([3, 1])
                        col_m.caption(f"• {m}: {db} dB")
                        if col_b.button("🗑️", key=f"del_{idx}_{m}"):
                            del props["maq"][m]
                            st.rerun()
                    c1, c2 = st.columns(2)
                    maquina_sel = c1.selectbox("Máquina:", lista_maquinas, key=f"sel_maq_{idx}")
                    if maquina_sel == "➕ Otra (Manual)":
                        m_nom = c1.text_input("Nombre:", key=f"m_nom_{idx}")
                        m_db = c2.number_input("dB (1m):", value=90.0, step=1.0, key=f"m_db_{idx}")
                    else:
                        m_nom = maquina_sel
                        db_defecto = float(df_maq[df_maq['Nombre_Maquina'] == maquina_sel]['dB_1m'].values[0])
                        m_db = c2.number_input("dB (1m):", value=db_defecto, step=1.0, key=f"m_db_{idx}")
                    if st.button("➕ Asignar", key=f"btn_assign_{idx}") and m_nom:
                        props["maq"][m_nom] = m_db
                        st.rerun()
                    st.write(f"Potencia Foco: **{sumar_decibelios(props['maq']):.1f} dB**")
                elif tipo == "LineString":
                    props["aten"] = st.number_input("Atenuación Muro (dB):", value=props["aten"], step=1.0, key=f"aten_{idx}")
                elif tipo == "Polygon":
                    usos_pob = {
                        "Sanitario, docente y cultural (Dotacional)": 60.0,
                        "Residencial": 65.0,
                        "Terciario y oficinas": 70.0,
                        "Recreativo y espectáculos": 73.0,
                        "Industrial": 75.0,
                        "Espacios naturales protegidos": 55.0,
                        "Zonas fluviales y riberas": 55.0,
                        "Fauna sensible / Áreas tranquilas": 45.0
                    }
                    if "uso_nombre" not in props: props["uso_nombre"] = "Residencial"
                    if "umbral" not in props: props["umbral"] = 65.0
                    idx_uso = list(usos_pob.keys()).index(props["uso_nombre"]) if props["uso_nombre"] in usos_pob else 1
                    sel_uso = st.selectbox("Categoría de Área Acústica:", list(usos_pob.keys()), index=idx_uso, key=f"uso_{idx}")
                    if sel_uso != props["uso_nombre"]:
                        props["uso_nombre"] = sel_uso
                        props["umbral"] = usos_pob[sel_uso]
                        st.rerun()
                    props["umbral"] = st.number_input("Límite Legal a aplicar (dB):", value=float(props["umbral"]), step=1.0, key=f"umb_{idx}")
                st.write("---")

    with st.expander("📥 3. Exportación", expanded=True):
        if st.session_state["mis_dibujos"]:
            tmp_focos, tmp_pan, tmp_pob = [], [], []
            for f in st.session_state["mis_dibujos"]:
                t = f["geometry"]["type"]
                if t == "Point": tmp_focos.append({"coords": f["geometry"]["coordinates"], "name": f["properties"]["name"], "emision": sumar_decibelios(f["properties"]["maq"])})
                elif t == "LineString": tmp_pan.append({"coords": f["geometry"]["coordinates"], "name": f["properties"]["name"], "aten": f["properties"]["aten"]})
                elif t == "Polygon": tmp_pob.append({"coords": f["geometry"]["coordinates"][0], "name": f["properties"]["name"], "umbral": f["properties"].get("umbral", 65.0)})
            kmz_data = generar_kmz(tmp_focos, tmp_pan, tmp_pob, [])
            st.download_button("⬇️ Descargar KMZ", data=kmz_data, file_name="mapa_ruido.kmz", mime="application/vnd.google-earth.kmz", use_container_width=True)

    with st.expander("🔗 4. Portales Oficiales", expanded=True):
        st.markdown("""
        * 🌲 [Espacios Protegidos y Red Natura (MITECO)](https://www.miteco.gob.es/es/biodiversidad/servicios/banco-datos-naturaleza/bdn-visores.html)
        * 🏢 [Sede Electrónica del Catastro](https://www1.sedecatastro.gob.es/Cartografia/mapa.aspx?buscar=S)
        * 🗺️ [SIOSE Oficial](https://www.siose.es/)
        """)

    if st.button("🧹 Limpiar Mapa Completo", type="primary", use_container_width=True):
        st.session_state["mis_dibujos"] = []
        st.session_state["map_version"] += 1
        st.rerun()

focos = []
pantallas_data = []
poblaciones = []

for feature in st.session_state["mis_dibujos"]:
    tipo = feature["geometry"]["type"]
    coords = feature["geometry"]["coordinates"]
    props = feature["properties"]
    if tipo == "Point":
        focos.append({"coords": coords, "name": props["name"], "emision": sumar_decibelios(props["maq"])})
    elif tipo == "LineString":
        pantallas_data.append({"coords": coords, "name": props["name"], "aten": props["aten"]})
    elif tipo == "Polygon":
        poblaciones.append({"coords": coords[0], "name": props["name"], "umbral": props.get("umbral", 65.0), "uso_nombre": props.get("uso_nombre", "Residencial")})

col1, col2, col3 = st.columns(3)
col1.metric("📍 Focos Detectados", len(focos))
col2.metric("〰️ Pantallas Detectadas", len(pantallas_data))
col3.metric("⬟ Zonas Evaluadas", len(poblaciones))

centro = st.session_state["map_center"]
zoom = st.session_state["map_zoom"]

if fondo_seleccionado == "Fondo Gris Claro (Simplificado)":
    m = folium.Map(location=centro, zoom_start=zoom, tiles="cartodbpositron")
elif fondo_seleccionado == "Satélite (Esri World Imagery)":
    m = folium.Map(location=centro, zoom_start=zoom, tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", attr="Tiles &copy; Esri")
elif fondo_seleccionado == "Topográfico (OpenTopoMap)":
    m = folium.Map(location=centro, zoom_start=zoom, tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", attr="Map data: &copy; OpenStreetMap contributors | Style: OpenTopoMap")
else:
    m = folium.Map(location=centro, zoom_start=zoom, tiles="OpenStreetMap")

Fullscreen(position='bottomleft', title='Ampliar a pantalla completa').add_to(m)
MeasureControl(position='topleft', primary_length_unit='meters', secondary_length_unit='kilometers', primary_area_unit='sqmeters').add_to(m)
Geocoder(position='topleft').add_to(m)

if activar_catastro:
    folium.WmsTileLayer(url="https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx", layers="CATASTRO", name="🏢 Catastro", fmt="image/png", transparent=True, opacity=0.6, overlay=True, control=False).add_to(m)

if activar_siose:
    folium.WmsTileLayer(url="https://servicios.idee.es/wms-inspire/ocupacion-suelo", layers="LC.LandCoverSurfaces", name="🗺️ Usos del Suelo (SIOSE)", fmt="image/png", transparent=True, opacity=0.5, overlay=True, control=False).add_to(m)

if activar_ambientales:
    folium.WmsTileLayer(url="https://bio.discomap.eea.europa.eu/arcgis/services/ProtectedSites/CDDA_Dyna_WM/MapServer/WMSServer", layers="0,1,2,3,4", fmt="image/png", transparent=True, version="1.3.0", opacity=0.8, overlay=True, control=False).add_to(m)
    folium.WmsTileLayer(url="https://bio.discomap.eea.europa.eu/arcgis/services/ProtectedSites/Natura2000Sites/MapServer/WMSServer", layers="0,1,2,3", fmt="image/png", transparent=True, version="1.3.0", opacity=1.0, overlay=True, control=False).add_to(m)

if activar_fluviales:
    folium.WmsTileLayer(url="https://servicios.idee.es/wms-inspire/hidrografia", layers="HY.PhysicalWaters.Waterbodies", name="💧 Zonas Fluviales", fmt="image/png", transparent=True, opacity=0.6, overlay=True, control=False).add_to(m)

if activar_transportes:
    folium.WmsTileLayer(url="https://servicios.idee.es/wms-inspire/transportes", layers="TN.RoadTransportNetwork.RoadLink", name="🛣️ Transportes", fmt="image/png", transparent=True, opacity=0.7, overlay=True, control=False).add_to(m)

fg_isofonas = folium.FeatureGroup(name="🔊 Ondas de Ruido (Isófonas)").add_to(m)
fg_poblaciones = folium.FeatureGroup(name="🏠 Poblaciones Evaluadas").add_to(m)
fg_pantallas = folium.FeatureGroup(name="〰️ Pantallas Acústicas").add_to(m)
fg_focos = folium.FeatureGroup(name="📍 Focos de Maquinaria").add_to(m)

pantallas_json = json.dumps(pantallas_data)
focos_json = json.dumps(focos)

css_texto = 'color: white; text-shadow: -1.5px -1.5px 0 #000, 1.5px -1.5px 0 #000, -1.5px 1.5px 0 #000, 1.5px 1.5px 0 #000; font-weight: bold; font-size: 14px; white-space: nowrap;'

if tipo_malla == "Malla Fina (Intervalos 5dB)":
    for banda in malla_fina_config:
        poligonos_banda = []
        for f in focos:
            if f["emision"] > banda["min"]:
                coords = generar_isofona_con_sombra(f["coords"][1], f["coords"][0], f["emision"], banda["min"], pantallas_json, focos_json)
                if len(coords) >= 3:
                    poly = ShapelyPolygon([(c[1], c[0]) for c in coords])
                    if not poly.is_valid: poly = poly.buffer(0)
                    poligonos_banda.append(poly)
        if poligonos_banda:
            merged_poly = unary_union(poligonos_banda)
            geoms = [merged_poly] if merged_poly.geom_type == 'Polygon' else merged_poly.geoms
            for geom in geoms:
                coords_folium = [(lat, lon) for lon, lat in geom.exterior.coords]
                folium.Polygon(locations=coords_folium, color=banda["color"], fill=True, fill_color=banda["color"], fill_opacity=0.4, weight=1, tooltip=f"Línea de Ruido: {banda['min']} dB").add_to(fg_isofonas)
else:
    for umb, color, opacity, w in [(umbral_referencia - 20, "green", 0.1, 1), (umbral_referencia - 10, "orange", 0.2, 1), (umbral_referencia, "red", 0.3, 2)]:
        poligonos_banda = []
        for f in focos:
            if f["emision"] > umb:
                coords = generar_isofona_con_sombra(f["coords"][1], f["coords"][0], f["emision"], umb, pantallas_json, focos_json)
                if len(coords) >= 3:
                    poly = ShapelyPolygon([(c[1], c[0]) for c in coords])
                    if not poly.is_valid: poly = poly.buffer(0)
                    poligonos_banda.append(poly)
        if poligonos_banda:
            merged_poly = unary_union(poligonos_banda)
            geoms = [merged_poly] if merged_poly.geom_type == 'Polygon' else merged_poly.geoms
            for geom in geoms:
                coords_folium = [(lat, lon) for lon, lat in geom.exterior.coords]
                folium.Polygon(locations=coords_folium, color=color, fill=True, fill_opacity=opacity, weight=w+1, tooltip=f"Límite: {umb} dB").add_to(fg_isofonas)

if activar_umbral_global:
    poligonos_limite = []
    for f in focos:
        if f["emision"] > umbral_referencia:
            coords = generar_isofona_con_sombra(f["coords"][1], f["coords"][0], f["emision"], umbral_referencia, pantallas_json, focos_json)
            if len(coords) >= 3:
                poly = ShapelyPolygon([(c[1], c[0]) for c in coords])
                if not poly.is_valid: poly = poly.buffer(0)
                poligonos_limite.append(poly)
    if poligonos_limite:
        merged_poly = unary_union(poligonos_limite)
        geoms = [merged_poly] if merged_poly.geom_type == 'Polygon' else merged_poly.geoms
        for geom in geoms:
            coords_folium = [(lat, lon) for lon, lat in geom.exterior.coords]
            folium.Polygon(locations=coords_folium, color="red", fill=False, weight=3, dash_array="10, 10", tooltip=f"Límite Común Voluntario: {umbral_referencia} dB").add_to(fg_isofonas)

for pob in poblaciones:
    poly_coords = pob["coords"]
    nombre = pob["name"]
    umbral_pob = pob["umbral"]
    shapely_poly = ShapelyPolygon(poly_coords)
    c_lon, c_lat = shapely_poly.centroid.x, shapely_poly.centroid.y
    ruidos_parciales = []
    for f in focos:
        flon, flat = f["coords"]
        if f["emision"] <= 0: continue
        dist = distancia_haversine(flat, flon, c_lat, c_lon)
        linea_vision = LineString([(flon, flat), (c_lon, c_lat)])
        aten_aplicada = 0
        for p in pantallas_data:
            if linea_vision.intersects(LineString(p["coords"])): aten_aplicada = max(aten_aplicada, p["aten"])
        ruido = f["emision"] - 20 * math.log10(dist) - aten_aplicada if dist > 1 else f["emision"] - aten_aplicada
        ruidos_parciales.append(ruido)
    ruido_total = 10 * math.log10(sum(10 ** (r / 10) for r in ruidos_parciales)) if ruidos_parciales else 0
    supera_umbral = False
    if ruido_total > umbral_pob: supera_umbral = True
    else:
        for f in focos:
            if f["emision"] <= 0: continue
            iso_coords_limite = generar_isofona_con_sombra(f["coords"][1], f["coords"][0], f["emision"], umbral_pob, pantallas_json, focos_json)
            if len(iso_coords_limite) >= 3:
                iso_poly = ShapelyPolygon([(lon, lat) for lat, lon in iso_coords_limite])
                if not iso_poly.is_valid: iso_poly = iso_poly.buffer(0)
                if shapely_poly.intersects(iso_poly):
                    supera_umbral = True
                    break
    if supera_umbral:
        color_pob, html = "red", f'<div style="{css_texto} text-align: center;">{nombre}<br><span style="color: #ffcccc; font-size: 11px;">(Incumple {umbral_pob}dB)</span></div>'
    else:
        color_pob, html = "green", f'<div style="{css_texto} text-align: center;">{nombre}<br><span style="color: #ccffcc; font-size: 11px;">({ruido_total:.1f} dB / {umbral_pob} dB)</span></div>'
    folium.Polygon(locations=[[lat, lon] for lon, lat in poly_coords], color=color_pob, fill=True, fill_opacity=0.4, weight=2).add_to(fg_poblaciones)
    if nombre: folium.Marker([c_lat, c_lon], icon=folium.DivIcon(html=html, icon_size=(250, 60), icon_anchor=(125, 30))).add_to(fg_poblaciones)

for p in pantallas_data:
    pant_coord = p["coords"]
    nombre, aten = p["name"], p["aten"]
    texto_hover = f"〰️ Pantalla Acústica: {nombre} | Reducción: -{aten:.1f} dB"
    folium.PolyLine(locations=[[lat, lon] for lon, lat in pant_coord], color="black", weight=12, opacity=1.0, tooltip=texto_hover).add_to(fg_pantallas)
    folium.PolyLine(locations=[[lat, lon] for lon, lat in pant_coord], color="#00FFFF", weight=6, opacity=1.0, popup=f"{nombre}: {aten} dB", tooltip=texto_hover).add_to(fg_pantallas)
    if nombre:
        folium.Marker([pant_coord[len(pant_coord)//2][1], pant_coord[len(pant_coord)//2][0]], icon=folium.DivIcon(html=f'<div style="{css_texto} text-align: center;">{nombre}<br>({aten:.1f} dB)</div>', icon_size=(150, 30), icon_anchor=(75, -10))).add_to(fg_pantallas)

for f in focos:
    lon, lat = f["coords"]
    nombre, emision_foco = f["name"], f["emision"]
    folium.Marker([lat, lon], icon=folium.Icon(color="black", icon="cog"), tooltip=f"📍 Foco Emisor: {nombre} | Potencia: {emision_foco:.1f} dB").add_to(fg_focos)
    if nombre:
        folium.Marker([lat, lon], icon=folium.DivIcon(html=f'<div style="{css_texto}">{nombre}<br>({emision_foco:.1f} dB)</div>', icon_size=(200, 40), icon_anchor=(-15, 20))).add_to(fg_focos)

Draw(
    export=False, 
    draw_options={'polyline': True, 'polygon': True, 'marker': True, 'circle': False, 'rectangle': False},
    edit_options={'edit': False, 'remove': False}
).add_to(m)
folium.LayerControl(position="topright", collapsed=True).add_to(m)

leyendas_html = """
{% macro html(this, kwargs) %}
<div style="position: absolute; bottom: 20px; left: 20px; z-index: 9999; background: rgba(255, 255, 255, 0.95); padding: 10px 15px; border: 1px solid rgba(0,0,0,0.1); border-radius: 10px; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 13px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); backdrop-filter: blur(4px); pointer-events: none; display: flex; flex-direction: row; align-items: center; gap: 15px; box-sizing: border-box;">
    <div style="font-weight: 700; color: #333; border-right: 2px solid #eee; padding-right: 12px;">🛠️ Herramientas</div>
    <div style="color: #444;">〰️ <b>Línea:</b> Pantalla</div>
    <div style="color: #444;">⬟ <b>Polígono:</b> Población</div>
    <div style="color: #444;">📍 <b>Marcador:</b> Foco</div>
</div>
<div style="position: absolute; bottom: 30px; right: 20px; z-index: 9999; background: rgba(255, 255, 255, 0.95); padding: 12px; border: 1px solid rgba(0,0,0,0.1); border-radius: 10px; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); backdrop-filter: blur(4px); pointer-events: none; max-width: 150px; box-sizing: border-box; overflow: hidden;">
    <div style="font-weight: 700; margin-bottom: 8px; text-align: center; color: #333; border-bottom: 1px solid #eee; padding-bottom: 5px;">Niveles (dB)</div>
    <div style="display: flex; align-items: center; margin-bottom: 4px; color: #444;"><div style="width: 14px; height: 14px; border-radius: 3px; background: #00FF00; margin-right: 8px; border: 1px solid rgba(0,0,0,0.1);"></div>30 - 35</div>
    <div style="display: flex; align-items: center; margin-bottom: 4px; color: #444;"><div style="width: 14px; height: 14px; border-radius: 3px; background: #66B24D; margin-right: 8px; border: 1px solid rgba(0,0,0,0.1);"></div>35 - 40</div>
    <div style="display: flex; align-items: center; margin-bottom: 4px; color: #444;"><div style="width: 14px; height: 14px; border-radius: 3px; background: #99CC33; margin-right: 8px; border: 1px solid rgba(0,0,0,0.1);"></div>40 - 45</div>
    <div style="display: flex; align-items: center; margin-bottom: 4px; color: #444;"><div style="width: 14px; height: 14px; border-radius: 3px; background: #D8F2A0; margin-right: 8px; border: 1px solid rgba(0,0,0,0.1);"></div>45 - 50</div>
    <div style="display: flex; align-items: center; margin-bottom: 4px; color: #444;"><div style="width: 14px; height: 14px; border-radius: 3px; background: #FFFF00; margin-right: 8px; border: 1px solid rgba(0,0,0,0.1);"></div>50 - 55</div>
    <div style="display: flex; align-items: center; margin-bottom: 4px; color: #444;"><div style="width: 14px; height: 14px; border-radius: 3px; background: #FFE6AA; margin-right: 8px; border: 1px solid rgba(0,0,0,0.1);"></div>55 - 60</div>
    <div style="display: flex; align-items: center; margin-bottom: 4px; color: #444;"><div style="width: 14px; height: 14px; border-radius: 3px; background: #FFAA33; margin-right: 8px; border: 1px solid rgba(0,0,0,0.1);"></div>60 - 65</div>
    <div style="display: flex; align-items: center; margin-bottom: 4px; color: #444;"><div style="width: 14px; height: 14px; border-radius: 3px; background: #FF3333; margin-right: 8px; border: 1px solid rgba(0,0,0,0.1);"></div>65 - 70</div>
    <div style="display: flex; align-items: center; margin-bottom: 4px; color: #444;"><div style="width: 14px; height: 14px; border-radius: 3px; background: #CC3333; margin-right: 8px; border: 1px solid rgba(0,0,0,0.1);"></div>70 - 75</div>
    <div style="display: flex; align-items: center; margin-bottom: 4px; color: #444;"><div style="width: 14px; height: 14px; border-radius: 3px; background: #FF00FF; margin-right: 8px; border: 1px solid rgba(0,0,0,0.1);"></div>75 - 80</div>
    <div style="display: flex; align-items: center; color: #444;"><div style="width: 14px; height: 14px; border-radius: 3px; background: #295180; margin-right: 8px; border: 1px solid rgba(0,0,0,0.1);"></div>&gt; 80</div>
</div>
{% endmacro %}
"""
macro = MacroElement()
macro._template = Template(leyendas_html)
m.get_root().add_child(macro)

map_output = st_folium(
    m,
    width=1200,
    height=650,
    use_container_width=True,
    key=map_key_actual,
    returned_objects=["last_active_drawing"],
    return_on_hover=False
)

if map_output and map_output.get("last_active_drawing"):
    nuevo_dibujo = map_output["last_active_drawing"]
    geom_nueva_str = json.dumps(nuevo_dibujo.get("geometry"), sort_keys=True)
    ya_existe = any(json.dumps(d.get("geometry"), sort_keys=True) == geom_nueva_str for d in st.session_state["mis_dibujos"])
    if not ya_existe:
        st.session_state["mis_dibujos"].append(nuevo_dibujo)
        st.rerun()
