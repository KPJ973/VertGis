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
from datetime import datetime
from streamlit_folium import folium_static
import base64
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import logging
import numpy as np

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration de la page Streamlit
st.set_page_config(layout="wide")

# Liste des dates disponibles
AVAILABLE_DATES = [
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

@st.cache_data
def uploaded_file_to_gdf(data):
    """
    Convertit le fichier uploadé en GeoDataFrame.
    
    Args:
        data: Le fichier uploadé par l'utilisateur.
    
    Returns:
        GeoDataFrame: Le GeoDataFrame créé à partir du fichier uploadé.
    """
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
    """
    Génère l'URL pour la requête WMS.
    
    Args:
        bbox: La bounding box de la zone d'intérêt.
        width: La largeur de l'image.
        height: La hauteur de l'image.
        time: La date pour laquelle récupérer l'image.
    
    Returns:
        str: L'URL complète pour la requête WMS.
    """
    url = "https://wms.geo.admin.ch/"
    params = {
        "SERVICE": "WMS",
        "REQUEST": "GetMap",
        "VERSION": "1.3.0",
        "LAYERS": "ch.swisstopo.zeitreihen",
        "STYLES": "",
        "CRS": "EPSG:2056",
        "BBOX": ",".join(map(str, bbox)),
        "WIDTH": str(width),
        "HEIGHT": str(height),
        "FORMAT": "image/png",
        "TIME": str(time),
        "TILED": "true"
    }
    return url + "?" + "&".join(f"{k}={v}" for k, v in params.items())

def add_date_to_image(image, date):
    """
    Ajoute la date à l'image.
    
    Args:
        image: L'image à modifier.
        date: La date à ajouter à l'image.
    
    Returns:
        Image: L'image modifiée avec la date ajoutée.
    """
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    text = str(date // 10000)  # Extraire seulement l'année
    
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
    """
    Récupère une image de manière asynchrone.
    
    Args:
        session: La session aiohttp.
        url: L'URL de l'image à récupérer.
        date: La date correspondant à l'image.
        semaphore: Le sémaphore pour limiter les requêtes simultanées.
    
    Returns:
        Image: L'image récupérée et modifiée, ou None en cas d'erreur.
    """
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
    """
    Télécharge les images de manière asynchrone.
    
    Args:
        bbox: La bounding box de la zone d'intérêt.
        width: La largeur des images.
        height: La hauteur des images.
        available_years: Les années disponibles pour le téléchargement.
    
    Returns:
        list: Une liste des images téléchargées.
    """
    semaphore = asyncio.Semaphore(20)  # Limité à 20 requêtes simultanées
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_image(session, get_wms_url(bbox, width, height, date), date, semaphore) for date in available_years]
        return await asyncio.gather(*tasks)

def process_images_stream(images, format_option, speed, temp_dir):
    """
    Traite les images en utilisant une approche par flux pour optimiser l'utilisation de la mémoire.
    
    Args:
        images: La liste des images à traiter.
        format_option: Les options de format choisies par l'utilisateur.
        speed: La vitesse de lecture des images (en FPS).
        temp_dir: Le répertoire temporaire pour stocker les fichiers générés.
    
    Returns:
        dict: Un dictionnaire contenant les chemins des fichiers générés.
    """
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

    if "Individual Images (ZIP)" in format_option:
        zip_path = os.path.join(temp_dir, "images.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for i, img in enumerate(images):
                if img is not None:
                    img_path = os.path.join(temp_dir, f"image_{i}.png")
                    img.save(img_path)
                    zipf.write(img_path, os.path.basename(img_path))
                    os.unlink(img_path)
        results["ZIP"] = zip_path

    return results

def get_binary_file_downloader_html(bin_file, file_label='File'):
    """
    Génère le HTML pour le téléchargement d'un fichier binaire.
    
    Args:
        bin_file: Le chemin du fichier binaire.
        file_label: Le label à afficher pour le lien de téléchargement.
    
    Returns:
        str: Le HTML pour le lien de téléchargement.
    """
    with open(bin_file, 'rb') as f:
        data = f.read()
    bin_str = base64.b64encode(data).decode()
    href = f'<a href="data:application/octet-stream;base64,{bin_str}" download="{os.path.basename(bin_file)}">Télécharger {file_label}</a>'
    return href

def app():
    """
    Fonction principale de l'application Streamlit.
    """
    st.title("Générateur de Timelapse Historique Suisse")

    st.markdown(
        """
        Une application web interactive pour créer des timelapses historiques de la Suisse en utilisant WMS-Time.
        """
    )

    row1_col1, row1_col2 = st.columns([2, 1])

    with row1_col1:
        m = folium.Map(location=[46.8182, 8.2275], zoom_start=8)
        folium.TileLayer(
            tiles="https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.pixelkarte-farbe/default/current/3857/{z}/{x}/{y}.jpeg",
            attr="© swisstopo",
            name="swisstopo",
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
            start_year = st.selectbox("Sélectionnez l'année de début:", [date // 10000 for date in AVAILABLE_DATES])
            end_year = st.selectbox("Sélectionnez l'année de fin:", [date // 10000 for date in AVAILABLE_DATES], index=len(AVAILABLE_DATES)-1)
            
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

                available_years = [date for date in AVAILABLE_DATES if start_year <= date // 10000 <= end_year]
                
                total_requests = len(available_years)
                
                if total_requests > 500:
                    st.warning(f"Vous demandez {total_requests} images. Cela dépasse la limite de 500 requêtes par seconde fixée par swisstopo. Le processus peut prendre plus de temps que prévu.")
                
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
                                if format == "GIF":
                                    st.success("Timelapse GIF créé avec succès!")
                                    st.image(path)
                                elif format == "MP4":
                                    st.success("Timelapse MP4 créé avec succès!")
                                    st.video(path)
                                elif format == "ZIP":
                                    st.success("Images individuelles sauvegardées avec succès!")
                                st.markdown(get_binary_file_downloader_html(path, f'Timelapse {format}'), unsafe_allow_html=True)
                            else:
                                st.error(f"Le fichier {format} n'a pas été créé avec succès.")
                else:
                    logger.error("Aucune image n'a été récupérée")
                    st.error("Échec de la création du timelapse. Aucune image n'a été générée.")

if __name__ == "__main__":
    app ()