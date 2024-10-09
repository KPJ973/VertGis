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

def get_wms_image(bbox, width, height, time):
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
    response = requests.get(url, params=params)
    if response.status_code == 200:
        return Image.open(BytesIO(response.content))
    else:
        st.error(f"Failed to fetch image: {response.status_code}")
        return None

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

def get_binary_file_downloader_html(bin_file, file_label='File'):
    with open(bin_file, 'rb') as f:
        data = f.read()
    bin_str = base64.b64encode(data).decode()
    href = f'<a href="data:application/octet-stream;base64,{bin_str}" download="{os.path.basename(bin_file)}">Download {file_label}</a>'
    return href

def app():
    st.title("Swiss Historical Timelapse Generator")

    st.markdown(
        """
        An interactive web app for creating historical timelapses of Switzerland using WMS-Time.
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
            "Upload a GeoJSON file to use as an ROI. Customize timelapse parameters and then click the Submit button 😇👇",
            type=["geojson", "kml", "zip"],
        )

        with st.form("submit_form"):
            start_year = st.selectbox("Select start year:", [date // 10000 for date in AVAILABLE_DATES])
            end_year = st.selectbox("Select end year:", [date // 10000 for date in AVAILABLE_DATES], index=len(AVAILABLE_DATES)-1)
            
            width = st.slider("Image width:", 100, 1000, 800)
            height = st.slider("Image height:", 100, 1000, 600)
            
            speed = st.slider("Frames per second:", 1, 30, 5)

            format_option = st.radio("Choose output format:", ("GIF", "MP4", "Both"))

            submitted = st.form_submit_button("Generate Timelapse")

        if submitted:
            if data is None:
                st.warning("Please upload a GeoJSON file.")
            else:
                gdf = uploaded_file_to_gdf(data)
                gdf_2056 = gdf.to_crs(epsg=2056)
                bbox = gdf_2056.total_bounds

                available_years = [date for date in AVAILABLE_DATES if start_year <= date // 10000 <= end_year]
                images = []
                image_files = []

                progress_bar = st.progress(0)
                for i, date in enumerate(available_years):
                    img = get_wms_image(bbox, width, height, date)
                    if img:
                        img_with_date = add_date_to_image(img, date)
                        images.append(img_with_date)
                        
                        # Save individual image
                        img_file = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{date}.png")
                        img_with_date.save(img_file.name)
                        image_files.append(img_file.name)
                        
                    progress_bar.progress((i + 1) / len(available_years))

                if images:
                    if format_option in ["GIF", "Both"]:
                        with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as tmp_file:
                            imageio.mimsave(tmp_file.name, images, fps=speed, loop=0)
                            st.success("GIF Timelapse created successfully!")
                            st.image(tmp_file.name)
                            st.markdown(get_binary_file_downloader_html(tmp_file.name, 'Timelapse GIF'), unsafe_allow_html=True)

                    if format_option in ["MP4", "Both"]:
                        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
                            imageio.mimsave(tmp_file.name, images, fps=speed, format='FFMPEG')
                            st.success("MP4 Timelapse created successfully!")
                            st.video(tmp_file.name)
                            st.markdown(get_binary_file_downloader_html(tmp_file.name, 'Timelapse MP4'), unsafe_allow_html=True)
                    
                    # Create ZIP file with individual images
                    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_zip:
                        with zipfile.ZipFile(tmp_zip.name, 'w') as zipf:
                            for img_file in image_files:
                                zipf.write(img_file, os.path.basename(img_file))
                    
                    st.success("Individual images saved successfully!")
                    st.markdown(get_binary_file_downloader_html(tmp_zip.name, 'Individual Images (ZIP)'), unsafe_allow_html=True)
                    
                    # Clean up temporary image files
                    for img_file in image_files:
                        os.unlink(img_file)
                else:
                    st.error("Failed to create timelapse. No images were generated.")

if __name__ == "__main__":
    app()