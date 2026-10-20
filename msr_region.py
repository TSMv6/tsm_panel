"""MSR zone structure: region, boundary and the model's land use.

Project Settings > Model Resolution picks the zone structure of a run:

  Standard TSM         every TSM zone (the 26k land use aggregated to TSM_NG)
  MSR: RPM region      TSM zones outside + RPM (26k) zones inside one or more
                       regional models (the land use's Model column)
  MSR: user boundary   same, inside a user polygon layer

The region is always WHOLE TSM zones: every 26k zone the boundary overlaps
brings in its TSM zone, and every 26k zone of those TSM zones is inside. That
keeps the network (netPrep), the trips (msr) and the land use on one region.

build_zone_structure() writes, to the scenario directory:

  msr_region_zones.csv     PopSyn_Index,TSM_NG,TAZ_REG,Model,County  (MSR only)
                           -> netPrep msr_zones_file, msr subarea list
  msr_region_boundary.gpkg the region dissolved to one polygon       (MSR only)
  model_zones_landuse.gpkg the final zonal land use: one feature per model zone
                           (ZONE = TSM_NG outside / PopSyn_Index inside, RES =
                           TSM | RPM) with the SE data summed to that zone, so
                           centroids and network can be checked against it.
                           Every row carries TSM_NG and PopSyn_Index (= TSM_NG on
                           aggregated rows), the same index fields as the 26k
                           land use, so PopSyn runs on either.

Ids are taken from the land use as-is: the RPM zone id IS PopSyn_Index (the
GeoMaster RPM centroids carry the same numbers), nothing is offset in code.
"""
import csv
import os

