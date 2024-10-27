import streamlit as st
import geopandas as gpd
import folium
from folium import plugins
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import imageio
import tempfile
import os
import zipfile
from streamlit_folium import folium_static
import base64
import asyncio
import aiohttp
from functools import lru_cache
import logging
import numpy as np

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(layout="wide")

# Listes des dates disponibles pour chaque type de carte
ORTHO_DATES = [
    1946, 1959, 
    *range(1965, 1968),
    *range(1970, 1975),
    *range(1976, 1983),
    *range(1983, 1989),
    *range(1989, 1993),
    *range(1993, 1998),
    *range(1998, 2003),
    *range(2003, 2008),
    *range(2008, 2012),
    *range(2012, 2016),
    *range(2016, 2020),
    *range(2020, 2024)
]

MAP_DATES = [
    18641231, 18701231, 18801231, 18901231, 18941231, 18951231, 18961231, 18971231, 18981231, 18991231,
    19001231, 19011231, 19021231, 19031231, 19041231, 19051231, 19061231, 19071231, 19081231, 19091231,
    19101231, 19111231, 19121231, 19131231, 19141231, 19151231, 19161231, 19171231, 19181231, 19191231,
    19201231, 19211231, 19221231, 19231231, 19241231, 19251231, 19261231, 19271231, 19281231, 19291231,
    19301231, 19311231, 19321231, 19331231, 19341231, 19351231, 19361231, 19371231, 19381231, 19391231,
    19401231, 19411231, 19421231, 19431231, 19441231, 19451231, 19461231, 19471231, 19481231, 19491231,
    19501231, 19511231, 19521231, 19531231, 19541231, 19551231, 19561231, 19571231, 19581231, 19591231,
    19601231, 19611231, 19621231, 19631231, 19641231, 19651231, 19661231, 19671231, 19681231, 19691231,
    19701231, 19711231, 19721231, 19731231, 19741231, 19751231, 19761231, 19771231, 19781231, 19791231,
    19801231, 19811231, 19821231, 19831231, 19841231, 19851231, 19861231, 19871231, 19881231, 19891231,
    19901231, 19911231, 19921231, 19931231, 19941231, 19951231, 19961231, 19971231, 19981231, 19991231,
    20001231, 20011231, 20021231, 20031231, 20041231, 20051231, 20061231, 20071231, 20081231, 20091231,
    20101231, 20111231, 20121231, 20131231, 20141231, 20151231, 20161231, 20171231, 20181231, 20191231,
    20201231, 20211231
]

# Extraire les années uniques de MAP_DATES
MAP_YEARS = sorted(set(date // 10000 for date in MAP_DATES))

# URL de base pour les services WMS
ORTHO_WMS_BASE_URL = "https://wms.geo.admin.ch/?LAYERS=ch.swisstopo.swissimage-product&FORMAT=image/jpeg"
MAP_WMS_BASE_URL = "https://wms.geo.admin.ch/?LAYERS=ch.swisstopo.zeitreihen&FORMAT=image/png"

@lru_cache(maxsize=128)
def get_wms_url(bbox, width, height, time, mode):
    base_url = ORTHO_WMS_BASE_URL if mode == "Orthophotos" else MAP_WMS_BASE_URL
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetMap",
        "CRS": "EPSG:2056",
        "BBOX": ",".join(map(str, bbox)),
        "WIDTH": str(width),
        "HEIGHT": str(height),
        "TIME": str(time)
    }
    return base_url + "&" + "&".join(f"{k}={v}" for k, v in params.items())

def app():
    st.title("Générateur de Timelapse Suisse (Orthophotos et Cartes historiques)")

    mode = st.selectbox("Sélectionnez le type de données :", ["Orthophotos", "Cartes historiques"])
    available_dates = ORTHO_DATES if mode == "Orthophotos" else MAP_YEARS

    row1_col1, row1_col2 = st.columns([2, 1])

    with row1_col1:
        m = folium.Map(location=[46.8182, 8.2275], zoom_start=8)
        layer_name = "SWISSIMAGE" if mode == "Orthophotos" else "Cartes historiques"
        folium.TileLayer(
            tiles="https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.pixelkarte-farbe/default/current/3857/{z}/{x}/{y}.jpeg",
            attr="© swisstopo",
            name=layer_name,
            overlay=False,
            control=True
        ).add_to(m)
        draw = plugins.Draw(export=True)
        draw.add_to(m)
        folium.LayerControl().add_to(m)
        folium_static(m, height=400)

    with row1_col2:
        data = st.file_uploader(
            "Téléchargez un fichier GeoJSON à utiliser comme ROI. Personnalisez les paramètres du timelapse puis cliquez sur le bouton Soumettre 😇👇",
            type=["geojson", "kml", "zip"],
        )

        with st.form("submit_form"):
            start_year = st.selectbox("Sélectionnez l'année de début:", available_dates)
            end_year = st.selectbox("Sélectionnez l'année de fin:", available_dates, index=len(available_dates)-1)
            
            size_options = {
                "HD (720p)": (1280, 720),
                "Full HD (1080p)": (1920, 1080),
                "2K": (2560, 1440),
                "4K": (3840, 2160),
                "Personnalisé": None
            }
            size_choice = st.selectbox("Choisissez la taille de l'image:", list(size_options.keys()))
            
            if size_choice == "Personnalisé":
                col1, col2 = st.columns(2)
                with col1:
                    width = st.number_input("Largeur:", min_value=100, max_value=4000, value=800)
                with col2:
                    height = st.number_input("Hauteur:", min_value=100, max_value=4000, value=600)
            else:
                width, height = size_options[size_choice]
            
            if width * height > 4000 * 4000:
                st.warning("Attention: La taille de l'image dépasse le maximum autorisé par swisstopo (4000x4000 pixels). Veuillez réduire la largeur ou la hauteur.")
            
            speed = st.slider("Images par seconde:", 1, 30, 5)
            format_option = st.multiselect("Choisissez le(s) format(s) de sortie:", ["GIF", "MP4", "Images individuelles (ZIP)"], default=["GIF", "MP4", "Images individuelles (ZIP)"])

            submitted = st.form_submit_button("Générer le Timelapse")

        if submitted and data is not None:
            # Conversion des années en dates complètes pour les cartes
            if mode == "Cartes historiques":
                start_date = next(date for date in MAP_DATES if date // 10000 == start_year)
                end_date = next(date for date in MAP_DATES if date // 10000 == end_year)
                available_years = [date for date in MAP_DATES if start_date <= date <= end_date]
            else:
                available_years = [year for year in ORTHO_DATES if start_year <= year <= end_year]

            # Suite du code pour générer les timelapses...

if __name__ == "__main__":
    app()
