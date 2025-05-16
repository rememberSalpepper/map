# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
import html
import sys
import base64
import io
import traceback

# --- Configuración Inicial de la Página Streamlit ---
st.set_page_config(layout="wide", page_title="Mapa Interactivo Establecimientos")
st.title("🗺️ Mapa Interactivo de Establecimientos Educacionales")
st.markdown("""
Sube tu archivo Excel ('Base Datos (EB).xlsx' o similar) para visualizar los establecimientos.
Puedes usar los filtros en la barra lateral para refinar la selección.
""")

# --- Constantes y Configuraciones ---
COLS_INTERES = [
    'RBD', 'NOM_RBD','COD_DEPE','COD_DEPE2', 'CONVENIO_PIE','PACE',
    'ENS_01','ENS_02','ENS_03','ENS_04','ENS_05','ENS_06',
    'MAT_TOTAL','LATITUD','LONGITUD'
]
COLS_CRITICAS = ['LATITUD', 'LONGITUD', 'RBD']
COLORS = {'PIE': '#E41A1C', 'PACE': '#377EB8', 'PIE y PACE': '#984EA3', 'Otros': '#4daf4a'}
DEFAULT_COLOR = '#808080'
FONT_FAMILY = "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif"
DEFAULT_LAT = -33.45
DEFAULT_LON = -70.67
DEFAULT_ZOOM = 10

# --- DATOS DEL COLEGIO (AÑADIR AQUÍ) ---
COLEGIO_NOMBRE = "COLEGIO TENIENTE DAGOBERTO GODOY"
COLEGIO_LAT = -33.5597464
COLEGIO_LON = -70.65811107
# --- FIN DATOS DEL COLEGIO ---

# --- Constantes para el Radio de los Marcadores --- ### NUEVO ###
MARKER_MIN_RADIUS = 5      # Radio mínimo para cualquier marcador (antes implícito 3)
MARKER_MAX_RADIUS = 18     # Radio máximo para cualquier marcador (antes implícito 12)
MARKER_BASE_SIZE_CALC = 3  # Tamaño base para el cálculo antes de aplicar min/max (antes 2)
MARKER_EXPONENT_CALC = 0.4 # Exponente para MAT_TOTAL (sensibilidad) (antes 0.35)
MARKER_DIVISOR_CALC = 2.5  # Divisor para MAT_TOTAL (escala) (antes 3)
# --- FIN Constantes para el Radio ---

