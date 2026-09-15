import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
import json
import os
import random
import sys
from datetime import datetime, timezone
from discord import app_commands


# ============================================================
# CONFIG
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

SCRIPTED_USER_ID = 630035129414320191
AUTHORIZED_ROLE_ID = 1367168922926841867

BADGE_WEBHOOK_URL = os.getenv("BADGE_WEBHOOK_URL")
GAME_WEBHOOK_URL = os.getenv("GAME_WEBHOOK_URL")
OPEN_CLOUD_API_KEY = os.getenv("OPEN_CLOUD_API_KEY")
TOKEN = os.getenv("TOKEN")

BADGE_FILE = "tracked_badges.json"
GAME_FILE = "tracked_games.json"

CHECK_INTERVAL = 60

# Maximum number of Roblox API requests happening at once.
# Prevents a game with tons of subplaces from hammering the API.
API_CONCURRENCY = 10

# ============================================================
# ENVIRONMENT CHECK
# ============================================================

if not BADGE_WEBHOOK_URL:
    print("❌ Error: BADGE_WEBHOOK_URL environment variable is not set!")

if not GAME_WEBHOOK_URL:
    print("❌ Error: GAME_WEBHOOK_URL environment variable is not set!")

if not OPEN_CLOUD_API_KEY:
    print("❌ Error: OPEN_CLOUD_API_KEY environment variable is not set!")

if not TOKEN:
    print("❌ Error: TOKEN environment variable is not set!")

if (
    not BADGE_WEBHOOK_URL
    or not GAME_WEBHOOK_URL
    or not OPEN_CLOUD_API_KEY
    or not TOKEN
):
    print("❌ One or more environment variables are missing. Exiting.")
    sys.exit(1)


# ============================================================
# GLOBAL STATE
# ============================================================

http_session = None
badge_webhook = None
game_webhook = None

# Prevent simultaneous reads/writes to JSON files.
file_lock = asyncio.Lock()

# Prevent too many Roblox requests at once.
api_semaphore = asyncio.Semaphore(API_CONCURRENCY)


# ============================================================
# FILE HELPERS
# ============================================================

def ensure_json_file(path):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2)


ensure_json_file(BADGE_FILE)
ensure_json_file(GAME_FILE)


async def load_json(path):
    async with file_lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            print(f"⚠️ Could not properly read {path}. Using empty data.")
            return {}


async def save_json(path, data):
    async with file_lock:
        temp_path = f"{path}.tmp"

        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        # Replace old file atomically.
        os.replace(temp_path, path)


# ============================================================
# ROBLOX API HELPERS
# ============================================================

async def roblox_get(url, headers=None):
    """
    GET request with:
    - shared session
    - concurrency limit
    - timeout
    - basic HTTP validation
    """

    if http_session is None:
        raise RuntimeError("HTTP session has not been initialized.")

    async with api_semaphore:
        try:
            async with http_session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as response:

                if response.status != 200:
                    print(
                        f"⚠️ Roblox API returned HTTP {response.status}: {url}"
                    )
                    return None

                return await response.json()

        except asyncio.TimeoutError:
            print(f"⏰ Roblox API timeout: {url}")
            return None

        except aiohttp.ClientError as e:
            print(f"🌐 Roblox API connection error: {e}")
            return None

        except Exception as e:
            print(f"❌ Unexpected Roblox API error: {e}")
            return None


def parse_roblox_timestamp(timestamp):
    """
    Handles Roblox ISO timestamps safely.

    Examples:
    2026-09-15T00:00:00Z
    2026-09-15T00:00:00.123Z
    2026-09-15T00:00:00.123456789Z
    """

    if not timestamp:
        return None

    try:
        timestamp = timestamp.replace("Z", "+00:00")

        dt = datetime.fromisoformat(timestamp)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except ValueError:
        print(f"⚠️ Could not parse Roblox timestamp: {timestamp}")
        return None


def discord_timestamp(dt):
    if not dt:
        return "Unknown"

    return f"<t:{int(dt.timestamp())}:R>"


# ============================================================
# ROBLOX GAME HELPERS
# ============================================================

async def get_game(universe_id):
    url = (
        f"https://games.roblox.com/v1/games"
        f"?universeIds={universe_id}"
    )

    data = await roblox_get(url)

    if not data or not data.get("data"):
        return None

    return data["data"][0]


