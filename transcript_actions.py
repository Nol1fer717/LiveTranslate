"""Actions shared by the live transcript and saved history."""
import tkinter as tk
from theme_manager import palette_for

UNAVAILABLE = {
    'Не удалось перевести фразу. Исходный текст сохранён.',
    'Немецкий перевод не установлен. Запустите установщик снова и выберите немецкий язык.',
    'Перевод для этого языка не установлен.',
}


def can_copy_translation(text):
    return bool(text and text.strip() and text.strip() not in UNAVAILABLE)


def copy_translation(widget, text, notify=None):
    if not can_copy_translation(text):
        return
    widget.clipboard_clear()
    widget.clipboard_append(text)
    if notify:
        notify('Перевод скопирован')


def add_copy_button(widget, text, notify=None):
    if not can_copy_translation(text):
        return None
    # Keep the button's text as its semantic label; compound='none' displays
    # only the image while retaining the label for native accessibility APIs.
    palette = palette_for(widget)
    button = tk.Button(widget, text='Копировать перевод', compound='none', takefocus=True,
                       bg=widget.cget('bg'), fg=palette['MUTED'], relief='flat', borderwidth=0,
                       highlightthickness=1, highlightcolor=palette['ACCENT'], cursor='hand2',
                       activebackground=palette['HOVER'], activeforeground=palette['TEXT'],
                       command=lambda: copy_translation(widget, text, notify))
    def draw_icon():
        scale = max(1.0, float(button.tk.call('tk', 'scaling')) / (96 / 72))
        size = round(18 * scale)
        image = tk.PhotoImage(master=button, width=size, height=size)
        color = button.cget('fg')
        def rect(x1, y1, x2, y2):
            image.put(color, to=(round(x1*scale), round(y1*scale), round(x2*scale), round(y2*scale)))
        for x, y in ((3, 2), (6, 5)):
            rect(x,y,x+8,y+1); rect(x,y,x+1,y+10)
            rect(x,y+9,x+8,y+10); rect(x+7,y,x+8,y+10)
        button._copy_icon = image
        button.configure(image=image)
    button._update_copy_icon = draw_icon
    draw_icon()
    tooltip = {'job': None, 'window': None}
    def hide_tooltip(event=None):
        if tooltip['job'] is not None:
            button.after_cancel(tooltip['job']); tooltip['job'] = None
        if tooltip['window'] is not None:
            tooltip['window'].destroy(); tooltip['window'] = None
    def show_tooltip():
        tooltip['job'] = None
        if not button.winfo_exists(): return
        tip = tk.Toplevel(button); tip.wm_overrideredirect(True)
        tip.wm_geometry(f'+{button.winfo_rootx()}+{button.winfo_rooty() + button.winfo_height() + 4}')
        tk.Label(tip, text='Копировать перевод', bg=palette['FIELD'], fg=palette['TEXT'],
                 relief='solid', borderwidth=1, padx=6, pady=3).pack()
        tooltip['window'] = tip
    def schedule_tooltip(event):
        hide_tooltip()
        tooltip['job'] = button.after(500, show_tooltip)
    button.bind('<Enter>', schedule_tooltip)
    button.bind('<FocusIn>', schedule_tooltip)
    button.bind('<Leave>', hide_tooltip)
    button.bind('<FocusOut>', hide_tooltip)
    button.bind('<Destroy>', hide_tooltip)
    button.bind('<Return>', lambda event: (button.invoke(), 'break')[1])
    button.bind('<KeyPress-space>', lambda event: (button.invoke(), 'break')[1])
    button.bind('<KeyRelease-space>', lambda event: 'break')
    widget.tag_configure('copy_action', justify='right')
    start = widget.index('end-1c')
    widget.window_create('end', window=button, padx=4, pady=4)
    widget.insert('end', '\n', 'copy_action')
    widget.tag_add('copy_action', start, 'end-1c')
    return button
