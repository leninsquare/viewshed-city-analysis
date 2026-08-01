import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


class _Dialog:
    Accepted = 1


class _ProgressDialog:
    def __init__(self, *_):
        pass

    def __getattr__(self, _):
        return lambda *_args, **_kwargs: None


qtcore = ModuleType("qgis.PyQt.QtCore")
qtcore.QCoreApplication = SimpleNamespace(translate=lambda _, text: text)
qtcore.Qt = SimpleNamespace(WindowModal=1)
qtgui = ModuleType("qgis.PyQt.QtGui")
qtgui.QIcon = lambda *_: None
qtgui.QColor = lambda *_: None
qtwidgets = ModuleType("qgis.PyQt.QtWidgets")
qtwidgets.QAction = qtwidgets.QApplication = object
qtwidgets.QFileDialog = qtwidgets.QMessageBox = object
qtwidgets.QDialog = _Dialog
qtwidgets.QProgressDialog = _ProgressDialog
pyqt = ModuleType("qgis.PyQt")
pyqt.QtCore, pyqt.QtGui, pyqt.QtWidgets = qtcore, qtgui, qtwidgets
core = ModuleType("qgis.core")
core.QgsMapLayer = SimpleNamespace(RasterLayer=1, VectorLayer=2)
core.QgsProcessingUtils = core.QgsRasterLayer = object
core.QgsColorRampShader = core.QgsRasterShader = object
core.QgsRasterBandStats = SimpleNamespace(Min=1, Max=2)
core.QgsRasterTransparency = object
core.QgsSingleBandPseudoColorRenderer = object
core.QgsWkbTypes = SimpleNamespace(PolygonGeometry=3)
core.QgsProject = SimpleNamespace(instance=lambda: project)
qgis = ModuleType("qgis")
qgis.PyQt = pyqt
handlers = ModuleType("vieshed_module.viewshed_module_handlers")
handlers.ViewshedCalculator = object
converter = ModuleType("vieshed_module.viewshed_module_converter")
converter.QgisLayerConverter = object

sys.modules.update(
    {
        "qgis": qgis,
        "qgis.PyQt": pyqt,
        "qgis.PyQt.QtCore": qtcore,
        "qgis.PyQt.QtGui": qtgui,
        "qgis.PyQt.QtWidgets": qtwidgets,
        "qgis.core": core,
        "vieshed_module.viewshed_module_converter": converter,
        "vieshed_module.viewshed_module_handlers": handlers,
    }
)

from vieshed_module.viewshed_module import ViewshedModule
import vieshed_module.viewshed_module as viewshed_module


class Combo:
    def __init__(self):
        self.items = []
        self.index = 0
        self.enabled = True

    def blockSignals(self, _):
        pass

    def clear(self):
        self.items.clear()

    def addItem(self, text, data=None):
        self.items.append((text, data))

    def addItems(self, items):
        self.items.extend((item, None) for item in items)

    def setCurrentIndex(self, index):
        self.index = index

    def currentData(self):
        return self.items[self.index][1]

    def currentIndex(self):
        return self.index

    def currentText(self):
        return self.items[self.index][0]

    def setEnabled(self, enabled):
        self.enabled = enabled


class Layer:
    def __init__(
        self, layer_id, name, layer_type, geometry=None, fields=(), source=""
    ):
        self._id, self._name = layer_id, name
        self._type, self._geometry, self._fields = layer_type, geometry, fields
        self._source = source

    def id(self):
        return self._id

    def name(self):
        return self._name

    def type(self):
        return self._type

    def geometryType(self):
        return self._geometry

    def fields(self):
        return [SimpleNamespace(name=lambda name=name: name) for name in self._fields]

    def source(self):
        return self._source


class Project:
    def __init__(self, layers):
        self.layers = {layer.id(): layer for layer in layers}

    def mapLayers(self):
        return self.layers

    def mapLayer(self, layer_id):
        return self.layers.get(layer_id)


project = Project(
    [
        Layer("dem", "DEM", 1),
        Layer("buildings", "Buildings", 2, 3, ("height", "floors")),
        Layer("roads", "Roads", 2, 1),
    ]
)


