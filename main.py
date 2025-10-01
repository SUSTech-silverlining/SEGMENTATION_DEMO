import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QFileDialog, QPushButton,
                             QVBoxLayout, QWidget, QSlider, QLabel, QGroupBox,
                             QFormLayout, QHBoxLayout, QMessageBox, QGridLayout)
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QProgressDialog
from PyQt5.QtCore import QTimer
import vtk
from vtk.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

# ==============================================================================
# Custom interactor style for picking points in the 2D view
# ==============================================================================
class ContourInteractorStyle(vtk.vtkInteractorStyleImage):
    def __init__(self, parent_viewer=None):
        super().__init__()
        self.parent_viewer = parent_viewer

        # Use AddObserver to bind the left-click event to ensure it's captured
        self.AddObserver("LeftButtonPressEvent", self.on_left_button_press)

    def on_left_button_press(self, obj, event):
        if not self.parent_viewer or not self.parent_viewer.is_drawing:
            self.OnLeftButtonDown()
            return

        click_pos = self.GetInteractor().GetEventPosition()
        renderer = self.GetDefaultRenderer()
        picker = vtk.vtkPropPicker()
        picker.Pick(click_pos[0], click_pos[1], 0, renderer)
        world_pos = list(picker.GetPickPosition())

        # Force the Z value to be the physical coordinate of the current axial slice
        if self.parent_viewer and hasattr(self.parent_viewer, "slider_axial"):
            axial_slice = self.parent_viewer.slider_axial.value()
            image_data = self.parent_viewer.image_data
            if image_data:
                origin = image_data.GetOrigin()
                spacing = image_data.GetSpacing()
                world_pos[2] = origin[2] + axial_slice * spacing[2]

        print(f"Picked point at {world_pos}")
        self.parent_viewer.add_contour_point(tuple(world_pos))
        self.OnLeftButtonDown()  # Allow the base class to continue processing the event

# ==============================================================================
# Custom interactor style for panning in the 2D view
# ==============================================================================
class PanWithMiddleButtonInteractorStyle(vtk.vtkInteractorStyleImage):
    def __init__(self, parent=None):
        super().__init__()
        self.AddObserver("MiddleButtonPressEvent", self.start_pan)
        self.AddObserver("MiddleButtonReleaseEvent", self.end_pan)
        self.AddObserver("MouseMoveEvent", self.pan_move)
        self.panning = False
        self.last_pos = None

    def start_pan(self, obj, event):
        self.panning = True
        self.last_pos = self.GetInteractor().GetEventPosition()
        self.OnMiddleButtonDown()

    def end_pan(self, obj, event):
        self.panning = False
        self.last_pos = None
        self.OnMiddleButtonUp()

    def pan_move(self, obj, event):
        if self.panning:
            interactor = self.GetInteractor()
            new_pos = interactor.GetEventPosition()
            dx = new_pos[0] - self.last_pos[0]
            dy = new_pos[1] - self.last_pos[1]
            renderer = self.GetDefaultRenderer()
            camera = renderer.GetActiveCamera()
            factor = 0.5  # Panning sensitivity
            camera.SetFocalPoint(camera.GetFocalPoint()[0] - dx * factor,
                                 camera.GetFocalPoint()[1] - dy * factor,
                                 camera.GetFocalPoint()[2])
            camera.SetPosition(camera.GetPosition()[0] - dx * factor,
                               camera.GetPosition()[1] - dy * factor,
                               camera.GetPosition()[2])
            renderer.ResetCameraClippingRange()
            interactor.Render()
            self.last_pos = new_pos
        self.OnMouseMove()



