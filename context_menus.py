"""Shared lifecycle for temporary Tk context menus."""


def show_context_menu(menu, event):
    menu.bind('<Unmap>', lambda event: menu.after_idle(menu.destroy))
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()
    return 'break'
