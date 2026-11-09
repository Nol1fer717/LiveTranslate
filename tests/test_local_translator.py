import os, tempfile, time, tkinter as tk, unittest
from unittest.mock import patch
from app import App

class LocalTranslatorTests(unittest.TestCase):
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
