import sys
from PyQt5 import QtWidgets, uic
app = QtWidgets.QApplication(sys.argv)
def render(fmt, outfile):
    w = uic.loadUi("ui/Skimmy.ui")
    for n in ["comboBox_Linklayer","comboBox_Nodelayer"]:
        getattr(w, n).addItem("Select a layer")
    w.comboBox_Format.addItems(["omx","csv","tiled_omx"]); w.comboBox_Format.setCurrentText(fmt)
    w.tiledGB.setEnabled(fmt=="tiled_omx")
    w.lineEdit_Threads.setText("100")
    w.resize(470, 620); w.show(); app.processEvents()
    w.grab().save(outfile); print("saved", outfile)
render("omx","_skimmy_omx.png")
render("tiled_omx","_skimmy_tiled.png")
