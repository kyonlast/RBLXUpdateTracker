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

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree  # This gives access to slash commands

SCRIPTED_USER_ID = 568741811099664386 
DUNKIN_USER_ID = 1290528478160228396
AUTHORIZED_ROLE_ID = 1367168922926841867  
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
OPEN_CLOUD_API_KEY = os.getenv("OPEN_CLOUD_API_KEY")
TOKEN = os.getenv("TOKEN")

# Check environment variables early
if not WEBHOOK_URL:
    print("❌ Error: WEBHOOK_URL environment variable is not set!")
if not OPEN_CLOUD_API_KEY:
    print("❌ Error: OPEN_CLOUD_API_KEY environment variable is not set!")
if not TOKEN:
    print("❌ Error: TOKEN environment variable is not set!")

if not WEBHOOK_URL or not OPEN_CLOUD_API_KEY or not TOKEN:
    print("❌ One or more environment variables are missing. Exiting the bot.")
    sys.exit(1)


# JSON files
BADGE_FILE = "tracked_badges.json"
GAME_FILE = "tracked_games.json"

# Initialize JSON files if they don't exist
if not os.path.exists(BADGE_FILE):
    with open(BADGE_FILE, "w") as f:
        json.dump({}, f)

if not os.path.exists(GAME_FILE):
    with open(GAME_FILE, "w") as f:
        json.dump({}, f)

async def send_webhook(embed):
    async with aiohttp.ClientSession() as session:
        webhook = discord.Webhook.from_url(WEBHOOK_URL, session=session)
        await webhook.send(embed=embed)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Bot connected as {bot.user}")

    # Set the bot's activity
    await bot.change_presence(activity=discord.Game(name="Deltarune"))

    if not check_badge_updates.is_running():
        check_badge_updates.start()
        print("Started badge updates.")
    else:
        print("⚠️ Badge update task already running.")

    if not check_game_updates.is_running():
        check_game_updates.start()
        print("Started game updates.")
    else:
        print("⚠️ Game update task already running.")

# Badge Tracker

@tasks.loop(seconds=60)
async def check_badge_updates():
    with open(BADGE_FILE, "r") as f:
        tracked = json.load(f)

    for badge_id, old_count in tracked.items():
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://badges.roblox.com/v1/badges/{badge_id}") as res:
                    badge_info = await res.json()

                new_count = badge_info["statistics"]["awardedCount"]
                
                # Only update if the badge count is less than 200
                if old_count != new_count and new_count < 200:
                    # Calculate the change in awarded count
                    change = new_count - old_count
                    embed = discord.Embed(
                        title=f"Badge Update: {badge_info['name']}",  # Badge title without ID
                        description=f"↳ **Badge:** `{badge_info['name']} ({badge_id})\n`"
                                    f"↳ **Game:** `{badge_info['awardingUniverse']['name']}\n`"
                                    f"↳ **Badge Count:** `{old_count}` → `{new_count}` `(+{change})`",  # Add game name here
                        color=discord.Color.blue()
                    )
                    embed.set_footer(text="Badge Update")
                    embed.timestamp = datetime.now(timezone.utc)

                    # Get the badge thumbnail
                    thumb_res = await session.get(f"https://thumbnails.roblox.com/v1/badges/icons?badgeIds={badge_id}&size=150x150&format=Png")
                    thumb_data = await thumb_res.json()
                    if thumb_data["data"] and thumb_data["data"][0]["imageUrl"]:
                        embed.set_thumbnail(url=thumb_data["data"][0]["imageUrl"])
                        await thumb_res.release()

                    await send_webhook(embed)
                    tracked[badge_id] = new_count

        except Exception as e:
            print(f"Error checking badge {badge_id}: {e}")

    with open(BADGE_FILE, "w") as f:
        json.dump(tracked, f, indent=2)


# Game Tracker with Subplaces and Main Game Update in One Message

