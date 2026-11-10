"""Windows keyboard shortcuts independent of the active keyboard layout."""
import tkinter as tk


class UndoEntry(tk.Entry):
    """Entry with a bounded per-note undo stack, reset on note switches."""
    def __init__(self, parent, **options):
        self._value = tk.StringVar(master=parent)
        options['textvariable'] = self._value
        super().__init__(parent, **options)
        self._previous = self._value.get()
        self._undo = []
        self._restoring = False
        self._value.trace_add('write', self._record)

    def _record(self, *_):
        current = self._value.get()
        if not self._restoring and current != self._previous:
            self._undo.append(self._previous)
            self._undo = self._undo[-100:]
        self._previous = current

    def reset_undo(self):
        self._undo.clear()
        self._previous = self._value.get()

    def undo(self):
        if self._undo:
            self._restoring = True
            try:
                self._value.set(self._undo.pop())
                self.icursor('end')
                self.event_generate('<<EntryUndo>>')
            finally:
                self._restoring = False


def clipboard_shortcut(event):
    widget = event.widget
    if event.state & (0x0008 | 0x20000):  # Tk Mod1 and Windows Alt/AltGr.
        return None
    key = event.keycode
    if key not in (65, 67, 86, 88, 90):
        return None
    readonly = str(widget.cget('state')) in ('disabled', 'readonly')
    if readonly and key in (86, 88, 90):
        return None
    is_text = isinstance(widget, tk.Text)
    if key == 90 and not is_text:
        if isinstance(widget, UndoEntry):
            widget.undo()
            return 'break'
        return None
    if key == 65:
        if is_text:
            widget.tag_add('sel', '1.0', 'end-1c')
        else:
            widget.selection_range(0, 'end')
        return 'break'
    if key == 67:
        try:
            text = widget.get('sel.first', 'sel.last') if is_text else widget.selection_get()
            widget.clipboard_clear()
            widget.clipboard_append(text)
        except tk.TclError:
            pass
        return 'break'
    widget.focus_set()
    widget.event_generate({86: '<<Paste>>', 88: '<<Cut>>', 90: '<<Undo>>'}[key])
    return 'break'


def bind_shortcuts(widget):
    widget.bind('<Control-KeyPress>', clipboard_shortcut)
