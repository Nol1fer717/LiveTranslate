import os, tempfile, time, tkinter as tk, unittest
from unittest.mock import patch
from types import SimpleNamespace
from test_note_mouse import FakeMenu
from app import App

class LocalTranslatorTests(unittest.TestCase):
 def test_context_menu_allows_paste_in_input_and_copy_in_output(self):
  with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LOCALAPPDATA':tmp,'LIVETRANSLATE_DOCUMENTS':os.path.join(tmp,'docs')}), patch('app.devices',return_value=([],[])):
   root=tk.Tk(); root.withdraw(); app=App(root); ui=app.translator
   ui.input.insert('1.0','hello'); ui.input.tag_add('sel','1.0','1.5')
   with patch('translator_ui.tk.Menu',FakeMenu), patch.object(ui.input,'clipboard_get',return_value='paste'):
    ui.context_menu(SimpleNamespace(widget=ui.input,x=0,y=0,x_root=0,y_root=0))
   self.assertEqual([item['label'] for item in FakeMenu.created.items],['Вырезать','Копировать','Вставить'])
   self.assertEqual([item['state'] for item in FakeMenu.created.items],['normal','normal','normal'])
   ui.set_output('Привет'); ui.output.tag_add('sel','1.0','1.6')
   with patch('translator_ui.tk.Menu',FakeMenu):
    ui.context_menu(SimpleNamespace(widget=ui.output,x=0,y=0,x_root=0,y_root=0))
   self.assertEqual([(item['label'],item['state']) for item in FakeMenu.created.items],[('Копировать','normal')])
   app.finish_close()

 def test_missing_german_component_reports_how_to_install(self):
  from pathlib import Path
  with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LOCALAPPDATA':tmp,'LIVETRANSLATE_DOCUMENTS':os.path.join(tmp,'docs')}), patch('app.devices',return_value=([],[])), patch('translator_ui.DATA',Path(tmp)):
   root=tk.Tk(); root.withdraw(); app=App(root); ui=app.translator
   ui.direction.set('Русский → Немецкий'); ui.input.insert('1.0','Привет'); root.update(); ui.submit()
   deadline=time.monotonic()+4
   while time.monotonic()<deadline and 'не установлена' not in ui.status.get(): root.update(); time.sleep(.02)
   self.assertIn('установщике',ui.status.get()); app.finish_close()

 def test_russian_to_german_direction_uses_local_pivot(self):
  from engine import DATA, EnglishToGerman, Language
  if not (DATA / 'translate-en_de-1_3').is_dir(): self.skipTest('optional German model is not installed')
  text = EnglishToGerman(Language('ru', load_speech=False)).translate('Привет, как дела?')
  self.assertTrue(text.strip())

 def test_automatic_translation_discards_outdated_result(self):
  class Model:
   def __init__(self, source, load_speech=True): pass
   def translate(self, text):
    if text == 'old': time.sleep(.3)
    return 'result:' + text
  with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LOCALAPPDATA':tmp,'LIVETRANSLATE_DOCUMENTS':os.path.join(tmp,'docs')}), patch('app.devices',return_value=([],[])), patch('translator_ui.Language',Model):
   root=tk.Tk(); root.withdraw(); app=App(root); ui=app.translator
   ui.input.insert('1.0','old'); root.update(); ui.submit(); time.sleep(.05)
   ui.input.delete('1.0','end'); ui.input.insert('1.0','new'); root.update(); ui.submit()
   deadline=time.monotonic()+4
   while time.monotonic()<deadline and ui.output.get('1.0','end-1c')!='result:new': root.update(); time.sleep(.02)
   self.assertEqual(ui.output.get('1.0','end-1c'),'result:new')
   ui.input.delete('1.0','end'); root.update(); self.assertEqual(ui.output.get('1.0','end-1c'),'')
   app.finish_close()
if __name__=='__main__': unittest.main()
