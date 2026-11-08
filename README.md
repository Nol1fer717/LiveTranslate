# LiveTranslate

Локальный перевод разговора на Windows. Микрофон и системный звук захватываются раздельно через WASAPI. Vosk показывает промежуточные слова. После паузы переводчик выводит исходную фразу и её перевод. Модели Argos работают на процессоре через CTranslate2.

## Запуск

Откройте эту папку в Visual Studio Code и нажмите F5 с установленным расширением Python Debugger. Также можно выполнить в PowerShell:

```powershell
.\.venv\Scripts\python.exe app.py
```

Выберите микрофон и устройство воспроизведения со словом Loopback, на которое звонок выводит голос собеседника. У каждого источника свой выбор направления перевода. Если нужен только один источник, у второго выберите «Отключён». Нажмите «Начать перевод». Наушники помогут исключить повторный захват голоса собеседника микрофоном.

По умолчанию звук обрабатывается в памяти. Опция «Сохранять звук в WAV» сохраняет файлы в папке `Documents/VoiceTranslator Recordings` профиля Windows. Кнопка «Остановить» завершает последнюю фразу и закрывает файлы. Программа показывает субтитры. Для передачи перевода голосом в звонок потребуется озвучка и отдельный аудиовыход.

## Восстановление из Git

Установите Python 3.12 x64. В новой копии проекта выполните:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe models.py
.\.venv\Scripts\python.exe app.py
```

Для сборки Windows-приложения:

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller==6.22.3
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm VoiceTranslator.spec
Copy-Item -Recurse data dist\VoiceTranslator\
```

Переносите папку сборки целиком. Исполняемому файлу нужны соседние каталоги `_internal` и `data`.
