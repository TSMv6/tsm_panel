import os, webbrowser

title = iface.mainWindow().windowTitle()
new_title = title.replace(title, 'TSM')
iface.mainWindow().setWindowTitle(new_title)

icon = 'TPK-mainline-logo.png'
dir = 'C:/Users/kn815vs/AppData/Roaming/QGIS/QGIS3/profiles/default/python/plugins/tsm_panel/icons'
icon_path = os.path.join(dir, icon)
iface.mainWindow().setWindowIcon(QIcon(icon_path))


def open_website():
    webbrowser.open('https://rawcdn.githack.com/4Step/NextGen_StoryTelling/81080ccbe072f7c2c4f408c1236f94fd97ed5d52/index.html')

website_action = QAction('TSM Overview')
website_action.triggered.connect(open_website)
iface.helpMenu().addSeparator()
iface.helpMenu().addAction(website_action)

def open_website2():
    webbrowser.open('https://chatgpt.com/g/g-p-67db57d314d08191aab1ac2ecdd0e257-pyqgis/project')

website_action2 = QAction('TSM AI Chat')
website_action2.triggered.connect(open_website2)
iface.helpMenu().addAction(website_action2)