async def get_subplaces(universe_id):
    url = (
        f"https://develop.roblox.com/v1/universes/"
        f"{universe_id}/places"
    )

    data = await roblox_get(url)

    if not data:
        return []

    return data.get("data", [])


async def get_subplace_update(universe_id, subplace):
    subplace_id = str(subplace["id"])
    subplace_name = subplace["name"]

    url = (
        f"https://apis.roblox.com/cloud/v2/universes/"
        f"{universe_id}/places/{subplace_id}"
    )

    headers = {
        "x-api-key": OPEN_CLOUD_API_KEY
    }

    data = await roblox_get(url, headers=headers)

    if not data:
        return None

    update_time = data.get("updateTime")

    if not update_time:
        return None

    return {
        "id": subplace_id,
        "name": subplace_name,
        "update_time": update_time,
        "datetime": parse_roblox_timestamp(update_time)
    }


async def get_game_thumbnail(universe_id):
    url = (
        f"https://thumbnails.roblox.com/v1/games/icons"
        f"?universeIds={universe_id}"
        f"&size=150x150"
        f"&format=Png"
        f"&isCircular=false"
    )

    data = await roblox_get(url)

    try:
        return data["data"][0]["imageUrl"]
    except (KeyError, IndexError, TypeError):
        return None


# ============================================================
# ROBLOX BADGE HELPERS
# ============================================================

async def get_badge(badge_id):
    url = f"https://badges.roblox.com/v1/badges/{badge_id}"

    return await roblox_get(url)


async def get_badge_thumbnail(badge_id):
    url = (
        f"https://thumbnails.roblox.com/v1/badges/icons"
        f"?badgeIds={badge_id}"
        f"&size=150x150"
        f"&format=Png"
    )

    data = await roblox_get(url)

    try:
        return data["data"][0]["imageUrl"]
    except (KeyError, IndexError, TypeError):
        return None


# ============================================================
# WEBHOOK
# ============================================================

async def send_webhook(embed, webhook):
    if webhook is None:
        print("⚠️ Webhook is not initialized.")
        return

    try:
        await webhook.send(embed=embed)
    except discord.HTTPException as e:
        print(f"❌ Discord webhook error: {e}")
    except Exception as e:
        print(f"❌ Failed to send webhook: {e}")


# ============================================================
# BOT STARTUP
# ============================================================

@bot.event
async def setup_hook():
    global http_session
    global badge_webhook
    global game_webhook

    http_session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=20)
    )

    badge_webhook = discord.Webhook.from_url(
    BADGE_WEBHOOK_URL,
    session=http_session
)

    game_webhook = discord.Webhook.from_url(
    GAME_WEBHOOK_URL,
    session=http_session
)

    guild = discord.Object(id=1353485428942176276)

    tree.copy_global_to(guild=guild)
    await tree.sync(guild=guild)

    print("✅ Slash commands synced.")

@bot.event
async def on_ready():
    print(f"✅ Bot connected as {bot.user}")

    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="Pleiades Watchtower"
        )
    )

    if not check_badge_updates.is_running():
        check_badge_updates.start()
        print("Started badge updates.")

    if not check_game_updates.is_running():
        check_game_updates.start()
        print("Started game updates.")


# ============================================================
# BADGE TRACKER
# ============================================================

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_badge_updates():

    tracked = await load_json(BADGE_FILE)

    if not tracked:
        return

    changed = False

    for badge_id, old_count in list(tracked.items()):

        try:
            badge_info = await get_badge(badge_id)

            if not badge_info:
                continue

            new_count = badge_info.get("statistics", {}).get(
                "awardedCount"
            )

            if new_count is None:
                continue

            # Keep your original <200 behavior.
            if old_count != new_count and new_count < 200:

                change = new_count - old_count

                # Avoid displaying +negative incorrectly.
                change_text = f"{change:+d}"

                embed = discord.Embed(
                    title=f"Badge Update: {badge_info.get('name', 'Unknown')}",
                    description=(
                        f"↳ **Badge:** "
                        f"`{badge_info.get('name', 'Unknown')} ({badge_id})`\n"
                        f"↳ **Game:** "
                        f"`{badge_info.get('awardingUniverse', {}).get('name', 'Unknown')}`\n"
                        f"↳ **Badge Count:** "
                        f"`{old_count}` → `{new_count}` "
                        f"`({change_text})`"
                    ),
                    color=discord.Color.blue()
                )

                thumbnail = await get_badge_thumbnail(badge_id)

                if thumbnail:
                    embed.set_thumbnail(url=thumbnail)

                embed.set_footer(text="Badge Update")
                embed.timestamp = datetime.now(timezone.utc)

                await send_webhook(embed, badge_webhook)

                tracked[badge_id] = new_count
                changed = True

            elif old_count != new_count:

                # Keep tracking current value even when >= 200.
                tracked[badge_id] = new_count
                changed = True

        except Exception as e:
            print(f"❌ Error checking badge {badge_id}: {e}")

    if changed:
        await save_json(BADGE_FILE, tracked)


