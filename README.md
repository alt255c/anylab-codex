# AnyLab для Codex

Плагин для локального Codex на Windows. Готовит лабораторные по AnyLogic по номеру варианта, запускает модели и собирает общий отчёт. Обезличенные ALP и DOCX для ЛР1–ЛР6 входят в установку. Штатные 3D-объекты и исходный пример АЗС берутся из установленной AnyLogic.

## Установка

Установите Codex CLI, Python 3.10 или новее с лаунчером `py` и AnyLogic. Выполните в PowerShell:

```powershell
py -3 -m pip install -r https://raw.githubusercontent.com/alt255c/anylab-codex/main/plugins/anylab/runtime/requirements.txt
codex plugin marketplace add alt255c/anylab-codex
codex plugin add anylab@anylab-marketplace
```

Для видео плагин найдёт системный FFmpeg или воспользуется кодировщиком из установленной зависимости `imageio-ffmpeg`. PDF можно экспортировать через Microsoft Word, LibreOffice или ReportLab. Word и LibreOffice подходят для сохранения вёрстки DOCX. ReportLab создаёт PDF с собственной вёрсткой.

## Пример запроса

> Используй AnyLab. Выполни ЛР4 целиком, вариант 6. Нужны отдельные модели по заданиям, общий DOCX (с снимками модели) и видео на 20 секунд. Также создай копию PDF. Студент: Иванов Иван Иванович; группа: Бxx-xxx
