import sys
from PyQt5 import QtWidgets, uic
def render(version, outfile):
    w = uic.loadUi("ui/tsm_link_consolidator.ui")
    for name in ["lineLayerCombo","nodeLayerCombo","lineLayerCombo_2","lineLayerCombo_3"]:
        getattr(w, name).addItem("Select a layer")
    w.comboBox_Year.addItems(["2023","2024","2025","2030","2035","2050"]); w.comboBox_Year.setCurrentText("2024")
    w.modelResolution.setCurrentText("TSM")
    w.networkVersion.setCurrentText(version)
    is_v6 = version == "TSMv6"
    for n in ["lineLayerCombo_2","label_Input_Linelayer_2","lineLayerCombo_3","label_Input_Linelayer_3"]:
        getattr(w, n).setEnabled(is_v6)
    with open("docs/LINK_CONSOLIDATION.md","r",encoding="utf-8") as f: md=f.read()
    w.textBrowser.setMarkdown(md)
    w.resize(1100, 640); w.show(); app.processEvents()
    w.grab().save(outfile); print("saved", outfile)
app = QtWidgets.QApplication(sys.argv)
render("TSMv6","_ui_v6.png")
render("TSMv5","_ui_v5.png")
