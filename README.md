# Natural Selection 2 — Pterodactyl Egg

Importable PTDL_v2 egg for the native Linux Natural Selection 2 dedicated server.

## What it does

- Installs Steam app **4940** through anonymous SteamCMD.
- Uses the supported native Linux `x64/server_linux` binary.
- Uses `ghcr.io/ptero-eggs/steamcmd:debian` at runtime.
- Updates automatically at container start by default.
- Keeps configuration, logs, Workshop data, and generated JSON files inside the Pterodactyl volume.
- Exposes vanilla map, player/spectator, password, and Workshop mod settings.
- Does **not** expose NS2's plaintext web administration interface.

## Required allocations

Use contiguous game/query ports:

- **Game:** UDP primary allocation, for example `27015`.
- **Query:** UDP at **game port + 1**, for example `27016`. NS2 chooses this implicitly, so assign it as an additional allocation even though it is not a startup variable.
Only the game and query UDP allocations are required.

## Recommended resources

- Disk: at least **6 GB** for the base server, game updates, logs, Workshop data, and installation headroom.
- RAM: **2 GB** minimum per server; allow more for mods.
- CPU: NS2 is mainly limited by one fast core. The community guidance is roughly 3.6 GHz for 16 players, 4.0 GHz for 20, and 4.4 GHz for 24. Treat these as practical guidance, not official requirements.

## Import and create

1. Import `egg-natural-selection-2.json` into a suitable Pterodactyl nest.
2. Create a server with the primary game UDP allocation.
3. Add the next UDP port for query traffic.
4. Give it at least 2 GB RAM and 6 GB disk.
5. Install, then start it.
6. Verify the console reports `Connected to Steam servers` and query the **game port + 1** with an A2S_INFO client.

The first installation downloads roughly 3.5 GB, so it takes longer than a small SteamCMD server.

## Configuration files

NS2 creates and uses these under `config/`:

- `ServerConfig.json`
- `ServerAdmin.json`
- `MapCycle.json`
- `BannedPlayers.json`
- `ConsistencyConfig.json`
- `Workshop/`

The installer seeds `MapCycle.json` only when it does not already exist. Reinstalling updates `start.sh` but preserves the existing map cycle and generated server configuration.

## Mods

`MOD_IDS` accepts space-separated **hexadecimal** Workshop IDs for NS2's `-mods` option. Example: Shine Workshop item `117887554` becomes `706D242`.

Modern UGC and per-map mods can instead be placed in `config/MapCycle.json`; decimal IDs are JSON numbers, while legacy hexadecimal IDs are quoted strings.

## Security notes

- No Steam username or password is needed or exposed.
- The built-in NS2 web admin is intentionally disabled because it is plaintext HTTP and can execute console commands.
- The built-in mod backup HTTP server is omitted from this portable egg. In a Docker/NAT deployment it needs one address for both binding and client advertisement; `0.0.0.0` fails and a container-private address is unusable by players. Steam Workshop remains the normal mod-delivery path.
- The startup wrapper rejects unsafe control characters, quotes, backslashes, invalid maps, invalid ports, and invalid mod ID lists.

## Validation

Run:

```bash
python3 build_artifacts.py
python3 -m unittest -v tests/test_egg.py
sha256sum -c SHA256SUMS
```

The release validation also requires a real app-4940 install and bounded server smoke test: process survival, UDP game/query sockets, and an A2S_INFO response reporting app `4920`, the configured name/map, and player limit.
