@echo off
setlocal
echo.
echo This stores your ElevenLabs API key in your Windows user environment.
echo The key is not written to settings.cfg and is not stored in this folder.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$key = Read-Host 'Paste your ElevenLabs API key' -AsSecureString; $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($key); try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr); if ([string]::IsNullOrWhiteSpace($plain)) { throw 'No API key entered.' }; [Environment]::SetEnvironmentVariable('ELEVENLABS_API_KEY', $plain, 'User'); Write-Host ''; Write-Host 'Done. Close and reopen WhisperAttackAPI if it was already running.' } finally { if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) } }"
echo.
pause
