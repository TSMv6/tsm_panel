import sys
from PyQt5 import QtWidgets, uic
app = QtWidgets.QApplication(sys.argv)
w = uic.loadUi("ui/PopulationSIM.ui")
for n in ["comboBox_LUlayer","comboBox_RefLUlayer"]:
    getattr(w, n).addItem("Select a layer")
with open("docs/POPULATIONSIM.md",encoding="utf-8") as f: w.textBrowser.setMarkdown(f.read())
w.resize(760, 430); w.show(); app.processEvents(); w.grab().save("_popsim_help.png"); print("saved")