# ==============================================================================
# Widget for displaying 2D image slices (Refactored)
# ==============================================================================
class ImageSliceViewerWidget(QWidget):
    """A QWidget for displaying VTI image slices."""
    def __init__(self, view_axis, parent_viewer=None):
        super().__init__()
        self.view_axis = view_axis

        self.vtk_widget = QVTKRenderWindowInteractor(self)
        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(0.1, 0.1, 0.1)
        self.vtk_widget.GetRenderWindow().AddRenderer(self.renderer)

        # Use the more robust vtkImageReslice to extract slices
        self.reslice = vtk.vtkImageReslice()
        self.reslice.SetOutputDimensionality(2)
        self.reslice.SetInterpolationModeToLinear()

        mapper = vtk.vtkImageSliceMapper()
        mapper.SetInputConnection(self.reslice.GetOutputPort())

        self.image_slice = vtk.vtkImageSlice()
        self.image_slice.SetMapper(mapper)
        self.renderer.AddActor(self.image_slice)
        

        camera = self.renderer.GetActiveCamera()
        camera.SetParallelProjection(True)

        if view_axis == 'z': # Axial
            self.interactor_style = ContourInteractorStyle(parent_viewer)
            self.interactor_style.SetDefaultRenderer(self.renderer)
        else:
            self.interactor_style = PanWithMiddleButtonInteractorStyle()
            self.interactor_style.SetDefaultRenderer(self.renderer)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.vtk_widget)

        self.camera_reset_done = False


    def set_input_data(self, image_data):
        """Sets the input volume data."""
        self.reslice.SetInputData(image_data)
        self.camera_reset_done = False
            
    def set_color_level(self, level):
        self.image_slice.GetProperty().SetColorLevel(level)

    def set_color_window(self, window):
        self.image_slice.GetProperty().SetColorWindow(window)

    def set_slice(self, slice_index):
        """Updates the slice position based on the slice index."""
        if not self.reslice.GetInput(): return
        
        image_data = self.reslice.GetInput()
        origin = image_data.GetOrigin()
        spacing = image_data.GetSpacing()
        
        # Define the slice plane by setting the ResliceAxes matrix
        reslice_axes = vtk.vtkMatrix4x4()
        
        if self.view_axis == 'x': # Sagittal (YZ Plane)
            reslice_axes.DeepCopy((0, 1, 0, 0,
                                   0, 0, 1, 0,
                                   1, 0, 0, 0,
                                   0, 0, 0, 1))
            center = image_data.GetCenter()
            slice_pos = origin[0] + slice_index * spacing[0]
            reslice_axes.SetElement(0, 3, slice_pos)
            reslice_axes.SetElement(1, 3, center[1])
            reslice_axes.SetElement(2, 3, center[2])
        elif self.view_axis == 'y': # Coronal (XZ Plane)
            reslice_axes.DeepCopy((1, 0, 0, 0,
                                   0, 0, 1, 0,
                                   0, 1, 0, 0,
                                   0, 0, 0, 1))
            center = image_data.GetCenter()
            slice_pos = origin[1] + slice_index * spacing[1]
            reslice_axes.SetElement(0, 3, center[0])
            reslice_axes.SetElement(1, 3, slice_pos)
            reslice_axes.SetElement(2, 3, center[2])
        elif self.view_axis == 'z': # Axial (XY Plane)
            reslice_axes.DeepCopy((1, 0, 0, 0,
                                   0, 1, 0, 0,
                                   0, 0, 1, 0,
                                   0, 0, 0, 1))
            center = image_data.GetCenter()
            slice_pos = origin[2] + slice_index * spacing[2]
            reslice_axes.SetElement(0, 3, center[0])
            reslice_axes.SetElement(1, 3, center[1])
            reslice_axes.SetElement(2, 3, slice_pos)

        self.reslice.SetResliceAxes(reslice_axes)
        self.reslice.Update()

        if not hasattr(self, "camera_reset_done") or not self.camera_reset_done:
            self.renderer.ResetCamera()
            self.camera_reset_done = True

        self.vtk_widget.GetRenderWindow().Render()

