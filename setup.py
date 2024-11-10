from PyQt5.QtWidgets import *
from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWebEngineWidgets import *
from http.server import SimpleHTTPRequestHandler, HTTPServer
import threading
import sys
import os
import geemap
import ee
from geopy.geocoders import GoogleV3
import leafmap
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import pandas as pd
import numpy as np


class MapWidget(QWebEngineView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.initUI()
        
    def initUI(self):
        
        # 建立一個空白的 Leafmap 地圖
        Map = leafmap.Map()

        # 保存地圖為 HTML
        self.html_file = "map.html"
        Map.to_html(outfile=self.html_file)

        # 使用 QWebEngineView 加載 HTML 文件
        self.load(QUrl(f"file:///{self.html_file}"))
        
    def search(self, loc, year, month):
        self.lat, self.lon = loc
        self.year = year
        self.month = month

        try:
            ee.Initialize()
        except ee.EEException:
            ee.Authenticate()
            ee.Initialize()

        aoi = ee.Geometry.Polygon(
            [[
                [self.lon-0.5, self.lat+0.5],  
                [self.lon-0.5, self.lat-0.5],  
                [self.lon+0.5, self.lat-0.5],  
                [self.lon+0.5, self.lat+0.5]  
            ]]
        )
        oi = ee.Geometry.Point([self.lon, self.lat])

        front_time = f'{self.year}-{self.month}-01'
        if self.month == 12:
            back_time = f'{self.year}-01-01'
        else:
            back_time = f'{self.year}-{self.month+1}-01'
            
        #sentinel-2
        sentinel2 = ee.ImageCollection('COPERNICUS/S2_HARMONIZED') \
            .filterDate(front_time, back_time) \
            .filterBounds(aoi) \
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20)) \
            .median()

        # NDVI = (NIR - RED) / (NIR + RED)
        ndvi = sentinel2.normalizedDifference(['B8', 'B4']).rename('NDVI')
        ndvi_vis_params = {
            'min': 0,
            'max': 1,
            'palette': ['white', 'yellow', 'green']
        }
        
        # 計算NDWI
        ndwi = sentinel2.normalizedDifference(['B3', 'B8']).rename('NDWI')
        ocean_mask = ndwi.gt(0)
        ndvi = ndvi.updateMask(ocean_mask.Not())
        def get_ndvi_mean(ndvi_image, roi):
            stats = ndvi_image.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=roi,
                scale=10,
                maxPixels=1e9
            )
            return stats.get('NDVI').getInfo()
        self.ndvi_index = get_ndvi_mean(ndvi, aoi)
        
        #no2
        no2 = ee.ImageCollection('COPERNICUS/S5P/OFFL/L3_NO2') \
            .filterDate(front_time, back_time) \
            .filterBounds(aoi) \
            .select('tropospheric_NO2_column_number_density') \
            .median() 
        no2_vis_params = {
            'min': 0, 
            'max': 0.0002, 
            'palette': ['green', 'yellow', 'red']
        }
        
        #AAI
        # aai = ee.ImageCollection('COPERNICUS/S5P/OFFL/L3_AER_AI') \
        #     .filterDate(front_time, back_time) \
        #     .filterBounds(aoi) \
        #     .select('absorbing_aerosol_index') \
        #     .median()
        # aai_vis_params = {
        #     'min': 0,
        #     'max': 1,
        #     'palette': ['blue', 'green', 'yellow', 'red']
        # }
        
        #AOD
        # aod = ee.ImageCollection('MODIS/006/MOD04_L2') \
        #     .filterDate(front_time, back_time) \
        #     .filterBounds(aoi) \
        #     .select('Optical_Depth_Land_And_Ocean') \
        #     .median()
        # aod_vis_params = {
        #     'min': 0,
        #     'max': 500,
        #     'palette': ['blue', 'green', 'yellow', 'orange', 'red']
        # }
        
        #relative temperature
        swir = sentinel2.select('B11')
        swir_vis_params = {
            'min': 500,
            'max': 4000,
            'palette': ['blue', 'lightblue', 'green', 'yellow', 'orange', 'red']
        }
        def get_swir_index(swir, aoi):
            median_temp = swir.reduceRegion(
                reducer=ee.Reducer.median(),
                geometry=aoi,
                scale=30,
                bestEffort=True
            ).get('B11').getInfo()

            percentile_90_temp = swir.reduceRegion(
                reducer=ee.Reducer.percentile([90]),
                geometry=aoi,
                scale=30,
                bestEffort=True
            ).get('B11').getInfo()
            
            uhii = percentile_90_temp - median_temp
            return uhii
        self.uhii_index = get_swir_index(swir, aoi)
        
        # 建立地圖
        Map = geemap.Map()
        Map.centerObject(oi, 12)
        
        Map.addLayer(ndvi.clip(aoi), ndvi_vis_params, 'NDVI', opacity=0.8)
        Map.addLayer(no2.clip(aoi), no2_vis_params, 'NO2 Concentration',opacity=0.6)
        Map.addLayer(swir.clip(aoi), swir_vis_params, 'Land Surface Temperature', opacity=0.5)
        
        Map.toolbar_reset()
        # Map.addLayer(aod.clip(aoi), aod_vis_params, 'AOD', opacity= 0.7)
        # Map.addLayer(aai.clip(aoi), aai_vis_params, 'absorbing_aerosol_index', opacity=1.0) 
        # Map.add_colorbar(cmap='jet', label='NO2 Concentration', position= "bottomright", layer_name='NO2 Concentration')

        # 保存地圖為 HTML
        self.html_file = "map.html"
        Map.to_html(filename=self.html_file)
        

        # 使用本地伺服器加載 HTML 文件
        self.load(QUrl(f"http://localhost:8000/{self.html_file}"))

class TimeWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
    
    def initUI(self):
        
        time_layout = QHBoxLayout()
        self.year_label = QLabel('Year: ')
        self.year = QComboBox(self)
        self.year.addItems(['2018', '2019', '2020', '2021', '2022', '2023', '2024'])
        self.year_int = 2018
        self.year.activated[str].connect(self.year_clicked)
        time_layout.addWidget(self.year_label)
        time_layout.addWidget(self.year)
        
        self.month_label = QLabel('Month: ')
        self.month = QComboBox(self)
        self.month.addItems([str(i) for i in range(1,13)])
        self.month_int = 1
        self.month.activated[str].connect(self.month_clicked)
        time_layout.addWidget(self.month_label)
        time_layout.addWidget(self.month)

        self.setLayout(time_layout)
        
    def year_clicked(self, text):
        self.year_int = int(text)
    
    def month_clicked(self, text):
        self.month_int = int(text)

class PlaceWidget(QWidget):
    def __init__(self, map_widget, time_widget, graph_widget):
        super().__init__()
        
        self.map_widget = map_widget
        self.time_widget = time_widget
        self.graph_widget = graph_widget
        
        self.initUI()
    
    def initUI(self):
        
        place_layout = QHBoxLayout()
        
        self.place_label = QLabel('Location: ')
        self.place = QLineEdit(self)
        
        place_layout.addWidget(self.place_label)
        place_layout.addWidget(self.place)

        
        search_layout = QHBoxLayout()
        
        self.search_button = QPushButton('Search', self)
        self.search_button.clicked.connect(self.search)
        self.compare_button = QPushButton('save current place to compare', self)
        self.compare_button.clicked.connect(self.savetocompare)
        
        search_layout.addWidget(self.search_button)
        search_layout.addWidget(self.compare_button)
        
        self.annoucement = QLabel('Failed to find location')
        self.annoucement.hide()
        
        layout = QVBoxLayout()
        layout.addLayout(place_layout)
        layout.addLayout(search_layout)
        
        self.setLayout(layout)
        

    def search(self):
        self.location = self.place.text()
        loc = self.coordinate()
        if loc == 'error':
            self.annoucement.show()
        else:
            print(loc, self.time_widget.year_int, self.time_widget.month_int)
            self.map_widget.search(loc, self.time_widget.year_int, self.time_widget.month_int)
            # self.graph_widget.initUI()
            self.graph_widget.draw(f'{self.location}{self.time_widget.year_int}{self.time_widget.month_int:02d}', self.map_widget.ndvi_index, self.map_widget.uhii_index)
    
    def coordinate(self):
        try:
                    geolocator = GoogleV3(api_key='AIzaSyAdmbZaOPZsgNEhdn9cPQFDf1V5gYbirIQ')
                    location = geolocator.geocode(self.location)
                    lat = location.latitude
                    lon = location.longitude
                    return (lat, lon)

        except:
                return 'error'
    

    def savetocompare(self):
        self.graph_widget.data_df = self.graph_widget.df.copy()

