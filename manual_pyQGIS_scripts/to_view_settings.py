import json
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QApplication
from PyQt5.QtCore import Qt

class JsonAttributeTable(QWidget):
    def __init__(self, json_path):
        super().__init__()
        self.setWindowTitle("Key-Value Table (Editable Values)")
        self.resize(500, 400)

        self.layout = QVBoxLayout()
        self.table = QTableWidget()
        self.layout.addWidget(self.table)
        self.setLayout(self.layout)

        self.load_json(json_path)

    def load_json(self, json_path):
        with open(json_path, 'r') as f:
            data = json.load(f)

        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Key", "Value"])
        self.table.setRowCount(len(data))

        for row, (key, value) in enumerate(data.items()):
            key_item = QTableWidgetItem(str(key))
            key_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)  # non-editable
            self.table.setItem(row, 0, key_item)

            value_item = QTableWidgetItem(str(value))
            value_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
            self.table.setItem(row, 1, value_item)

        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()

# Run within QGIS Python Console:
# Substitute the path below with the actual path to your JSON file
_window_ref = None

def show_table():
    global _window_ref
    json_path = "C:\\Projects\\Wekiwa_2025\\Subarea_Extraction_Settings.json"
    _window_ref = JsonAttributeTable(json_path)
    _window_ref.show()

# Uncomment the line below to test directly in QGIS Python Console
show_table()