@st.cache_data
def load_and_process_data(uploaded_file_obj):
    file_name = uploaded_file_obj.name
    print(f"\n--- FN CACHE: Leyendo y procesando archivo: {file_name} ---")
    try:
        df = pd.read_excel(uploaded_file_obj)
        print(f"FN CACHE: Archivo leído. {len(df)} filas iniciales.")

        missing_critical = [col for col in COLS_CRITICAS if col not in df.columns]
        if missing_critical:
            st.error(f"CRÍTICO ({file_name}): Faltan columnas: {', '.join(missing_critical)}. No se puede procesar.")
            return None
        missing_optional = [col for col in COLS_INTERES if col not in df.columns]
        if missing_optional:
            st.warning(f"Aviso ({file_name}): Faltan columnas opcionales: {', '.join(missing_optional)}. Usando disponibles.")
            cols_a_usar = [col for col in COLS_INTERES if col in df.columns]
        else:
            cols_a_usar = COLS_INTERES
        cols_finales = list(set(cols_a_usar + COLS_CRITICAS))
        try:
            df_processed = df[cols_finales].copy()
        except KeyError as e:
             st.error(f"Error ({file_name}) seleccionando columnas iniciales: {e}.")
             return None
        df_processed['LATITUD'] = pd.to_numeric(df_processed['LATITUD'], errors='coerce')
        df_processed['LONGITUD'] = pd.to_numeric(df_processed['LONGITUD'], errors='coerce')
        initial_rows = len(df_processed)
        df_processed.dropna(subset=['LATITUD', 'LONGITUD'], inplace=True)
        dropped_rows = initial_rows - len(df_processed)
        if dropped_rows > 0:
             print(f"FN CACHE WARN ({file_name}): Dropped {dropped_rows} rows due to invalid coordinates.")
        if 'RBD' in df_processed.columns:
             df_processed['RBD'] = pd.to_numeric(df_processed['RBD'], errors='coerce').fillna(0).astype(int)

        for col in ['CONVENIO_PIE', 'PACE', 'MAT_TOTAL']:
            if col in df_processed.columns:
                df_processed.loc[:, col] = pd.to_numeric(df_processed[col], errors='coerce').fillna(0).astype(int)

        for i in range(1, 7):
             col_name = f'ENS_0{i}'
             if col_name in df_processed.columns:
                 df_processed.loc[:, col_name] = df_processed[col_name].astype(str)

        if df_processed.empty:
            st.error(f"({file_name}) No quedan datos válidos con coordenadas tras limpieza.")
            return None
        if 'CONVENIO_PIE' in df_processed.columns or 'PACE' in df_processed.columns:
             df_processed['programa'] = df_processed.apply(asignar_programa, axis=1)
        else:
            df_processed['programa'] = 'N/A'
        print(f"--- FN CACHE: Procesamiento completado para {file_name}. {len(df_processed)} filas válidas. ---\n")
        return df_processed
    except Exception as e:
        st.error(f"Error crítico al procesar el archivo ({file_name}): {e}")
        print(f"CRITICAL ERROR in load_and_process_data ({file_name}): {e}\n{traceback.format_exc()}")
        return None

def asignar_programa(row):
    is_pie = row.get('CONVENIO_PIE', 0) == 1; is_pace = row.get('PACE', 0) == 1
    if is_pie and is_pace: return 'PIE y PACE'
    if is_pie: return 'PIE';
    if is_pace: return 'PACE';
    return 'Otros'

def crear_popup_html(r, clr):
    rbd_val = r.get('RBD', 'N/A'); nom_rbd_safe = html.escape(str(r.get('NOM_RBD', 'N/A')))
    cod_depe_safe = html.escape(str(r.get('COD_DEPE', 'N/A'))); cod_depe2_safe = html.escape(str(r.get('COD_DEPE2', 'N/A')))
    pie = r.get('CONVENIO_PIE', 0); pie_str = "Sí" if pie == 1 else "No"
    pace = r.get('PACE', 0); pace_str = "Sí" if pace == 1 else "No"
    ens_activas = [f"0{i}" for i in range(1, 7) if f'ENS_0{i}' in r and pd.notna(r[f'ENS_0{i}']) and str(r[f'ENS_0{i}']).strip() not in ['0', 'N/A', '', ' ']]
    ens_str_safe = html.escape(", ".join(ens_activas) if ens_activas else "Ninguna (01-06)")
    mat_total = r.get('MAT_TOTAL', 0); mat_total_safe = html.escape(str(mat_total))
    popup_html = f"""<div style="width: 350px; font-family: {FONT_FAMILY}; border-radius: 5px; box-shadow: 0 1px 3px rgba(0,0,0,0.2); overflow: hidden; font-size: 14px;"><div style="background: {clr}; color: white; padding: 10px 15px; text-align: center;"><strong style="font-size: 16px; display: block; margin-bottom: 2px;">{nom_rbd_safe}</strong><span style="font-size: 13px;">RBD: {rbd_val}</span></div><div style="padding: 10px 15px; background: #f9f9f9; line-height: 1.5;"><p style="margin: 5px 0;"><strong>Dependencia (1/2):</strong> {cod_depe_safe} / {cod_depe2_safe}</p><p style="margin: 5px 0;"><strong>PIE:</strong> <span style="color: {'#E41A1C' if pie == 1 else '#555'}; font-weight:{'bold' if pie == 1 else 'normal'};">{pie_str}</span></p><p style="margin: 5px 0;"><strong>PACE:</strong> <span style="color: {'#377EB8' if pace == 1 else '#555'}; font-weight:{'bold' if pace == 1 else 'normal'};">{pace_str}</span></p><p style="margin: 5px 0;"><strong>Matrícula Total:</strong> {mat_total_safe}</p><hr style="border: none; border-top: 1px solid #eee; margin: 8px 0;"><p style="margin: 5px 0; color: #555;"><strong>Enseñanzas Activas (01-06):</strong><br>{ens_str_safe}</p></div></div>"""
    return popup_html

