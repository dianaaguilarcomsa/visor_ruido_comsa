import streamlit as st
import folium
from folium.plugins import Draw, Fullscreen, MeasureControl, Geocoder
from streamlit_folium import st_folium
import math
import zipfile
import io
import json
import re
import xml.etree.ElementTree as ET
import pandas as pd
from shapely.geometry import Point, LineString, Polygon as ShapelyPolygon
from shapely.ops import unary_union

st.set_page_config(page_title="Visor Mapas de Ruido", layout="wide")

st.markdown("""<style>.stApp{background-color: var(--background-color);} [data-testid="stHeader"]{background-color: transparent !important;} [data-testid="stSidebar"]{background-color: var(--secondary-background-color); border-right: 1px solid var(--border-color);} [data-testid="stMetric"]{background-color: var(--secondary-background-color); padding: 15px 20px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); border-left: 5px solid #0093D0;} [data-testid="stExpander"]{background-color: var(--secondary-background-color); border-radius: 10px; border: 1px solid var(--border-color); margin-bottom: 10px;}</style>""", unsafe_allow_html=True)

st.markdown("""<div style="display: flex; align-items: center; gap: 40px; font-family: 'Segoe UI', system-ui, sans-serif; margin-bottom: 25px; background-color: var(--secondary-background-color); padding: 15px 20px; border-radius: 10px; border: 1px solid var(--border-color); border-bottom: 4px solid #E3182D;"><div style="display: flex; flex-direction: column; min-width: 120px;"><div style="display: flex; gap: 6px; margin-bottom: 2px;"><div style="width: 22px; height: 22px; background-color: #E3182D; border-radius: 50%;"></div><div style="width: 22px; height: 22px; background-color: #0093D0; border-radius: 50%;"></div></div><div style="color: var(--text-color); font-size: 28px; font-weight: 900; line-height: 1;">COMSA</div><div style="color: var(--text-color); opacity: 0.8; font-size: 11px; font-weight: 600;">CORPORACIÓN</div></div><div style="border-left: 2px solid var(--border-color); padding-left: 30px;"><h1 style="color: var(--text-color); margin: 0; font-size: 2.2rem; font-weight: 800;">Visor Mapas de Ruido</h1></div></div>""", unsafe_allow_html=True)

def safe_serialize(obj):
    if hasattr(obj, 'coords'): return list(obj.coords)
    return str(obj)

if "mis_dibujos" not in st.session_state: st.session_state["mis_dibujos"] = []
if "map_version" not in st.session_state: st.session_state["map_version"] = 0
if "map_center" not in st.session_state: st.session_state["map_center"] = [40.4410, -3.6908]
if "map_zoom" not in st.session_state: st.session_state["map_zoom"] = 15

malla_fina_config = [{"min": 30, "color": "#00FF00"}, {"min": 35, "color": "#66B24D"}, {"min": 40, "color": "#99CC33"}, {"min": 45, "color": "#D8F2A0"}, {"min": 50, "color": "#FFFF00"}, {"min": 55, "color": "#FFE6AA"}, {"min": 60, "color": "#FFAA33"}, {"min": 65, "color": "#FF3333"}, {"min": 70, "color": "#CC3333"}, {"min": 75, "color": "#FF00FF"}, {"min": 80, "color": "#295180"}]

@st.cache_data
def cargar_maquinas():
    try: return pd.read_csv("maquinaria.csv")
    except: return pd.DataFrame({"Nombre_Maquina": ["Máquina Genérica"], "dB_1m": [90.0]})

df_maq = cargar_maquinas()
lista_maquinas = df_maq['Nombre_Maquina'].tolist() + ["➕ Otra (Manual)"]

