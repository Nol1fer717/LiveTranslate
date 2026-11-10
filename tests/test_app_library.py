import os
import tempfile
import time
import tkinter as tk
import threading
import wave
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from app import App

class AppLibraryTests(unittest.TestCase):
    def test_palette_changes_only_current_window_without_module_mutation(self):
        import theme
        original=theme.BG
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root)
            try:
                app.theme_choice.set('Тёмная'); app.change_theme()
                self.assertEqual(theme.BG, original)
                self.assertEqual(app.palette['BG'], '#101b1a')
                self.assertIs(app.library.palette, app.palette)
                self.assertIs(app.translator.palette, app.palette)
                app.theme_choice.set('Светлая'); app.change_theme()
                self.assertEqual(theme.BG, original)
                self.assertEqual(app.palette['BG'], '#f3f6f3')
            finally: app.finish_close()
    def test_close_cancels_remaining_tk_callbacks(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root)
            job=root.after(30000, lambda: None)
            pending=[]
            original_destroy=root.destroy
            def inspect():
                pending.extend(root.tk.splitlist(root.tk.call('after', 'info')))
                original_destroy()
            with patch.object(root, 'destroy', side_effect=inspect):
                self.assertTrue(app.finish_close())
            self.assertNotIn(job, pending)
            self.assertFalse(pending)
    def test_growing_preview_keeps_translation_until_new_result(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root)
            try:
                def poll_once():
                    root.after_cancel(app.poll_job); app.poll()
                app.events.put(('preview', 0, ('hello', 'привет', 'EN'))); poll_once()
                app.events.put(('preview', 0, ('hello friend', '', 'EN'))); poll_once()
                visible=app.history.get('1.0', 'end-1c')
                self.assertIn('привет', visible); self.assertIn('Переводим', visible)
                app.events.put(('preview', 0, ('hello friend', 'привет друг', 'EN'))); poll_once()
                self.assertIn('привет друг', app.history.get('1.0', 'end-1c'))
                app.events.put(('preview', 0, ('different', '', 'EN'))); poll_once()
                self.assertNotIn('привет друг', app.history.get('1.0', 'end-1c'))
            finally: app.finish_close()
    def test_double_click_does_not_immediately_stop_new_session(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([{'name':'Microphone'}], [{'name':'Speakers'}])), patch('app.base_models_ready', return_value=True), patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root)
            def session(selected, folder, stop, detect):
                stop.wait(3); app.events.put(('done',None,None))
            app.session=session
            try:
                app.start.invoke(); current=app.stop
                self.assertIsNotNone(current)
                app.start.invoke()
                self.assertFalse(current.is_set())
                current.set()
                deadline=time.monotonic()+3
                while app.stop is not None and time.monotonic()<deadline:
                    root.update(); time.sleep(.01)
            finally:
                if app.stop: app.stop.set()
                app.finish_close()
    def test_stale_model_marker_is_verified_off_the_ui_thread(self):
        import hashlib, json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            data=Path(directory)/'data'; data.mkdir(); (data/'model.bin').write_bytes(b'valid')
            (data/'.models-installing').touch(); manifest=Path(directory)/'packages.json'
            manifest.write_text(json.dumps([{'task':None,'files':[{'path':'data/model.bin','sha256':hashlib.sha256(b'valid').hexdigest()}]}]),encoding='utf-8')
            with patch('app.DATA', data), patch('model_readiness.manifest_path', return_value=manifest), patch('model_readiness.downloader_running', return_value=False):
                root=tk.Tk(); app=App(root)
                try:
                    deadline=time.monotonic()+3
                    while not app.models_ready and time.monotonic()<deadline:
                        root.update(); time.sleep(.02)
                    self.assertTrue(app.models_ready)
                    self.assertTrue((data/'.models-installing').exists())
                finally: app.finish_close()
    def test_missing_speaker_model_disables_saved_speaker_setting(self):
        from pathlib import Path
        from settings import save_preferences
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('app.SPEAKER_PATH', Path(directory)/'missing'), patch('theme_manager.system_theme', return_value='light'):
            save_preferences(Path(directory)/'Documents'/'LiveTranslate'/'settings.json', {'identify_speakers':True})
            root=tk.Tk(); app=App(root)
            try:
                self.assertFalse(app.identify.get())
                self.assertEqual(str(app.speaker_check.cget('state')), 'disabled')
            finally: app.finish_close()
    def test_new_phrase_stays_visible_at_bottom_with_selection(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root)
            try:
                app.entries=[dict(time='00:00',index=0,speaker=None,**{'from':'EN','to':'RU','source':f'Original {i}','target':f'Перевод {i}'}) for i in range(50)]
                app.render(); root.update(); app.history.see('end'); root.update()
                app.history.tag_add('sel','3.0','3.4')
                app.entries.append(dict(time='00:01',index=0,speaker=None,**{'from':'EN','to':'RU','source':'Last','target':'Последнее'}))
                app.render(); root.update()
                self.assertGreaterEqual(app.history.yview()[1], .999)
                self.assertTrue(app.history.tag_ranges('sel'))
            finally: app.finish_close()
    def test_confirmed_discard_does_not_block_close_after_stop(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root)
            try:
                app.stop=threading.Event(); app.failure=''; app.unrecognized_audio=[(0,b'\x01\x00')]
                with patch('app.messagebox.askyesno', return_value=True) as confirm:
                    app.close()
                    self.assertEqual(app.unrecognized_audio, [])
                    app.events.put(('done',None,None))
                    with patch.object(app,'finish_close',return_value=True) as finish:
                        app.poll(); finish.assert_called_once()
                    confirm.assert_called_once()
            finally:
                app.stop=None; app.closing=False; app.finish_close()
    def test_duplicate_device_names_require_explicit_reselection(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([{'name':'Same'}, {'name':'Same'}], [{'name':'Speakers'}])), patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root)
            app.device_boxes[0].current(1); app.save_device_settings(); app.finish_close()
            root=tk.Tk(); app=App(root)
            try:
                self.assertEqual(app.device_boxes[0].current(), -1)
                self.assertEqual(app.device_boxes[0].get(), '')
            finally: app.finish_close()
    def test_close_waits_for_user_when_recovery_audio_arrives_during_stop(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root)
            try:
                app.stop=threading.Event(); app.closing=True
                app.events.put(('unrecognized_audio', 0, b'\x01\x00'))
                app.events.put(('done', None, None))
                app.poll()
                self.assertTrue(root.winfo_exists())
                self.assertFalse(app.closing)
                self.assertEqual(app.unrecognized_audio, [(0, b'\x01\x00')])
                self.assertEqual(str(app.recover_button['state']), 'normal')
            finally: app.finish_close()
    def test_unrecognized_fragment_is_saved_only_after_user_selects_folder(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root)
            try:
                app.unrecognized_audio.append((0, b'\x01\x00' * 100))
                with patch('app.filedialog.askdirectory', return_value=''):
                    app.save_unrecognized()
                self.assertEqual(len(app.unrecognized_audio), 1)
                with patch('app.filedialog.askdirectory', return_value=directory):
                    app.save_unrecognized()
                files=list(__import__('pathlib').Path(directory).glob('LiveTranslate-fragment-*.wav'))
                self.assertEqual(len(files), 1)
                with wave.open(str(files[0]), 'rb') as audio:
                    self.assertEqual(audio.readframes(100), b'\x01\x00' * 100)
                self.assertEqual(app.unrecognized_audio, [])
            finally: app.finish_close()
    def test_history_switch_discards_pending_batches(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root)
            try:
                first=app.storage.start_session('Микрофон'); second=app.storage.start_session('Микрофон')
                for n in range(45):
                    app.storage.add_phrase(first, dict(time='00:00', index=0, speaker=None, **{'from':'EN','to':'RU','source':f'OLD-{n}','target':'старое'}))
                app.storage.add_phrase(second, dict(time='00:00', index=0, speaker=None, **{'from':'EN','to':'RU','source':'NEW','target':'новое'}))
                library=app.library; library.session_ids=[first, second]
                library.session_list.delete(0, 'end'); library.session_list.insert('end', 'first', 'second')
                library.session_list.selection_set(0); library.show_session()
                library.session_list.selection_clear(0, 'end'); library.session_list.selection_set(1); library.show_session()
                time.sleep(.01); root.update()
                text=library.session_text.get('1.0', 'end-1c')
                self.assertIn('NEW', text); self.assertNotIn('OLD-', text)
            finally: app.finish_close()
    def test_history_copy_button_copies_only_translation(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root)
            try:
                session=app.storage.start_session('Микрофон')
                app.storage.add_phrase(session, dict(time='00:00', index=0, speaker='Голос 1', **{'from':'EN','to':'RU','source':'Hello','target':'Привет'}))
                app.storage.end_session(session); app.library.refresh_history(); root.update()
                buttons=app.library.session_text.winfo_children()
                self.assertEqual(len(buttons), 1); buttons[0].invoke()
                self.assertEqual(root.clipboard_get(), 'Привет')
                self.assertTrue(buttons[0].cget('image'))
                self.assertEqual(buttons[0].cget('compound'), 'none')
                index=app.library.session_text.index(str(buttons[0]))
                self.assertIn('copy_action', app.library.session_text.tag_names(index))
                self.assertEqual(app.library.session_text.tag_cget('copy_action', 'justify'), 'right')
                self.assertEqual(list(app.library.history_translations.values()), ['Привет'])
            finally: app.finish_close()
    def test_callback_error_opens_diagnostics_dialog_without_message(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root)
            try:
                app.report_ui_exception(ValueError, ValueError('secret'), None)
                dialogs = [child for child in root.winfo_children() if isinstance(child, tk.Toplevel)]
                self.assertEqual(len(dialogs), 1)
                self.assertEqual(dialogs[0].title(), 'Ошибка LiveTranslate')
                dialogs[0].destroy()
            finally: app.finish_close()
    def test_slow_stop_offers_explicit_close_without_starting_another_session(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root)
            try:
                app.stop = threading.Event()
                app.show_stop_warning()
                self.assertEqual(app.start.cget('text'), 'Закрыть приложение')
                self.assertIn('последняя фраза', app.status.get())
                self.assertFalse(app.stop.is_set())
            finally:
                app.stop = None; app.finish_close()
    def test_failed_microphone_does_not_stop_computer_source(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root); stop=threading.Event(); other_started=threading.Event()
            app.cache['en'] = SimpleNamespace(); app.current_split_level=5; app.current_quiet_voice=False
            class Audio:
                def __enter__(self): return self
                def __exit__(self, *args): pass
            def fake_capture(audio, device, language, index, source_stop, *args, **kwargs):
                if index == 0: raise RuntimeError('microphone failure')
                other_started.set()
                while not source_stop.is_set(): time.sleep(.01)
            try:
                with patch('app.pa.PyAudio', Audio), patch('app.capture', side_effect=fake_capture):
                    worker=threading.Thread(target=app.session, args=([(0, {}, 'en'), (1, {}, 'en')], None, stop, False))
                    worker.start(); self.assertTrue(other_started.wait(2))
                    time.sleep(.05); self.assertFalse(stop.is_set()); self.assertTrue(worker.is_alive())
                    stop.set(); worker.join(2); self.assertFalse(worker.is_alive())
                    messages=[]
                    while not app.events.empty(): messages.append(app.events.get())
                    self.assertTrue(any(kind == 'error' and index == 0 for kind, index, value in messages))
            finally:
                stop.set(); app.finish_close()
    def test_resize_keeps_bottom_and_preserves_scrolled_up_position(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root)
            try:
                app.entries = [dict(time='00:00', index=0, speaker=None, **{'from':'EN','to':'RU','source':f'Original {n}','target':f'Перевод {n}'}) for n in range(50)]
                app.render(); root.update(); app.history.see('end'); root.update()
                root.geometry('1000x900'); root.update()
                self.assertGreaterEqual(app.history.yview()[1], .999)
                app.history.yview_moveto(.3); root.update(); before=app.history.index('@0,0')
                root.geometry('1000x700'); root.update()
                self.assertEqual(app.history.index('@0,0'), before)
            finally: app.finish_close()
    def test_preview_update_keeps_final_translation_button(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root)
            try:
                app.entries = [dict(time='00:00', index=0, speaker=None, **{'from':'EN','to':'RU','source':'Hello','target':'Привет'})]
                app.render(); button=app.history.winfo_children()[0]
                app.previews[0] = ('First words', 'Первые слова', 'EN'); app.render_preview()
                app.previews[0] = ('More words', 'Больше слов', 'EN'); app.render_preview()
                self.assertTrue(button.winfo_exists())
                self.assertIn('Больше слов', app.history.get('1.0', 'end-1c'))
                self.assertNotIn('Первые слова', app.history.get('1.0', 'end-1c'))
            finally: app.finish_close()
    def test_theme_can_be_changed_and_restored(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root)
            app.theme_choice.set('Тёмная'); app.change_theme()
            self.assertEqual(app.current_palette['BG'], '#101b1a')
            self.assertEqual(app.start.cget('fg').lower(), app.current_palette['ON_ACCENT'])
            popdown=root.tk.call('ttk::combobox::PopdownWindow', str(app.theme_choice))
            self.assertEqual(root.tk.call(f'{popdown}.f.l', 'cget', '-background'), '#263b37')
            app.finish_close()
            root=tk.Tk(); app=App(root)
            try:
                self.assertEqual(app.theme_choice.get(), 'Тёмная')
                self.assertEqual(app.current_palette['BG'], '#101b1a')
                app.theme_choice.set('Светлая'); app.change_theme()
                self.assertEqual(app.current_palette['BG'], '#f3f6f3')
            finally:
                app.finish_close()
    def test_legacy_theme_label_remains_supported_and_saves_stable_key(self):
        from pathlib import Path
        from settings import save_preferences, read_preferences
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            path=Path(directory)/'Documents'/'LiveTranslate'/'settings.json'
            save_preferences(path, {'theme':'Тёмная'})
            root=tk.Tk(); app=App(root)
            try:
                self.assertEqual(app.theme_choice.get(), 'Тёмная')
                app.theme_choice.set('Светлая'); app.change_theme()
                self.assertEqual(read_preferences(path)['theme'], 'light')
            finally: app.finish_close()
    def test_copy_button_copies_only_final_translation(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])):
            root = tk.Tk(); app = App(root)
            try:
                app.entries = [dict(time='00:00', index=0, speaker=None, **{'from':'EN','to':'RU','source':'Hello', 'target':'Привет'})]
                app.previews[0] = ('Good morning', 'Доброе утро', 'EN')
                app.render(); root.update()
                buttons = app.history.winfo_children()
                self.assertEqual(len(buttons), 1)
                self.assertEqual(buttons[0].cget('text'), 'Копировать перевод')
                self.assertTrue(buttons[0].cget('image'))
                self.assertEqual(buttons[0].cget('compound'), 'none')
                button_index=app.history.index(str(buttons[0]))
                self.assertIn('copy_action', app.history.tag_names(button_index))
                self.assertEqual(app.history.tag_cget('copy_action', 'justify'), 'right')
                self.assertGreater(int(button_index.split('.')[0]), int(app.history.search('Привет', '1.0').split('.')[0]))
                buttons[0].invoke()
                self.assertEqual(root.clipboard_get(), 'Привет')
                root.clipboard_clear(); buttons[0].focus_force(); root.update()
                buttons[0].event_generate('<Return>'); root.update()
                self.assertEqual(root.clipboard_get(), 'Привет')
                root.clipboard_clear(); buttons[0].event_generate('<KeyPress-space>'); buttons[0].event_generate('<KeyRelease-space>'); root.update()
                self.assertEqual(root.clipboard_get(), 'Привет')
                app.entries.append(dict(time='00:01', index=0, speaker=None, **{'from':'EN','to':'RU','source':'Error','target':'Не удалось перевести фразу. Исходный текст сохранён.'}))
                app.render()
                self.assertEqual(len(app.history.winfo_children()), 1)
            finally:
                app.finish_close()
    def test_copy_actions_keep_translation_and_scroll_when_theme_changes(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root)
            try:
                translations=['Перевод ' + str(i) + ' длинный текст ' * 20 for i in range(25)]
                app.entries=[dict(time='00:00', index=0, speaker=None, **{'from':'EN','to':'RU','source':'Original', 'target':text}) for text in translations]
                app.render(); root.update()
                buttons=app.history.winfo_children(); self.assertEqual(len(buttons), len(translations))
                app.history.yview_moveto(.4); root.update(); before=app.history.yview()
                app.history.tag_add('sel', '3.0', '3.4')
                for i in (0, 12, 24):
                    buttons[i].invoke(); self.assertEqual(root.clipboard_get(), translations[i])
                self.assertEqual(app.history.yview(), before)
                self.assertTrue(app.history.tag_ranges('sel'))
                self.assertEqual(app.status.get(), 'Перевод скопирован')
                app.theme_choice.set('Тёмная'); app.change_theme(); root.update()
                buttons[12].invoke(); self.assertEqual(root.clipboard_get(), translations[12])
                self.assertTrue(buttons[12].cget('image'))
            finally: app.finish_close()
    def test_source_settings_restore_after_restart(self):
        from settings import save_preferences
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([{'name':'First'}, {'name':'Second'}], [{'name':'Speakers'}])):
            root = tk.Tk(); app = App(root)
            app.device_boxes[0].current(1); app.set_mode('Микрофон'); app.direction.current(1); app.save_device_settings(); app.finish_close()
            root = tk.Tk(); app = App(root)
            try:
                self.assertEqual(app.mode.get(), 'Микрофон')
                self.assertEqual(app.device_boxes[0].get(), 'Second')
                self.assertTrue(str(app.device_boxes[0]).startswith(str(app.settings_page) + '.'))
                self.assertFalse(str(app.mode_buttons[0]).startswith(str(app.settings_page) + '.'))
                self.assertEqual(app.direction.current(), 1)
                app.tabs.select(app.settings_page); app.tabs.select(0)
                self.assertEqual(app.mode.get(), 'Микрофон')
                self.assertEqual(app.direction.current(), 1)
            finally:
                app.finish_close()
    def test_source_buttons_lock_during_session_and_restore(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([{'name':'Mic'}], [{'name':'Speaker'}])), patch('app.base_models_ready', return_value=True), patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root); captured=[]
            def session(selected, folder, stop, detect):
                captured.extend(index for index, _, _ in selected)
                stop.wait(3); app.events.put(('done', None, None))
            app.session=session
            try:
                app.mode_buttons[1].invoke()
                self.assertEqual(app.mode.get(), 'Звук компьютера')
                app.toggle()
                self.assertTrue(all(str(button.cget('state')) == 'disabled' for button in app.mode_buttons))
                app.mode_buttons[0].invoke()
                self.assertEqual(app.mode.get(), 'Звук компьютера')
                app.stop.set()
                deadline=time.monotonic()+3
                while app.stop is not None and time.monotonic()<deadline:
                    root.update(); time.sleep(.01)
                self.assertEqual(captured, [1])
                self.assertTrue(all(str(button.cget('state')) == 'normal' for button in app.mode_buttons))
            finally:
                if app.stop: app.stop.set()
                app.finish_close()

    def test_missing_selected_device_opens_settings(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('app.base_models_ready', return_value=True), patch('app.messagebox.showerror') as error, patch('theme_manager.system_theme', return_value='light'):
            root=tk.Tk(); app=App(root)
            try:
                app.set_mode('Микрофон'); app.toggle()
                self.assertEqual(app.tabs.select(), str(app.settings_page))
                self.assertIn('Настройки', error.call_args.args[1])
                self.assertIsNone(app.stop)
            finally: app.finish_close()
    def test_render_keeps_position_when_reading_older_messages(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])):
            root = tk.Tk(); app = App(root)
            try:
                app.entries = [dict(time='00:00', index=0, speaker=None, **{'from':'EN','to':'RU','source':f'Original {n}', 'target':f'Перевод {n}'}) for n in range(80)]
                app.render(); root.update(); app.history.yview_moveto(.25); root.update()
                before = app.history.index('@0,0')
                app.entries.append(dict(time='00:00', index=0, speaker=None, **{'from':'EN','to':'RU','source':'New', 'target':'Новый'}))
                app.render(); root.update()
                self.assertEqual(app.history.index('@0,0'), before)
            finally:
                app.finish_close()
    def test_session_events_and_notes_are_saved_on_close(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([{'name':'Test microphone'}], [{'name':'Test output'}])):
            root = tk.Tk(); root.withdraw(); app = App(root)
            def session(selected, folder, stop, detect):
                app.events.put(('line', 0, ('Hello', 'Привет', None, 'EN → RU')))
                app.events.put(('done', None, None))
            app.session = session
            app.toggle()
            deadline = time.monotonic() + 5
            while app.stop is not None and time.monotonic() < deadline:
                root.update(); time.sleep(.02)
            self.assertIsNone(app.stop)
            app.history.tag_add('sel', '3.0', '3.3')
            selection = app.history.get('sel.first', 'sel.last')
            app.render()
            self.assertEqual(app.history.get('sel.first', 'sel.last'), selection)
            session_id = app.storage.sessions()[0][0]
            self.assertEqual(app.storage.phrases(session_id)[0][-2:], ('Hello', 'Привет'))
            app.library.add_note(); app.library.title.delete(0, 'end'); app.library.title.insert(0, 'Greetings')
            app.library.body.insert('1.0', 'Hello — Привет')
            note_id = app.library.current_note
            app.finish_close()
            from storage import Storage
            saved = Storage(os.path.join(directory, 'Documents', 'LiveTranslate', 'library.sqlite3'))
            self.assertEqual(saved.note(note_id)[:2], ('Greetings', 'Hello — Привет'))
            self.assertIsNotNone(saved.sessions()[0][2]); saved.close()

    def test_copy_icon_has_tooltip_and_accessibility_label(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            root = tk.Tk(); app = App(root)
            try:
                app.entries = [dict(time='00:00', index=0, speaker=None, **{'from':'EN','to':'RU','source':'Hello','target':'Привет'})]
                app.render(); root.update()
                button = app.history.winfo_children()[0]
                self.assertEqual(button.cget('compound'), 'none')
                self.assertEqual(button.cget('text'), 'Копировать перевод')
                self.assertTrue(button.bind('<Enter>'))
                button.event_generate('<Enter>')
                deadline = time.monotonic() + 1.5
                found = []
                while time.monotonic() < deadline and not found:
                    root.update(); time.sleep(.05)
                    def collect(widget):
                        result = []
                        for child in widget.winfo_children():
                            if isinstance(child, tk.Toplevel):
                                result.append(child)
                            result.extend(collect(child))
                        return result
                    found = collect(root)
                self.assertEqual(len(found), 1)
                labels = [child for child in found[0].winfo_children() if isinstance(child, tk.Label)]
                self.assertEqual([label.cget('text') for label in labels], ['Копировать перевод'])
                button.event_generate('<Leave>'); root.update()
            finally:
                app.finish_close()

    def test_source_mode_buttons_are_on_main_page(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory, 'LIVETRANSLATE_DOCUMENTS': os.path.join(directory, 'Documents')}), patch('app.devices', return_value=([], [])), patch('theme_manager.system_theme', return_value='light'):
            root = tk.Tk(); app = App(root)
            try:
                main = app.tabs.nametowidget(app.tabs.tabs()[0])
                for button in app.mode_buttons:
                    self.assertTrue(str(button).startswith(str(main) + '.'))
                    self.assertFalse(str(button).startswith(str(app.settings_page) + '.'))
            finally:
                app.finish_close()

if __name__ == '__main__': unittest.main()
