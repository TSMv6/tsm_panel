import os
import struct
import subprocess
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QMessageBox
from qgis.core import QgsProject
from qgis.PyQt import uic  # For loading .ui dynamically
from .tsm_settings import Config
from .model_run import (run_gated_model, begin_run_console, end_run_console,
                        closes_run_console)

from .hydra_ui import Ui_DialogHydra

# Default meso extent: the full limited-access system (freeways 11/12, ramps
# 71-79, toll roads 91-94, express lanes 96-98) runs mesoscopic so flow
# conserves across it.
MESO_LIMITED_ACCESS = "11,12,71,72,75,76,79,91,92,93,94,96,97,98"

# DTA run-mode preset -> (MACRO_MODEL, default Meso FTYPEs, signals on).
#   Node-conserving loaders (NodeDnl): N_out == N_in at every interior node.
#   NodePQ = inflow-capacity receiving, NodeLTM = spatial storage/spillback.
#
# "PointQueue + BPR" is gone. It described a per-link hybrid -- BPR running time
# below capacity, point queue above -- that the engine removed: MACRO_MODEL is
# one global choice and a static VDF is not mixed into the queue. The underlying
# DTA_PointQueue loader is still valid and is now offered on its own.
# Coupling combo rows -> MICRO_COUPLING (labels in hydra.ui, same order).
COUPLINGS = ("oneway", "twoway_frozen", "twoway_full")

MACRO_PRESETS = {
    "PointQueue (legacy per-link)":  ("DTA_PointQueue", "", False),
    "Node + PointQueue (nodeDNL)":   ("DTA_NodePQ", MESO_LIMITED_ACCESS, False),
    "Node + Spatial/LTM (nodeDNL)":  ("DTA_NodeLTM", MESO_LIMITED_ACCESS, False),
}
_DEFAULT_PRESET = ("DTA_NodeLTM", MESO_LIMITED_ACCESS, False)

# STA solver label -> STA_METHOD value. The static assignment is solved in flow
# space (all-or-nothing + a step on the Beckmann objective); "legacy" is the DTA
# path-swap loop, kept only to reproduce older runs -- its reroute floor cannot
# converge a static assignment.
STA_METHODS = {
    "Bi-conjugate Frank-Wolfe (fastest)":   "bfw",
    "Conjugate Frank-Wolfe":                "cfw",
    "Frank-Wolfe":                          "fw",
    "MSA (step 1/k)":                       "msa",
    "Legacy path-swap (does not converge)": "legacy",
}
# STA volume-delay curve label -> STA_VDF value. BPR is the legacy TSM curve;
# the other two exist because BPR's power term misbehaves around v/c = 1 -- flat
# where the real curve is already steepening, then explosive past it.
#   Conical (Spiess) keeps a bounded derivative, which is what makes the
#   Frank-Wolfe line search well behaved (measured: rel_gap 0.0025 vs BPR's
#   0.0055 at the same iteration on the 636k-link test network).
#   Akcelik is time-dependent: over-saturated delay grows with how long the
#   link stays loaded rather than with v/c alone, so its tail is far milder.
STA_VDFS = {
    "BPR (legacy TSM)":          "bpr",
    "Conical (Spiess)":          "conical",
    "Akcelik (time-dependent)":  "akcelik",
}

# ODME mode label -> ODME_MODE. "Grow only" raises under-loaded routes only:
# the added trips are the unmodeled (missing) market, written to
# odme_supplement.csv so later runs -- base or future year -- can load them.
ODME_MODES = {"Grow only (missing market)": "GROW", "Grow and reduce": "BOTH"}

# The ODME line edits: (widget attribute, settings key). Paired fields
# ("lo / hi") are split when the control file is written.
ODME_FIELDS = (("lineEdit_OdmeRounds", "hydra_odme_rounds"),
               ("lineEdit_OdmeReassign", "hydra_odme_reassign"),
               ("lineEdit_OdmePasses", "hydra_odme_passes"),
               ("lineEdit_OdmeAlpha", "hydra_odme_alpha"),
               ("lineEdit_OdmeMaxStep", "hydra_odme_max_step"),
               ("lineEdit_OdmeBounds", "hydra_odme_bounds"),
               ("lineEdit_OdmeMinImportance", "hydra_odme_min_importance"),
               ("lineEdit_OdmeModelClip", "hydra_odme_model_clip"))


def _pair(text, default_a, default_b):
    """Split an "a / b" field into two strings, falling back per side."""
    a, _, b = (text or "").partition("/")
    return (a.strip() or default_a), (b.strip() or default_b)


# VDF aggregation window label -> BPR_PERIOD_MIN.
BPR_PERIODS = {"15 min": "15", "30 min": "30", "60 min (hourly)": "60"}

# Per-link loader refresh label -> LOAD_REFRESH. Read only by the per-link
# PointQueue run mode; the node loaders are refreshed by NODE_SCHEDULE.
LOAD_REFRESH = {"Exact (rebuild all)": "exact", "Incremental (delta)": "incremental"}

# Departure-slot label -> DEPART_SLOT_MIN (route-key slot for HH:MM:SS trips).
DEPART_SLOTS = {"Auto (match trip list)": "AUTO", "15 min": "15", "30 min": "30",
                "60 min": "60"}

# Checkpoint "Then run" label -> resume plan.
RESUME_MODES = {"Up to Max Iterations": "max", "N more iterations": "more",
                "Outputs only (no new iterations)": "outputs"}

# Phase-1 DTA controls persisted in the scenario: (widget, settings key, kind).
P1_FIELDS = (("checkBox_Signals", "hydra_signals", "check"),
             ("lineEdit_SigSat", "hydra_sig_sat", "text"),
             ("lineEdit_SigCycle", "hydra_sig_cycle", "text"),
             ("lineEdit_SigGc", "hydra_sig_gc", "text"),
             ("lineEdit_SigGcFt", "hydra_sig_gc_ft", "text"),
             ("spinBox_MesoDt", "hydra_meso_dt", "spin"),
             ("comboBox_MicroDt", "hydra_micro_dt", "combo"),
             ("spinBox_MicroOuter", "hydra_micro_outer", "spin"),
             ("spinBox_ProbeStride", "hydra_probe_stride", "spin"),
             ("checkBox_MesoIntervalLog", "hydra_meso_interval_log", "check"),
             ("checkBox_MesoMovementLog", "hydra_meso_movement_log", "check"),
             ("checkBox_MesoSegmentLog", "hydra_meso_segment_log", "check"),
             ("doubleSpinBox_SegLen", "hydra_seg_len", "spin"),
             ("lineEdit_SegFile", "hydra_seg_file", "text"),
             ("checkBox_BuildViz", "hydra_build_viz", "check"),
             ("checkBox_BdMarket", "hydra_bd_market", "check"),
             ("checkBox_BdSegment", "hydra_bd_segment", "check"),
             ("checkBox_BdVotBin", "hydra_bd_votbin", "check"),
             ("lineEdit_VotEdges", "hydra_vot_edges", "text"),
             ("lineEdit_GmnsFile", "hydra_gmns_file", "text"),
             ("checkBox_UseGmns", "hydra_use_gmns", "check"),
             ("comboBox_MicroModel", "hydra_micro_model", "combo"),
             ("lineEdit_MicroPkg", "hydra_micro_pkg", "text"),
             ("checkBox_MicroCross", "hydra_micro_cross", "check"))

# Link tiers and probes sub-tabs: widget key -> (layer kind, field name).
TAG_TABS = {"Meso": ("link", "dta_meso"), "Micro": ("link", "dta_micro"),
            "Probe": ("link", "probe"), "NodeProbe": ("node", "probe")}


def read_checkpoint_header(path):
    """Header of an afdta checkpoint.bin, or a string saying why it is unusable.

    Layout (io/checkpoint.cpp): magic "AFDTACK1", int32 version, n_nodes,
    n_links, n_keys, iter, int64 path-link count; version 2 adds float slot
    width [min] and int32 flags (bit 0 = carries the STA averaged link flow).
    """
    try:
        with open(path, "rb") as f:
            head = f.read(8 + 5 * 4 + 8 + 4 + 4)
    except OSError as e:
        return f"cannot read the checkpoint: {e}"
    if len(head) < 36 or head[:8] != b"AFDTACK1":
        return "not an afdta checkpoint (bad header)"
    version, n_nodes, n_links, n_keys, it = struct.unpack_from("<5i", head, 8)
    info = {"version": version, "n_nodes": n_nodes, "n_links": n_links,
            "n_keys": n_keys, "iter": it, "slot_min": None, "sta_flow": False}
    if version >= 2 and len(head) >= 44:
        slot, flags = struct.unpack_from("<fi", head, 36)
        info["slot_min"] = slot
        info["sta_flow"] = bool(flags & 1)
    return info

# Per-iteration node-DNL refresh stride (NODE_SCHEDULE). Maps the GUI label to the
# control-file value; "hybrid" is expanded to an iteration ramp at write time
# (cheap per_iter through the sampling stages, a short per_chunk polish at the end).
NODE_SCHEDULES = {
    "Per iteration (fast - statewide)": "per_iter",
    "Per chunk (tight - county)":       "per_chunk",
    "Hybrid (per-iter -> per-chunk)":   "hybrid",
}


