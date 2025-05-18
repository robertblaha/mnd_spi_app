@echo off
rem Dávkový soubor pro aktualizaci requirements.txt

echo Aktualizuji soubor requirements.txt...

rem Uložíme aktuálně nainstalované balíčky do requirements.txt
pip freeze > requirements.txt

echo Soubor requirements.txt byl aktualizován.
pause