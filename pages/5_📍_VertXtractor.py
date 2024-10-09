import streamlit as st
import urllib
import json
from pathlib import Path
import datetime
import folium
from streamlit_folium import folium_static
import geopandas as gpd
import tempfile
import os

# Constants
CATEGORIES = {
    'Gebueschwald': 'Forêt buissonnante',
    'Wald': 'Forêt',
    'Wald offen': 'Forêt claisemée',
    'Gehoelzflaeche': 'Zone boisée',
}

MERGE_CATEGORIES = True
URL_STAC_SWISSTOPO_BASE = 'https://data.geo.admin.ch/api/stac/v0.9/collections/'
DIC_LAYERS = {
    'ortho': 'ch.swisstopo.swissimage-dop10',
    'mnt': 'ch.swisstopo.swissalti3d',
    'mns': 'ch.swisstopo.swisssurface3d-raster',
    'bati3D_v2': 'ch.swisstopo.swissbuildings3d_2',
    'bati3D_v3': 'ch.swisstopo.swissbuildings3d_3_0',
}

# Functions
def wgs84_to_lv95(lat, lon):
    url = f'http://geodesy.geo.admin.ch/reframe/wgs84tolv95?easting={lat}&northing={lon}&format=json'
    site = urllib.request.urlopen(url)
    data = json.load(site)
    return data['easting'], data['northing']

def lv95_to_wgs84(x, y):
    url = f'http://geodesy.geo.admin.ch/reframe/lv95towgs84?easting={x}&northing={y}&format=json'
    f = urllib.request.urlopen(url)
    txt = f.read().decode('utf-8')
    json_res = json.loads(txt)
    return json_res

def detect_and_convert_bbox(bbox):
    xmin, ymin, xmax, ymax = bbox
    wgs84_margin = 0.9
    wgs84_bounds = {
        'xmin': 5.96 - wgs84_margin,
        'ymin': 45.82 - wgs84_margin,
        'xmax': 10.49 + wgs84_margin,
        'ymax': 47.81 + wgs84_margin
    }
    lv95_margin = 100000
    lv95_bounds = {
        'xmin': 2485000 - lv95_margin,
        'ymin': 1075000 - lv95_margin,
        'xmax': 2834000 + lv95_margin,
        'ymax': 1296000 + lv95_margin
    }

    if (wgs84_bounds['xmin'] <= xmin <= wgs84_bounds['xmax'] and
        wgs84_bounds['ymin'] <= ymin <= wgs84_bounds['ymax'] and
        wgs84_bounds['xmin'] <= xmax <= wgs84_bounds['xmax'] and
        wgs84_bounds['ymin'] <= ymax <= wgs84_bounds['ymax']):
        lv95_min = wgs84_to_lv95(xmin, ymin)
        lv95_max = wgs84_to_lv95(xmax, ymax)
        bbox_lv95 = (lv95_min[0], lv95_min[1], lv95_max[0], lv95_max[1])
        return (bbox, bbox_lv95)
    
    if (lv95_bounds['xmin'] <= xmin <= lv95_bounds['xmax'] and
        lv95_bounds['ymin'] <= ymin <= lv95_bounds['ymax'] and
        lv95_bounds['xmin'] <= xmax <= lv95_bounds['xmax'] and
        lv95_bounds['ymin'] <= ymax <= lv95_bounds['ymax']):
        wgs84_min = lv95_to_wgs84(xmin, ymin)
        wgs84_max = lv95_to_wgs84(xmax, ymax)
        bbox_wgs84 = (wgs84_min['easting'], wgs84_min['northing'], wgs84_max['easting'], wgs84_max['northing'])
        return (bbox_wgs84, bbox)
    
    return None

def get_list_from_STAC_swisstopo(url, est, sud, ouest, nord, gdb=False):
    if gdb:
        lst_indesirables = []
    else:
        lst_indesirables = ['.xyz.zip', '.gdb.zip']
    
    sufixe_url = f"/items?bbox={est},{sud},{ouest},{nord}"
    url += sufixe_url
    res = []
    
    while url:
        f = urllib.request.urlopen(url)
        txt = f.read().decode('utf-8')
        json_res = json.loads(txt)
        url = None
        links = json_res.get('links', None)
        if links:
            for link in links:
                if link['rel'] == 'next':
                    url = link['href']
        for item in json_res['features']:
            for k, dic in item['assets'].items():
                href = dic['href']
                if gdb:
                    if href[-8:] == '.gdb.zip':
                        if len(dic['href'].split('/')[-1].split('_')) == 7:
                            res.append(dic['href'])
                else:
                    if href[-8:] not in lst_indesirables:
                        res.append(dic['href'])
    return res

