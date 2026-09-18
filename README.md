#SonicBerryBot & Media Infrastructure

## -- ARCHITECTURE ---
**SonicBerry** is an automated media infrastructure server designed for "zero-trust" environments, running on a headless Arch Linux (ARM) server. The nucleus of this project is
an asynchronous Telegram bot that uses fuzzy logic to search, evaluate, and download preferably lossless audio files (FLAC) through p2p Soulseek Network, processing and automating the
entire process of assigning the updated and correct metadata, as well as streaming, of course.

The ecosystem operates safely and remotely through containers:
* **INFRASTRUCTURE CORE:** Arch Linux (ARM), Docker, Cloudflare Zero-Trust Tunnels, Tailscale.
* **BACKEND & LOGIC:** Python 3 (`python-telegram-bot`, `httpx`, `asyncio`).
* **P2P NETWORK & DOWNLOADS:** Slskd (Web/API Client for Soulseek).
* **Pipeline de Datos:** Beets (Metadata management SQLite and structured importation).
* **Streaming:** Navidrome (Personal media server).

## -- FUZZY LOGIC --
To avoid blocked downloads or low-quality audio files, SonicBerryBot does not choose results randomly or guide based on the name itself. It implements an evaluation system that
classifies network peers based on:
* **FILE SIZE** Prioritizes dynamically heavy files (12MB - 90MB) that guarantee high-fidelity compression, and severely penalizes lossy format files (mp3).
* **Kbps** Evaluates remote host bandwidth available.
* **QUEUE LENGTH ** Calculates the virtual queue in p2p network, searching for an optimal balance between audio file quality and immediate availability

  ## -- REPOSITORY STRUCTURE --
  * `sonicberrybot.py`: Main asynchronous code for the Telegram bot as well as the fuzzy engine.
  * `docker-compose.yml`: template Infrastructure as code (IaC) to set up Slskd and navidrome services in standard form.
  * `config/`: Configuration files for the ecosystem (e.g., `beets_config.yaml` and the daemon `systemd` config).
  * `scripts/`: local maintenance tools, database restoration scripts, and metadata fixes.
 
  ## -- AUTOMATIZATION PIPELINE --
  * **QUERY & SANITIZATION** User sends a request via Telegram. Bot parses complex metadata (collaborations, accents, "feat.") relying in iTUNES API to ensure exact and accurate coincidences
  * in the strict Slskd search engine.
  * **SCRAPING P2P** Telegram Bot evaluates network responses for 22 seconds to ensure *power users* with massive libraries (and slow files) have enough time to respond. Fuzzy engine ranks
  * options and returns the best candidates in an interactive list.
  * **STAGING & TAGGING** When the download is finalized in the temporary environment (`/mnt/music/staging`), it releases a `beets` automatic routine to fix ID3 tags, downloads *Cover art*,
  * and moves the clean file to the final library.
 
  ## -- ROADMAP / FUTURE WORKS --
  *Deploy an independent and interactive web player using the Navidrome API, oriented exclusively to guest users.
  *Integrate Visual/UI layer inspired by a Y2K aesthetic for presentation of a no-copyright music catalogue.
  *Train a secondary prioritizing model to manage automatically stuck queues for more than 24 hrs.
