# 🍓 SonicBerryBot & Media Infrastructure

## -- ARCHITECTURE --
**SonicBerry** is an automated media infrastructure server designed for "zero-trust" environments, running on a headless Arch Linux (ARM) server. The core of this project is an asynchronous Telegram bot that uses a fuzzy logic engine to search, evaluate, and download preferably lossless audio files (FLAC) through the P2P Soulseek network, automating the entire process of metadata curation, tagging, and streaming.

The ecosystem operates safely and remotely through containers:
* **INFRASTRUCTURE CORE:** Arch Linux (ARM), Docker, Cloudflare Zero-Trust Tunnels, Tailscale.
* **BACKEND & LOGIC:** Python 3 (`python-telegram-bot`, `httpx`, `asyncio`).
* **P2P NETWORK & DOWNLOADS:** Slskd (Web/API Client for Soulseek).
* **DATA PIPELINE:** Beets (SQLite metadata management and structured importing).
* **STREAMING:** Navidrome (Personal media server).

## -- FUZZY LOGIC --
To avoid blocked downloads or low-quality audio files, SonicBerryBot does not choose results randomly or rely solely on file names. It implements an evaluation system that ranks network peers based on:
* **FILE SIZE:** Dynamically prioritizes heavier files (12MB - 90MB) that guarantee high-fidelity compression, and severely penalizes lossy formats (MP3).
* **UPLOAD SPEED (Kbps):** Evaluates the available bandwidth of the remote host.
* **QUEUE LENGTH:** Calculates the virtual wait time in the P2P network, seeking an optimal balance between top audio quality and immediate availability (free slots).

## -- REPOSITORY STRUCTURE --
* `sonicberrybot.py`: Main asynchronous code for the Telegram bot and the fuzzy logic engine.
* `docker-compose.yml`: Infrastructure as Code (IaC) template to set up Slskd and Navidrome services in a standardized format.
* `config/`: Configuration files for the ecosystem (e.g., `beets_config.yaml` and the `systemd` daemon config).
* `scripts/`: Local maintenance tools, database restoration scripts, and metadata fixers.

## -- AUTOMATION PIPELINE --
1. **QUERY & SANITIZATION:** The user sends a request via Telegram. The bot parses complex metadata (collaborations, accents, "feat.") relying on the iTunes API to ensure exact matches in the strict Slskd search engine.
2. **P2P SCRAPING:** The bot evaluates network responses for 22 seconds to ensure *power users* with massive libraries (and slow disks) have enough time to respond. The fuzzy engine ranks options and returns the best candidates in an interactive list.
3. **STAGING & TAGGING:** Once the download finishes in the temporary environment (`/mnt/music/staging`), it triggers an automatic `beets` routine to fix ID3 tags, download cover art, and move the clean files to the final library.

## -- ROADMAP / FUTURE WORK --
* Deploy an independent and interactive web player using the Navidrome API, oriented exclusively towards guest users.
* Integrate a visual/UI layer inspired by a Y2K aesthetic for the presentation of a copyright-free music catalog (TOWERSONIC).
* Train a secondary prioritization model to automatically manage queues stuck for more than 24 hours.
