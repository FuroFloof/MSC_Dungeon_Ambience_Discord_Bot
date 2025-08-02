import discord
import random
import sqlite3
import time
from discord.ext import commands
from discord import FFmpegPCMAudio, PCMVolumeTransformer
from discord import app_commands
from datetime import datetime, timedelta

import asyncio
import random

# Debug Display Toggle
isDebugDisp = False

# Constants
TOKEN = "MTMxNzk4NjYzOTcwMzcwNzcxMw.GqwJX9.3h4m43R75kjzuaVkujQA8M1oGJfPtoRSeAvaio"  # Replace with your bot's token
AUDIO_VOLUME = 0.1  # Audio volume level
DB_PATH = "./assets/db/channel_check.db"

SONGS = [
    {"id": 1, "song_name": "Beach Cave", "file_path": "./assets/audio/beach_cave.mp3", "chance": 5.5},
    {"id": 2, "song_name": "Crystal Cave", "file_path": "./assets/audio/crystal_cave.mp3", "chance": 5.5},
    {"id": 3, "song_name": "Craggy Coast", "file_path": "./assets/audio/craggy_coast.mp3", "chance": 5.5},
    {"id": 4, "song_name": "Fortune Ravine", "file_path": "./assets/audio/fortune_ravine.mp3", "chance": 5.5},
    {"id": 5, "song_name": "Monster House", "file_path": "./assets/audio/monster_house.mp3", "chance": 5.5},
    {"id": 6, "song_name": "Amp Plains", "file_path": "./assets/audio/amp_plains.mp3", "chance": 5.5},
    {"id": 7, "song_name": "Sheer Mountain", "file_path": "./assets/audio/sheer_mountain_range.mp3", "chance": 5.5},
    {"id": 8, "song_name": "Northern Desert", "file_path": "./assets/audio/northern_desert.mp3", "chance": 5.5},
    {"id": 9, "song_name": "School Forest", "file_path": "./assets/audio/school_forest.mp3", "chance": 5.5},
    {"id": 10, "song_name": "Poliwrath River", "file_path": "./assets/audio/poliwrath_river.mp3", "chance": 5.5},
    {"id": 11, "song_name": "Hazy Pass", "file_path": "./assets/audio/hazy_pass.mp3", "chance": 5.5},
    {"id": 12, "song_name": "Ragged Mountain", "file_path": "./assets/audio/ragged_mountain.mp3", "chance": 5.5},
    {"id": 13, "song_name": "Magma Cavern", "file_path": "./assets/audio/magma_cavern.mp3", "chance": 5.5},
    {"id": 14, "song_name": "Thunderwave Cave", "file_path": "./assets/audio/thunderwave_cave.mp3", "chance": 5.5},
    {"id": 15, "song_name": "Waterfall Cave", "file_path": "./assets/audio/waterfall_cave.mp3", "chance": 5.5},
    {"id": 16, "song_name": "Resolution Gorge", "file_path": "./assets/audio/resolution_gorge.mp3", "chance": 5.5},
    {"id": 17, "song_name": "Temporal Spire", "file_path": "./assets/audio/temporal_spire.mp3", "chance": 5.5},
    {"id": 18, "song_name": "Stony Cave", "file_path": "./assets/audio/stony_cave.mp3", "chance": 5.5},
]

# Intents setup
intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.members = True

# Bot setup
bot = commands.Bot(command_prefix="!", intents=intents)

# Store currently active temporary channel
active_temp_channels = {}

