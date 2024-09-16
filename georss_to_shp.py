import pandas as pd
import geopandas as gpd
import fiona
from bs4 import BeautifulSoup
import glob

input_file = glob.glob(r"C:\Users\shubh\Downloads\sisdpv2-TN_Tirunelveli_lulc_v2.xml")


#input_file = r"C:\Users\shubh\Downloads\lulc-TN_LULC50K_1516.xml"
output_file = input_file[:-4] + '.gpkg'
fiona.drvsupport.supported_drivers['GeoRSS'] = 'r'

gdf = gpd.read_file(input_file)

gdf['dec'] = gdf['description'].apply(lambda dec : {k.split(':')[0]:k.split(':')[1] for k in [li.text for li in BeautifulSoup(dec, 'lxml').find_all("li")]})
df = gdf['dec'].apply(pd.Series)
df['geometry'] = gdf['geometry']
gdf_2 = gpd.GeoDataFrame(df,geometry = df['geometry'])
gdf_2.to_file(output_file)
