import streamlit as st
import folium
from streamlit_folium import folium_static
import geopandas as gpd
import requests
import json
import os
import tempfile
import urllib.request
from osgeo import gdal
import numpy as np
from shapely.geometry import box
from branca.element import Template, MacroElement
import nested_lookup

# Configuration de GDAL
gdal.UseExceptions()

# Configuration de la page Streamlit
st.set_page_config(layout="wide", page_title="SwissScape")

# Définition des couches disponibles
LAYERS = {
    "Swissimage 10cm": "ch.swisstopo.swissimage-dop10",
    "Cadastre": "ch.swisstopo.amtliches-gebaeudeadressverzeichnis",
    "Voirie": "ch.swisstopo.swisstlm3d-strassen",
    "Végétation": "ch.bafu.bundesinventare-waldreservate",
    "Hydrographie": "ch.swisstopo.vec25-gewaessernetz",
    "Zones de protection du paysage": "ch.bafu.bundesinventare-landschaften",
    "Parcs": "ch.bafu.schutzgebiete-paerke_nationaler_bedeutung",
    "Inventaire fédéral des sites construits": "ch.bak.bundesinventar-schuetzenswerte-ortsbilder",
}

# Formats de papier standard
PAPER_FORMATS = {
    "A4": (210, 297),
    "A3": (297, 420),
    "A2": (420, 594),
    "A1": (594, 841),
    "A0": (841, 1189),
}

@st.cache_data
def getitems(productname, LLlon, LLlat, URlon, URlat, first100=0):
    itemsrequest = requests.get(f"https://data.geo.admin.ch/api/stac/v0.9/collections/{productname}/items?bbox={LLlon},{LLlat},{URlon},{URlat}")
    itemsresult = json.loads(itemsrequest.content)
    assets = nested_lookup.nested_lookup('assets', itemsresult)
    
    if len(itemsresult['links']) >= 6:
        morethan100 = 1
    else:
        morethan100 = 0
    
    if len(itemsresult['links']) >= 6 and first100 == 0:
        pagination = 1
        while pagination == 1:
            nextpage = itemsresult['links'][5]['href']
            itemsrequest = requests.get(nextpage)
            itemsresult = json.loads(itemsrequest.content)
            assets = np.append(assets, nested_lookup.nested_lookup('assets', itemsresult))
            
            if len(itemsresult['links']) >= 6 and itemsresult['links'][5]['rel'] == 'next':
                pagination = 1
            else:
                pagination = 0
                assets = assets.tolist()
    
    itemsfiles = nested_lookup.nested_lookup('href', assets)
    
    # Filtrage spécifique pour certains produits
    if "_krel_" in productname:
        itemsfiles = [i for i in itemsfiles if "_krel_" in i]
    elif "swissimage" in productname:
        itemsfiles = [i for i in itemsfiles if "_0.1_" in i]
    elif "swissalti3d" in productname:
        itemsfiles = [i for i in itemsfiles if ".tif" in i and "_0.5_" in i]
    
    return itemsfiles, morethan100

def download_file(url, output_path):
    urllib.request.urlretrieve(url, output_path)

def merge_rasters(input_files, output_file):
    vrt_options = gdal.BuildVRTOptions(resampleAlg='cubic', addAlpha=True)
    vrt = gdal.BuildVRT("/vsimem/merged.vrt", input_files, options=vrt_options)
    gdal.Translate(output_file, vrt, format="GTiff", creationOptions=["COMPRESS=LZW", "PREDICTOR=2"])
    vrt = None

class PrintFormatControl(MacroElement):
    def __init__(self):
        super(PrintFormatControl, self).__init__()
        self._template = Template("""
            {% macro script(this, kwargs) %}
            var printFormatControl = L.control({position: 'topright'});
            printFormatControl.onAdd = function (map) {
                var div = L.DomUtil.create('div', 'print-format-control');
                div.innerHTML = `
                    <select id="paper-format">
                        <option value="A4">A4</option>
                        <option value="A3">A3</option>
                        <option value="A2">A2</option>
                        <option value="A1">A1</option>
                        <option value="A0">A0</option>
                    </select>
                    <input type="number" id="scale" value="1000" min="1" step="100">
                    <button id="apply-format">Appliquer</button>
                `;
                L.DomEvent.disableClickPropagation(div);
                return div;
            };
            printFormatControl.addTo({{ this._parent.get_name() }});

            document.getElementById('apply-format').addEventListener('click', function() {
                var format = document.getElementById('paper-format').value;
                var scale = parseInt(document.getElementById('scale').value);
                var center = {{ this._parent.get_name() }}.getCenter();
                var paperSizes = {
                    'A4': [210, 297],
                    'A3': [297, 420],
                    'A2': [420, 594],
                    'A1': [594, 841],
                    'A0': [841, 1189]
                };
                var size = paperSizes[format];
                var widthMeters = size[0] / 1000 * scale;
                var heightMeters = size[1] / 1000 * scale;
                var bounds = [
                    [center.lat - heightMeters/2/111320, center.lng - widthMeters/2/(111320*Math.cos(center.lat*Math.PI/180))],
                    [center.lat + heightMeters/2/111320, center.lng + widthMeters/2/(111320*Math.cos(center.lat*Math.PI/180))]
                ];
                if (window.rectangleLayer) {
                    {{ this._parent.get_name() }}.removeLayer(window.rectangleLayer);
                }
                window.rectangleLayer = L.rectangle(bounds, {
                    color: "#ff7800",
                    weight: 1,
                    draggable: true,
                    transform: true
                }).addTo({{ this._parent.get_name() }});
                window.rectangleLayer.on('dragend', function(e) {
                    window.rectangleLayer.setBounds(e.target.getBounds());
                });
                {{ this._parent.get_name() }}.fitBounds(bounds);
            });
            {% endmacro %}
        """)

