import sys
from PyQt5 import QtWidgets, uic
app = QtWidgets.QApplication(sys.argv)
w = uic.loadUi("ui/hydra.ui")
for n in ["comboBox_LinkLayer","comboBox_NodeLayer"]: getattr(w,n).addItem("Select a layer")
w.comboBox_Macro.setCurrentText("LTM + Meso + Signals"); w.lineEdit_MesoFtypes.setText("11,91,93,94")
w.checkBox_Micro.setChecked(True)
for n in ["lineEdit_MicroFtypes","comboBox_Coupling","comboBox_MicroChoice"]: getattr(w,n).setEnabled(True)
w.checkBox_AgentPlans.setChecked(True); w.checkBox_DuckDB.setChecked(True)
with open("docs/HYDRA.md",encoding="utf-8") as f: w.textBrowser.setMarkdown(f.read())
w.resize(960,600); w.show(); app.processEvents(); w.grab().save("_hydra_preview.png"); print("saved")
