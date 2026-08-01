from pathlib import Path

from qgis.PyQt import QtCore, QtGui, QtWidgets


ASSETS_DIR = Path(__file__).with_name("assets")


DIALOG_STYLE = """
QDialog {
    background: #fbfbfb;
    color: #181818;
    font-family: "Anek Latin";
    font-size: 14px;
}
QLabel#title_label {
    color: #0b3eff;
    font-family: "Monomaniac One";
    font-size: 30px;
    letter-spacing: 1px;
}
QLabel#description_label {
    color: #707070;
    font-size: 12px;
}
QLabel#field_label {
    font-size: 15px;
}
QLabel#help_label {
    color: #707070;
    font-size: 11px;
}
QComboBox, QDoubleSpinBox, QLineEdit {
    min-height: 34px;
    padding: 0 11px;
    background: white;
    border: 1px solid #b1b1b1;
    border-radius: 4px;
}
QComboBox:disabled {
    color: #707070;
    background: #f2f2f2;
}
QPushButton {
    min-height: 34px;
    padding: 0 15px;
    background: white;
    border: 1px solid #b1b1b1;
    border-radius: 4px;
}
QPushButton:hover, QPushButton:pressed {
    color: white;
    background: #0b3eff;
    border-color: #0b3eff;
}
QPushButton#run_button, QPushButton#add_button {
    padding: 0;
    color: white;
    background: #0b3eff;
    border-color: #0b3eff;
}
QPushButton#cancel_button {
    padding: 0;
}
QPushButton#run_button:hover, QPushButton#add_button:hover {
    background: #092fd1;
}
QPushButton#more_info_button, QPushButton#additional_buildings_button {
    min-height: 24px;
    padding: 0;
    text-align: left;
    color: #0b3eff;
    font-family: "Monomaniac One";
    font-size: 14px;
    letter-spacing: 1px;
    background: transparent;
    border: none;
}
QPushButton#additional_buildings_button {
    text-align: center;
}
QPushButton#browse_button {
    padding: 0;
}
QLabel#footer_label {
    color: rgba(11, 62, 255, 96);
    font-family: "Monomaniac One";
    font-size: 10px;
    letter-spacing: 1px;
}
"""


