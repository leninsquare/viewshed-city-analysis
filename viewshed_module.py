import tempfile
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QApplication,
    QDialog,
    QFileDialog,
    QMessageBox,
    QProgressDialog,
)
from qgis.core import (
    QgsMapLayer,
    QgsRasterBandStats,
    QgsColorRampShader,
    QgsProcessingUtils,
    QgsProject,
    QgsRasterLayer,
    QgsRasterShader,
    QgsRasterTransparency,
    QgsSingleBandPseudoColorRenderer,
    QgsWkbTypes,
)

from .viewshed_module_dialog import AdditionalBuildingsDialog, ViewshedModuleDialog
from .viewshed_module_converter import QgisLayerConverter
from .viewshed_module_logging import get_logger


ICON_PATH = Path(__file__).with_name("icon.png")
LOGGER = get_logger(__name__)


class ViewshedModule:
    def __init__(self, iface):
        self.iface = iface
        self.actions = []
        self.menu = self.tr("&Urban viewshed")
        self.dlg = None
        self.additional_dlg = None

    def tr(self, message):
        return QCoreApplication.translate("ViewshedModule", message)

    def add_action(self, callback):
        action = QAction(QIcon(str(ICON_PATH)), "", self.iface.mainWindow())
        action.setToolTip(self.tr("Urban viewshed calculation"))
        action.triggered.connect(callback)
        self.iface.addToolBarIcon(action)
        self.actions.append(action)
        return action

    def initGui(self):
        self.add_action(self.run)

    def unload(self):
        for action in self.actions:
            self.iface.removeToolBarIcon(action)
            action.deleteLater()
        self.actions.clear()

        if self.dlg is not None:
            self.dlg.close()
            self.dlg.deleteLater()
            self.dlg = None
        if self.additional_dlg is not None:
            self.additional_dlg.close()
            self.additional_dlg.deleteLater()
            self.additional_dlg = None

    def _fill_layer_combo(self, combo, placeholder, layers):
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(placeholder)
        for layer in layers:
            combo.addItem(layer.name(), layer.id())
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _populate_layer_combos(self):
        layers = list(QgsProject.instance().mapLayers().values())
        raster_layers = [
            layer for layer in layers if layer.type() == QgsMapLayer.RasterLayer
        ]
        polygon_layers = [
            layer
            for layer in layers
            if layer.type() == QgsMapLayer.VectorLayer
            and layer.geometryType() == QgsWkbTypes.PolygonGeometry
        ]

        self._fill_layer_combo(
            self.dlg.dem_combo, self.tr("Select raster layer"), raster_layers
        )
        self._fill_layer_combo(
            self.dlg.buildings_combo,
            self.tr("Select polygon layer"),
            polygon_layers,
        )
        self._populate_height_fields()

    def _populate_height_fields(self):
        combo = self.dlg.height_combo
        layer_id = self.dlg.buildings_combo.currentData()
        layer = QgsProject.instance().mapLayer(layer_id) if layer_id else None

        combo.clear()
        combo.addItem(self.tr("Select height field"))
        if layer is not None:
            combo.addItems([field.name() for field in layer.fields()])
        combo.setEnabled(layer is not None)
        combo.setCurrentIndex(0)

    def _populate_additional_layers(self):
        polygon_layers = [
            layer
            for layer in QgsProject.instance().mapLayers().values()
            if layer.type() == QgsMapLayer.VectorLayer
            and layer.geometryType() == QgsWkbTypes.PolygonGeometry
        ]
        self._fill_layer_combo(
            self.additional_dlg.buildings_combo,
            self.tr("Select polygon layer"),
            polygon_layers,
        )
        self._populate_additional_height_fields()

    def _populate_additional_height_fields(self):
        enabled = self.additional_dlg.include_checkbox.isChecked()
        self.additional_dlg.cut_background_checkbox.setEnabled(enabled)
        buildings_combo = self.additional_dlg.buildings_combo
        buildings_combo.setEnabled(enabled)
        layer_id = buildings_combo.currentData() if enabled else None
        layer = QgsProject.instance().mapLayer(layer_id) if layer_id else None

        combo = self.additional_dlg.height_combo
        combo.clear()
        combo.addItem(self.tr("Select height field"))
        if layer is not None:
            combo.addItems([field.name() for field in layer.fields()])
        combo.setEnabled(layer is not None)
        combo.setCurrentIndex(0)

    def _accept_additional_buildings(self):
        if self.additional_dlg.include_checkbox.isChecked() and (
            not self.additional_dlg.buildings_combo.currentData()
            or self.additional_dlg.height_combo.currentIndex() == 0
        ):
            QMessageBox.warning(
                self.additional_dlg,
                self.tr("Missing input"),
                self.tr("Select additional buildings and height field"),
            )
            return
        self.additional_dlg.accept()

    def _show_additional_buildings(self):
        if self.additional_dlg is None:
            self.additional_dlg = AdditionalBuildingsDialog(
                self.iface.mainWindow()
            )
            self.additional_dlg.include_checkbox.toggled.connect(
                self._populate_additional_height_fields
            )
            self.additional_dlg.buildings_combo.currentIndexChanged.connect(
                self._populate_additional_height_fields
            )
            self.additional_dlg.cancel_button.clicked.connect(
                self.additional_dlg.reject
            )
            self.additional_dlg.add_button.clicked.connect(
                self._accept_additional_buildings
            )

        self._populate_additional_layers()
        self.additional_dlg.exec_()

    def _select_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self.dlg,
            self.tr("Save viewshed"),
            "",
            self.tr("GeoTIFF (*.tif *.tiff)"),
        )
        if path:
            self.dlg.output_edit.setText(path)

    def _style_result_layer(self, result_layer):
        provider = result_layer.dataProvider()
        statistics = provider.bandStatistics(
            1, QgsRasterBandStats.Min | QgsRasterBandStats.Max
        )
        maximum = float(statistics.maximumValue)
        minimum = 1.0 if maximum >= 1 else maximum

        ramp = QgsColorRampShader()
        ramp.setColorRampType(QgsColorRampShader.Interpolated)
        items = [
            QgsColorRampShader.ColorRampItem(minimum, QColor("#edf8fb"))
        ]
        if maximum > minimum:
            items.append(
                QgsColorRampShader.ColorRampItem(maximum, QColor("#810f7c"))
            )
        else:
            items[0] = QgsColorRampShader.ColorRampItem(
                maximum, QColor("#810f7c")
            )
        ramp.setColorRampItemList(items)

        shader = QgsRasterShader()
        shader.setRasterShaderFunction(ramp)
        renderer = QgsSingleBandPseudoColorRenderer(provider, 1, shader)
        renderer.setClassificationMin(minimum)
        renderer.setClassificationMax(maximum)
        renderer.setOpacity(0.75)

        transparent_values = {0.0}
        if provider.sourceHasNoDataValue(1):
            transparent_values.add(float(provider.sourceNoDataValue(1)))
        transparency = QgsRasterTransparency()
        entries = []
        for value in sorted(transparent_values):
            entry = QgsRasterTransparency.TransparentSingleValuePixel()
            entry.min = value
            entry.max = value
            entry.percentTransparent = 100
            entries.append(entry)
        transparency.setTransparentSingleValuePixelList(entries)
        renderer.setRasterTransparency(transparency)
        result_layer.setRenderer(renderer)
        LOGGER.info(
            "Result style applied: transparent=%s, color_range=%s..%s",
            sorted(transparent_values),
            minimum,
            maximum,
        )

    def _calculate(self):
        LOGGER.info("Calculation requested")
        dem_layer = QgsProject.instance().mapLayer(self.dlg.dem_combo.currentData())
        buildings_layer = QgsProject.instance().mapLayer(
            self.dlg.buildings_combo.currentData()
        )
        if dem_layer is None or buildings_layer is None:
            LOGGER.warning("Calculation stopped: DEM or buildings are not selected")
            QMessageBox.warning(
                self.dlg,
                self.tr("Missing input"),
                self.tr("Select DEM and buildings"),
            )
            return
        if self.dlg.height_combo.currentIndex() == 0:
            LOGGER.warning("Calculation stopped: height field is not selected")
            QMessageBox.warning(
                self.dlg,
                self.tr("Missing input"),
                self.tr("Select height field"),
            )
            return

        height_field = self.dlg.height_combo.currentText()
        output_path = self.dlg.output_edit.text().strip()
        if output_path:
            output_path = str(Path(output_path).with_suffix(".tif"))
        else:
            output_path = QgsProcessingUtils.generateTempFilename("viewshed.tif")

        LOGGER.info(
            "Inputs selected: DEM=%s, buildings=%s, height_field=%s, output=%s",
            dem_layer.name(),
            buildings_layer.name(),
            height_field,
            output_path,
        )
        self.dlg.run_button.setEnabled(False)
        progress = QProgressDialog(self.dlg)
        progress.setWindowTitle(self.tr("Viewshed calculation"))
        progress.setLabelText(self.tr("Preparing calculation..."))
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setCancelButton(None)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.show()

        def update_progress(value, message):
            progress.setValue(max(0, min(100, int(value))))
            progress.setLabelText(message)
            QApplication.processEvents()

        update_progress(0, self.tr("Preparing calculation..."))
        surface_directory = None
        try:
            LOGGER.info("Loading calculation handler")
            from .viewshed_module_handlers import ViewshedCalculator

            LOGGER.info("Converting primary buildings to GeoDataFrame")
            buildings = QgisLayerConverter.qgis_buildings_to_geodataframe(
                buildings_layer, height_field
            )
            LOGGER.info("Primary buildings converted: %s features", len(buildings))
            analysis_dem_path = dem_layer.source().split("|", 1)[0]
            additional_settings_accepted = (
                self.additional_dlg is not None
                and self.additional_dlg.result() == QDialog.Accepted
            )
            max_distance = (
                self.additional_dlg.max_distance_spin.value()
                if additional_settings_accepted
                else 4000.0
            )
            observer_height = (
                self.additional_dlg.observer_height_spin.value()
                if additional_settings_accepted
                else 0.0
            )
            LOGGER.info(
                "Analysis parameters: max_distance=%s m, observer_height=%s m",
                max_distance,
                observer_height,
            )
            use_additional = (
                additional_settings_accepted
                and self.additional_dlg.include_checkbox.isChecked()
            )
            if use_additional:
                LOGGER.info("Additional buildings are enabled")
                cut_background = (
                    self.additional_dlg.cut_background_checkbox.isChecked()
                )
                LOGGER.info(
                    "Background building mask is %s",
                    "enabled" if cut_background else "disabled",
                )
                additional_layer = QgsProject.instance().mapLayer(
                    self.additional_dlg.buildings_combo.currentData()
                )
                if (
                    additional_layer is None
                    or self.additional_dlg.height_combo.currentIndex() == 0
                ):
                    raise ValueError(
                        self.tr("Select additional buildings and height field")
                    )
                additional_height_field = (
                    self.additional_dlg.height_combo.currentText()
                )
                LOGGER.info(
                    "Converting additional buildings: layer=%s, height_field=%s",
                    additional_layer.name(),
                    additional_height_field,
                )
                additional_buildings = (
                    QgisLayerConverter.qgis_buildings_to_geodataframe(
                        additional_layer, additional_height_field
                    )
                )
                LOGGER.info(
                    "Additional buildings converted: %s features",
                    len(additional_buildings),
                )
                surface_builder = ViewshedCalculator(
                    analysis_dem_path,
                    additional_buildings,
                    additional_height_field,
                    output_path,
                )
                surface_builder.progress_callback = (
                    lambda value, message: update_progress(
                        value * 0.25, message
                    )
                )
                LOGGER.info("Building surface model from DEM and additional buildings")
                surface, profile = surface_builder.build_surface_model(
                    analysis_dem_path, additional_buildings
                )
                surface_directory = tempfile.TemporaryDirectory(
                    prefix="viewshed-surface-"
                )
                analysis_dem_path = Path(surface_directory.name) / "surface.tif"
                import rasterio

                LOGGER.info("Saving temporary surface model: %s", analysis_dem_path)
                with rasterio.open(analysis_dem_path, "w", **profile) as dst:
                    dst.write(surface, 1)
                LOGGER.info("Temporary surface model saved")
                calculation_start = 25
            else:
                LOGGER.info("Additional buildings are disabled; using original DEM")
                calculation_start = 0

            LOGGER.info("Starting visibility calculation with DEM=%s", analysis_dem_path)
            calculator = ViewshedCalculator(
                analysis_dem_path,
                buildings,
                height_field,
                output_path,
                max_distance=max_distance,
                observer_height=observer_height,
            )
            if use_additional and cut_background:
                calculator.exclusion_buildings = additional_buildings
                calculator.exclusion_buffer = 3.0
            calculator.progress_callback = (
                lambda value, message: update_progress(
                    calculation_start
                    + value * (95 - calculation_start) / 100,
                    message,
                )
            )
            result_path = calculator.calculate()
            LOGGER.info(
                "Visibility calculation finished: observers=%s, result=%s",
                calculator.observer_count,
                result_path,
            )
            LOGGER.info("Loading result raster into QGIS")
            update_progress(96, self.tr("Loading result raster into QGIS..."))
            result_layer = QgsRasterLayer(str(result_path), self.tr("Viewshed"))
            if not result_layer.isValid():
                raise RuntimeError(self.tr("QGIS could not open the result raster"))
            LOGGER.info("Applying result raster style")
            update_progress(98, self.tr("Applying result style..."))
            self._style_result_layer(result_layer)
            QgsProject.instance().addMapLayer(result_layer)
            self.dlg.output_edit.setText(str(result_path))
            LOGGER.info("Result layer added to QGIS project")
            update_progress(100, self.tr("Calculation completed"))
            QMessageBox.information(
                self.dlg,
                self.tr("Completed"),
                self.tr("Viewshed calculated from {} observer points").format(
                    calculator.observer_count
                ),
            )
        except Exception as error:
            LOGGER.exception("Calculation failed")
            QMessageBox.critical(self.dlg, self.tr("Calculation error"), str(error))
        finally:
            if surface_directory is not None:
                LOGGER.info("Removing temporary surface model")
                surface_directory.cleanup()
            progress.close()
            progress.deleteLater()
            self.dlg.run_button.setEnabled(True)
            LOGGER.info("Calculation workflow finished")

    def run(self):
        if self.dlg is None:
            self.dlg = ViewshedModuleDialog(self.iface.mainWindow())
            self.dlg.buildings_combo.currentIndexChanged.connect(
                self._populate_height_fields
            )
            self.dlg.browse_button.clicked.connect(self._select_output)
            self.dlg.additional_buildings_button.clicked.connect(
                self._show_additional_buildings
            )
            self.dlg.cancel_button.clicked.connect(self.dlg.reject)
            self.dlg.run_button.clicked.connect(self._calculate)

        self._populate_layer_combos()
        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()
