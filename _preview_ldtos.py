import sys
from PyQt5 import QtWidgets, uic
from PyQt5.QtWidgets import QTableWidgetItem, QHeaderView
app = QtWidgets.QApplication(sys.argv)
w = uic.loadUi("ui/LDT_OS.ui")
w.comboBox_LU.addItem("TSM_landuse_2024")
t = w.table_ExtStn_Counts
for r,(z,c,f) in enumerate([("","55000","1.0%"),("","30000","1.0%"),("","75000","1.0%")]):
    t.setItem(r,0,QTableWidgetItem(z)); t.setItem(r,1,QTableWidgetItem(c)); t.setItem(r,2,QTableWidgetItem(f))
t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
with open("docs/LDT_OS.md",encoding="utf-8") as fh: w.textBrowser.setMarkdown(fh.read())
w.resize(900, 500); w.show(); app.processEvents(); w.grab().save("_ldtos_preview.png"); print("saved")