from qgis.core import (
    QgsCoordinateTransform, QgsFeature, QgsFeatureRequest, QgsField, QgsFields,
    QgsGeometry, QgsProject, QgsVectorFileWriter, QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QMetaType

REQUIRED = ("TSM_NG", "PopSyn_Index", "Model")
REGION_CSV = "msr_region_zones.csv"
BOUNDARY_GPKG = "msr_region_boundary.gpkg"
LANDUSE_GPKG = "model_zones_landuse.gpkg"

# Not summable: carried as weighted means over the zones merged into a TSM zone.
WEIGHTED = {"Median_income_HH": "TotHH", "median_age_total": "POP"}
# Identity / label columns: never summed.
LABELS = ("fid", "TSM_NG", "TAZ_REG", "PopSyn_Index", "County", "Model", "District")


def _layer(src):
    if isinstance(src, QgsVectorLayer):
        return src
    lyr = QgsVectorLayer(str(src), "landuse", "ogr")
    if not lyr.isValid():
        raise ValueError(f"cannot open land use {src}")
    return lyr


def regional_models(landuse):
    """The regional models in the land use (its Model column), for the dropdown.
    'non-MPO' is left out: it has about one 26k zone per TSM zone, no detail."""
    lyr = _layer(landuse)
    i = lyr.fields().indexOf("Model")
    if i < 0:
        return []
    vals = {str(v) for v in lyr.uniqueValues(i) if v not in (None, "")}
    return sorted(v for v in vals if v.lower() != "non-mpo")


def output_paths(landuse_out):
    """(zonal land use, MSR boundary, MSR zones csv) named from the zonal land
    use: <dir>/<name>.gpkg -> <name>_msr_boundary.gpkg, <name>_msr_zones.csv."""
    base = os.path.splitext(str(landuse_out).replace("\\", "/"))[0]
    return base + ".gpkg", base + "_msr_boundary.gpkg", base + "_msr_zones.csv"


def zone_blocks(centroids):
    """Zone numbering read from the GeoMaster centroid layer, per `type`:
    {"TSM": (int_lo, int_hi, ext_lo, ext_hi), "RPM": (...)}. Each type's ids
    split at their largest gap -- below are the internal zones, above the
    external stations (TSM 1-8721 | 11501-11560, RPM 20001-46274 | 50001-50060),
    so nobody types these numbers and they cannot drift from the GeoMaster."""
    lyr = _layer(centroids)
    iN, iT = lyr.fields().indexOf("NODE_ID"), lyr.fields().indexOf("type")
    if iN < 0 or iT < 0:
        return {}
    ids = {}
    req = QgsFeatureRequest().setFlags(QgsFeatureRequest.Flag.NoGeometry)
    for f in lyr.getFeatures(req):
        if f[iN] not in (None, ""):
            ids.setdefault(str(f[iT]), []).append(int(f[iN]))
    out = {}
    for t, v in ids.items():
        v = sorted(set(v))
        if len(v) < 2:
            continue
        k = max(range(1, len(v)), key=lambda i: v[i] - v[i - 1])
        out[t] = (v[0], v[k - 1], v[k], v[-1])
    return out


def popsyn_range(landuse):
    """(min, max) PopSyn_Index of the land use -- the RPM zone id block netPrep
    marks as zones (rpm_zone_range). (0, 0) when the column is absent."""
    lyr = _layer(landuse)
    i = lyr.fields().indexOf("PopSyn_Index")
    if i < 0:
        return 0, 0
    return int(lyr.minimumValue(i)), int(lyr.maximumValue(i))


def _check_fields(lyr):
    missing = [f for f in REQUIRED if lyr.fields().indexOf(f) < 0]
    if missing:
        raise ValueError(f"land use {lyr.source()} is missing {', '.join(missing)}")


def region_tsm_zones(landuse, models=(), boundary=None, log=print):
    """TSM zones of the MSR region: those of the chosen regional models, plus
    every TSM zone owning a 26k zone that overlaps the boundary layer (an area
    overlap -- a shared edge alone does not count)."""
    lyr = _layer(landuse)
    _check_fields(lyr)
    tsm = set()
    models = [m for m in (models or []) if m]
    if models:
        quoted = ",".join("'" + m.replace("'", "''") + "'" for m in models)
        req = QgsFeatureRequest().setFilterExpression(f'"Model" IN ({quoted})')
        req.setFlags(QgsFeatureRequest.Flag.NoGeometry).setSubsetOfAttributes(["TSM_NG"], lyr.fields())
        n0 = len(tsm)
        for f in lyr.getFeatures(req):
            tsm.add(int(f["TSM_NG"]))
        log(f"[msr region] {', '.join(models)}: {len(tsm) - n0} TSM zones")
    if boundary is not None:
        bl = _layer(boundary)
        xf = QgsCoordinateTransform(bl.crs(), lyr.crs(), QgsProject.instance())
        geoms = []
        for f in bl.getFeatures():
            g = QgsGeometry(f.geometry())
            if g.isEmpty():
                continue
            g.transform(xf)
            geoms.append(g)
        if not geoms:
            raise ValueError(f"boundary layer {bl.name()} has no polygons")
        poly = QgsGeometry.unaryUnion(geoms)
        engine = QgsGeometry.createGeometryEngine(poly.constGet())
        engine.prepareGeometry()
        req = QgsFeatureRequest().setFilterRect(poly.boundingBox())
        req.setSubsetOfAttributes(["TSM_NG"], lyr.fields())
        n0, hit = len(tsm), set()
        for f in lyr.getFeatures(req):
            g = f.geometry()
            if engine.intersects(g.constGet()) and poly.intersection(g).area() > 0:
                hit.add(int(f["TSM_NG"]))
        tsm |= hit
        log(f"[msr region] boundary '{bl.name()}': {len(hit)} TSM zones touched "
            f"({len(tsm) - n0} new)")
    return tsm


def _sum_fields(lyr):
    """Numeric SE columns summed per model zone (labels and medians excluded)."""
    out = []
    for f in lyr.fields():
        if f.name() in LABELS or f.name() in WEIGHTED:
            continue
        if f.isNumeric():
            out.append(f.name())
    return out


def build_zone_structure(landuse, out_dir, models=(), boundary=None, log=print,
                         landuse_out=None, all_rpm=False):
    """Write the region files (MSR) and the final zonal land use for the chosen
    structure. models/boundary both empty = Standard TSM. landuse_out names the
    zonal land-use file (default <out_dir>/model_zones_landuse.gpkg). all_rpm
    (Standard TSM, PopSyn at RPM level statewide) writes every 26k zone as an
    RPM zone and no region files -- the network stays TSM. Returns a summary
    dict with the written paths and zone counts."""
    lyr = _layer(landuse)
    _check_fields(lyr)
    os.makedirs(out_dir, exist_ok=True)
    if landuse_out:
        os.makedirs(os.path.dirname(os.path.abspath(landuse_out)), exist_ok=True)
    msr = bool(models) or boundary is not None
    region = region_tsm_zones(lyr, models, boundary, log) if msr else set()
    if all_rpm and not msr:
        i = lyr.fields().indexOf("TSM_NG")
        region = {int(v) for v in lyr.uniqueValues(i) if v not in (None, "")}
    if msr and not region:
        raise ValueError("the MSR region is empty (no TSM zones selected)")

    sums = _sum_fields(lyr)
    fields = lyr.fields()
    # one pass over the 26k zones: RPM rows inside, TSM accumulators outside
    rpm_rows, tsm_acc = [], {}
    for f in lyr.getFeatures():
        t = int(f["TSM_NG"])
        if t in region:
            rpm_rows.append(f)
            continue
        a = tsm_acc.get(t)
        if a is None:
            a = tsm_acc[t] = {"geoms": [], "sum": dict.fromkeys(sums, 0.0),
                              "w": {k: [0.0, 0.0] for k in WEIGHTED},
                              "county": {}, "model": f["Model"]}
        a["geoms"].append(f.geometry())
        for k in sums:
            v = f[k]
            if v not in (None, "") and v == v:
                a["sum"][k] += float(v)
        for k, wk in WEIGHTED.items():
            if fields.indexOf(k) >= 0 and fields.indexOf(wk) >= 0:
                v, w = f[k], f[wk]
                if v not in (None, "") and w not in (None, "") and float(w) > 0:
                    a["w"][k][0] += float(v) * float(w)
                    a["w"][k][1] += float(w)
        c = f["County"] if fields.indexOf("County") >= 0 else None
        a["county"][c] = a["county"].get(c, 0) + 1

    # --- region list + boundary (MSR) ---
    region_csv = boundary_gpkg = None
    if msr:
        region_csv = (output_paths(landuse_out)[2] if landuse_out
                      else os.path.join(out_dir, REGION_CSV).replace("\\", "/"))
        with open(region_csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["PopSyn_Index", "TSM_NG", "TAZ_REG", "Model", "County"])
            for f in sorted(rpm_rows, key=lambda r: int(r["PopSyn_Index"])):
                w.writerow([int(f["PopSyn_Index"]), int(f["TSM_NG"]),
                            f["TAZ_REG"] if fields.indexOf("TAZ_REG") >= 0 else "",
                            f["Model"], f["County"] if fields.indexOf("County") >= 0 else ""])
        boundary_gpkg = (output_paths(landuse_out)[1] if landuse_out
                         else os.path.join(out_dir, BOUNDARY_GPKG).replace("\\", "/"))
        bf = QgsFields()
        for n, t in (("models", QMetaType.Type.QString), ("tsm_zones", QMetaType.Type.Int),
                     ("rpm_zones", QMetaType.Type.Int)):
            bf.append(QgsField(n, t))
        feat = QgsFeature(bf)
        feat.setGeometry(QgsGeometry.unaryUnion([f.geometry() for f in rpm_rows]))
        feat.setAttributes([", ".join(sorted({str(f["Model"]) for f in rpm_rows})),
                            len(region), len(rpm_rows)])
        _write_gpkg(boundary_gpkg, "msr_region_boundary", bf, QgsWkbTypes.Type.MultiPolygon,
                    lyr.crs(), [feat])
        log(f"[msr region] {len(region)} TSM zones -> {len(rpm_rows)} RPM zones; "
            f"wrote {region_csv} and {boundary_gpkg}")

    # --- the model's zonal land use ---
    of = QgsFields()
    for n, t in (("ZONE", QMetaType.Type.Int), ("RES", QMetaType.Type.QString),
                 ("TSM_NG", QMetaType.Type.Int), ("PopSyn_Index", QMetaType.Type.Int),
                 ("TAZ_REG", QMetaType.Type.Int), ("Model", QMetaType.Type.QString),
                 ("County", QMetaType.Type.QString)):
        of.append(QgsField(n, t))
    for k in sums:
        of.append(QgsField(k, QMetaType.Type.Double))
    for k in WEIGHTED:
        if fields.indexOf(k) >= 0:
            of.append(QgsField(k, QMetaType.Type.Double))
    out = []
    for t in sorted(tsm_acc):
        a = tsm_acc[t]
        ft = QgsFeature(of)
        ft.setGeometry(QgsGeometry.unaryUnion(a["geoms"]))
        county = max(a["county"].items(), key=lambda kv: kv[1])[0]
        # PopSyn_Index = TSM_NG on aggregated rows, so PopSyn keys on
        # PopSyn_Index whichever land use it is given (ids never collide:
        # TSM 1-8721, RPM 20001+).
        vals = [t, "TSM", t, t, None, a["model"], county]
        vals += [a["sum"][k] for k in sums]
        vals += [(a["w"][k][0] / a["w"][k][1]) if a["w"][k][1] > 0 else None
                 for k in WEIGHTED if fields.indexOf(k) >= 0]
        ft.setAttributes(vals)
        out.append(ft)
    for f in sorted(rpm_rows, key=lambda r: int(r["PopSyn_Index"])):
        ft = QgsFeature(of)
        ft.setGeometry(f.geometry())
        p = int(f["PopSyn_Index"])
        taz = f["TAZ_REG"] if fields.indexOf("TAZ_REG") >= 0 else None
        vals = [p, "RPM", int(f["TSM_NG"]), p, int(taz) if taz not in (None, "") else None,
                f["Model"], f["County"] if fields.indexOf("County") >= 0 else None]
        vals += [float(f[k]) if f[k] not in (None, "") else 0.0 for k in sums]
        vals += [f[k] for k in WEIGHTED if fields.indexOf(k) >= 0]
        ft.setAttributes(vals)
        out.append(ft)
    landuse_gpkg = (landuse_out or os.path.join(out_dir, LANDUSE_GPKG)).replace("\\", "/")
    os.makedirs(os.path.dirname(landuse_gpkg) or ".", exist_ok=True)
    _write_gpkg(landuse_gpkg, "model_zones_landuse", of, QgsWkbTypes.Type.MultiPolygon,
                lyr.crs(), out)
    log(f"[msr region] model zones: {len(tsm_acc)} TSM + {len(rpm_rows)} RPM "
        f"= {len(out)}; wrote {landuse_gpkg}")
    return {"msr": msr, "region_csv": region_csv, "boundary_gpkg": boundary_gpkg,
            "landuse_gpkg": landuse_gpkg, "tsm_zones": len(tsm_acc),
            "rpm_zones": len(rpm_rows), "region_tsm_zones": len(region)}


def _write_gpkg(path, layer_name, fields, wkb, crs, feats):
    if os.path.exists(path):
        os.remove(path)
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = layer_name
    w = QgsVectorFileWriter.create(path, fields, wkb, crs,
                                   QgsProject.instance().transformContext(), opts)
    if w.hasError() != QgsVectorFileWriter.WriterError.NoError:
        raise IOError(f"cannot write {path}: {w.errorMessage()}")
    for f in feats:
        g = f.geometry()
        if g.wkbType() != wkb:
            g.convertToMultiType()
            f.setGeometry(g)
        w.addFeature(f)
    del w
