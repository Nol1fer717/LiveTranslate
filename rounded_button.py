"""Small rounded backgrounds on ordinary, keyboard-accessible Tk buttons."""
import tkinter as tk
from tkinter import font as tkfont

from theme_manager import palette_for


class RoundedButton(tk.Button):
    def __init__(self, parent, **options):
        self._ready = False
        self._fill = options.pop('bg', options.pop('background', parent.cget('bg')))
        self._hover = options.pop('activebackground', self._fill)
        self._outer = parent.cget('bg')
        self._pad_x = int(options.pop('padx', 10))
        self._pad_y = int(options.pop('pady', 6))
        self._inside = False
        self._image_key = None
        options.update(background=self._outer, activebackground=self._outer, relief='flat',
                       borderwidth=0, highlightthickness=1, highlightbackground=self._outer,
                       highlightcolor=palette_for(parent)['ACCENT'], compound='center', padx=0, pady=0)
        super().__init__(parent, **options)
        self._ready = True
        self.bind('<Enter>', self._enter, add='+')
        self.bind('<Leave>', self._leave, add='+')
        self.bind('<Configure>', self._resize, add='+')
        self._paint()

    def configure(self, cnf=None, **options):
        if not getattr(self, '_ready', False) or (cnf is not None and not isinstance(cnf, dict)):
            return super().configure(cnf, **options)
        if cnf:
            options = {**cnf, **options}
        fill = options.pop('bg', options.pop('background', None))
        hover = options.pop('activebackground', None)
        if fill is not None:
            self._fill = fill
        if hover is not None:
            self._hover = hover
        result = super().configure(**options)
        if fill is not None or hover is not None or 'text' in options or 'state' in options:
            self._paint()
        return result

    config = configure

    def _enter(self, event):
        self._inside = True
        self._paint()

    def _leave(self, event):
        self._inside = False
        self._paint()

    def _resize(self, event):
        self._paint(event.width - 2, event.height - 2)

    def _paint(self, width=0, height=0):
        face = tkfont.Font(root=self, font=self.cget('font'))
        width = max(width, self.winfo_width() - 2)
        height = max(height, self.winfo_height() - 2)
        width = max(width, face.measure(self.cget('text')) + self._pad_x * 2, 20)
        height = max(height, face.metrics('linespace') + self._pad_y * 2, 20)
        color = self._hover if self._inside and str(self.cget('state')) != 'disabled' else self._fill
        key = (width, height, color, self._outer)
        if key == self._image_key:
            return
        self._image_key = key
        picture = tk.PhotoImage(master=self, width=width, height=height)
        picture.put(color, to=(0, 0, width, height))
        radius = min(7, width // 2, height // 2)
        front = tuple(value // 257 for value in self.winfo_rgb(color))
        back = tuple(value // 257 for value in self.winfo_rgb(self._outer))
        for y in range(radius):
            for x in range(radius):
                covered = sum((x + (sx + .5) / 4 - radius) ** 2 +
                              (y + (sy + .5) / 4 - radius) ** 2 <= radius ** 2
                              for sx in range(4) for sy in range(4))
                if covered == 16:
                    continue
                blended = '#%02x%02x%02x' % tuple(round((f * covered + b * (16 - covered)) / 16)
                                                   for f, b in zip(front, back))
                for px, py in ((x, y), (width - 1 - x, y), (x, height - 1 - y), (width - 1 - x, height - 1 - y)):
                    picture.put(blended, (px, py))
        self._rounded_image = picture
        super().configure(image=picture)
