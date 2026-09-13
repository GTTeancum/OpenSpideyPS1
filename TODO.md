# To-do

- [x] Add native **Video Setup** under **OPTIONS** in both SM1 and SM2, with **4:3 and 16:9 windowed output resolutions** starting at **640×480**, plus **Fullscreen On/Off**. Preserves each game's menu look and controls. Verified Apply, cancel, restart persistence, fullscreen transitions, exact windowed output areas, and temporary menu allocation cleanup. [Implementation and tests](docs/native-video-setup.md).

- [x] Expand both costume selectors to **60 total costumes per game**: 20 stock + 40 mods in SM1, 19 stock + 41 mods in SM2. Expanded inline menu allocations and row helpers; verified all 60 row selections, text bounds, stable-ID reload, overflow rejection, stock unlocks, donor powers, and SM2 custom actor release at the last slot.
