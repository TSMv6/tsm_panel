import sys
from PyQt5 import QtWidgets, uic
app = QtWidgets.QApplication(sys.argv)
w = uic.loadUi("ui/General_Configuration.ui")
w.lineEdit_ModelPath.setText("C:/TSM_NextGen_v6")
w.lineEdit_PluginsPath.setText("C:/Users/kn815vs/AppData/Roaming/QGIS/QGIS3/profiles/default/python/plugins/tsm_panel")
w.lineEdit_NumProcessors.setText("100")
w.resize(660, 220); w.show(); app.processEvents(); w.grab().save("_gc_preview.png"); print("saved")
