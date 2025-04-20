import discord
from discord.ext import commands, tasks
import requests
import aiohttp
import asyncio
import json
import os
from datetime import datetime, timezone

# Webhook URL
WEBHOOK_URL = "https://discord.com/api/webhooks/1363523928835752258/6wsRt0OZnjwOYeU82jXR8wG4cleFRX0xCfxayDzvAhZKRztenrlQ7ARE5zI53dODyRnl"

# Setup intents and bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# File names
GAMES_FILE = "tracked_games.json"
BADGES_FILE = "tracked_badges.json"

# Load or initialize JSON files
def load_json(filename):
    if not os.path.exists(filename):
        with open(filename, "w") as f:
            json.dump({}, f)
    with open(filename, "r") as f:
        return json.load(f)

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)

tracked_games = load_json(GAMES_FILE)
tracked_badges = load_json(BADGES_FILE)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    check_updates.start()

@tasks.loop(seconds=60)
async def check_updates():
    async with aiohttp.ClientSession() as session:
        for universe_id, data in tracked_games.items():
            try:
                url = f"https://games.roblox.com/v1/games?universeIds={universe_id}"
                async with session.get(url) as resp:
                    result = await resp.json()
                if not result.get("data"):
                    continue
                game_data = result["data"][0]

                icon_url = f"https://thumbnails.roblox.com/v1/games/icons?universeIds={universe_id}&size=256x256&format=Png&isCircular=false"
                async with session.get(icon_url) as resp:
                    icon_result = await resp.json()
                game_icon = icon_result["data"][0]["imageUrl"]

                # Check if updated
                last_updated = game_data["updated"]
                if last_updated != data.get("last_updated"):
                    universe_url = f"https://www.roblox.com/games/{game_data['rootPlaceId']}"
                    
                    # Get subplaces
                    subplaces_url = f"https://develop.roblox.com/v1/universes/{universe_id}/places"
                    async with session.get(subplaces_url) as resp:
                        subs = await resp.json()

                    updated_places = []
                    for place in subs["data"]:
                        place_id = str(place["id"])
                        if place_id not in data.get("places", {}):
                            updated_places.append(place)
                        else:
                            old_time = data["places"][place_id]
                            if place["updated"] != old_time:
                                updated_places.append(place)

                    data["last_updated"] = last_updated
                    for place in subs["data"]:
                        data.setdefault("places", {})[str(place["id"])] = place["updated"]

                    save_json(GAMES_FILE, tracked_games)

                    if updated_places:
                        embed = discord.Embed(
                            title=game_data["name"],
                            url=universe_url,
                            description=f"**Universe ID:** `{universe_id}`\n**Playable:** `{game_data['isPlayable']}`",
                            color=0x00ff00
                        )
                        embed.set_thumbnail(url=game_icon)
                        embed.add_field(name="Last Updated", value=f"<t:{int(datetime.strptime(last_updated, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc).timestamp())}:R>")

                        for place in updated_places:
                            embed.add_field(
                                name=place["name"],
                                value=f"[Place Link](https://www.roblox.com/games/{place['id']}) | Updated: <t:{int(datetime.strptime(place['updated'], '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc).timestamp())}:R> | Public: `{place['isPlayable']}`",
                                inline=False
                            )

                        async with session.post(WEBHOOK_URL, json={"embeds": [embed.to_dict()]}) as resp:
                            pass
            except Exception as e:
                print(f"Error checking game {universe_id}: {e}")

        for badge_id, badge_data in tracked_badges.items():
            try:
                url = f"https://badges.roblox.com/v1/badges/{badge_id}"
                async with session.get(url) as resp:
                    badge = await resp.json()

                if "errors" in badge:
                    continue

                current_awarded = badge["awardedCount"]
                if current_awarded != badge_data.get("awardedCount"):
                    universe_url = f"https://www.roblox.com/games/{badge['assetId']}"
                    icon_url = f"https://thumbnails.roblox.com/v1/assets?assetIds={badge['id']}&size=150x150&format=png"
                    async with session.get(icon_url) as resp:
                        icon_data = await resp.json()
                    image_url = icon_data["data"][0]["imageUrl"]

                    embed = discord.Embed(
                        title=badge["name"],
                        description=f"**Badge ID:** `{badge_id}`\n**Awarded Count:** `{badge_data['awardedCount']} -> {current_awarded}`",
                        color=0xff0000
                    )
                    embed.set_thumbnail(url=image_url)
                    embed.add_field(name="Game", value=f"{badge['name']}")

                    tracked_badges[badge_id]["awardedCount"] = current_awarded
                    save_json(BADGES_FILE, tracked_badges)

                    await session.post(WEBHOOK_URL, json={"embeds": [embed.to_dict()]})

            except Exception as e:
                print(f"Error checking badge {badge_id}: {e}")

# --- Commands ---

@bot.command()
async def addgame(ctx, universe_id):
    tracked_games[str(universe_id)] = {"last_updated": "", "places": {}}
    save_json(GAMES_FILE, tracked_games)
    await ctx.send(f"Added game with universe ID {universe_id} to tracking list.")

@bot.command()
async def removegame(ctx, universe_id):
    if str(universe_id) in tracked_games:
        del tracked_games[str(universe_id)]
        save_json(GAMES_FILE, tracked_games)
        await ctx.send(f"Removed game with universe ID {universe_id} from tracking list.")

@bot.command()
async def listgames(ctx):
    if tracked_games:
        await ctx.send("Tracked Games:\n" + "\n".join(f"{uid}" for uid in tracked_games))
    else:
        await ctx.send("No games are being tracked.")

@bot.command()
async def addbadge(ctx, badge_id: int):
    response = requests.get(f"https://badges.roblox.com/v1/badges/{badge_id}")
    if response.status_code != 200:
        await ctx.send("❌ Invalid badge ID or unable to fetch badge data.")
        return

    badge = response.json()
    
    # Check for 'statistics' and 'awardedCount'
    awarded_count = badge.get("statistics", {}).get("awardedCount", None)
    if awarded_count is None:
        await ctx.send("❌ Couldn't find awarded count for this badge. It may not be public or is invalid.")
        return

    tracked_badges[str(badge_id)] = {"awardedCount": awarded_count}
    save_json("tracked_badges.json", tracked_badges)
    await ctx.send(f"✅ Added badge `{badge['name']}` with ID `{badge_id}`.")

@bot.command()
async def removebadge(ctx, badge_id):
    if str(badge_id) in tracked_badges:
        del tracked_badges[str(badge_id)]
        save_json(BADGES_FILE, tracked_badges)
        await ctx.send(f"Stopped tracking badge {badge_id}.")

@bot.command()
async def listbadges(ctx):
    if tracked_badges:
        await ctx.send("Tracked Badges:\n" + "\n".join(f"{bid}" for bid in tracked_badges))
    else:
        await ctx.send("No badges are being tracked.")

# Run the bot
bot.run("MTM2MjgxMzEzODc1OTg0NDA1Mg.G5ziKL.Q9kkepGY1puz0VpXkdM3IDxBYLMXmIslidLEGY")