# ==============================================================================
# Main Window Class
# ==============================================================================
class VTIViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VTI Quad-View & Contour Tool")
        self.resize(1600, 900)

        self.image_data = None
        self.is_drawing = False
        self.contours = []
        self.current_contour_points = None
        self.current_contour_actor_2d = None
        self.current_contour_actor_3d = None

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        self.contour_point_actors_2d = [] 

        # === Top Control Area ===
        top_controls_layout = QHBoxLayout()
        self.open_btn = QPushButton("Open VTI File")
        self.open_btn.clicked.connect(self.open_vti)
        self.draw_btn = QPushButton("Start Drawing Contour")
        self.draw_btn.setCheckable(True)
        self.draw_btn.clicked.connect(self.toggle_drawing)
        self.clear_btn = QPushButton("Clear Current Contour")
        self.clear_btn.clicked.connect(self.clear_current_contour)
        top_controls_layout.addWidget(self.open_btn)
        top_controls_layout.addWidget(self.draw_btn)
        top_controls_layout.addWidget(self.clear_btn)
        top_controls_layout.addStretch()
        self.main_layout.addLayout(top_controls_layout)

        # === Add "Calculate" Functionality ===
        self.calc_btn = QPushButton("Calculate")
        self.calc_btn.clicked.connect(self.on_calculate)
        top_controls_layout.addWidget(self.calc_btn)

        # === Add VTI file on/off functionality ===
        self.vti_toggle_btn = QPushButton("Hide VTI")
        self.vti_toggle_btn.setCheckable(True)
        self.vti_toggle_btn.toggled.connect(self.toggle_vti_in_3d)
        top_controls_layout.addWidget(self.vti_toggle_btn)



        # === View Area (2x2 Grid) ===
        views_layout = QGridLayout()

        # 2D Axial View (Top Left)
        self.slice_widget_axial = ImageSliceViewerWidget('z', parent_viewer=self)
        axial_group = QWidget()
        axial_layout = QVBoxLayout(axial_group)
        axial_layout.setContentsMargins(0, 0, 0, 0)
        axial_label = QLabel("Axial (Z)")
        axial_label.setAlignment(Qt.AlignHCenter)
        axial_layout.addWidget(axial_label)
        axial_layout.addWidget(self.slice_widget_axial)

        # 2D Coronal View (Top Right)
        self.slice_widget_coronal = ImageSliceViewerWidget('y', parent_viewer=self)
        coronal_group = QWidget()
        coronal_layout = QVBoxLayout(coronal_group)
        coronal_layout.setContentsMargins(0, 0, 0, 0)
        coronal_label = QLabel("Coronal (Y)")
        coronal_label.setAlignment(Qt.AlignHCenter)
        coronal_layout.addWidget(coronal_label)
        coronal_layout.addWidget(self.slice_widget_coronal)

        # 2D Sagittal View (Bottom Left)
        self.slice_widget_sagittal = ImageSliceViewerWidget('x', parent_viewer=self)
        sagittal_group = QWidget()
        sagittal_layout = QVBoxLayout(sagittal_group)
        sagittal_layout.setContentsMargins(0, 0, 0, 0)
        sagittal_label = QLabel("Sagittal (X)")
        sagittal_label.setAlignment(Qt.AlignHCenter)
        sagittal_layout.addWidget(sagittal_label)
        sagittal_layout.addWidget(self.slice_widget_sagittal)

        # 3D View (Bottom Right)
        self.vtk_widget_3d = QVTKRenderWindowInteractor()
        self.renderer_3d = vtk.vtkRenderer()
        self.renderer_3d.SetBackground(0.7, 0.7, 0.7)
        self.vtk_widget_3d.GetRenderWindow().AddRenderer(self.renderer_3d)
        self.interactor_3d = self.vtk_widget_3d.GetRenderWindow().GetInteractor()
        self.interactor_3d.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())

        viewer3d_group = QWidget()
        viewer3d_layout = QVBoxLayout(viewer3d_group)
        viewer3d_layout.setContentsMargins(0, 0, 0, 0)
        viewer3d_label = QLabel("3D View")
        viewer3d_label.setAlignment(Qt.AlignHCenter)
        viewer3d_layout.addWidget(viewer3d_label)
        viewer3d_layout.addWidget(self.vtk_widget_3d)

        # Set the three 2D views to the same light gray background
        for w in [self.slice_widget_axial, self.slice_widget_coronal, self.slice_widget_sagittal]:
            w.renderer.SetBackground(0.7, 0.7, 0.7)


        # === Add a small coordinate axis to the 3D window ===
        axes_actor = vtk.vtkAxesActor()
        # Make it bold
        axes_actor.GetXAxisShaftProperty().SetLineWidth(4)
        axes_actor.GetYAxisShaftProperty().SetLineWidth(4)
        axes_actor.GetZAxisShaftProperty().SetLineWidth(4)


        self.orientation_marker = vtk.vtkOrientationMarkerWidget()
        self.orientation_marker.SetOrientationMarker(axes_actor)
        self.orientation_marker.SetInteractor(self.interactor_3d)
        self.orientation_marker.SetViewport(0.8, 0.0, 1.0, 0.2)  # Bottom right 20% area
        self.orientation_marker.SetEnabled(1)
        self.orientation_marker.InteractiveOff()

        # === Assemble the views into the grid ===
        views_layout.addWidget(axial_group,    0, 0)
        views_layout.addWidget(coronal_group,  0, 1)
        views_layout.addWidget(sagittal_group, 1, 0)
        views_layout.addWidget(viewer3d_group, 1, 1) 
        self.main_layout.addLayout(views_layout)

        # Slice objects in the 3D view (retaining original code structure)
        self.image_slice_3d_axial = vtk.vtkImageSlice()
        self.image_slice_3d_coronal = vtk.vtkImageSlice()
        self.image_slice_3d_sagittal = vtk.vtkImageSlice()

        # === Bottom Slider Control Area ===
        self.setup_controls_ui()
        self.main_layout.addWidget(self.controls_group)

        # Initialize interactors
        self.slice_widget_axial.vtk_widget.GetRenderWindow().GetInteractor().Initialize()
        self.vtk_widget_3d.GetRenderWindow().GetInteractor().Initialize()

        # Save contour objects for each slice
        self.axial_contours_per_slice = {}  # key: slice_index, value: dict with keys: points, actor2d, actor3d, etc.
        self.current_axial_slice = None     # The currently displayed axial slice

        # === Pre-store VTP files for later use ===
        self.vtp_file_list = [
            "D:/HuaweiMoveData/Users/lyxx01/Desktop/ISURE/segmentation_demo/vtp/ensemble_nc1_moved.vtp",
            "D:/HuaweiMoveData/Users/lyxx01/Desktop/ISURE/segmentation_demo/vtp/ensemble_nc2_moved.vtp",
            "D:/HuaweiMoveData/Users/lyxx01/Desktop/ISURE/segmentation_demo/vtp/ensemble_nc3_moved.vtp",
            "D:/HuaweiMoveData/Users/lyxx01/Desktop/ISURE/segmentation_demo/vtp/ensemble_nc4_moved.vtp"
        ]
        self.current_vtp_actor = None
        self.vtp_file_index = 0  # Used to control which VTP file is displayed in the current step


    def setup_controls_ui(self):
        """Creates the slider control panel."""
        self.controls_group = QGroupBox("Slice Controls")
        layout = QFormLayout(self.controls_group)
        
        # Axial
        self.slider_axial = QSlider(Qt.Horizontal)
        self.label_axial_min = QLabel("N/A")
        self.label_axial_max = QLabel("N/A")
        self.label_axial_value = QLabel("N/A")
        axial_layout = QHBoxLayout()
        axial_layout.addWidget(self.label_axial_min)
        axial_layout.addWidget(self.slider_axial)
        axial_layout.addWidget(self.label_axial_max)
        axial_layout.addWidget(QLabel("Current:"))
        axial_layout.addWidget(self.label_axial_value)
        layout.addRow("Axial (Z):", axial_layout)

        # Coronal
        self.slider_coronal = QSlider(Qt.Horizontal)
        self.label_coronal_min = QLabel("N/A")
        self.label_coronal_max = QLabel("N/A")
        self.label_coronal_value = QLabel("N/A")
        coronal_layout = QHBoxLayout()
        coronal_layout.addWidget(self.label_coronal_min)
        coronal_layout.addWidget(self.slider_coronal)
        coronal_layout.addWidget(self.label_coronal_max)
        coronal_layout.addWidget(QLabel("Current:"))
        coronal_layout.addWidget(self.label_coronal_value)
        layout.addRow("Coronal (Y):", coronal_layout)

        # Sagittal
        self.slider_sagittal = QSlider(Qt.Horizontal)
        self.label_sagittal_min = QLabel("N/A")
        self.label_sagittal_max = QLabel("N/A")
        self.label_sagittal_value = QLabel("N/A")
        sagittal_layout = QHBoxLayout()
        sagittal_layout.addWidget(self.label_sagittal_min)
        sagittal_layout.addWidget(self.slider_sagittal)
        sagittal_layout.addWidget(self.label_sagittal_max)
        sagittal_layout.addWidget(QLabel("Current:"))
        sagittal_layout.addWidget(self.label_sagittal_value)
        layout.addRow("Sagittal (X):", sagittal_layout)

        # Connect slider signals
        self.slider_axial.valueChanged.connect(self.update_slices)
        self.slider_coronal.valueChanged.connect(self.update_slices)
        self.slider_sagittal.valueChanged.connect(self.update_slices)
        self.controls_group.setEnabled(False)

    def show_actual_rotation_center_marker(self):
        """Displays a small sphere in the 3D window at the actual rotation center (i.e., Camera FocalPoint)."""
        camera = self.renderer_3d.GetActiveCamera()
        focal_point = camera.GetFocalPoint()

        # Prevent duplicate actors
        if hasattr(self, "_actual_rotation_center_actor") and self._actual_rotation_center_actor:
            self.renderer_3d.RemoveActor(self._actual_rotation_center_actor)

        # Sphere source
        sphere = vtk.vtkSphereSource()
        sphere.SetCenter(*focal_point)
        # Set the sphere's size to 2% of the global dimensions
        if self.image_data:
            bounds = self.image_data.GetBounds()
            max_dim = max(bounds[1]-bounds[0], bounds[3]-bounds[2], bounds[5]-bounds[4])
            radius = max_dim * 0.02
        else:
            radius = 5
        sphere.SetRadius(radius)
        sphere.SetThetaResolution(32)
        sphere.SetPhiResolution(32)

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(sphere.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(0, 1, 0)  # Green, to distinguish from the data center

        self.renderer_3d.AddActor(actor)
        self._actual_rotation_center_actor = actor

        self.vtk_widget_3d.GetRenderWindow().Render()





    def open_vti(self):
        """Opens a VTI file."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select VTI File", "", "VTI Files (*.vti)")
        if file_path:
            self.load_vti(file_path)

    def load_vti(self, file_path):
        """Loads a VTI file and initializes all views."""
        reader = vtk.vtkXMLImageDataReader()
        reader.SetFileName(file_path)
        reader.Update()
        self.image_data = reader.GetOutput()

        if not self.image_data:
            QMessageBox.critical(self, "Error", "Failed to load VTI file.")
            return

        scalar_range = self.image_data.GetScalarRange()
        window = scalar_range[1] - scalar_range[0]
        level = (scalar_range[0] + scalar_range[1]) / 2.0
        if window == 0: window = 1.0

        # --- Initialize 2D views ---
        for widget in [self.slice_widget_axial, self.slice_widget_coronal, self.slice_widget_sagittal]:
            widget.set_input_data(self.image_data)
            widget.set_color_window(window)
            widget.set_color_level(level)
        
        # --- Initialize slices in the 3D view ---
        self.renderer_3d.RemoveAllViewProps()
        slice_mappers_3d = {
            'axial': vtk.vtkImageSliceMapper(),
            'coronal': vtk.vtkImageSliceMapper(),
            'sagittal': vtk.vtkImageSliceMapper()
        }
        
        slice_mappers_3d['axial'].SetOrientation(2)
        self.image_slice_3d_axial.SetMapper(slice_mappers_3d['axial'])
        slice_mappers_3d['axial'].SetInputData(self.image_data)
        self.image_slice_3d_axial.GetProperty().SetColorWindow(window)
        self.image_slice_3d_axial.GetProperty().SetColorLevel(level)

        slice_mappers_3d['coronal'].SetOrientation(1)
        self.image_slice_3d_coronal.SetMapper(slice_mappers_3d['coronal'])
        slice_mappers_3d['coronal'].SetInputData(self.image_data)
        self.image_slice_3d_coronal.GetProperty().SetColorWindow(window)
        self.image_slice_3d_coronal.GetProperty().SetColorLevel(level)

        slice_mappers_3d['sagittal'].SetOrientation(0)
        self.image_slice_3d_sagittal.SetMapper(slice_mappers_3d['sagittal'])
        slice_mappers_3d['sagittal'].SetInputData(self.image_data)
        self.image_slice_3d_sagittal.GetProperty().SetColorWindow(window)
        self.image_slice_3d_sagittal.GetProperty().SetColorLevel(level)

        self.renderer_3d.AddActor(self.image_slice_3d_axial)
        self.renderer_3d.AddActor(self.image_slice_3d_coronal)
        self.renderer_3d.AddActor(self.image_slice_3d_sagittal)

        # --- Initialize sliders ---
        extent = self.image_data.GetExtent()
        self.slider_sagittal.setRange(extent[0], extent[1])
        self.slider_coronal.setRange(extent[2], extent[3])
        self.slider_axial.setRange(extent[4], extent[5])
        self.slider_sagittal.setValue((extent[0] + extent[1]) // 2)
        self.slider_coronal.setValue((extent[2] + extent[3]) // 2)
        self.slider_axial.setValue((extent[4] + extent[5]) // 2)
        
        self.controls_group.setEnabled(True)
        self.update_slices()

        # ====== Correct the 3D view camera's rotation center to the data center ======
        center = self.image_data.GetCenter()
        bounds = self.image_data.GetBounds()
        camera = self.renderer_3d.GetActiveCamera() 
        camera.SetFocalPoint(*center)



        # Position the camera at a reasonable distance based on the data size
        # Set the camera position on the positive z-axis, at a distance from the center
        max_dim = 1.5*max(bounds[1]-bounds[0], bounds[3]-bounds[2], bounds[5]-bounds[4])
        camera.SetPosition(
            center[0] + max_dim,
            center[1] + max_dim,
            center[2] + max_dim
        )
        camera.SetFocalPoint(*center)
        camera.SetViewUp(0, 0, 1)  # Ensure the Z-axis is pointing up


        self.renderer_3d.ResetCameraClippingRange()
        self.vtk_widget_3d.GetRenderWindow().Render()

        # self.show_actual_rotation_center_marker()  # Show the small sphere for the actual rotation center



    def update_slices(self):
        if not self.image_data:
            return

        prev_axial = getattr(self, "current_axial_slice", None)
        axial_slice = self.slider_axial.value()
        coronal_slice = self.slider_coronal.value()
        sagittal_slice = self.slider_sagittal.value()
        self.current_axial_slice = axial_slice

        # --------- 1. In the 2D window, hide the contours and cubes from the previous slice only ---------
        if prev_axial is not None:
            contour_list = self.axial_contours_per_slice.get(prev_axial, [])
            for contour_info in contour_list:
                if contour_info.get('actor2d'):
                    self.slice_widget_axial.renderer.RemoveActor(contour_info['actor2d'])
                for cube in contour_info.get('cube_actors', []):
                    self.slice_widget_axial.renderer.RemoveActor(cube)
        # Do nothing in the 3D window (do not remove actors)

        # --------- 2. Update slice rendering ---------
        self.slice_widget_axial.set_slice(axial_slice)
        self.slice_widget_coronal.set_slice(coronal_slice)
        self.slice_widget_sagittal.set_slice(sagittal_slice)

        # --------- 3. In the 2D window, add the contours and cubes for the current slice only ---------
        contour_list = self.axial_contours_per_slice.get(axial_slice, [])
        for contour_info in contour_list:
            if contour_info.get('actor2d'):
                self.slice_widget_axial.renderer.AddActor(contour_info['actor2d'])
            for cube in contour_info.get('cube_actors', []):
                self.slice_widget_axial.renderer.AddActor(cube)
        # Do nothing in the 3D window (actors have already been added permanently)

        # --------- 4. Update physical coordinate labels ---------
        origin = self.image_data.GetOrigin()
        spacing = self.image_data.GetSpacing()
        axial_coord = origin[2] + axial_slice * spacing[2]
        coronal_coord = origin[1] + coronal_slice * spacing[1]
        sagittal_coord = origin[0] + sagittal_slice * spacing[0]
        self.label_axial_value.setText(f"{axial_coord:.2f} (slice: {axial_slice})")
        self.label_coronal_value.setText(f"{coronal_coord:.2f} (slice: {coronal_slice})")
        self.label_sagittal_value.setText(f"{sagittal_coord:.2f} (slice: {sagittal_slice})")

        self.image_slice_3d_axial.GetMapper().SetSliceNumber(axial_slice)
        self.image_slice_3d_coronal.GetMapper().SetSliceNumber(coronal_slice)
        self.image_slice_3d_sagittal.GetMapper().SetSliceNumber(sagittal_slice)

        self.renderer_3d.ResetCameraClippingRange()
        self.slice_widget_axial.vtk_widget.GetRenderWindow().Render()
        self.slice_widget_coronal.vtk_widget.GetRenderWindow().Render()
        self.slice_widget_sagittal.vtk_widget.GetRenderWindow().Render()
        self.vtk_widget_3d.GetRenderWindow().Render()




    def toggle_drawing(self, checked):
        """Toggles drawing mode."""
        self.is_drawing = checked

        interactor = self.slice_widget_axial.vtk_widget.GetRenderWindow().GetInteractor()
        if self.is_drawing:
            contour_style = ContourInteractorStyle(parent_viewer=self)
            contour_style.SetDefaultRenderer(self.slice_widget_axial.renderer)
            interactor.SetInteractorStyle(contour_style)
        else:
            pan_style = PanWithMiddleButtonInteractorStyle()
            pan_style.SetDefaultRenderer(self.slice_widget_axial.renderer)
            interactor.SetInteractorStyle(pan_style)

        if self.is_drawing:
            self.draw_btn.setText("Finish Drawing")
            self.current_contour_points = vtk.vtkPoints()
            self.current_contour_cubes = []  # <--- New: Used to store the small cube actors for the current contour

            self.polydata_2d = vtk.vtkPolyData()
            self.polydata_2d.SetPoints(self.current_contour_points)
            self.polydata_2d.SetLines(vtk.vtkCellArray())
            self.polydata_2d.SetPolys(vtk.vtkCellArray())

            mapper2d = vtk.vtkPolyDataMapper()
            mapper2d.SetInputData(self.polydata_2d)
            self.current_contour_actor_2d = vtk.vtkActor()
            self.current_contour_actor_2d.SetMapper(mapper2d)
            self.current_contour_actor_2d.GetProperty().SetColor(1, 1, 0)  # Yellow
            self.current_contour_actor_2d.GetProperty().SetLineWidth(2)
            self.current_contour_actor_2d.PickableOff()
            self.slice_widget_axial.renderer.AddActor(self.current_contour_actor_2d)

            self.polydata_3d = vtk.vtkPolyData()
            self.polydata_3d.DeepCopy(self.polydata_2d)

            mapper3d = vtk.vtkPolyDataMapper()
            mapper3d.SetInputData(self.polydata_3d)
            self.current_contour_actor_3d = vtk.vtkActor()
            self.current_contour_actor_3d.SetMapper(mapper3d)
            self.current_contour_actor_3d.GetProperty().SetColor(1, 1, 0)
            self.current_contour_actor_3d.GetProperty().SetLineWidth(4)
            self.renderer_3d.AddActor(self.current_contour_actor_3d)

        else:
            self.draw_btn.setText("Start Drawing Contour")
            if self.current_contour_points and self.current_contour_points.GetNumberOfPoints() > 0:
                # --------- Storing multiple contours ----------
                if self.current_axial_slice not in self.axial_contours_per_slice:
                    self.axial_contours_per_slice[self.current_axial_slice] = []
                self.axial_contours_per_slice[self.current_axial_slice].append({
                    'points': self.current_contour_points,
                    'actor2d': self.current_contour_actor_2d,
                    'actor3d': self.current_contour_actor_3d,
                    'cube_actors': self.current_contour_cubes,  # <--- New
                })
            self.current_contour_points = None
            self.current_contour_actor_2d = None
            self.current_contour_actor_3d = None
            self.current_contour_cubes = []  # <--- New




    def add_contour_point(self, pos):
        if not self.is_drawing or not self.current_contour_points:
            return

        spacing = self.image_data.GetSpacing() if self.image_data else [1, 1, 1]
        origin = self.image_data.GetOrigin() if self.image_data else [0, 0, 0]
        current_slice = self.slider_axial.value()
        slice_z = origin[2] + current_slice * spacing[2]
        contour_z_2d = slice_z + spacing[2] * 20  # Z-offset for 2D visualization to prevent z-fighting

        # 1. Store the original point in self.current_contour_points
        self.current_contour_points.InsertNextPoint(pos)
        num_points = self.current_contour_points.GetNumberOfPoints()

        # 2. Refresh the 2D contour (smooth, closed, with a z-offset)
        if num_points >= 2:
            spline2d = vtk.vtkParametricSpline()
            points_2d = vtk.vtkPoints()
            for i in range(num_points):
                pt = self.current_contour_points.GetPoint(i)
                points_2d.InsertNextPoint(pt[0], pt[1], contour_z_2d)
            points_2d.InsertNextPoint(self.current_contour_points.GetPoint(0)[0],
                                    self.current_contour_points.GetPoint(0)[1],
                                    contour_z_2d)  # Close the loop
            spline2d.SetPoints(points_2d)
            splineSource2d = vtk.vtkParametricFunctionSource()
            splineSource2d.SetParametricFunction(spline2d)
            splineSource2d.SetUResolution(200)
            splineSource2d.Update()
            self.polydata_2d.ShallowCopy(splineSource2d.GetOutput())
        else:
            points_2d = vtk.vtkPoints()
            pt = self.current_contour_points.GetPoint(0)
            points_2d.InsertNextPoint(pt[0], pt[1], contour_z_2d)
            self.polydata_2d.SetPoints(points_2d)
            self.polydata_2d.SetLines(vtk.vtkCellArray())
            self.polydata_2d.SetPolys(vtk.vtkCellArray())
        self.polydata_2d.Modified()

        # The 2D line actor refreshes automatically; no need to re-add (it was added during initialization)

        # 2D cube
        cube = vtk.vtkCubeSource()
        size = 2
        cube.SetCenter(pos[0], pos[1], contour_z_2d)
        cube.SetXLength(size)
        cube.SetYLength(size)
        cube.SetZLength(size)
        cube.Update()
        cube_mapper = vtk.vtkPolyDataMapper()
        cube_mapper.SetInputConnection(cube.GetOutputPort())
        cube_actor = vtk.vtkActor()
        cube_actor.SetMapper(cube_mapper)
        cube_actor.GetProperty().SetColor(1, 0, 0)
        cube_actor.GetProperty().SetOpacity(1.0)
        self.slice_widget_axial.renderer.AddActor(cube_actor)
        self.current_contour_cubes.append(cube_actor)

        # 3. Refresh the 3D contour (smooth, closed, at the physical Z coordinate)
        if num_points >= 2:
            spline3d = vtk.vtkParametricSpline()
            points_3d = vtk.vtkPoints()
            for i in range(num_points):
                pt = self.current_contour_points.GetPoint(i)
                points_3d.InsertNextPoint(pt[0], pt[1], slice_z)
            points_3d.InsertNextPoint(self.current_contour_points.GetPoint(0)[0],
                                    self.current_contour_points.GetPoint(0)[1],
                                    slice_z)  # Close the loop
            spline3d.SetPoints(points_3d)
            splineSource3d = vtk.vtkParametricFunctionSource()
            splineSource3d.SetParametricFunction(spline3d)
            splineSource3d.SetUResolution(200)
            splineSource3d.Update()
            self.polydata_3d.ShallowCopy(splineSource3d.GetOutput())
        else:
            points_3d = vtk.vtkPoints()
            pt = self.current_contour_points.GetPoint(0)
            points_3d.InsertNextPoint(pt[0], pt[1], slice_z)
            self.polydata_3d.SetPoints(points_3d)
            self.polydata_3d.SetLines(vtk.vtkCellArray())
            self.polydata_3d.SetPolys(vtk.vtkCellArray())
        self.polydata_3d.Modified()

        # Refresh the display
        self.slice_widget_axial.renderer.ResetCameraClippingRange()
        self.slice_widget_axial.vtk_widget.GetRenderWindow().Render()
        self.vtk_widget_3d.GetRenderWindow().Render()


    def clear_current_contour(self):
        """Clears the contour currently being drawn."""
        if self.current_contour_actor_2d:
            self.slice_widget_axial.renderer.RemoveActor(self.current_contour_actor_2d)
        if self.current_contour_actor_3d:
            self.renderer_3d.RemoveActor(self.current_contour_actor_3d)

        self.slice_widget_axial.vtk_widget.GetRenderWindow().Render()
        self.vtk_widget_3d.GetRenderWindow().Render()
        
        self.current_contour_points = None
        self.current_contour_actor_2d = None
        self.current_contour_actor_3d = None
        
        if self.is_drawing:
            self.draw_btn.setChecked(False)
            self.toggle_drawing(False)
        
        for actor in getattr(self, 'contour_point_actors_2d', []):
            self.slice_widget_axial.renderer.RemoveActor(actor)
        self.contour_point_actors_2d = []
    
    def on_calculate(self):
        # 1. Check if the contour drawing is complete
        # It's sufficient if the current slice has at least one contour
        contour_list = self.axial_contours_per_slice.get(self.current_axial_slice, [])
        if not contour_list:
            QMessageBox.warning(self, "Warning", "Please draw and finish at least one contour on the current slice before clicking Calculate!")
            return


        # 2. Display a progress bar (simulating a calculation)
        self.progress = QProgressDialog("Calculating...", None, 0, 100, self)
        self.progress.setWindowTitle("Processing")
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setAutoClose(True)
        self.progress.setCancelButton(None)
        self.progress.show()

        # Use QTimer to simulate progress
        self._calc_step = 0
        total_steps = 100
        interval = 300  # ms, 0.3s/step, 100*0.3s = 30s
        def advance_progress():
            self._calc_step += 1
            self.progress.setValue(self._calc_step)
            # The print statement that was here has been removed.
            if self._calc_step >= total_steps:
                self.progress.setValue(total_steps)
                self.progress.close()
                QTimer.singleShot(200, self.load_vtp_after_calc)  # A slight delay can be added here
            else:
                QTimer.singleShot(interval, advance_progress)
        advance_progress()

    def load_vtp_after_calc(self):
        # 1. Automatically read the VTP file at the current index
        if self.vtp_file_index >= len(self.vtp_file_list):
            QMessageBox.information(self, "Info", "All steps are complete.")
            return
        vtp_path = self.vtp_file_list[self.vtp_file_index]

        reader = vtk.vtkXMLPolyDataReader()
        reader.SetFileName(vtp_path)
        reader.Update()
        polydata = reader.GetOutput()
        if not polydata or polydata.GetNumberOfPoints() == 0:
            QMessageBox.critical(self, "Error", f"VTP error: {vtp_path}")
            return

        # Replace the previously displayed VTP
        if self.current_vtp_actor is not None:
            self.renderer_3d.RemoveActor(self.current_vtp_actor)

        vtp_mapper = vtk.vtkPolyDataMapper()
        vtp_mapper.SetInputData(polydata)
        vtp_actor = vtk.vtkActor()
        vtp_actor.SetMapper(vtp_mapper)
        vtp_actor.GetProperty().SetColor(0.5, 0.5, 0.5) # Gray
        vtp_actor.GetProperty().SetOpacity(0.3) # Opacity
        self.renderer_3d.AddActor(vtp_actor)

        # --- New: Reset camera focal point when switching to VTP-only view ---
        if self.vti_toggle_btn.isChecked():  # If VTI is in a hidden state
            bounds = vtp_actor.GetBounds()
            center = [
                0.5 * (bounds[0] + bounds[1]),
                0.5 * (bounds[2] + bounds[3]),
                0.5 * (bounds[4] + bounds[5])
            ]
            camera = self.renderer_3d.GetActiveCamera()
            camera.SetFocalPoint(*center)
            max_dim = max(bounds[1]-bounds[0], bounds[3]-bounds[2], bounds[5]-bounds[4])
            camera.SetPosition(center[0], center[1], center[2] + max_dim * 2)
            camera.SetViewUp(0, 1, 0)
            self.renderer_3d.ResetCameraClippingRange()
            self.vtk_widget_3d.GetRenderWindow().Render()

        self.current_vtp_actor = vtp_actor

        self.vtk_widget_3d.GetRenderWindow().Render()

        # Step to the next file
        self.vtp_file_index += 1

    def toggle_vti_in_3d(self, checked):
        """
        Toggles the VTI visibility on/off. checked=True hides, False shows.
        """
        # Control the visibility of the three slice plane actors
        for actor in [self.image_slice_3d_axial, self.image_slice_3d_coronal, self.image_slice_3d_sagittal]:
            actor.SetVisibility(not checked)
        # Update button text
        if checked:
            self.vti_toggle_btn.setText("Show VTI")
        else:
            self.vti_toggle_btn.setText("Hide VTI")
        self.vtk_widget_3d.GetRenderWindow().Render()





# Disable the vtkOutputWindow popup
vtk.vtkObject.GlobalWarningDisplayOff()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VTIViewer()
    window.show()

    # First, initialize the interactor and interactor style
    interactor = window.slice_widget_axial.vtk_widget.GetRenderWindow().GetInteractor()
    style = ContourInteractorStyle(parent_viewer=window)
    style.SetDefaultRenderer(window.slice_widget_axial.renderer)
    interactor.SetInteractorStyle(style)

    interactor.Initialize()
    interactor.Start()  # Activate the VTK event loop

    sys.exit(app.exec_())