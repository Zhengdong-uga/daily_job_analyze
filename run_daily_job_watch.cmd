@echo off
cd /d C:\Users\joeyd\Desktop\JobWorkFlow

echo [%date% %time%] Starting Daily Job Intelligence Report >> logs\daily_job_watch.log

python scripts\run_daily_job_watch.py --config job_watch_config.yaml --send-email >> logs\daily_job_watch.log 2>&1

echo [%date% %time%] Finished with exit code %errorlevel% >> logs\daily_job_watch.log
echo. >> logs\daily_job_watch.log