def get_table_download_link(df, filename="datos_filtrados.xlsx", link_text="Descargar Datos Filtrados (Excel)"):
    output = io.BytesIO()
    try:
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_download = df.copy();
            for col in df_download.select_dtypes(include=['datetime64[ns]', 'timedelta64[ns]']).columns: df_download[col] = df_download[col].astype(str)
            df_download.to_excel(writer, index=False, sheet_name='Sheet1')
        excel_data = output.getvalue(); b64 = base64.b64encode(excel_data).decode()
        safe_filename = html.escape(filename); safe_link_text = html.escape(link_text)
        href = f'<a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" download="{safe_filename}">{safe_link_text}</a>'
        return href
    except Exception as e:
        st.error(f"Error al generar Excel para descarga: {e}"); print(f"ERROR generating download link: {e}\n{traceback.format_exc()}"); return "Error generando enlace."

if 'initialized' not in st.session_state:
    print("\n--- INICIALIZANDO SESSION STATE POR PRIMERA VEZ ---")
    st.session_state.initialized = True
    st.session_state.map_center = [DEFAULT_LAT, DEFAULT_LON]
    st.session_state.map_zoom = DEFAULT_ZOOM
    st.session_state.data_loaded = False
    st.session_state.original_df_processed = None
    st.session_state.selected_programas = []
    st.session_state.selected_dep = "Todos"
    st.session_state.selected_mat_range = None
    st.session_state.uploaded_filename = None
    print("--- SESSION STATE INICIALIZADO ---")

st.sidebar.header("1. Cargar Datos")
uploaded_file = st.sidebar.file_uploader("Sube tu archivo Excel", type=["xlsx", "xls"], key="file_uploader_main")

if st.session_state.data_loaded and st.session_state.uploaded_filename:
    st.sidebar.info(f"Archivo '{st.session_state.uploaded_filename}' activo.")

if st.sidebar.button("♻️ Limpiar Filtros Sidebar", key="clear_button"):
     print("\n--- ACCIÓN: Limpiando filtros sidebar y vista de mapa... ---")
     st.session_state.selected_programas = []
     st.session_state.selected_dep = "Todos"
     st.session_state.selected_mat_range = None
     st.session_state.map_center = [DEFAULT_LAT, DEFAULT_LON]
     st.session_state.map_zoom = DEFAULT_ZOOM
     print("--- ESTADO RESETEADO (sin dibujo). Disparando rerun. ---")
     st.rerun()

if uploaded_file is not None:
    is_new_file = (not st.session_state.data_loaded or uploaded_file.name != st.session_state.get('uploaded_filename'))
    if is_new_file:
        print(f"\n--- DETECTADO NUEVO ARCHIVO: {uploaded_file.name}. Procesando... ---")
        with st.spinner(f"Procesando '{uploaded_file.name}'..."): map_df_processed = load_and_process_data(uploaded_file)
        if map_df_processed is not None and not map_df_processed.empty:
            print("--- NUEVO ARCHIVO PROCESADO OK. Reseteando estado app... ---")
            st.session_state.original_df_processed = map_df_processed; st.session_state.data_loaded = True
            st.session_state.uploaded_filename = uploaded_file.name
            st.session_state.selected_programas = []; st.session_state.selected_dep = "Todos"; st.session_state.selected_mat_range = None
            st.session_state.map_center = [DEFAULT_LAT, DEFAULT_LON]; st.session_state.map_zoom = DEFAULT_ZOOM
            print("--- ESTADO APP RESETEADO (sin dibujo). Disparando rerun. ---")
            st.rerun()
        else:
            print(f"--- ERROR AL PROCESAR {uploaded_file.name} o sin datos válidos. ---")
            st.session_state.data_loaded = False; st.session_state.original_df_processed = None; st.session_state.uploaded_filename = None

