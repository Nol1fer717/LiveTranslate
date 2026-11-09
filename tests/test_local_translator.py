import os, tempfile, time, tkinter as tk, unittest
from unittest.mock import patch
from types import SimpleNamespace
from test_note_mouse import FakeMenu
from app import App
from translator_ui import prepare_translation_text, detect_text_language

class LocalTranslatorTests(unittest.TestCase):
 def test_spoken_russian_preparation_preserves_context_and_profanity(self):
  from engine import prepare_spoken_russian
  self.assertEqual(prepare_spoken_russian('Походу это хуёво работает'), 'похоже это пиздец как плохо работает')
  self.assertEqual(prepare_spoken_russian('работает хуево'), 'работает пиздец как плохо')
  self.assertEqual(prepare_spoken_russian('идём по походу реки'), 'идём по походу реки')
  self.assertEqual(prepare_spoken_russian('это охуенно работает'), 'это охуенно работает')

 def test_local_model_translates_poor_performance_as_negative(self):
  from engine import DATA, Language
  if not (DATA / 'translate-ru_en-1_9').is_dir(): self.skipTest('Russian model is not installed')
  result = Language('ru', load_speech=False).translate('Он хуёво работает.').lower()
  self.assertTrue('bad' in result or "doesn't work" in result or 'poor' in result, result)
  self.assertIn('fuck', result)

 def test_detects_russian_english_and_german_and_rejects_ambiguous_scripts(self):
  from langid.langid import LanguageIdentifier, model
  identifier=LanguageIdentifier.from_modelstring(model, norm_probs=True); identifier.set_languages(['en','de'])
  for text, expected in [('что случилось','ru'), ('what happened','en'), ('Guten Tag','de'), ('Hallo','de'), ('Danke','de'), ('wie geht es dir','de'), ('Ich möchte lernen','de'), ('123',None), ('hello привет',None)]:
   with self.subTest(text=text): self.assertEqual(detect_text_language(text,identifier)[0],expected)

 def test_unpunctuated_conversation_questions_are_prepared_without_changing_statements(self):
  for source, original, expected in [
   ('ru', 'как дела', 'как дела?'), ('ru_de', 'Привет как дела', 'Привет как дела?'),
   ('en', 'what up', 'what up?'), ('en', 'how are you', 'how are you?'),
   ('en', 'what up?', 'what up?'), ('ru', 'как дела!', 'как дела!'),
   ('ru', 'я знаю как дела', 'я знаю как дела'), ('en', 'I wonder what happened', 'I wonder what happened')]:
   with self.subTest(source=source, original=original):
    self.assertEqual(prepare_translation_text(original, source), expected)

 def test_clipboard_shortcuts_work_with_non_english_keysyms(self):
  with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LOCALAPPDATA':tmp,'LIVETRANSLATE_DOCUMENTS':os.path.join(tmp,'docs')}), patch('app.devices',return_value=([],[])):
   root=tk.Tk(); app=App(root); ui=app.translator
   ui.page.master.select(ui.page); root.update()
   ui.input.focus_force(); root.update()
   ui.input.insert('1.0','Привет'); ui.input.tag_add('sel','1.0','1.6')
   ui.input.edit_separator()
   self.assertEqual(ui.clipboard_shortcut(SimpleNamespace(widget=ui.input,keycode=67,keysym='Cyrillic_es',state=4)), 'break')
   self.assertEqual(root.clipboard_get(), 'Привет')
   ui.input.mark_set('insert','end-1c'); ui.input.tag_remove('sel','1.0','end')
   self.assertEqual(ui.clipboard_shortcut(SimpleNamespace(widget=ui.input,keycode=86,keysym='Cyrillic_em',state=4)), 'break')
   self.assertEqual(ui.input.get('1.0','end-1c'), 'ПриветПривет')
   self.assertEqual(ui.clipboard_shortcut(SimpleNamespace(widget=ui.input,keycode=90,keysym='Cyrillic_ya',state=4)), 'break')
   self.assertEqual(ui.input.get('1.0','end-1c'), 'Привет')
   root.update(); ui.set_output('Hello'); ui.output.focus_force(); root.update(); ui.output.tag_add('sel','1.0','1.5')
   self.assertEqual(ui.clipboard_shortcut(SimpleNamespace(widget=ui.output,keycode=67,keysym='Cyrillic_es',state=4)), 'break')
   self.assertEqual(root.clipboard_get(), 'Hello')
   self.assertIsNone(ui.clipboard_shortcut(SimpleNamespace(widget=ui.output,keycode=86,state=4)))
   self.assertIsNone(ui.clipboard_shortcut(SimpleNamespace(widget=ui.output,keycode=90,state=4)))
   self.assertIsNone(ui.clipboard_shortcut(SimpleNamespace(widget=ui.input,keycode=67,state=12)))
   app.finish_close()

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
   ui.direction.set('Русский → Немецкий'); ui.direction_selected(); ui.input.insert('1.0','Привет'); root.update(); ui.submit()
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

 def test_detected_direction_updates_without_changing_auto_mode(self):
  class Model:
   def __init__(self, source, load_speech=True): self.source=source
   def translate(self, text): return 'result:' + text
  with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LOCALAPPDATA':tmp,'LIVETRANSLATE_DOCUMENTS':os.path.join(tmp,'docs')}), patch('app.devices',return_value=([],[])), patch('translator_ui.Language',Model):
   root=tk.Tk(); root.withdraw(); app=App(root); ui=app.translator
   self.assertEqual(ui.direction.get(), 'Автоматически')
   for text, label in [('hello', 'Английский → Русский'), ('привет', 'Русский → Английский')]:
    ui.input.delete('1.0','end'); ui.input.insert('1.0',text); root.update(); ui.submit()
    deadline=time.monotonic()+5
    while time.monotonic()<deadline and ui.direction.get()!=label: root.update(); time.sleep(.02)
    self.assertEqual(ui.direction.get(),label)
    self.assertEqual(ui.direction_mode,'auto')
   ui.input.delete('1.0','end'); root.update()
   self.assertEqual(ui.direction.get(),'Автоматически')
   ui.direction.set('Русский → Немецкий'); ui.direction_selected()
   self.assertEqual(ui.direction_mode,'ru_de')
   ui.direction.set('Автоматически'); ui.direction_selected()
   self.assertEqual(ui.direction_mode,'auto')
   app.finish_close()
if __name__=='__main__': unittest.main()
