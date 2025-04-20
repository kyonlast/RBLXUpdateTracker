import discord
from discord.ext import commands, tasks
import requests
import datetime
import asyncio

intents = discord.Intents.default()
intents.message_content = True  # THIS LINE IS REQUIRED
intents.guilds = True
intents.messages = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Replace with your own
TOKEN = 'MTM2MjgxMzEzODc1OTg0NDA1Mg.Gdtj0p.jO_2yyf680PxP4fr9XXEI2GGDTobjt1G-39oAA'
WEBHOOK_URL = 'https://discord.com/api/webhooks/1363097385365934350/9ljF4DV7P8yTVdbmYhGaKB9mIhKFm7mh-GOYiLnt6thSBU5WAVK3sdIdIpiUYvVsaQd8'

tracked_games = {}
tracked_badges = {}
last_subplace_updates = {}

# --- Helper Functions ---

def get_universe_info(universe_id):
    response = requests.get(f"https://games.roblox.com/v1/games?universeIds={universe_id}")
    if response.ok:
        return response.json()['data'][0]
    return None

def get_places(universe_id):
    response = requests.get(f"https://develop.roblox.com/v1/universes/{universe_id}/places")
    if response.ok:
        return response.json()['data']
    return []

def get_game_icon(universe_id):
    response = requests.get(
        f"https://thumbnails.roblox.com/v1/games/icons?universeIds={universe_id}&size=150x150&format=Png&isCircular=false"
    )
    if response.ok:
        return response.json()["data"][0]["imageUrl"]
    return None

def get_badge_info(badge_id):
    response = requests.get(f"https://badges.roblox.com/v1/badges/{badge_id}")
    if response.ok:
        return response.json()
    return None

def get_badge_award_count(badge_id):
    response = requests.get(f"https://badges.roblox.com/v1/badges/{badge_id}/awarded-counts")
    if response.ok:
        return response.json().get("awardedCount", 0)
    return 0

def create_game_update_embed(game, place, icon_url):
    embed = discord.Embed(
        title=game["name"],
        url=f"https://www.roblox.com/games/{game['id']}",
        description="A game has been updated!",
        color=0x00ff00
    )
    embed.set_thumbnail(url=icon_url)
    embed.add_field(name="Updated At", value=game["updated"], inline=False)
    embed.add_field(name="Subplace", value=f"[{place['name']}](https://www.roblox.com/games/{place['id']})", inline=False)
    embed.add_field(name="Subplace Updated", value=place["updated"], inline=True)
    embed.add_field(name="Main Game Public", value=str(game["isPlayable"]), inline=True)
    embed.add_field(name="Subplace Public", value=str(place["isPlayable"]), inline=True)
    return embed

def create_badge_update_embed(game_name, badge_info, old_count, new_count):
    embed = discord.Embed(
        title=f"Someone has just gotten a badge in **{game_name}**!!",
        color=0x00aaff
    )
    embed.add_field(name="Badge Name", value=badge_info["name"], inline=False)
    embed.add_field(name="Count", value=f"{old_count} ➝ {new_count}", inline=True)
    embed.set_thumbnail(url=badge_info["iconImage"]["imageUrl"])
    return embed

# --- Background Tasks ---

@tasks.loop(seconds=10)
async def check_subplace_updates():
    for universe_id in tracked_games.keys():
        game = get_universe_info(universe_id)
        if not game:
            continue

        icon_url = get_game_icon(universe_id)
        places = get_places(universe_id)

        for place in places:
            last_update = last_subplace_updates.get(place['id'])
            if not last_update or last_update != place['updated']:
                last_subplace_updates[place['id']] = place['updated']
                embed = create_game_update_embed(game, place, icon_url)
                await send_webhook(embed)

@tasks.loop(seconds=10)
async def check_badge_updates():
    for badge_id, data in tracked_badges.items():
        if data["count"] >= 200:
            continue

        current_count = get_badge_award_count(badge_id)
        if current_count > data["count"]:
            badge_info = get_badge_info(badge_id)
            embed = create_badge_update_embed(data["game_name"], badge_info, data["count"], current_count)
            await send_webhook(embed)
            tracked_badges[badge_id]["count"] = current_count

# --- Discord Events and Commands ---

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    check_subplace_updates.start()
    check_badge_updates.start()

@bot.command()
async def addgame(ctx, universe_id: int):
    if universe_id in tracked_games:
        await ctx.send("Game already being tracked.")
        return

    game_info = get_universe_info(universe_id)
    if game_info:
        tracked_games[universe_id] = game_info['name']
        places = get_places(universe_id)
        for place in places:
            last_subplace_updates[place['id']] = place['updated']
        await ctx.send(f"Tracking game: {game_info['name']}")
    else:
        await ctx.send("Game not found.")

@bot.command()
async def removegame(ctx, universe_id: int):
    if universe_id in tracked_games:
        del tracked_games[universe_id]
        await ctx.send("Game removed from tracking.")
    else:
        await ctx.send("Game not found in tracking list.")

@bot.command()
async def listgames(ctx):
    if not tracked_games:
        await ctx.send("No games are currently being tracked.")
        return
    msg = "\n".join(f"- {name} (ID: {uid})" for uid, name in tracked_games.items())
    await ctx.send(f"Tracked Games:\n{msg}")

@bot.command()
async def addbadge(ctx, badge_id: int, *, game_name: str):
    if badge_id in tracked_badges:
        await ctx.send("Badge already being tracked.")
        return
    count = get_badge_award_count(badge_id)
    tracked_badges[badge_id] = {"game_name": game_name, "count": count}
    await ctx.send(f"Tracking badge in {game_name} (Current count: {count})")

@bot.command()
async def removebadge(ctx, badge_id: int):
    if badge_id in tracked_badges:
        del tracked_badges[badge_id]
        await ctx.send("Badge removed from tracking.")
    else:
        await ctx.send("Badge not found.")

@bot.command()
async def listbadges(ctx):
    if not tracked_badges:
        await ctx.send("No badges are currently being tracked.")
        return
    msg = "\n".join(f"- {info['game_name']} (ID: {bid}, Count: {info['count']})" for bid, info in tracked_badges.items())
    await ctx.send(f"Tracked Badges:\n{msg}")

# --- Send Webhook Function ---

async def send_webhook(embed):
    data = {
        "content": "",
        "embeds": [embed.to_dict()]
    }
    requests.post(WEBHOOK_URL, json=data)

# --- Run Bot ---

bot.run(TOKEN)
