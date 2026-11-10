"""Shared visual tokens for LiveTranslate's desktop interface."""
BG = '#f3f6f3'
CARD = '#ffffff'
FIELD = '#edf3ef'
TEXT = '#182e27'
MUTED = '#526960'
ACCENT = '#126e59'
ACCENT_DARK = '#0c5747'
ACCENT_SOFT = '#deeee7'
BORDER = '#d9e4dd'
HOVER = '#e7f0ea'
SELECTION = '#c4e4d6'
ON_ACCENT = '#ffffff'

# Immutable baseline for palette construction, unaffected by runtime themes.
LIGHT_PALETTE = {name: globals()[name] for name in (
    'BG', 'CARD', 'FIELD', 'TEXT', 'MUTED', 'ACCENT', 'ACCENT_DARK',
    'ACCENT_SOFT', 'BORDER', 'HOVER', 'SELECTION', 'ON_ACCENT')}