for idx, feature in enumerate(st.session_state["mis_dibujos"]):
    tipo = feature["geometry"]["type"]
    if "properties" not in feature: feature["properties"] = {}
    if "name" not in feature["properties"]: feature["properties"]["name"] = f"{'Foco' if tipo == 'Point' else 'Pantalla' if tipo == 'LineString' else 'Población'} {idx+1}"
    if tipo == "Point" and "maq" not in feature["properties"]: feature["properties"]["maq"] = {}
    if tipo == "LineString" and "aten" not in feature["properties"]: feature["properties"]["aten"] = 15.0
    if tipo == "Polygon" and "umbral" not in feature["properties"]: feature["properties"]["umbral"], feature["properties"]["uso_nombre"] = 65.0, "Residencial"

def sumar_decibelios(dic_maq):
    return 10 * math.log10(sum(10 ** (db / 10) for db in dic_maq.values())) if dic_maq else 0

def calcular_radio(origen, umbral, aten):
    return 10 ** ((origen - umbral - aten) / 20) if origen - aten > umbral else 0

def distancia_haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2, d_phi, d_lam = map(math.radians, [lat1, lat2, lat2-lat1, lon2-lon1])
    a = math.sin(d_phi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(d_lam/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

def parsear_kml_a_dibujos(kml_texto):
    dibujos = []
    try:
        kml_limpio = re.sub(r'\sxmlns="[^"]+"', '', kml_texto)
        root = ET.fromstring(kml_limpio)
        for placemark in root.iter('Placemark'):
            name_tag = placemark.find('name')
            nombre = name_tag.text if name_tag is not None else "Elemento Importado"
            
            pt = placemark.find('.//Point')
            if pt is not None:
                coord_tag = pt.find('.//coordinates')
                if coord_tag is not None:
                    coords = coord_tag.text.strip().split()
                    if coords: dibujos.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(c) for c in coords[0].split(',')[:2]]}, "properties": {"name": nombre, "maq": {}}})
                        
            ls = placemark.find('.//LineString')
            if ls is not None:
                coord_tag = ls.find('.//coordinates')
                if coord_tag is not None:
                    pares = coord_tag.text.strip().split()
                    coords_list = [[float(p.split(',')[0]), float(p.split(',')[1])] for p in pares if len(p.split(',')) >= 2]
                    if coords_list: dibujos.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords_list}, "properties": {"name": nombre, "aten": 15.0}})
                        
            poly = placemark.find('.//Polygon')
            if poly is not None:
                coord_tag = poly.find('.//coordinates')
                if coord_tag is not None:
                    pares = coord_tag.text.strip().split()
                    coords_list = [[float(p.split(',')[0]), float(p.split(',')[1])] for p in pares if len(p.split(',')) >= 2]
                    if coords_list: dibujos.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [coords_list]}, "properties": {"name": nombre, "umbral": 65.0, "uso_nombre": "Residencial"}})
    except Exception as e: st.error(f"Error parseando KML interno: {e}")
    return dibujos

@st.cache_data(show_spinner=False)
def generar_isofona_con_sombra(foco_lat, foco_lon, emision_foco, umbral_banda, pantallas_data_json, focos_all_json, r_earth=6378137.0):
    pantallas_data, focos_all = json.loads(pantallas_data_json), json.loads(focos_all_json)
    coords, foco_pt = [], Point(foco_lon, foco_lat)
    radio_base = calcular_radio(emision_foco, umbral_banda, 0)
    if radio_base <= 0: return []
    emision_total_all = 10 * math.log10(sum(10**(f["emision"]/10) for f in focos_all)) if focos_all else emision_foco
    r_max_posible = calcular_radio(emision_total_all, umbral_banda, 0)
    for angle in range(361):
        rad, r_max_libre = math.radians(angle), radio_base
        if len(focos_all) > 1 and r_max_posible > radio_base:
            low, high = radio_base, r_max_posible + 5
            for _ in range(12):
                mid = (low + high) / 2
                d_lon = math.degrees(mid * math.cos(rad) / (r_earth * math.cos(math.radians(foco_lat))))
                d_lat = math.degrees(mid * math.sin(rad) / r_earth)
                ruidos_pto = [f["emision"] - 20 * math.log10(distancia_haversine(f["coords"][1], f["coords"][0], foco_lat + d_lat, foco_lon + d_lon)) if distancia_haversine(f["coords"][1], f["coords"][0], foco_lat + d_lat, foco_lon + d_lon) > 1 else f["emision"] for f in focos_all]
                tot = 10 * math.log10(sum(10**(x/10) for x in ruidos_pto)) if ruidos_pto else 0
                if tot >= umbral_banda: low = mid
                else: high = mid
            r_max_libre = low
        d_lon_max = math.degrees(r_max_libre * math.cos(rad) / (r_earth * math.cos(math.radians(foco_lat))))
        d_lat_max = math.degrees(r_max_libre * math.sin(rad) / r_earth)
        rayo = LineString([foco_pt, Point(foco_lon + d_lon_max, foco_lat + d_lat_max)])
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
                else: radio_final = min(radio_final, d_muro + (radio_aten - d_min_wall))
        d_lon_final = math.degrees(radio_final * math.cos(rad) / (r_earth * math.cos(math.radians(foco_lat))))
        d_lat_final = math.degrees(radio_final * math.sin(rad) / r_earth)
        coords.append([foco_lat + d_lat_final, foco_lon + d_lon_final])
    return coords

