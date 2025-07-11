import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QFileDialog, QPushButton,
                             QVBoxLayout, QWidget, QSlider, QLabel, QGroupBox,
                             QFormLayout, QHBoxLayout)
from PyQt5.QtCore import Qt
import vtk
from vtk.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor


class SliceViewerWidget(QWidget):
    """ A QWidget for displaying a 2D slice view. """
    def __init__(self, view_axis, parent=None):
        super().__init__(parent)

        # --- VTK Components ---
        self.vtk_widget = QVTKRenderWindowInteractor(self)
        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(0.2, 0.2, 0.2)
        self.vtk_widget.GetRenderWindow().AddRenderer(self.renderer)

        # --- Setup 2D Camera ---
        camera = self.renderer.GetActiveCamera()
        camera.SetParallelProjection(True)

        if view_axis == 'x': # YZ Plane
            camera.SetPosition(1, 0, 0)
            camera.SetViewUp(0, 0, 1)
        elif view_axis == 'y': # XZ Plane
            camera.SetPosition(0, 1, 0)
            camera.SetViewUp(0, 0, 1)
        elif view_axis == 'z': # XY Plane
            camera.SetPosition(0, 0, 1)
            camera.SetViewUp(0, 1, 0)
            
        interactor_style = vtk.vtkInteractorStyleImage()
        self.vtk_widget.GetRenderWindow().GetInteractor().SetInteractorStyle(interactor_style)

        # --- Layout ---
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.vtk_widget)
        self.setLayout(layout)

        # --- Data Actor ---
        self.actor = vtk.vtkActor()
        self.actor.GetProperty().SetColor(1, 1, 1)
        self.actor.GetProperty().SetLineWidth(2)
        self.renderer.AddActor(self.actor)
        
    def update_data(self, polydata):
        if polydata and polydata.GetNumberOfPoints() > 0:
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(polydata)
            self.actor.SetMapper(mapper)
            self.renderer.ResetCamera()
        else:
            self.actor.SetMapper(None)
            
        self.vtk_widget.GetRenderWindow().Render()
        

class VTPViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VTP 3D/2D Viewer")
        self.resize(1600, 900)

        self.polydata = None
        self.bounds = None
        
        # --- Main Layout Structure ---
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        # Main vertical layout: Top controls, middle views, bottom sliders
        self.main_layout = QVBoxLayout(self.central_widget)

        # --- Top controls area (Open File button) ---
        top_controls_layout = QHBoxLayout()
        self.open_btn = QPushButton("Open VTP File")
        self.open_btn.clicked.connect(self.open_vtp)
        top_controls_layout.addWidget(self.open_btn)
        top_controls_layout.addStretch() # Pushes the button to the left
        self.main_layout.addLayout(top_controls_layout)

        # --- Views Layout (Horizontal Split: 3D view on left, 2D views on right) ---
        # This is the corrected section to prevent the layout error
        views_layout = QHBoxLayout()

        # 3D VTK Render Window (left side)
        self.vtk_widget_3d = QVTKRenderWindowInteractor()
        views_layout.addWidget(self.vtk_widget_3d, 2) # 3D view takes 2/3 of horizontal space

        # Right panel for all 2D views (vertical layout)
        right_panel_layout = QVBoxLayout()
        self.slice_widget_xy = SliceViewerWidget('z') # XY Plane
        self.slice_widget_xz = SliceViewerWidget('y') # XZ Plane
        self.slice_widget_yz = SliceViewerWidget('x') # YZ Plane
        right_panel_layout.addWidget(self.slice_widget_xy)
        right_panel_layout.addWidget(self.slice_widget_xz)
        right_panel_layout.addWidget(self.slice_widget_yz)
        
        # Add the right panel to the main horizontal views layout
        views_layout.addLayout(right_panel_layout, 1) # 2D views take 1/3 of space

        # Add the combined views layout to the main vertical layout
        self.main_layout.addLayout(views_layout)

        # --- Slice control panel (bottom) ---
        self.setup_controls_ui()
        self.main_layout.addWidget(self.controls_group)

        # --- 3D Renderer and VTK object initialization ---
        self.renderer_3d = vtk.vtkRenderer()
        self.renderer_3d.SetBackground(0.1, 0.2, 0.4)
        self.vtk_widget_3d.GetRenderWindow().AddRenderer(self.renderer_3d)
        self.interactor = self.vtk_widget_3d.GetRenderWindow().GetInteractor()
        self.interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())

        # Initialize actors and cutters
        self.main_actor = vtk.vtkActor()
        self.plane_x, self.plane_y, self.plane_z = vtk.vtkPlane(), vtk.vtkPlane(), vtk.vtkPlane()
        self.cutter_x, self.cutter_y, self.cutter_z = vtk.vtkCutter(), vtk.vtkCutter(), vtk.vtkCutter()
        
        self.slice_actor_x = self.create_slice_actor(self.cutter_x, [1, 0, 0]) 
        self.slice_actor_y = self.create_slice_actor(self.cutter_y, [0, 1, 0]) 
        self.slice_actor_z = self.create_slice_actor(self.cutter_z, [0, 0, 1]) 
        
        self.intersection_sphere = vtk.vtkSphereSource()
        intersection_mapper = vtk.vtkPolyDataMapper()
        intersection_mapper.SetInputConnection(self.intersection_sphere.GetOutputPort())
        self.intersection_actor = vtk.vtkActor()
        self.intersection_actor.SetMapper(intersection_mapper)
        self.intersection_actor.GetProperty().SetColor(1, 1, 0) # Yellow
        
        axes_actor = vtk.vtkAxesActor()
        self.orientation_widget = vtk.vtkOrientationMarkerWidget()
        self.orientation_widget.SetOrientationMarker(axes_actor)
        self.orientation_widget.SetInteractor(self.interactor)
        self.orientation_widget.SetViewport(0.0, 0.0, 0.2, 0.2)

    def setup_controls_ui(self):
        self.controls_group = QGroupBox("Slice Controls")
        layout = QFormLayout(self.controls_group)
        
        self.slider_x, self.label_x = QSlider(Qt.Horizontal), QLabel("N/A")
        self.slider_y, self.label_y = QSlider(Qt.Horizontal), QLabel("N/A")
        self.slider_z, self.label_z = QSlider(Qt.Horizontal), QLabel("N/A")
        
        self.slider_x.valueChanged.connect(self.update_slices)
        self.slider_y.valueChanged.connect(self.update_slices)
        self.slider_z.valueChanged.connect(self.update_slices)

        layout.addRow("X Slice:", self.slider_x)
        layout.addRow("Coordinate:", self.label_x)
        layout.addRow("Y Slice:", self.slider_y)
        layout.addRow("Coordinate:", self.label_y)
        layout.addRow("Z Slice:", self.slider_z)
        layout.addRow("Coordinate:", self.label_z)
        
        self.controls_group.setEnabled(False)

    def create_slice_actor(self, cutter, color):
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
        reader = vtk.vtkXMLPolyDataReader()
        reader.SetFileName(file_path)
        reader.Update()
        self.polydata = reader.GetOutput()
        
        if not self.polydata or self.polydata.GetNumberOfPoints() == 0:
            print("Error: VTP file is empty or could not be read.")
            return

        self.renderer_3d.RemoveAllViewProps()
        self.bounds = self.polydata.GetBounds()
        
        main_mapper = vtk.vtkPolyDataMapper()
        main_mapper.SetInputData(self.polydata)
        self.main_actor.SetMapper(main_mapper)
        self.main_actor.GetProperty().SetOpacity(0.3)
        self.main_actor.GetProperty().SetColor(0.8, 0.8, 0.8)
        
        for cutter, plane, normal in zip(
            [self.cutter_x, self.cutter_y, self.cutter_z],
            [self.plane_x, self.plane_y, self.plane_z],
            [(1, 0, 0), (0, 1, 0), (0, 0, 1)]
        ):
            plane.SetNormal(normal)
            cutter.SetInputData(self.polydata)
            cutter.SetCutFunction(plane)
        
        self.intersection_sphere.SetRadius(self.polydata.GetLength() * 0.01)
        
        for actor in [self.main_actor, self.slice_actor_x, self.slice_actor_y, self.slice_actor_z, self.intersection_actor]:
            self.renderer_3d.AddActor(actor)
        
        self.orientation_widget.SetEnabled(1)
        self.orientation_widget.InteractiveOff()
        
        for slider in [self.slider_x, self.slider_y, self.slider_z]:
            slider.setRange(0, 1000)
            slider.setValue(500)
        
        self.controls_group.setEnabled(True)
        self.update_slices()
        self.renderer_3d.ResetCamera()
        self.vtk_widget_3d.GetRenderWindow().Render()

    def update_slices(self):
        if self.polydata is None: return

        x_range, y_range, z_range = self.bounds[1]-self.bounds[0], self.bounds[3]-self.bounds[2], self.bounds[5]-self.bounds[4]
        x = self.bounds[0] + x_range * self.slider_x.value() / 1000.0
        y = a = self.bounds[2] + y_range * self.slider_y.value() / 1000.0
        z = self.bounds[4] + z_range * self.slider_z.value() / 1000.0
        
        self.label_x.setText(f"{x:.2f}")
        self.label_y.setText(f"{y:.2f}")
        self.label_z.setText(f"{z:.2f}")
        
        self.plane_x.SetOrigin(x, y, z)
        self.plane_y.SetOrigin(x, y, z)
        self.plane_z.SetOrigin(x, y, z)
        
        self.intersection_actor.SetPosition(x, y, z)

        for cutter in [self.cutter_x, self.cutter_y, self.cutter_z]:
            cutter.Update()

        self.vtk_widget_3d.GetRenderWindow().Render()
        
        self.slice_widget_yz.update_data(self.cutter_x.GetOutput())
        self.slice_widget_xz.update_data(self.cutter_y.GetOutput())
        self.slice_widget_xy.update_data(self.cutter_z.GetOutput())

    def closeEvent(self, event):
        """
        重写关闭事件，确保在退出前正确释放VTK资源。
        """
        # --- 这是解决关闭报错的关键 ---
        # 显式地告诉每个VTK交互器窗口去终止和清理资源
        if hasattr(self, 'vtk_widget_3d') and self.vtk_widget_3d:
            self.vtk_widget_3d.Finalize()

        if hasattr(self, 'slice_widget_xy') and self.slice_widget_xy:
            self.slice_widget_xy.vtk_widget.Finalize()

        if hasattr(self, 'slice_widget_xz') and self.slice_widget_xz:
            self.slice_widget_xz.vtk_widget.Finalize()

        if hasattr(self, 'slice_widget_yz') and self.slice_widget_yz:
            self.slice_widget_yz.vtk_widget.Finalize()
        # --- 关键代码结束 ---

        # 调用父类的closeEvent，让窗口正常关闭
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VTPViewer()
    window.show()
    sys.exit(app.exec_())