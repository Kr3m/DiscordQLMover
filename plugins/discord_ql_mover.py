import json
import time
import urllib.error
import urllib.request

import minqlx
import minqlx.database


class discord_ql_mover(minqlx.Plugin):
    database = minqlx.database.Redis

    KEY_STEAM_TO_DISCORD = "minqlx:dmover:steam_to_discord:{}"
    KEY_DISCORD_TO_STEAM = "minqlx:dmover:discord_to_steam:{}"
    KEY_DISCORD_NAME = "minqlx:dmover:discord_name:{}"
    KEY_NAME_TO_DISCORD = "minqlx:dmover:discord_name_to_id:{}"
    KEY_LINKS_SET = "minqlx:dmover:links"

    def __init__(self):
        super().__init__()

        self.set_cvar_once("qlx_dmoverDiscordBotToken", "")
        self.set_cvar_once("qlx_dmoverDiscordGuildId", "")
        self.set_cvar_once("qlx_dmoverDefaultChannelId", "")
        self.set_cvar_once("qlx_dmoverRedChannelId", "")
        self.set_cvar_once("qlx_dmoverBlueChannelId", "")
        self.set_cvar_once("qlx_dmoverCooldown", "8")
        self.set_cvar_once("qlx_dmoverCommandPermission", "2")
        self.set_cvar_once("qlx_dmoverDryRun", "0")
        self.set_cvar_once("qlx_dmoverRequestTimeoutSeconds", "8")

        self.add_command(("move", "dmove"), self.cmd_move, usage="<teams|default>")
        self.add_command("link", self.cmd_link, usage="<client_id|steam_id> <discord_user_id> [discord_name]")
        self.add_command("unlink", self.cmd_unlink, usage="<client_id|steam_id|discord_user_id>")
        self.add_command("whois", self.cmd_whois, usage="<client_id|steam_id|discord_user_id|discord_name>")
        self.add_command("links", self.cmd_links, usage="[limit]")

        self._last_move_ts = 0.0

    # ---------- Commands ----------
    def cmd_move(self, player, msg, channel):
        if not self._require_permission(player, channel):
            return minqlx.RET_STOP_ALL

        if len(msg) < 2:
            return minqlx.RET_USAGE

        action = msg[1].lower()
        if action not in ("teams", "default"):
            channel.reply("^1[DMover]^7 Invalid action. Use ^6teams^7 or ^6default^7.")
            return minqlx.RET_STOP_ALL

        bypass_cooldown = self.db.has_permission(player, 5)
        cooldown_seconds = self.get_cvar("qlx_dmoverCooldown", float)
        now = time.time()
        if not bypass_cooldown and now < self._last_move_ts + cooldown_seconds:
            remaining = int((self._last_move_ts + cooldown_seconds) - now)
            if remaining < 1:
                remaining = 1
            channel.reply("^1[DMover]^7 You must wait ^6{}^7 second(s) before moving again.".format(remaining))
            return minqlx.RET_STOP_ALL

        config_error = self._validate_runtime_config()
        if config_error is not None:
            channel.reply("^1[DMover]^7 {}".format(config_error))
            return minqlx.RET_STOP_ALL

        self._last_move_ts = now
        channel.reply("^2[DMover]^7 Processing ^6{}^7 move...".format(action))
        self._execute_move(action, channel)
        return minqlx.RET_STOP_ALL

    def cmd_link(self, player, msg, channel):
        if not self._require_permission(player, channel):
            return minqlx.RET_STOP_ALL

        if len(msg) < 3:
            return minqlx.RET_USAGE

        steam_id = self._resolve_steam_id(msg[1])
        if steam_id is None:
            channel.reply("^1[DMover]^7 Invalid player identifier. Use client id or SteamID64.")
            return minqlx.RET_STOP_ALL

        discord_id = self._normalize_discord_id(msg[2])
        if discord_id is None:
            channel.reply("^1[DMover]^7 Invalid Discord user id. It should be numeric.")
            return minqlx.RET_STOP_ALL

        discord_name = " ".join(msg[3:]).strip() if len(msg) > 3 else None
        self._set_mapping(steam_id, discord_id, discord_name if discord_name else None)

        if discord_name:
            channel.reply("^2[DMover]^7 Linked steam ^6{}^7 -> discord ^6{}^7 (^6{}^7)."
                          .format(steam_id, discord_id, discord_name))
        else:
            channel.reply("^2[DMover]^7 Linked steam ^6{}^7 -> discord ^6{}^7."
                          .format(steam_id, discord_id))
        return minqlx.RET_STOP_ALL

    def cmd_unlink(self, player, msg, channel):
        if not self._require_permission(player, channel):
            return minqlx.RET_STOP_ALL

        if len(msg) < 2:
            return minqlx.RET_USAGE

        target = msg[1]
        steam_id, discord_id = self._resolve_link_target(target)
        if steam_id is None and discord_id is None:
            channel.reply("^1[DMover]^7 No mapping found for ^6{}^7.".format(target))
            return minqlx.RET_STOP_ALL

        if steam_id is None and discord_id is not None:
            steam_id = self._get_steam_by_discord(discord_id)
        if discord_id is None and steam_id is not None:
            discord_id = self._get_discord_by_steam(steam_id)

        if steam_id is None or discord_id is None:
            channel.reply("^1[DMover]^7 Incomplete mapping detected; cannot unlink safely.")
            return minqlx.RET_STOP_ALL

        self._delete_mapping(steam_id, discord_id)
        channel.reply("^2[DMover]^7 Unlinked steam ^6{}^7 and discord ^6{}^7.".format(steam_id, discord_id))
        return minqlx.RET_STOP_ALL

    def cmd_whois(self, player, msg, channel):
        if len(msg) < 2:
            return minqlx.RET_USAGE

        target = msg[1]
        steam_id, discord_id = self._resolve_link_target(target)

        if steam_id is None and discord_id is None:
            discord_id = self._get_discord_by_name(target)
            if discord_id is not None:
                steam_id = self._get_steam_by_discord(discord_id)

        if steam_id is None and discord_id is None:
            channel.reply("^1[DMover]^7 No mapping found for ^6{}^7.".format(target))
            return minqlx.RET_STOP_ALL

        if steam_id is None:
            steam_id = self._get_steam_by_discord(discord_id)
        if discord_id is None:
            discord_id = self._get_discord_by_steam(steam_id)

        discord_name = self._get_discord_name(discord_id) if discord_id is not None else None

        if discord_name:
            channel.reply("^2[DMover]^7 steam ^6{}^7 <-> discord ^6{}^7 (^6{}^7)."
                          .format(steam_id, discord_id, discord_name))
        else:
            channel.reply("^2[DMover]^7 steam ^6{}^7 <-> discord ^6{}^7."
                          .format(steam_id, discord_id))
        return minqlx.RET_STOP_ALL

    def cmd_links(self, player, msg, channel):
        limit = 20
        if len(msg) > 1:
            try:
                limit = int(msg[1])
            except ValueError:
                channel.reply("^1[DMover]^7 Invalid limit.")
                return minqlx.RET_STOP_ALL
            if limit < 1:
                limit = 1
            if limit > 100:
                limit = 100

        steam_ids = sorted([self._decode(v) for v in self.db.smembers(self.KEY_LINKS_SET)])
        if not steam_ids:
            channel.reply("^3[DMover]^7 No mappings stored.")
            return minqlx.RET_STOP_ALL

        channel.reply("^3[DMover]^7 Showing {} of {} links:".format(min(limit, len(steam_ids)), len(steam_ids)))
        for steam_id in steam_ids[:limit]:
            discord_id = self._get_discord_by_steam(steam_id)
            if discord_id is None:
                continue
            discord_name = self._get_discord_name(discord_id)
            if discord_name:
                channel.reply("  ^6{}^7 -> ^6{}^7 (^6{}^7)".format(steam_id, discord_id, discord_name))
            else:
                channel.reply("  ^6{}^7 -> ^6{}^7".format(steam_id, discord_id))
        return minqlx.RET_STOP_ALL

    # ---------- Move flow ----------
    @minqlx.thread
    def _execute_move(self, action, channel):
        token = self.get_cvar("qlx_dmoverDiscordBotToken")
        guild_id = self.get_cvar("qlx_dmoverDiscordGuildId")
        default_channel = self.get_cvar("qlx_dmoverDefaultChannelId")
        red_channel = self.get_cvar("qlx_dmoverRedChannelId")
        blue_channel = self.get_cvar("qlx_dmoverBlueChannelId")
        dry_run = self.get_cvar("qlx_dmoverDryRun", bool)

        teams = self.teams()
        blue_players = teams.get("blue", [])
        red_players = teams.get("red", [])

        moved = []
        missing = []
        failed = []

        for player in blue_players:
            target_channel = blue_channel if action == "teams" else default_channel
            self._move_player(player, guild_id, token, target_channel, dry_run, moved, missing, failed)

        for player in red_players:
            target_channel = red_channel if action == "teams" else default_channel
            self._move_player(player, guild_id, token, target_channel, dry_run, moved, missing, failed)

        self._report_move_result(action, channel, moved, missing, failed, dry_run)

    def _move_player(self, player, guild_id, token, target_channel, dry_run, moved, missing, failed):
        steam_id = str(player.steam_id)
        discord_id = self._get_discord_by_steam(steam_id)
        if discord_id is None:
            missing.append((player.clean_name, steam_id))
            return

        if dry_run:
            moved.append((player.clean_name, steam_id, discord_id, "dry-run"))
            return

        ok, status, body = self._discord_move_member(guild_id, discord_id, target_channel, token)
        if ok:
            moved.append((player.clean_name, steam_id, discord_id, str(status)))
        else:
            failed.append((player.clean_name, steam_id, discord_id, status, body))

    def _discord_move_member(self, guild_id, discord_id, channel_id, token):
        payload = json.dumps({"channel_id": str(channel_id)}).encode("utf-8")
        url = "https://discord.com/api/v10/guilds/{}/members/{}".format(guild_id, discord_id)
        timeout_seconds = self.get_cvar("qlx_dmoverRequestTimeoutSeconds", float)

        return self._patch_discord_member(url, payload, token, timeout_seconds)

    def _patch_discord_member(self, url, payload, token, timeout_seconds):
        headers = {
            "Authorization": "Bot {}".format(token),
            "Content-Type": "application/json",
            "User-Agent": "discord-ql-mover/1.0",
        }

        request = urllib.request.Request(url=url, data=payload, headers=headers, method="PATCH")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                status = getattr(response, "status", 200)
                return True, int(status), ""
        except urllib.error.HTTPError as err:
            status = int(err.code)
            body = err.read().decode("utf-8", errors="replace")
            if status == 429:
                retry_seconds = self._parse_retry_after(body)
                if retry_seconds is not None and retry_seconds <= 10:
                    time.sleep(retry_seconds)
                    try:
                        with urllib.request.urlopen(request, timeout=timeout_seconds) as retry_response:
                            retry_status = getattr(retry_response, "status", 200)
                            return True, int(retry_status), ""
                    except urllib.error.HTTPError as retry_err:
                        retry_body = retry_err.read().decode("utf-8", errors="replace")
                        return False, int(retry_err.code), retry_body
                    except urllib.error.URLError as retry_err:
                        return False, -1, str(retry_err.reason)
            return False, status, body
        except urllib.error.URLError as err:
            return False, -1, str(err.reason)

    def _parse_retry_after(self, body):
        try:
            payload = json.loads(body)
        except ValueError:
            return None

        retry_after = payload.get("retry_after")
        if retry_after is None:
            return None
        try:
            value = float(retry_after)
        except (TypeError, ValueError):
            return None

        if value < 0:
            return None
        return value

    @minqlx.next_frame
    def _report_move_result(self, action, channel, moved, missing, failed, dry_run):
        mode = "DRY-RUN " if dry_run else ""
        channel.reply("^2[DMover]^7 {}{} completed. moved:^6{}^7 missing-link:^6{}^7 failed:^6{}^7"
                      .format(mode, action, len(moved), len(missing), len(failed)))

        if missing:
            missing_names = ", ".join(["{}({})".format(name, steam_id) for name, steam_id in missing[:8]])
            channel.reply("^3[DMover]^7 Missing links: {}".format(missing_names))

        if failed:
            first = failed[0]
            channel.reply("^1[DMover]^7 Discord move failure example: {}({}) -> {} status={} body={}"
                          .format(first[0], first[1], first[2], first[3], first[4][:120]))

    # ---------- Mapping ----------
    def _set_mapping(self, steam_id, discord_id, discord_name=None):
        old_discord = self._get_discord_by_steam(steam_id)
        if old_discord is not None and old_discord != discord_id:
            self._delete_mapping(steam_id, old_discord)

        old_steam = self._get_steam_by_discord(discord_id)
        if old_steam is not None and old_steam != steam_id:
            self._delete_mapping(old_steam, discord_id)

        self.db[self.KEY_STEAM_TO_DISCORD.format(steam_id)] = str(discord_id)
        self.db[self.KEY_DISCORD_TO_STEAM.format(discord_id)] = str(steam_id)
        self.db.sadd(self.KEY_LINKS_SET, str(steam_id))

        if discord_name:
            self._set_discord_name(discord_id, discord_name)

    def _delete_mapping(self, steam_id, discord_id):
        steam_key = self.KEY_STEAM_TO_DISCORD.format(steam_id)
        discord_key = self.KEY_DISCORD_TO_STEAM.format(discord_id)
        name_key = self.KEY_DISCORD_NAME.format(discord_id)

        if steam_key in self.db:
            del self.db[steam_key]
        if discord_key in self.db:
            del self.db[discord_key]

        if name_key in self.db:
            discord_name = self._decode(self.db[name_key])
            del self.db[name_key]
            normalized_name = self._normalize_discord_name(discord_name)
            if normalized_name:
                name_index_key = self.KEY_NAME_TO_DISCORD.format(normalized_name)
                if name_index_key in self.db:
                    existing = self._decode(self.db[name_index_key])
                    if existing == str(discord_id):
                        del self.db[name_index_key]

        self.db.srem(self.KEY_LINKS_SET, str(steam_id))

    def _set_discord_name(self, discord_id, discord_name):
        discord_name = discord_name.strip()
        if not discord_name:
            return

        old_name = self._get_discord_name(discord_id)
        if old_name is not None:
            old_norm = self._normalize_discord_name(old_name)
            if old_norm:
                old_key = self.KEY_NAME_TO_DISCORD.format(old_norm)
                if old_key in self.db:
                    existing = self._decode(self.db[old_key])
                    if existing == str(discord_id):
                        del self.db[old_key]

        self.db[self.KEY_DISCORD_NAME.format(discord_id)] = discord_name
        normalized = self._normalize_discord_name(discord_name)
        if normalized:
            self.db[self.KEY_NAME_TO_DISCORD.format(normalized)] = str(discord_id)

    def _resolve_link_target(self, token):
        steam_id = self._resolve_steam_id(token)
        if steam_id is not None and self._get_discord_by_steam(steam_id) is not None:
            return steam_id, None

        discord_id = self._normalize_discord_id(token)
        if discord_id is not None and self._get_steam_by_discord(discord_id) is not None:
            return None, discord_id

        return None, None

    def _resolve_steam_id(self, token):
        try:
            value = int(token)
        except ValueError:
            return None

        if 0 <= value < 64:
            try:
                target = self.player(value)
            except minqlx.NonexistentPlayerError:
                return None
            if target is None:
                return None
            return str(target.steam_id)

        if value >= 64:
            return str(value)
        return None

    def _normalize_discord_id(self, token):
        if not token.isdigit():
            return None
        return token

    def _normalize_discord_name(self, name):
        normalized = name.strip().lower()
        if not normalized:
            return None
        return normalized

    def _get_discord_by_steam(self, steam_id):
        key = self.KEY_STEAM_TO_DISCORD.format(steam_id)
        if key not in self.db:
            return None
        return self._decode(self.db[key])

    def _get_steam_by_discord(self, discord_id):
        key = self.KEY_DISCORD_TO_STEAM.format(discord_id)
        if key not in self.db:
            return None
        return self._decode(self.db[key])

    def _get_discord_name(self, discord_id):
        key = self.KEY_DISCORD_NAME.format(discord_id)
        if key not in self.db:
            return None
        return self._decode(self.db[key])

    def _get_discord_by_name(self, discord_name):
        normalized = self._normalize_discord_name(discord_name)
        if normalized is None:
            return None
        key = self.KEY_NAME_TO_DISCORD.format(normalized)
        if key not in self.db:
            return None
        return self._decode(self.db[key])

    def _decode(self, value):
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    # ---------- Validation / permissions ----------
    def _validate_runtime_config(self):
        token = self.get_cvar("qlx_dmoverDiscordBotToken")
        guild_id = self.get_cvar("qlx_dmoverDiscordGuildId")
        default_channel = self.get_cvar("qlx_dmoverDefaultChannelId")
        red_channel = self.get_cvar("qlx_dmoverRedChannelId")
        blue_channel = self.get_cvar("qlx_dmoverBlueChannelId")

        if not token:
            return "Missing qlx_dmoverDiscordBotToken."
        if not guild_id:
            return "Missing qlx_dmoverDiscordGuildId."
        if not default_channel:
            return "Missing qlx_dmoverDefaultChannelId."
        if not red_channel:
            return "Missing qlx_dmoverRedChannelId."
        if not blue_channel:
            return "Missing qlx_dmoverBlueChannelId."

        return None

    def _require_permission(self, player, channel):
        required = self.get_cvar("qlx_dmoverCommandPermission", int)
        if self.db.has_permission(player, required):
            return True
        channel.reply("^1[DMover]^7 You need permission level ^6{}^7.".format(required))
        return False