if st.session_state.data_loaded and st.session_state.original_df_processed is not None:
    map_df = st.session_state.original_df_processed.copy()
    st.success(f"Datos base listos: {len(map_df)} registros válidos.")

    st.sidebar.header("2. Filtrar Datos")
    programas_disp = sorted(map_df['programa'].unique()) if 'programa' in map_df.columns else ['N/A']
    current_prog_selection = st.session_state.selected_programas
    if not current_prog_selection or not all(p in programas_disp for p in current_prog_selection): default_programas = programas_disp
    else: default_programas = current_prog_selection
    selected_programas_new = st.sidebar.multiselect("Programa:", options=programas_disp, default=default_programas, key='select_programas')
    if selected_programas_new != st.session_state.selected_programas:
        print("\n--- CAMBIO DETECTADO: Filtro Programa ---")
        st.session_state.selected_programas = selected_programas_new; st.rerun()
    selected_programas = st.session_state.selected_programas

    selected_dep = "Todos"; deps_disp = ["Todos"]
    if 'COD_DEPE2' in map_df.columns:
        deps_list = map_df['COD_DEPE2'].dropna().astype(str).unique()
        try: deps_sorted = sorted(deps_list, key=lambda x: int(x) if x.isdigit() else float('inf'))
        except ValueError: deps_sorted = sorted(deps_list)
        deps_disp.extend(deps_sorted); current_selection = st.session_state.selected_dep
        if current_selection not in deps_disp: st.session_state.selected_dep = "Todos"; dep_index = 0
        else: dep_index = deps_disp.index(current_selection)
        selected_dep_new = st.sidebar.selectbox("Dependencia (COD_DEPE2):", options=deps_disp, index=dep_index, key='select_dependencia')
        if selected_dep_new != st.session_state.selected_dep:
            print("\n--- CAMBIO DETECTADO: Filtro Dependencia ---")
            st.session_state.selected_dep = selected_dep_new; st.rerun()
        selected_dep = st.session_state.selected_dep
    else: st.sidebar.text("'COD_DEPE2' no encontrado.")

    selected_mat_range = None
    if 'MAT_TOTAL' in map_df.columns and map_df['MAT_TOTAL'].nunique() > 1:
        min_mat, max_mat = int(map_df['MAT_TOTAL'].min()), int(map_df['MAT_TOTAL'].max())
        current_range = st.session_state.get('selected_mat_range')
        if current_range is None or not (isinstance(current_range, (tuple, list)) and len(current_range) == 2): default_range = (min_mat, max_mat)
        else: saved_min = max(min_mat, current_range[0]); saved_max = min(max_mat, current_range[1]); default_range = (min(saved_min, saved_max), max(saved_min, saved_max))
        selected_mat_range_new = st.sidebar.slider("Matrícula Total:", min_value=min_mat, max_value=max_mat, value=default_range, key='slider_matricula')
        if selected_mat_range_new != st.session_state.get('selected_mat_range'):
             print("\n--- CAMBIO DETECTADO: Filtro Matrícula ---")
             st.session_state.selected_mat_range = selected_mat_range_new; st.rerun()
        selected_mat_range = st.session_state.selected_mat_range
    elif 'MAT_TOTAL' in map_df.columns and not map_df['MAT_TOTAL'].empty:
        unique_mat_val = int(map_df['MAT_TOTAL'].iloc[0]); st.sidebar.text(f"Matrícula Total: {unique_mat_val} (valor único)")
        st.session_state.selected_mat_range = (unique_mat_val, unique_mat_val); selected_mat_range = st.session_state.selected_mat_range
    else: st.sidebar.text("'MAT_TOTAL' no encontrado.")

    with st.sidebar.expander("🐛 Estado Actual (Depuración)", expanded=False):
        st.write("**Vista Mapa:**")
        st.write(f"- Centro: `{st.session_state.get('map_center')}`")
        st.write(f"- Zoom: `{st.session_state.get('map_zoom')}`")
        st.write("**Otros:**")
        st.write(f"- Data Cargada: `{st.session_state.get('data_loaded')}`")
        st.write(f"- Archivo: `{st.session_state.get('uploaded_filename')}`")
        st.write(f"- Filtro Programa: `{st.session_state.get('selected_programas')}`")
        st.write(f"- Filtro Dep: `{st.session_state.get('selected_dep')}`")
        st.write(f"- Filtro Mat: `{st.session_state.get('selected_mat_range')}`")

    df_filtered_widgets = map_df.copy()
    if selected_programas: df_filtered_widgets = df_filtered_widgets[df_filtered_widgets['programa'].isin(selected_programas)]
    if selected_dep != "Todos": df_filtered_widgets = df_filtered_widgets[df_filtered_widgets['COD_DEPE2'].astype(str) == selected_dep]
    if selected_mat_range: df_filtered_widgets = df_filtered_widgets[(df_filtered_widgets['MAT_TOTAL'] >= selected_mat_range[0]) & (df_filtered_widgets['MAT_TOTAL'] <= selected_mat_range[1])]

    st.sidebar.metric("Registros (Tras Filtros Sidebar)", len(df_filtered_widgets))
    if len(df_filtered_widgets) > 15000:
        st.sidebar.warning("⚠️ >15k puntos sin agrupar. El mapa puede ser MUY LENTO o INESTABLE.")
    elif len(df_filtered_widgets) == 0:
        st.sidebar.warning("⚠️ 0 registros con filtros sidebar.")

    df_final_display = df_filtered_widgets.copy()
    print("\n--- Filtrado espacial DESHABILITADO. Mostrando datos filtrados solo por sidebar. ---")

    st.header("3. Mapa Interactivo")
    st.info(f"✨ Mostrando {len(df_final_display)} registros según filtros de sidebar. Marcadores individuales (sin agrupar).")

    m = folium.Map(location=st.session_state.get('map_center', [DEFAULT_LAT, DEFAULT_LON]),
                   zoom_start=st.session_state.get('map_zoom', DEFAULT_ZOOM),
                   tiles='OpenStreetMap', control_scale=True)

    folium.Marker(
        location=[COLEGIO_LAT, COLEGIO_LON],
        tooltip=html.escape(COLEGIO_NOMBRE),
        popup=f"<b>{html.escape(COLEGIO_NOMBRE)}</b>",
        icon=folium.Icon(color='darkblue', icon_color='white', icon='school', prefix='fa')
    ).add_to(m)

    if not df_final_display.empty:
        points_added_count = 0
        for idx, r in df_final_display.iterrows():
            try:
                prog = r.get('programa', 'N/A'); clr = COLORS.get(prog, DEFAULT_COLOR); popup_html = crear_popup_html(r, clr)
                popup_obj = folium.Popup(popup_html, max_width=400)
                
                mat_total_val = r.get('MAT_TOTAL', 0)
                
                # --- ### CAMBIO REQUERIDO: Nueva lógica para calcular el radio ---
                if mat_total_val > 0:
                    calculated_radius = (
                        MARKER_BASE_SIZE_CALC + 
                        (mat_total_val**MARKER_EXPONENT_CALC) / MARKER_DIVISOR_CALC
                    )
                    radius = max(MARKER_MIN_RADIUS, min(MARKER_MAX_RADIUS, calculated_radius))
                else:
                    radius = MARKER_MIN_RADIUS
                # --- FIN CAMBIO REQUERIDO ---
                
                nom_rbd_raw = str(r.get('NOM_RBD', 'N/A')); rbd_val_raw = str(r.get('RBD', 'N/A')); nom_rbd_html_safe = html.escape(nom_rbd_raw)
                nom_rbd_js_safe = nom_rbd_html_safe.replace('\\', '\\\\').replace('`', '\\`').replace('${', '\\${').replace("'", "\\'")
                tooltip_text = f"{nom_rbd_js_safe} (RBD: {rbd_val_raw})"

                folium.CircleMarker(
                    location=[r['LATITUD'], r['LONGITUD']],
                    radius=radius, # Usar el nuevo radio calculado
                    color='#333333',
                    weight=0.5,
                    fill=True,
                    fill_color=clr,
                    fill_opacity=0.7,
                    popup=popup_obj,
                    tooltip=tooltip_text
                ).add_to(m)
                points_added_count += 1
            except Exception as e_marker:
                rbd_err = r.get('RBD', 'DESCONOCIDO');
                print(f"ERROR al crear marcador para RBD {rbd_err}: {e_marker} - Datos fila: {r.to_dict()}")

    #draw = Draw(export=False, filename='dibujo.geojson', position='topleft', draw_options={'polyline': False, 'polygon': {'showArea': True, 'metric': True, 'feet': False}, 'circle': {'showRadius': True, 'metric': True, 'feet': False}, 'rectangle': {'showArea': True, 'metric': True, 'feet': False}, 'marker': False, 'circlemarker': False}, edit_options={'edit': False, 'remove': False }).add_to(m)

    print("Renderizando mapa con st_folium...")
    map_output = st_folium(m, key="map1", width='100%', height=600, returned_objects=["map_center", "map_zoom"])
    print("Mapa renderizado.")

    if map_output:
        new_center = map_output.get("map_center")
        if new_center and isinstance(new_center, list) and len(new_center) == 2:
            if new_center != st.session_state.map_center:
                st.session_state.map_center = new_center
        elif new_center: print(f"WARN: map_center recibido de st_folium no es válido: {new_center}")

        new_zoom = map_output.get("map_zoom")
        if new_zoom and isinstance(new_zoom, (int, float)):
             if new_zoom != st.session_state.map_zoom:
                 st.session_state.map_zoom = new_zoom
        elif new_zoom: print(f"WARN: map_zoom recibido de st_folium no es válido: {new_zoom}")

        print("\n--- ESTADO DESPUÉS DE INTERACCIÓN MAPA ---")
        print(f"Centro Actual en State: {st.session_state.get('map_center')}")
        print(f"Zoom Actual en State: {st.session_state.get('map_zoom')}")
        print("--- FIN ESTADO DESPUÉS DE INTERACCIÓN ---\n")
        print(f"Fin del bloque map_output. Solo se actualizó centro/zoom si cambiaron.")

    st.header("4. Datos Filtrados para Visualización")
    st.metric("Registros Mostrados en Mapa", len(df_final_display))
    if not df_final_display.empty:
        cols_prio = ['RBD', 'NOM_RBD', 'programa', 'MAT_TOTAL', 'COD_DEPE', 'COD_DEPE2']; cols_geo = ['LATITUD', 'LONGITUD']; cols_prog_details = ['CONVENIO_PIE', 'PACE']
        cols_display_ordered = [c for c in cols_prio + cols_geo + cols_prog_details if c in df_final_display.columns]
        st.dataframe(df_final_display[cols_display_ordered], height=300)
        st.markdown(get_table_download_link(df_final_display, "datos_filtrados_mapa.xlsx", "📊 Descargar Datos Visualizados (Excel)"), unsafe_allow_html=True)
    else:
        if len(df_filtered_widgets) == 0 and st.session_state.data_loaded:
            st.info("ℹ️ No hay establecimientos que coincidan con los filtros de la barra lateral.")
        else:
            st.info("ℹ️ No hay datos para mostrar. Ajusta filtros o carga un archivo.")

elif not st.session_state.data_loaded:
    st.info("👈 Sube un archivo Excel en la barra lateral para comenzar.")

print("--- Fin de la ejecución del script ---")