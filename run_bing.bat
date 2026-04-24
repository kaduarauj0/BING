@echo off
cd /d "c:\Users\super\Documents\Projetos\BING"

echo [%DATE% %TIME%] Iniciando Automacao... > bing_log.txt
call venv\Scripts\activate.bat >> bing_log.txt 2>&1
python main.py >> bing_log.txt 2>&1
echo [%DATE% %TIME%] Finalizado! >> bing_log.txt

cd /d "c:\Users\super\Documents\Projetos\Shopee_Shein_Aliexpres"
call run_automation.bat
