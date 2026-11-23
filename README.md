# RPX-PLC — firmware pubblicato

Versioni pubblicate del firmware di RPX-PLC (PLC su scheda Waveshare ESP32-S3-ETH-8DI-8RO, programmabile in LAD, SCL e
SFC dal browser).

- **Installazione e manuale**: https://replaytechsolution.github.io/RPX-PLC-firmware/
- **Versioni**: [releases](https://github.com/ReplayTechSolution/RPX-PLC-firmware/releases) — ogni versione contiene
  il firmware per l'aggiornamento via rete, l'immagine completa per la prima installazione, il manuale e le licenze.
- **Programma per Windows**: release [flasher](https://github.com/ReplayTechSolution/RPX-PLC-firmware/releases/tag/flasher).

## Licenze

- Firmware, ambiente di ingegneria e simulatore: licenza d'uso di RPX-PLC, [licenze/LICENZA.txt](licenze/LICENZA.txt)
  (uso gratuito, senza garanzia). **RPX-PLC non è un controllore di sicurezza**: non usarlo per arresti di
  emergenza, ripari o interblocchi di sicurezza.
- Componenti di terze parti contenuti nel firmware (ESP-IDF, FreeRTOS, lwIP, Mbed TLS, cJSON, littlefs, …):
  [licenze/LICENZE-TERZE-PARTI-FIRMWARE.txt](licenze/LICENZE-TERZE-PARTI-FIRMWARE.txt).
- RPX-PLC Flasher per Windows: GNU GPL versione 2 o successiva, sorgente completo nella cartella [flasher](flasher);
  componenti inclusi: [licenze/LICENZE-TERZE-PARTI-FLASHER.txt](licenze/LICENZE-TERZE-PARTI-FLASHER.txt).

SIEMENS, SIMATIC, S7-1200, TIA Portal e PLCSIM sono marchi di Siemens AG. RPX-PLC non è affiliato a Siemens né
approvato da Siemens: i nomi sono citati solo per descrivere la compatibilità e il modo di lavorare.

© 2026 Replay Tech Solution