class Compare_table(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.initUI()
        
    def initUI(self):
        pass

class Graph(QTableWidget):
    def __init__(self):
        super().__init__()
        
        self.data_df = pd.DataFrame({
            'City': ['New York', 'Singapore', 'Geneva', 'Reykjavik', 'Helsinki', 'Berlin', 
                    'Mumbai', 'Beijing', 'Tokyo', 'Cape Town'],
            'NDVI': [0.23583329861041075, 0.10641166559503078, 0.40702656960408284, 0.26761786652820935,
                    0.1577286401005873, 0.45167407360320716, 0.14118880234119496, 0.3546502680103287, 
                    0.2492380238311336, 0.3488009536535482],
            'UHII': [633.9882109639525, 1535.2876075699746, 1662.0403757211448, 1920.4101185115046,
                    1151.20550443919, 893.4049136022957, 829.3112056261127, 703.1508130982556,
                    958.6969784101211, 2560.929500607322]
        })
        
        self.initUI()
        
    def initUI(self):

        layout = QHBoxLayout()
        
        self.tabs = QTabWidget()
        # Create two tabs with Matplotlib plots
        self.ndvi_tab = MatplotlibWidget()
        self.tabs.addTab(self.ndvi_tab, 'NDVI')

        self.uhii_tab = MatplotlibWidget()
        self.tabs.addTab(self.uhii_tab, 'UHII')
        
        layout.addWidget(self.tabs)
        self.setLayout(layout)
        

    def draw(self, name, ndvi, uhii):
        new_city = {'City': name, 'NDVI': ndvi, 'UHII': uhii}
        self.df = self.data_df.copy()
        self.df.loc[-1] = new_city
        self.df.index = self.df.index + 1  
        self.df = self.df.sort_index()
        
        self.ndvi_tab.plot_ndvi(self.df)
        self.uhii_tab.plot_uhii(self.df)

class MatplotlibWidget(QWidget):
    def __init__(self, parent=None):
        super(MatplotlibWidget, self).__init__(parent)
        
        self.initUI()    
    
    def initUI(self):
        self.canvas = FigureCanvas(plt.figure())
        self.layout = QVBoxLayout(self)
        self.layout.addWidget(self.canvas)

    def plot_ndvi(self,df):
        self.canvas.figure.clear()
        ax = self.canvas.figure.add_subplot(111)
        ax.clear()
        ax.set_ylabel('NDVI', color='tab:blue')
        ax.bar(df['City'], df['NDVI'], color='tab:blue', label='NDVI')
        ax.tick_params(axis='y', labelcolor='tab:blue')
        ax.set_title('NDVI Comparison(2024-10)')
        ax.set_xticklabels(df['City'], rotation=45, ha='right')
        self.canvas.draw()

    def plot_uhii(self,df):
        self.canvas.figure.clear()
        ax2 = self.canvas.figure.add_subplot(111)
        ax2.clear()
        ax2.set_ylabel('UHII base on SWIR', color='tab:red')
        ax2.bar(df['City'], df['UHII'], color='tab:red', label='UHII')
        ax2.tick_params(axis='y', labelcolor='tab:red')
        ax2.set_title('UHII Comparison base on SWIR(2024-10)')
        ax2.set_xticklabels(df['City'], rotation=45, ha='right')
        self.canvas.draw()    
        
class GeoJsonHttpServer:
    def __init__(self, port=8000):
        self.port = port
        self.server = HTTPServer(('localhost', self.port), SimpleHTTPRequestHandler)
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.daemon = True

    def start(self):
        self.server_thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

class Leftside(QWidget):
    def __init__(self, map):
        super().__init__()
        
        self.map = map        
        self.initUI()
        
    def initUI(self):
        
        self.time = TimeWidget()
        self.graph = Graph()
        self.place = PlaceWidget(self.map, self.time, self.graph)
        
        vbox = QVBoxLayout()
        
        # 將小部件添加到布局中
        vbox.addWidget(self.time,1)
        vbox.addWidget(self.place,3)
        vbox.addWidget(self.graph,15)
        self.setLayout(vbox)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GUSI demonstration")
        self.setGeometry(100, 100, 1600, 1000)

        # 啟動本地伺服器
        self.server = GeoJsonHttpServer()
        self.server.start()

        # 創建布局
        hbox = QHBoxLayout()

        # 初始化自訂小部件
        self.map = MapWidget()
        self.leftside = Leftside(self.map)

        hbox.addWidget(self.map,1)
        hbox.addWidget(self.leftside,1)
        

        central_widget = QWidget()
        central_widget.setLayout(hbox)
        self.setCentralWidget(central_widget)

    def closeEvent(self, event):
        self.server.stop()
        super().closeEvent(event)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