def hex_to_kml_color(hex_color, alpha="60"):
    hex_clean = {"green": "00ff00", "orange": "00a5ff", "red": "0000ff"}.get(hex_color.lower(), hex_color.replace("#", ""))
    return f"{alpha}{hex_clean[4:6]}{hex_clean[2:4]}{hex_clean[0:2]}" if len(hex_clean) == 6 else f"{alpha}ffffff"

def generar_kmz(focos_list, pantallas_list, poblaciones_list, isofonas_list):
    kml = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2">', '<Document>', '<name>Resultados Visor COMSA</name>']
    for f in focos_list:
        kml.append(f'<Placemark><name>{f["name"]}</name><description>Emisión: {f["emision"]:.1f} dB</description><Point><coordinates>{f["coords"][0]},{f["coords"][1]},0</coordinates></Point></Placemark>')
    for p in pantallas_list:
        kml.append(f'<Placemark><name>{p["name"]}</name><description>Atenuación: {p["aten"]:.1f} dB</description><Style><LineStyle><color>ffffff00</color><width>6</width></LineStyle></Style><LineString><coordinates>{" ".join([f"{lon},{lat},0" for lon, lat in p["coords"]])}</coordinates></LineString></Placemark>')
    for pob in poblaciones_list:
        kml.append(f'<Placemark><name>{pob["name"]}</name><Style><PolyStyle><color>7f00ff00</color><fill>1</fill><outline>1</outline></PolyStyle><LineStyle><color>ff00ff00</color><width>2</width></LineStyle></Style><Polygon><outerBoundaryIs><LinearRing><coordinates>{" ".join([f"{lon},{lat},0" for lon, lat in pob["coords"]])} {pob["coords"][0][0]},{pob["coords"][0][1]},0</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>')
    kml.append('</Document></kml>')
    kmz_buffer = io.BytesIO()
    with zipfile.ZipFile(kmz_buffer, 'w', zipfile.ZIP_DEFLATED) as zf: zf.writestr('doc.kml', "\n".join(kml))
    kmz_buffer.seek(0)
    return kmz_buffer

