import sys
from PyQt5 import QtWidgets, uic
app = QtWidgets.QApplication(sys.argv)
w = uic.loadUi("ui/trip_list2table.ui")
w.comboBox_Year.addItems(["2024"]); w.comboBox_Feedback.addItems(["1"]); w.comboBox_Resolution.addItems(["30","15"])
w.textBrowser_Help.setHtml("<h2>agentPlans &#8211; trip list / trip table builder</h2><p>...</p>")
w.resize(1000,560); w.show(); app.processEvents(); w.grab().save("_tt_preview.png"); print("saved")