@tasks.loop(seconds=60)
async def check_game_updates():
    with open(GAME_FILE, "r") as f:
        tracked = json.load(f)
    
    # Convert old format to new format (backward compatibility)
    for universe_id in list(tracked.keys()):
        if isinstance(tracked[universe_id], str):
            # This is the old format, so convert it to the new format
            tracked[universe_id] = {
                "universe_update": tracked[universe_id],  # Copy the last update timestamp
                "subplaces": {}  # Initialize subplaces as empty (it will be filled later)
            }
    
    for universe_id, data in tracked.items():
        try:
            last_game_update = data.get("universe_update", "")
            last_subplace_updates = data.get("subplaces", {})

            async with aiohttp.ClientSession() as session:
                # Get main game data
                async with session.get(f"https://games.roblox.com/v1/games?universeIds={universe_id}") as res:
                    game_data = await res.json()
                    game = game_data["data"][0]
                    updated = game["updated"]
                    root_place_id = game["rootPlaceId"]

                # Fix timestamp precision
                if "." in updated:
                    base, frac = updated.split(".")
                    frac = frac.rstrip("Z")[:6]
                    updated_trimmed = f"{base}.{frac}Z"
                else:
                    updated_trimmed = updated

                game_dt = datetime.strptime(updated_trimmed, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)

                game_updated = (updated != last_game_update)

                # Get subplaces
                subplace_url = f"https://develop.roblox.com/v1/universes/{universe_id}/places"
                async with session.get(subplace_url) as sub_res:
                    subplaces_data = await sub_res.json()
                    subplace_list = subplaces_data.get("data", [])

                # Check subplace updates using Open Cloud API
                headers = {
                    "x-api-key": OPEN_CLOUD_API_KEY
                }
                updated_subplaces = []
                subplace_links = []

                for subplace in subplace_list:
                    subplace_id = str(subplace["id"])
                    subplace_name = subplace["name"]
                    subplace_link = f"https://www.roblox.com/games/{subplace_id}"
                    subplace_links.append(f"[{subplace_name}]({subplace_link})")

                    cloud_url = f"https://apis.roblox.com/cloud/v2/universes/{universe_id}/places/{subplace_id}"
                    async with session.get(cloud_url, headers=headers) as cloud_res:
                        if cloud_res.status != 200:
                            continue
                        cloud_data = await cloud_res.json()

                    update_time = cloud_data.get("updateTime", "")
                    if "." in update_time:
                        base, frac = update_time.split(".")
                        frac = frac.rstrip("Z")[:6]
                        update_time = f"{base}.{frac}Z"

                    sub_dt = datetime.strptime(update_time, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)
                    last_recorded = last_subplace_updates.get(subplace_id)

                    if update_time != last_recorded:
                        updated_subplaces.append(f"[{subplace_name}]({subplace_link}) - Updated At: <t:{int(sub_dt.timestamp())}:R>")
                        last_subplace_updates[subplace_id] = update_time  # Update stored timestamp

                # Only send a message if the game or any subplace was updated
                if game_updated or updated_subplaces:
                    embed = discord.Embed(
                        title=f"🚨 Game Updated: {game['name']}",
                        url=f"https://www.roblox.com/games/{root_place_id}",
                        description=f"The game `{game['name']}` has been updated!",
                        color=discord.Color.blue()
                    )
                    embed.set_thumbnail(url=f"https://thumbnails.roblox.com/v1/games/icons?universeIds={universe_id}&size=150x150&format=Png&isCircular=false")
                    embed.add_field(name="Universe ID", value=universe_id)
                    embed.add_field(name="Updated At", value=f"<t:{int(game_dt.timestamp())}:R>")

                    embed.add_field(
                        name="Available Subplaces:",
                        value="\n".join(subplace_links) if subplace_links else "No subplaces found.",
                        inline=False
                    )

                    embed.add_field(
                        name="Recently Updated Subplaces:",
                        value="\n".join(updated_subplaces) if updated_subplaces else "No updated subplaces",
                        inline=False
                    )

                    embed.set_footer(text="Game Update")
                    embed.timestamp = datetime.now(timezone.utc)

                    await send_webhook(embed)

                # Update JSON file data
                tracked[universe_id] = {
                    "universe_update": updated,
                    "subplaces": last_subplace_updates
                }

        except Exception as e:
            print(f"Error checking game {universe_id}: {e}")

    with open(GAME_FILE, "w") as f:
        json.dump(tracked, f, indent=2)


