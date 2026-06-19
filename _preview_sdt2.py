import sys
from PyQt5 import QtWidgets, uic
app = QtWidgets.QApplication(sys.argv)
def render(uifile, md, outfile, w0, h0):
    w = uic.loadUi(uifile)
    w.comboBox_Landuse.addItem("TSM_landuse_2024")
    if hasattr(w,"comboBox_TeleworkShare"):
        w.comboBox_TeleworkShare.addItems(["7%","10%","15%","20%","25%"]); w.comboBox_TeleworkShare.setCurrentText("15%")
    with open(md,encoding="utf-8") as f: w.textBrowser.setMarkdown(f.read())
    w.resize(w0,h0); w.show(); app.processEvents(); w.grab().save(outfile); print("saved",outfile)
render("ui/SDT_resident.ui","docs/SDT_RESIDENT.md","_sdt_res_help.png",760,420)
render("ui/SDT_visitor.ui","docs/SDT_VISITOR.md","_sdt_vis_help.png",760,420)
