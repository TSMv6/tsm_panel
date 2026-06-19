import sys
from PyQt5 import QtWidgets, uic
app = QtWidgets.QApplication(sys.argv)
def render(run_all, outfile):
    w = uic.loadUi("ui/SDT_resident.ui")
    w.comboBox_Landuse.addItem("TSM_landuse_2024")
    w.comboBox_TeleworkShare.addItems(["7%","10%","15%","20%","25%"]); w.comboBox_TeleworkShare.setCurrentText("15%")
    w.cb_runResident.setChecked(True)
    w.cb_runAllPhases.setChecked(run_all)
    phases=[w.cb_wfh,w.cb_autoOwn,w.cb_vehType,w.cb_mandatory,w.cb_tour,w.cb_stop,w.cb_trip]
    for cb in phases: cb.setEnabled(not run_all)
    w.resize(660, 360); w.show(); app.processEvents()
    w.grab().save(outfile); print("saved", outfile)
render(True, "_sdt_runall.png")
render(False, "_sdt_phases.png")
