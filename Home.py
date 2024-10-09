import streamlit as st
import leafmap.foliumap as leafmap

st.set_page_config(layout="wide")

st.sidebar.title("About")
st.sidebar.info(
    """
    - Web App URL: <https://vertgis.streamlit.app>
    """
)

st.sidebar.title("Contact")
st.sidebar.info(
    """
    Picenni Kenzo [GitHub]() | [Twitter](https://x.com/dur_vert) | [YouTube]() | [LinkedIn](www.linkedin.com/in/kenzo-picenni-a56b8950)
    """
)

st.sidebar.title("Support")
st.sidebar.info(
    """
    If you want to reward my work, I'd love a cup of coffee from you. Thanks!
    
    """
)


st.title("VertGIS")

st.markdown(
    """
 Cette application web multi-pages illustre diverses applications interactives créées avec Streamlit et des bibliothèques de cartographie open-source telles que leafmap, geemap, pydeck et kepler.gl.
J'ai énormément appris de Sebastien Mischler, Olivier Donzé et Qiusheng Wu, dont les ressources ont été inestimables pour mon apprentissage. Ce projet est open-source et vous êtes vivement encouragés à contribuer avec vos commentaires, questions etc.

    """
)

st.info("Click on the left sidebar menu to navigate to the different apps.")

st.subheader("Timelapse of Satellite Imagery")
st.markdown(
    """
Description Timelapse app"""
)

row1_col1, row1_col2 = st.columns(2)
with row1_col1:
    st.image("https://github.com/giswqs/data/raw/main/timelapse/spain.gif")
    st.image("https://github.com/giswqs/data/raw/main/timelapse/las_vegas.gif")

with row1_col2:
    st.image("https://github.com/giswqs/data/raw/main/timelapse/goes.gif")
    st.image("https://github.com/giswqs/data/raw/main/timelapse/fire.gif")
