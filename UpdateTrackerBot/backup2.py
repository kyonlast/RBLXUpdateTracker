import discord
from discord.ext import commands, tasks
import requests
import json
import os
import asyncio
from datetime import datetime, timezone

# Define the bot object and intents
intents = discord.Intents.default()
intents.message_content = True  # Enable reading message content
bot = commands.Bot(command_prefix="!", intents=intents)

GAMES_FILE = "tracked_games.json"
BADGES_FILE = "tracked_badges.json"
WEBHOOK_URL = "https://discord.com/api/webhooks/1363097385365934350/9ljF4DV7P8yTVdbmYhGaKB9mIhKFm7mh-GOYiLnt6thSBU5WAVK3sdIdIpiUYvVsaQd8"

# Load tracked games
if os.path.exists(GAMES_FILE):
    with open(GAMES_FILE, "r") as f:
        tracked_games = json.load(f)
else:
    tracked_games = {}

# Load tracked badges
if os.path.exists(BADGES_FILE):
    with open(BADGES_FILE, "r") as f:
        tracked_badges = json.load(f)
else:
    tracked_badges = {}

def save_games():
    with open(GAMES_FILE, "w") as f:
        json.dump(tracked_games, f, indent=2)

def save_badges():
    with open(BADGES_FILE, "w") as f:
        json.dump(tracked_badges, f, indent=2)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    check_updates.start()

@tasks.loop(seconds=2)  # Checks for updates every 2 seconds
async def check_updates():
    for game_id, game in tracked_games.items():
        try:
            response = requests.get(f"https://games.roblox.com/v1/games?universeIds={game_id}")
            data = response.json()["data"][0]

            updated = data["updated"]
            subplace_updated = "N/A"  # Default if no subplace is available
            
            # Check if we have subplace data available (the API does not directly provide it)
            if 'subplace' in data:
                subplace_updated = data['subplace']

            if game["last_updated"] != updated:
                embed = discord.Embed(title="Game Updated!", color=0x00ff00)
                embed.add_field(name="Name", value=data["name"], inline=False)
                embed.add_field(name="Subplace", value=subplace_updated, inline=False)
                embed.add_field(name="Updated At", value=updated, inline=False)
                embed.set_footer(text=f"Universe ID: {game_id}")

                requests.post(WEBHOOK_URL, json={"embeds": [embed.to_dict()]})
                game["last_updated"] = updated
                save_games()
        except Exception as e:
            print(f"Error checking game {game_id}: {e}")

    for badge_id, badge in tracked_badges.items():
        try:
            response = requests.get(f"https://badges.roblox.com/v1/badges/{badge_id}")
            data = response.json()
            new_time = data["updated"]

            if badge["last_updated"] != new_time:
                embed = discord.Embed(title="Badge Updated!", color=0xff0000)
                embed.add_field(name="Name", value=data["name"], inline=False)
                embed.add_field(name="Updated At", value=new_time, inline=False)
                embed.set_footer(text=f"Badge ID: {badge_id}")

                requests.post(WEBHOOK_URL, json={"embeds": [embed.to_dict()]})
                badge["last_updated"] = new_time
                save_badges()
        except Exception as e:
            print(f"Error checking badge {badge_id}: {e}")

# Command to add a game
@bot.command()
async def addgame(ctx, universe_id: int):
    response = requests.get(f"https://games.roblox.com/v1/games?universeIds={universe_id}")
    data = response.json()["data"][0]
    tracked_games[str(universe_id)] = {
        "name": data["name"],
        "last_updated": data["updated"]
    }
    save_games()
    await ctx.send(f"Added game: {data['name']}")

# Command to remove a game
@bot.command()
async def removegame(ctx, universe_id: int):
    if str(universe_id) in tracked_games:
        del tracked_games[str(universe_id)]
        save_games()
        await ctx.send(f"Removed game with ID {universe_id}.")
    else:
        await ctx.send("Game not found.")

# Command to list all tracked games
@bot.command()
async def listgames(ctx):
    if not tracked_games:
        await ctx.send("No games are currently being tracked.")
    else:
        msg = "**Tracked Games:**\n"
        for gid, gdata in tracked_games.items():
            msg += f"{gdata['name']} (ID: {gid})\n"
        await ctx.send(msg)

# Command to add a badge
@bot.command()
async def addbadge(ctx, badge_id: int):
    response = requests.get(f"https://badges.roblox.com/v1/badges/{badge_id}")
    data = response.json()
    tracked_badges[str(badge_id)] = {
        "name": data["name"],
        "last_updated": data["updated"]
    }
    save_badges()
    await ctx.send(f"Added badge: {data['name']}")

# Command to remove a badge
@bot.command()
async def removebadge(ctx, badge_id: int):
    if str(badge_id) in tracked_badges:
        del tracked_badges[str(badge_id)]
        save_badges()
        await ctx.send(f"Removed badge with ID {badge_id}.")
    else:
        await ctx.send("Badge not found.")

# Command to list all tracked badges
@bot.command()
async def listbadges(ctx):
    if not tracked_badges:
        await ctx.send("No badges are currently being tracked.")
    else:
        msg = "**Tracked Badges:**\n"
        for bid, bdata in tracked_badges.items():
            msg += f"{bdata['name']} (ID: {bid})\n"
        await ctx.send(msg)

bot.run("MTM2MjgxMzEzODc1OTg0NDA1Mg.GgpWjK.90YlVXzXhWehMYLm74y_WV7knscDY2AdiBnfq4")
