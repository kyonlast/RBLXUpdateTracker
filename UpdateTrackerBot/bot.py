import discord
from discord.ext import commands
import aiohttp
import asyncio
import json
import os
from datetime import datetime

# ------------------------------ CONFIG ------------------------------
TOKEN = "MTM2MjgxMzEzODc1OTg0NDA1Mg.GgvJys.-6sHQPxQ4oQ7dbKwtJ8RCiHTh4RdRRmu2R35Z4"
WEBHOOK_URL = "https://discord.com/api/webhooks/1363523928835752258/6wsRt0OZnjwOYeU82jXR8wG4cleFRX0xCfxayDzvAhZKRztenrlQ7ARE5zI53dODyRnl"
CHECK_INTERVAL = 60  # seconds

BADGE_API = "https://badges.roblox.com/v1/badges/{}"
GAME_API = "https://games.roblox.com/v1/games/{}"
PLACE_API = "https://games.roblox.com/v1/places/{}"
ICON_API = "https://thumbnails.roblox.com/v1/games/icons?universeIds={}&size=512x512&format=Png&isCircular=false"

TRACKED_BADGES_FILE = "tracked_badges.json"
TRACKED_GAMES_FILE = "tracked_games.json"

# ------------------------------ BOT CLASS ------------------------------
class PeekabooBot(commands.Bot):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.session = None
        self.tracked_badges = {}
        self.tracked_games = {}

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        self.load_data()
        self.loop.create_task(self.track_badges())
        self.loop.create_task(self.track_games())

    def load_data(self):
        if not os.path.exists(TRACKED_BADGES_FILE):
            with open(TRACKED_BADGES_FILE, 'w') as f:
                json.dump({}, f)

        if not os.path.exists(TRACKED_GAMES_FILE):
            with open(TRACKED_GAMES_FILE, 'w') as f:
                json.dump({}, f)

        with open(TRACKED_BADGES_FILE, 'r') as f:
            self.tracked_badges = json.load(f)

        with open(TRACKED_GAMES_FILE, 'r') as f:
            self.tracked_games = json.load(f)

    def save_data(self):
        with open(TRACKED_BADGES_FILE, 'w') as f:
            json.dump(self.tracked_badges, f)
        with open(TRACKED_GAMES_FILE, 'w') as f:
            json.dump(self.tracked_games, f)

    async def close(self):
        if self.session:
            await self.session.close()
        await super().close()

    async def track_badges(self):
        while True:
            for badge_id, last_count in list(self.tracked_badges.items()):
                async with self.session.get(BADGE_API.format(badge_id)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    count = data.get("statistics", {}).get("awardedCount", 0)
                    if count > last_count:
                        game_name = data.get("awardingUniverse", {}).get("name", "Unknown")
                        icon_id = data.get("iconImageId")
                        thumb_url = f"https://www.roblox.com/thumbs/image?userId=1&width=420&height=420&format=png&assetId={icon_id}" if icon_id else None

                        embed = discord.Embed(
                            title=f"Badge Update in {game_name}",
                            description=f"**{data.get('name')}**\n**{last_count}** → **{count}**",
                            color=discord.Color.green()
                        )
                        if thumb_url:
                            embed.set_thumbnail(url=thumb_url)

                        async with self.session.post(WEBHOOK_URL, json={"embeds": [embed.to_dict()]}) as w:
                            pass
                        self.tracked_badges[badge_id] = count
                        self.save_data()
            await asyncio.sleep(CHECK_INTERVAL)

    async def track_games(self):
        while True:
            for universe_id, last_updated in list(self.tracked_games.items()):
                async with self.session.get(GAME_API.format(universe_id)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    updated_time = data.get("updated")
                    if not updated_time:
                        continue
                    if updated_time != last_updated:
                        icon_res = await self.session.get(ICON_API.format(universe_id))
                        icon_data = await icon_res.json()
                        icon_url = icon_data['data'][0]['imageUrl'] if icon_data['data'] else None

                        embed = discord.Embed(
                            title=f"[{data.get('name')}] Game Updated!",
                            url=f"https://www.roblox.com/games/{universe_id}",
                            description=f"Updated <t:{int(datetime.fromisoformat(updated_time[:-1]).timestamp())}:R>\nUniverse ID: `{universe_id}`",
                            color=discord.Color.blue()
                        )
                        if icon_url:
                            embed.set_thumbnail(url=icon_url)
                        embed.add_field(name="Playable", value="✅" if data.get("isPlayable") else "❌")

                        async with self.session.post(WEBHOOK_URL, json={"embeds": [embed.to_dict()]}) as w:
                            pass

                        self.tracked_games[universe_id] = updated_time
                        self.save_data()
            await asyncio.sleep(CHECK_INTERVAL)

# ------------------------------ COMMANDS ------------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = PeekabooBot(command_prefix="!", intents=intents)

@bot.command()
async def addgame(ctx, universe_id):
    if universe_id in bot.tracked_games:
        await ctx.send("Game is already being tracked.")
        return
    bot.tracked_games[universe_id] = ""
    bot.save_data()
    await ctx.send(f"Added game `{universe_id}` to tracking list.")

@bot.command()
async def removegame(ctx, universe_id):
    if universe_id in bot.tracked_games:
        del bot.tracked_games[universe_id]
        bot.save_data()
        await ctx.send(f"Removed game `{universe_id}`.")
    else:
        await ctx.send("Game not found in tracked list.")

@bot.command()
async def listgames(ctx):
    if not bot.tracked_games:
        await ctx.send("No games are being tracked.")
    else:
        await ctx.send("Tracked games:\n" + "\n".join(bot.tracked_games.keys()))

@bot.command()
async def addbadge(ctx, badge_id):
    if badge_id in bot.tracked_badges:
        await ctx.send("Badge already being tracked.")
        return
    bot.tracked_badges[badge_id] = 0
    bot.save_data()
    await ctx.send(f"Added badge `{badge_id}` to tracking list.")

@bot.command()
async def removebadge(ctx, badge_id):
    if badge_id in bot.tracked_badges:
        del bot.tracked_badges[badge_id]
        bot.save_data()
        await ctx.send(f"Removed badge `{badge_id}`.")
    else:
        await ctx.send("Badge not found in tracked list.")

@bot.command()
async def listbadges(ctx):
    if not bot.tracked_badges:
        await ctx.send("No badges are being tracked.")
    else:
        await ctx.send("Tracked badges:\n" + "\n".join(bot.tracked_badges.keys()))

# ------------------------------ RUN ------------------------------
bot.run(TOKEN)
