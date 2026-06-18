@echo off
setlocal
echo.
echo Select the speech-to-text provider API key to store in your Windows user environment.
echo The key is not written to settings.cfg and is not stored in this folder.
echo.
echo 1. ElevenLabs  - ELEVENLABS_API_KEY
echo 2. OpenAI      - OPENAI_API_KEY
echo 3. Deepgram    - DEEPGRAM_API_KEY
echo.
set /p provider="Provider number: "

if "%provider%"=="1" set "env_name=ELEVENLABS_API_KEY"
if "%provider%"=="2" set "env_name=OPENAI_API_KEY"
if "%provider%"=="3" set "env_name=DEEPGRAM_API_KEY"

if "%env_name%"=="" (
  echo Invalid provider selection.
  echo.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$envName = '%env_name%'; $key = Read-Host ('Paste API key for ' + $envName) -AsSecureString; $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($key); try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr); if ([string]::IsNullOrWhiteSpace($plain)) { throw 'No API key entered.' }; [Environment]::SetEnvironmentVariable($envName, $plain, 'User'); Write-Host ''; Write-Host ('Done. Stored ' + $envName + '. Close and reopen WhisperAttackAPI if it was already running.') } finally { if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) } }"
echo.
pause
