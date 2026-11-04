import streamlit as st
import folium
from folium.plugins import Draw, Fullscreen, MeasureControl, Geocoder
from streamlit_folium import st_folium
import math
import zipfile
import io
import json
import re
import pandas as pd
import requests
from branca.element import Template, MacroElement
from shapely.geometry import Point, LineString, Polygon as ShapelyPolygon
from shapely.ops import unary_union
from datetime import datetime

st.set_page_config(page_title="Visor Ambiental Integral", layout="wide")

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
            <div style="width: 22px; height: 22px; background-color: #0093D0;"></div>
        </div>
        <div style="color: var(--text-color); font-size: 28px; font-weight: 900; line-height: 1; letter-spacing: -1px;">COMSA</div>
        <div style="color: var(--text-color); opacity: 0.8; font-size: 11px; font-weight: 600; letter-spacing: 0.5px;">CORPORACIÓN</div>
    </div>
    <div style="border-left: 2px solid var(--border-color); padding-left: 30px;">
        <h1 style="color: var(--text-color); margin: 0; font-size: 2.2rem; font-weight: 800; letter-spacing: -0.5px;">Visor Integral de Impacto Ambiental</h1>
    </div>
</div>
""", unsafe_allow_html=True)

def safe_serialize(obj):
    if hasattr(obj, 'coords'): return list(obj.coords)
    return str(obj)

if "mis_dibujos" not in st.session_state: st.session_state["mis_dibujos"] = []
if "capas_fondo" not in st.session_state: st.session_state["capas_fondo"] = []
if "map_version" not in st.session_state: st.session_state["map_version"] = 0
if "map_center" not in st.session_state: st.session_state["map_center"] = [40.4410, -3.6908]
if "map_zoom" not in st.session_state: st.session_state["map_zoom"] = 15

# ==========================================
# BASE DE DATOS E INICIALIZACIÓN
# ==========================================
malla_fina_config = [
    {"min": 30, "color": "#00FF00"}, {"min": 35, "color": "#66B24D"},
    {"min": 40, "color": "#99CC33"}, {"min": 45, "color": "#D8F2A0"},
    {"min": 50, "color": "#FFFF00"}, {"min": 55, "color": "#FFE6AA"},
    {"min": 60, "color": "#FFAA33"}, {"min": 65, "color": "#FF3333"},
    {"min": 70, "color": "#CC3333"}, {"min": 75, "color": "#FF00FF"},
    {"min": 80, "color": "#295180"}
]

actividades_polvo = {
    "Desbroce y limpieza del terreno": {"metodo": "factor_fijo", "base_g_s": 1.20, "red_humedad": 0.50, "H": 0.5},
    "Demolición mecánica de estructuras": {"metodo": "factor_fijo", "base_g_s": 1.20, "red_humedad": 0.50, "H": 3.0},
    "Fresado de pavimentos / Asfalto": {"metodo": "factor_fijo", "base_g_s": 0.95, "red_humedad": 0.50, "H": 0.2},
    "Voladuras (Explosivos)": {"metodo": "factor_fijo", "base_g_s": 8.00, "red_humedad": 0.50, "H": 5.0},
    "Perforación de pilotes / micropilotes": {"metodo": "factor_fijo", "base_g_s": 0.60, "red_humedad": 0.50, "H": 0.5},
    "Desmonte pesado (Bulldozer)": {"metodo": "factor_fijo", "base_g_s": 1.50, "red_humedad": 0.50, "H": 1.0},
    "Nivelación de plataformas (Motoniveladora)": {"metodo": "factor_fijo", "base_g_s": 0.85, "red_humedad": 0.50, "H": 1.0},
    "Excavación y carga de tierras (Retro)": {"metodo": "formula_caida", "k": 0.35, "M_seco": 2.0, "M_humedo": 8.0, "H": 2.0},
    "Descarga de camiones (acopios)": {"metodo": "formula_caida", "k": 0.35, "M_seco": 2.0, "M_humedo": 8.0, "H": 1.5},
    "Compactación de tierras y subbases": {"metodo": "factor_fijo", "base_g_s": 1.10, "red_humedad": 0.50, "H": 0.5},
    "Tránsito pesado por pistas de tierra": {"metodo": "factor_fijo", "base_g_s": 2.80, "red_humedad": 0.50, "H": 0.5},
    "Tránsito ligero por pistas de tierra": {"metodo": "factor_fijo", "base_g_s": 0.80, "red_humedad": 0.50, "H": 0.5},
    "Resuspensión en vías públicas pavimentadas": {"metodo": "factor_fijo", "base_g_s": 0.40, "red_humedad": 0.50, "H": 0.5},
    "Corte de pavimentos / Hormigón": {"metodo": "factor_fijo", "base_g_s": 0.50, "red_humedad": 0.50, "H": 0.5},
    "Chorro de arena (Sandblasting)": {"metodo": "factor_fijo", "base_g_s": 1.80, "red_humedad": 0.50, "H": 2.0},
    "Cribado y machaqueo de áridos": {"metodo": "factor_fijo", "base_g_s": 3.50, "red_humedad": 0.50, "H": 2.5},
    "Descarga de balasto (Vagón/Tolva)": {"metodo": "formula_caida", "k": 0.35, "M_seco": 1.0, "M_humedo": 4.0, "H": 1.5},
    "Bateo y perfilado de vías ferroviarias": {"metodo": "factor_fijo", "base_g_s": 1.60, "red_humedad": 0.50, "H": 0.5}
}

opciones_medidas = [
    "💧 Riego periódico de tierras y acopios (-50% emisión)",
    "🚷 Control de velocidad a 30 km/h en zona de obra (-40% resuspensión en tránsito)",
    "🚚 Transporte de material tapado y sin derrames (-30% en descargas)",
    "💨 Equipos de perforación con captadores de polvo (-85% en perforación)",
    "🚿 Lavado de ruedas a la salida (-80% resuspensión en vías públicas)"
]

@st.cache_data(ttl=900)
def obtener_clima_actual_api(lat, lon):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        r = requests.get(url, timeout=3).json()
        u = r["current_weather"]["windspeed"] / 3.6 
        d = r["current_weather"]["winddirection"]
        return float(u), float(d)
    except:
        return 3.5, 270.0 

@st.cache_data(ttl=3600, show_spinner=False)
def obtener_elevaciones(lats, lons):
    try:
        url = f"https://api.open-meteo.com/v1/elevation?latitude={','.join(map(str, lats))}&longitude={','.join(map(str, lons))}"
        r = requests.get(url, timeout=5).json()
        return r.get("elevation", [0.0]*len(lats))
    except:
        return [0.0]*len(lats)

def generar_perfil_radial(lat, lon, radius=100):
    lats, lons = [], []
    for angle in range(0, 360, 10): 
        rad = math.radians(angle)
        d_lat = math.degrees(radius * math.cos(rad) / 6378137.0)
        d_lon = math.degrees(radius * math.sin(rad) / (6378137.0 * math.cos(math.radians(lat))))
        lats.append(lat + d_lat)
        lons.append(lon + d_lon)
    return obtener_elevaciones(lats, lons)

@st.cache_data
def cargar_maquinas():
    try: return pd.read_csv("maquinaria.csv")
    except: return pd.DataFrame({"Nombre_Maquina": ["Máquina Genérica"], "dB_1m": [90.0]})

df_maq = cargar_maquinas()
lista_maquinas = df_maq['Nombre_Maquina'].tolist()
if "🚜 Lote Movimiento Tierras (Excav. + Transporte)" not in lista_maquinas:
    lista_maquinas.insert(0, "🚜 Lote Movimiento Tierras (Excav. + Transporte)")
lista_maquinas.append("➕ Otra (Manual)")

for idx, feature in enumerate(st.session_state["mis_dibujos"]):
    tipo = feature["geometry"]["type"]
    if "properties" not in feature: feature["properties"] = {}
    if "name" not in feature["properties"]:
        prefix = "Foco" if tipo == "Point" else "Pantalla" if tipo == "LineString" else "Polígono"
        feature["properties"]["name"] = f"{prefix} {idx+1}"
        
    if "cota" not in feature["properties"]: feature["properties"]["cota"] = 0.0
    if "altura_maq" not in feature["properties"]: feature["properties"]["altura_maq"] = 2.0
    if "h_dia" not in feature["properties"]: feature["properties"]["h_dia"] = 12.0
    if "h_noche" not in feature["properties"]: feature["properties"]["h_noche"] = 0.0
    if "h_total" not in feature["properties"]: feature["properties"]["h_total"] = 8.0
    
    if "perfil_radial" not in feature["properties"] or len(feature["properties"]["perfil_radial"]) != 36: 
        feature["properties"]["perfil_radial"] = [feature["properties"].get("cota", 0.0)] * 36
    
    if tipo == "Point" and "maq" not in feature["properties"]: feature["properties"]["maq"] = {}
    if tipo == "LineString" and "aten" not in feature["properties"]: feature["properties"]["aten"] = 15.0
    
    if tipo == "Polygon":
        if "tipo_poligono" not in feature["properties"]: feature["properties"]["tipo_poligono"] = "🏠 Población / Receptor"
        if "umbral" not in feature["properties"]: feature["properties"]["umbral"] = 65.0
        if "uso_nombre" not in feature["properties"]: feature["properties"]["uso_nombre"] = "Residencial"
        if "altura_edif" not in feature["properties"]: feature["properties"]["altura_edif"] = 10.0
        if "mostrar_poligono" not in feature["properties"]: feature["properties"]["mostrar_poligono"] = True
        if "color_poligono" not in feature["properties"]: 
            feature["properties"]["color_poligono"] = "#7f00ff" if feature["properties"]["tipo_poligono"] == "🏠 Población / Receptor" else "#555555"
        
    if tipo == "Point":
        if "actividades_polvo" not in feature["properties"]: feature["properties"]["actividades_polvo"] = ["Excavación y carga de tierras (Retro)"]
        if "medidas_polvo" not in feature["properties"]: feature["properties"]["medidas_polvo"] = []

# ==========================================
# FUNCIONES MATEMÁTICAS (RUIDO Y POLVO)
# ==========================================
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

def get_bearing(lat1, lon1, lat2, lon2):
    dLon = math.radians(lon2 - lon1)
    lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
    y = math.sin(dLon) * math.cos(lat2_rad)
    x = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dLon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

def parsear_kml_a_dibujos(kml_texto):
    dibujos = []
    try:
        placemarks = re.findall(r'<Placemark.*?>(.*?)</Placemark>', kml_texto, re.DOTALL | re.IGNORECASE)
        for pm in placemarks:
            nombre = "Elemento KML"
            nm = re.search(r'<name>(.*?)</name>', pm, re.DOTALL | re.IGNORECASE)
            if nm: nombre = nm.group(1).strip()
            
            pt = re.search(r'<Point.*?>.*?<coordinates>\s*(.*?)\s*</coordinates>', pm, re.DOTALL | re.IGNORECASE)
            if pt:
                coords = pt.group(1).strip().replace('\n', ' ').replace('\t', ' ').split(',')
                if len(coords) >= 2:
                    dibujos.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(coords[0].strip()), float(coords[1].strip())]}, "properties": {"name": nombre}})
                    continue
                    
            ls = re.search(r'<LineString.*?>.*?<coordinates>\s*(.*?)\s*</coordinates>', pm, re.DOTALL | re.IGNORECASE)
            if ls:
                c_str = ls.group(1).strip().replace('\n', ' ').replace('\t', ' ')
                pares = c_str.split()
                c_list = [[float(p.split(',')[0]), float(p.split(',')[1])] for p in pares if len(p.split(',')) >= 2]
                if c_list:
                    dibujos.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": c_list}, "properties": {"name": nombre}})
                    continue
                    
            poly = re.search(r'<Polygon.*?>.*?<coordinates>\s*(.*?)\s*</coordinates>', pm, re.DOTALL | re.IGNORECASE)
            if poly:
                c_str = poly.group(1).strip().replace('\n', ' ').replace('\t', ' ')
                pares = c_str.split()
                c_list = [[float(p.split(',')[0]), float(p.split(',')[1])] for p in pares if len(p.split(',')) >= 2]
                if c_list:
                    dibujos.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [c_list]}, "properties": {"name": nombre}})
                    
    except Exception as e:
        st.error(f"Error procesando KML: {e}")
        
    for d in dibujos:
        if "properties" not in d: d["properties"] = {}
        if d["geometry"]["type"] == "Point":
            d["properties"].update({"maq": {}, "actividades_polvo": ["Excavación y carga de tierras (Retro)"], "medidas_polvo": [], "cota": 0.0, "altura_maq": 2.0, "h_dia": 12.0, "h_noche": 0.0, "h_total": 8.0, "perfil_radial": [0.0]*36})
        elif d["geometry"]["type"] == "LineString":
            d["properties"].update({"aten": 15.0})
        elif d["geometry"]["type"] == "Polygon":
            d["properties"].update({"umbral": 65.0, "uso_nombre": "Residencial", "cota": 0.0, "tipo_poligono": "🏠 Población / Receptor", "altura_edif": 10.0, "mostrar_poligono": True, "color_poligono": "#7f00ff"})
    return dibujos

@st.cache_data(show_spinner=False)
def generar_isofona_con_sombra(foco_lat, foco_lon, emision_foco, umbral_banda, pantallas_data_json, edificios_data_json, veg_frondosa_json, veg_media_json, focos_all_json, f_cota=0.0, f_altura_maq=2.0, radial_foco=None, r_earth=6378137.0):
    pantallas_data = json.loads(pantallas_data_json)
    edificios_data = json.loads(edificios_data_json)
    veg_frondosa_data = json.loads(veg_frondosa_json)
    veg_media_data = json.loads(veg_media_json)
    focos_all = json.loads(focos_all_json)
    if radial_foco is None or len(radial_foco) != 36: radial_foco = [f_cota]*36
    
    foco_pt = Point(foco_lon, foco_lat)
    emision_total_all = 10 * math.log10(sum(10**(f["emision"]/10) for f in focos_all)) if focos_all else emision_foco
    r_max_posible = calcular_radio(emision_total_all, umbral_banda, 0)
    
    radios_brutos = []
    
    edif_polys = [{"poly": ShapelyPolygon(e["coords"]), "h_max": e["cota"] + e["altura"]} for e in edificios_data if len(e["coords"]) >= 3]
    veg_f_polys = [ShapelyPolygon(p["coords"]) for p in veg_frondosa_data if len(p["coords"]) >= 3]
    veg_m_polys = [ShapelyPolygon(p["coords"]) for p in veg_media_data if len(p["coords"]) >= 3]
    
    for angle in range(360):
        rad = math.radians(angle)
        
        idx1 = int(angle // 10) % 36
        idx2 = (idx1 + 1) % 36
        w = (angle % 10) / 10.0
        cota_terreno_angulo = radial_foco[idx1] * (1.0 - w) + radial_foco[idx2] * w
        
        dif_topo = cota_terreno_angulo - (f_cota + f_altura_maq)
        aten_topo_base = min(10.0, dif_topo * 0.75) if dif_topo > 0 else 0.0
        radio_base = calcular_radio(emision_foco, umbral_banda, aten_topo_base)
        
        if radio_base <= 0:
            radios_brutos.append(0.0)
            continue
            
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
                    dist_2d = distancia_haversine(f["coords"][1], f["coords"][0], foco_lat + d_lat, foco_lon + d_lon)
                    dist_3d = math.sqrt(dist_2d**2 + f.get("altura_maq", 2.0)**2)
                    
                    b_angle = get_bearing(f["coords"][1], f["coords"][0], foco_lat + d_lat, foco_lon + d_lon)
                    f_radial = f.get("perfil_radial", [f.get("cota",0.0)]*36)
                    if len(f_radial) != 36: f_radial = [f.get("cota",0.0)]*36
                    
                    idx_f1 = int(b_angle // 10) % 36
                    idx_f2 = (idx_f1 + 1) % 36
                    wf = (b_angle % 10) / 10.0
                    c_terr = f_radial[idx_f1] * (1 - wf) + f_radial[idx_f2] * wf
                    
                    d_top = c_terr - (f.get("cota", 0.0) + f.get("altura_maq", 2.0))
                    at_t = min(10.0, d_top * 0.75) if d_top > 0 else 0.0
                    
                    val = f["emision"] - 20 * math.log10(dist_3d) - at_t if dist_3d > 1 else f["emision"] - at_t
                    ruidos_pto.append(val)
                tot = 10 * math.log10(sum(10**(x/10) for x in ruidos_pto)) if ruidos_pto else 0
                if tot >= umbral_banda: low = mid
                else: high = mid
            r_max_libre = low
            
        radio_final = r_max_libre
        d_lon_temp = math.degrees(r_max_libre * math.cos(rad) / (r_earth * math.cos(math.radians(foco_lat))))
        d_lat_temp = math.degrees(r_max_libre * math.sin(rad) / r_earth)
        rayo = LineString([foco_pt, Point(foco_lon + d_lon_temp, foco_lat + d_lat_temp)])
        
        # 1. Absorción Vegetación Frondosa (-0.15 dB/m)
        for vf in veg_f_polys:
            if rayo.intersects(vf):
                try:
                    inter_len = rayo.intersection(vf).length * 111320.0
                    radio_aten = r_max_libre * (10 ** (-(inter_len * 0.15) / 20))
                    radio_final = min(radio_final, r_max_libre - (r_max_libre - radio_aten)*0.8)
                except: pass
                
        # 2. Absorción Vegetación Media (-0.05 dB/m)
        for vm in veg_m_polys:
            if rayo.intersects(vm):
                try:
                    inter_len = rayo.intersection(vm).length * 111320.0
                    radio_aten = r_max_libre * (10 ** (-(inter_len * 0.05) / 20))
                    radio_final = min(radio_final, r_max_libre - (r_max_libre - radio_aten)*0.8)
                except: pass

        # 3. Difracción de pantallas
        for p in pantallas_data:
            pantalla_line = LineString(p["coords"])
            if rayo.intersects(pantalla_line):
                try:
                    interseccion = rayo.intersection(pantalla_line)
                    pt_int = interseccion if interseccion.geom_type == 'Point' else interseccion.geoms[0]
                    d_muro = distancia_haversine(foco_lat, foco_lon, pt_int.y, pt_int.x)
                    radio_aten = r_max_libre * (10 ** (-p["aten"] / 20))
                    radio_final = min(radio_final, d_muro + (radio_aten - d_muro) if radio_aten > d_muro else d_muro)
                except: pass
                
        # 4. Difracción Edificios 3D
        for edif in edif_polys:
            if rayo.intersects(edif["poly"]):
                if edif["h_max"] > (f_cota + f_altura_maq):
                    try:
                        interseccion = rayo.intersection(edif["poly"])
                        if interseccion.geom_type == 'Point': pt_int = interseccion
                        elif interseccion.geom_type == 'MultiPoint': pt_int = interseccion.geoms[0]
                        elif interseccion.geom_type == 'LineString': pt_int = Point(interseccion.coords[0])
                        else: pt_int = edif["poly"].centroid
                        
                        d_edif = distancia_haversine(foco_lat, foco_lon, pt_int.y, pt_int.x)
                        radio_aten = r_max_libre * (10 ** (-15.0 / 20)) 
                        radio_final = min(radio_final, d_edif + (radio_aten - d_edif) if radio_aten > d_edif else d_edif)
                    except: pass

        radios_brutos.append(radio_final)
        
    # --- FILTRO ORGÁNICO --- 
    # Mantiene las isófonas fluidas al esquivar obstáculos
    ventana = 21 
    coords = []
    for i in range(360):
        suma_radios = 0.0
        for j in range(i - ventana//2, i + ventana//2 + 1):
            suma_radios += radios_brutos[j % 360]
        r_suave = suma_radios / ventana
        
        if r_suave <= 0: r_suave = 0.1
        rad = math.radians(i)
        d_lon_final = math.degrees(r_suave * math.cos(rad) / (r_earth * math.cos(math.radians(foco_lat))))
        d_lat_final = math.degrees(r_suave * math.sin(rad) / r_earth)
        coords.append([foco_lat + d_lat_final, foco_lon + d_lon_final])
        
    if coords: coords.append(coords[0])
    return coords

def calcular_emision_polvo_lista(actividades, medidas, u_viento):
    q_total = 0.0
    h_max = 0.5
    aplica_riego = any("Riego" in m for m in medidas)
    aplica_velocidad = any("velocidad" in m for m in medidas)
    aplica_tapado = any("tapado" in m for m in medidas)
    aplica_captador = any("captadores" in m for m in medidas)
    aplica_lavarruedas = any("Lavado" in m for m in medidas)

    for act in actividades:
        datos = actividades_polvo.get(act, actividades_polvo["Excavación y carga de tierras (Retro)"])
        if datos["metodo"] == "factor_fijo":
            q = datos["base_g_s"]
            if aplica_riego: q = q * datos["red_humedad"]
            if "Tránsito" in act:
                if aplica_velocidad: q = q * 0.60 
                if aplica_lavarruedas and "públicas" in act: q = q * 0.20
            if "Perforación" in act and aplica_captador: q = q * 0.15
        elif datos["metodo"] == "formula_caida":
            M = datos["M_humedo"] if aplica_riego else datos["M_seco"]
            k = datos["k"]
            q = k * 0.0016 * ((max(u_viento, 0.5) / 2.2)**1.3) / ((M / 2.0)**1.4)
            if "Descarga" in act and aplica_tapado: q = q * 0.70
            
        h = datos["H"]
        q_total += q
        h_max = max(h_max, h)
    return q_total, h_max

def calcular_concentracion_total_punto(lat_dest, lon_dest, focos_aire, u_viento, dir_viento_desde, cota_dest=0.0):
    concentracion = 0.0
    for f in focos_aire:
        Q, H_base = f["Q"], f["H"]
        if Q <= 0: continue
        
        dist = distancia_haversine(f["lat"], f["lon"], lat_dest, lon_dest)
        if dist < 1.0 or dist > 10000.0: continue 
        
        bearing = get_bearing(f["lat"], f["lon"], lat_dest, lon_dest)
        dir_pluma = (dir_viento_desde + 180) % 360
        angulo_relativo = math.radians(bearing - dir_pluma)
        
        dx = dist * math.cos(angulo_relativo)
        dy = dist * math.sin(angulo_relativo)
        
        sigma_y0 = 15.0 
        sigma_z0 = 5.0
        
        if dx > 0: 
            sigma_y = sigma_y0 + 0.35 * dx * (1 + 0.0001 * dx)**(-0.5)
            sigma_z = sigma_z0 + 0.08 * dx * (1 + 0.0015 * dx)**(-0.5)
            decay_x = 1.0
        else: 
            if dx < -150: continue 
            sigma_y = sigma_y0 + 0.25 * abs(dx) 
            sigma_z = sigma_z0
            decay_x = math.exp(-(dx**2) / (2 * 40.0**2)) 
        
        z_eff = 1.5
        
        f_radial = f.get("perfil_radial", [f.get("cota",0.0)]*36)
        if len(f_radial) != 36: f_radial = [f.get("cota",0.0)]*36
        
        idx1 = int(bearing // 10) % 36
        idx2 = (idx1 + 1) % 36
        w = (bearing % 10) / 10.0
        cota_terreno_medio = f_radial[idx1] * (1 - w) + f_radial[idx2] * w
        
        H_eff = max(0.0, H_base + f.get("cota", 0.0) + f.get("altura_maq", 2.0) - cota_dest)
        
        term_central = Q / (2 * math.pi * max(u_viento, 0.5) * sigma_y * sigma_z)
        disp_horiz = math.exp(-(dy**2) / (2 * sigma_y**2))
        disp_vert = math.exp(-((z_eff - H_eff)**2) / (2 * sigma_z**2)) + math.exp(-((z_eff + H_eff)**2) / (2 * sigma_z**2))
        
        concentracion += (term_central * disp_horiz * disp_vert * decay_x) * 1000000
    return concentracion

def hex_to_kml_color(hex_color, alpha="80"):
    colores_basicos = {"green": "008000", "orange": "FFA500", "red": "FF0000", "black": "000000", "blue": "0000FF", "white": "FFFFFF"}
    hex_clean = colores_basicos.get(hex_color.lower(), hex_color.replace("#", ""))
    if len(hex_clean) == 6:
        r, g, b = hex_clean[0:2], hex_clean[2:4], hex_clean[4:6]
        return f"{alpha}{b}{g}{r}"
    return f"{alpha}ffffff"

def generar_kmz(focos_list, pantallas_list, poblaciones_list, isofonas_list, modo="ruido", polvo_grid=None, viento_u=0, viento_dir=0):
    kml = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2">', '<Document>', '<name>Resultados Visor Ambiental COMSA</name>']
    if modo == "ruido":
        if isofonas_list:
            kml.append('<Folder><name>Mapas de Ondas de Ruido</name>')
            for iso in isofonas_list:
                kml_color = hex_to_kml_color(iso["color"], alpha="80")
                kml.append('<Placemark>')
                kml.append(f'<name>{iso["name"]}</name>')
                kml.append(f'<Style><PolyStyle><color>{kml_color}</color><fill>1</fill><outline>1</outline></PolyStyle><LineStyle><color>{kml_color}</color><width>1</width></LineStyle></Style>')
                kml.append('<Polygon><tessellate>1</tessellate><outerBoundaryIs><LinearRing><coordinates>')
                coord_str = " ".join([f"{lon},{lat},0" for lat, lon in iso["coords"]])
                coord_str += f" {iso['coords'][0][1]},{iso['coords'][0][0]},0"
                kml.append(coord_str)
                kml.append('</coordinates></LinearRing></outerBoundaryIs></Polygon>')
                kml.append('</Placemark>')
            kml.append('</Folder>')
    elif modo == "polvo":
        kml.append(f'<Placemark><name>Meteorología del Cálculo</name><description>Velocidad Viento: {viento_u:.1f} m/s\nSopla desde: {viento_dir:.0f}º\nPluma se dirige a: {(viento_dir+180)%360:.0f}º</description><Point><coordinates>{st.session_state["map_center"][1]},{st.session_state["map_center"][0]},0</coordinates></Point></Placemark>')
        if polvo_grid:
            kml.append('<Folder><name>Malla de Dispersión PM10 (RD 102/2011)</name>')
            for celda in polvo_grid:
                kml_color = hex_to_kml_color(celda["color"], alpha="99")
                b = celda["bounds"]
                lat1, lon1, lat2, lon2 = b[0][0], b[0][1], b[1][0], b[1][1]
                c_str = f"{lon1},{lat1},0 {lon2},{lat1},0 {lon2},{lat2},0 {lon1},{lat2},0 {lon1},{lat1},0"
                kml.append('<Placemark>')
                kml.append(f'<name>{celda["conc"]:.1f} ug/m3</name>')
                kml.append(f'<Style><PolyStyle><color>{kml_color}</color><fill>1</fill><outline>0</outline></PolyStyle></Style>')
                kml.append(f'<Polygon><tessellate>1</tessellate><outerBoundaryIs><LinearRing><coordinates>{c_str}</coordinates></LinearRing></outerBoundaryIs></Polygon>')
                kml.append('</Placemark>')
            kml.append('</Folder>')

    for f in focos_list:
        lon, lat = f.get("coords", [f.get("lon"), f.get("lat")])
        kml.append('<Placemark>')
        kml.append(f'<name>{f["name"]}</name>')
        if modo == "ruido": kml.append(f'<description>Foco Acústico\nEmisión: {f["emision"]:.1f} dB</description>')
        else: kml.append(f'<description>Foco Emisor de Polvo\nEmisión Total: {f.get("Q",0):.3f} g/s</description>')
        kml.append(f'<Point><coordinates>{lon},{lat},0</coordinates></Point>')
        kml.append('</Placemark>')
        
    for p in pantallas_list:
        kml.append('<Placemark>')
        kml.append(f'<name>{p["name"]}</name>')
        kml.append(f'<description>Pantalla Acústica\nAtenuación: {p["aten"]:.1f} dB</description>')
        kml.append('<Style><LineStyle><color>ffffff00</color><width>6</width></LineStyle></Style>')
        kml.append('<LineString><tessellate>1</tessellate><coordinates>')
        kml.append(" ".join([f"{lon},{lat},0" for lon, lat in p["coords"]]))
        kml.append('</coordinates></LineString>')
        kml.append('</Placemark>')
        
    for pob in poblaciones_list:
        kml.append('<Placemark>')
        kml.append(f'<name>{pob["name"]}</name>')
        kml.append(f'<description>Núcleo Receptor | Umbral: {pob.get("umbral", 65.0)}</description>')
        kml.append('<Style><PolyStyle><color>7f00ff00</color><fill>1</fill><outline>1</outline></PolyStyle><LineStyle><color>ff00ff00</color><width>2</width></LineStyle></Style>')
        kml.append('<Polygon><tessellate>1</tessellate><outerBoundaryIs><LinearRing><coordinates>')
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

    modo_visor = st.radio("TIPO DE ANÁLISIS AMBIENTAL:", ["🔊 Vectores de Ruido", "💨 Calidad del Aire (Polvo PM10)"], index=0)
    st.write("---")
    
    st.markdown("**📊 CONFIGURACIÓN DE ESCENARIO**")
    escenario_visualizacion = st.radio("MODO DE VISUALIZACIÓN / NORMATIVA:", ["🔴 Impacto Máximo (Pico instantáneo)", "🔵 Normativo Medio (Ld/Ln / 24h)"], index=0)
    periodo_normativo = "Día"
    if escenario_visualizacion == "🔵 Normativo Medio (Ld/Ln / 24h)":
        if modo_visor == "🔊 Vectores de Ruido":
            periodo_normativo = st.radio("Periodo a evaluar:", ["☀️ Día (Ld) - Ref. 12h", "🌙 Noche (Ln) - Ref. 8h"])
        else:
            st.caption("Se evaluará la media diaria (24h) aplicable al RD 102/2011.")
    st.write("---")

    with st.expander("💾 Gestión de Proyectos", expanded=False):
        if st.session_state["mis_dibujos"]:
            json_proyecto = json.dumps(st.session_state["mis_dibujos"], indent=2, default=safe_serialize)
            st.download_button("💾 Guardar Proyecto (.json)", data=json_proyecto, file_name="proyecto_ambiental.json", mime="application/json", use_container_width=True)
        st.write("---")
        archivo_cargado = st.file_uploader("📂 Importar Proyecto (.json, .kmz, .kml)", type=["json", "kmz", "kml"])
        if archivo_cargado is not None:
            nombre_arch = archivo_cargado.name.lower()
            if nombre_arch.endswith('.json'):
                try:
                    datos = json.load(archivo_cargado)
                    if st.button("Aplicar JSON Cargado", use_container_width=True):
                        st.session_state["mis_dibujos"] = datos
                        st.session_state["map_version"] += 1
                        st.rerun()
                except Exception as e: st.error(f"Error al leer JSON: {e}")
            elif nombre_arch.endswith('.kmz') or nombre_arch.endswith('.kml'):
                try:
                    file_bytes = archivo_cargado.getvalue()
                    kml_texto = ""
                    try:
                        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                            kml_internos = [f for f in zf.namelist() if f.lower().endswith('.kml')]
                            if kml_internos: kml_texto = zf.read(kml_internos[0]).decode('utf-8', errors='ignore')
                    except zipfile.BadZipFile: kml_texto = file_bytes.decode('utf-8', errors='ignore')
                    
                    if kml_texto:
                        dibujos_kml = parsear_kml_a_dibujos(kml_texto)
                        if dibujos_kml:
                            st.success(f"Detectados {len(dibujos_kml)} elementos.")
                            if st.button("Aplicar Archivo Cargado", use_container_width=True):
                                try:
                                    lats, lons = [], []
                                    for d in dibujos_kml:
                                        c = d["geometry"]["coordinates"]
                                        if d["geometry"]["type"] == "Point": lats.append(c[1]); lons.append(c[0])
                                        elif d["geometry"]["type"] == "Polygon": lats.append(c[0][0][1]); lons.append(c[0][0][0])
                                    
                                    elevs = obtener_elevaciones(lats, lons) if lats else []
                                    elev_idx = 0
                                    for d in dibujos_kml:
                                        if d["geometry"]["type"] in ["Point", "Polygon"]:
                                            elev = elevs[elev_idx] if elev_idx < len(elevs) and elevs[elev_idx] is not None else 0.0
                                            d["properties"]["cota"] = elev
                                            if d["geometry"]["type"] == "Point":
                                                c = d["geometry"]["coordinates"]
                                                d["properties"]["perfil_radial"] = generar_perfil_radial(c[1], c[0], 100)
                                            elev_idx += 1
                                except: pass
                                        
                                st.session_state["mis_dibujos"] = dibujos_kml
                                if dibujos_kml[0]["geometry"]["coordinates"]:
                                    c = dibujos_kml[0]["geometry"]["coordinates"]
                                    if dibujos_kml[0]["geometry"]["type"] == "Point": st.session_state["map_center"] = [c[1], c[0]]
                                    else: st.session_state["map_center"] = [c[0][1], c[0][0]] if isinstance(c[0], list) else [c[1], c[0]]
                                st.session_state["map_version"] += 1
                                st.rerun()
                        else: st.warning("No se encontraron geometrías válidas.")
                    else: st.error("Archivo vacío.")
                except Exception as e: st.error(f"Error procesando el archivo: {e}")

    with st.expander("🗺️ Capa de Fondo (Ámbito de Obra)", expanded=False):
        st.caption("Sube un KML/KMZ puramente visual para ubicar la obra.")
        st.markdown("**🎨 Estilo de la Capa de Fondo**")
        col_color, col_grosor = st.columns(2)
        color_fondo = col_color.color_picker("Color", "#3388ff")
        grosor_fondo = col_grosor.slider("Grosor", 1, 10, 3)
        relleno_fondo = st.checkbox("🔲 Aplicar relleno (solo polígonos)", value=False)
        st.write("---")
        
        archivo_fondo = st.file_uploader("📂 Importar Ámbito (.kmz, .kml)", type=["kmz", "kml"], key="fondo_uploader")
        if archivo_fondo is not None:
            try:
                file_bytes = archivo_fondo.getvalue()
                kml_texto = ""
                try:
                    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                        kml_internos = [f for f in zf.namelist() if f.lower().endswith('.kml')]
                        if kml_internos: kml_texto = zf.read(kml_internos[0]).decode('utf-8', errors='ignore')
                except zipfile.BadZipFile: kml_texto = file_bytes.decode('utf-8', errors='ignore')
                
                if kml_texto:
                    dibujos_fondo = parsear_kml_a_dibujos(kml_texto)
                    if dibujos_fondo:
                        if st.button("🗺️ Cargar al Mapa como Fondo", use_container_width=True):
                            st.session_state["capas_fondo"].extend(dibujos_fondo)
                            st.session_state["map_version"] += 1
                            st.rerun()
            except Exception as e: st.error(f"Error procesando fondo: {e}")
            
        if st.session_state["capas_fondo"]:
            st.success(f"Cargados {len(st.session_state['capas_fondo'])} elementos de fondo.")
            if st.button("🗑️ Limpiar Capa de Fondo", use_container_width=True):
                st.session_state["capas_fondo"] = []
                st.session_state["map_version"] += 1
                st.rerun()

    with st.expander("📚 Leyendas Capas Oficiales (SIOSE / ADIF)", expanded=False):
        st.markdown("**Límites Legales de Ruido (España / ADIF):**")
        st.markdown("""
        <div style="font-size: 12px; font-family: 'Segoe UI', system-ui, sans-serif; line-height: 1.5;">
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: #E6004D; margin-right: 8px; border: 1px solid #ccc;"></div><b>Rojo oscuro:</b> Tejido urbano continuo (Residencial - 65 dB)</div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: #FF0000; margin-right: 8px; border: 1px solid #ccc;"></div><b>Rojo vivo:</b> Tejido urbano discontinuo (Residencial - 65 dB)</div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: #CC4DF2; margin-right: 8px; border: 1px solid #ccc;"></div><b>Morado:</b> Zonas industriales y comerciales (75 dB)</div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: #CC0066; margin-right: 8px; border: 1px solid #ccc;"></div><b>Granate:</b> Infraestructuras de Transporte / Ejes ADIF</div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: #FFA6FF; margin-right: 8px; border: 1px solid #ccc;"></div><b>Rosa:</b> Dotacional, sanitario, docente (60 dB)</div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: #A6FF80; margin-right: 8px; border: 1px solid #ccc;"></div><b>Verde Pistacho:</b> Zonas verdes y deportivas</div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: #E6CCCC; margin-right: 8px; border: 1px solid #ccc;"></div><b>Gris/Marrón:</b> Zonas en obras o extracción</div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: #FFFFA8; margin-right: 8px; border: 1px solid #ccc;"></div><b>Amarillo:</b> Tierras de cultivo y labor</div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;"><div style="min-width: 15px; height: 15px; background: #00CCF2; margin-right: 8px; border: 1px solid #ccc;"></div><b>Azul:</b> Cursos de agua y zonas húmedas</div>
        </div>
        """, unsafe_allow_html=True)

    if modo_visor == "🔊 Vectores de Ruido":
        with st.expander("📜 Fondo de Isófonas Global", expanded=True):
            tipo_malla = st.radio("Estilo de Visualización:", ["Malla Básica (Semáforo)", "Malla Fina (Intervalos 5dB)"])
            opacidad_malla_fina = st.slider("Opacidad de la Malla Fina:", min_value=0.1, max_value=1.0, value=0.4, step=0.1)
            activar_umbral_global = st.checkbox("Mostrar línea de límite común voluntaria", value=True)
            umbral_referencia = st.number_input("Umbral de Referencia / Límite Común (dB):", value=65.0, step=1.0)
    else:
        with st.expander("🌤️ Meteorología y Viento", expanded=True):
            origen_viento = st.radio("Origen de los datos meteorológicos:", ["📡 Tiempo Real (API Open-Meteo)", "🎛️ Manual (Deslizadores)"], index=0)
            if origen_viento == "📡 Tiempo Real (API Open-Meteo)":
                lat_api, lon_api = st.session_state["map_center"]
                u_real, dir_real = obtener_clima_actual_api(lat_api, lon_api)
                st.success(f"Datos obtenidos de Open-Meteo para las coordenadas del mapa.")
                viento_velocidad = st.number_input("Velocidad detectada (m/s):", value=u_real, disabled=True)
                viento_direccion = st.number_input("Dirección (º desde):", value=dir_real, disabled=True)
            else:
                viento_velocidad = st.slider("Velocidad del viento (u) en m/s:", min_value=0.5, max_value=15.0, value=3.5, step=0.5)
                viento_direccion = st.slider("El viento sopla DESDE (Dirección):", min_value=0, max_value=350, value=270, step=10, help="0=Norte, 90=Este, 180=Sur, 270=Oeste")
            st.caption(f"Dirección física de arrastre de la pluma: **{(viento_direccion + 180) % 360:.0f}º**")

    with st.expander("🏷️ Configuración de Elementos", expanded=True):
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
                
                if tipo in ["Point", "Polygon"]:
                    c1_topo, c2_topo = st.columns(2)
                    props["cota"] = c1_topo.number_input("Cota (m):", value=float(props.get("cota", 0.0)), step=1.0, key=f"cota_{idx}")
                    if tipo == "Point":
                        props["altura_maq"] = c2_topo.number_input("Alt. Foco (m):", value=float(props.get("altura_maq", 2.0)), step=0.5, key=f"alm_{idx}")
                        
                        if escenario_visualizacion == "🔵 Normativo Medio (Ld/Ln / 24h)":
                            st.markdown("**⏱️ Horas de Trabajo**")
                            if modo_visor == "🔊 Vectores de Ruido":
                                ch1, ch2 = st.columns(2)
                                props["h_dia"] = ch1.slider("Día (12h):", 0.0, 12.0, float(props.get("h_dia", 12.0)), 0.5, key=f"hd_{idx}")
                                props["h_noche"] = ch2.slider("Noche (8h):", 0.0, 8.0, float(props.get("h_noche", 0.0)), 0.5, key=f"hn_{idx}")
                            else:
                                props["h_total"] = st.slider("Actividad (0-24h):", 0.0, 24.0, float(props.get("h_total", 8.0)), 0.5, key=f"ht_{idx}")
                
                if tipo == "Point":
                    if modo_visor == "🔊 Vectores de Ruido":
                        for m, db in list(props["maq"].items()):
                            col_m, col_b = st.columns([3, 1])
                            col_m.caption(f"• {m}: {db} dB")
                            if col_b.button("🗑️", key=f"del_{idx}_{m}"):
                                del props["maq"][m]; st.rerun()
                        c1, c2 = st.columns(2)
                        maquina_sel = c1.selectbox("Máquina:", lista_maquinas, key=f"sel_maq_{idx}")
                        if maquina_sel == "➕ Otra (Manual)":
                            m_nom = c1.text_input("Nombre:", key=f"m_nom_{idx}")
                            m_db = c2.number_input("dB (1m):", value=90.0, step=1.0, key=f"m_db_{idx}")
                        elif maquina_sel == "🚜 Lote Movimiento Tierras (Excav. + Transporte)":
                            m_nom = maquina_sel
                            m_db = c2.number_input("dB (1m):", value=110.0, step=1.0, key=f"m_db_{idx}")
                        else:
                            m_nom = maquina_sel
                            db_defecto = float(df_maq[df_maq['Nombre_Maquina'] == maquina_sel]['dB_1m'].values[0])
                            m_db = c2.number_input("dB (1m):", value=db_defecto, step=1.0, key=f"m_db_{idx}")
                            
                        if st.button("➕ Asignar", key=f"btn_assign_{idx}") and m_nom:
                            props["maq"][m_nom] = m_db; st.rerun()
                    else:
                        act_actuales = props.get("actividades_polvo", ["Excavación y carga de tierras (Retro)"])
                        if isinstance(act_actuales, str): act_actuales = [act_actuales]
                        sel_acts = st.multiselect("Actividades de Obra Simultáneas:", list(actividades_polvo.keys()), default=act_actuales, key=f"polvo_act_{idx}")
                        if sel_acts != act_actuales:
                            props["actividades_polvo"] = sel_acts; st.rerun()
                            
                        medidas_actuales = props.get("medidas_polvo", [])
                        sel_medidas = st.multiselect("Aplicar Medidas Preventivas:", opciones_medidas, default=medidas_actuales, key=f"polvo_med_{idx}")
                        if sel_medidas != medidas_actuales:
                            props["medidas_polvo"] = sel_medidas; st.rerun()
                        
                        q_base, _ = calcular_emision_polvo_lista(sel_acts, [], viento_velocidad)
                        q_calc, h_calc = calcular_emision_polvo_lista(sel_acts, sel_medidas, viento_velocidad)
                        if q_base > 0 and len(sel_medidas) > 0:
                            reduccion = (1 - (q_calc / q_base)) * 100
                            st.success(f"📉 Medidas aplicadas: Emisión reducida en un **{reduccion:.1f}%**")

                elif tipo == "LineString":
                    if modo_visor == "🔊 Vectores de Ruido":
                        props["aten"] = st.number_input("Atenuación Muro (dB):", value=props["aten"], step=1.0, key=f"aten_{idx}")
                    else:
                        st.caption("Pantalla física activa. Cortavientos sólido (-40% polvo).")
                elif tipo == "Polygon":
                    props["tipo_poligono"] = st.radio("Tipo de Polígono:", ["🏠 Población / Receptor", "🏢 Edificación Densa", "🌳 Vegetación Frondosa", "🌿 Vegetación Media"], index=["🏠 Población / Receptor", "🏢 Edificación Densa", "🌳 Vegetación Frondosa", "🌿 Vegetación Media"].index(props.get("tipo_poligono", "🏠 Población / Receptor")), key=f"tpoly_{idx}")
                    
                    c1_vis, c2_vis = st.columns(2)
                    props["mostrar_poligono"] = c1_vis.checkbox("👁️ Mostrar en mapa", value=props.get("mostrar_poligono", True), key=f"vis_{idx}")
                    props["color_poligono"] = c2_vis.color_picker("Color", value=props.get("color_poligono", "#7f00ff" if "Población" in props["tipo_poligono"] else "#555555"), key=f"col_{idx}")
                    
                    if props["tipo_poligono"] == "🏢 Edificación Densa":
                        props["altura_edif"] = st.number_input("Altura del edificio (m):", value=float(props.get("altura_edif", 10.0)), step=1.0, key=f"hledif_{idx}")
                    elif props["tipo_poligono"] == "🏠 Población / Receptor":
                        if modo_visor == "🔊 Vectores de Ruido":
                            usos_pob = {"Sanitario, docente y cultural (Dotacional)": 60.0, "Residencial": 65.0, "Terciario y oficinas": 70.0, "Industrial": 75.0, "Espacios naturales protegidos": 55.0, "Zonas fluviales y riberas": 55.0, "Fauna sensible / Áreas tranquilas": 45.0}
                            if "uso_nombre" not in props: props["uso_nombre"] = "Residencial"
                            idx_uso = list(usos_pob.keys()).index(props["uso_nombre"]) if props["uso_nombre"] in usos_pob else 1
                            sel_uso = st.selectbox("Categoría de Área Acústica:", list(usos_pob.keys()), index=idx_uso, key=f"uso_{idx}")
                            if sel_uso != props["uso_nombre"]:
                                props["uso_nombre"] = sel_uso; props["umbral"] = usos_pob[sel_uso]; st.rerun()
                            props["umbral"] = st.number_input("Límite Legal a aplicar (dB):", value=float(props["umbral"]), step=1.0, key=f"umb_{idx}")
                        else:
                            st.caption("Límite Diario PM10 (RD 102/2011): **50 µg/m³**.")
                    else:
                        st.caption("Atenuación acústica progresiva por fricción de masa vegetal.")
                st.write("---")

    focos, pantallas_data, edificios_data, veg_frondosa_data, veg_media_data, poblaciones, focos_aire = [], [], [], [], [], [], []
    for feature in st.session_state["mis_dibujos"]:
        tipo = feature["geometry"]["type"]
        coords = feature["geometry"]["coordinates"]
        props = feature["properties"]
        if tipo == "Point":
            f_cota = props.get("cota", 0.0)
            f_altura = props.get("altura_maq", 2.0)
            radial = props.get("perfil_radial", [f_cota]*36)
            if len(radial) != 36: radial = [f_cota]*36
            h_d = props.get("h_dia", 12.0)
            h_n = props.get("h_noche", 0.0)
            
            emision_max = sumar_decibelios(props.get("maq", {}))
            emision_act = emision_max
            if escenario_visualizacion == "🔵 Normativo Medio (Ld/Ln / 24h)":
                if "Día" in periodo_normativo: emision_act = (emision_max + 10*math.log10(h_d/12.0)) if h_d > 0 else 0
                else: emision_act = (emision_max + 10*math.log10(h_n/8.0)) if h_n > 0 else 0
            
            focos.append({"coords": coords, "name": props["name"], "emision": emision_act, "maq": props.get("maq", {}), "cota": f_cota, "altura_maq": f_altura, "perfil_radial": radial})
            
            act_list = props.get("actividades_polvo", ["Excavación y carga de tierras (Retro)"])
            med_list = props.get("medidas_polvo", [])
            if isinstance(act_list, str): act_list = [act_list]
            
            q_max, h_max = calcular_emision_polvo_lista(act_list, med_list, viento_velocidad if 'viento_velocidad' in locals() else 3.5)
            q_act = q_max
            if escenario_visualizacion == "🔵 Normativo Medio (Ld/Ln / 24h)":
                h_tot = props.get("h_total", 8.0)
                q_act = q_max * (h_tot / 24.0)
                
            focos_aire.append({"lat": coords[1], "lon": coords[0], "name": props["name"], "Q": q_act, "H": h_max, "medidas": med_list, "actividades": act_list, "cota": f_cota, "altura_maq": f_altura, "perfil_radial": radial})
            
        elif tipo == "LineString":
            pantallas_data.append({"coords": coords, "name": props["name"], "aten": props["aten"]})
        elif tipo == "Polygon":
            poly_info = {"coords": coords[0], "name": props["name"], "cota": props.get("cota", 0.0), "mostrar": props.get("mostrar_poligono", True), "color": props.get("color_poligono", "#555555")}
            if props.get("tipo_poligono") == "🏢 Edificación Densa":
                poly_info["altura"] = props.get("altura_edif", 10.0)
                edificios_data.append(poly_info)
            elif props.get("tipo_poligono") == "🌳 Vegetación Frondosa":
                veg_frondosa_data.append(poly_info)
            elif props.get("tipo_poligono") == "🌿 Vegetación Media":
                veg_media_data.append(poly_info)
            else:
                poblaciones.append({"coords": coords[0], "name": props["name"], "umbral": props.get("umbral", 65.0), "uso_nombre": props.get("uso_nombre", "Residencial"), "cota": props.get("cota", 0.0), "mostrar": props.get("mostrar_poligono", True), "color": props.get("color_poligono", "#7f00ff")})

    pantallas_json = json.dumps(pantallas_data, default=safe_serialize)
    edificios_json = json.dumps(edificios_data, default=safe_serialize)
    veg_frondosa_json = json.dumps(veg_frondosa_data, default=safe_serialize)
    veg_media_json = json.dumps(veg_media_data, default=safe_serialize)
    focos_json = json.dumps(focos, default=safe_serialize)

    if st.button("🧹 Limpiar Mapa Completo", type="primary", use_container_width=True, key="btn_limpiar_mapa_unico"):
        st.session_state["mis_dibujos"] = []; st.session_state["map_version"] += 1; st.rerun()

    st.write("---")
    st.markdown("### 🔗 Visores de Interés")
    st.markdown("""
    * [🌐 Visor SIOSE (Ocupación del Suelo)](https://www.siose.es/)
    * [🗺️ Visores Cartográficos (MITECO)](https://www.miteco.gob.es/es/biodiversidad/servicios/banco-datos-naturaleza/bdn-visores.html)
    * [🏢 Sede Electrónica del Catastro](https://www1.sedecatastro.gob.es/Cartografia/mapa.aspx)
    """)

col1, col2, col3 = st.columns(3)
col1.metric("📍 Focos Activos", len(focos))
col2.metric("〰️ Pantallas Acústicas", len(pantallas_data))
col3.metric("⬟ Elementos Manuales", f"{len(edificios_data)} Edificios | {len(veg_frondosa_data)+len(veg_media_data)} Áreas Verdes")

centro = st.session_state["map_center"]
zoom = st.session_state["map_zoom"]
m = folium.Map(location=centro, zoom_start=zoom, tiles=None)

show_osm = (modo_visor == "🔊 Vectores de Ruido")
show_sat = (modo_visor == "💨 Calidad del Aire (Polvo PM10)")

folium.TileLayer("OpenStreetMap", name="🗺️ Fondo OpenStreetMap", show=show_osm).add_to(m)
folium.TileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", attr="Esri", name="⚪ Fondo Gris Claro", show=False).add_to(m)
folium.TileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", attr="Esri", name="🌍 Satélite (Esri)", show=show_sat).add_to(m)
folium.TileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", attr="OpenTopoMap", name="🏔️ Topográfico", show=False).add_to(m)

Fullscreen(position='bottomleft', title='Ampliar a pantalla completa').add_to(m)
MeasureControl(position='topleft', primary_length_unit='meters').add_to(m)
Geocoder(position='topleft', add_marker=False).add_to(m)

folium.WmsTileLayer(url="https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx", layers="CATASTRO", name="🏢 Catastro", fmt="image/png", transparent=True, opacity=0.6, overlay=True, show=False).add_to(m)
folium.WmsTileLayer(url="https://servicios.idee.es/wms-inspire/ocupacion-suelo", layers="LC.LandCoverSurfaces", name="🗺️ Usos del Suelo (SIOSE)", fmt="image/png", transparent=True, opacity=0.5, overlay=True, show=False).add_to(m)
folium.WmsTileLayer(url="https://bio.discomap.eea.europa.eu/arcgis/services/ProtectedSites/CDDA_Dyna_WM/MapServer/WMSServer", layers="0,1,2,3,4", name="🌲 Espacios Protegidos CDDA", fmt="image/png", transparent=True, opacity=0.8, overlay=True, show=False).add_to(m)
folium.WmsTileLayer(url="https://servicios.idee.es/wms-inspire/hidrografia", layers="HY.PhysicalWaters.Waterbodies", name="💧 Zonas Fluviales", fmt="image/png", transparent=True, opacity=0.6, overlay=True, show=False).add_to(m)
folium.WmsTileLayer(url="https://servicios.idee.es/wms-inspire/transportes", layers="TN.RoadTransportNetwork.RoadLink", name="🛣️ Transportes", fmt="image/png", transparent=True, opacity=0.7, overlay=True, show=False).add_to(m)

fg_resultados_ruido = folium.FeatureGroup(name="🔊 Ondas de Ruido (Isófonas)", show=(modo_visor == "🔊 Vectores de Ruido")).add_to(m)
fg_resultados_aire = folium.FeatureGroup(name="💨 Dispersión de Polvo (PM10)", show=(modo_visor == "💨 Calidad del Aire (Polvo PM10)")).add_to(m)
fg_fondo = folium.FeatureGroup(name="🗺️ Ámbito de Obra (Fondo visual)").add_to(m)
fg_edificios = folium.FeatureGroup(name="🏢 Edificios / Obstáculos").add_to(m)
fg_vegetacion = folium.FeatureGroup(name="🌳 Vegetación (Fricción Acústica)").add_to(m)
fg_poblaciones = folium.FeatureGroup(name="🏠 Poblaciones Evaluadas").add_to(m)
fg_pantallas = folium.FeatureGroup(name="〰️ Pantallas Acústicas").add_to(m)
fg_focos = folium.FeatureGroup(name="📍 Focos de Obra").add_to(m)

for f_fondo in st.session_state["capas_fondo"]:
    coords_fondo = f_fondo["geometry"]["coordinates"]
    tipo_fondo = f_fondo["geometry"]["type"]
    if tipo_fondo == "LineString":
        folium.PolyLine(locations=[[lat, lon] for lon, lat in coords_fondo], color=color_fondo, weight=grosor_fondo).add_to(fg_fondo)
    elif tipo_fondo == "Polygon":
        folium.Polygon(locations=[[lat, lon] for lon, lat in coords_fondo[0]], color=color_fondo, fill=relleno_fondo, fill_color=color_fondo, fill_opacity=0.3, weight=grosor_fondo).add_to(fg_fondo)

css_texto = 'color: white; text-shadow: -1.5px -1.5px 0 #000, 1.5px -1.5px 0 #000, -1.5px 1.5px 0 #000, 1.5px 1.5px 0 #000; font-weight: bold; font-size: 14px; white-space: nowrap;'

isofonas_list_export = []
polvo_grid_kmz_export = []
poligonos_color = {}

if modo_visor == "🔊 Vectores de Ruido":
    if tipo_malla == "Malla Fina (Intervalos 5dB)":
        for banda in malla_fina_config:
            poligonos_banda = []
            for f in focos:
                if f["emision"] > banda["min"]:
                    coords = generar_isofona_con_sombra(f["coords"][1], f["coords"][0], f["emision"], banda["min"], pantallas_json, edificios_json, veg_frondosa_json, veg_media_json, focos_json, f["cota"], f["altura_maq"], f["perfil_radial"])
                    if len(coords) >= 3:
                        poly = ShapelyPolygon([(c[1], c[0]) for c in coords])
                        if not poly.is_valid: poly = poly.buffer(0)
                        poligonos_banda.append(poly)
            if poligonos_banda:
                merged_poly = unary_union(poligonos_banda)
                geoms = [merged_poly] if merged_poly.geom_type == 'Polygon' else merged_poly.geoms
                for geom in geoms:
                    coords_folium = [(lat, lon) for lon, lat in geom.exterior.coords]
                    folium.Polygon(locations=coords_folium, color=banda["color"], fill=True, fill_color=banda["color"], fill_opacity=opacidad_malla_fina, weight=1).add_to(fg_resultados_ruido)
                    isofonas_list_export.append({"name": f"Ruido > {banda['min']} dB", "color": banda["color"], "coords": coords_folium})
    else:
        for umb, color, opacity, w in [(umbral_referencia - 20, "green", 0.1, 1), (umbral_referencia - 10, "orange", 0.2, 1), (umbral_referencia, "red", 0.3, 2)]:
            poligonos_banda = []
            for f in focos:
                if f["emision"] > umb:
                    coords = generar_isofona_con_sombra(f["coords"][1], f["coords"][0], f["emision"], umb, pantallas_json, edificios_json, veg_frondosa_json, veg_media_json, focos_json, f["cota"], f["altura_maq"], f["perfil_radial"])
                    if len(coords) >= 3:
                        poly = ShapelyPolygon([(c[1], c[0]) for c in coords])
                        if not poly.is_valid: poly = poly.buffer(0)
                        poligonos_banda.append(poly)
            if poligonos_banda:
                merged_poly = unary_union(poligonos_banda)
                geoms = [merged_poly] if merged_poly.geom_type == 'Polygon' else merged_poly.geoms
                for geom in geoms:
                    coords_folium = [(lat, lon) for lon, lat in geom.exterior.coords]
                    folium.Polygon(locations=coords_folium, color=color, fill=True, fill_opacity=opacity, weight=w+1).add_to(fg_resultados_ruido)
                    isofonas_list_export.append({"name": f"Límite > {umb} dB", "color": color, "coords": coords_folium})

    if activar_umbral_global:
        poligonos_limite = []
        for f in focos:
            if f["emision"] > umbral_referencia:
                coords = generar_isofona_con_sombra(f["coords"][1], f["coords"][0], f["emision"], umbral_referencia, pantallas_json, edificios_json, veg_frondosa_json, veg_media_json, focos_json, f["cota"], f["altura_maq"], f["perfil_radial"])
                if len(coords) >= 3:
                    poly = ShapelyPolygon([(c[1], c[0]) for c in coords])
                    if not poly.is_valid: poly = poly.buffer(0)
                    poligonos_limite.append(poly)
        if poligonos_limite:
            merged_poly = unary_union(poligonos_limite)
            geoms = [merged_poly] if merged_poly.geom_type == 'Polygon' else merged_poly.geoms
            for geom in geoms:
                coords_folium = [(lat, lon) for lon, lat in geom.exterior.coords]
                folium.Polygon(locations=coords_folium, color="red", fill=False, weight=3, dash_array="10, 10").add_to(fg_resultados_ruido)

elif modo_visor == "💨 Calidad del Aire (Polvo PM10)":
    if focos_aire:
        max_q = max([f["Q"] for f in focos_aire] + [0.1])
        margen_lat = 0.015 + (max_q * 0.015) 
        margen_lon = 0.020 + (max_q * 0.015)
        
        min_lat = min(f["lat"] for f in focos_aire) - margen_lat
        max_lat = max(f["lat"] for f in focos_aire) + margen_lat
        min_lon = min(f["lon"] for f in focos_aire) - margen_lon
        max_lon = max(f["lon"] for f in focos_aire) + margen_lon
        
        step_lat = 0.00015
        step_lon = 0.00020
        
        def get_color_for_conc(c):
            stops = [(10.0, (253, 241, 226)), (20.0, (246, 210, 185)), (40.0, (236, 174, 147)), (50.0, (220, 130, 108)), (100.0, (189, 35, 40))]
            if c <= 10.0: return "#FDF1E2"
            if c >= 100.0: return "#BD2328"
            for i in range(4):
                if stops[i][0] <= c <= stops[i+1][0]:
                    f_val = (c - stops[i][0]) / (stops[i+1][0] - stops[i][0])
                    r = int(stops[i][1][0] + f_val * (stops[i+1][1][0] - stops[i][1][0]))
                    g = int(stops[i][1][1] + f_val * (stops[i+1][1][1] - stops[i][1][1]))
                    b = int(stops[i][1][2] + f_val * (stops[i+1][1][2] - stops[i][1][2]))
                    return f"#{r:02X}{g:02X}{b:02X}"
            return "#BD2328"
        
        lat_i = min_lat
        while lat_i <= max_lat:
            lon_i = min_lon
            while lon_i <= max_lon:
                c_lat = lat_i + step_lat/2
                c_lon = lon_i + step_lon/2
                
                conc = calcular_concentracion_total_punto(c_lat, c_lon, focos_aire, viento_velocidad, viento_direccion, cota_dest=0.0)
                
                if conc >= 10.0:
                    conc_level = round(conc, 0)
                    col = get_color_for_conc(conc_level)
                    
                    key = (col, "")
                    if key not in poligonos_color: poligonos_color[key] = []
                    
                    polvo_grid_kmz_export.append({"bounds": [[lat_i, lon_i], [lat_i + step_lat, lon_i + step_lon]], "color": col, "conc": conc})
                    
                    p1 = (lon_i, lat_i)
                    p2 = (lon_i + step_lon, lat_i)
                    p3 = (lon_i + step_lon, lat_i + step_lat)
                    p4 = (lon_i, lat_i + step_lat)
                    poly = ShapelyPolygon([p1, p2, p3, p4])
                    if not poly.is_valid: poly = poly.buffer(0)
                    poligonos_color[key].append(poly)
                    
                lon_i += step_lon
            lat_i += step_lat

        for (color, lbl), list_poly in poligonos_color.items():
            if list_poly:
                merged = unary_union(list_poly)
                geoms = [merged] if merged.geom_type == 'Polygon' else merged.geoms
                for geom in geoms:
                    coords_f = [(lat, lon) for lon, lat in geom.exterior.coords]
                    folium.Polygon(locations=coords_f, color=color, fill=True, fill_color=color, fill_opacity=0.45, weight=0).add_to(fg_resultados_aire)

for edif in edificios_data:
    if edif.get("mostrar", True):
        folium.Polygon(locations=[[lat, lon] for lon, lat in edif["coords"]], color=edif.get("color", "#555555"), fill=True, fill_color=edif.get("color", "#555555"), fill_opacity=0.7, weight=2, tooltip=f"🏢 {edif['name']} (H: {edif['altura']}m)").add_to(fg_edificios)

for veg in veg_frondosa_data:
    if veg.get("mostrar", True):
        folium.Polygon(locations=[[lat, lon] for lon, lat in veg["coords"]], color=veg.get("color", "#228B22"), fill=True, fill_color=veg.get("color", "#228B22"), fill_opacity=0.4, weight=2, tooltip=f"🌳 {veg['name']} (Fricción Alta)").add_to(fg_vegetacion)

for veg in veg_media_data:
    if veg.get("mostrar", True):
        folium.Polygon(locations=[[lat, lon] for lon, lat in veg["coords"]], color=veg.get("color", "#90EE90"), fill=True, fill_color=veg.get("color", "#90EE90"), fill_opacity=0.4, weight=2, tooltip=f"🌿 {veg['name']} (Fricción Media)").add_to(fg_vegetacion)

for pob in poblaciones:
    poly_coords = pob["coords"]
    nombre = pob["name"]
    umbral_pob = pob["umbral"]
    shapely_poly = ShapelyPolygon(poly_coords)
    c_lon, c_lat = shapely_poly.centroid.x, shapely_poly.centroid.y
    
    if modo_visor == "🔊 Vectores de Ruido":
        max_ruido = 0
        puntos_eval = [Point(c_lon, c_lat)] + [Point(c[0], c[1]) for c in poly_coords]
        
        pantallas_polys = [{"line": LineString(p["coords"]), "aten": p["aten"]} for p in pantallas_data if len(p["coords"]) >= 2]
        edif_polys = [{"poly": ShapelyPolygon(e["coords"]), "h_max": e["cota"] + e["altura"]} for e in edificios_data if len(e["coords"]) >= 3]
        veg_f_polys = [ShapelyPolygon(p["coords"]) for p in veg_frondosa_data if len(p["coords"]) >= 3]
        veg_m_polys = [ShapelyPolygon(p["coords"]) for p in veg_media_data if len(p["coords"]) >= 3]
        
        for pt in puntos_eval:
            r_parciales = []
            for f in focos:
                if f["emision"] <= 0: continue
                dist_2d = distancia_haversine(f["coords"][1], f["coords"][0], pt.y, pt.x)
                dist_3d = math.sqrt(dist_2d**2 + ((f.get("cota",0.0) + f.get("altura_maq",2.0)) - pob.get("cota", 0.0))**2)
                
                b_angle = get_bearing(f["coords"][1], f["coords"][0], pt.y, pt.x)
                f_radial = f.get("perfil_radial", [f.get("cota",0.0)]*36)
                if len(f_radial) != 36: f_radial = [f.get("cota",0.0)]*36
                idx1 = int(b_angle // 10) % 36
                idx2 = (idx1 + 1) % 36
                w = (b_angle % 10) / 10.0
                cota_terr = f_radial[idx1] * (1 - w) + f_radial[idx2] * w
                
                d_top = cota_terr - (f.get("cota", 0.0) + f.get("altura_maq", 2.0))
                at_ap = min(10.0, d_top * 0.75) if d_top > 0 else 0.0
                
                rayo = LineString([(f["coords"][0], f["coords"][1]), (pt.x, pt.y)])
                
                for pant in pantallas_polys:
                    if rayo.intersects(pant["line"]): at_ap = max(at_ap, pant["aten"])
                    
                for ed in edif_polys:
                    if rayo.intersects(ed["poly"]) and ed["h_max"] > (f.get("cota",0.0) + f.get("altura_maq",2.0)):
                        at_ap = max(at_ap, 15.0)
                        
                for vf in veg_f_polys:
                    if rayo.intersects(vf):
                        try: at_ap += (rayo.intersection(vf).length * 111320.0) * 0.15
                        except: pass
                        
                for vm in veg_m_polys:
                    if rayo.intersects(vm):
                        try: at_ap += (rayo.intersection(vm).length * 111320.0) * 0.05
                        except: pass
                            
                ruido_foco = f["emision"] - 20 * math.log10(dist_3d) - at_ap if dist_3d > 1 else f["emision"] - at_ap
                r_parciales.append(ruido_foco)
            r_tot = 10 * math.log10(sum(10 ** (r / 10) for r in r_parciales)) if r_parciales else 0
            if r_tot > max_ruido: max_ruido = r_tot
            
        supera_umbral = False
        if max_ruido > umbral_pob: 
            supera_umbral = True
        else:
            for f in focos:
                if f["emision"] <= 0: continue
                iso_coords_limite = generar_isofona_con_sombra(f["coords"][1], f["coords"][0], f["emision"], umbral_pob, pantallas_json, edificios_json, veg_frondosa_json, veg_media_json, focos_json, f["cota"], f["altura_maq"], f["perfil_radial"])
                if len(iso_coords_limite) >= 3:
                    iso_poly = ShapelyPolygon([(lon, lat) for lon, lat in iso_coords_limite])
                    if not iso_poly.is_valid: iso_poly = iso_poly.buffer(0)
                    if ShapelyPolygon(poly_coords).intersects(iso_poly): 
                        supera_umbral = True; break

        if supera_umbral: 
            color_pob = "red"
            html = f'<div style="{css_texto} text-align: center;">{nombre}<br><span style="color: #ffcccc; font-size: 11px;">(Incumple {umbral_pob}dB)</span></div>'
        else: 
            color_pob = pob.get("color", "green")
            html = f'<div style="{css_texto} text-align: center;">{nombre}<br><span style="color: #ccffcc; font-size: 11px;">({max_ruido:.1f} dB)</span></div>'
    else:
        polvo_centro = calcular_concentracion_total_punto(c_lat, c_lon, focos_aire, viento_velocidad, viento_direccion, cota_dest=pob.get("cota", 0.0))
        if polvo_centro > 50.0: color_pob, html = "red", f'<div style="{css_texto} text-align: center;">{nombre}<br><span style="color: #ffcccc; font-size: 11px;">(Excede RD 102: {polvo_centro:.1f}µg)</span></div>'
        else: color_pob, html = pob.get("color", "green"), f'<div style="{css_texto} text-align: center;">{nombre}<br><span style="color: #ccffcc; font-size: 11px;">({polvo_centro:.1f} / 50 µg/m³)</span></div>'
        
    if pob.get("mostrar", True):
        folium.Polygon(locations=[[lat, lon] for lon, lat in poly_coords], color=color_pob, fill=True, fill_opacity=0.35, weight=2).add_to(fg_poblaciones)
        if nombre: folium.Marker([c_lat, c_lon], icon=folium.DivIcon(html=html, icon_size=(250, 60), icon_anchor=(125, 30))).add_to(fg_poblaciones)

for p in pantallas_data:
    pant_coord = p["coords"]
    nombre, aten = p["name"], p["aten"]
    folium.PolyLine(locations=[[lat, lon] for lon, lat in pant_coord], color="black", weight=12, opacity=1.0).add_to(fg_pantallas)
    folium.PolyLine(locations=[[lat, lon] for lon, lat in pant_coord], color="#00FFFF", weight=6, opacity=1.0, tooltip=f"〰️ Pantalla: {nombre} | Filtro: -{aten:.1f} dB").add_to(fg_pantallas)

for idx, f in enumerate(st.session_state["mis_dibujos"]):
    if f["geometry"]["type"] == "Point":
        coords = f["geometry"]["coordinates"]
        props = f["properties"]
        if modo_visor == "🔊 Vectores de Ruido":
            foco_res = next((item for item in focos if item["coords"] == coords), None)
            val_em = foco_res["emision"] if foco_res else 0.0
            folium.Marker([coords[1], coords[0]], icon=folium.Icon(color="black", icon="cog")).add_to(fg_focos)
            folium.Marker([coords[1], coords[0]], icon=folium.DivIcon(html=f'<div style="{css_texto}">{props["name"]}</div>', icon_size=(250, 40), icon_anchor=(-15, 20))).add_to(fg_focos)
        else:
            foco_res = next((item for item in focos_aire if item["lat"] == coords[1] and item["lon"] == coords[0]), None)
            val_em = foco_res["Q"] if foco_res else 0.0
            icono_color = "blue" if props.get("medidas_polvo") else "lightgray"
            folium.Marker([coords[1], coords[0]], icon=folium.Icon(color=icono_color, icon="info-sign")).add_to(fg_focos)
            folium.Marker([coords[1], coords[0]], icon=folium.DivIcon(html=f'<div style="{css_texto}">{props["name"]}</div>', icon_size=(250, 40), icon_anchor=(-15, 20))).add_to(fg_focos)

Draw(export=False, draw_options={'polyline': True, 'polygon': True, 'marker': True, 'circle': False, 'rectangle': False}, edit_options={'edit': False, 'remove': False}).add_to(m)
folium.LayerControl(position="topright", collapsed=True).add_to(m)

escala_ruido_html = """
<div style="flex: 1; min-width: 200px; padding-right: 15px; border-right: 1px solid #ccc;">
    <div style="font-weight: bold; margin-bottom: 5px; text-align: center; border-bottom: 1px solid #eee; padding-bottom: 3px;">Niveles de Ruido (dB)</div>
    <div style="display: flex; flex-wrap: wrap; font-size: 11px;">
        <div style="width: 50%; margin-bottom: 2px;"><span style="display:inline-block; width:12px; height:12px; background:#00FF00; border:1px solid #999;"></span> 30-35</div>
        <div style="width: 50%; margin-bottom: 2px;"><span style="display:inline-block; width:12px; height:12px; background:#66B24D; border:1px solid #999;"></span> 35-40</div>
        <div style="width: 50%; margin-bottom: 2px;"><span style="display:inline-block; width:12px; height:12px; background:#99CC33; border:1px solid #999;"></span> 40-45</div>
        <div style="width: 50%; margin-bottom: 2px;"><span style="display:inline-block; width:12px; height:12px; background:#D8F2A0; border:1px solid #999;"></span> 45-50</div>
        <div style="width: 50%; margin-bottom: 2px;"><span style="display:inline-block; width:12px; height:12px; background:#FFFF00; border:1px solid #999;"></span> 50-55</div>
        <div style="width: 50%; margin-bottom: 2px;"><span style="display:inline-block; width:12px; height:12px; background:#FFE6AA; border:1px solid #999;"></span> 55-60</div>
        <div style="width: 50%; margin-bottom: 2px;"><span style="display:inline-block; width:12px; height:12px; background:#FFAA33; border:1px solid #999;"></span> 60-65</div>
        <div style="width: 50%; margin-bottom: 2px;"><span style="display:inline-block; width:12px; height:12px; background:#FF3333; border:1px solid #999;"></span> 65-70</div>
        <div style="width: 50%; margin-bottom: 2px;"><span style="display:inline-block; width:12px; height:12px; background:#CC3333; border:1px solid #999;"></span> 70-75</div>
        <div style="width: 50%; margin-bottom: 2px;"><span style="display:inline-block; width:12px; height:12px; background:#FF00FF; border:1px solid #999;"></span> 75-80</div>
        <div style="width: 50%; margin-bottom: 2px;"><span style="display:inline-block; width:12px; height:12px; background:#295180; border:1px solid #999;"></span> > 80</div>
    </div>
</div>
"""

escala_polvo_html = """
<div style="flex: 1; min-width: 200px; padding-right: 15px; border-right: 1px solid #ccc;">
    <div style="font-weight: bold; margin-bottom: 5px; text-align: center; border-bottom: 1px solid #eee; padding-bottom: 3px;">Concentración PM10 (µg/m³)</div>
    <div style="display: flex; flex-direction: column; gap: 4px; font-size: 11px;">
        <div><span style="display:inline-block; width:12px; height:12px; background:#FDF1E2; border:1px solid #999;"></span> 10 - 20 (Fondo Disperso)</div>
        <div><span style="display:inline-block; width:12px; height:12px; background:#F6D2B9; border:1px solid #999;"></span> 20 - 40 (Moderado)</div>
        <div><span style="display:inline-block; width:12px; height:12px; background:#ECAE93; border:1px solid #999;"></span> 40 - 50 (Alerta Preventiva)</div>
        <div><span style="display:inline-block; width:12px; height:12px; background:#DC826C; border:1px solid #999;"></span> <b>50 - 100 (Incumple Límite)</b></div>
        <div><span style="display:inline-block; width:12px; height:12px; background:#BD2328; border:1px solid #999;"></span> > 100 (Impacto Crítico a Salud)</div>
    </div>
</div>
"""

columna_eea_html = """
<div style="flex: 1; min-width: 200px; padding-left: 5px;">
    <div style="font-weight: bold; margin-bottom: 5px; text-align: center; border-bottom: 1px solid #eee; padding-bottom: 3px;">Ambiental (EEA)</div>
    <div style="display: flex; flex-wrap: wrap; font-size: 11px;">
        <div style="width: 50%; margin-bottom: 2px; display: flex; align-items: center;"><span style="display:inline-block; width:12px; height:12px; background:repeating-linear-gradient(-45deg, transparent, transparent 2px, #8888FF 2px, #8888FF 3px); border:1px solid #8888FF; margin-right: 5px;"></span> LIC/ZEC</div>
        <div style="width: 50%; margin-bottom: 2px; display: flex; align-items: center;"><span style="display:inline-block; width:12px; height:12px; background:repeating-linear-gradient(45deg, transparent, transparent 2px, #FF8888 2px, #FF8888 3px); border:1px solid #FF8888; margin-right: 5px;"></span> ZEPA</div>
        <div style="width: 50%; margin-bottom: 2px; display: flex; align-items: center;"><span style="display:inline-block; width:12px; height:12px; background:repeating-linear-gradient(-45deg, transparent, transparent 2px, #8888FF 2px, #8888FF 3px), repeating-linear-gradient(45deg, transparent, transparent 2px, #FF8888 2px, #FF8888 3px); border:1px solid #333; margin-right: 5px;"></span> LIC+ZEPA</div>
        <div style="width: 50%; margin-bottom: 2px; display: flex; align-items: center;"><span style="display:inline-block; width:12px; height:12px; background:#7CFC00; border:1px solid #999; margin-right: 5px;"></span> Res. Estricta</div>
        <div style="width: 50%; margin-bottom: 2px; display: flex; align-items: center;"><span style="display:inline-block; width:12px; height:12px; background:#808000; border:1px solid #999; margin-right: 5px;"></span> Silvestre</div>
        <div style="width: 50%; margin-bottom: 2px; display: flex; align-items: center;"><span style="display:inline-block; width:12px; height:12px; background:#006400; border:1px solid #999; margin-right: 5px;"></span> P. Nacional</div>
        <div style="width: 50%; margin-bottom: 2px; display: flex; align-items: center;"><span style="display:inline-block; width:12px; height:12px; background:#FFFACD; border:1px solid #999; margin-right: 5px;"></span> Mon. Natural</div>
        <div style="width: 50%; margin-bottom: 2px; display: flex; align-items: center;"><span style="display:inline-block; width:12px; height:12px; background:#FFA500; border:1px solid #999; margin-right: 5px;"></span> Gest. Hábitat</div>
        <div style="width: 50%; margin-bottom: 2px; display: flex; align-items: center;"><span style="display:inline-block; width:12px; height:12px; background:#FF69B4; border:1px solid #999; margin-right: 5px;"></span> Paisaje Prot.</div>
        <div style="width: 50%; margin-bottom: 2px; display: flex; align-items: center;"><span style="display:inline-block; width:12px; height:12px; background:#0000FF; border:1px solid #999; margin-right: 5px;"></span> Uso Sost.</div>
    </div>
</div>
"""

escala_activa = escala_ruido_html if modo_visor == "🔊 Vectores de Ruido" else escala_polvo_html

leyendas_html = f"""
<div style="position: fixed; top: 15px; left: 50%; transform: translateX(-50%); z-index: 10000; background: rgba(255, 255, 255, 0.95); padding: 8px 15px; border: 1px solid rgba(0,0,0,0.1); border-radius: 8px; font-family: sans-serif; font-size: 13px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); display: flex; align-items: center; gap: 15px; pointer-events: none;">
    <b>🛠️ Herramientas</b> | 〰️ Pantalla | ⬟ Área/Edificio | 📍 Foco
</div>
<div style="position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); z-index: 10000; background: rgba(255, 255, 255, 0.95); padding: 12px; border: 1px solid rgba(0,0,0,0.1); border-radius: 10px; font-family: sans-serif; box-shadow: 0 4px 15px rgba(0,0,0,0.1); pointer-events: auto; display: flex; flex-direction: row; align-items: stretch; max-width: 90vw;">
    {escala_activa}
    {columna_eea_html}
</div>
"""

leyenda_macro = MacroElement()
leyenda_macro._template = Template(f"{{% macro html(this, kwargs) %}}\n{leyendas_html}\n{{% endmacro %}}")
m.get_root().add_child(leyenda_macro)

map_key_actual = f"visor_mapa_{st.session_state.get('map_version', 0)}"
estilos_capas = "<style>.leaflet-control-layers-expanded { padding: 6px 10px !important; } .leaflet-control-layers label { font-size: 12px !important; line-height: 1.2 !important; margin-bottom: 2px !important; } .leaflet-control-layers-selector { margin-top: 2px !important; margin-right: 5px !important; } .leaflet-control-layers-separator { margin: 4px 0 !important; }</style>"
m.get_root().header.add_child(folium.Element(estilos_capas))

map_output = st_folium(m, width=1200, height=850, use_container_width=True, key=map_key_actual, returned_objects=["last_active_drawing"], return_on_hover=False)

if map_output and map_output.get("last_active_drawing"):
    nuevo_dibujo = map_output["last_active_drawing"]
    geom_nueva_str = json.dumps(nuevo_dibujo.get("geometry"), sort_keys=True, default=safe_serialize)
    ya_existe = any(json.dumps(d.get("geometry"), sort_keys=True, default=safe_serialize) == geom_nueva_str for d in st.session_state["mis_dibujos"])
    
    if not ya_existe:
        coords = nuevo_dibujo["geometry"]["coordinates"]
        tipo = nuevo_dibujo["geometry"]["type"]
        
        nuevo_dibujo["properties"]["cota"] = 0.0
        nuevo_dibujo["properties"]["altura_maq"] = 2.0
        nuevo_dibujo["properties"]["h_dia"] = 12.0
        nuevo_dibujo["properties"]["h_noche"] = 0.0
        nuevo_dibujo["properties"]["h_total"] = 8.0
        nuevo_dibujo["properties"]["perfil_radial"] = [0.0]*36
        
        try:
            if tipo == "Point":
                elev = obtener_elevaciones([coords[1]], [coords[0]])[0]
                nuevo_dibujo["properties"]["cota"] = elev
                nuevo_dibujo["properties"]["perfil_radial"] = generar_perfil_radial(coords[1], coords[0], 100)
                st.session_state["map_center"] = [coords[1], coords[0]]
            elif tipo == "Polygon" and coords and coords[0]:
                elev = obtener_elevaciones([coords[0][0][1]], [coords[0][0][0]])[0]
                nuevo_dibujo["properties"]["cota"] = elev
                st.session_state["map_center"] = [coords[0][0][1], coords[0][0][0]]
            elif tipo == "LineString" and coords:
                st.session_state["map_center"] = [coords[0][1], coords[0][0]]
        except:
            pass
            
        st.session_state["mis_dibujos"].append(nuevo_dibujo)
        st.session_state["map_version"] += 1
        st.rerun()

# ==========================================
# EXPORTACIÓN Y REPORTES AL FINAL 
# ==========================================
with st.sidebar:
    with st.expander("📥 3. Exportación y Reportes", expanded=False):
        if st.session_state["mis_dibujos"]:
            if modo_visor == "🔊 Vectores de Ruido":
                kmz_data = generar_kmz(focos, pantallas_data, poblaciones, isofonas_list_export, modo="ruido")
                st.download_button("⬇️ Descargar KMZ (Ruido y Elementos)", data=kmz_data, file_name="mapa_ruido.kmz", mime="application/vnd.google-earth.kmz", use_container_width=True)
                
                informe_ruido = "ESTUDIO ACÚSTICO: VECTORES DE RUIDO. FASE DE OBRA\n"
                informe_ruido += "="*65 + "\n\n"
                informe_ruido += f"FECHA DE SIMULACIÓN: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
                informe_ruido += f"ESCENARIO EVALUADO: {escenario_visualizacion}\n\n"
                informe_ruido += "1. MARCO LEGAL Y METODOLOGÍA\n"
                informe_ruido += "-"*55 + "\n"
                informe_ruido += "Legislación de referencia: Ley 37/2003, del Ruido y Real Decreto 1367/2007.\n"
                informe_ruido += "Metodología de cálculo: Propagación sonora en exteriores evaluando atenuación por divergencia geométrica, fricción por masa forestal y difracción topográfica por barreras y edificios interpuestos.\n\n"
                
                informe_ruido += "2. INVENTARIO DE FOCOS SONOROS (MAQUINARIA)\n"
                informe_ruido += "-"*55 + "\n"
                if focos:
                    for i, f in enumerate(focos):
                        informe_ruido += f"Foco {i+1}: {f['name']} (Cota: {f['cota']}m + Altura emisión: {f['altura_maq']}m)\n"
                        informe_ruido += f"  - Emisión Acústica ({'Media' if 'Normativo' in escenario_visualizacion else 'Pico'}): {f['emision']:.1f} dB(A)\n"
                        if f['maq']:
                            informe_ruido += "  - Maquinaria operativa en este foco (Nivel de potencia sonora Lw base):\n"
                            for m_name, m_db in f['maq'].items():
                                informe_ruido += f"      * {m_name}: {m_db} dB(A)\n"
                        else:
                            informe_ruido += "  - Maquinaria operativa: No especificada manualmente.\n"
                        informe_ruido += "\n"
                else: 
                    informe_ruido += " No se han modelizado focos sonoros.\n\n"
                
                informe_ruido += "3. MEDIDAS CORRECTORAS Y OBSTÁCULOS FÍSICOS\n"
                informe_ruido += "-"*55 + "\n"
                if pantallas_data or edificios_data or veg_frondosa_data or veg_media_data:
                    for p in pantallas_data: informe_ruido += f" - Barrera '{p['name']}': Atenuación configurada de {p['aten']} dB(A)\n"
                    for e in edificios_data: informe_ruido += f" - Edificio 3D '{e['name']}': Altura {e['altura']}m (Bloqueo visual difractado max -15 dB)\n"
                    for v in veg_frondosa_data: informe_ruido += f" - Vegetación Frondosa '{v['name']}': Absorción (-0.15 dB/m)\n"
                    for v in veg_media_data: informe_ruido += f" - Vegetación Media '{v['name']}': Absorción (-0.05 dB/m)\n"
                else: 
                    informe_ruido += " No se han dispuesto pantallas o topografía 3D manual para esta simulación.\n"
                
                informe_ruido += "\n4. AFECCIÓN A RECEPTORES SENSIBLES (POBLACIÓN)\n"
                informe_ruido += "-"*55 + "\n"
                if poblaciones:
                    for pob in poblaciones:
                        poly_coords = pob["coords"]
                        c_lon, c_lat = ShapelyPolygon(poly_coords).centroid.x, ShapelyPolygon(poly_coords).centroid.y
                        max_ruido = 0
                        
                        pantallas_polys = [{"line": LineString(p["coords"]), "aten": p["aten"]} for p in pantallas_data if len(p["coords"]) >= 2]
                        edif_polys = [{"poly": ShapelyPolygon(e["coords"]), "h_max": e["cota"] + e["altura"]} for e in edificios_data if len(e["coords"]) >= 3]
                        veg_f_polys = [ShapelyPolygon(p["coords"]) for p in veg_frondosa_data if len(p["coords"]) >= 3]
                        veg_m_polys = [ShapelyPolygon(p["coords"]) for p in veg_media_data if len(p["coords"]) >= 3]
                        
                        puntos_eval = [Point(c_lon, c_lat)] + [Point(c[0], c[1]) for c in poly_coords]
                        for pt in puntos_eval:
                            r_parciales = []
                            for f in focos:
                                if f["emision"] <= 0: continue
                                d_2d = distancia_haversine(f["coords"][1], f["coords"][0], pt.y, pt.x)
                                h_s, h_r = f["cota"] + f["altura_maq"], pob["cota"] + 1.5
                                dist_3d = math.sqrt(d_2d**2 + (h_r - h_s)**2)
                                
                                b_angle = get_bearing(f["coords"][1], f["coords"][0], pt.y, pt.x)
                                f_radial = f.get("perfil_radial", [f.get("cota",0.0)]*36)
                                if len(f_radial) != 36: f_radial = [f.get("cota",0.0)]*36
                                idx1 = int(b_angle // 10) % 36
                                idx2 = (idx1 + 1) % 36
                                w = (b_angle % 10) / 10.0
                                cota_terr = f_radial[idx1] * (1 - w) + f_radial[idx2] * w
                                
                                d_top = cota_terr - (f.get("cota", 0.0) + f.get("altura_maq", 2.0))
                                at_ap = min(10.0, d_top * 0.75) if d_top > 0 else 0.0
                                
                                rayo = LineString([(f["coords"][0], f["coords"][1]), (pt.x, pt.y)])
                                
                                for vf in veg_f_polys:
                                    if rayo.intersects(vf):
                                        try: at_ap += (rayo.intersection(vf).length * 111320.0) * 0.15
                                        except: pass
                                        
                                for vm in veg_m_polys:
                                    if rayo.intersects(vm):
                                        try: at_ap += (rayo.intersection(vm).length * 111320.0) * 0.05
                                        except: pass
                                        
                                for pant in pantallas_polys:
                                    if rayo.intersects(pant["line"]): at_ap = max(at_ap, pant["aten"])
                                    
                                for ed in edif_polys:
                                    if rayo.intersects(ed["poly"]):
                                        if ed["h_max"] > h_s:
                                            at_ap = max(at_ap, 15.0)
                                            
                                ruido_foco = f["emision"] - 20 * math.log10(dist_3d) - at_ap if dist_3d > 1 else f["emision"] - at_ap
                                r_parciales.append(ruido_foco)
                            r_tot = 10 * math.log10(sum(10 ** (r / 10) for r in r_parciales)) if r_parciales else 0
                            if r_tot > max_ruido: max_ruido = r_tot
                            
                        supera_umbral = False
                        if max_ruido > pob['umbral']: supera_umbral = True
                        else:
                            for f in focos:
                                if f["emision"] <= 0: continue
                                iso_coords_limite = generar_isofona_con_sombra(f["coords"][1], f["coords"][0], f["emision"], pob['umbral'], pantallas_json, edificios_json, veg_frondosa_json, veg_media_json, focos_json, f["cota"], f["altura_maq"], f["perfil_radial"])
                                if len(iso_coords_limite) >= 3:
                                    iso_poly = ShapelyPolygon([(lon, lat) for lon, lat in iso_coords_limite])
                                    if not iso_poly.is_valid: iso_poly = iso_poly.buffer(0)
                                    if ShapelyPolygon(poly_coords).intersects(iso_poly): 
                                        supera_umbral = True; break

                        estado = "INCUMPLE (Supera límite legal)" if supera_umbral else "CUMPLE"
                        informe_ruido += f" - Receptor Analizado: {pob['name']}\n"
                        informe_ruido += f"   * Uso del Suelo: {pob['uso_nombre']} (Límite Legal: {pob['umbral']} dB)\n"
                        informe_ruido += f"   * Ruido Estimado en Fachada/Límite: {max_ruido:.1f} dB(A)\n"
                        informe_ruido += f"   * ESTADO NORMATIVO: {estado}\n\n"
                else: 
                    informe_ruido += " No se han modelizado núcleos receptores sensibles.\n"
                
                st.write("---")
                st.download_button("📄 Descargar Informe Acústico (TXT)", data=informe_ruido, file_name="informe_ruido.txt", mime="text/plain", use_container_width=True)

            elif modo_visor == "💨 Calidad del Aire (Polvo PM10)":
                kmz_data = generar_kmz(focos_aire, pantallas_data, poblaciones, [], modo="polvo", polvo_grid=polvo_grid_kmz_export, viento_u=viento_velocidad, viento_dir=viento_direccion)
                st.download_button("⬇️ Descargar KMZ (Pluma de Polvo)", data=kmz_data, file_name="mapa_polvo.kmz", mime="application/vnd.google-earth.kmz", use_container_width=True)
                
                st.write("---")
                informe_txt = "ESTUDIO ATMOSFÉRICO: POLVO Y PARTÍCULAS PM10. FASE DE OBRA\n"
                informe_txt += "="*65 + "\n\n"
                informe_txt += f"FECHA DE SIMULACIÓN: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
                informe_txt += f"ESCENARIO EVALUADO: {escenario_visualizacion}\n\n"
                
                informe_txt += "1. CONDICIONES METEOROLÓGICAS DEL ESCENARIO\n"
                informe_txt += "-"*55 + "\n"
                informe_txt += f"Velocidad del viento (u): {viento_velocidad} m/s\n"
                informe_txt += f"Dirección de procedencia: {viento_direccion}º\n"
                informe_txt += f"Dirección física de arrastre de la pluma: {(viento_direccion + 180) % 360}º\n\n"
                
                informe_txt += "2. MARCO LEGAL Y METODOLOGÍA\n"
                informe_txt += "-"*55 + "\n"
                informe_txt += "Legislación aplicable: Ley 34/2007 de Calidad del Aire y Protección de la Atmósfera, y RD 102/2011.\n"
                informe_txt += "Modelo matemático: Modelo Gaussiano de dispersión en estado estacionario (basado en formulación AUSTAL2000).\n"
                informe_txt += "Evaluación térmica y mecánica: Los cálculos evalúan el transporte del contaminante por advección, difusión transversal y turbulencias mecánicas. Se consideran Focos de Volumen para simular el inicio de emisión en base.\n\n"
                
                informe_txt += "3. INVENTARIO DE FOCOS Y MEDIDAS CORRECTORAS APLICADAS\n"
                informe_txt += "-"*55 + "\n"
                if focos_aire:
                    for i, f in enumerate(focos_aire):
                        informe_txt += f"Foco {i+1}: {f['name']} (Cota terreno: {f['cota']}m + Altura: {f['altura_maq']}m)\n"
                        informe_txt += f"  - Coordenadas: Lat {f['lat']:.5f}, Lon {f['lon']:.5f}\n"
                        informe_txt += f"  - Actividades operativas simultáneas:\n"
                        for a in f['actividades']: informe_txt += f"      * {a}\n"
                        
                        if f['medidas']:
                            informe_txt += f"  - Medidas preventivas activas y factor de reducción:\n"
                            for m in f['medidas']: informe_txt += f"      * {m}\n"
                        else:
                            informe_txt += f"  - Medidas preventivas activas: NINGUNA\n"
                        
                        q_base_foco, _ = calcular_emision_polvo_lista(f['actividades'], [], viento_velocidad)
                        informe_txt += f"  - Tasa de Emisión Base bruta: {q_base_foco:.3f} g/s\n"
                        informe_txt += f"  - Tasa de Emisión Neta Final Aplicada ({'Media' if 'Normativo' in escenario_visualizacion else 'Pico'}): {f['Q']:.3f} g/s\n\n"
                else: informe_txt += " No se han modelizado focos emisores de polvo.\n\n"
                
                informe_txt += "4. LÍMITES NORMATIVOS Y CONCLUSIONES\n"
                informe_txt += "-"*55 + "\n"
                informe_txt += "La evaluación se ha realizado teniendo en cuenta los límites establecidos en el "
                informe_txt += "Anexo I del Real Decreto 102/2011, de 28 de enero, relativo a la mejora de la calidad del aire.\n"
                informe_txt += "Límite Diario legal para protección de la salud humana: 50 µg/m³.\n\n"
                informe_txt += "Se recomienda visualizar la cartografía en el Visor o KMZ para verificar la no afección a receptores sensibles "
                informe_txt += "(El límite legal de 50 µg/m³ queda representado mediante el contorno de color rojo. De superarse en zonas habitadas, deberán aplicarse medidas de mitigación adicionales o paralizarse los trabajos).\n"
                
                st.download_button("📄 Descargar Informe Calidad del Aire (TXT)", data=informe_txt, file_name="informe_polvo.txt", mime="text/plain", use_container_width=True)
