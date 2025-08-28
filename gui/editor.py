import os
import json
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from shared.utils import sanitize_name
from extract.region_builder import extract_regions_from_dat
from shared.constants import INSTANCE_TYPES


INSTANCE_SUFFIXES = {
    '.moby.json': 'moby',
    '.controller.json': 'controller',
    '.path.json': 'path',
    '.volume.json': 'volume',
    '.clue.json': 'clue',
    '.area.json': 'area',
    '.pod.json': 'pod',
    '.scent.json': 'scent',
}


def _scan_instances(root_dir: str):
    items = []
    for base, _dirs, files in os.walk(root_dir):
        for fn in files:
            for suf, typ in INSTANCE_SUFFIXES.items():
                if fn.endswith(suf):
                    p = os.path.join(base, fn)
                    try:
                        with open(p, 'r', encoding='utf-8') as f:
                            obj = json.load(f)
                        items.append({'type': typ, 'path': p, 'data': obj})
                    except Exception:
                        pass
                    break
    # Tri: type, zone, tuid
    def _key(it):
        d = it['data']
        return (it['type'], int(d.get('zone', 0)), int(d.get('tuid', 0)))
    items.sort(key=_key)
    return items


def _read_subfile_class_id(subfile_path: str) -> int | None:
    try:
        with open(subfile_path, 'rb') as f:
            data = f.read()
        if data[:4] != b'IGHW':
            return None
        version_major = int.from_bytes(data[4:6], 'big')
        section_count = int.from_bytes(data[12:16], 'big') if version_major >= 1 else int.from_bytes(data[8:10], 'big')
        section_start = 0x20 if version_major >= 1 else 0x10
        for i in range(section_count):
            off = section_start + i * 16
            if off + 16 > len(data):
                break
            sid = int.from_bytes(data[off:off+4], 'big')
            doff = int.from_bytes(data[off+4:off+8], 'big')
            if sid == 0x0002501C and doff + 4 <= len(data):
                return int.from_bytes(data[doff:doff+4], 'big')
    except Exception:
        return None
    return None


class EditorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Polaris Level Editor (Lite)")
        self.geometry("1100x700")
        self.extract_dir: str | None = None
        self.instances: list[dict] = []
        self.zone_names: list[str] = []
        self.pending_path_point: tuple[dict, int] | None = None

        self._build_ui()

    def _build_ui(self):
        # Menus
        menubar = tk.Menu(self)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Ouvrir DAT...", command=self.menu_open_dat)
        filemenu.add_command(label="Ouvrir dossier d'extraction...", command=self.menu_open_folder)
        filemenu.add_separator()
        filemenu.add_command(label="Rebuild vers DAT...", command=self.menu_rebuild)
        filemenu.add_separator()
        filemenu.add_command(label="Quitter", command=self.destroy)
        menubar.add_cascade(label="Fichier", menu=filemenu)
        self.config(menu=menubar)

        # Layout
        main = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main, width=300)
        center = ttk.Frame(main, width=350)
        right = ttk.Frame(main)
        main.add(left, weight=1)
        main.add(center, weight=2)
        main.add(right, weight=3)

        # Left: navigation tree (Region -> Type -> Instances) with search + scrollbar
        ttk.Label(left, text="Navigation").pack(anchor='w')
        search_row = ttk.Frame(left)
        search_row.pack(fill=tk.X, padx=4)
        ttk.Label(search_row, text='Rechercher', width=10).pack(side=tk.LEFT)
        self.nav_search_var = tk.StringVar()
        nav_search = ttk.Entry(search_row, textvariable=self.nav_search_var)
        nav_search.pack(side=tk.LEFT, fill=tk.X, expand=True)
        nav_search.bind('<KeyRelease>', lambda _e: self.refresh_tree())
        nav_container = ttk.Frame(left)
        nav_container.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.nav_tree = ttk.Treeview(nav_container, show='tree')
        nav_scroll = ttk.Scrollbar(nav_container, orient="vertical", command=self.nav_tree.yview)
        self.nav_tree.configure(yscrollcommand=nav_scroll.set)
        self.nav_tree.pack(side='left', fill=tk.BOTH, expand=True)
        nav_scroll.pack(side='right', fill='y')
        self.nav_tree.bind('<<TreeviewSelect>>', self.on_select)
        self.nav_tree.bind('<Double-Button-1>', self.on_select)
        # Drag & drop interne pour références
        self._drag_data = {'start_node': None, 'dragging': False}
        self.nav_tree.bind('<ButtonPress-1>', self._on_tree_button_press, add='+')
        self.nav_tree.bind('<B1-Motion>', self._on_tree_motion, add='+')
        self.nav_tree.bind('<ButtonRelease-1>', self._on_tree_button_release, add='+')
        self.node_to_instance: dict[str, dict] = {}
        self.node_action: dict[str, dict] = {}

        # Center: fields with scrollbar
        fields_container = ttk.Frame(center)
        fields_container.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        fields_canvas = tk.Canvas(fields_container)
        fields_scroll = ttk.Scrollbar(fields_container, orient="vertical", command=fields_canvas.yview)
        self.fields_frame = ttk.Frame(fields_canvas)
        self.fields_frame.bind("<Configure>", lambda e: fields_canvas.configure(scrollregion=fields_canvas.bbox("all")))
        fields_canvas.create_window((0, 0), window=self.fields_frame, anchor="nw")
        fields_canvas.configure(yscrollcommand=fields_scroll.set)
        fields_canvas.pack(side='left', fill=tk.BOTH, expand=True)
        fields_scroll.pack(side='right', fill='y')

        self.lbl_path = ttk.Label(self.fields_frame, text="")
        self.lbl_path.pack(anchor='w')

        self.form_vars: dict[str, tk.StringVar] = {}
        self.generic_rows: dict[str, tk.Widget] = {}
        def add_field(label):
            row = ttk.Frame(self.fields_frame)
            row.pack(fill=tk.X)
            ttk.Label(row, text=label, width=14).pack(side=tk.LEFT)
            var = tk.StringVar()
            ttk.Entry(row, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.form_vars[label] = var
            self.generic_rows[label] = row

        # Zone selection via combobox
        ttk.Label(self.fields_frame, text="zone").pack(anchor='w')
        self.zone_var = tk.StringVar()
        self.zone_combo = ttk.Combobox(self.fields_frame, textvariable=self.zone_var, values=[])
        self.zone_combo.pack(fill=tk.X)
        # Pas de champ numérique de zone: l'index est déduit de la combobox

        # Generic fields - will be shown/hidden dynamically per instance type
        for label in ["name", "position.x", "position.y", "position.z", "rotation.x", "rotation.y", "rotation.z", "scale", "scale_y", "scale_z"]:
            add_field(label)

        # Type-specific panel (placé avant les boutons pour éviter les grands espaces)
        ttk.Separator(self.fields_frame).pack(fill=tk.X, pady=6)
        self.type_frame = ttk.Frame(self.fields_frame)
        self.type_frame.pack(fill=tk.BOTH, expand=False)
        self.type_widgets: dict[str, Any] = {}

        # Boutons en bas
        btns = ttk.Frame(self.fields_frame)
        btns.pack(fill=tk.X, pady=8)
        ttk.Button(btns, text="Enregistrer", command=self.save_current).pack(side=tk.LEFT)
        ttk.Button(btns, text="Dupliquer", command=self.duplicate_current).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Nouveau Clue", command=self.create_new_clue).pack(side=tk.LEFT)
        self.btns_frame = btns

        # Right: Subfile info with scrollbar
        subf = ttk.Frame(right)
        subf.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        ttk.Label(subf, text="Subfile").pack(anchor='w')
        subfile_frame = ttk.Frame(subf)
        subfile_frame.pack(fill=tk.BOTH, expand=True)
        self.subfile_text = tk.Text(subfile_frame, height=20)
        subfile_scroll = ttk.Scrollbar(subfile_frame, orient="vertical", command=self.subfile_text.yview)
        self.subfile_text.configure(yscrollcommand=subfile_scroll.set)
        self.subfile_text.pack(side='left', fill=tk.BOTH, expand=True)
        subfile_scroll.pack(side='right', fill='y')

        # Right (bottom): JSON brut with scrollbar
        ttk.Label(subf, text="JSON").pack(anchor='w')
        json_frame = ttk.Frame(subf)
        json_frame.pack(fill=tk.BOTH, expand=True)
        self.json_text = tk.Text(json_frame, height=14)
        json_scroll = ttk.Scrollbar(json_frame, orient="vertical", command=self.json_text.yview)
        self.json_text.configure(yscrollcommand=json_scroll.set)
        self.json_text.pack(side='left', fill=tk.BOTH, expand=True)
        json_scroll.pack(side='right', fill='y')

    # Menu actions
    def menu_open_dat(self):
        path = filedialog.askopenfilename(title="Choisir gp_prius.dat", filetypes=[("DAT","*.dat"), ("Tous","*.*")])
        if not path:
            return
        out_dir = filedialog.askdirectory(title="Choisir dossier d'extraction")
        if not out_dir:
            return
        def run():
            try:
                extract_regions_from_dat(path, out_dir)
                self.extract_dir = out_dir
                self.reload_instances()
            except Exception as e:
                messagebox.showerror("Erreur extraction", str(e))
        threading.Thread(target=run, daemon=True).start()

    def menu_open_folder(self):
        path = filedialog.askdirectory(title="Choisir dossier d'extraction")
        if not path:
            return
        self.extract_dir = path
        self.reload_instances()

    def menu_rebuild(self):
        if not self.extract_dir:
            messagebox.showinfo("Info", "Ouvrez un dossier d'extraction d'abord")
            return
        out = filedialog.asksaveasfilename(title="Rebuild vers", defaultextension=".dat", filetypes=[("DAT","*.dat")])
        if not out:
            return
        def run():
            try:
                from main import rebuild_dat_from_folder
                rebuild_dat_from_folder(self.extract_dir, out)
                # Générer instance.lua à côté du DAT sauvegardé
                try:
                    from tools.generate_instance_handles_lua import generate_instance_handles_lua
                    out_dir = os.path.dirname(out)
                    generate_instance_handles_lua(self.extract_dir, os.path.join(out_dir, 'instance.lua'))
                except Exception:
                    pass
                messagebox.showinfo("Rebuild", f"Rebuild terminé: {out}")
            except Exception as e:
                messagebox.showerror("Erreur rebuild", str(e))
        threading.Thread(target=run, daemon=True).start()

    # Data loading
    def reload_instances(self):
        if not self.extract_dir:
            return
        # collect zone names: assume structure <extract_dir>/<region>/<zone>/*
        self.zone_names = []
        try:
            # pick first region directory
            regions = [d for d in os.listdir(self.extract_dir) if os.path.isdir(os.path.join(self.extract_dir, d))]
            if regions:
                region_dir = os.path.join(self.extract_dir, regions[0])
                self.zone_names = [d for d in os.listdir(region_dir) if os.path.isdir(os.path.join(region_dir, d))]
                self.zone_names.sort()
        except Exception:
            self.zone_names = []
        self.zone_combo['values'] = self.zone_names
        # collect volume options for Clue linking (name + tuid)
        self.volume_options = []
        self.volume_by_tuid = {}
        # collect clue options for Scent linking (name + tuid)
        self.clue_options = []
        self.clue_by_tuid = {}
        try:
            all_items = _scan_instances(self.extract_dir)
            for it in all_items:
                if it['type'] == 'volume':
                    name = it['data'].get('name') or os.path.basename(it['path'])
                    tuid = it['data'].get('tuid')
                    try:
                        tuid_int = int(tuid, 0) if isinstance(tuid, str) else int(tuid)
                        tuid_hex = f"0x{tuid_int:016X}"
                    except Exception:
                        tuid_int = None
                        tuid_hex = str(tuid)
                    self.volume_options.append((f"{name} ({tuid_hex})", tuid))
                    if tuid_int is not None:
                        self.volume_by_tuid[tuid_int] = it['data']
                elif it['type'] == 'clue':
                    name = it['data'].get('name') or os.path.basename(it['path'])
                    tuid = it['data'].get('tuid')
                    try:
                        tuid_int = int(tuid, 0) if isinstance(tuid, str) else int(tuid)
                        tuid_hex = f"0x{tuid_int:016X}"
                    except Exception:
                        tuid_int = None
                        tuid_hex = str(tuid)
                    self.clue_options.append((f"{name} ({tuid_hex})", tuid))
                    if tuid_int is not None:
                        self.clue_by_tuid[tuid_int] = it['data']
            # sort by name
            self.volume_options.sort(key=lambda x: x[0].lower())
            self.clue_options.sort(key=lambda x: x[0].lower())
        except Exception:
            self.volume_options = []
            self.clue_options = []
        self.instances = _scan_instances(self.extract_dir)
        self.refresh_list()

    def refresh_list(self):
        # Backward compatibility no-op
        self.refresh_tree()

    def refresh_tree(self):
        # Clear tree
        for i in self.nav_tree.get_children():
            self.nav_tree.delete(i)
        self.node_to_instance.clear()
        self.node_action.clear()
        # index by tuid for navigation
        self.tuid_to_instance: dict[int, dict] = {}
        # Optional filter by search
        filter_text = ''
        try:
            filter_text = (self.nav_search_var.get() or '').strip().lower()
        except Exception:
            filter_text = ''
        def _matches(it: dict) -> bool:
            if not filter_text:
                return True
            d = it['data']
            name = str(d.get('name') or '')
            typ = str(it.get('type') or '')
            path = str(it.get('path') or '')
            # include tuid string and hex
            tu = d.get('tuid')
            tu_s = ''
            try:
                tu_i = int(tu, 0) if isinstance(tu, str) else int(tu)
                tu_s = f"0x{tu_i:016X}"
            except Exception:
                tu_s = str(tu or '')
            blob = ' '.join([name, typ, path, tu_s]).lower()
            return filter_text in blob
        items_source = [it for it in self.instances if _matches(it)]
        for it in items_source:
            tuid = it['data'].get('tuid')
            try:
                self.tuid_to_instance[int(tuid,0) if isinstance(tuid,str) else int(tuid)] = it
            except Exception:
                pass
        # Group by region then type
        grouped: dict[str, dict[str, dict[str, list[dict]]]] = {}
        base_parts = self.extract_dir.rstrip(os.sep).split(os.sep) if self.extract_dir else []
        for it in items_source:
            path_parts = it['path'].split(os.sep)
            region = 'default'
            zone = ''
            if len(path_parts) > len(base_parts):
                region = path_parts[len(base_parts)]
            if len(path_parts) > len(base_parts)+1:
                zone = path_parts[len(base_parts)+1]
            grouped.setdefault(region, {})
            grouped[region].setdefault(zone, {})
            grouped[region][zone].setdefault(it['type'], []).append(it)
        # Build nodes
        for region in sorted(grouped.keys()):
            rid = self.nav_tree.insert('', 'end', text=region)
            for zone in sorted(grouped[region].keys()):
                zid_text = zone if zone else '(racine)'
                zid = self.nav_tree.insert(rid, 'end', text=zid_text)
                for typ in sorted(grouped[region][zone].keys()):
                    tid = self.nav_tree.insert(zid, 'end', text=typ)
                    items = grouped[region][zone][typ]
                    # sort instances by name
                    items_sorted = sorted(items, key=lambda x: (str(x['data'].get('name') or os.path.basename(x['path']))).lower())
                    for inst in items_sorted:
                        name = inst['data'].get('name') or os.path.basename(inst['path'])
                        iid = self.nav_tree.insert(tid, 'end', text=name)
                        self.node_to_instance[iid] = inst
                        # expandables for container-like types
                        if inst['type'] == 'area':
                            an = self.nav_tree.insert(iid, 'end', text='Paths')
                            self.node_action[an] = {'action': 'container_header', 'container': inst, 'container_type': 'area', 'sublist': 'paths'}
                            for ref in inst['data'].get('path_references') or []:
                                # Show name if known via tuid index
                                txt = f"TUID {ref.get('tuid')}"
                                try:
                                    rinst = self.tuid_to_instance.get(int(ref.get('tuid')))
                                    if rinst:
                                        rname = rinst['data'].get('name') or os.path.basename(rinst['path'])
                                        txt = f"{rname} (TUID {ref.get('tuid')})"
                                except Exception:
                                    pass
                                rn = self.nav_tree.insert(an, 'end', text=txt)
                                try:
                                    self.node_action[rn] = {'action':'ref_tuid', 'tuid': int(ref.get('tuid')), 'container': inst, 'container_type': 'area', 'sublist': 'paths', 'ref': {'tuid': int(ref.get('tuid'))}}
                                except Exception:
                                    pass
                            vn = self.nav_tree.insert(iid, 'end', text='Volumes')
                            self.node_action[vn] = {'action': 'container_header', 'container': inst, 'container_type': 'area', 'sublist': 'volumes'}
                            for ref in inst['data'].get('volume_references') or []:
                                txt = f"TUID {ref.get('tuid')}"
                                try:
                                    rinst = self.tuid_to_instance.get(int(ref.get('tuid')))
                                    if rinst:
                                        rname = rinst['data'].get('name') or os.path.basename(rinst['path'])
                                        txt = f"{rname} (TUID {ref.get('tuid')})"
                                except Exception:
                                    pass
                                rn = self.nav_tree.insert(vn, 'end', text=txt)
                                try:
                                    self.node_action[rn] = {'action':'ref_tuid', 'tuid': int(ref.get('tuid')), 'container': inst, 'container_type': 'area', 'sublist': 'volumes', 'ref': {'tuid': int(ref.get('tuid'))}}
                                except Exception:
                                    pass
                        elif inst['type'] == 'pod':
                            pn = self.nav_tree.insert(iid, 'end', text='Références')
                            self.node_action[pn] = {'action': 'container_header', 'container': inst, 'container_type': 'pod'}
                            for ref in inst['data'].get('instance_references') or []:
                                txt = f"type {ref.get('type')} - tuid {ref.get('tuid')}"
                                try:
                                    rinst = self.tuid_to_instance.get(int(ref.get('tuid')))
                                    if rinst:
                                        rname = rinst['data'].get('name') or os.path.basename(rinst['path'])
                                        txt = f"{rname} (type {ref.get('type')} - tuid {ref.get('tuid')})"
                                except Exception:
                                    pass
                                rn = self.nav_tree.insert(pn, 'end', text=txt)
                                try:
                                    self.node_action[rn] = {'action':'ref_tuid', 'tuid': int(ref.get('tuid')), 'type': int(ref.get('type')), 'container': inst, 'container_type': 'pod', 'ref': {'type': int(ref.get('type')), 'tuid': int(ref.get('tuid'))}}
                                except Exception:
                                    pass
                        elif inst['type'] == 'scent':
                            sn = self.nav_tree.insert(iid, 'end', text='Références')
                            self.node_action[sn] = {'action': 'container_header', 'container': inst, 'container_type': 'scent'}
                            for ref in inst['data'].get('instance_references') or []:
                                txt = f"tuid {ref.get('tuid')}"
                                try:
                                    rinst = self.tuid_to_instance.get(int(ref.get('tuid')))
                                    if rinst:
                                        rname = rinst['data'].get('name') or os.path.basename(rinst['path'])
                                        txt = f"{rname} (tuid {ref.get('tuid')})"
                                except Exception:
                                    pass
                                rn = self.nav_tree.insert(sn, 'end', text=txt)
                                try:
                                    self.node_action[rn] = {'action':'ref_tuid', 'tuid': int(ref.get('tuid')), 'container': inst, 'container_type': 'scent', 'ref': {'tuid': int(ref.get('tuid'))}}
                                except Exception:
                                    pass
                        elif inst['type'] == 'path':
                            # Add point children under the path instance
                            pts = inst['data'].get('points') or []
                            pn = self.nav_tree.insert(iid, 'end', text='Points')
                            for idx, pt in enumerate(pts):
                                ts = pt.get('timestamp', '')
                                child = self.nav_tree.insert(pn, 'end', text=f'Point {idx} (t={ts})')
                                self.node_action[child] = {'action': 'path_point', 'instance': inst, 'index': idx, 'node': child}
                        # subfile child for types with subfiles
                        if inst['type'] in ('moby','controller','clue'):
                            base_dir = os.path.dirname(inst['path'])
                            sname = sanitize_name(inst['data'].get('name') or '')
                            host = os.path.join(base_dir, f"{sname}_CLASS.host.dat")
                            local = os.path.join(base_dir, f"{sname}_CLASS.local.dat")
                            if os.path.isfile(host) or os.path.isfile(local):
                                sroot = self.nav_tree.insert(iid, 'end', text='Subfiles')
                                if os.path.isfile(host):
                                    hn = self.nav_tree.insert(sroot, 'end', text='host')
                                    self.node_action[hn] = {'action':'subfile', 'path': host}
                                if os.path.isfile(local):
                                    ln = self.nav_tree.insert(sroot, 'end', text='local')
                                    self.node_action[ln] = {'action':'subfile', 'path': local}
                            if inst['type'] == 'clue':
                                # linked volume
                                vol_tuid = inst['data'].get('volume_tuid')
                                try:
                                    v_int = int(vol_tuid,0) if isinstance(vol_tuid,str) else int(vol_tuid)
                                except Exception:
                                    v_int = None
                                label = 'Linked Volume'
                                if v_int is not None and v_int in self.volume_by_tuid:
                                    vname = self.volume_by_tuid[v_int].get('name') or ''
                                    if vname:
                                        label = f'Linked Volume ({vname})'
                                vn = self.nav_tree.insert(iid, 'end', text=label)
                                if v_int is not None:
                                    self.node_action[vn] = {'action':'ref_tuid', 'tuid': v_int}

    def _current_item(self):
        sel = self.nav_tree.selection()
        if not sel:
            return None
        node_id = sel[0]
        # handle actions: navigate to referenced instance or show subfile
        act = self.node_action.get(node_id)
        if act and act.get('action') == 'ref_tuid':
            target = self.tuid_to_instance.get(act.get('tuid'))
            if target:
                # Ne pas changer la sélection globale; permettre l'édition in-place
                return target
        if act and act.get('action') == 'subfile':
            # just show subfile content header
            try:
                self.subfile_text.delete('1.0', tk.END)
                p = act.get('path')
                cid = _read_subfile_class_id(p)
                self.subfile_text.insert(tk.END, f"{os.path.basename(p)}\nClassID: {cid}\n")
            except Exception:
                pass
        if act and act.get('action') == 'path_point':
            # set pending path-point to focus in the encart; return the instance
            inst = act.get('instance')
            idx = act.get('index')
            if inst is not None and idx is not None:
                self.pending_path_point = (inst, idx)
                return inst
        return self.node_to_instance.get(node_id)

    def on_select(self, _evt=None):
        it = self._current_item()
        if not it:
            return
        d = it['data']
        self.lbl_path.config(text=it['path'])
        # Reset fields
        for k in self.form_vars:
            self.form_vars[k].set("")
        # Populate known fields
        self.form_vars['name'].set(str(d.get('name') or ""))
        # zone index est déduit de la combobox; pas de champ numérique
        # guess current zone folder name from path
        current_zone_name = None
        try:
            parts = it['path'].split(os.sep)
            # .../<extract>/<region>/<zone>/file
            if len(parts) >= 2:
                # find region folder under extract_dir
                base_parts = self.extract_dir.rstrip(os.sep).split(os.sep)
                idx = len(base_parts)
                if len(parts) > idx + 1:
                    current_zone_name = parts[idx + 1]
        except Exception:
            current_zone_name = None
        self.zone_var.set(current_zone_name or "")
        pos = d.get('position') or {}
        rot = d.get('rotation') or {}
        self.form_vars['position.x'].set(str(pos.get('x', "")))
        self.form_vars['position.y'].set(str(pos.get('y', "")))
        self.form_vars['position.z'].set(str(pos.get('z', "")))
        self.form_vars['rotation.x'].set(str(rot.get('x', "")))
        self.form_vars['rotation.y'].set(str(rot.get('y', "")))
        self.form_vars['rotation.z'].set(str(rot.get('z', "")))
        self.form_vars['scale'].set(str(d.get('scale', "")))
        # optional per type scales
        self.form_vars['scale_y'].set(str(d.get('scale_y', "")))
        self.form_vars['scale_z'].set(str(d.get('scale_z', "")))

        # Subfile info (affiché uniquement pour moby/controller/clue)
        self.subfile_text.delete('1.0', tk.END)
        if it['type'] in ('moby','controller','clue'):
            base_dir = os.path.dirname(it['path'])
            sname = sanitize_name(d.get('name') or '')
            host = os.path.join(base_dir, f"{sname}_CLASS.host.dat")
            local = os.path.join(base_dir, f"{sname}_CLASS.local.dat")
            if os.path.isfile(host):
                cid = _read_subfile_class_id(host)
                self.subfile_text.insert(tk.END, f"host.dat présent\nClassID: {cid}\n")
            if os.path.isfile(local):
                cid = _read_subfile_class_id(local)
                self.subfile_text.insert(tk.END, f"local.dat présent\nClassID: {cid}\n")
            if not os.path.isfile(host) and not os.path.isfile(local):
                self.subfile_text.insert(tk.END, "Aucun subfile détecté\n")

        # JSON raw
        try:
            self.json_text.delete('1.0', tk.END)
            self.json_text.insert(tk.END, json.dumps(d, indent=2, ensure_ascii=False))
        except Exception:
            pass

        # Adapt generic fields visibility per instance type
        self._adapt_generic_fields(it['type'])
        
        # Build type-specific form
        self._build_type_form(it['type'], d)

    # Drag & drop handlers for references
    def _on_tree_button_press(self, event):
        try:
            nid = self.nav_tree.identify_row(event.y)
            self._drag_data = {'start_node': nid, 'dragging': False}
        except Exception:
            self._drag_data = {'start_node': None, 'dragging': False}

    def _on_tree_motion(self, event):
        if self._drag_data.get('start_node'):
            self._drag_data['dragging'] = True

    def _on_tree_button_release(self, event):
        try:
            if not self._drag_data.get('dragging'):
                return
            src_id = self._drag_data.get('start_node')
            tgt_id = self.nav_tree.identify_row(event.y)
        finally:
            self._drag_data = {'start_node': None, 'dragging': False}
        if not src_id or not tgt_id or src_id == tgt_id:
            return
        src_meta = self.node_action.get(src_id)
        if not src_meta or src_meta.get('action') != 'ref_tuid':
            return
        # Resolve target container: header, ref child, or instance node
        tgt_meta = self.node_action.get(tgt_id)
        target_container = None
        target_container_type = None
        target_sublist = None
        if tgt_meta and tgt_meta.get('action') == 'container_header':
            target_container = tgt_meta.get('container')
            target_container_type = tgt_meta.get('container_type')
            target_sublist = tgt_meta.get('sublist')
        elif tgt_meta and tgt_meta.get('action') == 'ref_tuid':
            target_container = tgt_meta.get('container')
            target_container_type = tgt_meta.get('container_type')
            target_sublist = tgt_meta.get('sublist')
        elif tgt_id in self.node_to_instance:
            inst = self.node_to_instance[tgt_id]
            target_container = inst
            target_container_type = inst.get('type')
            # For area, default to same sublist as source
            target_sublist = src_meta.get('sublist')
        else:
            return
        if target_container is None:
            return
        # Ask move or copy
        ans = messagebox.askyesnocancel('Déplacer la référence ?', 'Oui = Déplacer (supprimer de la source), Non = Copier (garder la source), Annuler = annuler')
        if ans is None:
            return
        move = bool(ans)
        # Prepare data
        ref = src_meta.get('ref') or {}
        src_container = src_meta.get('container')
        src_container_type = src_meta.get('container_type')
        try:
            # Extract tuid and optional type
            ref_tuid = int(ref.get('tuid') if isinstance(ref.get('tuid'), (int, str)) else src_meta.get('tuid'))
        except Exception:
            return
        ref_type_val = ref.get('type') if isinstance(ref.get('type'), (int, str)) else src_meta.get('type')

        # Remove from source if move
        try:
            if move and src_container:
                if src_container_type == 'scent':
                    src_list = src_container['data'].get('instance_references') or []
                    src_container['data']['instance_references'] = [r for r in src_list if int(r.get('tuid')) != ref_tuid]
                elif src_container_type == 'pod':
                    src_list = src_container['data'].get('instance_references') or []
                    src_container['data']['instance_references'] = [r for r in src_list if not (int(r.get('tuid')) == ref_tuid and int(r.get('type')) == int(ref_type_val))]
                elif src_container_type == 'area':
                    src_key = 'path_references' if src_meta.get('sublist') == 'paths' else 'volume_references'
                    src_list = src_container['data'].get(src_key) or []
                    src_container['data'][src_key] = [r for r in src_list if int(r.get('tuid')) != ref_tuid]
        except Exception:
            pass

        # Add to target
        try:
            if target_container_type == 'scent':
                tgt_list = target_container['data'].get('instance_references') or []
                if not any(int(r.get('tuid')) == ref_tuid for r in tgt_list):
                    tgt_list.append({'tuid': ref_tuid})
                target_container['data']['instance_references'] = tgt_list
            elif target_container_type == 'pod':
                # Determine type id
                type_id = None
                if ref_type_val is not None:
                    try:
                        type_id = int(ref_type_val)
                    except Exception:
                        type_id = None
                if type_id is None:
                    type_map = {'moby':0,'path':1,'volume':2,'clue':3,'controller':4,'scent':5,'area':6,'pod':7}
                    for inst in self.instances:
                        try:
                            tu = inst['data'].get('tuid')
                            if int(tu,0) if isinstance(tu,str) else int(tu) == ref_tuid:
                                type_id = type_map.get(inst['type'])
                                break
                        except Exception:
                            continue
                if type_id is not None:
                    tgt_list = target_container['data'].get('instance_references') or []
                    if not any(int(r.get('tuid')) == ref_tuid and int(r.get('type')) == int(type_id) for r in tgt_list):
                        tgt_list.append({'type': int(type_id), 'tuid': ref_tuid})
                    target_container['data']['instance_references'] = tgt_list
            elif target_container_type == 'area':
                # choose sublist by header or detect by instance type
                list_key = None
                if target_sublist == 'paths':
                    list_key = 'path_references'
                elif target_sublist == 'volumes':
                    list_key = 'volume_references'
                else:
                    # detect
                    is_path = False
                    for inst in self.instances:
                        try:
                            tu = inst['data'].get('tuid')
                            if int(tu,0) if isinstance(tu,str) else int(tu) == ref_tuid:
                                is_path = (inst['type'] == 'path')
                                break
                        except Exception:
                            continue
                    list_key = 'path_references' if is_path else 'volume_references'
                tgt_list = target_container['data'].get(list_key) or []
                if not any(int(r.get('tuid')) == ref_tuid for r in tgt_list):
                    tgt_list.append({'tuid': ref_tuid})
                target_container['data'][list_key] = tgt_list
        except Exception:
            pass

        # Persist both containers
        try:
            def _save_container(inst):
                try:
                    with open(inst['path'], 'w', encoding='utf-8') as f:
                        json.dump(inst['data'], f, indent=2, ensure_ascii=False)
                except Exception:
                    pass
            _save_container(target_container)
            if move and src_container:
                _save_container(src_container)
            self.reload_instances()
        except Exception as e:
            messagebox.showerror('Erreur DnD', str(e))

    def _adapt_generic_fields(self, typ: str):
        """Show/hide generic fields based on instance type"""
        # Hide all generic fields first
        for label, widget in self.generic_rows.items():
            widget.pack_forget()
        
        # Show only relevant fields per type
        if typ == 'moby':
            # Moby: position, rotation, scale (no scale_y/z)
            for label in ["name", "position.x", "position.y", "position.z", "rotation.x", "rotation.y", "rotation.z", "scale"]:
                self.generic_rows[label].pack(fill=tk.X)
        elif typ == 'controller':
            # Controller: position, rotation, scale, scale_y, scale_z
            for label in ["name", "position.x", "position.y", "position.z", "rotation.x", "rotation.y", "rotation.z", "scale", "scale_y", "scale_z"]:
                self.generic_rows[label].pack(fill=tk.X)
        elif typ == 'clue':
            # Clue: only name (position/rotation/scale come from volume matrix)
            for label in ["name"]:
                self.generic_rows[label].pack(fill=tk.X)
        elif typ == 'volume':
            # Volume: only name (transform matrix handles position/rotation/scale)
            for label in ["name"]:
                self.generic_rows[label].pack(fill=tk.X)
        elif typ == 'path':
            # Path: name only (points have their own coordinates)
            for label in ["name"]:
                self.generic_rows[label].pack(fill=tk.X)
        elif typ in ['area', 'pod', 'scent']:
            # Container types: name only (no position/rotation/scale)
            for label in ["name"]:
                self.generic_rows[label].pack(fill=tk.X)
        else:
            # Default: show all fields
            for label, widget in self.generic_rows.items():
                widget.pack(fill=tk.X)

    def _clear_type_form(self):
        for w in self.type_frame.winfo_children():
            w.destroy()
        self.type_widgets = {}

    def _build_type_form(self, typ: str, data: dict):
        self._clear_type_form()
        # Utility to add a labeled entry
        def add_entry(parent, label, initial=""):
            row = ttk.Frame(parent)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=label, width=18).pack(side=tk.LEFT)
            var = tk.StringVar(value=str(initial))
            ent = ttk.Entry(row, textvariable=var)
            ent.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.type_widgets[label] = var
            return var

        if typ == 'moby':
            add_entry(self.type_frame, 'model_index', data.get('model_index', ''))
            add_entry(self.type_frame, 'zone_render_index', data.get('zone_render_index', data.get('zone', '')))
            add_entry(self.type_frame, 'update_dist', data.get('update_dist', ''))
            add_entry(self.type_frame, 'display_dist', data.get('display_dist', ''))
            add_entry(self.type_frame, 'flags_hex', data.get('flags', ''))
            add_entry(self.type_frame, 'unknown_hex', data.get('unknown', ''))
            add_entry(self.type_frame, 'padding_hex', data.get('padding', ''))

        elif typ == 'controller':
            # scale_y/z already present in generic fields; no duplicates here
            pass

        elif typ == 'clue':
            # class_id + volume tuid (combobox + raw)
            add_entry(self.type_frame, 'class_id', data.get('class_id', ''))
            # volume selector
            row = ttk.Frame(self.type_frame)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text='volume_tuid', width=18).pack(side=tk.LEFT)
            vol_var = tk.StringVar()
            combo = ttk.Combobox(row, textvariable=vol_var, values=[opt[0] for opt in self.volume_options])
            # preselect current
            current_v = data.get('volume_tuid')
            if current_v is not None:
                try:
                    cur_int = int(current_v, 0) if isinstance(current_v, str) else int(current_v)
                    cur_hex = f"0x{cur_int:016X}"
                except Exception:
                    cur_int = None
                    cur_hex = str(current_v)
                for label, tu in self.volume_options:
                    if cur_hex in label:
                        vol_var.set(label)
                        break
            combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.type_widgets['volume_tuid_combo'] = vol_var
            # raw fallback
            add_entry(self.type_frame, 'volume_tuid_raw', data.get('volume_tuid', ''))
            
            # Editor identique à Volume: grille 4x4 éditable
            ttk.Label(self.type_frame, text='Transform 4x4').pack(anchor='w')
            grid = ttk.Frame(self.type_frame)
            grid.pack()
            vol_matrix_vars = []
            vol_matrix = None
            if current_v is not None:
                try:
                    v_int = int(current_v, 0) if isinstance(current_v, str) else int(current_v)
                except Exception:
                    v_int = None
                if v_int is not None and v_int in self.volume_by_tuid:
                    vol = self.volume_by_tuid[v_int]
                    vol_matrix = vol.get('transform_matrix')
            if not vol_matrix:
                vol_matrix = [[0,0,0,0] for _ in range(4)]
            for r in range(4):
                row_vars = []
                for c in range(4):
                    var = tk.StringVar(value=str(vol_matrix[r][c]))
                    e = ttk.Entry(grid, textvariable=var, width=10)
                    e.grid(row=r, column=c, padx=2, pady=2)
                    row_vars.append(var)
                vol_matrix_vars.append(row_vars)
            self.type_widgets['clue_volume_matrix'] = vol_matrix_vars

        elif typ == 'path':
            # Focus editor for a single point (selected from tree)
            pts = data.get('points') or []
            sel_idx = 0
            if self.pending_path_point and self.pending_path_point[0] is not None and self.pending_path_point[0]['path'] == data.get('path', None):
                sel_idx = int(self.pending_path_point[1])
            elif self.pending_path_point and self.pending_path_point[0] is not None and self.pending_path_point[0]['data'] is data:
                sel_idx = int(self.pending_path_point[1])
            sel_idx = min(max(sel_idx, 0), len(pts)-1) if pts else 0
            
            ttk.Label(self.type_frame, text=f'Point sélectionné: {sel_idx}').pack(anchor='w')
            ex = add_entry(self.type_frame, 'pt.x', pts[sel_idx].get('position',{}).get('x','') if pts else '')
            ey = add_entry(self.type_frame, 'pt.y', pts[sel_idx].get('position',{}).get('y','') if pts else '')
            ez = add_entry(self.type_frame, 'pt.z', pts[sel_idx].get('position',{}).get('z','') if pts else '')
            et = add_entry(self.type_frame, 'timestamp', pts[sel_idx].get('timestamp','') if pts else '')
            
            def add_pt():
                pts.append({'index': len(pts), 'position': {'x':0.0,'y':0.0,'z':0.0}, 'timestamp': 0.0})
            def del_pt():
                if pts:
                    pts.pop(sel_idx)
            def apply_pt():
                if not pts:
                    return
                try:
                    x = float(ex.get()); y = float(ey.get()); z = float(ez.get()); t = float(et.get())
                except Exception:
                    return
                pts[sel_idx]['position'] = {'x': x, 'y': y, 'z': z}
                pts[sel_idx]['timestamp'] = t
                # sort by timestamp
                pts.sort(key=lambda p: float(p.get('timestamp',0)))
                for i, p in enumerate(pts):
                    p['index'] = i
            
            row = ttk.Frame(self.type_frame)
            row.pack(fill=tk.X, pady=4)
            ttk.Button(row, text='Ajouter', command=add_pt).pack(side=tk.LEFT)
            ttk.Button(row, text='Supprimer', command=del_pt).pack(side=tk.LEFT, padx=4)
            ttk.Button(row, text='Appliquer', command=apply_pt).pack(side=tk.LEFT)
            
            # header fields
            add_entry(self.type_frame, 'total_duration', data.get('total_duration',''))
            add_entry(self.type_frame, 'flags', data.get('flags',''))
            add_entry(self.type_frame, 'point_count', data.get('point_count', len(pts)))

        elif typ == 'volume':
            # Move buttons temporarily to place matrix above them
            self.btns_frame.pack_forget()
            ttk.Label(self.type_frame, text='Transform 4x4').pack(anchor='w')
            grid = ttk.Frame(self.type_frame)
            grid.pack()
            mat_vars = []
            mat = data.get('transform_matrix') or [[0,0,0,0] for _ in range(4)]
            for r in range(4):
                row_vars = []
                for c in range(4):
                    var = tk.StringVar(value=str(mat[r][c]))
                    e = ttk.Entry(grid, textvariable=var, width=10)
                    e.grid(row=r, column=c, padx=2, pady=2)
                    row_vars.append(var)
                mat_vars.append(row_vars)
            self.type_widgets['volume_matrix'] = mat_vars
            # Place buttons back after matrix
            self.btns_frame.pack(after=self.type_frame, fill=tk.X, pady=8)

        elif typ == 'area':
            ttk.Label(self.type_frame, text='Paths').pack(anchor='w')
            paths_container = ttk.Frame(self.type_frame)
            paths_container.pack(fill=tk.BOTH, expand=True)
            ttk.Label(self.type_frame, text='Volumes').pack(anchor='w')
            vols_container = ttk.Frame(self.type_frame)
            vols_container.pack(fill=tk.BOTH, expand=True)

            # options
            path_options: list[tuple[str,int]] = []
            vol_options: list[tuple[str,int]] = []
            try:
                for inst in self.instances:
                    if inst['type'] in ('path','volume'):
                        tu = inst['data'].get('tuid')
                        try:
                            tu_int = int(tu,0) if isinstance(tu,str) else int(tu)
                        except Exception:
                            continue
                        label = inst['data'].get('name') or os.path.basename(inst['path'])
                        hexid = f"0x{tu_int:016X}"
                        (path_options if inst['type']=='path' else vol_options).append((f"{label} ({hexid})", tu_int))
                path_options.sort(key=lambda x: x[0].lower())
                vol_options.sort(key=lambda x: x[0].lower())
            except Exception:
                pass

            area_path_rows: list[tk.Widget] = []
            area_vol_rows: list[tk.Widget] = []

            def make_area_row(container_frame, options, initial_tuid: int | None, rows_store: list[tk.Widget]):
                row = ttk.Frame(container_frame); row.pack(fill=tk.X, pady=2)
                var = tk.StringVar(); cmb = ttk.Combobox(row, textvariable=var, values=[lbl for lbl,_tu in options])
                def _filter(_evt=None):
                    typed = var.get().lower().strip(); base = [lbl for lbl,_tu in options]
                    cmb['values'] = base if not typed else [lbl for lbl in base if typed in lbl.lower()]
                cmb.bind('<KeyRelease>', _filter)
                if initial_tuid is not None:
                    try:
                        for lbl, tu in options:
                            if int(tu) == int(initial_tuid):
                                var.set(lbl); break
                    except Exception:
                        pass
                cmb.pack(side=tk.LEFT, fill=tk.X, expand=True)
                def remove_this():
                    try:
                        rows_store.remove(row)
                    except Exception:
                        pass
                    row.destroy()
                ttk.Button(row, text='Supprimer', command=remove_this).pack(side=tk.RIGHT, padx=4)
                rows_store.append(row)

            for ref in data.get('path_references') or []:
                try: tu = int(ref.get('tuid'),0) if isinstance(ref.get('tuid'),str) else int(ref.get('tuid'))
                except Exception: tu = None
                make_area_row(paths_container, path_options, tu, area_path_rows)
            for ref in data.get('volume_references') or []:
                try: tu = int(ref.get('tuid'),0) if isinstance(ref.get('tuid'),str) else int(ref.get('tuid'))
                except Exception: tu = None
                make_area_row(vols_container, vol_options, tu, area_vol_rows)

            # ajout path (bouton à gauche + combobox)
            addp = ttk.Frame(self.type_frame); addp.pack(fill=tk.X, pady=4)
            addp_var = tk.StringVar(); addp_cmb = ttk.Combobox(addp, textvariable=addp_var, values=[lbl for lbl,_tu in path_options])
            def addp_filter(_evt=None):
                typed = addp_var.get().lower().strip(); base = [lbl for lbl,_tu in path_options]
                addp_cmb['values'] = base if not typed else [lbl for lbl in base if typed in lbl.lower()]
            def do_addp():
                sel = addp_var.get(); tu = None
                for lbl, v in path_options:
                    if lbl == sel: tu = v; break
                if tu is None: return
                make_area_row(paths_container, path_options, tu, area_path_rows)
                addp_var.set('')
            ttk.Button(addp, text='Ajouter Path', command=do_addp).pack(side=tk.LEFT, padx=4)
            addp_cmb.bind('<KeyRelease>', addp_filter)
            addp_cmb.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # ajout volume (bouton à gauche + combobox)
            addv = ttk.Frame(self.type_frame); addv.pack(fill=tk.X, pady=4)
            addv_var = tk.StringVar(); addv_cmb = ttk.Combobox(addv, textvariable=addv_var, values=[lbl for lbl,_tu in vol_options])
            def addv_filter(_evt=None):
                typed = addv_var.get().lower().strip(); base = [lbl for lbl,_tu in vol_options]
                addv_cmb['values'] = base if not typed else [lbl for lbl in base if typed in lbl.lower()]
            def do_addv():
                sel = addv_var.get(); tu = None
                for lbl, v in vol_options:
                    if lbl == sel: tu = v; break
                if tu is None: return
                make_area_row(vols_container, vol_options, tu, area_vol_rows)
                addv_var.set('')
            ttk.Button(addv, text='Ajouter Volume', command=do_addv).pack(side=tk.LEFT, padx=4)
            addv_cmb.bind('<KeyRelease>', addv_filter)
            addv_cmb.pack(side=tk.LEFT, fill=tk.X, expand=True)

            self.type_widgets['area_path_rows'] = (area_path_rows, path_options)
            self.type_widgets['area_vol_rows'] = (area_vol_rows, vol_options)

        elif typ == 'pod':
            ttk.Label(self.type_frame, text='Références (Mobys / Controllers)').pack(anchor='w')
            container = ttk.Frame(self.type_frame)
            container.pack(fill=tk.BOTH, expand=True)

            # Options: seulement moby et controller
            type_map = {'moby':0, 'controller':4}
            inv_type_map = {v:k for k,v in type_map.items()}
            options: list[tuple[str,int,int]] = []  # (label, type_id, tuid)
            label_to_ref: dict[str, tuple[int,int]] = {}
            try:
                for inst in self.instances:
                    if inst['type'] in ('moby','controller'):
                        tu = inst['data'].get('tuid')
                        try:
                            tu_int = int(tu,0) if isinstance(tu,str) else int(tu)
                        except Exception:
                            continue
                        label = inst['data'].get('name') or os.path.basename(inst['path'])
                        hexid = f"0x{tu_int:016X}"
                        t_id = type_map[inst['type']]
                        full = f"{label} ({inv_type_map[t_id]}) ({hexid})"
                        options.append((full, t_id, tu_int))
                        label_to_ref[full] = (t_id, tu_int)
                options.sort(key=lambda x: x[0].lower())
            except Exception:
                pass

            pod_rows: list[tk.Widget] = []

            def make_row(initial_type_id: int | None, initial_tuid: int | None):
                row = ttk.Frame(container); row.pack(fill=tk.X, pady=2)
                var = tk.StringVar()
                cmb = ttk.Combobox(row, textvariable=var, values=[lbl for lbl, _ty, _tu in options])
                def _filter(_evt=None):
                    typed = var.get().lower().strip(); base = [lbl for lbl,_ty,_tu in options]
                    cmb['values'] = base if not typed else [lbl for lbl in base if typed in lbl.lower()]
                cmb.bind('<KeyRelease>', _filter)
                # preselect
                if initial_type_id is not None and initial_tuid is not None:
                    try:
                        wanted = None
                        for lbl, ty, tu in options:
                            if int(ty) == int(initial_type_id) and int(tu) == int(initial_tuid):
                                wanted = lbl; break
                        if wanted:
                            var.set(wanted)
                    except Exception:
                        pass
                cmb.pack(side=tk.LEFT, fill=tk.X, expand=True)
                def remove_this():
                    try: pod_rows.remove(row)
                    except Exception: pass
                    row.destroy()
                ttk.Button(row, text='Supprimer', command=remove_this).pack(side=tk.RIGHT, padx=4)
                pod_rows.append(row)

            # Existing rows
            for ref in data.get('instance_references') or []:
                try:
                    ty = int(ref.get('type'))
                except Exception:
                    ty = None
                try:
                    tu = int(ref.get('tuid'))
                except Exception:
                    tu = None
                # ignorer autres types que moby/controller
                if ty not in (0,4):
                    continue
                make_row(ty, tu)

            # Add row (bouton Ajouter + combobox)
            add_row = ttk.Frame(self.type_frame); add_row.pack(fill=tk.X, pady=4)
            new_var = tk.StringVar()
            def add_filter(_evt=None):
                typed = new_var.get().lower().strip(); base = [lbl for lbl,_ty,_tu in options]
                add_cmb['values'] = base if not typed else [lbl for lbl in base if typed in lbl.lower()]
            ttk.Button(add_row, text='Ajouter', command=lambda: (
                (lambda sel=new_var.get(): (
                    (lambda ref=label_to_ref.get(sel): (
                        make_row(ref[0], ref[1]) if ref else None,
                        new_var.set('')
                    ))()
                ))()
            )).pack(side=tk.LEFT, padx=4)
            add_cmb = ttk.Combobox(add_row, textvariable=new_var, values=[lbl for lbl,_ty,_tu in options])
            add_cmb.bind('<KeyRelease>', add_filter)
            add_cmb.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # store for save
            self.type_widgets['pod_row_widgets'] = (pod_rows, label_to_ref)

        elif typ == 'scent':
            ttk.Label(self.type_frame, text='Références (Clues)').pack(anchor='w')
            refs_container = ttk.Frame(self.type_frame)
            refs_container.pack(fill=tk.BOTH, expand=True)
            scent_ref_rows: list[tuple[tk.Widget, int | None]] = []
            all_labels = [opt[0] for opt in self.clue_options]

            def make_row(initial_tuid: int | None):
                row = ttk.Frame(refs_container)
                row.pack(fill=tk.X, pady=2)
                var = tk.StringVar()
                cmb = ttk.Combobox(row, textvariable=var, values=all_labels, state='normal')
                def _filter_values(_evt=None):
                    typed = var.get().lower().strip()
                    cmb['values'] = all_labels if not typed else [lbl for lbl in all_labels if typed in lbl.lower()]
                cmb.bind('<KeyRelease>', _filter_values)
                # pré-sélectionner depuis TUID
                if initial_tuid is not None:
                    try:
                        for lbl, tu in self.clue_options:
                            try:
                                if (int(tu,0) if isinstance(tu,str) else int(tu)) == int(initial_tuid):
                                    var.set(lbl)
                                    break
                            except Exception:
                                continue
                    except Exception:
                        pass
                cmb.pack(side=tk.LEFT, fill=tk.X, expand=True)
                def remove_this():
                    try:
                        scent_ref_rows.remove((row, initial_tuid))
                    except Exception:
                        pass
                    row.destroy()
                ttk.Button(row, text='Supprimer', command=remove_this).pack(side=tk.RIGHT, padx=4)
                scent_ref_rows.append((row, initial_tuid))

            # Lignes existantes
            for ref in data.get('instance_references') or []:
                try:
                    tu = int(ref.get('tuid'), 0) if isinstance(ref.get('tuid'), str) else int(ref.get('tuid'))
                except Exception:
                    tu = None
                make_row(tu)

            # Ligne d'ajout (bouton Ajouter à gauche + combobox à droite)
            add_row = ttk.Frame(self.type_frame)
            add_row.pack(fill=tk.X, pady=4)
            new_var = tk.StringVar()
            def add_new():
                sel = new_var.get(); target = None
                for lbl, tu in self.clue_options:
                    if lbl == sel:
                        try:
                            target = int(tu,0) if isinstance(tu,str) else int(tu)
                        except Exception:
                            target = None
                        break
                if target is None:
                    return
                # éviter doublons visuels
                current_tuids = []
                for _row, tu in scent_ref_rows:
                    try: current_tuids.append(int(tu) if tu is not None else None)
                    except Exception: current_tuids.append(tu)
                if target in current_tuids:
                    return
                make_row(target)
                new_var.set('')
            ttk.Button(add_row, text='Ajouter', command=add_new).pack(side=tk.LEFT, padx=4)
            add_cmb = ttk.Combobox(add_row, textvariable=new_var, values=all_labels, state='normal')
            def _filter_new(_evt=None):
                typed = new_var.get().lower().strip()
                add_cmb['values'] = all_labels if not typed else [lbl for lbl in all_labels if typed in lbl.lower()]
            add_cmb.bind('<KeyRelease>', _filter_new)
            add_cmb.pack(side=tk.LEFT, fill=tk.X, expand=True)
            

            # Stocker pour persistance
            self.type_widgets['scent_row_widgets'] = (scent_ref_rows, refs_container)

    def save_current(self):
        it = self._current_item()
        if not it:
            return
        d = it['data']
        typ = it['type']
        # Update fields present
        name = self.form_vars['name'].get().strip()
        if name:
            d['name'] = name
        # Définir zone index selon combobox
        try:
            if self.zone_names and self.zone_var.get() in self.zone_names:
                d['zone'] = self.zone_names.index(self.zone_var.get())
        except Exception:
            pass
        # Handle zone folder move if combobox changed
        target_zone_name = self.zone_var.get().strip()
        # Positions
        def _float(v):
            try:
                return float(v)
            except Exception:
                return None
        pos = d.get('position') or {}
        rx = _float(self.form_vars['position.x'].get())
        ry = _float(self.form_vars['position.y'].get())
        rz = _float(self.form_vars['position.z'].get())
        if rx is not None or ry is not None or rz is not None:
            pos = {
                'x': rx if rx is not None else pos.get('x', 0.0),
                'y': ry if ry is not None else pos.get('y', 0.0),
                'z': rz if rz is not None else pos.get('z', 0.0),
            }
            d['position'] = pos
        rot = d.get('rotation') or {}
        r0 = _float(self.form_vars['rotation.x'].get())
        r1 = _float(self.form_vars['rotation.y'].get())
        r2 = _float(self.form_vars['rotation.z'].get())
        if r0 is not None or r1 is not None or r2 is not None:
            rot = {
                'x': r0 if r0 is not None else rot.get('x', 0.0),
                'y': r1 if r1 is not None else rot.get('y', 0.0),
                'z': r2 if r2 is not None else rot.get('z', 0.0),
            }
            d['rotation'] = rot
        sc = _float(self.form_vars['scale'].get())
        if sc is not None:
            d['scale'] = sc
        # Clue extras
        try:
            cid = int(self.form_vars['class_id'].get(), 0)
            d['class_id'] = cid
        except Exception:
            pass
        try:
            vt = int(self.form_vars['volume_tuid'].get(), 0)
            d['volume_tuid'] = vt
        except Exception:
            pass
        # Write JSON
        try:
            # If zone folder changes, move files first
            new_path = it['path']
            if self.zone_names and target_zone_name and os.path.basename(os.path.dirname(it['path'])) != target_zone_name:
                # compute new dir under extract_dir/<region>/<target_zone>
                regions = [dname for dname in os.listdir(self.extract_dir) if os.path.isdir(os.path.join(self.extract_dir, dname))]
                region_dir = os.path.join(self.extract_dir, regions[0]) if regions else self.extract_dir
                new_dir = os.path.join(region_dir, target_zone_name)
                os.makedirs(new_dir, exist_ok=True)
                # move json and subfiles
                new_path = os.path.join(new_dir, os.path.basename(it['path']))
                os.replace(it['path'], new_path)
                base_dir_old = os.path.dirname(it['path'])
                base_dir_new = new_dir
                sname = sanitize_name(d.get('name') or '')
                for suf in ('host', 'local'):
                    oldp = os.path.join(base_dir_old, f"{sname}_CLASS.{suf}.dat")
                    newp = os.path.join(base_dir_new, f"{sname}_CLASS.{suf}.dat")
                    if os.path.exists(oldp):
                        os.replace(oldp, newp)
                it['path'] = new_path
            # Rename subfile if name changed
            base_dir = os.path.dirname(it['path'])
            s_old = sanitize_name(it['data'].get('name') or '')
            s_new = sanitize_name(d.get('name') or '')
            if s_old and s_new and s_old != s_new:
                for suf in ('host', 'local'):
                    oldp = os.path.join(base_dir, f"{s_old}_CLASS.{suf}.dat")
                    newp = os.path.join(base_dir, f"{s_new}_CLASS.{suf}.dat")
                    if os.path.exists(oldp) and not os.path.exists(newp):
                        os.rename(oldp, newp)
                # Rename JSON file to reflect new name
                old_json = it['path']
                new_json = os.path.join(base_dir, f"{s_new}.{it['type']}.json")
                try:
                    if os.path.exists(old_json) and (old_json != new_json):
                        if not os.path.exists(new_json):
                            os.replace(old_json, new_json)
                            it['path'] = new_json
                            self.lbl_path.config(text=new_json)
                except Exception:
                    pass
            # Type-specific persistence (mutates d)
            if typ == 'moby':
                def _int(v):
                    try:
                        return int(v, 0)
                    except Exception:
                        return None
                mi = self.type_widgets.get('model_index'); zri = self.type_widgets.get('zone_render_index')
                ud = self.type_widgets.get('update_dist'); dd = self.type_widgets.get('display_dist')
                if isinstance(mi, tk.StringVar):
                    v = _int(mi.get());
                    if v is not None: d['model_index'] = v
                if isinstance(zri, tk.StringVar):
                    v = _int(zri.get());
                    if v is not None: d['zone_render_index'] = v
                if isinstance(ud, tk.StringVar):
                    try: d['update_dist'] = float(ud.get())
                    except Exception: pass
                if isinstance(dd, tk.StringVar):
                    try: d['display_dist'] = float(dd.get())
                    except Exception: pass
                for key_json, key_ui in [('flags','flags_hex'), ('unknown','unknown_hex'), ('padding','padding_hex')]:
                    ui = self.type_widgets.get(key_ui)
                    if isinstance(ui, tk.StringVar) and ui.get():
                        d[key_json] = ui.get()

            elif typ == 'controller':
                sy = self.type_widgets.get('scale_y'); sz = self.type_widgets.get('scale_z')
                if isinstance(sy, tk.StringVar):
                    try: d['scale_y'] = float(sy.get())
                    except Exception: pass
                if isinstance(sz, tk.StringVar):
                    try: d['scale_z'] = float(sz.get())
                    except Exception: pass

            elif typ == 'clue':
                cid = self.type_widgets.get('class_id')
                if isinstance(cid, tk.StringVar):
                    try: d['class_id'] = int(cid.get(), 0)
                    except Exception: pass
                lab = self.type_widgets.get('volume_tuid_combo')
                if isinstance(lab, tk.StringVar) and lab.get():
                    for lbl, tu in self.volume_options:
                        if lbl == lab.get():
                            try: d['volume_tuid'] = int(tu, 0) if isinstance(tu, str) else int(tu)
                            except Exception: d['volume_tuid'] = tu
                            break
                else:
                    raw = self.type_widgets.get('volume_tuid_raw')
                    if isinstance(raw, tk.StringVar):
                        try: d['volume_tuid'] = int(raw.get(), 0)
                        except Exception: pass
                # Sauvegarder la matrice si éditée (écriture dans le volume lié)
                vol_matrix_vars = self.type_widgets.get('clue_volume_matrix')
                if vol_matrix_vars:
                    new_mat = []
                    for r in vol_matrix_vars:
                        row = []
                        for var in r:
                            try: row.append(float(var.get()))
                            except Exception: row.append(0.0)
                            
                        new_mat.append(row)
                    vol_tuid = d.get('volume_tuid')
                    if vol_tuid is not None:
                        try:
                            v_int = int(vol_tuid, 0) if isinstance(vol_tuid, str) else int(vol_tuid)
                        except Exception:
                            v_int = None
                        if v_int is not None:
                            # Mettre à jour le JSON du volume correspondant
                            for vol_inst in self.instances:
                                try:
                                    if vol_inst['type'] == 'volume':
                                        t = vol_inst['data'].get('tuid')
                                        t_int = int(t, 0) if isinstance(t, str) else int(t)
                                        if t_int == v_int:
                                            vol_inst['data']['transform_matrix'] = new_mat
                                            with open(vol_inst['path'], 'w', encoding='utf-8') as f:
                                                json.dump(vol_inst['data'], f, indent=2, ensure_ascii=False)
                                            break
                                except Exception:
                                    pass

            elif typ == 'path':
                tpl = self.type_widgets.get('path_points_list')
                if isinstance(tpl, tuple) and len(tpl) == 2:
                    pts = tpl[1]
                    for idx, pt in enumerate(pts):
                        pt['index'] = idx
                    d['points'] = pts
                    d['point_count'] = len(pts)
                td = self.type_widgets.get('total_duration')
                if isinstance(td, tk.StringVar):
                    try: d['total_duration'] = float(td.get())
                    except Exception: pass
                fl = self.type_widgets.get('flags')
                if isinstance(fl, tk.StringVar):
                    try: d['flags'] = int(fl.get(), 0)
                    except Exception: pass

            elif typ == 'volume':
                mats = self.type_widgets.get('volume_matrix')
                if mats:
                    new_mat = []
                    for r in mats:
                        row = []
                        for var in r:
                            try: row.append(float(var.get()))
                            except Exception: row.append(0.0)
                        new_mat.append(row)
                    d['transform_matrix'] = new_mat

            elif typ == 'area':
                # Read from combobox rows
                pr = self.type_widgets.get('area_path_rows')
                vr = self.type_widgets.get('area_vol_rows')
                path_refs: list[dict] = []
                vol_refs: list[dict] = []
                def rows_to_refs(rows_tuple, out_list):
                    if not isinstance(rows_tuple, tuple) or len(rows_tuple) != 2:
                        return
                    rows_list, options = rows_tuple
                    label_to_tuid = {lbl: tu for (lbl, tu) in options}
                    for row in rows_list:
                        try:
                            for child in row.winfo_children():
                                if isinstance(child, ttk.Combobox):
                                    lbl = child.get()
                                    if lbl in label_to_tuid:
                                        tu = label_to_tuid[lbl]
                                        if not any(int(r.get('tuid')) == int(tu) for r in out_list):
                                            out_list.append({'tuid': int(tu)})
                                    break
                        except Exception:
                            continue
                rows_to_refs(pr, path_refs)
                rows_to_refs(vr, vol_refs)
                d['path_references'] = path_refs
                d['volume_references'] = vol_refs

            elif typ == 'pod':
                # Read from single-combobox rows (label encodes type and tuid)
                pod_tuple = self.type_widgets.get('pod_row_widgets')
                refs: list[dict] = []
                if isinstance(pod_tuple, tuple) and len(pod_tuple) == 2:
                    rows_list, label_to_ref = pod_tuple
                    for row in rows_list:
                        try:
                            for child in row.winfo_children():
                                if isinstance(child, ttk.Combobox):
                                    lbl = child.get()
                                    ref = label_to_ref.get(lbl)
                                    if ref:
                                        ty, tu = ref
                                        if not any(int(r.get('tuid'))==int(tu) and int(r.get('type'))==int(ty) for r in refs):
                                            refs.append({'type': int(ty), 'tuid': int(tu)})
                                    break
                        except Exception:
                            continue
                d['instance_references'] = refs

            elif typ == 'scent':
                rows = self.type_widgets.get('scent_row_widgets')
                if isinstance(rows, tuple) and len(rows) == 2:
                    scent_ref_rows, _container = rows
                    refs = []
                    for row, _tuid in scent_ref_rows:
                        # lire la valeur sélectionnée dans la combobox de cette ligne
                        try:
                            # enfants: [combobox, bouton Supprimer]; on lit la combobox
                            for child in row.winfo_children():
                                if isinstance(child, ttk.Combobox):
                                    label = child.get()
                                    target = None
                                    for lbl, tu in self.clue_options:
                                        if lbl == label:
                                            try:
                                                target = int(tu,0) if isinstance(tu,str) else int(tu)
                                            except Exception:
                                                target = None
                                            break
                                    if target is not None and not any(int(r.get('tuid'))==int(target) for r in refs):
                                        refs.append({'tuid': int(target)})
                                    break
                        except Exception:
                            continue
                    d['instance_references'] = refs
                    try:
                        d['count'] = int(len(refs))
                    except Exception:
                        pass

            # Write JSON after all mutations
            with open(new_path, 'w', encoding='utf-8') as f:
                json.dump(d, f, indent=2, ensure_ascii=False)
            # Auto-générer instance.lua à la racine d'extraction
            try:
                from tools.generate_instance_handles_lua import generate_instance_handles_lua
                if self.extract_dir and os.path.isdir(self.extract_dir):
                    generate_instance_handles_lua(self.extract_dir, os.path.join(self.extract_dir, 'instance.lua'))
            except Exception:
                pass
            it['path'] = new_path
            it['data'] = d
            messagebox.showinfo("Enregistré", "Modifications enregistrées")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def _next_free_tuid(self) -> int:
        seen = set()
        for it in self.instances:
            v = it['data'].get('tuid', 0)
            try:
                seen.add(int(v, 0) if isinstance(v, str) else int(v))
            except Exception:
                pass
        x = max(seen) + 1 if seen else 1
        while x in seen:
            x += 1
        return x

    def duplicate_current(self):
        it = self._current_item()
        if not it:
            return
        d = json.loads(json.dumps(it['data']))
        d['tuid'] = self._next_free_tuid()
        # nouveau nom
        name = (d.get('name') or 'Instance') + "_copy"
        d['name'] = name
        base_dir = os.path.dirname(it['path'])
        # chemin
        base_name = sanitize_name(name)
        new_json = os.path.join(base_dir, f"{base_name}.{it['type']}.json")
        # ensure unique filename if already exists
        if os.path.exists(new_json):
            idx = 2
            while True:
                candidate = os.path.join(base_dir, f"{base_name}_{idx}.{it['type']}.json")
                if not os.path.exists(candidate):
                    new_json = candidate
                    break
                idx += 1
        # copier subfiles si présent
        s_old = sanitize_name(it['data'].get('name') or '')
        s_new = sanitize_name(name)
        for suf in ('host', 'local'):
            oldp = os.path.join(base_dir, f"{s_old}_CLASS.{suf}.dat")
            newp = os.path.join(base_dir, f"{s_new}_CLASS.{suf}.dat")
            try:
                if os.path.isfile(oldp) and not os.path.exists(newp):
                    with open(oldp, 'rb') as fsrc, open(newp, 'wb') as fdst:
                        fdst.write(fsrc.read())
            except Exception:
                pass
        # Si on duplique un Clue: dupliquer aussi le Volume lié (s'il existe)
        if it['type'] == 'clue':
            try:
                vol_tuid = it['data'].get('volume_tuid')
                if vol_tuid is not None:
                    v_int = int(vol_tuid, 0) if isinstance(vol_tuid, str) else int(vol_tuid)
                    # retrouver l'instance volume
                    vol_inst = None
                    for cand in self.instances:
                        if cand['type'] == 'volume':
                            try:
                                cand_tuid = cand['data'].get('tuid')
                                cand_int = int(cand_tuid, 0) if isinstance(cand_tuid, str) else int(cand_tuid)
                                if cand_int == v_int:
                                    vol_inst = cand
                                    break
                            except Exception:
                                continue
                    if vol_inst:
                        # cloner volume avec nouveau TUID et nom dérivé
                        new_vol = json.loads(json.dumps(vol_inst['data']))
                        new_vol_tuid = self._next_free_tuid()
                        new_vol['tuid'] = new_vol_tuid
                        new_vol['name'] = (new_vol.get('name') or 'Volume') + "_copy"
                        vol_dir = os.path.dirname(vol_inst['path'])
                        new_vol_path = os.path.join(vol_dir, f"{sanitize_name(new_vol['name'])}.volume.json")
                        with open(new_vol_path, 'w', encoding='utf-8') as vf:
                            json.dump(new_vol, vf, indent=2, ensure_ascii=False)
                        # mettre à jour le clue cloné pour pointer vers le nouveau volume
                        d['volume_tuid'] = new_vol_tuid
            except Exception:
                pass
        try:
            with open(new_json, 'w', encoding='utf-8') as f:
                json.dump(d, f, indent=2, ensure_ascii=False)
            self.reload_instances()
            # Sélectionner automatiquement la nouvelle instance dans l'arbre
            try:
                # Rechercher par TUID (plus robuste que le chemin)
                target_tuid = d.get('tuid')
                target_node = None
                for nid, inst in self.node_to_instance.items():
                    try:
                        tu = inst['data'].get('tuid')
                        tu_int = int(tu, 0) if isinstance(tu, str) else int(tu)
                        if tu_int == int(target_tuid):
                            target_node = nid
                            break
                    except Exception:
                        continue
                if target_node:
                    self.nav_tree.selection_set(target_node)
                    self.nav_tree.see(target_node)
                    self.on_select()
            except Exception:
                pass
            messagebox.showinfo("Duplication", f"Créé: {new_json}")
        except Exception as e:
            messagebox.showerror("Erreur duplication", str(e))

    def create_new_clue(self):
        if not self.extract_dir:
            return
        # créer un Clue minimal dans le dossier de l'item courant ou à la racine
        folder = os.path.dirname(self._current_item()['path']) if self._current_item() else self.extract_dir
        tuid = self._next_free_tuid()
        name = f"Clue_{tuid}"
        d = {
            'name': name,
            'tuid': tuid,
            'zone': 0,
            'class_id': 0,
            'volume_tuid': 0,
        }
        p = os.path.join(folder, f"{sanitize_name(name)}.clue.json")
        try:
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(d, f, indent=2, ensure_ascii=False)
            # créer subfile vide (host) pour que le rebuilder puisse lier si besoin
            hostp = os.path.join(folder, f"{sanitize_name(name)}_CLASS.host.dat")
            with open(hostp, 'wb') as f:
                f.write(b'')
            self.reload_instances()
            messagebox.showinfo("Nouveau Clue", f"Créé: {p}")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))


def launch(initial_dir: str | None = None):
    app = EditorApp()
    if initial_dir and os.path.isdir(initial_dir):
        app.extract_dir = initial_dir
        app.reload_instances()
    app.mainloop()


if __name__ == '__main__':
    launch()


