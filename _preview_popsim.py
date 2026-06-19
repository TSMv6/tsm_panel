import sys
from PyQt5 import QtWidgets, uic
app = QtWidgets.QApplication(sys.argv)
w = uic.loadUi("ui/PopulationSIM.ui")
for n in ["comboBox_LUlayer","comboBox_RefLUlayer"]:
    getattr(w, n).addItem("Select a layer")
w.resize(700, 430); w.show(); app.processEvents()
w.grab().save("_popsim_preview.png"); print("saved")