# Role Check Function for Slash Commands
def has_required_role(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    return any(role.id == AUTHORIZED_ROLE_ID for role in interaction.user.roles)   

# Slash Commands:

# Slash command: Add Game
@tree.command(name="addgame", description="Add a game to track by universe ID")
@app_commands.describe(universe_id="The Universe ID of the game")
async def add_game_slash(interaction: discord.Interaction, universe_id: str):
    if not has_required_role(interaction):
        await interaction.response.send_message("Unauthorized Request")
        return

    with open(GAME_FILE, "r") as f:
        tracked = json.load(f)

    if universe_id in tracked:
        await interaction.response.send_message("Game already tracked.")
        return

    tracked[universe_id] = ""
    with open(GAME_FILE, "w") as f:
        json.dump(tracked, f, indent=2)

    await interaction.response.send_message("Game added.")

# Slash command: Remove Game
@tree.command(name="removegame", description="Remove a tracked game by universe ID")
@app_commands.describe(universe_id="The Universe ID of the game")
async def remove_game_slash(interaction: discord.Interaction, universe_id: str):
    if not has_required_role(interaction):
        await interaction.response.send_message("Unauthorized Request")
        return

    with open(GAME_FILE, "r") as f:
        tracked = json.load(f)

    if universe_id not in tracked:
        await interaction.response.send_message("Game not tracked.")
        return

    del tracked[universe_id]
    with open(GAME_FILE, "w") as f:
        json.dump(tracked, f, indent=2)

    await interaction.response.send_message("Game removed.")

# Slash command: List Games
@tree.command(name="listgames", description="List all tracked games")
async def list_games_slash(interaction: discord.Interaction):
    if not has_required_role(interaction):
        await interaction.response.send_message("Unauthorized Request")
        return

    with open(GAME_FILE, "r") as f:
        tracked = json.load(f)

    game_info = []
    async with aiohttp.ClientSession() as session:
        for universe_id in tracked.keys():
            try:
                async with session.get(f"https://games.roblox.com/v1/games?universeIds={universe_id}") as res:
                    game_data = await res.json()
                    game_name = game_data["data"][0]["name"]
                    game_info.append(f"**{game_name}** (`{universe_id}`)")
            except Exception as e:
                print(f"Error fetching game info for {universe_id}: {e}")
                game_info.append(f"**[Unknown Game]** (`{universe_id}`)")

    await interaction.response.send_message("Tracked games:\n" + "\n".join(game_info))

# Slash command: Add Badge
@tree.command(name="addbadge", description="Add a badge to track by badge ID")
@app_commands.describe(badge_id="The Badge ID")
async def add_badge_slash(interaction: discord.Interaction, badge_id: str):
    if not has_required_role(interaction):
        await interaction.response.send_message("Unauthorized Request")
        return

    with open(BADGE_FILE, "r") as f:
        tracked = json.load(f)

    if badge_id in tracked:
        await interaction.response.send_message("Badge already tracked.")
        return

    tracked[badge_id] = 0
    with open(BADGE_FILE, "w") as f:
        json.dump(tracked, f, indent=2)

    await interaction.response.send_message("Badge added.")

# Slash command: Remove Badge
@tree.command(name="removebadge", description="Remove a tracked badge by badge ID")
@app_commands.describe(badge_id="The Badge ID")
async def remove_badge_slash(interaction: discord.Interaction, badge_id: str):
    if not has_required_role(interaction):
        await interaction.response.send_message("Unauthorized Request")
        return

    with open(BADGE_FILE, "r") as f:
        tracked = json.load(f)

    if badge_id not in tracked:
        await interaction.response.send_message("Badge not tracked.")
        return

    del tracked[badge_id]
    with open(BADGE_FILE, "w") as f:
        json.dump(tracked, f, indent=2)

    await interaction.response.send_message("Badge removed.")

# Slash command: List Badges
@tree.command(name="listbadges", description="List all tracked badges")
async def list_badges_slash(interaction: discord.Interaction):
    if not has_required_role(interaction):
        await interaction.response.send_message("Unauthorized Request")
        return

    with open(BADGE_FILE, "r") as f:
        tracked = json.load(f)

    badge_info = []
    async with aiohttp.ClientSession() as session:
        for badge_id in tracked.keys():
            try:
                async with session.get(f"https://badges.roblox.com/v1/badges/{badge_id}") as res:
                    badge_data = await res.json()
                    badge_name = badge_data["name"]
                    badge_info.append(f"**{badge_name}** (`{badge_id}`)")
            except Exception as e:
                print(f"Error fetching badge info for {badge_id}: {e}")
                badge_info.append(f"**[Unknown Badge]** (`{badge_id}`)")

    await interaction.response.send_message("Tracked badges:\n" + "\n".join(badge_info))

# Slash command: Help
@tree.command(name="commands", description="List all available bot commands")
async def commands_slash(interaction: discord.Interaction):
    if not has_required_role(interaction):
        await interaction.response.send_message("Unauthorized Request")
        return

    help_text = (
        "**🛠️ Available Slash Commands:**\n\n"
        "📌 `/addgame <universe_id>` — Add a game to track using the Universe ID (not placeID).\n"
        "📌 `/removegame <universe_id>` — Remove a tracked game using the Universe ID (not placeID).\n"
        "📌 `/listgames` — List all tracked games.\n\n"
        "📌 `/addbadge <badge_id>` — Add a badge to track using the Badge ID.\n"
        "📌 `/removebadge <badge_id>` — Remove a tracked badge using the Badge ID.\n"
        "📌 `/listbadges` — List all tracked badges.\n\n"
        "🕵️ `/commands` — Show this help message."
    )
    await interaction.response.send_message(help_text, ephemeral=True)


# Scripted's Curse & Dunkin's Purgatory
@bot.event
async def on_message(message):
    if message.author.id == bot.user.id:
        return

    reacted = False

    # React if message is from the target user
    if message.author.id == SCRIPTED_USER_ID:
        try:
            await message.add_reaction("🖕")
            reacted = True
        except Exception as e:
            print(f"Failed to react to target user message: {e}")

    # React to Dunkin with 💀
    if message.author.id == DUNKIN_USER_ID:
        try:
            await message.add_reaction("💀")
            reacted = True
        except Exception as e:
            print(f"Failed to react to Dunkin's message: {e}")

    # React if message mentions the target user
    if not reacted and message.mentions:
        if any(user.id == SCRIPTED_USER_ID for user in message.mentions):
            try:
                await message.add_reaction("🖕")
            except Exception as e:
                print(f"Failed to react to mention message: {e}")

    # React if message mentions Dunkin
    if not reacted and message.mentions:
        if any(user.id == DUNKIN_USER_ID for user in message.mentions):
            try:
                await message.add_reaction("💀")
                reacted = True
            except Exception as e:
                print(f"Failed to react to mention message: {e}")

    # If Scripted pings the bot (not a command), reply with either a roast or a gif (randomly)
    if (
        message.author.id == SCRIPTED_USER_ID and
        bot.user in message.mentions and
        not message.content.startswith("!") and
        not message.content.startswith("/")
    ):
        roasts = [
    "FUCK YOU SCRIPTED 🖕",
    "stop jerking off to fortnite skins",
    "bfdi sucks bro",
    "stop sending toriel porn my nigga"
]

        gifs = [
            "https://media.discordapp.net/attachments/1004788285605937192/1377477846313992252/watermark.gif?ex=685573f6&is=68542276&hm=30a58c9f4c6ee6af05ef4c30aa81ff94db662bccc31a1a30a3f180c0768a1d9d&=&width=1050&height=578",
            "https://cdn.discordapp.com/attachments/983841637295865906/1364670601209446562/giffy.gif?ex=685500c9&is=6853af49&hm=c80af5b472e3c7e05af57833fbf907e6fc83710af9f94d677c5e9bcff9eb8a95&",
            "https://tenor.com/view/sonic-boom-shut-up-mf-sonic-and-knuckles-gif-11592251616573120658",
            "https://cdn.discordapp.com/attachments/737764979654131813/1362874297537925430/speechmemified_Screenshot_2025-04-18_202035.gif?ex=68550f59&is=6853bdd9&hm=6e23df9b522846c56d6c79a0113ae52a54a98240ee63b36466f29a2134a8c171&",
            "https://cdn.discordapp.com/attachments/1332761690647040011/1348785501729194044/togif.gif?ex=685538a2&is=6853e722&hm=d28d09a1f2ca00d2e0991624f8d293e3c5dd816094b4e9cb01e9ab139da18933&",
            "https://media.discordapp.net/attachments/1061072781678227506/1061073289348386886/cta.gif?ex=68554ec1&is=6853fd41&hm=a69924f159330a26f9a9b01a198a6d15b27f0d242b0d71722920645997770286&",
            "https://tenor.com/view/mcdonalds-mcdonald's-mcdonald's-soap-gif-mcdonalds-soap-gif-legend-4x-gif-14156725404483926518",
            "https://media.discordapp.net/attachments/1099448217290149891/1272444913170255912/attachment.gif?ex=685502ac&is=6853b12c&hm=186ade644acef91a6f684591c3d76e2c9b3b9c25c508fe8771260f96ecabffb6&",
            "https://cdn.discordapp.com/attachments/1266843788425302138/1340407535395672065/attachment-10.gif?ex=6855108c&is=6853bf0c&hm=e57183915d52715b2fc1ed010d127db9780264bcb78a2b985aa47485706aa2b8&"
        ]

        try:
            # Choose either roast or gif randomly
            if random.choice([True, False]):
                # Send roast as a reply
                await message.reply(random.choice(roasts))
            else:
                # Send gif URL as a reply
                await message.reply(random.choice(gifs))
        except Exception as e:
            print(f"Failed to respond to Scripted's ping: {e}")

    await bot.process_commands(message)




# Start the bot
bot.run(TOKEN)
