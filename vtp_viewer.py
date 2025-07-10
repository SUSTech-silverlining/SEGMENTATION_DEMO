import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QFileDialog, QPushButton, QVBoxLayout, QWidget
import vtk
from vtk.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

class VTPViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VTP 3D Viewer")
        self.resize(800, 600)

        # 主部件和布局
        self.frame = QWidget()
        self.layout = QVBoxLayout()
        self.frame.setLayout(self.layout)
        self.setCentralWidget(self.frame)

        # 打开文件按钮
        self.open_btn = QPushButton("打开VTP文件")
        self.open_btn.clicked.connect(self.open_vtp)
        self.layout.addWidget(self.open_btn)

        # VTK渲染窗口
        self.vtk_widget = QVTKRenderWindowInteractor(self.frame)
        self.layout.addWidget(self.vtk_widget)

        # VTK渲染器
        self.renderer = vtk.vtkRenderer()
        self.vtk_widget.GetRenderWindow().AddRenderer(self.renderer)
        self.interactor = self.vtk_widget.GetRenderWindow().GetInteractor()

    def open_vtp(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择VTP文件", "", "VTP Files (*.vtp)")
        if file_path:
            self.load_vtp(file_path)

    def load_vtp(self, file_path):
        # 读取VTP文件
        reader = vtk.vtkXMLPolyDataReader()
        reader.SetFileName(file_path)
        reader.Update()

        polydata = reader.GetOutput()

        # 创建映射器和actor
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(polydata)
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)

        # 清空旧的actor
        self.renderer.RemoveAllViewProps()
        self.renderer.AddActor(actor)
        self.renderer.ResetCamera()
        self.vtk_widget.GetRenderWindow().Render()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VTPViewer()
    window.show()
    window.interactor.Initialize()
    sys.exit(app.exec_())