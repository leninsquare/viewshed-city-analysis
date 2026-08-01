import json

import geopandas as gpd
from shapely.geometry import shape


class QgisLayerConverter:
    @staticmethod
    def qgis_buildings_to_geodataframe(layer, height_field):
        geometries = []
        heights = []

        for feature in layer.getFeatures():
            geometry = feature.geometry()
            if geometry is None or geometry.isEmpty():
                continue
            geometries.append(shape(json.loads(geometry.asJson())))
            heights.append(feature[height_field])

        return gpd.GeoDataFrame(
            {height_field: heights},
            geometry=geometries,
            crs=layer.crs().toWkt(),
        )