with st.sidebar:
    st.title("⚙️ Panel de Control")
    with st.expander("💾 Gestión de Proyectos", expanded=True):
        if st.session_state["mis_dibujos"]:
            json_proyecto = json.dumps(st.session_state["mis_dibujos"], indent=2, default=safe_serialize)
            st.download_button("💾 Guardar Proyecto (.json)", data=json_proyecto, file_name="proyecto_ruido.json", mime="application/json", use_container_width=True)
        archivo_cargado = st.file_uploader("📂 Importar Proyecto (.json, .kmz, .kml)", type=["json", "kmz", "kml"])
        if archivo_cargado is not None:
            nombre_arch = archivo_cargado.name.lower()
            if nombre_arch.endswith('.json'):
                try:
                    if st.button("Aplicar JSON", use_container_width=True):
                        st.session_state["mis_dibujos"] = json.load(archivo_cargado)
                        st.session_state["map_version"] += 1
                        st.rerun()
                except Exception as e: st.error("Error al leer JSON")
            elif nombre_arch.endswith('.kmz') or nombre_arch.endswith('.kml'):
                try:
                    file_bytes, kml_texto = archivo_cargado.getvalue(), ""
                    try:
                        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                            kml_internos = [f for f in zf.namelist() if f.lower().endswith('.kml')]
                            if kml_internos: kml_texto = zf.read(kml_internos[0]).decode('utf-8', errors='ignore')
                    except zipfile.BadZipFile: kml_texto = file_bytes.decode('utf-8', errors='ignore')
                    if kml_texto:
                        dibujos_kml = parsear_kml_a_dibujos(kml_texto)
                        if dibujos_kml and st.button("Aplicar Archivo", use_container_width=True):
                            st.session_state["mis_dibujos"] = dibujos_kml
                            st.session_state["map_version"] += 1
                            st.rerun()
                except Exception as e: st.error("Error procesando archivo")

    with st.expander("🗺️ Interruptores de Capas (Mejor usar el icono 📚 del mapa)", expanded=True):
        st.info("Para que el mapa no se recargue al cambiar de capa, te recomendamos usar el icono blanco de las capas arriba a la derecha en el propio mapa.")
        idx_fondo_defecto = 0
        fondo_seleccionado = st.radio("Fondo Base Inicial:", ["OpenStreetMap", "Satélite (Esri World Imagery)"], index=idx_fondo_defecto)

    with st.expander("📜 Fondo de Isófonas Global", expanded=True):
        tipo_malla = st.radio("Estilo:", ["Malla Básica (Semáforo)", "Malla Fina (Intervalos 5dB)"])
        activar_umbral_global = st.checkbox("Mostrar línea de límite común voluntaria", value=True)
        umbral_referencia = st.number_input("Umbral / Límite Común (dB):", value=65.0, step=1.0)

    with st.expander("🏷️ Configuración de Elementos", expanded=True):
        if not st.session_state["mis_dibujos"]: st.info("Dibuja elementos en el mapa.")
        else:
            for idx, feature in enumerate(st.session_state["mis_dibujos"]):
                tipo, props = feature["geometry"]["type"], feature["properties"]
                icono = "📍" if tipo == "Point" else "〰️" if tipo == "LineString" else "⬟"
                c1, c2 = st.columns([5, 1])
                with c1: st.markdown(f"**{icono} {props['name']}**")
                with c2:
                    if st.button("🗑️", key=f"del_{idx}"):
                        st.session_state["mis_dibujos"].pop(idx)
                        st.session_state["map_version"] += 1
                        st.rerun()
                props["name"] = st.text_input("Nombre", value=props["name"], key=f"nm_{idx}")
                if tipo == "Point":
                    for m, db in list(props["maq"].items()):
                        c_m, c_b = st.columns([3, 1])
                        c_m.caption(f"• {m}: {db} dB")
                        if c_b.button("🗑️", key=f"dmaq_{idx}_{m}"): del props["maq"][m]; st.rerun()
                    col_sel, col_num = st.columns(2)
                    msel = col_sel.selectbox("Máquina:", lista_maquinas, key=f"sm_{idx}")
                    mnom = col_sel.text_input("Nombre:", key=f"in_{idx}") if msel == "➕ Otra (Manual)" else msel
                    mdb = col_num.number_input("dB:", value=90.0 if msel == "➕ Otra (Manual)" else float(df_maq[df_maq['Nombre_Maquina'] == msel]['dB_1m'].values[0]), step=1.0, key=f"db_{idx}")
                    if st.button("➕ Asignar", key=f"btn_{idx}") and mnom: props["maq"][mnom] = mdb; st.rerun()
                    st.write(f"Potencia Foco: **{sumar_decibelios(props['maq']):.1f} dB**")
                elif tipo == "LineString":
                    props["aten"] = st.number_input("Atenuación (dB):", value=props["aten"], step=1.0, key=f"at_{idx}")
                elif tipo == "Polygon":
                    usos_pob = {"Sanitario/docente": 60.0, "Residencial": 65.0, "Terciario/oficinas": 70.0, "Industrial": 75.0, "Espacios protegidos": 55.0}
                    sel_uso = st.selectbox("Área Acústica:", list(usos_pob.keys()), index=list(usos_pob.keys()).index(props.get("uso_nombre", "Residencial")) if props.get("uso_nombre", "Residencial") in usos_pob else 1, key=f"uso_{idx}")
                    if sel_uso != props.get("uso_nombre", ""): props["uso_nombre"], props["umbral"] = sel_uso, usos_pob[sel_uso]; st.rerun()
                    props["umbral"] = st.number_input("Límite (dB):", value=float(props.get("umbral", 65.0)), step=1.0, key=f"umb_{idx}")
                st.write("---")

    if st.button("🧹 Limpiar Mapa Completo", type="primary", use_container_width=True):
        st.session_state["mis_dibujos"], st.session_state["map_version"] = [], st.session_state["map_version"] + 1
        st.rerun()