def main():
    st.title("SwissScape")

    st.markdown("""
    SwissScape est un outil pour les paysagistes permettant de générer des fonds de plans personnalisés.
    Utilisez la carte interactive pour définir votre zone d'intérêt, choisissez vos options, et exportez votre fond de plan.
    """)

    col1, col2 = st.columns([3, 1])

    with col1:
        m = folium.Map(location=[46.8182, 8.2275], zoom_start=8)
        folium.TileLayer(
            tiles="https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.pixelkarte-farbe/default/current/3857/{z}/{x}/{y}.jpeg",
            attr="© swisstopo",
            name="swisstopo",
            overlay=False,
            control=True
        ).add_to(m)

        draw = folium.plugins.Draw(
            export=True,
            position="topleft",
            draw_options={
                "rectangle": True,
                "polyline": False,
                "polygon": False,
                "circle": False,
                "marker": False,
                "circlemarker": False,
            }
        )
        draw.add_to(m)

        m.add_child(PrintFormatControl())

        folium_static(m, width=800, height=600)

    with col2:
        st.subheader("Options d'export")

        uploaded_file = st.file_uploader("Uploader un GeoJSON (optionnel)", type=["geojson"])
        
        if uploaded_file is not None:
            gdf = gpd.read_file(uploaded_file)
            bbox = gdf.total_bounds
            m.fit_bounds([[bbox[1], bbox[0]], [bbox[3], bbox[2]]])

        selected_layers = st.multiselect("Sélectionnez les couches:", list(LAYERS.keys()), default=["Swissimage 10cm"])

        export_format = st.selectbox("Format d'export:", ["GeoTIFF", "GeoPackage"])

        if st.button("Générer le fond de plan"):
            bbox = None
            if uploaded_file is not None:
                bbox = gdf.total_bounds.tolist()
            else:
                last_active_drawing = st.session_state.get('last_active_drawing')
                if last_active_drawing and 'bounds' in last_active_drawing:
                    bounds = last_active_drawing['bounds']
                    bbox = [bounds['_southWest']['lng'], bounds['_southWest']['lat'], 
                            bounds['_northEast']['lng'], bounds['_northEast']['lat']]

            if bbox:
                with st.spinner('Génération du fond de plan en cours...'):
                    try:
                        with tempfile.TemporaryDirectory() as temp_dir:
                            downloaded_files = []
                            for layer in selected_layers:
                                product = LAYERS[layer]
                                items, _ = getitems(product, bbox[0], bbox[1], bbox[2], bbox[3])
                                for i, item_url in enumerate(items):
                                    file_path = os.path.join(temp_dir, f"{layer}_{i}.tif")
                                    download_file(item_url, file_path)
                                    downloaded_files.append(file_path)
                            
                            if downloaded_files:
                                if export_format == "GeoTIFF":
                                    output_path = os.path.join(temp_dir, "fond_de_plan.tif")
                                    merge_rasters(downloaded_files, output_path)
                                else:  # GeoPackage
                                    output_path = os.path.join(temp_dir, "fond_de_plan.gpkg")
                                    gdf = gpd.GeoDataFrame({'geometry': [box(*bbox)]}, crs="EPSG:4326")
                                    for file in downloaded_files:
                                        with rasterio.open(file) as src:
                                            gdf[os.path.basename(file)] = [src.read(1)]
                                    gdf.to_file(output_path, driver="GPKG")

                                with open(output_path, "rb") as file:
                                    btn = st.download_button(
                                        label=f"Télécharger le fond de plan ({export_format})",
                                        data=file,
                                        file_name=f"fond_de_plan.{export_format.lower()}",
                                        mime=f"application/{export_format.lower()}"
                                    )
                                
                                # Afficher un aperçu
                                preview = gdal.Open(output_path)
                                preview_array = preview.ReadAsArray()
                                if len(preview_array.shape) > 2:
                                    preview_array = np.transpose(preview_array, (1, 2, 0))
                                st.image(preview_array, caption="Aperçu du fond de plan", use_column_width=True)
                            else:
                                st.error("Aucune image n'a pu être récupérée. Veuillez vérifier votre sélection de couches et la zone d'intérêt.")

                    except Exception as e:
                        st.error(f"Une erreur s'est produite : {str(e)}")
            else:
                st.warning("Veuillez dessiner un rectangle sur la carte ou uploader un GeoJSON pour définir la zone d'intérêt.")

if __name__ == "__main__":
    main()