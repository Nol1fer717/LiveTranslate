"""Runtime palette application for the existing Tk interface."""
import tkinter as tk
from tkinter import ttk
from theme import LIGHT_PALETTE

LIGHT = dict(LIGHT_PALETTE)
DARK = {'BG':'#101b1a','CARD':'#192927','FIELD':'#263b37','TEXT':'#e5f3ec',
        'MUTED':'#b4cbc0','ACCENT':'#79e0bf','ACCENT_DARK':'#36ad8a',
        'ACCENT_SOFT':'#29443b','BORDER':'#49635a','HOVER':'#365149','SELECTION':'#406f60','ON_ACCENT':'#101b1a'}


def system_theme():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
            return 'light' if winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] else 'dark'
    except (ImportError, OSError):
        return 'light'


def palette_for(widget):
    return getattr(widget._root(), '_livetranslate_palette', LIGHT)


def apply_palette(root, old, new):
    mapping = {old[key].lower(): new[key] for key in old if key != 'ON_ACCENT' and old[key].lower() != new[key].lower()}
    def mapped(widget, value):
        try:
            rgb = widget.winfo_rgb(value)
            normalized = '#%02x%02x%02x' % tuple(component // 257 for component in rgb)
            return mapping.get(normalized)
        except tk.TclError:
            return None
    palette = palette_for(root)
    if palette is not LIGHT:
        palette.clear()
        palette.update(new)

    def walk(widget):
        if isinstance(widget, ttk.Combobox):
            try:
                popdown = widget.tk.call('ttk::combobox::PopdownWindow', str(widget))
                widget.tk.call(f'{popdown}.f.l', 'configure', '-background', new['FIELD'],
                               '-foreground', new['TEXT'], '-selectbackground', new['SELECTION'],
                               '-selectforeground', new['TEXT'])
            except tk.TclError:
                pass
        if not isinstance(widget, ttk.Widget):
            changes = {}
            for option in ('background', 'foreground', 'activebackground', 'activeforeground',
                           'disabledforeground', 'disabledbackground', 'selectbackground',
                           'selectforeground', 'insertbackground', 'highlightbackground',
                           'highlightcolor', 'selectcolor', 'troughcolor'):
                try:
                    if hasattr(widget, '_paint') and option in ('background', 'activebackground'):
                        continue
                    value = mapped(widget, str(widget.cget(option)))
                    if value is not None: changes[option] = value
                except tk.TclError:
                    pass
            if changes:
                try: widget.configure(**changes)
                except tk.TclError: pass
        for attribute in ('_fill', '_hover', '_outer'):
            value = mapped(widget, str(getattr(widget, attribute, '')))
            if value is not None: setattr(widget, attribute, value)
        if hasattr(widget, '_paint'):
            tk.Button.configure(widget, background=widget._outer, activebackground=widget._outer)
            widget._image_key = None
            widget._paint()
        if hasattr(widget, '_update_copy_icon'):
            widget._update_copy_icon()
        if getattr(widget, '_accent_action', False):
            widget.configure(fg=new['ON_ACCENT'], activeforeground=new['ON_ACCENT'])
        if isinstance(widget, tk.Text):
            for tag in widget.tag_names():
                for option in ('foreground', 'background'):
                    try:
                        value = mapped(widget, str(widget.tag_cget(tag, option)))
                        if value is not None: widget.tag_configure(tag, **{option: value})
                    except tk.TclError: pass
        for child in widget.winfo_children(): walk(child)
    walk(root)
    style = ttk.Style(root)
    style.configure('Dark.TCombobox', fieldbackground=new['FIELD'], background=new['FIELD'],
                    foreground=new['TEXT'], arrowcolor=new['MUTED'], bordercolor=new['BORDER'],
                    lightcolor=new['BORDER'], darkcolor=new['BORDER'])
    style.map('Dark.TCombobox', fieldbackground=[('readonly', new['FIELD'])], foreground=[('readonly', new['TEXT'])])
    style.configure('Vertical.TScrollbar', background=new['BORDER'], troughcolor=new['CARD'],
                    bordercolor=new['CARD'], arrowcolor=new['MUTED'])
    style.configure('Modern.TNotebook', background=new['BG'])