# ----------------------
# DATABASE HELPER FUNCS
# ----------------------
def get_db_connection():
    """Returns a new SQLite connection."""
    conn = sqlite3.connect(DB_PATH)
    # Ensure the table is created (if not existing)
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS channels (
        "server-id"    TEXT,
        "channel-name" TEXT,
        "change-admin" INTEGER,
        "change-date"  INTEGER
    );
    """
    conn.execute(create_table_sql)
    conn.commit()
    return conn

def get_channel_name_for_guild(guild_id: int) -> str:
    """Retrieve the custom channel name for a given guild ID from the database, 
    or return 'Join Dungeon' if not found."""
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT `channel-name` FROM channels WHERE `server-id` = ?",
            (str(guild_id),)
        )
        row = cursor.fetchone()
        if row:
            return row[0]  # the stored channel name
        else:
            return "Join Dungeon"
    finally:
        conn.close()

def set_channel_name_for_guild(guild_id: int, channel_name: str, admin_id: int):
    """Upsert the channel name for a given guild ID along with admin_id and current time."""
    conn = get_db_connection()
    try:
        # current time as unix timestamp
        now_ts = int(time.time())
        # Check if there's an existing entry
        cursor = conn.execute(
            "SELECT 1 FROM channels WHERE `server-id` = ?",
            (str(guild_id),)
        )
        if cursor.fetchone():
            # update existing
            conn.execute(
                "UPDATE channels SET `channel-name` = ?, `change-admin` = ?, `change-date` = ? WHERE `server-id` = ?",
                (channel_name, admin_id, now_ts, str(guild_id))
            )
        else:
            # insert new
            conn.execute(
                "INSERT INTO channels(`server-id`, `channel-name`, `change-admin`, `change-date`) VALUES(?,?,?,?)",
                (str(guild_id), channel_name, admin_id, now_ts)
            )
        conn.commit()
    finally:
        conn.close()

# Helper: Weighted random song selection
def weighted_random_song():
    total = sum(song["chance"] for song in SONGS)
    pick = random.uniform(0, total)
    current = 0
    for song in SONGS:
        current += song["chance"]
        if current >= pick:
            return song

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot logged in as {bot.user}")

    # Example: on startup, you could send a message in a known channel
    # channel_id = 1136685002290118687
    # channel = bot.get_channel(channel_id)
    # if channel:
    #     await channel.send("Bot Came (funny word) online!")

    # If debug display is enabled, log every channel the bot has access to
    if isDebugDisp:
        for guild in bot.guilds:
            print(f"[DEBUG] Guild: {guild.name} (ID: {guild.id})")
            for ch in guild.channels:
                print(f"[DEBUG]   Channel: {ch.name} (ID: {ch.id}, Type: {ch.type})")

    print("Ready to rumble!")


@bot.event
async def on_voice_state_update(member, before, after):
    """Triggered when a member's voice state changes."""
    if member.bot:
        return
    
    # Log voice activity
    if before.channel is None and after.channel is not None:
        # User joined a channel
        print(f"[LOG] {member} joined voice channel: {after.channel.name}")
    elif before.channel is not None and after.channel is None:
        # User left a channel
        print(f"[LOG] {member} left voice channel: {before.channel.name}")
    elif before.channel is not None and after.channel is not None and before.channel != after.channel:
        # User moved channels
        print(f"[LOG] {member} moved from {before.channel.name} to {after.channel.name}")

    # Get channel name from DB or default
    # If user joined a channel named the DB's channel name, spawn a new dungeon channel
    if after.channel and before.channel != after.channel:
        # This is the channel name we're looking for
        channel_name = get_channel_name_for_guild(after.channel.guild.id)

        if after.channel.name == channel_name:
            guild = after.channel.guild
            category = after.channel.category

            # Check if there's already an active temporary channel
            temp_channel = active_temp_channels.get(guild.id)

            if temp_channel and temp_channel["channel"]:
                # Move the user to the existing temporary channel
                await member.move_to(temp_channel["channel"])
            else:
                # Select a random song
                song = weighted_random_song()
                
                # Create a new temporary voice channel
                new_channel = await guild.create_voice_channel(name=song["song_name"], category=category)
                active_temp_channels[guild.id] = {"channel": new_channel, "voice_client": None}

                # Move the user to the new channel
                await member.move_to(new_channel)

                # Connect to the channel and play the song
                voice_client = await new_channel.connect()
                active_temp_channels[guild.id]["voice_client"] = voice_client
                bot.loop.create_task(play_audio(voice_client, song["file_path"]))

    # Cleanup abandoned temporary channels
    if before.channel:
        guild = before.channel.guild

        if before.channel.name in [song["song_name"] for song in SONGS]:
            # If no one is in the channel (or only the bot is in there)
            if len(before.channel.members) == 0 or (len(before.channel.members) == 1 and before.channel.members[0].bot):
                temp_channel = active_temp_channels.get(guild.id)
                if temp_channel and temp_channel["channel"] == before.channel:
                    voice_client = temp_channel["voice_client"]
                    if voice_client:
                        await voice_client.disconnect()
                    await before.channel.delete()
                    del active_temp_channels[guild.id]
                    print(f"[DEBUG] Deleted abandoned channel: {before.channel.name}")

async def play_audio(voice_client, file_path):
    """Plays the specified audio file in a loop."""
    while True:
        if not voice_client.is_playing():
            source = FFmpegPCMAudio(file_path)
            player = PCMVolumeTransformer(source, volume=AUDIO_VOLUME)
            voice_client.play(player)
        await asyncio.sleep(1)