focos, pantallas_data, poblaciones = [], [], []
for feature in st.session_state["mis_dibujos"]:
    tipo, coords, props = feature["geometry"]["type"], feature["geometry"]["coordinates"], feature["properties"]
    if tipo == "Point": focos.append({"coords": coords, "name": props["name"], "emision": sumar_decibelios(props["maq"])})
    elif tipo == "LineString": pantallas_data.append({"coords": coords, "name": props["name"], "aten": props["aten"]})
    elif tipo == "Polygon": poblaciones.append({"coords": coords[0], "name": props["name"], "umbral": props.get("umbral", 65.0)})

col1, col2, col3 = st.columns(3)
col1.metric("📍 Focos", len(focos))
col2.metric("〰️ Pantallas", len(pantallas_data))
col3.metric("⬟ Zonas", len(poblaciones))

centro = st.session_state["map_center"]
m = folium.Map(location=centro, zoom_start=st.session_state["map_zoom"], tiles="OpenStreetMap" if fondo_seleccionado == "OpenStreetMap" else "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", attr="Map" if fondo_seleccionado == "OpenStreetMap" else "Esri")

# CAPAS COMO CONTROLES NATIVOS (EVITA QUE SE RECARGUE STREAMLIT)
folium.WmsTileLayer(url="https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx", layers="CATASTRO", name="🏢 Catastro", fmt="image/png", transparent=True, opacity=0.6, overlay=True, show=False).add_to(m)
folium.WmsTileLayer(url="https://servicios.idee.es/wms-inspire/ocupacion-suelo", layers="LC.LandCoverSurfaces", name="🗺️ SIOSE", fmt="image/png", transparent=True, opacity=0.5, overlay=True, show=False).add_to(m)
folium.WmsTileLayer(url="https://bio.discomap.eea.europa.eu/arcgis/services/ProtectedSites/Natura2000Sites/MapServer/WMSServer", layers="0,1,2,3", name="🌲 Red Natura 2000", fmt="image/png", transparent=True, opacity=1.0, overlay=True, show=False).add_to(m)
folium.WmsTileLayer(url="https://bio.discomap.eea.europa.eu/arcgis/services/ProtectedSites/CDDA_Dyna_WM/MapServer/WMSServer", layers="0,1,2,3,4", name="🌲 Espacios CDDA", fmt="image/png", transparent=True, opacity=0.8, overlay=True, show=False).add_to(m)

Fullscreen(position='bottomleft').add_to(m)
MeasureControl(position='topleft', primary_length_unit='meters', secondary_length_unit='kilometers', primary_area_unit='sqmeters').add_to(m)
Geocoder(position='topleft', add_marker=False).add_to(m)

