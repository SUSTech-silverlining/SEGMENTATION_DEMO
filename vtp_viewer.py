import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QFileDialog, QPushButton,
                             QVBoxLayout, QWidget, QSlider, QLabel, QGroupBox,
                             QFormLayout, QHBoxLayout)
from PyQt5.QtCore import Qt
import vtk
from vtk.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor


class SliceViewerWindow(QWidget):
    def __init__(self, title, view_axis, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setGeometry(100, 100, 400, 400) # x, y, width, height

        # --- VTK Components ---
        self.vtk_widget = QVTKRenderWindowInteractor(self)
        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(0.2, 0.2, 0.2) # Dark gray background
        self.vtk_widget.GetRenderWindow().AddRenderer(self.renderer)

        # --- Setup 2D Camera ---
        camera = self.renderer.GetActiveCamera()
        camera.SetParallelProjection(True) # Key step: Set to orthographic projection for 2D effect

        # Set camera position based on the view axis
        if view_axis == 'x': # YZ Plane (view from X-axis)
            camera.SetPosition(1, 0, 0)
            camera.SetViewUp(0, 0, 1)
        elif view_axis == 'y': # XZ Plane (view from Y-axis)
            camera.SetPosition(0, 1, 0)
            camera.SetViewUp(0, 0, 1)
        elif view_axis == 'z': # XY Plane (view from Z-axis)
            camera.SetPosition(0, 0, 1)
            camera.SetViewUp(0, 1, 0)
            
        # Set interaction style to 2D mode (mainly for pan and zoom)
        interactor_style = vtk.vtkInteractorStyleImage()
        self.vtk_widget.GetRenderWindow().GetInteractor().SetInteractorStyle(interactor_style)

        # --- Layout ---
        layout = QVBoxLayout()
        layout.addWidget(self.vtk_widget)
        self.setLayout(layout)

        # --- Data Actor ---
        self.actor = vtk.vtkActor()
        self.actor.GetProperty().SetColor(1, 1, 1) # White outline
        self.actor.GetProperty().SetLineWidth(2)
        self.renderer.AddActor(self.actor)
        
    def update_data(self, polydata):
        """Public method to update the displayed slice data from outside."""
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(polydata)
        self.actor.SetMapper(mapper)
        
        # Automatically adjust the camera to fit the new data
        self.renderer.ResetCamera()
        self.vtk_widget.GetRenderWindow().Render()
        

class VTPViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VTP 3D/2D Viewer")
        self.resize(1000, 800)

        # --- Initialize core VTK and data variables ---
        self.polydata = None
        self.bounds = None
        self.frame = QWidget()
        self.main_layout = QVBoxLayout()
        self.frame.setLayout(self.main_layout)
        self.setCentralWidget(self.frame)

        # --- Create and add UI controls ---
        # Use a horizontal layout for the top buttons
        top_button_layout = QHBoxLayout()
        self.open_btn = QPushButton("Open VTP File")
        self.open_btn.clicked.connect(self.open_vtp)
        top_button_layout.addWidget(self.open_btn)

        # Button to show/hide 2D windows
        self.toggle_2d_btn = QPushButton("Show/Hide 2D Slice Windows")
        self.toggle_2d_btn.setCheckable(True) # Make it a toggle button
        self.toggle_2d_btn.clicked.connect(self.toggle_slice_windows)
        top_button_layout.addWidget(self.toggle_2d_btn)
        
        self.main_layout.addLayout(top_button_layout)

        # 3D VTK Render Window
        self.vtk_widget = QVTKRenderWindowInteractor(self.frame)
        self.main_layout.addWidget(self.vtk_widget)

        # Slice control panel
        self.setup_controls_ui()

        # Renderer and VTK object initialization
        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(0.1, 0.2, 0.4) 
        self.vtk_widget.GetRenderWindow().AddRenderer(self.renderer)
        self.interactor = self.vtk_widget.GetRenderWindow().GetInteractor()
        style = vtk.vtkInteractorStyleJoystickCamera()
        self.interactor.SetInteractorStyle(style)

        self.main_actor = vtk.vtkActor()
        self.plane_x = vtk.vtkPlane()
        self.plane_y = vtk.vtkPlane()
        self.plane_z = vtk.vtkPlane()
        self.cutter_x = vtk.vtkCutter()
        self.cutter_y = vtk.vtkCutter()
        self.cutter_z = vtk.vtkCutter()
        
        # Slice Actors in the 3D view
        self.slice_actor_x = self.create_slice_actor(self.cutter_x, [1, 0, 0]) 
        self.slice_actor_y = self.create_slice_actor(self.cutter_y, [0, 1, 0]) 
        self.slice_actor_z = self.create_slice_actor(self.cutter_z, [0, 0, 1]) 
        
        self.intersection_sphere = vtk.vtkSphereSource()
        intersection_mapper = vtk.vtkPolyDataMapper()
        intersection_mapper.SetInputConnection(self.intersection_sphere.GetOutputPort())
        self.intersection_actor = vtk.vtkActor()
        self.intersection_actor.SetMapper(intersection_mapper)
        self.intersection_actor.GetProperty().SetColor(1, 1, 0)
        
        # Create instances of the three 2D slice sub-windows
        self.slice_window_xy = SliceViewerWindow("XY Plane", 'z')
        self.slice_window_yz = SliceViewerWindow("YZ Plane", 'x')
        self.slice_window_xz = SliceViewerWindow("XZ Plane", 'y')

        # Create and setup the axes widget
        axes_actor = vtk.vtkAxesActor()

        self.orientation_widget = vtk.vtkOrientationMarkerWidget() 
        self.orientation_widget.SetOrientationMarker(axes_actor)
        self.orientation_widget.SetInteractor(self.interactor)
        self.orientation_widget.SetViewport(0.0, 0.0, 0.2, 0.2)
        self.orientation_widget.SetEnabled(1)
        self.orientation_widget.InteractiveOff()

    def closeEvent(self, event):
        """Override the close event to ensure all child windows are closed."""
        self.slice_window_xy.close()
        self.slice_window_yz.close()
        self.slice_window_xz.close()
        super().closeEvent(event)

    def toggle_slice_windows(self):
        """Show or hide the three 2D windows based on the button state."""
        if self.toggle_2d_btn.isChecked():
            self.slice_window_xy.show()
            self.slice_window_yz.show()
            self.slice_window_xz.show()
        else:
            self.slice_window_xy.hide()
            self.slice_window_yz.hide()
            self.slice_window_xz.hide()
    
    def setup_controls_ui(self):
        """Setup the UI for slice controls."""
        self.controls_group = QGroupBox("Slice Controls")
        controls_layout = QFormLayout()
        self.slider_x = QSlider(Qt.Horizontal)
        self.label_x = QLabel("N/A")
        self.slider_x.valueChanged.connect(self.update_slices)
        controls_layout.addRow("X Coordinate:", self.slider_x)
        controls_layout.addRow("Current Value:", self.label_x)
        self.slider_y = QSlider(Qt.Horizontal)
        self.label_y = QLabel("N/A")
        self.slider_y.valueChanged.connect(self.update_slices)
        controls_layout.addRow("Y Coordinate:", self.slider_y)
        controls_layout.addRow("Current Value:", self.label_y)
        self.slider_z = QSlider(Qt.Horizontal)
        self.label_z = QLabel("N/A")
        self.slider_z.valueChanged.connect(self.update_slices)
        controls_layout.addRow("Z Coordinate:", self.slider_z)
        controls_layout.addRow("Current Value:", self.label_z)
        self.controls_group.setLayout(controls_layout)
        self.controls_group.setEnabled(False) 
        self.main_layout.addWidget(self.controls_group)

    def create_slice_actor(self, cutter, color):
        """Helper function to create a slice actor."""
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(cutter.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(color)
        actor.GetProperty().SetLineWidth(2)
        return actor
    
    def open_vtp(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select VTP File", "", "VTP Files (*.vtp)")
        if file_path:
            self.load_vtp(file_path)

    def load_vtp(self, file_path):
        """Load a VTP file and setup the renderers."""
        self.renderer.RemoveAllViewProps()
        reader = vtk.vtkXMLPolyDataReader()
        reader.SetFileName(file_path)
        reader.Update()
        self.polydata = reader.GetOutput()
        self.bounds = self.polydata.GetBounds()
        main_mapper = vtk.vtkPolyDataMapper()
        main_mapper.SetInputData(self.polydata)
        self.main_actor.SetMapper(main_mapper)
        self.main_actor.GetProperty().SetOpacity(0.3) 
        self.main_actor.GetProperty().SetColor(0.8, 0.8, 0.8)
        self.main_actor.GetProperty().EdgeVisibilityOff()
        cutters = [self.cutter_x, self.cutter_y, self.cutter_z]
        planes = [self.plane_x, self.plane_y, self.plane_z]
        normals = [(1, 0, 0), (0, 1, 0), (0, 0, 1)]
        for cutter, plane, normal in zip(cutters, planes, normals):
            plane.SetNormal(normal)
            cutter.SetInputData(self.polydata)
            cutter.SetCutFunction(plane)
        diag = self.polydata.GetLength() 
        self.intersection_sphere.SetRadius(diag * 0.01) 
        self.renderer.AddActor(self.main_actor)
        self.renderer.AddActor(self.slice_actor_x)
        self.renderer.AddActor(self.slice_actor_y)
        self.renderer.AddActor(self.slice_actor_z)
        self.renderer.AddActor(self.intersection_actor)
        self.slider_x.setRange(0, 1000)
        self.slider_y.setRange(0, 1000)
        self.slider_z.setRange(0, 1000)
        self.slider_x.setValue(500)
        self.slider_y.setValue(500)
        self.slider_z.setValue(500)
        self.controls_group.setEnabled(True)
        self.update_slices()
        self.renderer.ResetCamera()
        self.vtk_widget.GetRenderWindow().Render()

    def update_slices(self):
        """Update all views (3D and 2D) based on the slider values."""
        if self.polydata is None:
            return

        x_range = self.bounds[1] - self.bounds[0]
        y_range = self.bounds[3] - self.bounds[2]
        z_range = self.bounds[5] - self.bounds[4]
        x = self.bounds[0] + x_range * self.slider_x.value() / 1000.0
        y = self.bounds[2] + y_range * self.slider_y.value() / 1000.0
        z = self.bounds[4] + z_range * self.slider_z.value() / 1000.0
        self.label_x.setText(f"{x:.2f}")
        self.label_y.setText(f"{y:.2f}")
        self.label_z.setText(f"{z:.2f}")
        self.plane_x.SetOrigin(x, y, z)
        self.plane_y.SetOrigin(x, y, z)
        self.plane_z.SetOrigin(x, y, z)
        self.intersection_actor.SetPosition(x, y, z)

        # Trigger redraw of the 3D main window
        self.vtk_widget.GetRenderWindow().Render()
        
        # Update the data in the three 2D sub-windows
        # Note the correspondence between cutters and planes:
        # cutter_x (normal 1,0,0) -> YZ Plane
        # cutter_y (normal 0,1,0) -> XZ Plane
        # cutter_z (normal 0,0,1) -> XY Plane
        self.slice_window_yz.update_data(self.cutter_x.GetOutput())
        self.slice_window_xz.update_data(self.cutter_y.GetOutput())
        self.slice_window_xy.update_data(self.cutter_z.GetOutput())

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VTPViewer()
    window.show()
    # 2D windows are initially hidden, shown by user action
    sys.exit(app.exec_())
