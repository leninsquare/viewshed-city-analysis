import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box, mapping

from vieshed_module.viewshed_module_converter import QgisLayerConverter
from vieshed_module.viewshed_module_handlers import (
    SURFACE_NODATA,
    ViewshedCalculator,
    compute_visibility_raster_numba,
)


class ViewshedCalculatorTest(unittest.TestCase):
    def test_boundary_points_use_three_metre_step_and_include_vertices(self):
        geometry = box(0, 0, 10, 10)
        calculator = ViewshedCalculator(
            "dem.tif", None, "height", "viewshed.tif"
        )

        points = list(
            calculator._boundary_points(geometry, calculator.point_spacing)
        )
        coordinates = {(point.x, point.y) for point in points}
        distances = sorted(geometry.exterior.project(point) for point in points)
        gaps = [
            right - left for left, right in zip(distances, distances[1:])
        ]
        gaps.append(geometry.exterior.length - distances[-1] + distances[0])

        self.assertEqual(calculator.point_spacing, 3.0)
        self.assertTrue(
            {(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)}
            <= coordinates
        )
        self.assertLessEqual(max(gaps), 3.0)

    def test_surface_model_flattens_building_footprint(self):
        with tempfile.TemporaryDirectory() as directory:
            dem_path = Path(directory, "dem.tif")
            with rasterio.open(
                dem_path,
                "w",
                driver="GTiff",
                width=4,
                height=4,
                count=1,
                dtype=np.float32,
                crs="EPSG:3857",
                transform=from_origin(0, 40, 10, 10),
            ) as dst:
                dst.write(
                    np.array(
                        [
                            [10, 10, 10, 10],
                            [10, 20, 30, 10],
                            [10, 40, 50, 10],
                            [10, 10, 10, 0],
                        ],
                        dtype=np.float32,
                    ),
                    1,
                )

            buildings = gpd.GeoDataFrame(
                {"height": [10.0]},
                geometry=[box(10.1, 10.1, 29.9, 29.9)],
                crs="EPSG:3857",
            )
            calculator = ViewshedCalculator(
                dem_path,
                buildings,
                "height",
                Path(directory, "unused.tif"),
            )

            surface, profile = calculator.build_surface_model(dem_path, buildings)

            np.testing.assert_array_equal(surface[1:3, 1:3], 30)
            self.assertEqual(surface[3, 3], SURFACE_NODATA)
            self.assertEqual(profile["nodata"], SURFACE_NODATA)

    def test_njit_visibility_respects_obstacle(self):
        surface = np.array([[0, 10, 0, 0, 0]], dtype=np.float32)

        visible = compute_visibility_raster_numba(
            base_surface=surface,
            observer_rc=(0, 0),
            observer_height_abs=0.0,
            px_size=1.0,
        )

        np.testing.assert_array_equal(visible, [[0, 1, 0, 0, 0]])

    def test_qgis_building_conversion(self):
        polygon = box(0, 0, 10, 10)
        geometry = SimpleNamespace(
            isEmpty=lambda: False,
            asJson=lambda: json.dumps(mapping(polygon)),
        )

        class Feature:
            def geometry(self):
                return geometry

            def __getitem__(self, field):
                return 12.0

        layer = SimpleNamespace(
            getFeatures=lambda: [Feature()],
            crs=lambda: SimpleNamespace(toWkt=lambda: "EPSG:3857"),
        )

        result = QgisLayerConverter.qgis_buildings_to_geodataframe(layer, "height")
        self.assertEqual(result["height"].tolist(), [12.0])
        self.assertEqual(result.geometry.iloc[0], polygon)

    def test_calculation_writes_cumulative_viewshed(self):
        with tempfile.TemporaryDirectory() as directory:
            dem_path = Path(directory, "dem.tif")
            output_path = Path(directory, "viewshed.tif")
            with rasterio.open(
                dem_path,
                "w",
                driver="GTiff",
                width=9,
                height=9,
                count=1,
                dtype=np.float32,
                crs="EPSG:3857",
                transform=from_origin(0, 90, 10, 10),
            ) as dst:
                dem = np.full((9, 9), 10, dtype=np.float32)
                dem[0, 0] = 0
                dst.write(dem, 1)

            buildings = gpd.GeoDataFrame(
                {"height": [10.0]},
                geometry=[box(30, 30, 60, 60)],
                crs="EPSG:3857",
            )
            calculator = ViewshedCalculator(
                dem_path,
                buildings,
                "height",
                output_path,
                point_spacing=20,
                max_distance=50,
            )
            progress = []
            calculator.progress_callback = lambda value, message: progress.append(
                (value, message)
            )
            calculator.exclusion_buildings = buildings
            calculator.exclusion_buffer = 3.0

            self.assertEqual(calculator.calculate(), output_path)
            self.assertGreater(calculator.observer_count, 0)
            self.assertEqual(progress[-1][0], 100)
            with rasterio.open(output_path) as result:
                self.assertEqual(result.dtypes[0], "uint32")
                self.assertGreater(result.read(1, masked=True).max(), 0)
                self.assertTrue(result.read(1, masked=True).mask[0, 0])
                self.assertTrue(result.read(1, masked=True).mask[4, 4])


if __name__ == "__main__":
    unittest.main()
