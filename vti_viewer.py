import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QFileDialog, QPushButton,
                             QVBoxLayout, QWidget, QSlider, QLabel, QGroupBox,
                             QFormLayout, QHBoxLayout, QMessageBox, QGridLayout)
from PyQt5.QtCore import Qt
import vtk
from vtk.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

# ==============================================================================
# 自定义交互方式，用于在2D视图中拾取点
# ==============================================================================
class ContourInteractorStyle(vtk.vtkInteractorStyleImage):
    def __init__(self, parent_viewer=None):
        super().__init__()
        self.parent_viewer = parent_viewer
        print("Interactor style set for ContourInteractorStyle")

        # 用 AddObserver 绑定左键事件，保证事件捕获
        self.AddObserver("LeftButtonPressEvent", self.on_left_button_press)

    def on_left_button_press(self, obj, event):
        if not self.parent_viewer or not self.parent_viewer.is_drawing:
            # 事件传递给基类默认处理
            self.OnLeftButtonDown()
            return

        click_pos = self.GetInteractor().GetEventPosition()
        renderer = self.GetDefaultRenderer()
        picker = vtk.vtkPropPicker()
        picker.Pick(click_pos[0], click_pos[1], 0, renderer)
        world_pos = picker.GetPickPosition()
        print(f"Picked point at {world_pos}")
        self.parent_viewer.add_contour_point(world_pos)

        self.OnLeftButtonDown()  # 让基类继续处理事件


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
            self.interactor_style.SetDefaultRenderer(self.renderer)  # 关键补充
        else: # Coronal, Sagittal
            self.interactor_style = vtk.vtkInteractorStyleImage()
        
        self.vtk_widget.GetRenderWindow().GetInteractor().SetInteractorStyle(self.interactor_style)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.vtk_widget)

    def set_input_data(self, image_data):
        """设置输入的体数据。"""
        self.reslice.SetInputData(image_data)
            
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
        
        self.renderer.ResetCamera()
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

        # --- 顶部控制区 ---
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

        # --- 视图区 (2x2 网格布局) ---
        views_layout = QGridLayout()
        self.slice_widget_axial = ImageSliceViewerWidget('z', parent_viewer=self) # 左上
        self.slice_widget_coronal = ImageSliceViewerWidget('y', parent_viewer=self) # 右上
        self.slice_widget_sagittal = ImageSliceViewerWidget('x', parent_viewer=self) # 左下
        
        # 3D 视图 (右下)
        self.vtk_widget_3d = QVTKRenderWindowInteractor()
        self.renderer_3d = vtk.vtkRenderer()
        self.renderer_3d.SetBackground(0.2, 0.3, 0.4)
        self.vtk_widget_3d.GetRenderWindow().AddRenderer(self.renderer_3d)
        self.interactor_3d = self.vtk_widget_3d.GetRenderWindow().GetInteractor()
        self.interactor_3d.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())

        views_layout.addWidget(self.slice_widget_axial, 0, 0)
        views_layout.addWidget(self.slice_widget_coronal, 0, 1)
        views_layout.addWidget(self.slice_widget_sagittal, 1, 0)
        views_layout.addWidget(self.vtk_widget_3d, 1, 1)
        self.main_layout.addLayout(views_layout)

        # --- 3D视图中的切面对象 ---
        self.image_slice_3d_axial = vtk.vtkImageSlice()
        self.image_slice_3d_coronal = vtk.vtkImageSlice()
        self.image_slice_3d_sagittal = vtk.vtkImageSlice()
        
        # --- 底部滑块控制区 ---
        self.setup_controls_ui()
        self.main_layout.addWidget(self.controls_group)

        self.slice_widget_axial.vtk_widget.GetRenderWindow().GetInteractor().Initialize()
        self.vtk_widget_3d.GetRenderWindow().GetInteractor().Initialize()

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
        """根据滑块的值更新所有视图。"""
        if not self.image_data: return
        
        axial_slice = self.slider_axial.value()
        coronal_slice = self.slider_coronal.value()
        sagittal_slice = self.slider_sagittal.value()

        self.slice_widget_axial.set_slice(axial_slice)
        self.slice_widget_coronal.set_slice(coronal_slice)
        self.slice_widget_sagittal.set_slice(sagittal_slice)
        
        # 更新3D视图中的切面位置
        self.image_slice_3d_axial.GetMapper().SetSliceNumber(axial_slice)
        self.image_slice_3d_coronal.GetMapper().SetSliceNumber(coronal_slice)
        self.image_slice_3d_sagittal.GetMapper().SetSliceNumber(sagittal_slice)
        
        self.renderer_3d.ResetCamera()
        self.vtk_widget_3d.GetRenderWindow().Render()

    def toggle_drawing(self, checked):
        """切换绘制模式。"""
        self.is_drawing = checked
        if self.is_drawing:
            self.draw_btn.setText("Finish Drawing")
            self.current_contour_points = vtk.vtkPoints()
        
            # 新建一个独立的polydata管理点和拓扑
            self.polydata_2d = vtk.vtkPolyData()
            self.polydata_2d.SetPoints(self.current_contour_points)
            self.polydata_2d.SetLines(vtk.vtkCellArray())
            self.polydata_2d.SetPolys(vtk.vtkCellArray())

            # 2D视图mapper和actor
            mapper2d = vtk.vtkPolyDataMapper()
            mapper2d.SetInputData(self.polydata_2d)
            self.current_contour_actor_2d = vtk.vtkActor()
            self.current_contour_actor_2d.SetMapper(mapper2d)
            self.current_contour_actor_2d.GetProperty().SetColor(1, 1, 0)  # 黄色
            self.current_contour_actor_2d.GetProperty().SetLineWidth(2)
            self.current_contour_actor_2d.PickableOff()
            self.slice_widget_axial.renderer.AddActor(self.current_contour_actor_2d)

            # 3D视图用独立polydata，初始拷贝一份2D数据（空）
            self.polydata_3d = vtk.vtkPolyData()
            self.polydata_3d.DeepCopy(self.polydata_2d)

            mapper3d = vtk.vtkPolyDataMapper()
            mapper3d.SetInputData(self.polydata_3d)
            self.current_contour_actor_3d = vtk.vtkActor()
            self.current_contour_actor_3d.SetMapper(mapper3d)
            self.current_contour_actor_3d.GetProperty().SetColor(1, 1, 0)  # 黄色
            self.current_contour_actor_3d.GetProperty().SetLineWidth(2)
            self.renderer_3d.AddActor(self.current_contour_actor_3d)

        else:
            self.draw_btn.setText("Start Drawing Contour")
            if self.current_contour_points and self.current_contour_points.GetNumberOfPoints() > 0:
                self.contours.append(self.current_contour_points)
            self.current_contour_points = None
            # 保留已完成的轮廓显示，不清空actor

    def add_contour_point(self, pos):
        """向当前轮廓添加一个点，并实时更新闭合轮廓。"""
        if not self.is_drawing or not self.current_contour_points:
            return
        
        self.current_contour_points.InsertNextPoint(pos)
        
        polydata2d = self.polydata_2d
        num_points = self.current_contour_points.GetNumberOfPoints()
        
        if num_points < 2:
            # 只有一个点，不画任何线或面
            polydata2d.SetLines(vtk.vtkCellArray())
            polydata2d.SetPolys(vtk.vtkCellArray())
        elif num_points == 2:
            # 两个点，画线段
            line = vtk.vtkLine()
            line.GetPointIds().SetId(0, 0)
            line.GetPointIds().SetId(1, 1)
            lines = vtk.vtkCellArray()
            lines.InsertNextCell(line)
            polydata2d.SetLines(lines)
            polydata2d.SetPolys(vtk.vtkCellArray())
        else:
            # 3个及以上点，画闭合多边形
            polygon = vtk.vtkPolygon()
            polygon.GetPointIds().SetNumberOfIds(num_points)
            for i in range(num_points):
                polygon.GetPointIds().SetId(i, i)
            polys = vtk.vtkCellArray()
            polys.InsertNextCell(polygon)
            polydata2d.SetPolys(polys)
            polydata2d.SetLines(vtk.vtkCellArray())

        polydata2d.Modified()

        # 3D数据用DeepCopy同步2D数据
        self.polydata_3d.DeepCopy(polydata2d)
        self.polydata_3d.Modified()

        # 触发渲染刷新
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

