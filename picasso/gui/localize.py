#!/usr/bin/env python
"""
    gui/localize
    ~~~~~~~~~~~~~~~~~~~~

    Graphical user interface for localizing single molecules

    :author: Joerg Schnitzbauer, 2015
    :copyright: Copyright (c) 2015 Jungmann Lab, Max Planck Institute of Biochemistry
"""

import os.path
import sys
import yaml
from PyQt4 import QtCore, QtGui
import time
import numpy as np
import traceback
from .. import io, localize, CONFIG


CMAP_GRAYSCALE = [QtGui.qRgb(_, _, _) for _ in range(256)]
DEFAULT_PARAMETERS = {'Box Size': 7, 'Min. Net Gradient': 5000}


class RubberBand(QtGui.QRubberBand):

    def __init__(self, parent):
        super().__init__(QtGui.QRubberBand.Rectangle, parent)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        color = QtGui.QColor(QtCore.Qt.blue)
        painter.setPen(QtGui.QPen(color))
        rect = event.rect()
        rect.setHeight(rect.height() - 1)
        rect.setWidth(rect.width() - 1)
        painter.drawRect(rect)


class View(QtGui.QGraphicsView):
    """ The central widget which shows `Scene` objects of individual frames """

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setAcceptDrops(True)
        self.pan = False
        self.hscrollbar = self.horizontalScrollBar()
        self.vscrollbar = self.verticalScrollBar()
        self.rubberband = RubberBand(self)
        self.roi = None

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.roi_origin = QtCore.QPoint(event.pos())
            self.rubberband.setGeometry(QtCore.QRect(self.roi_origin, QtCore.QSize()))
            self.rubberband.show()
        elif event.button() == QtCore.Qt.RightButton:
            self.pan = True
            self.pan_start_x = event.x()
            self.pan_start_y = event.y()
            self.setCursor(QtCore.Qt.ClosedHandCursor)
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        if event.buttons() == QtCore.Qt.LeftButton:
            self.rubberband.setGeometry(QtCore.QRect(self.roi_origin, event.pos()))
        if self.pan:
            self.hscrollbar.setValue(self.hscrollbar.value() - event.x() + self.pan_start_x)
            self.vscrollbar.setValue(self.vscrollbar.value() - event.y() + self.pan_start_y)
            self.pan_start_x = event.x()
            self.pan_start_y = event.y()
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.roi_end = QtCore.QPoint(event.pos())
            dx = abs(self.roi_end.x() - self.roi_origin.x())
            dy = abs(self.roi_end.y() - self.roi_origin.y())
            if dx < 10 or dy < 10:
                self.roi = None
                self.rubberband.hide()
            else:
                roi_points = (self.mapToScene(self.roi_origin), self.mapToScene(self.roi_end))
                self.roi = list([[int(_.y()), int(_.x())] for _ in roi_points])
            self.window.draw_frame()
        elif event.button() == QtCore.Qt.RightButton:
            self.pan = False
            self.setCursor(QtCore.Qt.ArrowCursor)
            event.accept()
        else:
            event.ignore()

    def wheelEvent(self, event):
        """ Implements zoooming with the mouse wheel """
        scale = 1.008 ** (-event.delta())
        self.scale(scale, scale)


class Scene(QtGui.QGraphicsScene):
    """ Scenes render indivdual frames and can be displayed in a `View` widget """

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.dragMoveEvent = self.dragEnterEvent

    def path_from_drop(self, event):
        url = event.mimeData().urls()[0]
        path = url.toLocalFile()
        base, extension = os.path.splitext(path)
        return path, extension

    def drop_has_valid_url(self, event):
        if not event.mimeData().hasUrls():
            return False
        path, extension = self.path_from_drop(event)
        if extension.lower() not in ['.raw', '.tif']:
            return False
        return True

    def dragEnterEvent(self, event):
        if self.drop_has_valid_url(event):
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        """ Loads  when dropped into the scene """
        path, extension = self.path_from_drop(event)
        self.window.open(path)


class FitMarker(QtGui.QGraphicsItemGroup):

    def __init__(self, x, y, size, parent=None):
        super().__init__(parent)
        L = size/2
        line1 = QtGui.QGraphicsLineItem(x-L, y-L, x+L, y+L)
        line1.setPen(QtGui.QPen(QtGui.QColor(0, 255, 0)))
        self.addToGroup(line1)
        line2 = QtGui.QGraphicsLineItem(x-L, y+L, x+L, y-L)
        line2.setPen(QtGui.QPen(QtGui.QColor(0, 255, 0)))
        self.addToGroup(line2)


class OddSpinBox(QtGui.QSpinBox):
    """ A spinbox that allows only odd numbers """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSingleStep(2)
        self.valueChanged.connect(self.on_value_changed)

    def on_value_changed(self, value):
        if value % 2 == 0:
            self.setValue(value + 1)


