import math
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

from .viewshed_module_logging import get_logger


LOGGER = get_logger(__name__)
"""
TOOLS_DIR = Path(__file__).with_name("tools")
platform_tools = {
    "darwin": TOOLS_DIR / "macos",
    "win32": TOOLS_DIR / "windows",
}.get(sys.platform)
if platform_tools and platform_tools.is_dir() and str(platform_tools) not in sys.path:
    sys.path.insert(0, str(platform_tools))
"""

"""
try:
    from numba import njit
except (ImportError, OSError) as error:
    LOGGER.exception("Failed to import Numba")
    raise ImportError(
        "Numba is required for the viewshed calculation. QGIS could not load "
        "the bundled llvmlite binary; install a QGIS-compatible Numba build."
    ) from error
"""

try:
    import rasterio
    from rasterio.features import geometry_window, rasterize
except (ImportError, OSError):
    LOGGER.exception("Failed to import Rasterio")
    raise
from shapely.geometry import MultiPolygon, Point, Polygon, box


SURFACE_NODATA = -3.4e38


#@njit
def ray_pixels(r0, c0, r1, c1):
    # returning pixels along ray
    dr = abs(r1 - r0)
    dc = abs(c1 - c0)
    step_r = 1 if r1 >= r0 else -1
    step_c = 1 if c1 >= c0 else -1
    pixels = []

    if dc > dr:
        err = dc // 2
        r = r0
        for c in range(c0, c1 + step_c, step_c):
            pixels.append((r, c))
            err -= dr
            if err < 0:
                r += step_r
                err += dc
    else:
        err = dr // 2
        c = c0
        for r in range(r0, r1 + step_r, step_r):
            pixels.append((r, c))
            err -= dc
            if err < 0:
                c += step_c
                err += dr
    return np.array(pixels, dtype=np.int32)


#@njit
def compute_visibility_raster_numba(
    base_surface, observer_rc, observer_height_abs, px_size, angle_bin_deg=0.5
):
    # making visibility binary raster

    R_EARTH = 6371000.0
    H, W = base_surface.shape
    visible = np.zeros((H, W), dtype=np.uint8)

    r0, c0 = observer_rc
    scene_radius = 2 * max(H, W)
    num_rays = int(360 / angle_bin_deg)

    for i in range(num_rays):
        angle = math.radians(i * angle_bin_deg)
        dr = math.sin(angle)
        dc = math.cos(angle)
        r_far = int(round(r0 + scene_radius * dr))
        c_far = int(round(c0 + scene_radius * dc))

        pixels = ray_pixels(r0, c0, r_far, c_far)
        max_alpha = -1e10

        for k in range(pixels.shape[0]):
            r, c = pixels[k, 0], pixels[k, 1]
            if r < 0 or r >= H or c < 0 or c >= W:
                continue
            d = math.hypot((r - r0) * px_size, (c - c0) * px_size)
            h_eff = base_surface[r, c] - d * d / (2 * R_EARTH)
            alpha_cell = math.atan2(h_eff - observer_height_abs, d) if d > 0 else -1e10
            if alpha_cell > max_alpha:
                visible[r, c] = 1
                max_alpha = alpha_cell
    return visible


