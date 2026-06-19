def classFactory(iface):
    from .tsm_panel_plugin import TsmPanelPlugin
    return TsmPanelPlugin(iface)