class UiViewshedModule:
    def setupUi(self, dialog):
        self._load_fonts()
        dialog.setObjectName("viewshed_module")
        dialog.setFixedSize(520, 537)
        dialog.setWindowTitle("Urban viewshed calculation")
        dialog.setWindowIcon(QtGui.QIcon(str(Path(__file__).with_name("icon.png"))))

        self.main_layout = QtWidgets.QVBoxLayout(dialog)
        self.main_layout.setContentsMargins(34, 20, 34, 8)
        self.main_layout.setSpacing(0)

        self.title_label = QtWidgets.QLabel("Urban viewshed calculation")
        self.title_label.setObjectName("title_label")
        self.title_label.setFixedHeight(44)
        self.main_layout.addWidget(self.title_label)

        self.description_label = QtWidgets.QLabel(
            "Calculate visibility from terrain and building data."
        )
        self.description_label.setObjectName("description_label")
        self.description_label.setFixedHeight(18)
        self.main_layout.addWidget(self.description_label)
        self.main_layout.addSpacing(10)

        self.dem_combo = self._add_combo("Elevation model *", "Select raster layer")
        self.buildings_combo = self._add_combo("Buildings *", "Select polygon layer")
        self.height_combo = self._add_combo(
            "Height field *", "Select after choosing buildings", enabled=False
        )

        self.height_help_label = QtWidgets.QLabel(
            "Available after selecting a building layer"
        )
        self.height_help_label.setObjectName("help_label")
        self.main_layout.addWidget(self.height_help_label)
        self.main_layout.addSpacing(12)

        self.output_label = QtWidgets.QLabel("Output")
        self.main_layout.addWidget(self.output_label)
        self.main_layout.addSpacing(6)

        self.output_layout = QtWidgets.QHBoxLayout()
        self.output_layout.setSpacing(8)
        self.output_edit = QtWidgets.QLineEdit()
        self.output_edit.setPlaceholderText("Temporary layer")
        self.browse_button = QtWidgets.QPushButton("...")
        self.browse_button.setObjectName("browse_button")
        self.browse_button.setFixedSize(36, 36)
        self.output_layout.addWidget(self.output_edit)
        self.output_layout.addWidget(self.browse_button)
        self.main_layout.addLayout(self.output_layout)
        self.main_layout.addStretch()

        self.actions_layout = QtWidgets.QHBoxLayout()
        self.actions_layout.setSpacing(0)
        self.more_info_button = QtWidgets.QPushButton("More information")
        self.more_info_button.setObjectName("more_info_button")
        self.more_info_button.setFixedSize(150, 24)
        self.additional_buildings_button = QtWidgets.QPushButton(
            "Additional buildings"
        )
        self.additional_buildings_button.setObjectName(
            "additional_buildings_button"
        )
        self.additional_buildings_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.additional_buildings_button.setFixedSize(140, 24)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.setObjectName("cancel_button")
        self.cancel_button.setFixedWidth(68)
        self.run_button = QtWidgets.QPushButton("Run")
        self.run_button.setObjectName("run_button")
        self.run_button.setFixedWidth(70)
        self.actions_layout.addWidget(self.more_info_button)
        self.actions_layout.addWidget(self.additional_buildings_button)
        self.actions_layout.addStretch()
        self.actions_layout.addWidget(self.cancel_button)
        self.actions_layout.addSpacing(12)
        self.actions_layout.addWidget(self.run_button)
        self.main_layout.addLayout(self.actions_layout)
        self.main_layout.addSpacing(24)

        self.footer_label = QtWidgets.QLabel("made by @leninsquare, 2026")
        self.footer_label.setObjectName("footer_label")
        self.footer_label.setAlignment(QtCore.Qt.AlignCenter)
        self.footer_label.setFixedHeight(16)
        self.main_layout.addWidget(self.footer_label)

        dialog.setStyleSheet(DIALOG_STYLE)
        QtCore.QMetaObject.connectSlotsByName(dialog)

    def _add_combo(self, label, placeholder, enabled=True):
        label_widget = QtWidgets.QLabel(label)
        label_widget.setObjectName("field_label")
        label_widget.setFixedHeight(22)
        self.main_layout.addWidget(label_widget)
        self.main_layout.addSpacing(6)

        combo = QtWidgets.QComboBox()
        combo.addItem(placeholder)
        combo.setEnabled(enabled)
        combo.setFixedHeight(36)
        self.main_layout.addWidget(combo)
        self.main_layout.addSpacing(15)
        return combo

    @staticmethod
    def _load_fonts():
        for name in ("monomaniac-one.ttf", "anek-latin-regular.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(ASSETS_DIR / name))


class UiAdditionalBuildings(UiViewshedModule):
    def setupUi(self, dialog):
        self._load_fonts()
        dialog.setObjectName("additional_buildings")
        dialog.setFixedSize(520, 554)
        dialog.setWindowTitle("Additional buildings")
        dialog.setWindowIcon(QtGui.QIcon(str(Path(__file__).with_name("icon.png"))))

        self.main_layout = QtWidgets.QVBoxLayout(dialog)
        self.main_layout.setContentsMargins(34, 20, 34, 8)
        self.main_layout.setSpacing(0)

        self.title_label = QtWidgets.QLabel("Additional buildings")
        self.title_label.setObjectName("title_label")
        self.title_label.setFixedHeight(44)
        self.main_layout.addWidget(self.title_label)

        self.description_label = QtWidgets.QLabel(
            "Add another building layer and select its height field."
        )
        self.description_label.setObjectName("description_label")
        self.description_label.setFixedHeight(18)
        self.main_layout.addWidget(self.description_label)
        self.main_layout.addSpacing(10)

        self.include_checkbox = QtWidgets.QCheckBox(
            "Include in visibility analysis"
        )
        self.main_layout.addWidget(self.include_checkbox)
        self.main_layout.addSpacing(10)

        self.cut_background_checkbox = QtWidgets.QCheckBox(
            "Cut background buildings from result (3 m buffer)"
        )
        self.cut_background_checkbox.setEnabled(False)
        self.main_layout.addWidget(self.cut_background_checkbox)
        self.main_layout.addSpacing(10)

        self.buildings_combo = self._add_combo(
            "Buildings *", "Select polygon layer", enabled=False
        )
        self.height_combo = self._add_combo(
            "Height field *", "Select after choosing buildings", enabled=False
        )

        self.height_help_label = QtWidgets.QLabel(
            "Available after selecting a building layer"
        )
        self.height_help_label.setObjectName("help_label")
        self.main_layout.addWidget(self.height_help_label)
        self.main_layout.addSpacing(12)

        self.max_distance_label = QtWidgets.QLabel("Maximum distance")
        self.max_distance_label.setObjectName("field_label")
        self.max_distance_label.setFixedHeight(22)
        self.main_layout.addWidget(self.max_distance_label)
        self.main_layout.addSpacing(6)
        self.max_distance_spin = QtWidgets.QDoubleSpinBox()
        self.max_distance_spin.setRange(1, 1_000_000)
        self.max_distance_spin.setDecimals(0)
        self.max_distance_spin.setSuffix(" m")
        self.max_distance_spin.setValue(4000)
        self.max_distance_spin.setFixedHeight(36)
        self.main_layout.addWidget(self.max_distance_spin)
        self.main_layout.addSpacing(15)

        self.observer_height_label = QtWidgets.QLabel("Observer height")
        self.observer_height_label.setObjectName("field_label")
        self.observer_height_label.setFixedHeight(22)
        self.main_layout.addWidget(self.observer_height_label)
        self.main_layout.addSpacing(6)
        self.observer_height_spin = QtWidgets.QDoubleSpinBox()
        self.observer_height_spin.setRange(0, 10_000)
        self.observer_height_spin.setDecimals(1)
        self.observer_height_spin.setSuffix(" m")
        self.observer_height_spin.setValue(0.0)
        self.observer_height_spin.setFixedHeight(36)
        self.main_layout.addWidget(self.observer_height_spin)
        self.main_layout.addSpacing(15)
        self.main_layout.addStretch()

        self.actions_layout = QtWidgets.QHBoxLayout()
        self.actions_layout.setSpacing(0)
        self.actions_layout.addStretch()
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.setObjectName("cancel_button")
        self.cancel_button.setFixedWidth(68)
        self.add_button = QtWidgets.QPushButton("Add")
        self.add_button.setObjectName("add_button")
        self.add_button.setFixedWidth(70)
        self.actions_layout.addWidget(self.cancel_button)
        self.actions_layout.addSpacing(12)
        self.actions_layout.addWidget(self.add_button)
        self.main_layout.addLayout(self.actions_layout)
        self.main_layout.addSpacing(16)

        self.footer_label = QtWidgets.QLabel("made by @leninsquare, 2026")
        self.footer_label.setObjectName("footer_label")
        self.footer_label.setAlignment(QtCore.Qt.AlignCenter)
        self.footer_label.setFixedHeight(16)
        self.main_layout.addWidget(self.footer_label)

        dialog.setStyleSheet(DIALOG_STYLE)
        QtCore.QMetaObject.connectSlotsByName(dialog)


class ViewshedModuleDialog(QtWidgets.QDialog, UiViewshedModule):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)


class AdditionalBuildingsDialog(QtWidgets.QDialog, UiAdditionalBuildings):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
