I'm doing this for a private friend group server I'm in. We solve puzzles and with this bot, our chances on being first to solve puzzles will increase drastically so lock in twin

A discord bot that tracks a game's data, updating and notifying whenever the game updates while specifying what subplace(s) got updated. Furthermore, it must also be able to track badges and notify us whenever the badge count increases (ex: 1 to 3 or 3 to 5) while showing the time. The bot will fetch these datas by using the Roblox public APIs and NOT OPEN CLOUD. The bot will use discord webhooks for it's updates. 

(some info that aren't related to the script: The bot's name is Peekaboo with a pfp of a roblox avatar, the description has already been set by me.)

For the game updater, the webhook should look like this:
- The title of the updated game (hyperlinked with the game's link)
- The game icon on the right
- When it got updated (in relative time using the discord timestamps feature)
- The main game's ID (universe ID and not place ID)
- What subplace got updated (hyperlinked with the subplace's link)
- When did that subplace get updated (in relative time using the discord timestamps feature)
- Whether the main game is playable or not (public or not)
- Whether the subplace is playable or not (public or not)

For the badge count updater, the webhook should look like this:
- The game name of where the badge originates from
- The game icon on the right
- The badge name
- The count from before and after (ex: 0 -> 1, etc)

I must also clarify this is will be coded in python (as you already know). Make also 2 json files with named "tracked_badges" and "tracked_games" upon running for the first time and after that it will be updated along the way. Make sure messages intent is on in the script. Find a way to bypass the roblox api ratelimiting system while using the quickest but balanced interval. I find 60 seconds (a minute) a balanced interval but you can change it into a possibly more balanced interval if you find one. 

The possible commands will be:
!addgame <universeid> 
!removegame <universeid>
!listgames
!addbadge <badgeid>
!removebadge <badgeid>
!listbadges





