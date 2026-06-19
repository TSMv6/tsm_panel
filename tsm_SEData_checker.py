
import re
from math import floor
from qgis.core import QgsProject

DEFAULT_FIELD_MAP = {
    "POP": { "subs_regex": r"^age_\d+to\d+|^age_\d+p|^age_\d+to\d+p$" },
    "HH" : { "subs_regex": r"^person_\d+$" },
    "DU" : { "subs": ["single_family_dwelling_unit","multifamily_dwelling_unit","apartments_condos"] },
    "EMP": { "subs_regex": r"^emp_.+$" },
}
EMP_MAIN = "EMP"

def _ensure_int(x):
    try: return int(round(float(x)))
    except: return 0

def _list_subfields(layer, spec):
    fields = [f.name() for f in layer.fields()]
    if "subs" in spec and spec["subs"]:
        for s in spec["subs"]:
            if s not in fields:
                raise ValueError(f"Missing sub-field: {s}")
        return spec["subs"]
    if "subs_regex" in spec and spec["subs_regex"]:
        pat = re.compile(spec["subs_regex"], re.IGNORECASE)
        subs = [f for f in fields if pat.match(f)]
        subs.sort()
        if not subs:
            raise ValueError(f"No sub-fields matched: {spec['subs_regex']}")
        return subs
    raise ValueError("spec must include 'subs' or 'subs_regex'")

def _apportion(total, raw_vals):
    n = len(raw_vals)
    total = int(round(total))
    if n == 0: return []
    if total == 0: return [0]*n
    s = sum(raw_vals)
    if s == 0:
        base = total // n
        rem = total - base*n
        out = [base]*n
        for i in range(rem): out[i]+=1
        return out
    shares = [v/s for v in raw_vals]
    floats = [total*x for x in shares]
    ints   = [floor(x) for x in floats]
    diff   = total - sum(ints)
    if diff>0:
        fracs = sorted([(i, floats[i]-ints[i]) for i in range(n)], key=lambda t:t[1], reverse=True)
        for k in range(diff):
            ints[fracs[k % n][0]] += 1
    return ints

class TSMLanduseAllocator:

    def __init__(self, layer_name="land_use", field_map=None, emp_main=EMP_MAIN):
        self.layer_name = layer_name
        self.field_map  = field_map or DEFAULT_FIELD_MAP
        self.emp_main   = emp_main
        self._conns     = []

    def _layer(self):
        lst = QgsProject.instance().mapLayersByName(self.layer_name)
        if not lst: raise RuntimeError(f"Layer not found: {self.layer_name}")
        return lst[0]

    def allocate_subs_from_main(self):
        layer = self._layer()
        if not layer.isEditable(): layer.startEditing()
        for main_field, spec in self.field_map.items():
            if layer.fields().indexOf(main_field) < 0:
                continue
            subs = _list_subfields(layer, spec)
            idxs = {name: layer.fields().indexOf(name) for name in subs+[main_field]}
            for f in layer.getFeatures():
                main_total = _ensure_int(f[main_field])
                sub_vals   = [_ensure_int(f[sf]) for sf in subs]
                new_subs   = _apportion(main_total, sub_vals)
                for sf, val in zip(subs, new_subs):
                    layer.changeAttributeValue(f.id(), idxs[sf], val)
        layer.triggerRepaint()

    def rollup_emp_main_from_subs(self):
        layer = self._layer()
        if layer.fields().indexOf(self.emp_main) < 0:
            return
        subs = _list_subfields(layer, self.field_map["EMP"])
        if not layer.isEditable(): layer.startEditing()
        idx_main = layer.fields().indexOf(self.emp_main)
        for f in layer.getFeatures():
            s = sum(_ensure_int(f[sf]) for sf in subs)
            layer.changeAttributeValue(f.id(), idx_main, s)
        layer.triggerRepaint()

    def connect_live_watch(self):
        layer = self._layer()
        fields_idx = {layer.fields()[i].name(): i for i in range(len(layer.fields()))}

        # pre-resolve subs
        resolved = {}
        for main_field, spec in self.field_map.items():
            try: resolved[main_field] = _list_subfields(layer, spec)
            except: resolved[main_field] = []

        def on_attr_changed(fid, idx, old, new):
            fname = layer.fields()[idx].name()
            # Main changed -> push to subs
            if fname in self.field_map and resolved.get(fname):
                subs = resolved[fname]
                f = next(layer.getFeatures(f"id = {fid}"), None)
                if f is None: return
                main_total = _ensure_int(new)
                sub_vals = [_ensure_int(f[sf]) for sf in subs]
                new_subs = _apportion(main_total, sub_vals)
                for sf, val in zip(subs, new_subs):
                    layer.changeAttributeValue(fid, fields_idx[sf], val)
                return
            # EMP sub changed -> roll up main EMP
            emp_subs = resolved.get(self.emp_main, [])
            if fname in emp_subs and emp_subs:
                f = next(layer.getFeatures(f"id = {fid}"), None)
                if f is None: return
                s = sum(_ensure_int(f[sf]) if sf != fname else _ensure_int(new) for sf in emp_subs)
                if layer.fields().indexOf(self.emp_main) >= 0:
                    layer.changeAttributeValue(fid, fields_idx[self.emp_main], s)

        self._conns.append(layer.attributeValueChanged.connect(on_attr_changed))
