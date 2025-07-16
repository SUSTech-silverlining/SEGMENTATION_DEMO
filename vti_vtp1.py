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
# 自定义交互方式，用于在2D视图中拾取点
# ==============================================================================
class ContourInteractorStyle(vtk.vtkInteractorStyleImage):
    def __init__(self, parent_viewer=None):
        super().__init__()
        self.parent_viewer = parent_viewer

        # 用 AddObserver 绑定左键事件，保证事件捕获
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

        # 强制Z值为当前axial切片的物理坐标
        if self.parent_viewer and hasattr(self.parent_viewer, "slider_axial"):
            axial_slice = self.parent_viewer.slider_axial.value()
            image_data = self.parent_viewer.image_data
            if image_data:
                origin = image_data.GetOrigin()
                spacing = image_data.GetSpacing()
                world_pos[2] = origin[2] + axial_slice * spacing[2]

        print(f"Picked point at {world_pos}")
        self.parent_viewer.add_contour_point(tuple(world_pos))
        self.OnLeftButtonDown()  # 让基类继续处理事件

# ==============================================================================
# 自定义交互方式，用于在2D视图中平移
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
            factor = 0.5  # 平移灵敏度
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
# 用于显示2D图像切片的控件 (已重构)
# ==============================================================================
class ImageSliceViewerWidget(QWidget):
    """一个用于显示VTI图像切片的QWidget控件。"""
    def __init__(self, view_axis, parent_viewer=None):
        super().__init__()
        self.view_axis = view_axis

        self.vtk_widget = QVTKRenderWindowInteractor(self)
        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(0.1, 0.1, 0.1)
        self.vtk_widget.GetRenderWindow().AddRenderer(self.renderer)

        # 使用更健壮的 vtkImageReslice 来提取切片
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
        """设置输入的体数据。"""
        self.reslice.SetInputData(image_data)
        self.camera_reset_done = False
            
    def set_color_level(self, level):
        self.image_slice.GetProperty().SetColorLevel(level)

    def set_color_window(self, window):
        self.image_slice.GetProperty().SetColorWindow(window)

    def set_slice(self, slice_index):
        """根据切片索引更新切片位置。"""
        if not self.reslice.GetInput(): return
        
        image_data = self.reslice.GetInput()
        origin = image_data.GetOrigin()
        spacing = image_data.GetSpacing()
        
        # 通过设置Reslice的变换矩阵来定义切面
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
# 主窗口类
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

        # === 顶部控制区 ===
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

        # === 新增 Calculate 功能 ===
        self.calc_btn = QPushButton("Calculate")
        self.calc_btn.clicked.connect(self.on_calculate)
        top_controls_layout.addWidget(self.calc_btn)

        # === 新增vti文件on/off功能 ===
        self.vti_toggle_btn = QPushButton("Hide VTI")
        self.vti_toggle_btn.setCheckable(True)
        self.vti_toggle_btn.toggled.connect(self.toggle_vti_in_3d)
        top_controls_layout.addWidget(self.vti_toggle_btn)



        # === 视图区 (2x2 网格) ===
        views_layout = QGridLayout()

        # 2D Axial 视图（左上）
        self.slice_widget_axial = ImageSliceViewerWidget('z', parent_viewer=self)
        axial_group = QWidget()
        axial_layout = QVBoxLayout(axial_group)
        axial_layout.setContentsMargins(0, 0, 0, 0)
        axial_label = QLabel("Axial (Z)")
        axial_label.setAlignment(Qt.AlignHCenter)
        axial_layout.addWidget(axial_label)
        axial_layout.addWidget(self.slice_widget_axial)

        # 2D Coronal 视图（右上）
        self.slice_widget_coronal = ImageSliceViewerWidget('y', parent_viewer=self)
        coronal_group = QWidget()
        coronal_layout = QVBoxLayout(coronal_group)
        coronal_layout.setContentsMargins(0, 0, 0, 0)
        coronal_label = QLabel("Coronal (Y)")
        coronal_label.setAlignment(Qt.AlignHCenter)
        coronal_layout.addWidget(coronal_label)
        coronal_layout.addWidget(self.slice_widget_coronal)

        # 2D Sagittal 视图（左下）
        self.slice_widget_sagittal = ImageSliceViewerWidget('x', parent_viewer=self)
        sagittal_group = QWidget()
        sagittal_layout = QVBoxLayout(sagittal_group)
        sagittal_layout.setContentsMargins(0, 0, 0, 0)
        sagittal_label = QLabel("Sagittal (X)")
        sagittal_label.setAlignment(Qt.AlignHCenter)
        sagittal_layout.addWidget(sagittal_label)
        sagittal_layout.addWidget(self.slice_widget_sagittal)

        # 3D视图（右下）
        self.vtk_widget_3d = QVTKRenderWindowInteractor()
        self.renderer_3d = vtk.vtkRenderer()
        self.renderer_3d.SetBackground(0.2, 0.3, 0.4)
        self.vtk_widget_3d.GetRenderWindow().AddRenderer(self.renderer_3d)
        self.interactor_3d = self.vtk_widget_3d.GetRenderWindow().GetInteractor()
        self.interactor_3d.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())

        # === 添加小坐标轴到3D窗口 ===
        axes_actor = vtk.vtkAxesActor()
        self.orientation_marker = vtk.vtkOrientationMarkerWidget()
        self.orientation_marker.SetOrientationMarker(axes_actor)
        self.orientation_marker.SetInteractor(self.interactor_3d)
        self.orientation_marker.SetViewport(0.8, 0.0, 1.0, 0.2)  # 右下角 20% 区域
        self.orientation_marker.SetEnabled(1)
        self.orientation_marker.InteractiveOff()

        # === 将各视图组装到网格 ===
        views_layout.addWidget(axial_group,    0, 0)
        views_layout.addWidget(coronal_group,  0, 1)
        views_layout.addWidget(sagittal_group, 1, 0)
        views_layout.addWidget(self.vtk_widget_3d, 1, 1)
        self.main_layout.addLayout(views_layout)

        # 3D视图中的切面对象（你原有代码保留）
        self.image_slice_3d_axial = vtk.vtkImageSlice()
        self.image_slice_3d_coronal = vtk.vtkImageSlice()
        self.image_slice_3d_sagittal = vtk.vtkImageSlice()

        # === 底部滑块控制区 ===
        self.setup_controls_ui()
        self.main_layout.addWidget(self.controls_group)

        # 初始化交互器
        self.slice_widget_axial.vtk_widget.GetRenderWindow().GetInteractor().Initialize()
        self.vtk_widget_3d.GetRenderWindow().GetInteractor().Initialize()

        # 保存每个切片的contour对象
        self.axial_contours_per_slice = {}  # key: slice_index, value: dict with keys: points, actor2d, actor3d, etc.
        self.current_axial_slice = None     # 当前显示的axial切片

        # === 预先存好后期要用的vtp文件 ===
        self.vtp_file_list = [
            "D:/HuaweiMoveData/Users/lyxx01/Desktop/ISURE/segmentation_demo/vtp/ensemble_nc1_moved.vtp",
            "D:/HuaweiMoveData/Users/lyxx01/Desktop/ISURE/segmentation_demo/vtp/ensemble_nc2_moved.vtp",
            "D:/HuaweiMoveData/Users/lyxx01/Desktop/ISURE/segmentation_demo/vtp/ensemble_nc3_moved.vtp",
            "D:/HuaweiMoveData/Users/lyxx01/Desktop/ISURE/segmentation_demo/vtp/ensemble_nc4_moved.vtp"
        ]
        self.current_vtp_actor = None
        self.vtp_file_index = 0  # 用于控制当前步骤显示哪个vtp




    def setup_controls_ui(self):
        """创建滑块控制面板。"""
        self.controls_group = QGroupBox("Slice Controls")
        layout = QFormLayout(self.controls_group)
        self.slider_axial, self.label_axial = QSlider(Qt.Horizontal), QLabel("N/A")
        self.slider_coronal, self.label_coronal = QSlider(Qt.Horizontal), QLabel("N/A")
        self.slider_sagittal, self.label_sagittal = QSlider(Qt.Horizontal), QLabel("N/A")
        self.slider_axial.valueChanged.connect(self.update_slices)
        self.slider_coronal.valueChanged.connect(self.update_slices)
        self.slider_sagittal.valueChanged.connect(self.update_slices)
        layout.addRow("Axial (Z-axis):", self.slider_axial)
        layout.addRow("Coronal (Y-axis):", self.slider_coronal)
        layout.addRow("Sagittal (X-axis):", self.slider_sagittal)
        self.controls_group.setEnabled(False)

    def open_vti(self):
        """打开VTI文件。"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select VTI File", "", "VTI Files (*.vti)")
        if file_path:
            self.load_vti(file_path)

    def load_vti(self, file_path):
        """加载VTI文件并初始化所有视图。"""
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

        # --- 初始化2D视图 ---
        for widget in [self.slice_widget_axial, self.slice_widget_coronal, self.slice_widget_sagittal]:
            widget.set_input_data(self.image_data)
            widget.set_color_window(window)
            widget.set_color_level(level)
        
        # --- 初始化3D视图中的切面 ---
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

        # --- 初始化滑块 ---
        extent = self.image_data.GetExtent()
        self.slider_sagittal.setRange(extent[0], extent[1])
        self.slider_coronal.setRange(extent[2], extent[3])
        self.slider_axial.setRange(extent[4], extent[5])
        self.slider_sagittal.setValue((extent[0] + extent[1]) // 2)
        self.slider_coronal.setValue((extent[2] + extent[3]) // 2)
        self.slider_axial.setValue((extent[4] + extent[5]) // 2)
        
        self.controls_group.setEnabled(True)
        self.update_slices()

    def update_slices(self):
        if not self.image_data:
            return

        prev_axial = getattr(self, "current_axial_slice", None)
        axial_slice = self.slider_axial.value()
        coronal_slice = self.slider_coronal.value()
        sagittal_slice = self.slider_sagittal.value()
        self.current_axial_slice = axial_slice

        # --------- 1. 2D窗口只隐藏上一个slice的contour和cube ---------
        if prev_axial is not None:
            contour_list = self.axial_contours_per_slice.get(prev_axial, [])
            for contour_info in contour_list:
                if contour_info.get('actor2d'):
                    self.slice_widget_axial.renderer.RemoveActor(contour_info['actor2d'])
                for cube in contour_info.get('cube_actors', []):
                    self.slice_widget_axial.renderer.RemoveActor(cube)
        # 3D窗口什么都不做（不要remove）

        # --------- 2. 切片渲染更新 ---------
        self.slice_widget_axial.set_slice(axial_slice)
        self.slice_widget_coronal.set_slice(coronal_slice)
        self.slice_widget_sagittal.set_slice(sagittal_slice)

        # --------- 3. 2D窗口只add当前slice的contour和cube ---------
        contour_list = self.axial_contours_per_slice.get(axial_slice, [])
        for contour_info in contour_list:
            if contour_info.get('actor2d'):
                self.slice_widget_axial.renderer.AddActor(contour_info['actor2d'])
            for cube in contour_info.get('cube_actors', []):
                self.slice_widget_axial.renderer.AddActor(cube)
        # 3D窗口什么都不做（actor已经永久add过了）

        # --------- 4. 其它视图和label ---------
        self.label_axial.setText(str(axial_slice))
        self.label_coronal.setText(str(coronal_slice))
        self.label_sagittal.setText(str(sagittal_slice))

        self.image_slice_3d_axial.GetMapper().SetSliceNumber(axial_slice)
        self.image_slice_3d_coronal.GetMapper().SetSliceNumber(coronal_slice)
        self.image_slice_3d_sagittal.GetMapper().SetSliceNumber(sagittal_slice)

        self.renderer_3d.ResetCameraClippingRange()
        self.slice_widget_axial.vtk_widget.GetRenderWindow().Render()
        self.slice_widget_coronal.vtk_widget.GetRenderWindow().Render()
        self.slice_widget_sagittal.vtk_widget.GetRenderWindow().Render()
        self.vtk_widget_3d.GetRenderWindow().Render()




    def toggle_drawing(self, checked):
        """切换绘制模式。"""
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
            self.current_contour_cubes = []  # <--- 新增：用于存储当前轮廓的小方块actors

            self.polydata_2d = vtk.vtkPolyData()
            self.polydata_2d.SetPoints(self.current_contour_points)
            self.polydata_2d.SetLines(vtk.vtkCellArray())
            self.polydata_2d.SetPolys(vtk.vtkCellArray())

            mapper2d = vtk.vtkPolyDataMapper()
            mapper2d.SetInputData(self.polydata_2d)
            self.current_contour_actor_2d = vtk.vtkActor()
            self.current_contour_actor_2d.SetMapper(mapper2d)
            self.current_contour_actor_2d.GetProperty().SetColor(1, 1, 0)  # 黄色
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
                # --------- 多contour存储 ----------
                if self.current_axial_slice not in self.axial_contours_per_slice:
                    self.axial_contours_per_slice[self.current_axial_slice] = []
                self.axial_contours_per_slice[self.current_axial_slice].append({
                    'points': self.current_contour_points,
                    'actor2d': self.current_contour_actor_2d,
                    'actor3d': self.current_contour_actor_3d,
                    'cube_actors': self.current_contour_cubes,  # <--- 新增
                })
            self.current_contour_points = None
            self.current_contour_actor_2d = None
            self.current_contour_actor_3d = None
            self.current_contour_cubes = []  # <--- 新增




    def add_contour_point(self, pos):
        if not self.is_drawing or not self.current_contour_points:
            return
        spacing = self.image_data.GetSpacing() if self.image_data else [1, 1, 1]
        origin = self.image_data.GetOrigin() if self.image_data else [0, 0, 0]
        current_slice = self.slider_axial.value()
        slice_z = origin[2] + current_slice * spacing[2]
        # 2D窗口要浮高
        contour_z_2d = slice_z + spacing[2] * 20

        # === 1. 2D窗口的点，z浮高
        adjusted_pos_2d = (pos[0], pos[1], contour_z_2d)
        self.current_contour_points.InsertNextPoint(adjusted_pos_2d)
        num_points = self.current_contour_points.GetNumberOfPoints()

        # 2D线条
        if num_points < 2:
            self.polydata_2d.SetPoints(self.current_contour_points)
            self.polydata_2d.SetLines(vtk.vtkCellArray())
            self.polydata_2d.SetPolys(vtk.vtkCellArray())
        else:
            spline = vtk.vtkParametricSpline()
            points_for_spline = vtk.vtkPoints()
            for i in range(num_points):
                points_for_spline.InsertNextPoint(self.current_contour_points.GetPoint(i))
            points_for_spline.InsertNextPoint(self.current_contour_points.GetPoint(0))
            spline.SetPoints(points_for_spline)
            splineSource = vtk.vtkParametricFunctionSource()
            splineSource.SetParametricFunction(spline)
            splineSource.SetUResolution(200)
            splineSource.Update()
            self.polydata_2d.ShallowCopy(splineSource.GetOutput())
        self.polydata_2d.Modified()

        # 2D cube
        cube = vtk.vtkCubeSource()
        size = 3
        cube.SetCenter(*adjusted_pos_2d)
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

        # 2D线actor
        if self.current_contour_actor_2d:
            self.current_contour_actor_2d.GetProperty().SetColor(1, 1, 0)
            self.current_contour_actor_2d.GetProperty().SetLineWidth(3)
            self.current_contour_actor_2d.GetProperty().SetOpacity(1.0)
            self.slice_widget_axial.renderer.AddActor(self.current_contour_actor_2d)

        # === 2. 3D窗口的线，z严格用slice_z（即真实物理z），不要浮高 ===
        # 直接重新生成polydata，z为slice_z
        num_points_3d = num_points
        points_3d = vtk.vtkPoints()
        for i in range(num_points_3d):
            pt = self.current_contour_points.GetPoint(i)
            pt_3d = (pt[0], pt[1], slice_z)  # 强制用slice物理z
            points_3d.InsertNextPoint(pt_3d)
        # 闭合
        if num_points_3d > 1:
            pt = self.current_contour_points.GetPoint(0)
            pt_3d = (pt[0], pt[1], slice_z)
            points_3d.InsertNextPoint(pt_3d)
        polydata_3d = vtk.vtkPolyData()
        polydata_3d.SetPoints(points_3d)
        if num_points_3d > 1:
            lines = vtk.vtkCellArray()
            n = num_points_3d + 1  # 闭合
            lines.InsertNextCell(n)
            for i in range(n):
                lines.InsertCellPoint(i)
            polydata_3d.SetLines(lines)
        self.polydata_3d.DeepCopy(polydata_3d)
        self.polydata_3d.Modified()

        # 3D线actor已经在renderer_3d中，无需重复add
        self.slice_widget_axial.renderer.ResetCameraClippingRange()
        self.slice_widget_axial.vtk_widget.GetRenderWindow().Render()
        self.vtk_widget_3d.GetRenderWindow().Render()









    def clear_current_contour(self):
        """清除当前正在绘制的轮廓。"""
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
        # 1. 检查是否已完成轮廓绘制
        # 只要当前切片有至少一个contour即可
        contour_list = self.axial_contours_per_slice.get(self.current_axial_slice, [])
        if not contour_list:
            QMessageBox.warning(self, "Warning", "请先在当前切片画好并完成一个轮廓，然后再点击 Calculate！")
            return


        # 2. 显示进度条（假装计算5s）
        self.progress = QProgressDialog("正在计算...", None, 0, 100, self)
        self.progress.setWindowTitle("Processing")
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setAutoClose(True)
        self.progress.setCancelButton(None)
        self.progress.show()

        # 用 QTimer 假装进度
        self._calc_step = 0
        def advance_progress():
            self._calc_step += 1
            self.progress.setValue(self._calc_step)
            if self._calc_step >= 100:
                self.progress.close()
                QTimer.singleShot(100, self.load_vtp_after_calc)
            else:
                QTimer.singleShot(50, advance_progress)
        advance_progress()

    def load_vtp_after_calc(self):
        # 1. 自动读取当前索引的VTP文件
        if self.vtp_file_index >= len(self.vtp_file_list):
            QMessageBox.information(self, "Info", "已无更多VTP文件。")
            return
        vtp_path = self.vtp_file_list[self.vtp_file_index]

        reader = vtk.vtkXMLPolyDataReader()
        reader.SetFileName(vtp_path)
        reader.Update()
        polydata = reader.GetOutput()
        if not polydata or polydata.GetNumberOfPoints() == 0:
            QMessageBox.critical(self, "Error", f"VTP文件读取失败: {vtp_path}")
            return

        # 替换上一个VTP显示
        if self.current_vtp_actor is not None:
            self.renderer_3d.RemoveActor(self.current_vtp_actor)

        vtp_mapper = vtk.vtkPolyDataMapper()
        vtp_mapper.SetInputData(polydata)
        vtp_actor = vtk.vtkActor()
        vtp_actor.SetMapper(vtp_mapper)
        vtp_actor.GetProperty().SetColor(0.5, 0.5, 0.5) # 灰色
        vtp_actor.GetProperty().SetOpacity(0.3) # 透明度
        self.renderer_3d.AddActor(vtp_actor)
        self.current_vtp_actor = vtp_actor

        self.vtk_widget_3d.GetRenderWindow().Render()

        # 步进到下一个
        self.vtp_file_index += 1

    def toggle_vti_in_3d(self, checked):
        """
        切换 VTI 显示 on/off。checked=True时隐藏，False时显示
        """
        # 控制三个切面actor的显示与否
        for actor in [self.image_slice_3d_axial, self.image_slice_3d_coronal, self.image_slice_3d_sagittal]:
            actor.SetVisibility(not checked)
        # 更新按钮文字
        if checked:
            self.vti_toggle_btn.setText("Show VTI")
        else:
            self.vti_toggle_btn.setText("Hide VTI")
        self.vtk_widget_3d.GetRenderWindow().Render()





# 禁止vtkOutputWindow弹窗
vtk.vtkObject.GlobalWarningDisplayOff()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VTIViewer()
    window.show()

    # 先初始化交互器和交互风格
    interactor = window.slice_widget_axial.vtk_widget.GetRenderWindow().GetInteractor()
    style = ContourInteractorStyle(parent_viewer=window)
    style.SetDefaultRenderer(window.slice_widget_axial.renderer)
    interactor.SetInteractorStyle(style)

    interactor.Initialize()
    interactor.Start()  # 激活 VTK 事件循环

    sys.exit(app.exec_())