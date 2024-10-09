import streamlit as st
import geopandas as gpd
import folium
from folium import plugins
import requests
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

# Configuration de la page Streamlit
st.set_page_config(layout="wide")

# Liste mise à jour des dates disponibles pour SWISSIMAGE Voyage dans le temps
AVAILABLE_DATES = [
    1946, 1959, 
    *range(1965, 1968),  # 1965-1967
    *range(1970, 1975),  # 1970-1974
    *range(1976, 1983),  # 1976-1982
    *range(1983, 1989),  # 1983-1988
    *range(1989, 1993),  # 1989-1992
    *range(1993, 1998),  # 1993-1997
    *range(1998, 2003),  # 1998-2002
    *range(2003, 2008),  # 2003-2007
    *range(2008, 2012),  # 2008-2011
    *range(2012, 2016),  # 2012-2015
    *range(2016, 2020),  # 2016-2019
    *range(2020, 2024)   # 2020-2023
]

# URL de base pour le service WMS
WMS_BASE_URL = "https://wms.geo.admin.ch/"

@st.cache_data
def uploaded_file_to_gdf(data):
    import tempfile
    import os
    import uuid

    _, file_extension = os.path.splitext(data.name)
    file_id = str(uuid.uuid4())
    file_path = os.path.join(tempfile.gettempdir(), f"{file_id}{file_extension}")

    with open(file_path, "wb") as file:
        file.write(data.getbuffer())

    if file_path.lower().endswith(".kml"):
        gdf = gpd.read_file(file_path, driver="KML")
    else:
        gdf = gpd.read_file(file_path)

    return gdf

@lru_cache(maxsize=128)
def get_wms_url(bbox, width, height, time):
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetMap",
        "LAYERS": "ch.swisstopo.swissimage-product",
        "FORMAT": "image/jpeg",
        "CRS": "EPSG:2056",
        "BBOX": ",".join(map(str, bbox)),
        "WIDTH": str(width),
        "HEIGHT": str(height),
        "TIME": str(time)
    }
    return WMS_BASE_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items())

def add_date_to_image(image, date):
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    text = str(date)
    
    bbox = draw.textbbox((0, 0), text, font=font)
    textwidth = bbox[2] - bbox[0]
    textheight = bbox[3] - bbox[1]
    
    margin = 10
    x = image.width - textwidth - margin
    y = image.height - textheight - margin
    draw.rectangle((x-5, y-5, x+textwidth+5, y+textheight+5), fill="black")
    draw.text((x, y), text, font=font, fill="white")
    return image

async def fetch_image(session, url, date, semaphore):
    async with semaphore:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.read()
                    img = Image.open(BytesIO(data))
                    return add_date_to_image(img, date)
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de l'image pour la date {date}: {str(e)}")
    return None

async def download_images(bbox, width, height, available_years):
    semaphore = asyncio.Semaphore(20)  # Limité à 20 requêtes simultanées
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_image(session, get_wms_url(bbox, width, height, year), year, semaphore) for year in available_years]
        return await asyncio.gather(*tasks)

def process_images_stream(images, format_option, speed, temp_dir):
    results = {}

    if "GIF" in format_option:
        gif_path = os.path.join(temp_dir, "timelapse.gif")
        with imageio.get_writer(gif_path, mode='I', fps=speed, loop=0) as writer:
            for img in images:
                if img is not None:
                    writer.append_data(np.array(img))
        results["GIF"] = gif_path

    if "MP4" in format_option:
        mp4_path = os.path.join(temp_dir, "timelapse.mp4")
        with imageio.get_writer(mp4_path, fps=speed, quality=9) as writer:
            for img in images:
                if img is not None:
                    writer.append_data(np.array(img))
        results["MP4"] = mp4_path

    if "Images individuelles (ZIP)" in format_option:
        zip_path = os.path.join(temp_dir, "images.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for i, img in enumerate(images):
                if img is not None:
                    img_path = os.path.join(temp_dir, f"image_{i}.png")
                    img.save(img_path)
                    zipf.write(img_path, os.path.basename(img_path))
                    os.remove(img_path)
        results["ZIP"] = zip_path

    return results

def get_binary_file_downloader_html(bin_file, file_label='File'):
    with open(bin_file, 'rb') as f:
        data = f.read()
    bin_str = base64.b64encode(data).decode()
    href = f'<a href="data:application/octet-stream;base64,{bin_str}" download="{os.path.basename(bin_file)}">Télécharger {file_label}</a>'
    return href

def app():
    st.title("Générateur de Timelapse SWISSIMAGE Voyage dans le temps (WMS)")

    st.markdown(
        """
        Une application web interactive pour créer des timelapses historiques de la Suisse en utilisant SWISSIMAGE Voyage dans le temps via WMS.
        """
    )

    row1_col1, row1_col2 = st.columns([2, 1])

    with row1_col1:
        m = folium.Map(location=[46.8182, 8.2275], zoom_start=8)
        folium.TileLayer(
            tiles="https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.swissimage/default/current/3857/{z}/{x}/{y}.jpeg",
            attr="© swisstopo",
            name="SWISSIMAGE",
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
            start_year = st.selectbox("Sélectionnez l'année de début:", AVAILABLE_DATES)
            end_year = st.selectbox("Sélectionnez l'année de fin:", AVAILABLE_DATES, index=len(AVAILABLE_DATES)-1)
            
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

        if submitted:
            if data is None:
                st.warning("Veuillez télécharger un fichier GeoJSON.")
            elif width * height > 4000 * 4000:
                st.error("La taille de l'image dépasse le maximum autorisé par swisstopo (4000x4000 pixels). Veuillez réduire la largeur ou la hauteur.")
            else:
                gdf = uploaded_file_to_gdf(data)
                gdf_2056 = gdf.to_crs(epsg=2056)
                bbox = tuple(gdf_2056.total_bounds)

                available_years = [year for year in AVAILABLE_DATES if start_year <= year <= end_year]
                
                progress_bar = st.progress(0)
                
                images = asyncio.run(download_images(bbox, width, height, available_years))
                
                progress_bar.progress(100)

                if images:
                    logger.info(f"Récupération réussie de {len(images)} images")
                    with tempfile.TemporaryDirectory() as temp_dir:
                        with st.spinner('Traitement des images en cours... Cela peut prendre un certain temps pour les grandes images.'):
                            results = process_images_stream(images, format_option, speed, temp_dir)

                        for format, path in results.items():
                            if os.path.exists(path):
                                if format == "ZIP":
                                    st.success("Images individuelles (ZIP) créées avec succès!")
                                else:
                                    st.success(f"Timelapse {format} créé avec succès!")
                                st.markdown(get_binary_file_downloader_html(path, f'Timelapse {format if format != "ZIP" else "Images individuelles (ZIP)"}'), unsafe_allow_html=True)
                            else:
                                st.error(f"Le fichier {format} n'a pas été créé avec succès.")
                else:
                    logger.error("Aucune image n'a été récupérée")
                    st.error("Échec de la création du timelapse. Aucune image n'a été générée.")

if __name__ == "__main__":
    app()