class ViewshedModuleTest(unittest.TestCase):
    def test_layer_and_field_filters(self):
        plugin = ViewshedModule.__new__(ViewshedModule)
        plugin.dlg = SimpleNamespace(
            dem_combo=Combo(), buildings_combo=Combo(), height_combo=Combo()
        )
        plugin._populate_layer_combos()

        self.assertEqual(plugin.dlg.dem_combo.items[1:], [("DEM", "dem")])
        self.assertEqual(
            plugin.dlg.buildings_combo.items[1:], [("Buildings", "buildings")]
        )
        self.assertFalse(plugin.dlg.height_combo.enabled)

        plugin.dlg.buildings_combo.setCurrentIndex(1)
        plugin._populate_height_fields()
        self.assertEqual(
            plugin.dlg.height_combo.items[1:], [("height", None), ("floors", None)]
        )
        self.assertTrue(plugin.dlg.height_combo.enabled)

    def test_additional_buildings_change_analysis_dem_only_when_checked(self):
        calc_project = Project(
            [
                Layer("dem", "DEM", 1, source="/tmp/dem.tif"),
                Layer("main", "Main", 2, 3, ("height",)),
                Layer("extra", "Extra", 2, 3, ("height",)),
            ]
        )

        def combo(data, text, index=0):
            value = Combo()
            value.addItem(text, data)
            value.index = index
            return value

        def height_combo():
            value = Combo()
            value.addItem("Select height field")
            value.addItem("height")
            value.index = 1
            return value

        class FakeCalculator:
            created = []

            def __init__(
                self,
                dem_path,
                buildings,
                height_field,
                output_path,
                **parameters,
            ):
                self.dem_path = Path(dem_path)
                self.observer_count = 0
                self.surface_built = False
                self.parameters = parameters
                self.created.append(self)

            def build_surface_model(self, dem_path, buildings):
                self.surface_built = True
                return [[1]], {"driver": "GTiff"}

            def calculate(self):
                raise RuntimeError("stop after selecting analysis DEM")

        class RasterWriter:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def write(self, *_):
                pass

        checked = SimpleNamespace(isChecked=lambda: True)
        plugin = ViewshedModule.__new__(ViewshedModule)
        plugin.dlg = SimpleNamespace(
            dem_combo=combo("dem", "DEM"),
            buildings_combo=combo("main", "Main"),
            height_combo=height_combo(),
            output_edit=SimpleNamespace(
                text=lambda: "/tmp/result.tif", setText=lambda *_: None
            ),
            run_button=SimpleNamespace(setEnabled=lambda *_: None),
        )
        plugin.additional_dlg = SimpleNamespace(
            result=lambda: _Dialog.Accepted,
            include_checkbox=checked,
            cut_background_checkbox=SimpleNamespace(isChecked=lambda: True),
            max_distance_spin=SimpleNamespace(value=lambda: 2500.0),
            observer_height_spin=SimpleNamespace(value=lambda: 1.7),
            buildings_combo=combo("extra", "Extra"),
            height_combo=height_combo(),
        )
        fake_rasterio = ModuleType("rasterio")
        fake_rasterio.open = lambda *_args, **_kwargs: RasterWriter()

        with (
            patch.object(viewshed_module.QgsProject, "instance", return_value=calc_project),
            patch.object(
                viewshed_module,
                "QgisLayerConverter",
                SimpleNamespace(
                    qgis_buildings_to_geodataframe=lambda layer, field: layer.id()
                ),
            ),
            patch.object(
                viewshed_module,
                "QApplication",
                SimpleNamespace(processEvents=lambda: None),
            ),
            patch.object(
                viewshed_module,
                "QMessageBox",
                SimpleNamespace(critical=lambda *_: None),
            ),
            patch.object(handlers, "ViewshedCalculator", FakeCalculator),
            patch.dict(sys.modules, {"rasterio": fake_rasterio}),
        ):
            plugin._calculate()
            self.assertEqual(len(FakeCalculator.created), 2)
            self.assertTrue(FakeCalculator.created[0].surface_built)
            self.assertEqual(FakeCalculator.created[1].dem_path.name, "surface.tif")
            self.assertEqual(FakeCalculator.created[1].exclusion_buildings, "extra")
            self.assertEqual(FakeCalculator.created[1].exclusion_buffer, 3.0)
            self.assertEqual(
                FakeCalculator.created[1].parameters,
                {"max_distance": 2500.0, "observer_height": 1.7},
            )

            FakeCalculator.created.clear()
            checked.isChecked = lambda: False
            plugin._calculate()
            self.assertEqual(len(FakeCalculator.created), 1)
            self.assertEqual(FakeCalculator.created[0].dem_path, Path("/tmp/dem.tif"))


if __name__ == "__main__":
    unittest.main()
