@echo off
echo Starting Voice Clone Service...
cd /d "d:\project\voice"
call venv\Scripts\activate.bat
python manage.py runserver 0.0.0.0:8014
