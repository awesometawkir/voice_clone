@echo off
echo ========================================
echo Voice Clone Service Setup
echo ========================================
echo.

echo Step 1: Creating virtual environment...
python -m venv venv
if errorlevel 1 (
    echo Failed to create virtual environment
    pause
    exit /b 1
)

echo.
echo Step 2: Activating virtual environment...
call venv\Scripts\activate.bat

echo.
echo Step 3: Installing dependencies...
pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo Step 4: Creating .env file...
if not exist .env (
    copy .env.example .env
    echo .env file created. Please edit it with your API keys.
) else (
    echo .env file already exists.
)

echo.
echo Step 5: Running migrations...
python manage.py makemigrations
python manage.py migrate

echo.
echo ========================================
echo Setup Complete!
echo ========================================
echo.
echo Next steps:
echo 1. Edit .env file and add your API keys (optional for free TTS)
echo 2. Run: python manage.py createsuperuser (optional)
echo 3. Run: python manage.py runserver
echo 4. Open: http://127.0.0.1:8000/
echo.
pause
