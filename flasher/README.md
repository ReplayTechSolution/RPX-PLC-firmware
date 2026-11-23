# RPX-PLC Flasher (Windows) — sorgente

Programma per Windows che installa via USB il firmware RPX-PLC pubblicato (o un file dal PC) e mostra la console
della scheda. L'eseguibile pronto è nella release
[flasher](https://github.com/ReplayTechSolution/RPX-PLC-firmware/releases/tag/flasher).

## Licenza

Copyright (C) 2026 Replay Tech Solution.

RPX-PLC Flasher è software libero: puoi ridistribuirlo e modificarlo secondo la **GNU General Public License,
versione 2 o (a tua scelta) successiva** (file `COPYING.txt`). È distribuito senza alcuna garanzia.
Usa [esptool](https://github.com/espressif/esptool) (GPL v2 o successiva) e altri componenti con le loro licenze,
elencati in `LICENZE.txt`.

Questa licenza vale solo per il flasher: il firmware RPX-PLC ha la sua licenza d'uso (`licenze/LICENZA.txt` nel
repository).

## Costruire l'eseguibile

Serve Python 3.12 o successivo per Windows.

```powershell
py -3 -m pip install -r requirements.txt pyinstaller
.\build.ps1
```

Il risultato è `dist\RPX-PLC-Flasher.exe` (un solo file, nessuna installazione). Senza costruire l'eseguibile si può
anche avviare direttamente `py -3 rpx_flasher.py`.

| File | Contenuto |
|---|---|
| `rpx_flasher.py` | il programma |
| `build.ps1` | costruzione dell'eseguibile con PyInstaller e controllo automatico |
| `requirements.txt` | versioni di esptool e pyserial usate |
| `assets/` | icone |
| `COPYING.txt` | GNU General Public License versione 2 |
| `LICENZE.txt` | licenze dei componenti inclusi nell'eseguibile |