def suppr_doublons_list_ortho(lst):
    dic = {}
    for url in lst:
        nom, an, noflle, taille_px, epsg = url.split('/')[-1][:-4].split('_')
        dic.setdefault((noflle, float(taille_px)), []).append((an, url))
    res = []
    for noflle, lst in dic.items():
        an, url = sorted(lst, reverse=True)[0]
        res.append(url)
    return res

def get_urls(bbox_wgs84, mnt=True, mns=True, bati3D_v2=True, bati3D_v3=True, ortho=True, mnt_resol=0.5, ortho_resol=0.1):
    est, sud, ouest, nord = bbox_wgs84
    urls = []

    if mnt:
        mnt_resol = 0.5 if mnt_resol < 2 else 2
        tri = f'_{mnt_resol}_'
        url = URL_STAC_SWISSTOPO_BASE + DIC_LAYERS['mnt']
        lst = [v for v in get_list_from_STAC_swisstopo(url, est, sud, ouest, nord) if tri in v]
        urls += lst

    if mns:
        url = URL_STAC_SWISSTOPO_BASE + DIC_LAYERS['mns']
        lst = [v for v in get_list_from_STAC_swisstopo(url, est, sud, ouest, nord) if 'raster' in v]
        urls += lst

    if bati3D_v2:
        url = URL_STAC_SWISSTOPO_BASE + DIC_LAYERS['bati3D_v2']
        lst = get_list_from_STAC_swisstopo(url, est, sud, ouest, nord)
        urls += lst

    if bati3D_v3:
        url = URL_STAC_SWISSTOPO_BASE + DIC_LAYERS['bati3D_v3']
        lst = get_list_from_STAC_swisstopo(url, est, sud, ouest, nord, gdb=True)
        urls += lst

    if ortho:
        ortho_resol = 0.1 if ortho_resol < 2 else 2
        tri = f'_{ortho_resol}_'
        url = URL_STAC_SWISSTOPO_BASE + DIC_LAYERS['ortho']
        lst = [v for v in get_list_from_STAC_swisstopo(url, est, sud, ouest, nord) if tri in v and v.endswith('.png')]
        lst = suppr_doublons_list_ortho(lst)
        urls += lst

    return urls

def classification_urls(urls):
    dic = {}
    for url in urls:
        fn = url.split('/')[-1]
        dirname = fn.split('_')[0]

        if dirname == 'swissbuildings3d':
            name, version, *a = fn.split('_')
            if version == '2':
                an = fn.split('_')[2].split('-')[0]
            elif version == '3':
                an = fn.split('_')[3]
            dirname = f'{name}_v{version}_{an}'
        elif dirname == 'swissalti3d':
            name, an, no_flle, resol, *a = fn.split('_')
            if resol == '0.5':
                resol = '50cm'
            elif resol == '2':
                resol = '2m'
            dirname = f'{name}_{an}_{resol}'
        elif dirname == 'swisssurface3d-raster':
            name, an, no_flle, resol, *a = fn.split('_')
            if resol == '0.5':
                resol = '50cm'
            dirname = f'{name}_{an}_{resol}'
        elif dirname == 'swissimage-dop10':
            name, an, no_flle, resol, *a = fn.split('_')
            if resol == '0.1':
                resol = '10cm'
            elif resol == '2':
                resol = '2m'
            dirname = f'{name}_{an}_{resol}_png'

        dic.setdefault(dirname, []).append((url, fn))
    return dic

def download_files(urls, path):
    now = datetime.datetime.now()
    path = Path(path) / f'swisstopo_extraction_{now.strftime("%Y%m%d_%H%M")}'
    path.mkdir(exist_ok=True)
    for k, v in classification_urls(urls).items():
        p = path / k
        p.mkdir(exist_ok=True)
        for url, fn in v:
            urllib.request.urlretrieve(url, p / fn)
    return path

