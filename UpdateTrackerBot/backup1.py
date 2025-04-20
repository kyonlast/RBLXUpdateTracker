import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone
import requests
import json
import os

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

games_file = 'tracked_games.json'
badges_file = 'tracked_badges.json'

webhook_url = 'https://discord.com/api/webhooks/1363097385365934350/9ljF4DV7P8yTVdbmYhGaKB9mIhKFm7mh-GOYiLnt6thSBU5WAVK3sdIdIpiUYvVsaQd8'

# Ensure the JSON files exist
for file in [games_file, badges_file]:
    if not os.path.exists(file):
        with open(file, 'w') as f:
            json.dump([], f)

def load_data(file):
    with open(file, 'r') as f:
        return json.load(f)

def save_data(file, data):
    with open(file, 'w') as f:
        json.dump(data, f, indent=2)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    check_updates.start()

@bot.command()
async def addgame(ctx, game_id: int):
    response = requests.get(f"https://games.roblox.com/v1/games?universeIds={game_id}")
    data = response.json()

    if not data["data"]:
        await ctx.send("Game not found.")
        return

    game_data = data["data"][0]

    tracked = load_data(games_file)
    if any(game['id'] == game_id for game in tracked):
        await ctx.send("Game already tracked.")
        return

    tracked.append({
        "id": game_id,
        "name": game_data['name'],
        "updated": datetime.now(timezone.utc).isoformat()
    })
    save_data(games_file, tracked)
    await ctx.send(f"Added game: {game_data['name']} ({game_id})")

@bot.command()
async def removegame(ctx, game_id: int):
    tracked = load_data(games_file)
    updated = [game for game in tracked if game['id'] != game_id]

    if len(tracked) == len(updated):
        await ctx.send("Game ID not found.")
        return

    save_data(games_file, updated)
    await ctx.send(f"Removed game ID: {game_id}")

@bot.command()
async def listgames(ctx):
    tracked = load_data(games_file)
    if not tracked:
        await ctx.send("No games are currently being tracked.")
        return

    msg = "**Tracked Games:**\n"
    for game in tracked:
        msg += f"{game['name']} (ID: {game['id']})\n"
    await ctx.send(msg)

@bot.command()
async def addbadge(ctx, badge_id: int):
    response = requests.get(f"https://badges.roblox.com/v1/badges/{badge_id}")
    if response.status_code != 200:
        await ctx.send("Badge not found.")
        return

    badge_data = response.json()
    tracked = load_data(badges_file)
    if any(badge['id'] == badge_id for badge in tracked):
        await ctx.send("Badge already tracked.")
        return

    tracked.append({
        "id": badge_id,
        "name": badge_data['name'],
        "updated": datetime.now(timezone.utc).isoformat()
    })
    save_data(badges_file, tracked)
    await ctx.send(f"Added badge: {badge_data['name']} ({badge_id})")

@bot.command()
async def removebadge(ctx, badge_id: int):
    tracked = load_data(badges_file)
    updated = [badge for badge in tracked if badge['id'] != badge_id]

    if len(tracked) == len(updated):
        await ctx.send("Badge ID not found.")
        return

    save_data(badges_file, updated)
    await ctx.send(f"Removed badge ID: {badge_id}")

@bot.command()
async def listbadges(ctx):
    tracked = load_data(badges_file)
    if not tracked:
        await ctx.send("No badges are currently being tracked.")
        return

    msg = "**Tracked Badges:**\n"
    for badge in tracked:
        msg += f"{badge['name']} (ID: {badge['id']})\n"
    await ctx.send(msg)

@tasks.loop(minutes=5)
async def check_updates():
    games = load_data(games_file)
    updated_games = []
    for game in games:
        response = requests.get(f"https://games.roblox.com/v1/games?universeIds={game['id']}")
        if not response.ok:
            continue

        data = response.json()["data"]
        if not data:
            continue

        game_data = data[0]
        last_update = game['updated']
        current_update = game_data['updated']

        if current_update != last_update:
            game['updated'] = current_update
            updated_games.append(game)

    if updated_games:
        msg = "**Game Updates Detected:**\n"
        for game in updated_games:
            msg += f"{game['name']} (ID: {game['id']}) was updated.\n"
        requests.post(webhook_url, json={"content": msg})

        save_data(games_file, games)

bot.run('MTM2MjgxMzEzODc1OTg0NDA1Mg.Gdtj0p.jO_2yyf680PxP4fr9XXEI2GGDTobjt1G-39oAA')