fg_isofonas = folium.FeatureGroup(name="🔊 Ondas de Ruido").add_to(m)
fg_poblaciones = folium.FeatureGroup(name="🏠 Poblaciones").add_to(m)
fg_pantallas = folium.FeatureGroup(name="〰️ Pantallas").add_to(m)
fg_focos = folium.FeatureGroup(name="📍 Focos").add_to(m)

pantallas_json, focos_json = json.dumps(pantallas_data, default=safe_serialize), json.dumps(focos, default=safe_serialize)

if tipo_malla == "Malla Fina (Intervalos 5dB)":
    for banda in malla_fina_config:
        poligonos_banda = [ShapelyPolygon([(c[1], c[0]) for c in generar_isofona_con_sombra(f["coords"][1], f["coords"][0], f["emision"], banda["min"], pantallas_json, focos_json)]) for f in focos if f["emision"] > banda["min"] and len(generar_isofona_con_sombra(f["coords"][1], f["coords"][0], f["emision"], banda["min"], pantallas_json, focos_json)) >= 3]
        if poligonos_banda:
            for geom in ([unary_union([p if p.is_valid else p.buffer(0) for p in poligonos_banda])] if unary_union([p if p.is_valid else p.buffer(0) for p in poligonos_banda]).geom_type == 'Polygon' else unary_union([p if p.is_valid else p.buffer(0) for p in poligonos_banda]).geoms): folium.Polygon(locations=[(lat, lon) for lon, lat in geom.exterior.coords], color=banda["color"], fill=True, fill_opacity=0.4, weight=1).add_to(fg_isofonas)
else:
    for umb, color, opacity, w in [(umbral_referencia - 20, "green", 0.1, 1), (umbral_referencia - 10, "orange", 0.2, 1), (umbral_referencia, "red", 0.3, 2)]:
        poligonos_banda = [ShapelyPolygon([(c[1], c[0]) for c in generar_isofona_con_sombra(f["coords"][1], f["coords"][0], f["emision"], umb, pantallas_json, focos_json)]) for f in focos if f["emision"] > umb and len(generar_isofona_con_sombra(f["coords"][1], f["coords"][0], f["emision"], umb, pantallas_json, focos_json)) >= 3]
        if poligonos_banda:
            for geom in ([unary_union([p if p.is_valid else p.buffer(0) for p in poligonos_banda])] if unary_union([p if p.is_valid else p.buffer(0) for p in poligonos_banda]).geom_type == 'Polygon' else unary_union([p if p.is_valid else p.buffer(0) for p in poligonos_banda]).geoms): folium.Polygon(locations=[(lat, lon) for lon, lat in geom.exterior.coords], color=color, fill=True, fill_opacity=opacity, weight=w+1).add_to(fg_isofonas)

if activar_umbral_global:
    poligonos_limite = [ShapelyPolygon([(c[1], c[0]) for c in generar_isofona_con_sombra(f["coords"][1], f["coords"][0], f["emision"], umbral_referencia, pantallas_json, focos_json)]) for f in focos if f["emision"] > umbral_referencia and len(generar_isofona_con_sombra(f["coords"][1], f["coords"][0], f["emision"], umbral_referencia, pantallas_json, focos_json)) >= 3]
    if poligonos_limite:
        for geom in ([unary_union([p if p.is_valid else p.buffer(0) for p in poligonos_limite])] if unary_union([p if p.is_valid else p.buffer(0) for p in poligonos_limite]).geom_type == 'Polygon' else unary_union([p if p.is_valid else p.buffer(0) for p in poligonos_limite]).geoms): folium.Polygon(locations=[(lat, lon) for lon, lat in geom.exterior.coords], color="red", fill=False, weight=3, dash_array="10, 10").add_to(fg_isofonas)

