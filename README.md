# DiscordQLMover

Port of the original DiscordTF2Mover workflow to **Quake Live + minqlx**.

This project preserves the core behavior of the original bot:
- maintain a SteamID64 ↔ Discord identity mapping
- move Discord users to team voice channels based on in-game team composition
- move everyone back to a default voice channel

---

## Features

- **minqlx-native plugin** (no SourceMod dependency)
- **Direct Discord API integration** (no required Node/Express sidecar)
- **Bidirectional mapping layer**:
  - SteamID64 -> Discord user ID
  - Discord user ID -> SteamID64
  - Optional Discord display name index for human lookup
- **Admin commands** for linking, unlinking, lookup, listing, and moving
- **Cooldown control** for move operations
- **Dry-run mode** to validate behavior before real moves
- **Redis-backed storage** via minqlx (`self.db`)

---

## Project structure

- [plugins/discord_ql_mover.py](./plugins/discord_ql_mover.py)  
  Main minqlx plugin.
- [config/example_server.cfg.snippet](./config/example_server.cfg.snippet)  
  Example server cfg settings.
- [tools/import_from_csv.py](./tools/import_from_csv.py)  
  Optional helper to create `!link` commands from legacy data exports.

---

## Why Redis storage (instead of JSON/SQLite/MySQL)?

This port uses minqlx Redis storage because it is the most idiomatic and operationally simple in a minqlx runtime:

- already present in standard minqlx installations
- fast key-value lookup for both mapping directions
- no additional service management beyond what minqlx already expects
- integrates with minqlx plugin patterns used in existing plugins

### Stored keys

- `minqlx:dmover:steam_to_discord:<steam_id>` -> `<discord_user_id>`
- `minqlx:dmover:discord_to_steam:<discord_user_id>` -> `<steam_id>`
- `minqlx:dmover:discord_name:<discord_user_id>` -> `<discord_display_name>` (optional)
- `minqlx:dmover:discord_name_to_id:<normalized_name>` -> `<discord_user_id>`
- `minqlx:dmover:links` (set of linked Steam IDs)

---

## Installation

1. Copy [plugins/discord_ql_mover.py](./plugins/discord_ql_mover.py) into your minqlx plugins directory.
2. Add `discord_ql_mover` to `qlx_plugins` in your server cfg.
3. Apply cvars from [config/example_server.cfg.snippet](./config/example_server.cfg.snippet) (adjust IDs/token first).
4. Restart server or reload plugin (`!load discord_ql_mover` / `!reload discord_ql_mover`).

---

## Required configuration

Set these cvars in your server config:

- `qlx_dmoverDiscordBotToken` - Discord bot token
- `qlx_dmoverDiscordGuildId` - guild/server ID
- `qlx_dmoverDefaultChannelId` - default pre/post-game voice channel
- `qlx_dmoverRedChannelId` - red team voice channel
- `qlx_dmoverBlueChannelId` - blue team voice channel

Optional:
- `qlx_dmoverCooldown` (default `8`)
- `qlx_dmoverCommandPermission` (default `2`)
- `qlx_dmoverDryRun` (`1` for testing, default `0`)
- `qlx_dmoverRequestTimeoutSeconds` (default `8`)

---

## Commands

All commands use your server prefix (usually `!`).

- `!move <teams|default>`
  - `teams`: move blue/red roster members to their configured team voice channels
  - `default`: move blue/red roster members back to default voice channel

- `!link <client_id|steam_id> <discord_user_id> [discord_name]`
  - creates/updates mapping

- `!unlink <client_id|steam_id|discord_user_id>`
  - removes mapping in both directions

- `!whois <client_id|steam_id|discord_user_id|discord_name>`
  - queries mapping

- `!links [limit]`
  - list stored links (default 20, max 100)

---

## Discord bot requirements

The configured bot token must belong to a bot that:
- is in the target guild
- can see target voice channels
- has permission to move members between those channels
- has role hierarchy high enough to move target users

Discord API endpoint used:
- `PATCH /guilds/{guild_id}/members/{user_id}` with `{"channel_id":"..."}`.

---

## Port mapping from original project

Original stack:
- TF2 SourceMod command -> Node/Express webhook -> Discord.js move

This port:
- minqlx command -> direct Discord REST move

Functional mapping:
- `sm_move teams/default` -> `!move teams/default`
- MySQL `dmover_users` -> Redis keyspace (`minqlx:dmover:*`)
- web linker -> admin mapping commands (`!link`, `!unlink`)

---

## Known behavior differences (intentional)

- No PHP OAuth linker is included in this port.
  - Linking is handled by admin commands in-game/console.
- Only players currently in **red/blue** are considered for move operations.
  - Spectators/free players are not moved by `!move`.
- Name lookups are optional convenience indexes; canonical identity is Discord user ID.

---

## Operational notes

- Use `qlx_dmoverDryRun 1` first to verify mapping completeness and command flow.
- If Discord rate limits (`429`) occur, plugin performs one short retry.
- Any failed move response is surfaced to command output for troubleshooting.