class CamSettingComboBox(QtGui.QComboBox):

    def __init__(self, cam_combos, camera, index):
        super().__init__()
        self.cam_combos = cam_combos
        self.camera = camera
        self.index = index

    def change_target_choices(self, index):
        cam_combos = self.cam_combos[self.camera]
        sensitivity = CONFIG['Cameras'][self.camera]['Sensitivity']
        for i in range(self.index + 1):
            sensitivity = sensitivity[cam_combos[i].currentText()]
        target = cam_combos[self.index + 1]
        target.blockSignals(True)
        target.clear()
        target.blockSignals(False)
        target.addItems(sorted(list(sensitivity.keys())))


class PromptInfoDialog(QtGui.QDialog):

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle('Enter movie info')
        vbox = QtGui.QVBoxLayout(self)
        grid = QtGui.QGridLayout()
        grid.addWidget(QtGui.QLabel('Byte Order:'), 0, 0)
        self.byte_order = QtGui.QComboBox()
        self.byte_order.addItems(['Little Endian (loads faster)', 'Big Endian'])
        grid.addWidget(self.byte_order, 0, 1)
        grid.addWidget(QtGui.QLabel('Data Type:'), 1, 0)
        self.dtype = QtGui.QComboBox()
        self.dtype.addItems(['float16', 'float32', 'float64', 'int8', 'int16', 'int32', 'uint8', 'uint16', 'uint32'])
        grid.addWidget(self.dtype, 1, 1)
        grid.addWidget(QtGui.QLabel('Frames:'), 2, 0)
        self.frames = QtGui.QSpinBox()
        self.frames.setRange(1, 1e9)
        grid.addWidget(self.frames, 2, 1)
        grid.addWidget(QtGui.QLabel('Height:'), 3, 0)
        self.movie_height = QtGui.QSpinBox()
        self.movie_height.setRange(1, 1e9)
        grid.addWidget(self.movie_height, 3, 1)
        grid.addWidget(QtGui.QLabel('Width'), 4, 0)
        self.movie_width = QtGui.QSpinBox()
        self.movie_width.setRange(1, 1e9)
        grid.addWidget(self.movie_width, 4, 1)
        self.save = QtGui.QCheckBox('Save info to yaml file')
        self.save.setChecked(True)
        grid.addWidget(self.save, 5, 0, 1, 2)
        vbox.addLayout(grid)
        hbox = QtGui.QHBoxLayout()
        vbox.addLayout(hbox)
        # OK and Cancel buttons
        self.buttons = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel,
                                              QtCore.Qt.Horizontal,
                                              self)
        vbox.addWidget(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

    # static method to create the dialog and return (date, time, accepted)
    @staticmethod
    def getMovieSpecs(parent=None):
        dialog = PromptInfoDialog(parent)
        result = dialog.exec_()
        info = {}
        info['Byte Order'] = '>' if dialog.byte_order == 'big endian' else '<'
        info['Data Type'] = dialog.dtype.currentText()
        info['Frames'] = dialog.frames.value()
        info['Height'] = dialog.movie_height.value()
        info['Width'] = dialog.movie_width.value()
        save = dialog.save.isChecked()
        return (info, save, result == QtGui.QDialog.Accepted)


class ParametersDialog(QtGui.QDialog):
    """ The dialog showing analysis parameters """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.window = parent
        self.setWindowTitle('Parameters')
        self.resize(300, 0)
        self.setModal(False)

        vbox = QtGui.QVBoxLayout(self)
        identification_groupbox = QtGui.QGroupBox('Identification')
        vbox.addWidget(identification_groupbox)
        identification_grid = QtGui.QGridLayout(identification_groupbox)

        # Box Size
        identification_grid.addWidget(QtGui.QLabel('Box side length:'), 0, 0)
        self.box_spinbox = OddSpinBox()
        self.box_spinbox.setValue(DEFAULT_PARAMETERS['Box Size'])
        self.box_spinbox.valueChanged.connect(self.on_box_changed)
        identification_grid.addWidget(self.box_spinbox, 0, 1)

        # Min. Net Gradient
        identification_grid.addWidget(QtGui.QLabel('Min. Net Gradient:'), 1, 0)
        self.mng_spinbox = QtGui.QSpinBox()
        self.mng_spinbox.setRange(0, 1e9)
        self.mng_spinbox.setValue(DEFAULT_PARAMETERS['Min. Net Gradient'])
        self.mng_spinbox.setKeyboardTracking(False)
        self.mng_spinbox.valueChanged.connect(self.on_mng_spinbox_changed)
        identification_grid.addWidget(self.mng_spinbox, 1, 1)

        # Slider
        self.mng_slider = QtGui.QSlider()
        self.mng_slider.setOrientation(QtCore.Qt.Horizontal)
        self.mng_slider.setRange(0, 10000)
        self.mng_slider.setValue(DEFAULT_PARAMETERS['Min. Net Gradient'])
        self.mng_slider.setSingleStep(1)
        self.mng_slider.setPageStep(20)
        self.mng_slider.valueChanged.connect(self.on_mng_slider_changed)
        identification_grid.addWidget(self.mng_slider, 2, 0, 1, 2)

        hbox = QtGui.QHBoxLayout()
        identification_grid.addLayout(hbox, 3, 0, 1, 2)

        # Min SpinBox
        self.mng_min_spinbox = QtGui.QSpinBox()
        self.mng_min_spinbox.setRange(0, 999999)
        self.mng_min_spinbox.setKeyboardTracking(False)
        self.mng_min_spinbox.setValue(0)
        self.mng_min_spinbox.valueChanged.connect(self.on_mng_min_changed)
        hbox.addWidget(self.mng_min_spinbox)

        hbox.addStretch(1)

        # Max SpinBox
        self.mng_max_spinbox = QtGui.QSpinBox()
        self.mng_max_spinbox.setKeyboardTracking(False)
        self.mng_max_spinbox.setRange(0, 999999)
        self.mng_max_spinbox.setValue(10000)
        self.mng_max_spinbox.valueChanged.connect(self.on_mng_max_changed)
        hbox.addWidget(self.mng_max_spinbox)

        self.preview_checkbox = QtGui.QCheckBox('Preview')
        self.preview_checkbox.setTristate(False)
        # self.preview_checkbox.setChecked(True)
        self.preview_checkbox.stateChanged.connect(self.on_preview_changed)
        identification_grid.addWidget(self.preview_checkbox, 4, 0)

        # Camera:
        if 'Cameras' in CONFIG:
            # Experiment settings
            exp_groupbox = QtGui.QGroupBox('Experiment settings')
            vbox.addWidget(exp_groupbox)
            exp_grid = QtGui.QGridLayout(exp_groupbox)
            exp_grid.addWidget(QtGui.QLabel('Camera:'), 0, 0)
            self.camera = QtGui.QComboBox()
            exp_grid.addWidget(self.camera, 0, 1)
            cameras = sorted(list(CONFIG['Cameras'].keys()))
            self.camera.addItems(cameras)
            self.camera.currentIndexChanged.connect(self.on_camera_changed)

            self.cam_settings = QtGui.QStackedWidget()
            exp_grid.addWidget(self.cam_settings, 1, 0, 1, 2)
            self.cam_combos = {}
            self.emission_combos = {}
            for camera in cameras:
                cam_widget = QtGui.QWidget()
                cam_grid = QtGui.QGridLayout(cam_widget)
                self.cam_settings.addWidget(cam_widget)
                cam_config = CONFIG['Cameras'][camera]
                if 'Sensitivity' in cam_config:
                    sensitivity = cam_config['Sensitivity']
                    if 'Sensitivity Categories' in cam_config:
                        self.cam_combos[camera] = []
                        categories = cam_config['Sensitivity Categories']
                        for i, category in enumerate(categories):
                            row_count = cam_grid.rowCount()
                            cam_grid.addWidget(QtGui.QLabel(category+':'), row_count, 0)
                            cat_combo = CamSettingComboBox(self.cam_combos, camera, i)
                            cam_grid.addWidget(cat_combo, row_count, 1)
                            self.cam_combos[camera].append(cat_combo)
                        self.cam_combos[camera][0].addItems(sorted(list(sensitivity.keys())))
                        for cam_combo in self.cam_combos[camera][:-1]:
                            cam_combo.currentIndexChanged.connect(cam_combo.change_target_choices)
                        self.cam_combos[camera][0].change_target_choices(0)
                        self.cam_combos[camera][-1].currentIndexChanged.connect(self.update_sensitivity)
                if 'Quantum Efficiency' in cam_config:
                    row_count = cam_grid.rowCount()
                    cam_grid.addWidget(QtGui.QLabel('Emission Wavelength:'), row_count, 0)
                    emission_combo = QtGui.QComboBox()
                    cam_grid.addWidget(emission_combo, row_count, 1)
                    qes = cam_config['Quantum Efficiency'].keys()
                    wavelengths = sorted([str(_) for _ in qes])
                    emission_combo.addItems(wavelengths)
                    emission_combo.currentIndexChanged.connect(self.on_emission_changed)
                    self.emission_combos[camera] = emission_combo
                spacer = QtGui.QWidget()
                spacer.setSizePolicy(QtGui.QSizePolicy.Preferred, QtGui.QSizePolicy.Expanding)
                cam_grid.addWidget(spacer, cam_grid.rowCount(), 0)

        # Photon conversion
        photon_groupbox = QtGui.QGroupBox('Photon Conversion')
        vbox.addWidget(photon_groupbox)
        photon_grid = QtGui.QGridLayout(photon_groupbox)

        # EM Gain
        photon_grid.addWidget(QtGui.QLabel('EM Gain:'), 0, 0)
        self.gain = QtGui.QSpinBox()
        self.gain.setRange(1, 1e6)
        self.gain.setValue(1)
        photon_grid.addWidget(self.gain, 0, 1)

        # Baseline
        photon_grid.addWidget(QtGui.QLabel('Baseline:'), 1, 0)
        self.baseline = QtGui.QDoubleSpinBox()
        self.baseline.setRange(0, 1e6)
        self.baseline.setValue(100.0)
        self.baseline.setDecimals(1)
        self.baseline.setSingleStep(0.1)
        photon_grid.addWidget(self.baseline, 1, 1)

        # Sensitivity
        photon_grid.addWidget(QtGui.QLabel('Sensitivity:'), 2, 0)
        self.sensitivity = QtGui.QDoubleSpinBox()
        self.sensitivity.setRange(0, 1e6)
        self.sensitivity.setValue(1.0)
        self.sensitivity.setDecimals(2)
        self.sensitivity.setSingleStep(0.01)
        photon_grid.addWidget(self.sensitivity, 2, 1)

        # QE
        photon_grid.addWidget(QtGui.QLabel('Quantum Efficiency:'), 3, 0)
        self.qe = QtGui.QDoubleSpinBox()
        self.qe.setRange(0, 1)
        self.qe.setValue(0.9)
        self.qe.setDecimals(2)
        self.qe.setSingleStep(0.1)
        photon_grid.addWidget(self.qe, 3, 1)

        # Fit Settings
        fit_groupbox = QtGui.QGroupBox('Fit Settings')
        vbox.addWidget(fit_groupbox)
        fit_grid = QtGui.QGridLayout(fit_groupbox)
        self.symmetric_checkbox = QtGui.QCheckBox('Symmetric PSF')
        self.symmetric_checkbox.setChecked(True)
        fit_grid.addWidget(self.symmetric_checkbox, 0, 1)
        fit_grid.addWidget(QtGui.QLabel('Convergence Criterion:'), 1, 0)
        self.convergence_spinbox = QtGui.QDoubleSpinBox()
        self.convergence_spinbox.setRange(0, 1)
        self.convergence_spinbox.setDecimals(5)
        self.convergence_spinbox.setValue(0.0001)
        self.convergence_spinbox.setSingleStep(0.001)
        fit_grid.addWidget(self.convergence_spinbox, 1, 1)
        fit_grid.addWidget(QtGui.QLabel('Max. Iterations:'), 2, 0)
        self.max_iterations_spinbox = QtGui.QSpinBox()
        self.max_iterations_spinbox.setRange(0, 999999)
        self.max_iterations_spinbox.setValue(100)
        self.max_iterations_spinbox.setSingleStep(10)
        fit_grid.addWidget(self.max_iterations_spinbox, 2, 1)

        if 'Cameras' in CONFIG:
            camera = self.camera.currentText()
            if camera in CONFIG['Cameras']:
                self.on_camera_changed(0)
                camera_config = CONFIG['Cameras'][camera]
                if 'Sensitivity' in camera_config and 'Sensitivity Categories' in camera_config:
                    self.update_sensitivity()

    def on_box_changed(self, value):
        self.window.on_parameters_changed()

    def on_camera_changed(self, index):
        self.cam_settings.setCurrentIndex(index)
        camera = self.camera.currentText()
        cam_config = CONFIG['Cameras'][camera]
        if 'Baseline' in cam_config:
            self.baseline.setValue(cam_config['Baseline'])
        if 'Sensitivity' in cam_config:
            sensitivity = cam_config['Sensitivity']
            try:
                self.sensitivity.setValue(sensitivity)
            except TypeError:
                # sensitivity is not a number
                pass

    def on_emission_changed(self, index):
        camera = self.camera.currentText()
        em_combo = self.emission_combos[camera]
        wavelength = float(em_combo.currentText())
        qe = CONFIG['Cameras'][camera]['Quantum Efficiency'][wavelength]
        self.qe.setValue(qe)

    def on_mng_spinbox_changed(self, value):
        if value < self.mng_slider.minimum():
            self.mng_min_spinbox.setValue(value)
        if value > self.mng_slider.maximum():
            self.mng_max_spinbox.setValue(value)
        self.mng_slider.setValue(value)

    def on_mng_slider_changed(self, value):
        self.mng_spinbox.setValue(value)
        if self.preview_checkbox.isChecked():
            self.window.on_parameters_changed()

    def on_mng_min_changed(self, value):
        self.mng_slider.setMinimum(value)

    def on_mng_max_changed(self, value):
        self.mng_slider.setMaximum(value)

    def on_preview_changed(self, state):
        self.window.draw_frame()

    def set_camera_parameters(self, info):
        if 'Micro-Manager Metadata' in info:
            info = info['Micro-Manager Metadata']
            if 'Cameras' in CONFIG:
                cameras = [self.camera.itemText(_) for _ in range(self.camera.count())]
                camera = info['Camera']
                if camera in cameras:
                    index = cameras.index(camera)
                    self.camera.setCurrentIndex(index)
                    cam_config = CONFIG['Cameras'][camera]
                    if 'Gain Property Name' in cam_config:
                        gain_property_name = cam_config['Gain Property Name']
                        gain = info[camera + '-' + gain_property_name]
                        self.gain.setValue(int(gain))
                    else:
                        self.gain.setValue(1)
                    if 'Sensitivity Categories' in cam_config:
                        cam_combos = self.cam_combos[camera]
                        categories = cam_config['Sensitivity Categories']
                        for i, category in enumerate(categories):
                            property_name = camera + '-' + category
                            if property_name in info:
                                exp_setting = info[camera + '-' + category]
                                cam_combo = cam_combos[i]
                                for index in range(cam_combo.count()):
                                    if cam_combo.itemText(index) == exp_setting:
                                        cam_combo.setCurrentIndex(index)
                                        break
                        # else:
                        #     raise ValueError('No configuration for setting "{}": {}'.format(category,
                        #                      exp_setting))
                    if 'Quantum Efficiency' in cam_config:
                        if 'Channel Device' in cam_config:
                            channel_device_name = cam_config['Channel Device']['Name']
                            channel = info[channel_device_name]
                            channels = cam_config['Channel Device']['Emission Wavelengths']
                            if channel in channels:
                                wavelength = str(channels[channel])
                                em_combo = self.emission_combos[camera]
                                for index in range(em_combo.count()):
                                    if em_combo.itemText(index) == wavelength:
                                        em_combo.setCurrentIndex(index)
                                        break
                                else:
                                    raise ValueError('No quantum efficiency found for wavelength ' + wavelength)

    def update_sensitivity(self, index=None):
        camera = self.camera.currentText()
        cam_config = CONFIG['Cameras'][camera]
        sensitivity = cam_config['Sensitivity']
        categories = cam_config['Sensitivity Categories']
        for i, category in enumerate(categories):
            cat_combo = self.cam_combos[camera][i]
            sensitivity = sensitivity[cat_combo.currentText()]
        self.sensitivity.setValue(sensitivity)


class ContrastDialog(QtGui.QDialog):

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle('Contrast')
        self.resize(200, 0)
        self.setModal(False)
        grid = QtGui.QGridLayout(self)
        black_label = QtGui.QLabel('Black:')
        grid.addWidget(black_label, 0, 0)
        self.black_spinbox = QtGui.QSpinBox()
        self.black_spinbox.setKeyboardTracking(False)
        self.black_spinbox.setRange(0, 999999)
        self.black_spinbox.valueChanged.connect(self.on_contrast_changed)
        grid.addWidget(self.black_spinbox, 0, 1)
        white_label = QtGui.QLabel('White:')
        grid.addWidget(white_label, 1, 0)
        self.white_spinbox = QtGui.QSpinBox()
        self.white_spinbox.setKeyboardTracking(False)
        self.white_spinbox.setRange(0, 999999)
        self.white_spinbox.valueChanged.connect(self.on_contrast_changed)
        grid.addWidget(self.white_spinbox, 1, 1)
        self.auto_checkbox = QtGui.QCheckBox('Auto')
        self.auto_checkbox.setTristate(False)
        self.auto_checkbox.setChecked(True)
        self.auto_checkbox.stateChanged.connect(self.on_auto_changed)
        grid.addWidget(self.auto_checkbox, 2, 0, 1, 2)
        self.silent_contrast_change = False

    def change_contrast_silently(self, black, white):
        self.silent_contrast_change = True
        self.black_spinbox.setValue(black)
        self.white_spinbox.setValue(white)
        self.silent_contrast_change = False

    def on_contrast_changed(self, value):
        if not self.silent_contrast_change:
            self.auto_checkbox.setChecked(False)
            self.window.draw_frame()

    def on_auto_changed(self, state):
        if state:
            movie = self.window.movie
            frame_number = self.window.current_frame_number
            frame = movie[frame_number]
            self.change_contrast_silently(frame.min(), frame.max())
            self.window.draw_frame()


class Window(QtGui.QMainWindow):
    """ The main window """

    def __init__(self):
        super().__init__()
        # Init GUI
        self.setWindowTitle('Picasso: Localize')
        this_directory = os.path.dirname(os.path.realpath(__file__))
        icon_path = os.path.join(this_directory, 'icons', 'localize.ico')
        icon = QtGui.QIcon(icon_path)
        self.setWindowIcon(icon)
        self.resize(768, 768)
        self.parameters_dialog = ParametersDialog(self)
        self.contrast_dialog = ContrastDialog(self)
        self.init_menu_bar()
        self.view = View(self)
        self.setCentralWidget(self.view)
        self.scene = Scene(self)
        self.view.setScene(self.scene)
        self.status_bar = self.statusBar()
        self.status_bar_frame_indicator = QtGui.QLabel()
        self.status_bar.addPermanentWidget(self.status_bar_frame_indicator)

        #: Holds the current movie as a numpy memmap in the format (frame, y, x)
        self.movie = None

        #: A dictionary of analysis parameters used for the last operation
        self.last_identification_info = None

        #: A numpy.recarray of identifcations with fields frame, x and y
        self.identifications = None

        self.ready_for_fit = False

        self.locs = None

    def init_menu_bar(self):
        menu_bar = self.menuBar()

        """ File """
        file_menu = menu_bar.addMenu('File')
        open_action = file_menu.addAction('Open movie')
        open_action.setShortcut('Ctrl+O')
        open_action.triggered.connect(self.open_file_dialog)
        file_menu.addAction(open_action)
        save_action = file_menu.addAction('Save localizations')
        save_action.setShortcut('Ctrl+S')
        save_action.triggered.connect(self.save_locs_dialog)
        file_menu.addAction(save_action)
        file_menu.addSeparator()
        # open_parameters_action = file_menu.addAction('Load parameters')
        # open_parameters_action.setShortcut('Ctrl+Shift+O')
        # open_parameters_action.triggered.connect(self.open_parameters)
        # file_menu.addAction(open_parameters_action)
        # save_parameters_action = file_menu.addAction('Save parameters')
        # save_parameters_action.setShortcut('Ctrl+Shift+S')
        # save_parameters_action.triggered.connect(self.save_parameters)
        # file_menu.addAction(save_parameters_action)

        """ View """
        view_menu = menu_bar.addMenu('View')
        previous_frame_action = view_menu.addAction('Previous frame')
        previous_frame_action.setShortcut('Left')
        previous_frame_action.triggered.connect(self.previous_frame)
        view_menu.addAction(previous_frame_action)
        next_frame_action = view_menu.addAction('Next frame')
        next_frame_action.setShortcut('Right')
        next_frame_action.triggered.connect(self.next_frame)
        view_menu.addAction(next_frame_action)
        view_menu.addSeparator()
        first_frame_action = view_menu.addAction('First frame')
        first_frame_action.setShortcut('Home')
        first_frame_action.triggered.connect(self.first_frame)
        view_menu.addAction(first_frame_action)
        last_frame_action = view_menu.addAction('Last frame')
        last_frame_action.setShortcut('End')
        last_frame_action.triggered.connect(self.last_frame)
        view_menu.addAction(last_frame_action)
        go_to_frame_action = view_menu.addAction('Go to frame')
        go_to_frame_action.setShortcut('Ctrl+G')
        go_to_frame_action.triggered.connect(self.to_frame)
        view_menu.addAction(go_to_frame_action)
        view_menu.addSeparator()
        zoom_in_action = view_menu.addAction('Zoom in')
        zoom_in_action.setShortcuts(['Ctrl++', 'Ctrl+='])
        zoom_in_action.triggered.connect(self.zoom_in)
        view_menu.addAction(zoom_in_action)
        zoom_out_action = view_menu.addAction('Zoom out')
        zoom_out_action.setShortcut('Ctrl+-')
        zoom_out_action.triggered.connect(self.zoom_out)
        view_menu.addAction(zoom_out_action)
        fit_in_view_action = view_menu.addAction('Fit image to window')
        fit_in_view_action.setShortcut('Ctrl+W')
        fit_in_view_action.triggered.connect(self.fit_in_view)
        view_menu.addAction(fit_in_view_action)
        view_menu.addSeparator()
        display_settings_action = view_menu.addAction('Contrast')
        display_settings_action.setShortcut('Ctrl+C')
        display_settings_action.triggered.connect(self.contrast_dialog.show)
        view_menu.addAction(display_settings_action)

        """ Analyze """
        analyze_menu = menu_bar.addMenu('Analyze')
        parameters_action = analyze_menu.addAction('Parameters')
        parameters_action.setShortcut('Ctrl+P')
        parameters_action.triggered.connect(self.parameters_dialog.show)
        analyze_menu.addAction(parameters_action)
        analyze_menu.addSeparator()
        identify_action = analyze_menu.addAction('Identify')
        identify_action.setShortcut('Ctrl+I')
        identify_action.triggered.connect(self.identify)
        analyze_menu.addAction(identify_action)
        fit_action = analyze_menu.addAction('Fit')
        fit_action.setShortcut('Ctrl+F')
        fit_action.triggered.connect(self.fit)
        analyze_menu.addAction(fit_action)
        localize_action = analyze_menu.addAction('Localize (Identify && Fit)')
        localize_action.setShortcut('Ctrl+L')
        localize_action.triggered.connect(self.localize)
        analyze_menu.addAction(localize_action)

    def open_file_dialog(self):
        path = QtGui.QFileDialog.getOpenFileName(self, 'Open image sequence', filter='*.raw; *.tif')
        if path:
            self.open(path)

    def open(self, path):
        t0 = time.time()
        result = io.load_movie(path, prompt_info=self.prompt_info)
        if result is not None:
            self.movie, self.info = result
            dt = time.time() - t0
            self.movie_path = path
            self.identifications = None
            self.locs = None
            self.ready_for_fit = False
            self.set_frame(0)
            self.fit_in_view()
            self.parameters_dialog.set_camera_parameters(self.info[0])
            self.status_bar.showMessage('Opened movie in {:.2f} seconds.'.format(dt))

    def prompt_info(self):
        info, save, ok = PromptInfoDialog.getMovieSpecs(self)
        if ok:
            return info, save

    def previous_frame(self):
        if self.movie is not None:
            if self.current_frame_number > 0:
                self.set_frame(self.current_frame_number - 1)

    def next_frame(self):
        if self.movie is not None:
            if self.current_frame_number + 1 < self.info[0]['Frames']:
                self.set_frame(self.current_frame_number + 1)

    def first_frame(self):
        if self.movie is not None:
            self.set_frame(0)

    def last_frame(self):
        if self.movie is not None:
            self.set_frame(self.info[0]['Frames'] - 1)

    def to_frame(self):
        if self.movie is not None:
            frames = self.info[0]['Frames']
            number, ok = QtGui.QInputDialog.getInt(self, 'Go to frame', 'Frame number:', self.current_frame_number+1, 1, frames)
            if ok:
                self.set_frame(number - 1)

    def set_frame(self, number):
        self.current_frame_number = number
        if self.contrast_dialog.auto_checkbox.isChecked():
            black = self.movie[number].min()
            white = self.movie[number].max()
            self.contrast_dialog.change_contrast_silently(black, white)
        self.draw_frame()
        self.status_bar_frame_indicator.setText('{:,}/{:,}'.format(number + 1, self.info[0]['Frames']))

    def draw_frame(self):
        if self.movie is not None:
            frame = self.movie[self.current_frame_number]
            frame = frame.astype('float32')
            if self.contrast_dialog.auto_checkbox.isChecked():
                frame -= frame.min()
                frame /= frame.max()
            else:
                frame -= self.contrast_dialog.black_spinbox.value()
                frame /= self.contrast_dialog.white_spinbox.value()
            frame *= 255.0
            frame = np.maximum(frame, 0)
            frame = np.minimum(frame, 255)
            frame = frame.astype('uint8')
            height, width = frame.shape
            image = QtGui.QImage(frame.data, width, height, width, QtGui.QImage.Format_Indexed8)
            image.setColorTable(CMAP_GRAYSCALE)
            pixmap = QtGui.QPixmap.fromImage(image)
            self.scene = Scene(self)
            self.scene.addPixmap(pixmap)
            self.view.setScene(self.scene)
            if self.ready_for_fit:
                identifications_frame = self.identifications[self.identifications.frame == self.current_frame_number]
                box = self.last_identification_info['Box Size']
                self.draw_identifications(identifications_frame, box, QtGui.QColor('yellow'))
            else:
                if self.parameters_dialog.preview_checkbox.isChecked():
                    identifications_frame = localize.identify_by_frame_number(self.movie,
                                                                              self.parameters['Min. Net Gradient'],
                                                                              self.parameters['Box Size'],
                                                                              self.current_frame_number,
                                                                              self.view.roi)
                    box = self.parameters['Box Size']
                    self.status_bar.showMessage('Found {:,} spots in current frame.'.format(len(identifications_frame)))
                    self.draw_identifications(identifications_frame, box, QtGui.QColor('red'))
                else:
                    self.status_bar.showMessage('')
            if self.locs is not None:
                locs_frame = self.locs[self.locs.frame == self.current_frame_number]
                for loc in locs_frame:
                    self.scene.addItem(FitMarker(loc.x+0.5, loc.y+0.5, 1))

    def draw_identifications(self, identifications, box, color):
        box_half = int(box / 2)
        for identification in identifications:
            x = identification.x
            y = identification.y
            self.scene.addRect(x - box_half, y - box_half, box, box, color)

    def open_parameters(self):
        path = QtGui.QFileDialog.getOpenFileName(self, 'Open parameters', filter='*.yaml')
        if path:
            self.load_parameters(path)

    def load_parameters(self, path):
        with open(path, 'r') as file:
            parameters = yaml.load(file)
            self.parameters_dialog.box_spinbox.setValue(parameters['Box Size'])
            self.parameters_dialog.mng_spinbox.setValue(parameters['Min. Net Gradient'])
            self.status_bar.showMessage('Parameter file {} loaded.'.format(path))

    def save_parameters(self):
        path = QtGui.QFileDialog.getSaveFileName(self, 'Save parameters', filter='*.yaml')
        if path:
            with open(path, 'w') as file:
                yaml.dump(self.parameters, file, default_flow_style=False)

    @property
    def parameters(self):
        return {'Box Size': self.parameters_dialog.box_spinbox.value(),
                'Min. Net Gradient': self.parameters_dialog.mng_slider.value()}

    def on_parameters_changed(self):
        self.locs = None
        self.ready_for_fit = False
        self.draw_frame()

    def identify(self, fit_afterwards=False):
        if self.movie is not None:
            self.status_bar.showMessage('Preparing identification...')
            self.identificaton_worker = IdentificationWorker(self, fit_afterwards)
            self.identificaton_worker.progressMade.connect(self.on_identify_progress)
            self.identificaton_worker.finished.connect(self.on_identify_finished)
            self.identificaton_worker.start()

    def on_identify_progress(self, frame_number, parameters):
        n_frames = self.info[0]['Frames']
        box = parameters['Box Size']
        mng = parameters['Min. Net Gradient']
        message = 'Identifying in frame {:,} / {:,} (Box Size: {:,}; Min. Net Gradient: {:,}) ...'.format(frame_number,
                                                                                                          n_frames,
                                                                                                          box,
                                                                                                          mng)
        self.status_bar.showMessage(message)

    def on_identify_finished(self, parameters, roi, identifications, fit_afterwards):
        if len(identifications):
            self.locs = None
            self.last_identification_info = parameters.copy()
            self.last_identification_info['ROI'] = roi
            n_identifications = len(identifications)
            box = parameters['Box Size']
            mng = parameters['Min. Net Gradient']
            message = 'Identified {:,} spots (Box Size: {:,}; Min. Net Gradient: {:,}). Ready for fit.'.format(n_identifications,
                                                                                                               box, mng)
            self.status_bar.showMessage(message)
            self.identifications = identifications
            self.ready_for_fit = True
            self.draw_frame()
            if fit_afterwards:
                self.fit()

    def fit(self):
        if self.movie is not None and self.ready_for_fit:
            self.status_bar.showMessage('Preparing fit...')
            camera_info = {}
            camera_info['baseline'] = self.parameters_dialog.baseline.value()
            camera_info['gain'] = self.parameters_dialog.gain.value()
            camera_info['sensitivity'] = self.parameters_dialog.sensitivity.value()
            camera_info['qe'] = self.parameters_dialog.qe.value()
            eps = self.parameters_dialog.convergence_spinbox.value()
            max_it = self.parameters_dialog.max_iterations_spinbox.value()
            method = {True: 'sigma', False: 'sigmaxy'}[self.parameters_dialog.symmetric_checkbox.isChecked()]
            self.fit_worker = FitWorker(self.movie, camera_info, self.identifications, self.parameters['Box Size'],
                                        eps, max_it, method)
            self.fit_worker.progressMade.connect(self.on_fit_progress)
            self.fit_worker.finished.connect(self.on_fit_finished)
            self.fit_worker.start()

    def on_fit_progress(self, current, total):
        message = 'Fitting spot {:,} / {:,} ...'.format(current, total)
        self.status_bar.showMessage(message)

    def on_fit_finished(self, locs, elapsed_time):
        self.status_bar.showMessage('Fitted {:,} spots in {:.2f} seconds.'.format(len(locs), elapsed_time))
        self.locs = locs
        self.draw_frame()
        base, ext = os.path.splitext(self.movie_path)
        self.save_locs(base + '_locs.hdf5')

    def fit_in_view(self):
        self.view.fitInView(self.scene.sceneRect(), QtCore.Qt.KeepAspectRatio)

    def zoom_in(self):
        self.view.scale(10 / 7, 10 / 7)

    def zoom_out(self):
        self.view.scale(7 / 10, 7 / 10)

    def save_locs(self, path):
        localize_info = self.last_identification_info.copy()
        localize_info['Generated by'] = 'Picasso Localize'
        info = self.info + [localize_info]
        io.save_locs(path, self.locs, info)

    def save_locs_dialog(self):
        base, ext = os.path.splitext(self.movie_path)
        locs_path = base + '_locs.hdf5'
        path = QtGui.QFileDialog.getSaveFileName(self, 'Save localizations', locs_path, filter='*.hdf5')
        if path:
            self.save_locs(path)

    def localize(self):
        self.identify(fit_afterwards=True)


class IdentificationWorker(QtCore.QThread):

    progressMade = QtCore.pyqtSignal(int, dict)
    finished = QtCore.pyqtSignal(dict, object, np.recarray, bool)

    def __init__(self, window, fit_afterwards):
        super().__init__()
        self.window = window
        self.movie = window.movie
        self.roi = window.view.roi
        self.parameters = window.parameters
        self.fit_afterwards = fit_afterwards

    def run(self):
        N = len(self.movie)
        current, futures = localize.identify_async(self.movie,
                                                   self.parameters['Min. Net Gradient'],
                                                   self.parameters['Box Size'],
                                                   self.roi)
        while current[0] < N:
            self.progressMade.emit(current[0], self.parameters)
            time.sleep(0.2)
        self.progressMade.emit(current[0], self.parameters)
        identifications = localize.identifications_from_futures(futures)
        self.finished.emit(self.parameters, self.roi, identifications, self.fit_afterwards)


class FitWorker(QtCore.QThread):

    progressMade = QtCore.pyqtSignal(int, int)
    finished = QtCore.pyqtSignal(np.recarray, float)

    def __init__(self, movie, camera_info, identifications, box, eps, max_it, method):
        super().__init__()
        self.movie = movie
        self.camera_info = camera_info
        self.identifications = identifications
        self.box = box
        self.eps = eps
        self.max_it = max_it
        self.method = method

    def run(self):
        N = len(self.identifications)
        t0 = time.time()
        current, thetas, CRLBs, likelihoods, iterations = localize.fit_async(self.movie, self.camera_info,
                                                                             self.identifications, self.box,
                                                                             self.eps, self.max_it, self.method)
        while current[0] < N:
            self.progressMade.emit(current[0], N)
            time.sleep(0.2)
        self.progressMade.emit(current[0], N)
        dt = time.time() - t0
        locs = localize.locs_from_fits(self.identifications, thetas, CRLBs, likelihoods, iterations, self.box)
        self.finished.emit(locs, dt)


def main():
    app = QtGui.QApplication(sys.argv)
    window = Window()
    window.show()

    def excepthook(type, value, tback):
        message = ''.join(traceback.format_exception(type, value, tback))
        errorbox = QtGui.QMessageBox.critical(window, 'An error occured', message)
        errorbox.exec_()
        sys.__excepthook__(type, value, tback)
    sys.excepthook = excepthook

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