@bot.tree.command(name="change_dungeon", description="Change the dungeon music in the active channel.")
@app_commands.choices(dungeon=[
    discord.app_commands.Choice(name=song["song_name"], value=song["song_name"])
    for song in SONGS
])
async def change_dungeon(interaction: discord.Interaction, dungeon: str):
    song = next((s for s in SONGS if s["song_name"] == dungeon), None)
    if not song:
        await interaction.response.send_message(f"Dungeon '{dungeon}' not found.")
        return

    guild = interaction.guild
    temp_channel = active_temp_channels.get(guild.id)

    if not temp_channel or not temp_channel["channel"]:
        await interaction.response.send_message("No active dungeon to change music.")
        return

    old_channel = temp_channel["channel"]
    voice_client = temp_channel["voice_client"]

    # Disconnect from the old channel first
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()

    # Create a new temporary voice channel
    category = old_channel.category
    new_channel = await guild.create_voice_channel(name=song["song_name"], category=category)

    # Move all members to the new channel
    for member in old_channel.members:
        if member != guild.me:  # Skip the bot, as it will join later
            await member.move_to(new_channel)

    # Delete the old channel after ensuring members have been moved
    try:
        await old_channel.delete()
    except discord.NotFound:
        print(f"[DEBUG] Old channel {old_channel.name} was already deleted.")

    # Connect the bot to the new channel
    new_voice_client = await new_channel.connect()
    active_temp_channels[guild.id] = {"channel": new_channel, "voice_client": new_voice_client}

    # Play the new song in the new channel
    bot.loop.create_task(play_audio(new_voice_client, song["file_path"]))

    await interaction.response.send_message(f"Changed dungeon to {song['song_name']}.")

# Dictionary to store the last trigger time for each guild
monster_house_cooldowns = {}

@bot.tree.command(name="monster_house", description="Trigger a Monster House and Purge The Channel")
async def monster_house(interaction: discord.Interaction):
    global monster_house_cooldowns
    guild = interaction.guild

    # Check cooldown
    now = datetime.now()
    cooldown_end = monster_house_cooldowns.get(guild.id, None)

    if cooldown_end and now < cooldown_end:
        remaining_time = cooldown_end - now
        minutes, seconds = divmod(remaining_time.total_seconds(), 60)
        await interaction.response.send_message(
            f"Monster House can only be triggered every 30 minutes. Please wait {int(minutes)} minutes and {int(seconds)} seconds."
        )
        return

    # Update cooldown
    monster_house_cooldowns[guild.id] = now + timedelta(minutes=30)

    # Find the Monster House song
    monster_house_song = next((s for s in SONGS if s["song_name"].lower() == "monster house"), None)
    if not monster_house_song:
        await interaction.response.send_message("Monster House dungeon not found.")
        return

    temp_channel = active_temp_channels.get(guild.id)

    if not temp_channel or not temp_channel["channel"]:
        await interaction.response.send_message("No active dungeon to change music.")
        return

    # Acknowledge the command right away
    await interaction.response.send_message("It's a Monster House!!")

    old_channel = temp_channel["channel"]
    voice_client = temp_channel["voice_client"]

    # Disconnect from the old channel first if connected
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()

    # Create a new temporary voice channel for Monster House
    category = old_channel.category
    new_channel = await guild.create_voice_channel(name=monster_house_song["song_name"], category=category)

    # Move all members (except the bot) to the new channel
    for member in old_channel.members:
        if member != guild.me:
            await member.move_to(new_channel)

    # Delete the old channel after ensuring members have been moved
    try:
        await old_channel.delete()
    except discord.NotFound:
        print(f"[DEBUG] Old channel {old_channel.name} was already deleted.")

    # Connect the bot to the new channel
    new_voice_client = await new_channel.connect()
    active_temp_channels[guild.id] = {"channel": new_channel, "voice_client": new_voice_client}

    # Start playing the Monster House audio
    bot.loop.create_task(play_audio(new_voice_client, monster_house_song["file_path"]))

    # Wait for 7.5 seconds before kicking everyone
    await asyncio.sleep(7.5)

    # Disconnect everyone except the bot from the voice channel
    for member in new_channel.members:
        if not member.bot:
            await member.edit(voice_channel=None)

    # Mark the channel as abandoned: stop the audio, disconnect the bot, and delete the channel
    if new_voice_client and new_voice_client.is_connected():
        await new_voice_client.disconnect()

    try:
        await new_channel.delete()
    except discord.NotFound:
        print(f"[DEBUG] Channel {new_channel.name} was already deleted.")

    # Remove the channel from active_temp_channels
    if guild.id in active_temp_channels:
        del active_temp_channels[guild.id]

    # Notify the user that everyone has been kicked and the channel removed
    await interaction.followup.send("Everyone Fainted...")

# ------------------------------------
# NEW COMMAND: /dungeon_channel_name
# ------------------------------------
@bot.tree.command(name="dungeon_channel_name", description="Set or update the channel name that triggers dungeon creation.")
@app_commands.describe(channel_name="The name of the channel to watch for (max 32 chars).")
async def dungeon_channel_name(interaction: discord.Interaction, channel_name: str):
    # Validate length
    if len(channel_name) > 32:
        await interaction.response.send_message("Channel name must be 32 characters or less!")
        return
    
    # Store in DB
    set_channel_name_for_guild(
        guild_id=interaction.guild.id,
        channel_name=channel_name,
        admin_id=interaction.user.id
    )

    await interaction.response.send_message(
        f"Dungeon trigger channel name updated to '{channel_name}'."
    )

# Run the bot
bot.run(TOKEN)
