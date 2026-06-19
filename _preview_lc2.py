import sys
from PyQt5 import QtWidgets, uic
app = QtWidgets.QApplication(sys.argv)
def render(version, outfile):
    w = uic.loadUi("ui/tsm_link_consolidator.ui")
    for n in ["lineLayerCombo","nodeLayerCombo","lineLayerCombo_2","lineLayerCombo_3"]:
        getattr(w,n).addItem("Select a layer")
    w.comboBox_Year.addItems(["2024"]); w.comboBox_Year.setCurrentText("2024")
    w.networkVersion.setCurrentText(version)
    is_v6 = version=="TSMv6"
    for n in ["lineLayerCombo_2","label_Input_Linelayer_2","lineLayerCombo_3","label_Input_Linelayer_3"]:
        getattr(w,n).setEnabled(is_v6)
    if not is_v6: w.modelResolution.setCurrentText("TSM")
    w.modelResolution.setEnabled(is_v6)
    with open("docs/LINK_CONSOLIDATION.md",encoding="utf-8") as f: w.textBrowser.setMarkdown(f.read())
    w.resize(1100,640); w.show(); app.processEvents(); w.grab().save(outfile); print("saved",outfile)
render("TSMv6","_lc_v6.png"); render("TSMv5","_lc_v5.png")