for pob in poblaciones:
    c_lon, c_lat = ShapelyPolygon(pob["coords"]).centroid.x, ShapelyPolygon(pob["coords"]).centroid.y
    ruido_total = 10 * math.log10(sum(10 ** ((f["emision"] - 20 * math.log10(distancia_haversine(f["coords"][1], f["coords"][0], c_lat, c_lon)) - max([p["aten"] for p in pantallas_data if LineString([(f["coords"][0], f["coords"][1]), (c_lon, c_lat)]).intersects(LineString(p["coords"]))]+[0])) / 10) for f in focos if f["emision"] > 0 and distancia_haversine(f["coords"][1], f["coords"][0], c_lat, c_lon) > 1)) if focos else 0
    color_pob = "red" if ruido_total > pob["umbral"] else "green"
    folium.Polygon(locations=[[lat, lon] for lon, lat in pob["coords"]], color=color_pob, fill=True, fill_opacity=0.4, weight=2).add_to(fg_poblaciones)
    folium.Marker([c_lat, c_lon], icon=folium.DivIcon(html=f'<div style="color: white; text-shadow: -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000; font-weight: bold; font-size: 14px; text-align: center;">{pob["name"]}<br><span style="font-size: 11px;">({ruido_total:.1f} / {pob["umbral"]} dB)</span></div>', icon_size=(150, 40))).add_to(fg_poblaciones)

