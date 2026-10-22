# Проверки сборки 0.1

- Android APK собран из этого проекта с JDK 17, SDK 35, Gradle 8.13, AGP 8.9.1 и Chaquopy 17.1.0.
- APK содержит ARM64 и x86_64, minSdk 24, targetSdk 35.
- `apksigner verify --verbose`: успешная проверка подписи APK Signature Scheme v2.
- `zipalign -c -P 16 4`: успешная проверка упаковки. Она не гарантирует поддержку 16-КБ страниц всеми встроенными ELF-библиотеками.
- Объединённый manifest не содержит разрешения INTERNET.
- Исходный engine.py совпадает с входным Python-модулем сборки.
- Семь модульных тестов прошли на Linux/CPython, включая независимое FFT-измерение переноса 220 → 440 Гц и точную длительность 8,1-секундной записи на границе блоков.
- ARM64-сборка PyWORLD слинкована с запретом неопределённых символов; runtime на физическом ARM64-телефоне пока не проверялся.
- Проверка TalkBack с реальным незрячим пользователем не выполнена. Использованы стандартные Android-элементы, подписи, labelFor и live region.

## Android runtime

Инструментальная проверка **прошла** в Android 7.0 / API 24, x86_64, без аппаратного ускорения:

- установка приложения и тестового APK;
- FFmpeg: MP3 внутри Matroska с расширением `.data`;
- загрузка встроенного Python, NumPy и нативного PyWORLD;
- разбор MIDI, синтез прослушивания выбранной мелодии;
- реальная обработка вокала и FFT-проверка частоты 440 Гц;
- запуск MainActivity и проверка наличия текстовых подписей кнопок;
- запуск обработки нажатием кнопки интерфейса через foreground service;
- успешное завершение обработки.

В ходе проверки исправлена отсутствующая в POM FFmpegKit Java-зависимость: `com.arthenica:smart-exception-java:0.2.1`. После исправления проверка повторена успешно.

Android 15 в программном эмуляторе не завершил загрузку в разумный срок; выполнение приложения на этой версии не проверено. Физический ARM64-телефон и реальный TalkBack не проверены. Проверка меток в дереве Android не заменяет ручную проверку доступности.

```text
PASS: Android FFmpeg MP3-in-Matroska with unknown extension; embedded PyWORLD; MIDI preview; 440 Hz render; Activity and button labels; foreground service through UI button.
```

## Контрольная сумма APK

SHA-256: `d02e85d126ecc9f7bae4826beec2a1869660237e314f9586e9f10967de8c82f6`

## Модульные тесты

```text
test_cancel (test_engine.EngineTests.test_cancel) ... /root/.local/lib/python3.12/site-packages/pyworld/__init__.py:13: UserWarning: pkg_resources is deprecated as an API. See https://setuptools.pypa.io/en/latest/pkg_resources.html. The pkg_resources package is slated for removal as early as 2025-11-30. Refrain from using this package or pin to Setuptools<81.
  import pkg_resources
ok
test_global_tempo_map_and_noteoff_zero (test_engine.EngineTests.test_global_tempo_map_and_noteoff_zero) ... ok
test_polyphony_offset_transposition (test_engine.EngineTests.test_polyphony_offset_transposition) ... ok
test_preview_pitch (test_engine.EngineTests.test_preview_pitch) ... ok
test_reject_type2 (test_engine.EngineTests.test_reject_type2) ... ok
test_render_pitch_and_exact_duration_across_boundary (test_engine.EngineTests.test_render_pitch_and_exact_duration_across_boundary) ... ok
test_rmid (test_engine.EngineTests.test_rmid) ... ok

----------------------------------------------------------------------
Ran 7 tests in 4.085s

OK

```