class ViewshedCalculator:

    def __init__(
        self,
        dem_path,
        buildings,
        height_field,
        output_path,
        point_spacing=3.0,
        max_distance=4000.0,
        observer_height=0.0,
    ):
        self.dem_path = Path(dem_path)
        self.buildings = buildings
        self.height_field = height_field
        self.output_path = Path(output_path)
        self.point_spacing = float(point_spacing)
        self.max_distance = float(max_distance)
        self.observer_height = float(observer_height)
        self.observer_count = 0
        self.progress_callback = None
        self.exclusion_buildings = None
        self.exclusion_buffer = 3.0

    def _report_progress(self, value, message):
        if self.progress_callback is not None:
            self.progress_callback(value, message)

    def _validate(self):
        if not self.dem_path.is_file():
            raise FileNotFoundError(f"DEM not found: {self.dem_path}")
        if self.dem_path.resolve() == self.output_path.resolve():
            raise ValueError("Output path must differ from the DEM path")
        if self.buildings is None or self.buildings.empty:
            raise ValueError("Buildings layer is empty")
        if self.height_field not in self.buildings.columns:
            raise ValueError(f"Height field not found: {self.height_field}")
        if self.buildings.crs is None:
            raise ValueError("Buildings CRS is not defined")
        if self.point_spacing <= 0 or self.max_distance <= 0:
            raise ValueError("Point spacing and maximum distance must be positive")

    @staticmethod
    def _boundary_points(geometry, spacing):
        polygons = geometry.geoms if isinstance(geometry, MultiPolygon) else [geometry]
        for polygon in polygons:
            for ring in (polygon.exterior, *polygon.interiors):
                distances = {
                    float(distance)
                    for distance in np.arange(0.0, ring.length, spacing)
                }
                distances.update(
                    float(ring.project(Point(coordinate)))
                    for coordinate in list(ring.coords)[:-1]
                )
                for distance in sorted(distances):
                    yield ring.interpolate(float(distance))

    def build_surface_model(self, dem_path, buildings):
        dem_path = Path(dem_path)
        self._report_progress(0, "Preparing surface model...")
        LOGGER.info(
            "Surface model started: DEM=%s, buildings=%s, height_field=%s",
            dem_path,
            0 if buildings is None else len(buildings),
            self.height_field,
        )
        if not dem_path.is_file():
            raise FileNotFoundError(f"DEM not found: {dem_path}")
        if buildings is None or buildings.empty:
            raise ValueError("Buildings layer is empty")
        if buildings.crs is None:
            raise ValueError("Buildings CRS is not defined")
        if self.height_field not in buildings.columns:
            raise ValueError(f"Height field not found: {self.height_field}")

        with rasterio.open(dem_path) as src:
            if src.crs is None:
                raise ValueError("DEM CRS is not defined")
            LOGGER.info(
                "Surface DEM opened: size=%sx%s, CRS=%s",
                src.width,
                src.height,
                src.crs,
            )
            self._report_progress(15, "Opening elevation model...")

            buildings = buildings.to_crs(src.crs)
            LOGGER.info("Additional buildings reprojected to DEM CRS")
            self._report_progress(30, "Reprojecting additional buildings...")
            try:
                heights = buildings[self.height_field].astype(float)
            except (TypeError, ValueError) as error:
                raise ValueError("Building heights must be numeric") from error

            dem = src.read(1, masked=True)
            valid_dem = ~np.ma.getmaskarray(dem) & (dem.data != 0)
            terrain = dem.filled(0).astype(np.float32)
            surface = terrain.copy()
            dem_extent = box(*src.bounds)
            processed = 0
            LOGGER.info(
                "Surface DEM read: valid_cells=%s", int(valid_dem.sum())
            )
            self._report_progress(45, "Preparing terrain surface...")

            ordered_buildings = sorted(
                zip(buildings.geometry, heights), key=lambda item: item[1]
            )
            progress_step = max(1, len(ordered_buildings) // 10)
            for index, (geometry, height) in enumerate(
                ordered_buildings, start=1
            ):
                if (
                    index == 1
                    or index % progress_step == 0
                    or index == len(ordered_buildings)
                ):
                    self._report_progress(
                        45 + 50 * index / len(ordered_buildings),
                        f"Adding buildings to terrain: "
                        f"{index}/{len(ordered_buildings)}",
                    )
                if geometry is None or geometry.is_empty:
                    continue
                #if not geometry.is_valid or not isinstance(
                    #geometry, (Polygon, MultiPolygon)
                #):
                    #raise ValueError("Buildings must contain valid polygon geometries")
                if not np.isfinite(height) or height < 0:
                    raise ValueError(
                        "Building heights must be finite and non-negative"
                    )
                if not geometry.intersects(dem_extent):
                    continue

                window = geometry_window(src, [geometry])
                row_slice, col_slice = window.toslices()
                footprint = rasterize(
                    [(geometry, 1)],
                    out_shape=(int(window.height), int(window.width)),
                    transform=src.window_transform(window),
                    fill=0,
                    all_touched=True,
                    dtype=np.uint8,
                ).astype(bool)
                valid_footprint = footprint & valid_dem[row_slice, col_slice]
                if not valid_footprint.any():
                    continue

                terrain_window = terrain[row_slice, col_slice]
                surface_window = surface[row_slice, col_slice]
                base_elevation = terrain_window[valid_footprint].min()
                surface_window[valid_footprint] = base_elevation + float(height)
                processed += 1

            if not processed:
                raise ValueError("No buildings overlap valid DEM cells")

            surface[~valid_dem] = SURFACE_NODATA
            profile = src.profile.copy()
            profile.update(count=1, dtype=np.float32, nodata=SURFACE_NODATA)
            LOGGER.info(
                "Surface model completed: processed_buildings=%s", processed
            )
            self._report_progress(100, "Surface model completed")
            return surface, profile

    def calculate(self):
        self._report_progress(0, "Validating input data...")
        LOGGER.info(
            "Viewshed calculation started: DEM=%s, output=%s, buildings=%s, "
            "height_field=%s, point_spacing=%s, max_distance=%s",
            self.dem_path,
            self.output_path,
            0 if self.buildings is None else len(self.buildings),
            self.height_field,
            self.point_spacing,
            self.max_distance,
        )
        self._validate()
        LOGGER.info("Input validation completed")
        self._report_progress(5, "Input data validated")
        self.observer_count = 0
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        LOGGER.info("Output directory prepared: %s", self.output_path.parent)

        with rasterio.open(self.dem_path) as src:
            if src.crs is None or src.crs.is_geographic:
                raise ValueError("DEM must use a projected CRS")
            if not math.isclose(src.transform.b, 0.0) or not math.isclose(
                src.transform.d, 0.0
            ):
                raise ValueError("Rotated DEM rasters are not supported")
            LOGGER.info(
                "DEM opened: size=%sx%s, CRS=%s, pixel_size=(%s, %s)",
                src.width,
                src.height,
                src.crs,
                src.transform.a,
                src.transform.e,
            )
            self._report_progress(10, "Opening elevation model...")

            metres_per_unit = float(src.crs.linear_units_factor[1])
            spacing = self.point_spacing / metres_per_unit
            buildings = self.buildings.to_crs(src.crs)
            LOGGER.info("Primary buildings reprojected to DEM CRS")
            self._report_progress(15, "Reprojecting buildings...")

            try:
                heights = buildings[self.height_field].astype(float)
            except (TypeError, ValueError) as error:
                raise ValueError("Building heights must be numeric") from error

            records = []
            dem_extent = box(*src.bounds)
            for geometry, height in zip(buildings.geometry, heights):
                if (
                    geometry is None
                    or geometry.is_empty
                    or not geometry.intersects(dem_extent)
                ):
                    continue
                if not geometry.is_valid or not isinstance(
                    geometry, (Polygon, MultiPolygon)
                ):
                    raise ValueError("Buildings must contain valid polygon geometries")
                if not np.isfinite(height) or height < 0:
                    raise ValueError(
                        "Building heights must be finite and non-negative"
                    )
                records.append((geometry, float(height)))

            if not records:
                raise ValueError("No buildings intersect the DEM")

            records.sort(key=lambda item: item[1])
            LOGGER.info("Buildings intersecting DEM: %s", len(records))
            self._report_progress(20, "Rasterizing building heights...")
            dem = src.read(1, masked=True)
            valid_dem = ~np.ma.getmaskarray(dem) & (dem.data != 0)
            dem = dem.filled(0).astype(np.float32)
            building_heights = rasterize(
                records,
                out_shape=dem.shape,
                transform=src.transform,
                fill=0,
                all_touched=True,
                dtype=np.float32,
            )
            surface = dem + building_heights
            surface[~valid_dem] = SURFACE_NODATA
            LOGGER.info(
                "DEM and building heights combined: valid_cells=%s",
                int(valid_dem.sum()),
            )
            self._report_progress(30, "Creating analysis surface...")
            profile = src.profile.copy()
            transform = src.transform
            pixel_width = abs(transform.a) * metres_per_unit
            pixel_height = abs(transform.e) * metres_per_unit
            if not math.isclose(pixel_width, pixel_height):
                raise ValueError("DEM must have square pixels")
            observer_pixels = set()
            for geometry, _ in records:
                for point in self._boundary_points(geometry, spacing):
                    row, col = src.index(point.x, point.y)
                    if (
                        0 <= row < src.height
                        and 0 <= col < src.width
                        and valid_dem[row, col]
                    ):
                        observer_pixels.add((row, col))

        if not observer_pixels:
            raise ValueError("No boundary points fall inside the DEM")
        LOGGER.info("Observer points generated: %s", len(observer_pixels))
        self._report_progress(40, "Observer points prepared")

        result = np.zeros(surface.shape, dtype=np.uint32)
        row_radius = int(math.ceil(self.max_distance / pixel_height))
        col_radius = int(math.ceil(self.max_distance / pixel_width))
        ordered_observers = sorted(observer_pixels)
        progress_step = max(1, len(ordered_observers) // 10)
        LOGGER.info(
            "Visibility accumulation started: observers=%s, window_radius=(%s, %s)",
            len(ordered_observers),
            row_radius,
            col_radius,
        )

        for index, (row, col) in enumerate(ordered_observers, start=1):
            row_start = max(0, row - row_radius)
            row_stop = min(surface.shape[0], row + row_radius + 1)
            col_start = max(0, col - col_radius)
            col_stop = min(surface.shape[1], col + col_radius + 1)
            window = surface[row_start:row_stop, col_start:col_stop]
            observer_height = float(surface[row, col]) + self.observer_height
            visibility = compute_visibility_raster_numba(
                base_surface=window,
                observer_rc=(row - row_start, col - col_start),
                observer_height_abs=observer_height,
                px_size=pixel_width,
                angle_bin_deg=0.01,
            )
            result[row_start:row_stop, col_start:col_stop] += visibility
            self._report_progress(
                40 + 50 * index / len(ordered_observers),
                f"Calculating visibility: {index}/{len(ordered_observers)}",
            )
            if index == 1 or index % progress_step == 0 or index == len(
                ordered_observers
            ):
                LOGGER.info(
                    "Visibility progress: %s/%s observers",
                    index,
                    len(ordered_observers),
                )

        self.observer_count = len(observer_pixels)
        nodata = np.iinfo(np.uint32).max
        result[~valid_dem] = nodata
        if self.exclusion_buildings is not None:
            if self.exclusion_buildings.empty:
                raise ValueError("Background buildings layer is empty")
            if self.exclusion_buildings.crs is None:
                raise ValueError("Background buildings CRS is not defined")
            if self.exclusion_buffer < 0:
                raise ValueError("Background buildings buffer cannot be negative")

            self._report_progress(92, "Masking background buildings...")
            buffer_units = self.exclusion_buffer / metres_per_unit
            exclusion_buildings = self.exclusion_buildings.to_crs(profile["crs"])
            buffered_geometries = [
                geometry.buffer(buffer_units)
                for geometry in exclusion_buildings.geometry
                if geometry is not None and not geometry.is_empty
            ]
            if not buffered_geometries:
                raise ValueError("Background buildings contain no geometries")
            exclusion_mask = rasterize(
                [(geometry, 1) for geometry in buffered_geometries],
                out_shape=result.shape,
                transform=transform,
                fill=0,
                all_touched=True,
                dtype=np.uint8,
            ).astype(bool)
            result[exclusion_mask] = nodata
            LOGGER.info(
                "Background buildings masked: buffer=%s m, cells=%s",
                self.exclusion_buffer,
                int(exclusion_mask.sum()),
            )

        self._report_progress(95, "Writing result raster...")
        with tempfile.TemporaryDirectory(
            prefix=".viewshed-", dir=self.output_path.parent
        ) as temp_dir:
            result_path = Path(temp_dir, "result.tif")
            LOGGER.info("Writing result raster to temporary file: %s", result_path)
            profile.update(
                count=1, dtype=np.uint32, nodata=nodata, compress="deflate"
            )
            with rasterio.open(result_path, "w", **profile) as dst:
                dst.write(result, 1)
            os.replace(result_path, self.output_path)
            LOGGER.info("Result raster moved to: %s", self.output_path)

        LOGGER.info(
            "Viewshed calculation completed: observers=%s", self.observer_count
        )
        self._report_progress(100, "Visibility calculation completed")
        return self.output_path