# ============================================================
# GAME TRACKER
# ============================================================

async def check_single_subplace(
    universe_id,
    subplace,
    last_subplace_updates
):
    """
    Checks one subplace.

    Returns:
        updated_info or None
    """

    result = await get_subplace_update(
        universe_id,
        subplace
    )

    if not result:
        return None

    subplace_id = result["id"]
    update_time = result["update_time"]
    subplace_name = result["name"]
    sub_dt = result["datetime"]

    last_recorded = last_subplace_updates.get(subplace_id)

    if update_time == last_recorded:
        return None

    return {
        "id": subplace_id,
        "name": subplace_name,
        "update_time": update_time,
        "datetime": sub_dt
    }


@tasks.loop(seconds=CHECK_INTERVAL)
async def check_game_updates():

    tracked = await load_json(GAME_FILE)

    if not tracked:
        return

    changed = False

    # Backward compatibility with your old format.
    for universe_id in list(tracked.keys()):

        if isinstance(tracked[universe_id], str):
            tracked[universe_id] = {
                "universe_update": tracked[universe_id],
                "subplaces": {}
            }

            changed = True

    for universe_id, data in list(tracked.items()):

        try:
            last_game_update = data.get(
                "universe_update",
                ""
            )

            last_subplace_updates = data.get(
                "subplaces",
                {}
            )

            # ------------------------------------------------
            # Main game
            # ------------------------------------------------

            game = await get_game(universe_id)

            if not game:
                print(
                    f"⚠️ Could not retrieve game {universe_id}"
                )
                continue

            game_name = game.get(
                "name",
                "Unknown Game"
            )

            root_place_id = game.get(
                "rootPlaceId"
            )

            updated = game.get(
                "updated",
                ""
            )

            game_dt = parse_roblox_timestamp(updated)

            game_updated = (
                bool(last_game_update)
                and updated != last_game_update
            )

            # ------------------------------------------------
            # Subplaces
            # ------------------------------------------------

            subplace_list = await get_subplaces(
                universe_id
            )

            # Run all subplace checks concurrently.
            results = await asyncio.gather(
                *[
                    check_single_subplace(
                        universe_id,
                        subplace,
                        last_subplace_updates
                    )
                    for subplace in subplace_list
                ],
                return_exceptions=True
            )

            updated_subplaces = []
            new_subplace_updates = dict(
                last_subplace_updates
            )

            for result in results:

                if isinstance(result, Exception):
                    print(
                        f"❌ Subplace check error for "
                        f"{universe_id}: {result}"
                    )
                    continue

                if not result:
                    continue

                subplace_id = result["id"]
                subplace_name = result["name"]
                update_time = result["update_time"]
                sub_dt = result["datetime"]

                subplace_link = (
                    f"https://www.roblox.com/games/"
                    f"{subplace_id}"
                )

                updated_subplaces.append(
                    f"[{subplace_name}]({subplace_link}) "
                    f"- Updated At: "
                    f"{discord_timestamp(sub_dt)}"
                )

                new_subplace_updates[subplace_id] = (
                    update_time
                )

            # ------------------------------------------------
            # Available subplace links
            # ------------------------------------------------

            subplace_links = []

            for subplace in subplace_list:

                subplace_id = str(
                    subplace["id"]
                )

                subplace_name = subplace["name"]

                subplace_link = (
                    f"https://www.roblox.com/games/"
                    f"{subplace_id}"
                )

                subplace_links.append(
                    f"[{subplace_name}]"
                    f"({subplace_link})"
                )

            # ------------------------------------------------
            # Send notification
            # ------------------------------------------------

            if game_updated or updated_subplaces:

                embed = discord.Embed(
                    title=f"🚨 Game Updated: {game_name}",
                    url=(
                        f"https://www.roblox.com/games/"
                        f"{root_place_id}"
                    ),
                    description=(
                        f"The game `{game_name}` "
                        f"has been updated!"
                    ),
                    color=discord.Color.blue()
                )

                thumbnail = await get_game_thumbnail(
                    universe_id
                )

                if thumbnail:
                    embed.set_thumbnail(
                        url=thumbnail
                    )

                embed.add_field(
                    name="Universe ID",
                    value=universe_id
                )

                embed.add_field(
                    name="Updated At",
                    value=discord_timestamp(game_dt)
                )

                embed.add_field(
                    name="Available Subplaces:",
                    value=(
                        "\n".join(subplace_links)
                        if subplace_links
                        else "No subplaces found."
                    ),
                    inline=False
                )

                embed.add_field(
                    name="Recently Updated Subplaces:",
                    value=(
                        "\n".join(updated_subplaces)
                        if updated_subplaces
                        else "No updated subplaces"
                    ),
                    inline=False
                )

                embed.set_footer(
                    text="Game Update"
                )

                embed.timestamp = datetime.now(
                    timezone.utc
                )

                await send_webhook(embed, game_webhook)

            # ------------------------------------------------
            # Save current state
            # ------------------------------------------------

            new_data = {
                "name": data.get(
                    "name",
                    game_name
                ),
                "universe_update": updated,
                "subplaces": new_subplace_updates
}

            if tracked[universe_id] != new_data:
                tracked[universe_id] = new_data
                changed = True

        except Exception as e:
            print(
                f"❌ Error checking game "
                f"{universe_id}: {e}"
            )

    if changed:
        await save_json(GAME_FILE, tracked)