def geojson_forest(bbox, fn_geojson):
    xmin, ymin, xmax, ymax = bbox
    url_base = 'https://hepiadata.hesge.ch/arcgis/rest/services/suisse/TLM_C4D_couverture_sol/FeatureServer/1/query?'
    sql = ' OR '.join([f"OBJEKTART='{cat}'" for cat in CATEGORIES.keys()])
    params = {
        "geometry": f"{xmin},{ymin},{xmax},{ymax}",
        "geometryType": "esriGeometryEnvelope",
        "returnGeometry": "true",
        "outFields": "OBJEKTART",
        "orderByFields": "OBJEKTART",
        "where": sql,
        "returnZ": "true",
        "outSR": '2056',
        "spatialRel": "esriSpatialRelIntersects",
        "f": "geojson"
    }
    query_string = urllib.parse.urlencode(params)
    url = url_base + query_string
    with urllib.request.urlopen(url) as response:
        response_data = response.read()
        data = json.loads(response_data)
    with open(fn_geojson, 'w') as f:
        json.dump(data, f)

# Streamlit app
st.set_page_config(page_title="Swiss Geospatial Data Downloader", layout="wide")
st.title("Swiss Geospatial Data Downloader")

# Sidebar for data selection
st.sidebar.header("Data Selection")
mnt = st.sidebar.checkbox("Digital Terrain Model (MNT)", value=True)
mns = st.sidebar.checkbox("Digital Surface Model (MNS)", value=True)
bati3D_v2 = st.sidebar.checkbox("3D Buildings v2", value=True)
bati3D_v3 = st.sidebar.checkbox("3D Buildings v3", value=True)
ortho = st.sidebar.checkbox("Orthophotos", value=True)
mnt_resol = st.sidebar.selectbox("MNT Resolution", [0.5, 2.0], index=0)
ortho_resol = st.sidebar.selectbox("Orthophoto Resolution", [0.1, 2.0], index=0)

# Main content area
st.subheader("Enter Bounding Box Coordinates")
col1, col2, col3, col4 = st.columns(4)
with col1:
    xmin = st.number_input("Min Longitude", value=6.0, step=0.1)
with col2:
    ymin = st.number_input("Min Latitude", value=46.0, step=0.1)
with col3:
    xmax = st.number_input("Max Longitude", value=10.0, step=0.1)
with col4:
    ymax = st.number_input("Max Latitude", value=47.0, step=0.1)

if st.button("Set Bounding Box"):
    st.session_state.bbox = [xmin, ymin, xmax, ymax]

if 'bbox' in st.session_state:
    st.write(f"Selected bounding box (WGS84): {st.session_state.bbox}")
    bbox_results = detect_and_convert_bbox(st.session_state.bbox)
    if bbox_results:
        bbox_wgs84, bbox_lv95 = bbox_results
        st.write(f"Converted bounding box (LV95): {bbox_lv95}")
        
        if st.button("Get Download Links"):
            with st.spinner("Fetching download links..."):
                urls = get_urls(bbox_wgs84, mnt, mns, bati3D_v2, bati3D_v3, ortho, mnt_resol, ortho_resol)
                if urls:
                    st.success(f"Found {len(urls)} files to download:")
                    for url in urls:
                        st.write(url)
                    
                    if st.button("Download Files"):
                        with st.spinner("Downloading files..."):
                            download_path = download_files(urls, "downloads")
                            st.success(f"Files downloaded to: {download_path}")
                else:
                    st.warning("No files found for the selected area and options.")
        
       # Option to download forest data
if st.button("Download Forest Data"):
    with st.spinner("Downloading forest data..."):
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.geojson') as tmp:
            geojson_forest(bbox_lv95, tmp.name)
            gdf = gpd.read_file(tmp.name)
            st.write(gdf)
            
            # Display the forest data on a map
            m = folium.Map(location=[(ymin + ymax) / 2, (xmin + xmax) / 2], zoom_start=10)
            folium.GeoJson(gdf).add_to(m)
            folium_static(m)
            
            # Option to download the GeoJSON file
            st.download_button(
                label="Download Forest GeoJSON",
                data=gdf.to_json(),
                file_name="forest_data.geojson",
                mime="application/json"
            )
            
            os.unlink(tmp.name)
        st.success("Forest data downloaded, displayed, and available for download.")

else:
    st.error("Selected area is outside Switzerland. Please select an area within Switzerland.")

# Add information about the app in the sidebar
st.sidebar.info("""
This application allows you to download various types of geospatial data for Switzerland. 
Select the data types you want, enter the bounding box coordinates, and click 'Get Download Links' to see available files.
You can also download forest data for the selected area.
""")

# Add a footer
st.markdown("""
---
Created with ❤️ by Your Name
""")