class HydraAssignModel(QDialog, Ui_DialogHydra):
    def __init__(self):
        super().__init__()

        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/hydra.ui")
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return
        uic.loadUi(ui_file, self)

        self.textBrowser.setOpenExternalLinks(True)
        self._load_help_doc(os.path.join(plugin_dir, "docs", "HYDRA.md"))

        # Threads default from General Configuration (num_processors) but stay editable
        # for a one-off run. Not persisted as a HyDRA setting -- it re-seeds from
        # General Configuration each time the dialog opens.
        self.lineEdit_Threads.setText(str(settings.num_processors()))
        self.lineEdit_Threads.setToolTip("Defaults from General Configuration (number of "
                                         "processors). Edit for this run only; not saved.")

        # Link/Node are GeoPackage layers loaded in QGIS; converted to CSV at run
        # time via gpkgcsv.exe.
        self.populate_layer_combobox(self.comboBox_LinkLayer, "LineString")
        self.populate_layer_combobox(self.comboBox_NodeLayer, "Point")

        # Default output location; the Output directory field (blank = scenario
        # directory) overrides it at run time via _resolve_out_dir.
        self._out_dir = (settings.get("scenarioDir") or "").replace("\\", "/")
        # HyDRA's network is its own setting (hydra_*_layer_name), NOT the
        # shared link/node_layer_name Skimmy reads: an MSR scenario assigns on
        # the Link Consolidator's MSR network while skims stay on TSM. Default
        # = the assignment network of the scenario (MSR or TSM); a saved TSM
        # pick is not carried into an MSR scenario.
        self._select_combo(self.comboBox_LinkLayer, self._hydra_layer(settings, "link"))
        self._select_combo(self.comboBox_NodeLayer, self._hydra_layer(settings, "node"))

        # Connections
        self.browse_TripFile.clicked.connect(lambda: self.select_file(self.lineEdit_TripFile, "Trip list (*.csv.gz *.csv)"))
        self.browse_OutDir.clicked.connect(self._browse_out_dir)
        self.browse_TollPolicy.clicked.connect(lambda: self.select_file(self.lineEdit_TollPolicy, "CSV (*.csv)"))
        self.browse_SegParams.clicked.connect(lambda: self.select_file(self.lineEdit_SegParams, "CSV (*.csv)"))
        self.comboBox_Macro.currentTextChanged.connect(self.apply_macro_preset)
        self.checkBox_Micro.toggled.connect(self.toggle_micro)
        self.checkBox_Signals.toggled.connect(self._toggle_signals)
        self.browse_CountFile.clicked.connect(lambda: self.select_file(self.lineEdit_CountFile, "Counts (*.csv)"))
        self.browse_SuppFile.clicked.connect(lambda: self.select_file(self.lineEdit_SuppFile, "Trip list (*.csv *.csv.gz)"))
        self.browse_SuppGrowth.clicked.connect(lambda: self.select_file(self.lineEdit_SuppGrowth, "CSV (*.csv)"))
        self.checkBox_Odme.toggled.connect(self.toggle_odme)
        # Checkpoint tabs (DTA and STA share the logic; p = widget-name prefix).
        for p, iters in (("", self.lineEdit_Iters), ("Sta", self.lineEdit_StaIters)):
            w = self._resume_w(p)
            w["browse"].clicked.connect(
                lambda _=False, e=w["file"]: self.select_file(e, "Checkpoint (*.bin *.ckpt)"))
            refresh = (lambda *_a, p=p: self._refresh_resume(p))
            w["check"].toggled.connect(refresh)
            w["file"].textChanged.connect(refresh)
            w["mode"].currentIndexChanged.connect(refresh)
            w["more"].textChanged.connect(refresh)
            w["write"].toggled.connect(refresh)
            iters.textChanged.connect(refresh)
        self.comboBox_Macro.currentTextChanged.connect(lambda _: self._sync_loader_controls())
        # Meso / Micro tab: tiers and probes from the HyDRA layers, segment file,
        # outer loops (twoway_full only).
        for key, (kind, field) in TAG_TABS.items():
            getattr(self, f"btn_Tag{key}Sel").clicked.connect(
                lambda _=False, k=kind, f=field: self._tag_selected(k, f))
            getattr(self, f"btn_Tag{key}Expr").clicked.connect(
                lambda _=False, k=kind, f=field: self._tag_by_expression(k, f))
            getattr(self, f"btn_Tag{key}Clear").clicked.connect(
                lambda _=False, k=kind, f=field: self._tag_clear(k, f))
        self.tabWidget_Tags.currentChanged.connect(lambda _: self._refresh_tag_counts())
        self.browse_SegFile.clicked.connect(
            lambda: self.select_file(self.lineEdit_SegFile, "Segments (*.csv)"))
        self.comboBox_Coupling.currentTextChanged.connect(self._sync_micro_outer)
        self.checkBox_Micro.toggled.connect(self._sync_micro_outer)
        # GMNS sub-tab: the netPrep GMNS package (lanes, pockets, movements,
        # signal timing) -- load / validate / edit timing; GMNS_DIR at run time.
        self.browse_GmnsFile.clicked.connect(
            lambda: self.select_file(self.lineEdit_GmnsFile, "GMNS package (*.gpkg)"))
        self.btn_GmnsLoad.clicked.connect(self._gmns_load)
        self.btn_GmnsValidate.clicked.connect(self._gmns_validate)
        self.btn_GmnsSignals.clicked.connect(self._gmns_signals)
        self.btn_GmnsImport.clicked.connect(self._gmns_import)
        # Micro package: rerun the micro area alone (frozen traffic, edited GMNS).
        self.browse_MicroPkg.clicked.connect(self._micro_pkg_browse)
        self.btn_MicroPkgOpen.clicked.connect(self._micro_pkg_open)
        self.btn_MicroPkgRun.clicked.connect(self._micro_pkg_run)
        self._gmns_windows = []
        # Network micro: the micro area polygon layer (refreshed as layers come
        # and go) and the model choice.
        self._fill_micro_area(Config().get("hydra_micro_area") or "")
        QgsProject.instance().layersAdded.connect(lambda *_: self._fill_micro_area())
        QgsProject.instance().layersRemoved.connect(lambda *_: self._fill_micro_area())
        self.comboBox_MicroModel.currentIndexChanged.connect(
            lambda _: self.toggle_micro(self.checkBox_Micro.isChecked()))
        self.run_Hydra.clicked.connect(lambda: self.run_hydra(show_message=True))
        # Save persists and LEAVES THE DIALOG OPEN (accepted -> update_settings,
        # never accept()), so settings can be saved and then run without
        # reopening. Cancel is the only thing that closes.
        self.buttonBox.accepted.connect(lambda: self.update_settings(notify=True))
        self.buttonBox.rejected.connect(self.reject)
        # No preselected engine: Run stays disabled until at least ONE tab has its
        # flow model / solver chosen, so the run mode is always deliberate. With
        # both filled in, Run asks which engine to use (see _choose_engine).
        self.tabWidget_Engine.currentChanged.connect(self._refresh_run_enabled)
        # The option groups sit in sub-tabs now (Engine/equilibrium, Meso-Micro,
        # Advanced; Solver/VDF, Equilibrium, Demand). A QTabWidget reserves the
        # height of its TALLEST page, so without this the short tabs would show
        # a band of dead space sized for Advanced.
        for _t in (self.tabWidget_Tags, self.tabWidget_MesoMicro, self.tabWidget_DTA,
                   self.tabWidget_STA, self.tabWidget_Engine):
            _t.currentChanged.connect(self._fit_tabs)
        self._fit_tabs()
        self.comboBox_Macro.currentIndexChanged.connect(self._refresh_run_enabled)
        self.comboBox_StaMethod.currentIndexChanged.connect(self._refresh_run_enabled)

        # Restore everything the Save button persists, so the dialog reopens with
        # the user's last HyDRA settings (not just the defaults).
        def _b(key):
            v = settings.get(key)
            return str(v).lower() in ("true", "1", "yes") if v is not None else False

        if settings.get("hydra_macro"):
            self._select_combo(self.comboBox_Macro, settings.get("hydra_macro"))
        if settings.get("hydra_iters"):
            self.lineEdit_Iters.setText(str(settings.get("hydra_iters")))
        if settings.get("hydra_gap"):
            self.lineEdit_Gap.setText(str(settings.get("hydra_gap")))
        if settings.get("hydra_chunks"):
            self.lineEdit_Chunks.setText(str(settings.get("hydra_chunks")))
        if settings.get("hydra_node_schedule"):
            self._select_node_schedule(settings.get("hydra_node_schedule"))
        trip = self._hydra_trip_file(settings)
        if trip:
            self.lineEdit_TripFile.setText(trip)
        if settings.get("hydra_out_dir"):
            self.lineEdit_OutDir.setText(settings.get("hydra_out_dir"))
        if settings.get("hydra_toll_policy"):
            self.lineEdit_TollPolicy.setText(settings.get("hydra_toll_policy"))
        if settings.get("hydra_segment_params"):
            self.lineEdit_SegParams.setText(settings.get("hydra_segment_params"))
        # Advanced numeric keys (each falls back to the .ui default if unset).
        for key, edit in (("hydra_reroute_fraction", self.lineEdit_RerouteFraction),
                          ("hydra_reroute_threshold", self.lineEdit_RerouteThreshold),
                          ("hydra_ltm_spillback", self.lineEdit_LtmSpillback),
                          ("hydra_jam_density", self.lineEdit_JamDensity),
                          ("hydra_max_trips", self.lineEdit_MaxTrips),
                          ("hydra_sample_every", self.lineEdit_SampleEvery),
                          ("hydra_sample_schedule", self.lineEdit_SampleSchedule),
                          ("hydra_checkpoint_every", self.lineEdit_CheckpointEvery)):
            if settings.get(key) not in (None, ""):
                edit.setText(str(settings.get(key)))
        if settings.get("hydra_inject_res") not in (None, ""):
            try:
                self.spinBox_InjectRes.setValue(int(float(settings.get("hydra_inject_res"))))
            except ValueError:
                pass
        if settings.get("hydra_depart_slot"):
            self._select_combo(self.comboBox_DepartSlot, settings.get("hydra_depart_slot"))
        if settings.get("hydra_sample_mode"):
            self._select_combo(self.comboBox_SampleSchedule, settings.get("hydra_sample_mode"))
        if settings.get("hydra_micro_ftypes"):
            self.lineEdit_MicroFtypes.setText(settings.get("hydra_micro_ftypes"))
        if settings.get("hydra_coupling"):
            v = settings.get("hydra_coupling")
            if v in COUPLINGS:
                self.comboBox_Coupling.setCurrentIndex(COUPLINGS.index(v))
        if settings.get("hydra_micro_choice"):
            self._select_combo(self.comboBox_MicroChoice, settings.get("hydra_micro_choice"))
        self.checkBox_Micro.setChecked(_b("hydra_micro_enabled"))
        # Both agent artifacts default ON; only an explicit saved "false" unchecks.
        def _b_on(key):
            v = settings.get(key)
            return True if v in (None, "") else str(v).lower() in ("true", "1", "yes")
        self.checkBox_AgentPlans.setChecked(_b_on("hydra_agent_plans"))
        self.checkBox_AgentPaths.setChecked(_b_on("hydra_agent_paths"))
        self.checkBox_Checkpoint.setChecked(_b_on("hydra_checkpoint"))
        # Counts / ODME / supplemental demand
        for key, edit in (("hydra_count_file", self.lineEdit_CountFile),
                          ("hydra_supp_file", self.lineEdit_SuppFile),
                          ("hydra_supp_scale", self.lineEdit_SuppScale),
                          ("hydra_supp_growth", self.lineEdit_SuppGrowth)):
            if settings.get(key) not in (None, ""):
                edit.setText(str(settings.get(key)))
        for attr, key in ODME_FIELDS:
            if settings.get(key) not in (None, ""):
                getattr(self, attr).setText(str(settings.get(key)))
        if settings.get("hydra_odme_mode"):
            self._select_combo(self.comboBox_OdmeMode, settings.get("hydra_odme_mode"))
        self.checkBox_Odme.setChecked(_b("hydra_odme"))
        self.toggle_odme(self.checkBox_Odme.isChecked())

        # ---- STA tab ----
        if settings.get("hydra_sta_method"):
            self._select_combo(self.comboBox_StaMethod, settings.get("hydra_sta_method"))
        if settings.get("hydra_bpr_period"):
            self._select_combo(self.comboBox_BprPeriod, settings.get("hydra_bpr_period"))
        # VDF curve + the parameters that belong to each one.
        if settings.get("hydra_sta_vdf"):
            self._select_combo(self.comboBox_StaVdf, settings.get("hydra_sta_vdf"))
        for key, edit in (("hydra_conical_alpha", self.lineEdit_ConicalAlpha),
                          ("hydra_akcelik_ja", self.lineEdit_AkcelikJa),
                          ("hydra_bpr_beta_mult", self.lineEdit_BprBetaMult)):
            if settings.get(key) not in (None, ""):
                edit.setText(str(settings.get(key)))
        self.checkBox_BprOverCap.setChecked(_b("hydra_bpr_overcap"))
        self.comboBox_StaVdf.currentTextChanged.connect(lambda _: self._sync_vdf())
        self.checkBox_BprOverCap.toggled.connect(lambda _: self._sync_vdf())
        self._sync_vdf()
        for key, edit in (("hydra_sta_iters", self.lineEdit_StaIters),
                          ("hydra_sta_gap", self.lineEdit_StaGap),
                          ("hydra_sta_threads", self.lineEdit_StaThreads),
                          ("hydra_sta_max_trips", self.lineEdit_StaMaxTrips),
                          ("hydra_sta_sample_every", self.lineEdit_StaSampleEvery),
                          ("hydra_sta_sample_schedule", self.lineEdit_StaSampleSchedule),
                          ("hydra_sta_checkpoint_every", self.lineEdit_StaCheckpointEvery)):
            if settings.get(key) not in (None, ""):
                edit.setText(str(settings.get(key)))
        if settings.get("hydra_sta_sample_mode"):
            self._select_combo(self.comboBox_StaSampleSchedule, settings.get("hydra_sta_sample_mode"))
        self.checkBox_StaCheckpoint.setChecked(_b_on("hydra_sta_checkpoint"))
        self.checkBox_StaAgentPlans.setChecked(_b_on("hydra_sta_agent_plans"))
        self.checkBox_StaAgentPaths.setChecked(_b("hydra_sta_agent_paths"))
        self.checkBox_StaPathScale.setChecked(_b_on("hydra_sta_path_scale"))
        # Resume (Checkpoint tabs). Off by default: a resume is a deliberate act.
        for p, key in (("", "hydra"), ("Sta", "hydra_sta")):
            w = self._resume_w(p)
            if settings.get(f"{key}_resume_file"):
                w["file"].setText(settings.get(f"{key}_resume_file"))
            if settings.get(f"{key}_resume_mode"):
                self._select_combo(w["mode"], settings.get(f"{key}_resume_mode"))
            if settings.get(f"{key}_resume_more") not in (None, ""):
                w["more"].setText(str(settings.get(f"{key}_resume_more")))
            w["check"].setChecked(_b(f"{key}_resume"))
            self._refresh_resume(p)
        if settings.get("hydra_load_refresh"):
            self._select_combo(self.comboBox_LoadRefresh, settings.get("hydra_load_refresh"))
        if settings.get("hydra_load_schedule"):
            self.lineEdit_LoadSchedule.setText(settings.get("hydra_load_schedule"))

        # apply_macro_preset() overwrites Meso FTYPEs from the preset, so restore the
        # saved override AFTER it; toggle_micro() applies the enable state.
        self.apply_macro_preset(self.comboBox_Macro.currentText())
        if settings.get("hydra_meso_ftypes"):
            self.lineEdit_MesoFtypes.setText(settings.get("hydra_meso_ftypes"))
        self.toggle_micro(self.checkBox_Micro.isChecked())
        self._toggle_signals(self.checkBox_Signals.isChecked())
        self._sync_loader_controls()
        from . import gmns_tools
        self.lineEdit_GmnsFile.setText(gmns_tools.default_path(settings))
        for attr, key, kind in P1_FIELDS:
            v = settings.get(key)
            if v in (None, ""):
                continue
            w = getattr(self, attr)
            try:
                if kind == "check":
                    w.setChecked(str(v).lower() in ("true", "1", "yes"))
                elif kind == "text":
                    w.setText(str(v))
                elif kind == "combo":
                    self._select_combo(w, str(v))
                else:
                    w.setValue(type(w.value())(float(v)))
            except (ValueError, TypeError):
                pass
        self._sync_micro_outer()
        self._refresh_tag_counts()

        # Reopen on whichever engine tab was saved; Run re-enables only once the
        # tab's mode is set (a saved scenario carries that, a fresh one does not).
        saved_tab = (settings.get("hydra_engine") or "").upper()
        if saved_tab == "STA":
            self.tabWidget_Engine.setCurrentWidget(self.page_STA)
        elif saved_tab == "DTA":
            self.tabWidget_Engine.setCurrentWidget(self.page_DTA)
        self._refresh_run_enabled()

    def _sync_vdf(self):
        """Grey out the parameters that do not belong to the chosen curve.

        Each curve reads exactly one of these, so leaving all three live invites
        someone to set a conical alpha on a BPR run and expect it to matter.
        """
        vdf = STA_VDFS.get(self.comboBox_StaVdf.currentText(), "bpr")
        is_bpr = vdf == "bpr"
        self.checkBox_BprOverCap.setEnabled(is_bpr)
        self.label_bprBetaMult.setEnabled(is_bpr)
        self.lineEdit_BprBetaMult.setEnabled(is_bpr and
                                             self.checkBox_BprOverCap.isChecked())
        self.label_conicalAlpha.setEnabled(vdf == "conical")
        self.lineEdit_ConicalAlpha.setEnabled(vdf == "conical")
        self.label_akcelikJa.setEnabled(vdf == "akcelik")
        self.lineEdit_AkcelikJa.setEnabled(vdf == "akcelik")
        # alpha/beta are per-link, so this note only applies to BPR.
        self.label_bprCoef.setEnabled(is_bpr)

    @staticmethod
    def _fit_one_tab(tabs):
        """Cap a tab frame at the page on screen instead of the tallest page."""
        page = tabs.currentWidget()
        if page is None:
            return
        tabs.setMaximumHeight(page.sizeHint().height()
                              + tabs.tabBar().sizeHint().height() + 12)

    def _fit_tabs(self, *_):
        """Re-fit the sub-tabs first, then the engine tabs that contain them --
        the outer frame's height depends on what the inner ones settled at."""
        self._fit_one_tab(self.tabWidget_Tags)        # innermost first
        self._fit_one_tab(self.tabWidget_MesoMicro)
        self._fit_one_tab(self.tabWidget_DTA)
        self._fit_one_tab(self.tabWidget_STA)
        self._fit_one_tab(self.tabWidget_Engine)

    # ------------------------------------------------------------------
    def _is_sta(self):
        """True when the STA tab is the active engine."""
        return self.tabWidget_Engine.currentWidget() is self.page_STA

    def _dta_ready(self):
        """True when the DTA tab carries a run mode (flow model)."""
        return self.comboBox_Macro.currentIndex() >= 0

    def _sta_ready(self):
        """True when the STA tab carries a solver."""
        return self.comboBox_StaMethod.currentIndex() >= 0

    def _choose_engine(self):
        """Which engine this run uses: "DTA", "STA", or None to abort.

        The two tabs are independent specifications and BOTH are saved, so the
        visible tab is not evidence of intent -- filling in STA and then
        flicking back to DTA to re-read a value used to silently run a DTA
        assignment. When both tabs are filled in, ask; when only one is, that
        one is the answer and no dialog appears.
        """
        dta, sta = self._dta_ready(), self._sta_ready()
        if dta and not sta:
            return "DTA"
        if sta and not dta:
            return "STA"
        if not (dta or sta):
            QMessageBox.critical(self, "No engine selected",
                                 "Pick a Run Mode (flow model) on the DTA tab or a "
                                 "solver on the STA tab before running.")
            return None
        # Both specified: ask, defaulting to the tab on screen.
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Which assignment should run?")
        box.setText("Both engines are configured for this scenario.\n\n"
                    "Which one should this run use?")
        box.setInformativeText(
            "DTA (dynamic): %s\nSTA (static): %s\n\n"
            "Both specifications stay saved either way; only the selected one "
            "is written to the HyDRA control file."
            % (self.comboBox_Macro.currentText(), self.comboBox_StaMethod.currentText()))
        b_dta = box.addButton("Run DTA (dynamic)", QMessageBox.ButtonRole.AcceptRole)
        b_sta = box.addButton("Run STA (static)", QMessageBox.ButtonRole.AcceptRole)
        b_cancel = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(b_sta if self._is_sta() else b_dta)
        box.exec()
        clicked = box.clickedButton()
        if clicked is None or clicked == b_cancel:
            return None
        return "STA" if clicked == b_sta else "DTA"

    def _default_engine(self):
        """Engine recorded by Save when the run has not picked one: the visible
        tab, unless it is the empty one and the other tab is filled in (saving
        an STA specification must not leave hydra_engine reading "DTA")."""
        sta = self._is_sta()
        if sta and not self._sta_ready() and self._dta_ready():
            return "DTA"
        if not sta and not self._dta_ready() and self._sta_ready():
            return "STA"
        return "STA" if sta else "DTA"

    def _refresh_run_enabled(self, *_):
        """Run is available once EITHER tab's engine is chosen (the run asks which
        one when both are)."""
        ready = self._dta_ready() or self._sta_ready()
        self.run_Hydra.setEnabled(ready)
        self.run_Hydra.setToolTip(
            "" if ready else
            "Pick a Run Mode (flow model) on the DTA tab, or a solver on the STA tab.")

    # ------------------------------------------------------------------
    def _load_help_doc(self, md_path):
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                md = f.read()
        except Exception as e:
            print(f"Could not read help doc {md_path}: {e}")
            return
        if hasattr(self.textBrowser, "setMarkdown"):
            self.textBrowser.setMarkdown(md)
        else:
            self.textBrowser.setPlainText(md)

    def apply_macro_preset(self, name):
        _, meso, _ = MACRO_PRESETS.get(name, _DEFAULT_PRESET)
        self.lineEdit_MesoFtypes.setText(meso)

    def _select_node_schedule(self, value):
        """Select the node-schedule combo from a saved control value (per_iter /
        per_chunk / hybrid)."""
        for text, val in NODE_SCHEDULES.items():
            if val == value:
                self._select_combo(self.comboBox_NodeSchedule, text)
                return

    def _node_schedule_value(self):
        """NODE_SCHEDULE control value from the combo. 'hybrid' expands to an
        iteration ramp: cheap per_iter for most iterations, a short per_chunk
        polish at the end (last ~15%, min 3) to restore the AM/PM peaks."""
        val = NODE_SCHEDULES.get(self.comboBox_NodeSchedule.currentText(), "per_iter")
        if val != "hybrid":
            return val
        try:
            iters = int(float(self.lineEdit_Iters.text().strip() or "10"))
        except ValueError:
            iters = 10
        split = max(1, iters - max(3, round(iters * 0.15)))
        return "per_chunk" if split >= iters else f"1-{split}:iter, {split+1}-{iters}:chunk"

    def _sample_schedule_value(self, mode_combo=None, custom_edit=None, iters_edit=None):
        """SAMPLE_SCHEDULE control value, or "" to omit the key (full sample).

        Progressive coarse-to-fine runs the early iterations on a cheap sample
        and only the later ones at 100%, for ~30% less wall time at the same
        converged result. The split mirrors the runs of record: for 15
        iterations it reproduces "1-4:25, 5-8:50, 9-15:100" exactly.

        Defaults to the DTA widgets; the STA tab passes its own -- including
        its own iteration count, which used to be picked by the VISIBLE tab and
        so staged an STA run against the DTA iteration count -- and both tabs
        share this logic rather than duplicating the staging arithmetic.
        """
        mode_combo = mode_combo or self.comboBox_SampleSchedule
        custom_edit = custom_edit or self.lineEdit_SampleSchedule
        iters_edit = iters_edit or self.lineEdit_Iters
        mode = mode_combo.currentText()
        if mode.startswith("Custom"):
            return custom_edit.text().strip()
        if not mode.startswith("Progressive"):
            return ""                      # full sample -> omit the key
        try:
            iters = int(float(iters_edit.text().strip() or "10"))
        except ValueError:
            iters = 10
        if iters < 3:
            return ""
        a = max(1, round(iters * 0.27))            # 25% stage
        b = max(a + 1, round(iters * 0.53))        # 50% stage
        if b >= iters:                             # too few iterations to stage
            return ""
        return "1-%d:25, %d-%d:50, %d-%d:100" % (a, a + 1, b, b + 1, iters)

    def _agent_paths_on(self, sta):
        """WRITE_AGENT_PATHS for the engine actually being run. Each tab carries
        its own toggle, so the DTA checkbox must not speak for an STA run."""
        return (self.checkBox_StaAgentPaths if sta
                else self.checkBox_AgentPaths).isChecked()

    def toggle_micro(self, on):
        network = self._micro_network()
        self.lineEdit_MicroFtypes.setEnabled(on)
        self.comboBox_Coupling.setEnabled(on)
        self.comboBox_MicroModel.setEnabled(on)
        # EL/GP choice is a freeway-corridor setting; area + cross streets are network ones.
        self.comboBox_MicroChoice.setEnabled(on and not network)
        for w in (self.label_MicroArea, self.comboBox_MicroArea, self.checkBox_MicroCross):
            w.setEnabled(on and network)

    def _toggle_signals(self, on):
        # Unchecked, no SIGNAL_MODEL is written: no capacity cap, no control
        # delay, and these values are not read.
        for w in (self.label_sigSat, self.lineEdit_SigSat, self.label_sigCycle, self.lineEdit_SigCycle,
                  self.label_sigGc, self.lineEdit_SigGc, self.label_sigGcFt, self.lineEdit_SigGcFt):
            w.setEnabled(on)

    def _coupling(self):
        """MICRO_COUPLING value of the coupling combo (its labels are descriptive)."""
        return COUPLINGS[max(0, self.comboBox_Coupling.currentIndex())]

    def _micro_network(self):
        return self.comboBox_MicroModel.currentText().startswith("Network")

    def _fill_micro_area(self, keep=None):
        """Polygon layers for the network micro area ("(none)" first)."""
        from qgis.core import QgsMapLayerType, QgsWkbTypes
        combo = self.comboBox_MicroArea
        keep = combo.currentText() if keep is None else keep
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("(none)", None)
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.type() == QgsMapLayerType.VectorLayer and \
                    lyr.geometryType() == QgsWkbTypes.GeometryType.PolygonGeometry:
                combo.addItem(lyr.name(), lyr.id())
        i = combo.findText(keep)
        combo.setCurrentIndex(i if i >= 0 else 0)
        combo.blockSignals(False)

    def toggle_odme(self, on):
        """ODME tuning only matters when ODME runs; the count file and the
        supplement stay live (validation and supplement loading work alone)."""
        self.comboBox_OdmeMode.setEnabled(on)
        for attr, _ in ODME_FIELDS:
            getattr(self, attr).setEnabled(on)

    def _is_per_link_loader(self):
        """True for the per-link PointQueue run mode (no node model)."""
        model = MACRO_PRESETS.get(self.comboBox_Macro.currentText(), _DEFAULT_PRESET)[0]
        return model == "DTA_PointQueue"

    def _sync_loader_controls(self):
        """Grey out the loading controls the chosen run mode does not read:
        Loading resolution is a node-loader setting; Per-link load refresh and
        schedule belong to the per-link PointQueue mode only."""
        per_link = self._is_per_link_loader()
        for w in (self.label_injectRes, self.spinBox_InjectRes):
            w.setEnabled(not per_link)
        for w in (self.label_loadRefresh, self.comboBox_LoadRefresh,
                  self.label_loadSchedule, self.lineEdit_LoadSchedule):
            w.setEnabled(per_link)

    # ---- checkpoint / resume -------------------------------------------
    def _resume_w(self, p):
        """The Checkpoint-tab widgets of one engine (p = "" DTA, "Sta" STA)."""
        lo = p.lower()
        return {"check": getattr(self, f"checkBox_{p}Resume"),
                "file": getattr(self, f"lineEdit_{p}ResumeFile"),
                "browse": getattr(self, f"browse_{p}ResumeFile"),
                "info": getattr(self, f"label_{p}ResumeInfo"),
                "mode": getattr(self, f"comboBox_{p}ResumeMode"),
                "more": getattr(self, f"lineEdit_{p}ResumeMore"),
                "more_label": getattr(self, f"label_{lo}ResumeMore"),
                "iters": self.lineEdit_StaIters if p else self.lineEdit_Iters,
                "write": self.checkBox_StaCheckpoint if p else self.checkBox_Checkpoint}

    def _resume_plan(self, p):
        """(checkpoint header, MAX_ITERATIONS to write, error) for a resume of
        engine p, or (None, None, None) when resume is off.

        "Up to Max Iterations" keeps the Max Iterations field; "N more" runs
        N past the checkpoint; "Outputs only" sets MAX_ITERATIONS to the
        checkpoint's own iteration, which afdta treats as load-and-post-process.
        """
        w = self._resume_w(p)
        if not w["check"].isChecked():
            return None, None, None
        path = w["file"].text().strip()
        if not path:
            return None, None, "Pick the checkpoint file to resume from."
        if not os.path.exists(path):
            return None, None, f"Checkpoint not found: {path}"
        hdr = read_checkpoint_header(path)
        if isinstance(hdr, str):
            return None, None, hdr[0].upper() + hdr[1:] + "."
        if p and not hdr["sta_flow"]:
            return hdr, None, ("This checkpoint holds no STA link flow (written by a DTA run "
                               "or an older afdta), so STA cannot resume from it.")
        mode = RESUME_MODES.get(w["mode"].currentText(), "max")
        try:
            if mode == "more":
                n = max(int(float(w["more"].text().strip() or "0")), 0)
                return hdr, hdr["iter"] + n, None
            if mode == "outputs":
                return hdr, hdr["iter"], None
            return hdr, int(float(w["iters"].text().strip() or "10")), None
        except ValueError:
            return hdr, None, "The iteration count is not a number."

    def _refresh_resume(self, p):
        """Enable the resume widgets with the checkbox and describe the chosen
        checkpoint: its iteration, size, slot width and engine, and what the
        run will then do."""
        w = self._resume_w(p)
        on = w["check"].isChecked()
        for k in ("file", "browse", "mode", "info"):
            w[k].setEnabled(on)
        more = RESUME_MODES.get(w["mode"].currentText()) == "more"
        w["more"].setEnabled(on and more)
        w["more_label"].setEnabled(on and more)
        if not on:
            w["info"].setText("")
            return
        hdr, max_iter, err = self._resume_plan(p)
        if hdr is None:
            w["info"].setText(err or "")
            return
        slot = ("%.0f-min slots" % hdr["slot_min"]) if hdr["slot_min"] else \
            "slot width not recorded (older afdta)"
        kind = "STA" if hdr["sta_flow"] else ("DTA" if hdr["version"] >= 2 else "version-1")
        text = "Iteration %d · %s route keys · %s links · %s · %s checkpoint." % (
            hdr["iter"], f"{hdr['n_keys']:,}", f"{hdr['n_links']:,}", slot, kind)
        if err:
            text += "\n" + err
        elif max_iter <= hdr["iter"]:
            text += "\nNo new iterations: outputs are written from the loaded state."
        else:
            text += "\nRuns iterations %d to %d." % (hdr["iter"] + 1, max_iter)
        out_ckpt = os.path.join(self._out_dir_for_check(), "checkpoint.bin")
        if w["write"].isChecked() and os.path.normcase(os.path.abspath(out_ckpt)) == \
                os.path.normcase(os.path.abspath(w["file"].text().strip())):
            text += " This run writes its own checkpoint over this file."
        w["info"].setText(text)

    def _out_dir_for_check(self):
        """Output directory as typed (blank = scenario directory), without
        creating it -- for display only."""
        return (self.lineEdit_OutDir.text().strip() or self._out_dir or "").replace("\\", "/")

    def _write_resume_ctl(self, f, p, pad):
        """RESUME_FROM for engine p. Returns False (after telling the user)
        when the resume cannot run."""
        hdr, _max_iter, err = self._resume_plan(p)
        if err:
            QMessageBox.critical(self, "Cannot resume", err)
            return False
        if hdr is not None:
            path = self._resume_w(p)["file"].text().strip().replace("\\", "/")
            f.write(f"RESUME_FROM{' ' * pad}{path}\n")
        return True

    def _max_iters_value(self, p):
        """MAX_ITERATIONS for engine p: the resume plan's when resuming."""
        _hdr, max_iter, err = self._resume_plan(p)
        if max_iter is not None and not err:
            return str(max_iter)
        edit = self.lineEdit_StaIters if p else self.lineEdit_Iters
        return edit.text().strip() or ("15" if p else "10")

    # ---- link tiers and probes (Meso / Micro tab) ----------------------
    def _tag_layer(self, kind):
        """The HyDRA link or node layer picked at the top of the dialog."""
        combo = self.comboBox_LinkLayer if kind == "link" else self.comboBox_NodeLayer
        lyr = combo.currentData()
        if lyr is None:
            QMessageBox.warning(self, "Link tiers and probes",
                                "Pick the HyDRA %s layer at the top of the dialog first." % kind)
        return lyr

    @staticmethod
    def _ensure_flag_field(lyr, field):
        """Index of an integer flag field on the layer, adding it when missing."""
        idx = lyr.fields().indexOf(field)
        if idx >= 0:
            return idx
        from qgis.core import QgsField
        try:
            from qgis.PyQt.QtCore import QMetaType
            fld = QgsField(field, QMetaType.Type.Int)
        except (ImportError, AttributeError, TypeError):
            from qgis.PyQt.QtCore import QVariant
            fld = QgsField(field, QVariant.Int)
        if lyr.isEditable():
            lyr.addAttribute(fld)
        else:
            lyr.dataProvider().addAttributes([fld])
        lyr.updateFields()
        return lyr.fields().indexOf(field)

    def _write_flags(self, lyr, field, fids, value):
        """Set `field` = value on the features fids. In the layer's edit buffer
        when the user is editing it (they commit), else straight to the data
        source."""
        idx = self._ensure_flag_field(lyr, field)
        if idx < 0:
            QMessageBox.critical(self, "Link tiers and probes",
                                 "Could not add the field %s to %s." % (field, lyr.name()))
            return 0
        fids = list(fids)
        if lyr.isEditable():
            for fid in fids:
                lyr.changeAttributeValue(fid, idx, value)
        else:
            lyr.dataProvider().changeAttributeValues({fid: {idx: value} for fid in fids})
            lyr.reload()
        lyr.triggerRepaint()
        return len(fids)

    # ---- GMNS sub-tab
    def _gmns_path(self):
        """The file the GMNS tools work on: the statewide package, or the open
        micro package's micro_gmns.gpkg."""
        from . import gmns_tools
        if self.comboBox_GmnsTarget.currentIndex() == 1:
            path = gmns_tools.package_gpkg(self.lineEdit_MicroPkg.text().strip())
            if not os.path.exists(path):
                QMessageBox.warning(self, "GMNS", "Open a micro package for editing first (Micro package > "
                                    "Open for editing).")
                return None
            return path
        path = self.lineEdit_GmnsFile.text().strip()
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "GMNS", "Pick the GMNS package (gmns_network.gpkg from netPrep) first.")
            return None
        return path

    # ---- Micro package
    def _micro_pkg_dir(self):
        from . import gmns_tools
        d = self.lineEdit_MicroPkg.text().strip()
        if not gmns_tools.is_package(d):
            QMessageBox.warning(self, "Micro package", "Pick a micro package folder (<output>/micro_package of a "
                                "network micro run; it holds micro_package.ctl).")
            return None
        return d

    def _micro_pkg_browse(self):
        from qgis.PyQt.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "Micro package folder", self.lineEdit_MicroPkg.text().strip())
        if d:
            self.lineEdit_MicroPkg.setText(d.replace("\\", "/"))

    def _micro_pkg_open(self):
        """Cut micro_gmns.gpkg from the statewide GMNS package (once; ask before
        replacing edits), load its layers and point the GMNS tools at it."""
        from . import gmns_tools
        d = self._micro_pkg_dir()
        if not d:
            return
        gp = gmns_tools.package_gpkg(d)
        build = not os.path.exists(gp)
        if not build and QMessageBox.question(
                self, "Micro package", "micro_gmns.gpkg exists (it may hold your edits).\n\nKeep it? "
                "No cuts it again from the GMNS package.") == QMessageBox.StandardButton.No:
            build = True
        if build:
            src = self.lineEdit_GmnsFile.text().strip()
            if not src or not os.path.exists(src):
                QMessageBox.warning(self, "Micro package", "Pick the statewide GMNS package above first: the "
                                    "editable copy is cut from it.")
                return
            try:
                for lyr in gmns_tools._gmns_layers(gp).values():
                    QgsProject.instance().removeMapLayer(lyr.id())
                gp = gmns_tools.build_package_gpkg(src, d)
            except Exception as e:
                QMessageBox.critical(self, "Micro package", "Could not build micro_gmns.gpkg: %s" % e)
                return
        self.comboBox_GmnsTarget.setCurrentIndex(1)
        if not gmns_tools._gmns_layers(gp):
            try:
                gmns_tools.load_layers(gp)
            except Exception as e:
                QMessageBox.critical(self, "Micro package", "Could not load the layers: %s" % e)
                return
        QMessageBox.information(self, "Micro package", "Editing %s.\n\nSignal timing, Validate and Import "
                                "timing pack now work on it; Run uses it." % gp)

    def _micro_pkg_run(self):
        """Rerun the package: export micro_gmns.gpkg (if any) to gmns/, run
        afdta MICRO_PACKAGE into <package>/<run name>, add the LOS layers."""
        import datetime
        from . import gmns_tools
        d = self._micro_pkg_dir()
        if not d:
            return
        settings = Config()
        afdta = settings.app_exe("Hydra/afdta.exe")
        name = self.lineEdit_MicroPkgRun.text().strip() or datetime.datetime.now().strftime("run_%Y%m%d_%H%M%S")
        name = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
        out = os.path.join(d, name).replace("\\", "/")
        os.makedirs(out, exist_ok=True)
        log = os.path.join(out, "Hydra.log")
        gp = gmns_tools.package_gpkg(d)
        if os.path.exists(gp):
            busy = gmns_tools._editing(gp, gmns_tools.EXPORT_TABLES)
            if busy:
                QMessageBox.warning(self, "Micro package", "Save or stop editing first: %s" % ", ".join(busy))
                return
            try:
                gmns_tools.export_csv(gp, os.path.join(d, "gmns"), settings.app_exe("utilities/gpkgcsv.exe"),
                                      lambda args: settings.run_app(args, log_path=log, append=True))
            except Exception as e:
                QMessageBox.critical(self, "Micro package", "Could not export micro_gmns.gpkg: %s" % e)
                return
        dt = "0.5"
        with open(os.path.join(d, "micro_package.ctl")) as f:
            for line in f:
                if line.startswith("MICRO_DT_SEC"):
                    dt = line.split()[1]
        ctl = os.path.join(out, "micro_run.ctl")
        with open(ctl, "w") as f:
            f.write("# AgentFlow micro package rerun - generated by the HyDRA dialog\n")
            f.write("MICRO_PACKAGE         %s\n" % d.replace("\\", "/"))
            f.write("OUTPUT_DIRECTORY      %s\n" % out)
            f.write("MICRO_DT_SEC          %s\n" % dt)
        if not run_gated_model(self, [afdta, "--control", ctl], "HyDRA micro package",
                               log_path=log, console=True):
            end_run_console()
            return
        end_run_console()
        summary = ""
        try:
            with open(log, errors="replace") as f:
                summary = "\n".join(l.strip() for l in f if "vehicles left the area" in l)
        except OSError:
            pass
        los = gmns_tools.build_micro_los(gp if os.path.exists(gp) else self.lineEdit_GmnsFile.text().strip(), out)
        added = gmns_tools.load_micro_los(los, name) if los else []
        QMessageBox.information(self, "Micro package", "Run %s done.\n\n%s\n\nOutputs in %s%s" % (
            name, summary, out, ("\nLayers: " + ", ".join(added)) if added else ""))

    def _gmns_load(self):
        from . import gmns_tools
        path = self._gmns_path()
        if not path:
            return
        try:
            lyrs = gmns_tools.load_layers(path)
        except Exception as e:
            QMessageBox.critical(self, "GMNS", "Could not load the GMNS layers: %s" % e)
            return
        QMessageBox.information(self, "GMNS", "Added %d GMNS layers. Lanes, pockets and movements draw "
                                "when zoomed in (1:10,000 and closer)." % len(lyrs))

    def _gmns_show(self, dlg):
        self._gmns_windows = [w for w in self._gmns_windows if w.isVisible()] + [dlg]
        dlg.show()

    def _gmns_validate(self):
        from . import gmns_tools
        from qgis.utils import iface
        path = self._gmns_path()
        if path:
            self._gmns_show(gmns_tools.ValidateDialog(path, iface, self))

    def _gmns_signals(self):
        from . import gmns_tools
        from qgis.utils import iface
        path = self._gmns_path()
        if path:
            dlg = gmns_tools.SignalTimingDialog(path, iface, self)
            self._gmns_show(dlg)
            lyr = iface.activeLayer() if iface else None
            if lyr is not None and hasattr(lyr, "selectedFeatureCount") and lyr.selectedFeatureCount():
                dlg.from_selection()

    def _gmns_import(self):
        """Load a timing pack (config/gmns/samples has demonstration packs)."""
        from . import gmns_tools
        from qgis.PyQt.QtWidgets import QFileDialog
        path = self._gmns_path()
        if not path:
            return
        busy = gmns_tools._editing(path, ("node", "movement") + gmns_tools.SIGNAL_TABLES)
        if busy:
            QMessageBox.warning(self, "GMNS", "Save or stop editing first: %s" % ", ".join(busy))
            return
        start = os.path.join(os.path.dirname(__file__), "config", "gmns", "samples")
        d = QFileDialog.getExistingDirectory(self, "Timing pack folder", start)
        if not d:
            return
        try:
            st = gmns_tools.import_timing(path, d)
        except Exception as e:
            QMessageBox.critical(self, "GMNS", "Timing pack not loaded: %s" % e)
            return
        msg = ("Loaded %d controllers: %d plans, %d phases, %d phase movements."
               % (st["controllers"], st["plans"], st["phases"], st["movements"]))
        if st["unmatched"]:
            msg += ("\n\n%d pack movements are not in this package (skipped):\n%s"
                    % (len(st["unmatched"]), "\n".join(st["unmatched"][:15])))
        QMessageBox.information(self, "GMNS", msg)

    def _tag_selected(self, kind, field):
        lyr = self._tag_layer(kind)
        if lyr is None:
            return
        fids = lyr.selectedFeatureIds()
        if not fids:
            QMessageBox.information(self, "Link tiers and probes",
                                    "Select features on %s first (the dialog stays open)." % lyr.name())
            return
        n = self._write_flags(lyr, field, fids, 1)
        self._refresh_tag_counts(note="%s = 1 set on %d %s." % (field, n, "links" if kind == "link" else "nodes"))

    def _tag_by_expression(self, kind, field):
        lyr = self._tag_layer(kind)
        if lyr is None:
            return
        from qgis.gui import QgsExpressionBuilderDialog
        from qgis.core import QgsExpression, QgsFeatureRequest
        dlg = QgsExpressionBuilderDialog(lyr, "", self)
        dlg.setWindowTitle("Set %s = 1 where..." % field)
        if not dlg.exec():
            return
        expr = QgsExpression(dlg.expressionText())
        if expr.hasParserError():
            QMessageBox.critical(self, "Link tiers and probes", expr.parserErrorString())
            return
        req = QgsFeatureRequest(expr)
        req.setFlags(QgsFeatureRequest.Flag.NoGeometry)
        req.setNoAttributes()
        fids = [f.id() for f in lyr.getFeatures(req)]
        n = self._write_flags(lyr, field, fids, 1)
        self._refresh_tag_counts(note="%s = 1 set on %d features matching the expression." % (field, n))

    def _tag_clear(self, kind, field):
        lyr = self._tag_layer(kind)
        if lyr is None or lyr.fields().indexOf(field) < 0:
            return
        fids = self._flagged_ids(lyr, field)
        if not fids:
            return
        if QMessageBox.question(self, "Clear field",
                                "Set %s = 0 on the %d flagged features of %s?"
                                % (field, len(fids), lyr.name())) != QMessageBox.StandardButton.Yes:
            return
        self._write_flags(lyr, field, fids, 0)
        self._refresh_tag_counts(note="%s cleared on %d features." % (field, len(fids)))

    @staticmethod
    def _flagged_ids(lyr, field):
        from qgis.core import QgsFeatureRequest
        if lyr.fields().indexOf(field) < 0:
            return []
        req = QgsFeatureRequest().setFilterExpression('"%s" = 1' % field)
        req.setFlags(QgsFeatureRequest.Flag.NoGeometry)
        req.setNoAttributes()
        return [f.id() for f in lyr.getFeatures(req)]

    def _refresh_tag_counts(self, *_a, note=""):
        """Show how many links / nodes carry each flag on the HyDRA layers."""
        parts = []
        for kind, field in (("link", "dta_meso"), ("link", "dta_micro"),
                            ("link", "probe"), ("node", "probe")):
            combo = self.comboBox_LinkLayer if kind == "link" else self.comboBox_NodeLayer
            lyr = combo.currentData()
            if lyr is None:
                continue
            n = len(self._flagged_ids(lyr, field))
            parts.append("%s %s: %s" % ("link" if kind == "link" else "node", field, f"{n:,}"))
        text = ("Tagged: " + " · ".join(parts)) if parts else \
            "Pick the HyDRA link and node layers to see the tags."
        if any(x.startswith("link dta_micro") and not x.endswith(": 0") for x in parts) \
                and not self.checkBox_Micro.isChecked():
            text += "\nMicro corridor is off: dta_micro links run as macro/meso until it is checked."
        self.label_TagCounts.setText(text + ("\n" + note if note else ""))

    def _sync_micro_outer(self, *_a):
        """Outer loops only matter for twoway_full coupling."""
        on = self.checkBox_Micro.isChecked() and self._coupling() == "twoway_full"
        self.spinBox_MicroOuter.setEnabled(on)
        self.label_microOuter.setEnabled(on)

    def _build_visualizer(self, out_dir, link_path):
        """Visualizer layers for this run (Meso Segments / Micro Lanes), added
        to the map. Returns a note for the completion message."""
        import importlib.util
        path = os.path.join(os.path.dirname(__file__), "Apps", "Visualizer",
                            "build_resolution_gpkg.py")
        spec = importlib.util.spec_from_file_location("tsm_visualizer_builder", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        do_meso = os.path.exists(os.path.join(out_dir, "meso_segment_log.csv"))
        do_micro = os.path.exists(os.path.join(out_dir, "micro_lane_performance.csv"))
        # Network micro: movement / intersection LOS on the GMNS geometry.
        los_note = ""
        if os.path.exists(os.path.join(out_dir, "micro_movement_performance.csv")):
            from . import gmns_tools
            gp = gmns_tools.build_micro_los(self.lineEdit_GmnsFile.text().strip(), out_dir)
            if gp:
                los_note = ", " + ", ".join(gmns_tools.load_micro_los(gp))
        if not (do_meso or do_micro):
            return ("\nVisualizer layers: " + los_note[2:]) if los_note else \
                "\nVisualizer: nothing to build (turn on the Segment log or a micro corridor)."
        res = mod.build(link_path, out_dir, out_dir=os.path.join(out_dir, "visualizer"),
                        hours="8,17,18", do_meso=do_meso, do_micro=do_micro)
        from qgis.core import QgsVectorLayer
        added = []
        for name, key in (("Meso Segments", "meso"), ("Micro Lanes", "micro")):
            p = (res or {}).get(key)
            if p and os.path.exists(p):
                lyr = QgsVectorLayer(p, name, "ogr")
                if lyr.isValid():
                    QgsProject.instance().addMapLayer(lyr)
                    added.append(name)
        return "\nVisualizer layers: %s%s" % (", ".join(added) or "none built", los_note)

    def _write_odme_ctl(self, f):
        """Counts, ODME and supplemental-demand keys. Every ODME key is written
        explicitly when ODME is on, so the control file documents the run."""
        counts = self.lineEdit_CountFile.text().strip()
        if counts:
            f.write(f"TIME_COUNT_FILE       {counts}\n")
        if self.checkBox_Odme.isChecked():
            if not counts:
                raise ValueError("ODME is checked but no count file is set "
                                 "(Counts / ODME tab).")
            lo, hi = _pair(self.lineEdit_OdmeBounds.text(), "0.5", "2.0")
            min_model, clip = _pair(self.lineEdit_OdmeModelClip.text(), "1", "10")
            f.write("ODME                  YES\n")
            f.write(f"ODME_MODE             {ODME_MODES.get(self.comboBox_OdmeMode.currentText(), 'GROW')}\n")
            f.write(f"ODME_ROUNDS           {self.lineEdit_OdmeRounds.text().strip() or '2'}\n")
            f.write(f"ODME_REASSIGN_ITERS   {self.lineEdit_OdmeReassign.text().strip() or '3'}\n")
            f.write(f"ODME_PASSES           {self.lineEdit_OdmePasses.text().strip() or '5'}\n")
            f.write(f"ODME_ALPHA            {self.lineEdit_OdmeAlpha.text().strip() or '0.5'}\n")
            f.write(f"ODME_MAX_STEP         {self.lineEdit_OdmeMaxStep.text().strip() or '0.25'}\n")
            f.write(f"ODME_BOUND_LO         {lo}\n")
            f.write(f"ODME_BOUND_HI         {hi}\n")
            f.write(f"ODME_MIN_IMPORTANCE   {self.lineEdit_OdmeMinImportance.text().strip() or '0'}\n")
            f.write(f"ODME_MIN_MODEL        {min_model}\n")
            f.write(f"ODME_RATIO_CLIP       {clip}\n")
        supp = self.lineEdit_SuppFile.text().strip()
        if supp:
            f.write(f"SUPPLEMENT_TRIP_FILE  {supp}\n")
            f.write(f"SUPPLEMENT_SCALE      {self.lineEdit_SuppScale.text().strip() or '1.0'}\n")
            growth = self.lineEdit_SuppGrowth.text().strip()
            if growth:
                f.write(f"SUPPLEMENT_GROWTH_FILE {growth}\n")

    def select_file(self, line_edit, file_filter):
        path, _ = QFileDialog.getOpenFileName(self, "Select File", "", file_filter + ";; All Files (*)")
        if path:
            line_edit.setText(path)

    def _browse_out_dir(self):
        settings = Config()
        start = self.lineEdit_OutDir.text().strip() or settings.get("scenarioDir") or ""
        path = QFileDialog.getExistingDirectory(self, "Select HyDRA output directory", start)
        if path:
            self.lineEdit_OutDir.setText(path)

    @staticmethod
    def _hydra_layer(settings, kind):
        """HyDRA's link/node layer name: the saved HyDRA pick, else the
        scenario's assignment network (MSR outputs for an MSR scenario)."""
        _lf, _nf, d_link, d_node = settings.assignment_network()
        default = d_link if kind == "link" else d_node
        saved = settings.get(f"hydra_{kind}_layer_name") or ""
        tsm = settings.get(f"{kind}_layer_name") or ""
        msr = settings.get(f"msr_{kind}_layer_name") or ""
        if settings.is_msr() and saved and saved == tsm and default and default != tsm:
            return default          # a TSM pick from before the scenario went MSR
        if not settings.is_msr() and saved and msr and saved == msr:
            return default          # an MSR pick from before the scenario went TSM
        return saved or default

    @staticmethod
    def _hydra_trip_file(settings):
        """HyDRA's trip list: the saved one, else the MSR trip list for an MSR
        scenario or the agentPlans trip list -- never the interim TSM list in
        an MSR scenario."""
        msr = settings.get("msr_triplist_file") or ""
        tsm = settings.get("triplist_file") or ""
        saved = settings.get("hydra_trip_file") or ""
        if settings.is_msr():
            if (not saved or saved == tsm) and msr:
                return msr
            return saved
        if saved and saved == msr:
            return tsm or saved     # the MSR list belongs to an MSR scenario
        return saved or tsm

    def _resolve_out_dir(self, settings):
        """User's output directory, defaulting to the scenario directory when
        blank (the panel-wide convention). Created if it does not exist."""
        out_dir = (self.lineEdit_OutDir.text().strip()
                   or settings.get("scenarioDir") or "").replace("\\", "/")
        if out_dir and not os.path.isdir(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError:
                pass
        return out_dir

    def populate_layer_combobox(self, combobox, geom_type):
        combobox.clear()
        combobox.addItem("Select a layer", None)
        for layer in [l for l in QgsProject.instance().mapLayers().values() if hasattr(l, "geometryType")]:
            if layer.geometryType() == {"Point": 0, "LineString": 1, "Polygon": 2}[geom_type]:
                combobox.addItem(layer.name(), layer)

    def get_layer_path(self, layer):
        if layer is None:
            return None
        return layer.dataProvider().dataSourceUri().split("|")[0]

    def _select_combo(self, combo, text):
        if text and text in [combo.itemText(i) for i in range(combo.count())]:
            combo.setCurrentText(text)

    def update_settings(self, notify=True, engine=None):
        """Persist the dialog to the scenario settings.

        BOTH tabs are always written: the DTA and the STA specification are
        independent and a scenario keeps whichever of them the user filled in,
        regardless of which tab happens to be on screen. Only `hydra_engine`
        records which of the two a run uses.

        notify=False is used by run_hydra, which saves before launching: a run
        must never use values that differ from what is on screen, but it should
        not pop a "settings updated" box on the way to starting.

        engine ("DTA"/"STA") overrides the saved selection. run_hydra passes the
        engine the user actually picked, so the control file and the persisted
        hydra_engine can never disagree; Save (no override) records the tab in
        front of the user.
        """
        settings = Config()
        # Which engine this scenario runs. Both tabs stay saved either way; the
        # two _configured flags say which specifications are actually filled in.
        settings.set("hydra_engine", engine or self._default_engine())
        settings.set("hydra_dta_configured", self._dta_ready())
        settings.set("hydra_sta_configured", self._sta_ready())
        # Equilibrium / run mode
        settings.set("hydra_macro", self.comboBox_Macro.currentText())
        settings.set("hydra_iters", self.lineEdit_Iters.text())
        settings.set("hydra_gap", self.lineEdit_Gap.text())
        settings.set("hydra_chunks", self.lineEdit_Chunks.text())
        settings.set("hydra_node_schedule",
                     NODE_SCHEDULES.get(self.comboBox_NodeSchedule.currentText(), "per_iter"))
        # Threads are NOT persisted here -- they come from General Configuration.
        # Inputs / outputs (blank output dir = scenario directory at run time)
        settings.set("hydra_trip_file", self.lineEdit_TripFile.text())
        settings.set("hydra_out_dir", self.lineEdit_OutDir.text().strip())
        settings.set("hydra_link_layer_name", self.comboBox_LinkLayer.currentText())
        settings.set("hydra_node_layer_name", self.comboBox_NodeLayer.currentText())
        # Meso / Micro
        settings.set("hydra_meso_ftypes", self.lineEdit_MesoFtypes.text())
        settings.set("hydra_micro_enabled", self.checkBox_Micro.isChecked())
        settings.set("hydra_micro_ftypes", self.lineEdit_MicroFtypes.text())
        settings.set("hydra_coupling", self._coupling())
        settings.set("hydra_micro_choice", self.comboBox_MicroChoice.currentText())
        settings.set("hydra_toll_policy", self.lineEdit_TollPolicy.text())
        # Generalized cost + advanced (afdta) tuning
        settings.set("hydra_segment_params", self.lineEdit_SegParams.text())
        settings.set("hydra_reroute_fraction", self.lineEdit_RerouteFraction.text())
        settings.set("hydra_reroute_threshold", self.lineEdit_RerouteThreshold.text())
        settings.set("hydra_ltm_spillback", self.lineEdit_LtmSpillback.text())
        settings.set("hydra_jam_density", self.lineEdit_JamDensity.text())
        settings.set("hydra_max_trips", self.lineEdit_MaxTrips.text())
        settings.set("hydra_sample_every", self.lineEdit_SampleEvery.text())
        settings.set("hydra_sample_mode", self.comboBox_SampleSchedule.currentText())
        settings.set("hydra_sample_schedule", self.lineEdit_SampleSchedule.text())
        settings.set("hydra_checkpoint", self.checkBox_Checkpoint.isChecked())
        settings.set("hydra_checkpoint_every", self.lineEdit_CheckpointEvery.text())
        settings.set("hydra_inject_res", str(self.spinBox_InjectRes.value()))
        for attr, key, kind in P1_FIELDS:
            w = getattr(self, attr)
            settings.set(key, w.isChecked() if kind == "check" else
                         w.text().strip() if kind == "text" else
                         w.currentText() if kind == "combo" else str(w.value()))
        settings.set("hydra_depart_slot", self.comboBox_DepartSlot.currentText())
        area = self.comboBox_MicroArea.currentText()
        settings.set("hydra_micro_area", "" if area == "(none)" else area)
        for p, key in (("", "hydra"), ("Sta", "hydra_sta")):
            w = self._resume_w(p)
            settings.set(f"{key}_resume", w["check"].isChecked())
            settings.set(f"{key}_resume_file", w["file"].text().strip())
            settings.set(f"{key}_resume_mode", w["mode"].currentText())
            settings.set(f"{key}_resume_more", w["more"].text().strip())
        # Output toggles
        settings.set("hydra_agent_plans", self.checkBox_AgentPlans.isChecked())
        settings.set("hydra_agent_paths", self.checkBox_AgentPaths.isChecked())
        settings.set("hydra_load_refresh", self.comboBox_LoadRefresh.currentText())
        settings.set("hydra_load_schedule", self.lineEdit_LoadSchedule.text().strip())
        # Counts / ODME / supplemental demand
        settings.set("hydra_count_file", self.lineEdit_CountFile.text().strip())
        settings.set("hydra_odme", self.checkBox_Odme.isChecked())
        settings.set("hydra_odme_mode", self.comboBox_OdmeMode.currentText())
        for attr, key in ODME_FIELDS:
            settings.set(key, getattr(self, attr).text().strip())
        settings.set("hydra_supp_file", self.lineEdit_SuppFile.text().strip())
        settings.set("hydra_supp_scale", self.lineEdit_SuppScale.text().strip())
        settings.set("hydra_supp_growth", self.lineEdit_SuppGrowth.text().strip())
        # ---- STA tab ----
        settings.set("hydra_sta_method", self.comboBox_StaMethod.currentText())
        settings.set("hydra_bpr_period", self.comboBox_BprPeriod.currentText())
        settings.set("hydra_sta_vdf", self.comboBox_StaVdf.currentText())
        settings.set("hydra_conical_alpha", self.lineEdit_ConicalAlpha.text())
        settings.set("hydra_akcelik_ja", self.lineEdit_AkcelikJa.text())
        settings.set("hydra_bpr_overcap", self.checkBox_BprOverCap.isChecked())
        settings.set("hydra_bpr_beta_mult", self.lineEdit_BprBetaMult.text())
        settings.set("hydra_sta_iters", self.lineEdit_StaIters.text())
        settings.set("hydra_sta_gap", self.lineEdit_StaGap.text())
        settings.set("hydra_sta_threads", self.lineEdit_StaThreads.text())
        settings.set("hydra_sta_max_trips", self.lineEdit_StaMaxTrips.text())
        settings.set("hydra_sta_sample_every", self.lineEdit_StaSampleEvery.text())
        settings.set("hydra_sta_sample_mode", self.comboBox_StaSampleSchedule.currentText())
        settings.set("hydra_sta_sample_schedule", self.lineEdit_StaSampleSchedule.text())
        settings.set("hydra_sta_checkpoint", self.checkBox_StaCheckpoint.isChecked())
        settings.set("hydra_sta_checkpoint_every", self.lineEdit_StaCheckpointEvery.text())
        settings.set("hydra_sta_agent_plans", self.checkBox_StaAgentPlans.isChecked())
        settings.set("hydra_sta_agent_paths", self.checkBox_StaAgentPaths.isChecked())
        settings.set("hydra_sta_path_scale", self.checkBox_StaPathScale.isChecked())
        settings.check_and_save_to_file("scenario_settings_file")
        if notify:
            QMessageBox.information(self, "Settings Saved",
                                    "HyDRA settings saved. The dialog stays open -- "
                                    "use Cancel to close.")

    # ------------------------------------------------------------------
    @closes_run_console
    def run_hydra(self, show_message=False):
        settings = Config()
        # Which engine runs is decided FIRST, and explicitly -- never inferred
        # from whichever tab happens to be visible. A full run never stops to
        # ask: it uses the engine the scenario was saved with.
        if settings.full_run_active():
            engine = (settings.get("hydra_engine") or "").upper()
            if engine not in ("DTA", "STA"):
                engine = self._default_engine()
        else:
            engine = self._choose_engine()
            if engine is None:
                return False
        # Save next, always: a run must use exactly what is on screen, and both
        # tab specifications are persisted along with the engine just chosen.
        # Silent, so starting a run does not require dismissing a dialog.
        self.update_settings(notify=False, engine=engine)
        tsm_location = settings.get("tsm_location")

        link_layer = self.comboBox_LinkLayer.currentData()
        node_layer = self.comboBox_NodeLayer.currentData()
        # Network input: dialog dropdown when standalone; in a full run (or when
        # nothing is picked) chain off the Link Consolidator outputs.
        sel_link = self.get_layer_path(link_layer) if link_layer else ""
        sel_node = self.get_layer_path(node_layer) if node_layer else ""
        link_path, node_path = settings.resolve_network_paths(sel_link, sel_node, assignment=True)
        trip_file = self.lineEdit_TripFile.text().strip()
        out_dir = self._resolve_out_dir(settings)
        if not (link_path and node_path and trip_file and out_dir):
            QMessageBox.critical(self, "Error", "Need a Link network, Node network, and Trip list. Pick the layers here, or run Link Consolidation first (output goes to the scenario directory).")
            return False
        # One live-tail window for the whole Hydra run (no per-step black windows).
        begin_run_console(os.path.join(out_dir, "Hydra.log"), "AgentFlow / Hydra - run log")

        sta = (engine == "STA")
        if sta:
            # Static assignment: one flow model, and none of the DTA physics
            # controls apply (see _write_sta_ctl).
            macro_model, meso, signals = "STA_BPR", "", False
        else:
            macro = self.comboBox_Macro.currentText()
            macro_model, _, signals = MACRO_PRESETS.get(macro, _DEFAULT_PRESET)
            meso = self.lineEdit_MesoFtypes.text().strip()
        toll_policy = self.lineEdit_TollPolicy.text().strip()

        afdta = settings.app_exe("Hydra/afdta.exe")
        if not os.path.exists(afdta):
            QMessageBox.critical(self, "Error", f"afdta.exe not found at: {afdta}")
            return False

        # Convert the GeoPackage link/node layers to CSV (gpkgcsv.exe), then run.
        gpkgcsv = settings.app_exe("utilities/gpkgcsv.exe")
        if not os.path.exists(gpkgcsv):
            QMessageBox.critical(self, "Error", f"gpkgcsv.exe not found at: {gpkgcsv}")
            return False
        link_csv = os.path.join(out_dir, "Link_hydra.csv")
        node_csv = os.path.join(out_dir, "Node_hydra.csv")
        convert_log = os.path.join(out_dir, "Hydra_convert.log")
        try:
            for i, (src, dst, label) in enumerate(((link_path, link_csv, "link"), (node_path, node_csv, "node"))):
                r = Config().run_app([gpkgcsv, "to-csv", src, dst, "--drop-geom"],
                                     log_path=convert_log, console=True, append=(i > 0))
                if r.returncode != 0 or not os.path.exists(dst):
                    QMessageBox.critical(self, "Error", f"Failed to convert {label} layer to CSV.")
                    return False
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error converting layers to CSV: {e}")
            return False

        # GMNS package -> <output>/gmns/gmns_<table>.csv for afdta (GMNS_DIR);
        # always for the network micro, which is built from it.
        self._gmns_dir = None
        net_micro = self.checkBox_Micro.isChecked() and self._micro_network()
        if not sta and (self.checkBox_UseGmns.isChecked() or net_micro):
            from . import gmns_tools
            gmns = self.lineEdit_GmnsFile.text().strip()
            if not gmns or not os.path.exists(gmns):
                QMessageBox.critical(self, "Error", f"GMNS package not found: {gmns}")
                return False
            try:
                self._gmns_dir = gmns_tools.export_csv(
                    gmns, os.path.join(out_dir, "gmns"), gpkgcsv,
                    lambda args: Config().run_app(args, log_path=convert_log, console=True, append=True))
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not export the GMNS package: {e}")
                return False

        ctl = os.path.join(out_dir, "hydra_run.ctl")
        if sta:
            if not self._write_sta_ctl(ctl, node_csv, link_csv, trip_file, out_dir,
                                       toll_policy):
                return False
            return self._launch_afdta(afdta, ctl, out_dir, link_path, show_message,
                                      label="HyDRA (AgentFlow-STA)")
        try:
            with open(ctl, "w") as f:
                f.write("# AgentFlow DTA control - generated by the HyDRA dialog\n")
                f.write(f"NODE_FILE              {node_csv}\n")
                f.write(f"LINK_FILE              {link_csv}\n")
                f.write(f"TRIP_FILE             {trip_file}\n")
                # The MSR trip list carries TSM_O/TSM_D, which afdta's AUTO
                # takes for a cut-out subarea and switches county-scope
                # masking off; the MSR network is statewide, so keep it on.
                msr_file = settings.get("MSR_Link_File") or ""
                if settings.is_msr() and msr_file and \
                        os.path.normcase(os.path.abspath(link_path)) == os.path.normcase(os.path.abspath(msr_file)):
                    f.write("SCOPE_MASKING         YES\n")
                f.write(f"OUTPUT_DIRECTORY      {out_dir}\n")
                f.write(f"MACRO_MODEL           {macro_model}\n")
                f.write(f"MAX_ITERATIONS        {self._max_iters_value('')}\n")
                f.write(f"RELATIVE_GAP          {self.lineEdit_Gap.text().strip() or '0.01'}\n")
                f.write(f"ROUTE_CHUNKS          {self.lineEdit_Chunks.text().strip() or '10'}\n")
                # Node-DNL refresh stride (per_iter / per_chunk / hybrid ramp).
                # Only the DTA_Node* loaders run the node sim, but the key is
                # harmless for the others.
                f.write(f"NODE_SCHEDULE         {self._node_schedule_value()}\n")
                # Within-slot loading resolution of the node loaders, and the
                # route-key departure slot (AUTO follows the trip list's grid).
                f.write(f"NODE_INJECT_RES       {self.spinBox_InjectRes.value()}\n")
                f.write(f"DEPART_SLOT_MIN       {DEPART_SLOTS.get(self.comboBox_DepartSlot.currentText(), 'AUTO')}\n")
                # The per-link PointQueue loader's refresh (the node loaders
                # use NODE_SCHEDULE above and ignore these).
                if macro_model == "DTA_PointQueue":
                    f.write(f"LOAD_REFRESH          {LOAD_REFRESH.get(self.comboBox_LoadRefresh.currentText(), 'exact')}\n")
                    load_sched = self.lineEdit_LoadSchedule.text().strip()
                    if load_sched:
                        f.write(f"LOAD_SCHEDULE         {load_sched}\n")
                f.write(f"THREADS               {self.lineEdit_Threads.text().strip() or '0'}\n")
                # Per-purpose volume columns in every link_performance_
                # <Macro|Meso|Micro>DTA.csv (vol_<purpose> sums to volume).
                # Purpose inline in link_performance; each ticked extra goes to
                # its own link_volume_by_<kind>.csv (Summarization > Link Performance).
                extra = [k for box, k in ((self.checkBox_BdMarket, "Market"),
                                          (self.checkBox_BdSegment, "Segment"),
                                          (self.checkBox_BdVotBin, "VotBin"))
                         if box.isChecked()]
                f.write("LINK_VOLUME_BREAKDOWN %s\n" % ", ".join(["Purpose"] + extra))
                if self.checkBox_BdVotBin.isChecked():
                    f.write(f"VOT_BIN_EDGES         {self.lineEdit_VotEdges.text().strip() or '10,20,40,80'}\n")
                if meso:
                    f.write(f"MESO_FTYPE            {meso}\n")
                    # Anti-gridlock breaker -- MESO ONLY, so these keys are
                    # written inside the `if meso` block and never appear in a
                    # macro-only control file.
                    #
                    # The engine defaults are meso_breaker_rate=0 ("legacy") and
                    # meso_max_spillback_min=20, which together drain a
                    # deadlocked movement at ONE packet (<=3 veh) per 20 min =
                    # ~9 veh/hour. That cannot dissolve interchange rings: meso
                    # gridlocked by ~11am, reported 0.0-0.4% of daily volume per
                    # hour for the rest of the day, held 18.2% of freeway demand
                    # out of the network entirely, and diverted the rest onto
                    # arterials -- limited access scored ratio 0.588 / R2 0.060.
                    #
                    # Rate mode drains a timed-out movement at rate*capacity per
                    # step; cap_credit still gates every release so the forced
                    # rate can NEVER exceed link capacity (values >1.0 buy
                    # nothing). With rate 1.0 + a 5-minute timeout, measured on
                    # New_landuse: backlog 18.2% -> 5.1%, limited access
                    # 0.588/0.060 -> 0.862/0.253, tolls 0.617 -> 1.160, ramps
                    # 0.796 -> 1.106, statewide R2 0.353 -> 0.544, rel_gap
                    # 0.1038 -> 0.0827.
                    brk = (settings.get("hydra_meso_breaker_rate") or "1.0").strip()
                    spb = (settings.get("hydra_meso_spillback_min") or "5").strip()
                    if brk.lower() != "off":
                        f.write(f"MESO_BREAKER_RATE     {brk}\n")
                    if spb.lower() != "off":
                        f.write(f"MESO_MAX_SPILLBACK_MIN {spb}\n")
                if signals or self.checkBox_Signals.isChecked():
                    f.write("SIGNAL_MODEL          YES\n")
                    f.write(f"SIGNAL_SAT_FLOW       {self.lineEdit_SigSat.text().strip() or '1800'}\n")
                    f.write(f"SIGNAL_CYCLE          {self.lineEdit_SigCycle.text().strip() or '120'}\n")
                    f.write(f"SIGNAL_GC             {self.lineEdit_SigGc.text().strip() or '0.45'}\n")
                    for pair in self.lineEdit_SigGcFt.text().split(","):
                        ft, _, gc = pair.partition(":")
                        if ft.strip() and gc.strip():
                            f.write(f"SIGNAL_GC_{ft.strip():<12}{gc.strip()}\n")
                if self._gmns_dir:
                    f.write(f"GMNS_DIR              {self._gmns_dir}\n")
                # Meso time step and diagnostics (read only where meso runs).
                f.write(f"MESO_DT_SEC           {self.spinBox_MesoDt.value()}\n")
                for box, key in ((self.checkBox_MesoIntervalLog, "MESO_INTERVAL_LOG"),
                                 (self.checkBox_MesoMovementLog, "MESO_MOVEMENT_LOG"),
                                 (self.checkBox_MesoSegmentLog, "MESO_SEGMENT_LOG")):
                    if box.isChecked():
                        f.write(f"{key:<22}YES\n")
                if self.checkBox_MesoSegmentLog.isChecked():
                    seg_file = self.lineEdit_SegFile.text().strip()
                    if seg_file:
                        f.write(f"MESO_SEGMENT_FILE     {seg_file}\n")
                    else:
                        f.write(f"MESO_SEGMENT_LEN      {self.doubleSpinBox_SegLen.value():g}\n")
                if toll_policy:
                    f.write(f"TOLL_POLICY_FILE      {toll_policy}\n")
                # Generalized-cost segment params (beta_time/beta_cost/distance per
                # market segment). Without it afdta falls back to time-only GC.
                seg_params = self.lineEdit_SegParams.text().strip()
                if seg_params:
                    f.write(f"SEGMENT_PARAM_FILE    {seg_params}\n")
                # Rerouting controls
                f.write(f"REROUTE_FRACTION_MIN  {self.lineEdit_RerouteFraction.text().strip() or '0.05'}\n")
                f.write(f"REROUTE_THRESHOLD_MIN {self.lineEdit_RerouteThreshold.text().strip() or '0.01'}\n")
                # LTM / spillback (used by the LTM macro models)
                f.write(f"LTM_MAX_SPILLBACK_MIN {self.lineEdit_LtmSpillback.text().strip() or '20'}\n")
                f.write(f"JAM_DENSITY           {self.lineEdit_JamDensity.text().strip() or '240'}\n")
                # Discharge calibration: QLOS planning capacities (LOS-E service
                # volumes) under-state physical discharge in a hard-capacity DNL;
                # the calibrated per-FTYPE scale-ups from the assignment of record
                # are written by DEFAULT (omitting them collapses freeway loading
                # -- limited-access ratio 0.58 vs 1.06 calibrated). Override via
                # the hydra_discharge_factors setting ("ft:factor,ft:factor,...";
                # "off" suppresses the block entirely).
                df_setting = (settings.get("hydra_discharge_factors") or "").strip()
                if df_setting.lower() != "off":
                    factors = df_setting or ("11:1.15,21:1.15,31:1.15,41:1.15,"
                                             "45:1.15,48:1.15,71:1.2,91:1.15,"
                                             "93:1.15,94:1.15")
                    for pair in factors.split(","):
                        ft, _, val = pair.partition(":")
                        if ft.strip() and val.strip():
                            f.write(f"DISCHARGE_FACTOR_{ft.strip()}  {val.strip()}\n")
                # Sampling / limits
                f.write(f"MAX_TRIPS             {self.lineEdit_MaxTrips.text().strip() or '0'}\n")
                f.write(f"SAMPLE_EVERY          {self.lineEdit_SampleEvery.text().strip() or '1'}\n")
                # Coarse-to-fine sampling; omitted entirely = every iteration at
                # 100%. Progressive is the default: ~30% less wall time for the
                # same converged result.
                sample_sched = self._sample_schedule_value()
                if sample_sched:
                    f.write(f"SAMPLE_SCHEDULE       {sample_sched}\n")
                # Checkpoint: lets a later run warm-start via RESUME_FROM (2-3
                # iterations instead of a full cold run) and lets outputs be
                # re-scored straight from the checkpoint without re-assigning.
                if self.checkBox_Checkpoint.isChecked():
                    ckpt = os.path.join(out_dir, "checkpoint.bin").replace("\\", "/")
                    f.write(f"CHECKPOINT_FILE       {ckpt}\n")
                    f.write(f"CHECKPOINT_EVERY      {self.lineEdit_CheckpointEvery.text().strip() or '3'}\n")
                if not self._write_resume_ctl(f, "", 11):
                    return False
                if self.checkBox_Micro.isChecked():
                    micro_ft = self.lineEdit_MicroFtypes.text().strip()
                    f.write("MICRO_CORRIDOR        YES\n")
                    if micro_ft:
                        f.write(f"MICRO_FTYPE           {micro_ft}\n")
                    f.write(f"MICRO_COUPLING        {self._coupling()}\n")
                    if self._micro_network():
                        f.write("MICRO_MODEL           network\n")
                        f.write(f"MICRO_CROSS_STREETS   {'YES' if self.checkBox_MicroCross.isChecked() else 'NO'}\n")
                        area_id = self.comboBox_MicroArea.currentData()
                        area = QgsProject.instance().mapLayer(area_id) if area_id else None
                        links = self.comboBox_LinkLayer.currentData()
                        if area is not None and links is not None:
                            from . import gmns_tools
                            area_csv = os.path.join(out_dir, "micro_area_links.csv").replace("\\", "/")
                            n = gmns_tools.micro_area_links(area, links, area_csv)
                            print(f"micro area: {n} links inside {area.name()}")
                            f.write(f"MICRO_AREA_LINKS      {area_csv}\n")
                    if self._coupling() == "twoway_full":
                        f.write(f"MICRO_OUTER           {self.spinBox_MicroOuter.value()}\n")
                    f.write(f"MICRO_DT_SEC          {self.comboBox_MicroDt.currentText().split()[0]}\n")
                    f.write(f"MICRO_PROBE_STRIDE    {self.spinBox_ProbeStride.value()}\n")
                    # EL/GP choice inside the micro corridor: meso logit vs micro
                    # time-differential converted by each agent's VOT.
                    if self.comboBox_MicroChoice.currentText().startswith("Meso"):
                        f.write("MICRO_CHOICE          MODEA\n")
                    else:
                        f.write("MICRO_CHOICE          ENDOGENOUS\n")
                # Link performance (macro/meso/micro) is always written by the engine.
                # Two independent agent artifacts, both default ON:
                #   Agent plans -> agentPlans_out.csv (light per-agent summary)
                #   Agent paths -> agentPaths.duckdb (heavy: full key paths;
                #                  feeds agentAnalysis select-link/trace/tiers)
                f.write(f"WRITE_AGENT_PLANS     {'YES' if self.checkBox_AgentPlans.isChecked() else 'NO'}\n")
                f.write(f"WRITE_AGENT_PATHS     {'YES' if self.checkBox_AgentPaths.isChecked() else 'NO'}\n")
                self._write_odme_ctl(f)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error writing hydra_run.ctl: {e}")
            return False

        # A new run rewrites agentPaths.duckdb, so any existing sidecar link
        # index (agentPaths_index.duckdb) would describe the OLD paths. Delete
        # it here -- the authoritative place to know the pairing is broken (a
        # timestamp check can't: the index may legitimately be built later).
        # Agent Analysis offers to rebuild it on demand, so nothing is lost.
        if self._agent_paths_on(sta):
            stale_idx = os.path.join(out_dir, "agentPaths_index.duckdb")
            if os.path.exists(stale_idx):
                try:
                    os.remove(stale_idx)
                    print(f"removed stale link index (new run rewrites agentPaths.duckdb): {stale_idx}")
                except OSError as e:
                    QMessageBox.warning(self, "Stale link index",
                                        "Could not delete the old agentPaths_index.duckdb "
                                        "(in use?). Delete it before running Agent Analysis "
                                        "on the new results:\n%s" % e)

        # Same launch path as STA, so both engines behave identically from here
        # (run, summarize, close the run-log window, then report).
        return self._launch_afdta(afdta, ctl, out_dir, link_path, show_message,
                                  label="HyDRA (AgentFlow-DTA)")

    # ------------------------------------------------------------------
    def _write_sta_ctl(self, ctl, node_csv, link_csv, trip_file, out_dir, toll_policy):
        """Control file for a STATIC BPR assignment.

        Deliberately short. Everything the DTA writer emits for the loading
        physics is absent because a static assignment ignores it, and writing
        keys the engine ignores would imply they had an effect:

          ROUTE_CHUNKS        all-or-nothing routes the whole demand against one
                              frozen cost field; there is nothing to load
                              incrementally (afdta warns if it is present)
          DISCHARGE_FACTOR_*  BPR divides by the STATED CAPACITY x NLANES, so
                              the calibrated discharge rate is never read
          MESO_*, MICRO_*     unsupported under a static assignment
          NODE_*, LTM_*, JAM  no node model and no spatial queue exist
          REROUTE_*           the flow-space solver averages flows, not paths
        """
        settings = Config()
        try:
            with open(ctl, "w") as f:
                f.write("# AgentFlow STA (static BPR) control - generated by the HyDRA dialog\n")
                f.write(f"NODE_FILE              {node_csv}\n")
                f.write(f"LINK_FILE              {link_csv}\n")
                f.write(f"TRIP_FILE              {trip_file}\n")
                f.write(f"OUTPUT_DIRECTORY       {out_dir}\n")
                f.write("MACRO_MODEL            STA_BPR\n")
                method = STA_METHODS.get(self.comboBox_StaMethod.currentText(), "bfw")
                f.write(f"STA_METHOD             {method}\n")
                period = BPR_PERIODS.get(self.comboBox_BprPeriod.currentText(), "60")
                f.write(f"BPR_PERIOD_MIN         {period}\n")
                # Volume-delay curve. Only the chosen curve's parameter is
                # written -- afdta would accept the others, but a control file
                # carrying a conical alpha on a BPR run reads as if it mattered.
                vdf = STA_VDFS.get(self.comboBox_StaVdf.currentText(), "bpr")
                f.write(f"STA_VDF                {vdf}\n")
                if vdf == "conical":
                    f.write("CONICAL_ALPHA          %s\n"
                            % (self.lineEdit_ConicalAlpha.text().strip() or "4.0"))
                elif vdf == "akcelik":
                    f.write("AKCELIK_JA             %s\n"
                            % (self.lineEdit_AkcelikJa.text().strip() or "0.1"))
                elif self.checkBox_BprOverCap.isChecked():
                    f.write("BPR_OVERCAP_BETA_MULT  %s\n"
                            % (self.lineEdit_BprBetaMult.text().strip() or "1.5"))
                f.write(f"MAX_ITERATIONS         {self._max_iters_value('Sta')}\n")
                f.write(f"RELATIVE_GAP           {self.lineEdit_StaGap.text().strip() or '0.01'}\n")
                f.write(f"THREADS                {self.lineEdit_StaThreads.text().strip() or '0'}\n")
                f.write("LINK_VOLUME_BREAKDOWN  Purpose\n")
                # Impedance is shared with the DTA tab (same scenario inputs).
                if toll_policy:
                    f.write(f"TOLL_POLICY_FILE       {toll_policy}\n")
                seg_params = self.lineEdit_SegParams.text().strip()
                if seg_params:
                    f.write(f"SEGMENT_PARAM_FILE     {seg_params}\n")
                f.write(f"MAX_TRIPS              {self.lineEdit_StaMaxTrips.text().strip() or '0'}\n")
                f.write(f"SAMPLE_EVERY           {self.lineEdit_StaSampleEvery.text().strip() or '1'}\n")
                sched = self._sample_schedule_value(
                    self.comboBox_StaSampleSchedule, self.lineEdit_StaSampleSchedule,
                    self.lineEdit_StaIters)
                if sched:
                    f.write(f"SAMPLE_SCHEDULE        {sched}\n")
                if self.checkBox_StaCheckpoint.isChecked():
                    ckpt = os.path.join(out_dir, "checkpoint.bin").replace("\\", "/")
                    f.write(f"CHECKPOINT_FILE        {ckpt}\n")
                    f.write(f"CHECKPOINT_EVERY       {self.lineEdit_StaCheckpointEvery.text().strip() or '3'}\n")
                if not self._write_resume_ctl(f, "Sta", 12):
                    return False
                f.write(f"WRITE_AGENT_PLANS      {'YES' if self.checkBox_StaAgentPlans.isChecked() else 'NO'}\n")
                f.write(f"WRITE_AGENT_PATHS      {'YES' if self.checkBox_StaAgentPaths.isChecked() else 'NO'}\n")
                if not self.checkBox_StaPathScale.isChecked():
                    f.write("STA_PATH_SCALE         NO\n")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error writing the STA control file: {e}")
            return False
        return True

    # ------------------------------------------------------------------
    def _launch_afdta(self, afdta, ctl, out_dir, link_path, show_message,
                      label="HyDRA (AgentFlow-DTA)"):
        """Run afdta on a written control file and summarise the loaded network.
        Shared by the DTA and STA paths so both behave identically from here.

        The live-tail run-log window is closed HERE, before any completion or
        failure box, instead of being left to the @closes_run_console decorator
        on the way out: the decorator only fires once the modal box has been
        dismissed, so the black window sat on screen for exactly as long as the
        "HyDRA completed" dialog did -- which reads as a window that never
        closes. Closing it twice is harmless (end_run_console is idempotent).
        """
        hydra_log = os.path.join(out_dir, "Hydra.log")
        print(f"afdta   : {afdta}")
        print(f"control : {ctl}")
        print(f"log     : {hydra_log}")
        if not run_gated_model(self, [afdta, "--control", ctl], label,
                               log_path=hydra_log, console=True):
            end_run_console()
            return False
        loaded_note = ""
        pkg = os.path.join(out_dir, "micro_package")
        if os.path.exists(os.path.join(pkg, "micro_package.ctl")):
            # The editable copy goes in the package now, while the statewide
            # GMNS package the run used is at hand: the package stands alone.
            from . import gmns_tools
            src = self.lineEdit_GmnsFile.text().strip()
            try:
                if src and os.path.exists(src):
                    gmns_tools.build_package_gpkg(src, pkg)
            except Exception as e:
                loaded_note += "\n(micro_gmns.gpkg not built: %s)" % e
            self.lineEdit_MicroPkg.setText(pkg.replace("\\", "/"))
            loaded_note += "\nMicro package: %s (GMNS > Micro package reruns it alone)" % pkg
        try:
            gp = self._auto_summarize(out_dir, link_path)
            loaded_note = f"\nLoaded network: {gp}" if gp else \
                          "\n(loaded-network summary failed - see summarize_hydra_run.log)"
        except Exception as e:
            loaded_note = f"\n(loaded-network summary failed: {e})"
        if self.checkBox_BuildViz.isChecked():
            try:
                loaded_note += self._build_visualizer(out_dir, link_path)
            except Exception as e:
                loaded_note += f"\n(visualizer layers failed: {e})"
        # Every step that streams into the run log has finished -- close the
        # live-tail window now, not after the user dismisses the box below.
        end_run_console()
        if show_message:
            QMessageBox.information(self, "Success",
                                    f"{label} completed.\n\nOutputs in: {out_dir}{loaded_note}")
        return True

    def _auto_summarize(self, out_dir, link_path):
        """Post-run loaded network: summarize.exe (hydra mode) over the macro /
        meso / micro link-performance CSVs joined to the run's link layer ->
        loaded_network.gpkg (+ _daily.csv), loaded into QGIS with the standard
        symbology. Returns the gpkg path, or None."""
        from .summarize_runner import run_summary
        macro_csv = os.path.join(out_dir, "link_performance_macroDTA.csv")
        if not os.path.exists(macro_csv):
            return None
        meso_csv = os.path.join(out_dir, "link_performance_mesoDTA.csv")
        micro_csv = os.path.join(out_dir, "link_performance_microDTA.csv")
        out_gpkg = os.path.join(out_dir, "loaded_network.gpkg").replace("\\", "/")
        # Release QGIS's handle if the previous run's loaded network is open --
        # otherwise the GeoPackage rewrite fails ("already exists" lock).
        proj = QgsProject.instance()
        target = os.path.normcase(os.path.abspath(out_gpkg))
        removed = 0
        for lyr in list(proj.mapLayers().values()):
            try:
                src = lyr.source().split("|")[0]
                if os.path.normcase(os.path.abspath(src)) == target:
                    proj.removeMapLayer(lyr.id())
                    removed += 1
            except Exception:
                continue
        if removed:
            try:
                import gc
                from qgis.PyQt.QtWidgets import QApplication
                gc.collect(); QApplication.processEvents(); gc.collect()
            except Exception:
                pass
        r = run_summary("summarize_hydra.toml", link_path, macro_csv, out_gpkg,
                        subarea=False,
                        vol2=meso_csv if os.path.exists(meso_csv) else None,
                        vol3=micro_csv if os.path.exists(micro_csv) else None)
        if r.returncode != 0 or not os.path.exists(out_gpkg):
            return None
        try:
            from qgis.core import QgsVectorLayer
            lyr = QgsVectorLayer(out_gpkg, "LoadedNetwork", "ogr")
            if lyr.isValid():
                qml = os.path.join(Config().get("plugin_dir") or "",
                                   "qgis_styles/TSM_Loaded_Symbology.qml")
                if os.path.exists(qml):
                    lyr.loadNamedStyle(qml)
                QgsProject.instance().addMapLayer(lyr)
        except Exception:
            pass
        return out_gpkg