# ============================================================
# LOOP ERROR HANDLERS
# ============================================================

@check_badge_updates.before_loop
async def before_badge_loop():
    await bot.wait_until_ready()


@check_game_updates.before_loop
async def before_game_loop():
    await bot.wait_until_ready()


# ============================================================
# ROLE CHECK
# ============================================================

def has_required_role(
    interaction: discord.Interaction
) -> bool:

    if not isinstance(
        interaction.user,
        discord.Member
    ):
        return False

    return any(
        role.id == AUTHORIZED_ROLE_ID
        for role in interaction.user.roles
    )


# ============================================================
# GAME COMMANDS
# ============================================================

@tree.command(
    name="addgame",
    description="Add a game to track by universe ID"
)
@app_commands.describe(
    universe_id="The Universe ID of the game"
)
async def add_game_slash(
    interaction: discord.Interaction,
    universe_id: str
):

    if not has_required_role(interaction):
        await interaction.response.send_message(
            "Unauthorized Request",
            ephemeral=True
        )
        return

    universe_id = universe_id.strip()

    if not universe_id.isdigit():
        await interaction.response.send_message(
            "❌ Invalid Universe ID.",
            ephemeral=True
        )
        return

    tracked = await load_json(GAME_FILE)

    if universe_id in tracked:
        await interaction.response.send_message(
            "Game already tracked.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    game = await get_game(universe_id)

    if not game:
        await interaction.followup.send(
            "❌ Could not find a Roblox game with that Universe ID."
        )
        return

    # Get current state immediately.
    # This prevents the bot from treating the initial state
    # as an update on the next polling cycle.

    subplaces = await get_subplaces(universe_id)

    subplace_states = {}

    results = await asyncio.gather(
        *[
            get_subplace_update(
                universe_id,
                subplace
            )
            for subplace in subplaces
        ],
        return_exceptions=True
    )

    for result in results:
        if isinstance(result, Exception) or not result:
            continue

        subplace_states[result["id"]] = (
            result["update_time"]
        )

    tracked[universe_id] = {
        "name": game.get(
            "name",
            "Unknown Game"
        ),
        "universe_update": game.get(
            "updated",
            ""
        ),
        "subplaces": subplace_states
}

    await save_json(GAME_FILE, tracked)

    await interaction.followup.send(
        f"✅ Now tracking **{game.get('name', 'Unknown Game')}** "
        f"(`{universe_id}`)."
    )


@tree.command(
    name="removegame",
    description="Remove a tracked game by universe ID"
)
@app_commands.describe(
    universe_id="The Universe ID of the game"
)
async def remove_game_slash(
    interaction: discord.Interaction,
    universe_id: str
):

    if not has_required_role(interaction):
        await interaction.response.send_message(
            "Unauthorized Request",
            ephemeral=True
        )
        return

    tracked = await load_json(GAME_FILE)

    if universe_id not in tracked:
        await interaction.response.send_message(
            "Game not tracked.",
            ephemeral=True
        )
        return

    del tracked[universe_id]

    await save_json(GAME_FILE, tracked)

    await interaction.response.send_message(
        "✅ Game removed.",
        ephemeral=True
    )


@tree.command(
    name="listgames",
    description="List all tracked games"
)
async def list_games_slash(
    interaction: discord.Interaction
):

    if not has_required_role(interaction):
        await interaction.response.send_message(
            "Unauthorized Request",
            ephemeral=True
        )
        return

    tracked = await load_json(GAME_FILE)

    if not tracked:
        await interaction.response.send_message(
            "No games are currently being tracked.",
            ephemeral=True
        )
        return

    results = []

    for universe_id, game_data in tracked.items():

        game_name = game_data.get(
            "name",
            "[Unknown Game]"
        )

        results.append(
            f"**{game_name}** (`{universe_id}`)"
        )

    await interaction.response.send_message(
        "Tracked games:\n" + "\n".join(results)
    )

@tree.command(
    name="gamecheck",
    description="Manually check a Roblox game and send its current update info"
)
@app_commands.describe(
    universe_id="The Universe ID of the game"
)
async def game_check_slash(
    interaction: discord.Interaction,
    universe_id: str
):
    if not has_required_role(interaction):
        await interaction.response.send_message(
            "Unauthorized Request",
            ephemeral=True
        )
        return

    universe_id = universe_id.strip()

    if not universe_id.isdigit():
        await interaction.response.send_message(
            "❌ Invalid Universe ID.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    game = await get_game(universe_id)

    if not game:
        await interaction.followup.send(
            "❌ Could not find a Roblox game with that Universe ID.",
            ephemeral=True
        )
        return

    game_name = game.get(
        "name",
        "Unknown Game"
    )

    root_place_id = game.get(
        "rootPlaceId"
    )

    # Get root Place update time from Open Cloud
    root_update_time = None

    if root_place_id:
        root_url = (
            f"https://apis.roblox.com/cloud/v2/universes/"
            f"{universe_id}/places/{root_place_id}"
        )

        headers = {
            "x-api-key": OPEN_CLOUD_API_KEY
        }

        root_data = await roblox_get(
            root_url,
            headers=headers
        )

        if root_data:
            root_update_time = root_data.get(
                "updateTime"
            )

    root_dt = parse_roblox_timestamp(
        root_update_time
    )

    # Get all subplaces
    subplace_list = await get_subplaces(
        universe_id
    )

    results = await asyncio.gather(
        *[
            get_subplace_update(
                universe_id,
                subplace
            )
            for subplace in subplace_list
        ],
        return_exceptions=True
    )

    updated_subplaces = []
    subplace_links = []

    for subplace in subplace_list:
        subplace_id = str(
            subplace["id"]
        )
        subplace_name = subplace["name"]

        subplace_link = (
            f"https://www.roblox.com/games/"
            f"{subplace_id}"
        )

        subplace_links.append(
            f"[{subplace_name}]"
            f"({subplace_link})"
        )

    for result in results:
        if isinstance(result, Exception):
            print(
                f"❌ Subplace check error for "
                f"{universe_id}: {result}"
            )
            continue

        if not result:
            continue

        subplace_name = result["name"]
        update_time = result["update_time"]
        sub_dt = result["datetime"]

        subplace_link = (
            f"https://www.roblox.com/games/"
            f"{result['id']}"
        )

        updated_subplaces.append(
            f"[{subplace_name}]({subplace_link}) "
            f"- Updated At: "
            f"{discord_timestamp(sub_dt)}"
        )

    embed = discord.Embed(
        title=f"🔎 Game Check: {game_name}",
        url=(
            f"https://www.roblox.com/games/"
            f"{root_place_id}"
        ),
        description=(
            f"Current update information for "
            f"`{game_name}`."
        ),
        color=discord.Color.blue()
    )

    thumbnail = await get_game_thumbnail(
        universe_id
    )

    if thumbnail:
        embed.set_thumbnail(
            url=thumbnail
        )

    embed.add_field(
        name="Universe ID",
        value=universe_id
    )

    embed.add_field(
        name="Updated At",
        value=discord_timestamp(root_dt)
    )

    embed.add_field(
        name="Available Subplaces:",
        value=(
            "\n".join(subplace_links)
            if subplace_links
            else "No subplaces found."
        ),
        inline=False
    )

    embed.add_field(
        name="Subplace Update Times:",
        value=(
            "\n".join(updated_subplaces)
            if updated_subplaces
            else "No subplace update information found."
        ),
        inline=False
    )

    embed.set_footer(
        text="Manual Game Check"
    )

    embed.timestamp = datetime.now(
        timezone.utc
    )

    await send_webhook(embed, game_webhook)

    await interaction.followup.send(
        f"✅ Game check sent for **{game_name}**.",
        ephemeral=True
    )


# ============================================================
# BADGE COMMANDS
# ============================================================

@tree.command(
    name="addbadge",
    description="Add a badge to track by badge ID"
)
@app_commands.describe(
    badge_id="The Badge ID"
)
async def add_badge_slash(
    interaction: discord.Interaction,
    badge_id: str
):

    if not has_required_role(interaction):
        await interaction.response.send_message(
            "Unauthorized Request",
            ephemeral=True
        )
        return

    badge_id = badge_id.strip()

    if not badge_id.isdigit():
        await interaction.response.send_message(
            "❌ Invalid Badge ID.",
            ephemeral=True
        )
        return

    tracked = await load_json(BADGE_FILE)

    if badge_id in tracked:
        await interaction.response.send_message(
            "Badge already tracked.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    badge = await get_badge(badge_id)

    if not badge:
        await interaction.followup.send(
            "❌ Could not find that Roblox badge."
        )
        return

    current_count = badge.get(
        "statistics",
        {}
    ).get(
        "awardedCount"
    )

    if current_count is None:
        await interaction.followup.send(
            "❌ Could not retrieve the badge's awarded count."
        )
        return

    # Start at the CURRENT count rather than 0.
    tracked[badge_id] = current_count

    await save_json(BADGE_FILE, tracked)

    await interaction.followup.send(
        f"✅ Now tracking **{badge.get('name', 'Unknown Badge')}** "
        f"(`{badge_id}`).\n"
        f"Current awarded count: **{current_count}**"
    )


@tree.command(
    name="removebadge",
    description="Remove a tracked badge by badge ID"
)
@app_commands.describe(
    badge_id="The Badge ID"
)
async def remove_badge_slash(
    interaction: discord.Interaction,
    badge_id: str
):

    if not has_required_role(interaction):
        await interaction.response.send_message(
            "Unauthorized Request",
            ephemeral=True
        )
        return

    tracked = await load_json(BADGE_FILE)

    if badge_id not in tracked:
        await interaction.response.send_message(
            "Badge not tracked.",
            ephemeral=True
        )
        return

    del tracked[badge_id]

    await save_json(BADGE_FILE, tracked)

    await interaction.response.send_message(
        "✅ Badge removed.",
        ephemeral=True
    )


@tree.command(
    name="listbadges",
    description="List all tracked badges"
)
async def list_badges_slash(
    interaction: discord.Interaction
):

    if not has_required_role(interaction):
        await interaction.response.send_message(
            "Unauthorized Request",
            ephemeral=True
        )
        return

    tracked = await load_json(BADGE_FILE)

    if not tracked:
        await interaction.response.send_message(
            "No badges are currently being tracked.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    async def fetch_badge_name(badge_id):

        badge = await get_badge(badge_id)

        if badge:
            return (
                f"**{badge.get('name', 'Unknown Badge')}** "
                f"(`{badge_id}`)"
            )

        return f"**[Unknown Badge]** (`{badge_id}`)"

    results = await asyncio.gather(
        *[
            fetch_badge_name(badge_id)
            for badge_id in tracked
        ]
    )

    await interaction.followup.send(
        "Tracked badges:\n" + "\n".join(results)
    )


# ============================================================
# COMMANDS / HELP
# ============================================================

@tree.command(
    name="commands",
    description="List all available bot commands"
)
async def commands_slash(
    interaction: discord.Interaction
):

    if not has_required_role(interaction):
        await interaction.response.send_message(
            "Unauthorized Request",
            ephemeral=True
        )
        return

    help_text = (
        "**🛠️ Available Slash Commands:**\n\n"

        "📌 `/addgame <universe_id>` "
        "— Add a game to track using the Universe ID.\n"

        "📌 `/removegame <universe_id>` "
        "— Remove a tracked game.\n"

        "📌 `/gamecheck <universe_id>` "
        "— Manually check a currently tracked Roblox game and send its current update info \n"

        "📌 `/listgames` "
        "— List all tracked games.\n\n"

        "📌 `/addbadge <badge_id>` "
        "— Add a badge to track.\n"

        "📌 `/removebadge <badge_id>` "
        "— Remove a tracked badge.\n"

        "📌 `/listbadges` "
        "— List all tracked badges.\n\n"

        "🕵️ `/commands` "
        "— Show this help message."
    )

    await interaction.response.send_message(
        help_text,
        ephemeral=True
    )


# ============================================================
# SCRIPTED'S CURSE
# ============================================================


GIFS = [
    "https://media.discordapp.net/attachments/1004788285605937192/1377477846313992252/watermark.gif?ex=685573f6&is=68542276&hm=30a58c9f4c6ee6af05ef4c30aa81ff94db662bccc31a1a30a3f180c0768a1d9d&=&width=1050&height=578",

    "https://cdn.discordapp.com/attachments/983841637295865906/1364670601209446562/giffy.gif?ex=685500c9&is=6853af49&hm=c80af5b472e3c7e05af57833fbf907e6fc83710af9f94d677c5e9bcff9eb8a95&",

    "https://tenor.com/view/sonic-boom-shut-up-mf-sonic-and-knuckles-gif-11592251616573120658",

    "https://cdn.discordapp.com/attachments/737764979654131813/1362874297537925430/speechmemified_Screenshot_2025-04-18_202035.gif?ex=68550f59&is=6853bdd9&hm=6d6c79a0113ae52a54a98240ee63b36466f29a2134a8c171&",

    "https://cdn.discordapp.com/attachments/1332761690647040011/1348785501729194044/togif.gif?ex=685538a2&is=6853e722&hm=d28d09a1f2ca00d2e0991624f8d293e3c5dd816094b4e9cb01e9ab139da18933&",

    "https://media.discordapp.net/attachments/1061072781678227506/1061073289348386886/cta.gif?ex=68554ec1&is=6853fd41&hm=a69924f159330a26f9a9b01a198a6d15b27f0d242b0d71722920645997770286&",

    "https://tenor.com/view/mcdonalds-mcdonald's-mcdonald's-soap-gif-mcdonalds-soap-gif-legend-4x-gif-14156725404483926518",

    "https://media.discordapp.net/attachments/1099448217290149891/1272444913170255912/attachment.gif?ex=685502ac&is=6853b12c&hm=186ade644acef91a6f684591c3d76e2c9b3b9c25c508fe8771260f96ecabffb6&",

    "https://cdn.discordapp.com/attachments/1266843788425302138/1340407535395672065/attachment-10.gif?ex=6855108c&is=6853bf0c&hm=e57183915d52715b2fc1ed010d127db9780264bcb78a2b985aa47485706aa2b8&"
]


@bot.event
async def on_message(message):

    if message.author.id == bot.user.id:
        return

    # --------------------------------------------------------
    # Scripted
    # --------------------------------------------------------

    if message.author.id == SCRIPTED_USER_ID:

        try:
            await message.add_reaction("🖕")

        except Exception as e:
            print(
                f"Failed to react to target user message: {e}"
            )

    # --------------------------------------------------------
    # Mention Scripted
    # --------------------------------------------------------

    if message.mentions:

        if any(
            user.id == SCRIPTED_USER_ID
            for user in message.mentions
        ):

            try:
                await message.add_reaction("🖕")

            except Exception as e:
                print(
                    f"Failed to react to mention message: {e}"
                )

    # --------------------------------------------------------
    # Anyone pings bot
    # --------------------------------------------------------

    if (
        bot.user in message.mentions
        and not message.content.startswith("!")
        and not message.content.startswith("/")
    ):

        try:

            await message.reply(
                random.choice(GIFS)
            )

        except Exception as e:
            print(
                f"Failed to respond to bot ping: {e}"
            )

    await bot.process_commands(message)


# ============================================================
# SHUTDOWN
# ============================================================

async def close_http_session():
    global http_session

    if http_session:
        await http_session.close()
        http_session = None


# ============================================================
# RUN
# ============================================================

try:
    bot.run(TOKEN)

finally:
    try:
        asyncio.run(close_http_session())
    except Exception:
        pass
