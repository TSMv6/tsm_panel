import sys
from PyQt5 import QtWidgets, uic
app = QtWidgets.QApplication(sys.argv)
w = uic.loadUi("ui/LDT_Res.ui")
w.comboBox_LU.addItem("TSM_landuse_2024")
with open("docs/LDT_RES.md",encoding="utf-8") as fh: w.textBrowser.setMarkdown(fh.read())
w.resize(900, 470); w.show(); app.processEvents(); w.grab().save("_ldtres_preview.png"); print("saved")