for p in pantallas_data:
    folium.PolyLine(locations=[[lat, lon] for lon, lat in p["coords"]], color="#00FFFF", weight=6, opacity=1.0).add_to(fg_pantallas)
    folium.Marker([p["coords"][len(p["coords"])//2][1], p["coords"][len(p["coords"])//2][0]], icon=folium.DivIcon(html=f'<div style="color: white; text-shadow: -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000; font-weight: bold; font-size: 14px; text-align: center;">{p["name"]}<br>(-{p["aten"]:.1f} dB)</div>', icon_size=(150, 30))).add_to(fg_pantallas)

for f in focos:
    folium.Marker([f["coords"][1], f["coords"][0]], icon=folium.Icon(color="black", icon="cog")).add_to(fg_focos)

Draw(
    export=False,
    draw_options={'polyline': True, 'polygon': True, 'marker': True, 'circle': False, 'rectangle': False},
    edit_options={'edit': False, 'remove': False}
).add_to(m)
folium.LayerControl(position="topright", collapsed=True).add_to(m)

# HTML LEYENDAS (COMPRIMIDO PARA EVITAR CORTES DE TOKEN)
m.get_root().html.add_child(folium.Element("""
<div style="position:absolute;top:15px;left:50%;transform:translateX(-50%);z-index:9999;background:rgba(255,255,255,0.95);padding:8px 15px;border:1px solid rgba(0,0,0,0.1);border-radius:8px;font-family:sans-serif;font-size:13px;box-shadow:0 4px 15px rgba(0,0,0,0.1);"><b>🛠️ Herramientas</b> | 〰️ Pantalla | ⬟ Población | 📍 Foco</div>
<div style="position:absolute;bottom:30px;right:20px;z-index:9999;background:rgba(255,255,255,0.95);padding:12px;border:1px solid rgba(0,0,0,0.1);border-radius:10px;font-family:sans-serif;font-size:11px;box-shadow:0 4px 15px rgba(0,0,0,0.1);width:230px;">
<div style="font-weight:bold;margin-bottom:5px;text-align:center;border-bottom:1px solid #eee;padding-bottom:3px;">Niveles (dB)</div>
<div style="display:flex;flex-wrap:wrap;">
<div style="width:50%;"><span style="display:inline-block;width:12px;height:12px;background:#00FF00;border:1px solid #999;"></span> 30-35</div><div style="width:50%;"><span style="display:inline-block;width:12px;height:12px;background:#66B24D;border:1px solid #999;"></span> 35-40</div><div style="width:50%;"><span style="display:inline-block;width:12px;height:12px;background:#99CC33;border:1px solid #999;"></span> 40-45</div><div style="width:50%;"><span style="display:inline-block;width:12px;height:12px;background:#D8F2A0;border:1px solid #999;"></span> 45-50</div><div style="width:50%;"><span style="display:inline-block;width:12px;height:12px;background:#FFFF00;border:1px solid #999;"></span> 50-55</div><div style="width:50%;"><span style="display:inline-block;width:12px;height:12px;background:#FFE6AA;border:1px solid #999;"></span> 55-60</div><div style="width:50%;"><span style="display:inline-block;width:12px;height:12px;background:#FFAA33;border:1px solid #999;"></span> 60-65</div><div style="width:50%;"><span style="display:inline-block;width:12px;height:12px;background:#FF3333;border:1px solid #999;"></span> 65-70</div><div style="width:50%;"><span style="display:inline-block;width:12px;height:12px;background:#CC3333;border:1px solid #999;"></span> 70-75</div><div style="width:50%;"><span style="display:inline-block;width:12px;height:12px;background:#FF00FF;border:1px solid #999;"></span> 75-80</div><div style="width:50%;"><span style="display:inline-block;width:12px;height:12px;background:#295180;border:1px solid #999;"></span> >80</div>
</div><div style="font-weight:bold;margin-bottom:5px;text-align:center;border-bottom:1px solid #eee;padding-bottom:3px;margin-top:5px;">Ambiental (EEA)</div>
<div style="margin-bottom:2px;"><span style="display:inline-block;width:12px;height:12px;background:repeating-linear-gradient(-45deg,transparent,transparent 2px,#8888FF 2px,#8888FF 3px);border:1px solid #8888FF;margin-right:5px;"></span> LIC/ZEC (Hábitats)</div>
<div style="margin-bottom:2px;"><span style="display:inline-block;width:12px;height:12px;background:repeating-linear-gradient(45deg,transparent,transparent 2px,#FF8888 2px,#FF8888 3px);border:1px solid #FF8888;margin-right:5px;"></span> ZEPA (Aves)</div>
<div style="margin-bottom:2px;"><span style="display:inline-block;width:12px;height:12px;background:repeating-linear-gradient(-45deg,transparent,transparent 2px,#8888FF 2px,#8888FF 3px),repeating-linear-gradient(45deg,transparent,transparent 2px,#FF8888 2px,#FF8888 3px);border:1px solid #333;margin-right:5px;"></span> LIC + ZEPA</div>
<div style="margin-bottom:2px;"><span style="display:inline-block;width:12px;height:12px;background:#7CFC00;border:1px solid #999;margin-right:5px;"></span> Reserva Estricta (Ia)</div>
<div style="margin-bottom:2px;"><span style="display:inline-block;width:12px;height:12px;background:#808000;border:1px solid #999;margin-right:5px;"></span> Área Silvestre (Ib)</div>
<div style="margin-bottom:2px;"><span style="display:inline-block;width:12px;height:12px;background:#006400;border:1px solid #999;margin-right:5px;"></span> P. Nacional (II)</div>
<div style="margin-bottom:2px;"><span style="display:inline-block;width:12px;height:12px;background:#FFFACD;border:1px solid #999;margin-right:5px;"></span> Mon. Natural (III)</div>
<div style="margin-bottom:2px;"><span style="display:inline-block;width:12px;height:12px;background:#FFA500;border:1px solid #999;margin-right:5px;"></span> Gest. Hábitat (IV)</div>
<div style="margin-bottom:2px;"><span style="display:inline-block;width:12px;height:12px;background:#FF69B4;border:1px solid #999;margin-right:5px;"></span> Paisaje Protegido (V)</div>
<div><span style="display:inline-block;width:12px;height:12px;background:#0000FF;border:1px solid #999;margin-right:5px;"></span> Área Uso Sost. (VI)</div>
</div>
"""))

map_key_actual = f"visor_mapa_{st.session_state.get('map_version', 0)}"

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
    geom_nueva_str = json.dumps(nuevo_dibujo.get("geometry"), sort_keys=True, default=safe_serialize)
    ya_existe = any(json.dumps(d.get("geometry"), sort_keys=True, default=safe_serialize) == geom_nueva_str for d in st.session_state["mis_dibujos"])
    if not ya_existe:
        st.session_state["mis_dibujos"].append(nuevo_dibujo)
        st.session_state["map_version"] += 1
        st.rerun()
