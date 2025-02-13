import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button
import sqlite3
from typing import Optional
import math
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup
import asyncio
import os
from dotenv import load_dotenv


# Bot Configuration
ADMIN_ID = 488015447417946151
ALLOWED_SERVERS = [1332678406902513684]
ALLOWED_CHANNELS = [1332928917471887380]

# Database setup
conn = sqlite3.connect("streamer_data.db")
cursor = conn.cursor()


# Setup the database and tables
def setup_db():
    conn = sqlite3.connect('streamer_data.db')
    c = conn.cursor()

    # Ensure the giveaway_data table is created
    c.execute('''CREATE TABLE IF NOT EXISTS giveaway_data (
                    viewer_name INTEGER,
                    discord_id INTEGER,
                    total_won INTEGER,
                    total_received REAL)''')

    # Ensure the giveaway_leaderboard table is created
    c.execute('''CREATE TABLE IF NOT EXISTS giveaway_leaderboard (
                    viewer_name INTEGER,
                    total_won INTEGER,
                    total_received REAL)''')

    # Ensure the streamer_profiles table is created
    c.execute('''CREATE TABLE IF NOT EXISTS streamer_profiles (
                    streamer_id INTEGER PRIMARY KEY,
                    discord_id INTEGER,
                    kick_link TEXT,
                    twitter_link TEXT)''')

    # Ensure the streamer_profiles table is created
    c.execute('''CREATE TABLE IF NOT EXISTS prize_pool (
            id INTEGER PRIMARY KEY, 
            amount REAL DEFAULT 0.0
        )''')

    # Ensure the stats table is created
    c.execute('''CREATE TABLE IF NOT EXISTS stats (
                    stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    streamer_id INTEGER,
                    slot_name TEXT,
                    buy_amount REAL,
                    buy_result REAL,
                    match_result TEXT,
                    match_history TEXT,
                    FOREIGN KEY (streamer_id) REFERENCES streamer_profiles(streamer_id))''')

    # Add Instagram and YouTube links if they don't exist
    cursor.execute("PRAGMA table_info(streamer_profiles);")
    columns = [column[1] for column in cursor.fetchall()]  # Get a list of column names

    if 'instagram_link' not in columns:
        cursor.execute('ALTER TABLE streamer_profiles ADD COLUMN instagram_link TEXT;')
    if 'youtube_link' not in columns:
        cursor.execute('ALTER TABLE streamer_profiles ADD COLUMN youtube_link TEXT;')
    if 'profile_image' not in columns:
        cursor.execute('ALTER TABLE streamer_profiles ADD COLUMN profile_image TEXT;')

    # Create indexes for faster access
    c.execute('CREATE INDEX IF NOT EXISTS idx_discord_id ON streamer_profiles(discord_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_streamer_id ON stats(streamer_id)')
    c.execute("INSERT OR IGNORE INTO prize_pool (id, amount) VALUES (1, 0.0)")

    conn.commit()
    conn.close()


setup_db()

# Initialize bot
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Check if user is admin
async def is_admin(interaction: discord.Interaction):
    return interaction.user.id == ADMIN_ID

# Commands

@tree.command(name="add_streamer_profile", description="Add a Streamer Profile (Admin only)")
@app_commands.describe(
    streamer="Tag the Streamer",
    kick_link="Provide the Kick link",
    twitter_link="Provide the Twitter link",
    profile_image="Upload the profile image (Optional)"
)
async def add_streamer_profile(
    interaction: discord.Interaction,
    streamer: discord.Member,
    kick_link: str,
    twitter_link: str,
    profile_image: Optional[discord.Attachment] = None,  # Optional image
    instagram_link: str = None,
    youtube_link: str = None
):
    if not await is_admin(interaction):
        await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        return

    profile_image_url = None
    if profile_image:
        # Upload the image and get the URL
        profile_image_url = profile_image.url

        # Insert or update streamer profile
        cursor.execute("""INSERT OR REPLACE INTO streamer_profiles (discord_id, kick_link, twitter_link, instagram_link, youtube_link, profile_image)
                          VALUES (?, ?, ?, ?, ?, ?)""",
                       (streamer.id, kick_link, twitter_link, instagram_link, youtube_link, profile_image_url))
        conn.commit()
        await interaction.response.send_message(f"Streamer profile for {streamer.mention} has been added/updated.")

@tree.command(name="add_stats", description="Add Stats for a Streamer (Admin only)")
@app_commands.describe(
    streamer="Tag the Streamer",
    slot_name="Provide the Slot Name",
    buy_amount="Enter the Buy Amount",
    buy_result="Enter the Buy Result",
    match_result="Select WIN or LOSE",
    match_history="Enter Match History details"
)
@app_commands.choices(match_result=[
    app_commands.Choice(name="WIN", value="WIN"),
    app_commands.Choice(name="LOSE", value="LOSE")
])
async def add_stats(interaction: discord.Interaction, streamer: discord.Member, slot_name: str, buy_amount: float, buy_result: float, match_result: app_commands.Choice[str], match_history: str):
    if not await is_admin(interaction):
        await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        return

    # Get Streamer ID
    cursor.execute("SELECT streamer_id FROM streamer_profiles WHERE discord_id = ?", (streamer.id,))
    result = cursor.fetchone()
    if not result:
        await interaction.response.send_message(f"Streamer profile for {streamer.mention} does not exist. Add the profile first.", ephemeral=True)
        return

    streamer_id = result[0]
    cursor.execute("INSERT INTO stats (streamer_id, slot_name, buy_amount, buy_result, match_result, match_history) VALUES (?, ?, ?, ?, ?, ?)",
                   (streamer_id, slot_name, buy_amount, buy_result, match_result.value, match_history))
    conn.commit()
    await interaction.response.send_message(f"Stats for {streamer.mention} have been added.")


# Slot Stats Pagination View
class SlotStatsView(View):
    def __init__(self, embed_callback, total_pages, current_page=1):
        super().__init__()
        self.embed_callback = embed_callback  # Callback to fetch and update the embed
        self.total_pages = total_pages
        self.current_page = current_page

        # Pagination buttons
        self.prev_button = Button(label="Prev Slots", style=discord.ButtonStyle.primary, row=0, disabled=(current_page <= 1))
        self.next_button = Button(label="Next Slots", style=discord.ButtonStyle.primary, row=0, disabled=(current_page >= total_pages))

        self.prev_button.callback = self.prev_page
        self.next_button.callback = self.next_page

        self.add_item(self.prev_button)
        self.add_item(self.next_button)

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page -= 1
        embed = self.embed_callback(self.current_page)  # Update embed for the new page
        self.prev_button.disabled = self.current_page <= 1
        self.next_button.disabled = self.current_page >= self.total_pages
        await interaction.response.edit_message(embed=embed, view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page += 1
        embed = self.embed_callback(self.current_page)  # Update embed for the new page
        self.prev_button.disabled = self.current_page <= 1
        self.next_button.disabled = self.current_page >= self.total_pages
        await interaction.response.edit_message(embed=embed, view=self)


# Match History Pagination View
class MatchHistoryView(View):
    def __init__(self, embed_callback, total_pages, current_page=1):
        super().__init__()
        self.embed_callback = embed_callback  # Callback to fetch and update the embed
        self.total_pages = total_pages
        self.current_page = current_page

        # Pagination buttons
        self.prev_button = Button(label="Current Matches", style=discord.ButtonStyle.secondary, row=0, disabled=(current_page <= 1))
        self.next_button = Button(label="Older Matches", style=discord.ButtonStyle.secondary, row=0, disabled=(current_page >= total_pages))

        self.prev_button.callback = self.prev_page
        self.next_button.callback = self.next_page

        self.add_item(self.prev_button)
        self.add_item(self.next_button)

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page -= 1
        embed = self.embed_callback(self.current_page)  # Update embed for the new page
        self.prev_button.disabled = self.current_page <= 1
        self.next_button.disabled = self.current_page >= self.total_pages
        await interaction.response.edit_message(embed=embed, view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page += 1
        embed = self.embed_callback(self.current_page)  # Update embed for the new page
        self.prev_button.disabled = self.current_page <= 1
        self.next_button.disabled = self.current_page >= self.total_pages
        await interaction.response.edit_message(embed=embed, view=self)


# Main /streamer_profile Command
@tree.command(name="streamer_profile", description="View a Streamer's Profile")
@app_commands.describe(streamer="Tag the Streamer")
async def streamer_profile(interaction: discord.Interaction, streamer: discord.Member):
    # Database Query: Fetch Streamer Information
    cursor.execute(
        "SELECT streamer_id, kick_link, twitter_link, instagram_link, youtube_link, profile_image FROM streamer_profiles WHERE discord_id = ?",
        (streamer.id,)
    )
    result = cursor.fetchone()
    if not result:
        await interaction.response.send_message(f"Streamer profile for {streamer.mention} does not exist.",
                                                ephemeral=True)
        return

    streamer_id, kick_link, twitter_link, instagram_link, youtube_link, profile_image_url = result

    # Database Query: Fetch Tournament Stats
    cursor.execute("SELECT COUNT(*) FROM stats WHERE streamer_id = ? AND match_result = 'WIN'", (streamer_id,))
    total_wins = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM stats WHERE streamer_id = ? AND match_result = 'LOSE'", (streamer_id,))
    total_losses = cursor.fetchone()[0]
    win_percentage = (100 * total_wins / (total_wins + total_losses)) if (total_wins + total_losses) > 0 else 0

    # Compute Total Profit
    cursor.execute("""
        SELECT 
            SUM(buy_result) AS total_buy_result, 
            SUM(buy_amount) AS total_buy_amount 
        FROM stats 
        WHERE streamer_id = ?
    """, (streamer_id,))
    buy_result, buy_amount = cursor.fetchone()
    total_profit = (buy_result or 0) - (buy_amount or 0)  # Ensure we handle None values gracefully

    # Base Embed with Streamer Profile Info
    embed = discord.Embed(title=f"Streamer Profile: {streamer.display_name}", color=discord.Color.blue())

    # Add the profile image if it exists
    if profile_image_url:
        embed.set_thumbnail(url=profile_image_url)
    else:
        embed.set_thumbnail(url="default_profile_image_url")

    embed.add_field(
        name="LINKS",
        value=f"**Kick:** ({kick_link})\n**Twitter:** ({twitter_link})\n**Instagram:** ({instagram_link})\n**YouTube:** ({youtube_link})",
        inline=False,
    )
    embed.add_field(
        name="TOURNAMENT STATS",
        value=(
            f"Wins: {total_wins}\n"
            f"Losses: {total_losses}\n"
            f"Win %: {win_percentage:.2f}%\n"
            f"Total Profit: ${total_profit:.2f}"  # Add Total Profit to the embed
        ),
        inline=False,
    )

    # Send the Profile Embed
    await interaction.response.send_message(embed=embed)

    # Pagination Data for Slot Stats
    def generate_slot_embed(page):
        items_per_page = 5
        offset = (page - 1) * items_per_page
        cursor.execute(""" 
            SELECT slot_name, COUNT(*), SUM(CASE WHEN match_result = 'WIN' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN match_result = 'LOSE' THEN 1 ELSE 0 END), SUM(buy_result), SUM(buy_amount)
            FROM stats
            WHERE streamer_id = ?
            GROUP BY slot_name
            ORDER BY SUM(CASE WHEN match_result = 'WIN' THEN 1 ELSE 0 END) DESC,
                     SUM(buy_result - buy_amount) DESC,
                     (100.0 * SUM(CASE WHEN match_result = 'WIN' THEN 1 ELSE 0 END) / COUNT(*)) DESC
            LIMIT ? OFFSET ?
        """, (streamer_id, items_per_page, offset))
        slot_stats = cursor.fetchall()

        slot_embed = embed.copy()  # Create a copy to avoid overwriting the original embed
        slot_embed.clear_fields()  # Clear for new content
        slot_embed.title = f"{streamer.display_name}'s Opponents (Page {page}/{total_slot_pages})"
        if slot_stats:
            for slot_name, total_games, wins, losses, total_buy_result, total_buy_amount in slot_stats:
                win_percentage_slot = (100 * wins / total_games) if total_games > 0 else 0
                total_profit_slot = total_buy_result - total_buy_amount
                slot_embed.add_field(
                    name=f"**{slot_name}**",
                    value=(
                        f"Games: {total_games}\n"
                        f"Wins: {wins}\n"
                        f"Losses: {losses}\n"
                        f"Win %: {win_percentage_slot:.2f}%\n"
                        f"Profit: ${total_profit_slot:.2f}"
                    ),
                    inline=False,
                )
        return slot_embed

    cursor.execute("SELECT COUNT(DISTINCT slot_name) FROM stats WHERE streamer_id = ?", (streamer_id,))
    total_slot_pages = (cursor.fetchone()[0] + 4) // 5  # 5 items per page

    # Pagination Data for Match History
    def generate_match_embed(page):
        items_per_page = 5
        offset = (page - 1) * items_per_page
        cursor.execute(""" 
            SELECT slot_name, match_result, match_history
            FROM stats
            WHERE streamer_id = ?
            ORDER BY rowid DESC
            LIMIT ? OFFSET ?
        """, (streamer_id, items_per_page, offset))
        match_history = cursor.fetchall()

        match_embed = embed.copy()  # Create a copy to avoid overwriting the original embed
        match_embed.clear_fields()
        match_embed.title = f"{streamer.display_name}'s Match History (Page {page}/{total_match_pages})"
        if match_history:
            for slot_name, match_result, history in match_history:
                match_embed.add_field(name=f"**{slot_name}** - {match_result}", value=history, inline=False)
        return match_embed

    cursor.execute("SELECT COUNT(*) FROM stats WHERE streamer_id = ?", (streamer_id,))
    total_match_pages = (cursor.fetchone()[0] + 4) // 5  # 5 items per page

    # Send Slot Stats and Match History with Pagination Views
    await interaction.channel.send(embed=generate_slot_embed(1), view=SlotStatsView(generate_slot_embed, total_slot_pages))
    await interaction.channel.send(embed=generate_match_embed(1), view=MatchHistoryView(generate_match_embed, total_match_pages))


# Define the leaderboard command
@tree.command(name="leaderboard", description="View the Leaderboard")
async def leaderboard(interaction: discord.Interaction, page: Optional[int] = 1):
    items_per_page = 4  # Changed from 5 to 4
    offset = (page - 1) * items_per_page  # Calculate offset for pagination

    await interaction.response.defer()  # Allow time for processing

    # Fetch leaderboard data
    cursor.execute('''
        SELECT sp.discord_id, sp.profile_image, 
               COUNT(CASE WHEN s.match_result = 'WIN' THEN 1 END) as wins,
               COUNT(CASE WHEN s.match_result = 'LOSE' THEN 1 END) as losses,
               SUM(s.buy_result - s.buy_amount) as profit
        FROM streamer_profiles sp
        LEFT JOIN stats s ON sp.streamer_id = s.streamer_id
        GROUP BY sp.discord_id
        ORDER BY wins DESC, profit DESC
        LIMIT ? OFFSET ?
    ''', (items_per_page, offset))

    leaderboard_data = cursor.fetchall()
    if not leaderboard_data:
        await interaction.followup.send("No leaderboard data available.", ephemeral=True)
        return

    # Generate embeds for each streamer
    embeds = []
    for rank, (discord_id, profile_image_url, wins, losses, profit) in enumerate(leaderboard_data, start=1 + offset):
        win_percentage = (100 * wins / (wins + losses)) if (wins + losses) > 0 else 0
        profit = profit if profit is not None else 0  # Ensure profit isn't None
        streamer = await bot.fetch_user(discord_id)  # Fetch the user's Discord profile

        embed = discord.Embed(
            title=f"Rank {rank}: {streamer.display_name}",
            color=discord.Color.gold(),
            description=(
                f"{streamer.mention}\n"
                f"Wins: {wins}\n"
                f"Losses: {losses}\n"
                f"Win %: {win_percentage:.2f}%\n"
                f"Profit: ${profit:.2f}"
            ),
        )

        # Set the profile picture for each embed
        if profile_image_url:
            embed.set_thumbnail(url=profile_image_url)
        else:
            embed.set_thumbnail(url="default_profile_image_url")

        embeds.append(embed)

    # Calculate total pages for pagination
    total_streamers = cursor.execute(
        'SELECT COUNT(DISTINCT sp.discord_id) FROM streamer_profiles sp LEFT JOIN stats s ON sp.streamer_id = s.streamer_id'
    ).fetchone()[0]
    total_pages = math.ceil(total_streamers / items_per_page)

    # Add pagination buttons
    view = LeaderboardPaginationView(page, total_pages, embed_callback=generate_leaderboard_embeds)
    await interaction.followup.send(embeds=embeds, view=view)


# Pagination View for Leaderboard
class LeaderboardPaginationView(View):
    def __init__(self, current_page, total_pages, embed_callback):
        super().__init__()
        self.current_page = current_page
        self.total_pages = total_pages
        self.embed_callback = embed_callback

        # Create buttons for navigation
        self.prev_button = Button(label="Previous", style=discord.ButtonStyle.primary, disabled=(current_page == 1))
        self.next_button = Button(label="Next", style=discord.ButtonStyle.primary, disabled=(current_page == total_pages))

        # Link button callbacks
        self.prev_button.callback = self.prev_page
        self.next_button.callback = self.next_page

        self.add_item(self.prev_button)
        self.add_item(self.next_button)

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page -= 1
        embeds = await self.embed_callback(self.current_page)
        self.prev_button.disabled = self.current_page == 1
        self.next_button.disabled = self.current_page == self.total_pages
        await interaction.response.edit_message(embeds=embeds, view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page += 1
        embeds = await self.embed_callback(self.current_page)
        self.prev_button.disabled = self.current_page == 1
        self.next_button.disabled = self.current_page == self.total_pages
        await interaction.response.edit_message(embeds=embeds, view=self)

# Generate leaderboard embeds for pagination
async def generate_leaderboard_embeds(page):
    items_per_page = 4  # Changed from 5 to 4
    offset = (page - 1) * items_per_page

    cursor.execute('''
        SELECT sp.discord_id, sp.profile_image, 
               COUNT(CASE WHEN s.match_result = 'WIN' THEN 1 END) as wins,
               COUNT(CASE WHEN s.match_result = 'LOSE' THEN 1 END) as losses,
               SUM(s.buy_result - s.buy_amount) as profit
        FROM streamer_profiles sp
        LEFT JOIN stats s ON sp.streamer_id = s.streamer_id
        GROUP BY sp.discord_id
        ORDER BY wins DESC, profit DESC
        LIMIT ? OFFSET ? 
    ''', (items_per_page, offset))

    leaderboard_data = cursor.fetchall()
    embeds = []

    for rank, (discord_id, profile_image_url, wins, losses, profit) in enumerate(leaderboard_data, start=1 + offset):
        win_percentage = (100 * wins / (wins + losses)) if (wins + losses) > 0 else 0
        profit = profit if profit is not None else 0  # Ensure profit isn't None
        streamer = await bot.fetch_user(discord_id)  # Fetch the user's Discord profile

        embed = discord.Embed(
            title=f"Rank {rank}: {streamer.display_name}",
            color=discord.Color.gold(),
            description=(
                f"{streamer.mention}\n"
                f"Wins: {wins}\n"
                f"Losses: {losses}\n"
                f"Win %: {win_percentage:.2f}%\n"
                f"Profit: ${profit:.2f}"
            ),
        )

        # Check if the profile image URL exists in the database, else use Discord's profile picture
        if profile_image_url:
            embed.set_thumbnail(url=profile_image_url)
        else:
            # If no profile image in the database, use the user's Discord profile picture
            embed.set_thumbnail(url=streamer.avatar.url)

        embeds.append(embed)

    return embeds

@tree.command(name="reset_leaderboard", description="Reset the Leaderboard (Admin only)")
async def reset_leaderboard(interaction: discord.Interaction):
    if not await is_admin(interaction):
        await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        return

    cursor.execute("DELETE FROM stats")
    conn.commit()
    await interaction.response.send_message("Leaderboard has been reset.")

# Check if user is admin
async def is_admin(interaction: discord.Interaction):
    return interaction.user.id == ADMIN_ID

# Reset Streamer Profile command
@tree.command(name="reset_streamer_profile", description="Reset a Streamer's Profile (Admin only)")
@app_commands.describe(
    streamer="Tag the Streamer",
    confirm_reset="Are you sure to reset?"
)
@app_commands.choices(
    confirm_reset=[
        app_commands.Choice(name="YES", value="YES"),
        app_commands.Choice(name="NO", value="NO")
    ]
)
async def reset_streamer_profile(interaction: discord.Interaction, streamer: discord.Member, confirm_reset: app_commands.Choice[str]):
    if not await is_admin(interaction):
        await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        return

    if confirm_reset.value == "YES":
        # Reset Streamer Profile in the Database
        cursor.execute("DELETE FROM streamer_profiles WHERE discord_id = ?", (streamer.id,))
        cursor.execute("DELETE FROM stats WHERE streamer_id = (SELECT streamer_id FROM streamer_profiles WHERE discord_id = ?)", (streamer.id,))
        conn.commit()

        # Send confirmation that the profile has been reset
        await interaction.response.send_message(f"Streamer profile for {streamer.mention} has been reset.", ephemeral=True)

    elif confirm_reset.value == "NO":
        await interaction.response.send_message("Reset operation cancelled.", ephemeral=True)

# /Giveaway Winner (Admin only)
@bot.tree.command(name="giveaway_winner")
async def giveaway_winner(interaction: discord.Interaction, viewer: discord.Member, prize: float, quantity: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You do not have the necessary permissions to use this command.", ephemeral=True)
        return

    conn = sqlite3.connect('streamer_data.db')
    c = conn.cursor()

    # Check if the viewer already exists in the database
    c.execute('SELECT * FROM giveaway_data WHERE viewer_name = ?', (viewer.name,))
    result = c.fetchone()

    if result:
        c.execute('UPDATE giveaway_data SET total_won = total_won + ?, total_received = total_received + ? WHERE viewer_name = ?',
                  (quantity, prize, viewer.name))
    else:
        c.execute('INSERT INTO giveaway_data (viewer_name, total_won, total_received) VALUES (?, ?, ?)',
                  (viewer.name, quantity, prize))

    conn.commit()
    conn.close()

    await interaction.response.send_message(f"{viewer.mention} has won {quantity} prize(s) worth ${prize}.")

# /Viewer Profile (Anyone can use)
@bot.tree.command(name="viewer_profile")
async def viewer_profile(interaction: discord.Interaction, viewer: discord.Member):
    conn = sqlite3.connect('streamer_data.db')
    c = conn.cursor()

    c.execute('SELECT * FROM giveaway_data WHERE viewer_name = ?', (viewer.name,))
    result = c.fetchone()

    if result:
        total_won = result[1]
        total_received = result[2]
        embed = discord.Embed(title=f"{viewer.name}'s Profile", color=discord.Color.blue())
        embed.add_field(name="Giveaway Stats", value=f"Times Won: {total_won}\nTotal $$$ Received: ${total_received}")
        embed.set_thumbnail(url=viewer.avatar.url)
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(f"{viewer.mention} has no giveaway data.", ephemeral=True)

    conn.close()


# /Prizes Leaderboard (Anyone can use)
@bot.tree.command(name="prizes_leaderboard")
async def prizes_leaderboard(interaction: discord.Interaction, page: Optional[int] = 1):
    items_per_page = 5  # Set the number of items per page
    offset = (page - 1) * items_per_page  # Calculate the offset for pagination

    # Database connection and query
    conn = sqlite3.connect('streamer_data.db')
    c = conn.cursor()

    # Fetch leaderboard data (use discord_id instead of viewer_name)
    c.execute(''' 
        SELECT viewer_name, discord_id, total_won, total_received
        FROM giveaway_data
        ORDER BY total_received DESC, total_won DESC
        LIMIT ? OFFSET ?
    ''', (items_per_page, offset))

    leaderboard_data = c.fetchall()
    if not leaderboard_data:
        await interaction.response.send_message("No leaderboard data available.", ephemeral=True)
        return

    # Fetch total giveaways and total prizes
    c.execute('SELECT SUM(total_won), SUM(total_received) FROM giveaway_data')
    total_giveaways, total_prizes = c.fetchone()

    # Server Status Embed
    embed = discord.Embed(title="BATTLE UNDERGROUND GIVEAWAYS", color=discord.Color.green())
    embed.add_field(name="Total Giveaways Hosted", value=f"**{total_giveaways}**\n\n*Note: All the Prizes given are in NZ USD*")
    embed.add_field(name="Total Prizes Given", value=f"**${total_prizes}**")

    # List of embeds for leaderboard
    embeds = [embed]

    # Generate embeds for each viewer
    # Generate embeds for each viewer
    # Generate embeds for each viewer
    for rank, (viewer_name, discord_id, total_won, total_received) in enumerate(leaderboard_data, start=1 + offset):
        try:
            user = await bot.fetch_user(discord_id)  # Fetch the latest user data
        except:
            user = None

        # Default avatar URL in case user is not found
        avatar_url = "https://cdn.discordapp.com/embed/avatars/0.png"

        # Determine mention or username
        if user:
            avatar_url = user.avatar.url if user.avatar else avatar_url
            display_name = user.mention  # This will correctly use the @mention format
        else:
            display_name = f"<@{discord_id}>"  # Use a fallback mention format if the user is not found

        leaderboard_embed = discord.Embed(
            title=f"Rank {rank}: {viewer_name}",
            color=discord.Color.purple(),
            description=(
                f"Viewer: **{display_name}**\n"
                f"Times Won: **{total_won}**\n"
                f"Total $$$ Received: **${total_received}**"
            ),
        ).set_thumbnail(url=avatar_url)

        embeds.append(leaderboard_embed)

    # Calculate total pages for pagination
    c.execute('SELECT COUNT(*) FROM giveaway_data')
    total_viewers = c.fetchone()[0]
    total_pages = math.ceil(total_viewers / items_per_page)

    # Add pagination buttons
    view = PrizeLeaderboardPaginationView(page, total_pages, embed_callback=generate_prize_leaderboard_embeds)

    # Send a single message with all embeds
    await interaction.response.send_message(embeds=embeds, view=view)

    conn.close()


# Pagination View for Prizes Leaderboard
class PrizeLeaderboardPaginationView(discord.ui.View):
    def __init__(self, current_page, total_pages, embed_callback):
        super().__init__()
        self.current_page = current_page
        self.total_pages = total_pages
        self.embed_callback = embed_callback

        # Create buttons for navigation
        self.prev_button = discord.ui.Button(label="Previous", style=discord.ButtonStyle.primary,
                                             disabled=(current_page == 1))
        self.next_button = discord.ui.Button(label="Next", style=discord.ButtonStyle.primary,
                                             disabled=(current_page == total_pages))

        # Link button callbacks
        self.prev_button.callback = self.prev_page
        self.next_button.callback = self.next_page

        self.add_item(self.prev_button)
        self.add_item(self.next_button)

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page -= 1
        embeds = await self.embed_callback(self.current_page)
        self.prev_button.disabled = self.current_page == 1
        self.next_button.disabled = self.current_page == self.total_pages
        await interaction.response.edit_message(embeds=embeds, view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page += 1
        embeds = await self.embed_callback(self.current_page)
        self.prev_button.disabled = self.current_page == 1
        self.next_button.disabled = self.current_page == self.total_pages
        await interaction.response.edit_message(embeds=embeds, view=self)


# Generate leaderboard embeds for pagination
async def generate_prize_leaderboard_embeds(page):
    items_per_page = 5  # Set the number of items per page
    offset = (page - 1) * items_per_page

    # Database connection and query
    conn = sqlite3.connect('streamer_data.db')
    c = conn.cursor()

    c.execute(''' 
        SELECT viewer_name, discord_id, total_won, total_received
        FROM giveaway_data
        ORDER BY total_received DESC, total_won DESC
        LIMIT ? OFFSET ? 
    ''', (items_per_page, offset))

    leaderboard_data = c.fetchall()
    embeds = []

    for rank, (viewer_name, discord_id, total_won, total_received) in enumerate(leaderboard_data, start=1 + offset):
        try:
            user = await bot.fetch_user(discord_id)  # Fetch the user by discord_id
        except discord.NotFound:
            user = None  # User not found

        # Default avatar URL if the user is not found
        avatar_url = "https://cdn.discordapp.com/embed/avatars/0.png"
        display_name = viewer_name  # Default display name is viewer_name (if user not found)

        if user:
            # Fetch member from the guild directly using the user ID
            member = interaction.guild.get_member(user.id)  # This checks if the user is in the guild
            if member:
                display_name = member.mention  # Use mention if the user is in the server
            else:
                display_name = user.name  # Use the username if the user is not in the server
            avatar_url = user.avatar.url if user.avatar else avatar_url  # Get user's avatar URL if available
        else:
            display_name = f"<@{discord_id}>"

        leaderboard_embed = discord.Embed(
            title=f"Rank {rank}: {viewer_name}",
            color=discord.Color.purple(),
            description=(
                f"Viewer: {display_name}\n"
                f"Times Won: **{total_won}**\n"
                f"Total $$$ Received: **${total_received}**"
            ),
        ).set_thumbnail(url=avatar_url)

        embeds.append(leaderboard_embed)

    conn.close()
    return embeds


# Admin-only command to update the prize pool
@bot.tree.command(name="update_prize_pool", description="Update the prize pool amount (Admin only)")
@app_commands.choices(action=[
    app_commands.Choice(name="ADD", value="ADD"),
    app_commands.Choice(name="REMOVE", value="REMOVE")
])
async def update_prize_pool(interaction: discord.Interaction, action: str, amount: float):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return

    conn = sqlite3.connect('streamer_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT amount FROM prize_pool WHERE id = 1")
    current_amount = cursor.fetchone()[0]

    if action == "ADD":
        new_amount = current_amount + amount
    elif action == "REMOVE":
        new_amount = max(0, current_amount - amount)

    cursor.execute("UPDATE prize_pool SET amount = ? WHERE id = 1", (new_amount,))
    conn.commit()
    conn.close()

    await interaction.response.send_message(f"Prize Pool updated: ${new_amount:.2f}", ephemeral=True)


# Command to display the current prize pool
@bot.tree.command(name="prize_pool", description="Check the current prize pool amount")
async def prize_pool(interaction: discord.Interaction):
    conn = sqlite3.connect('streamer_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT amount FROM prize_pool WHERE id = 1")
    current_amount = cursor.fetchone()[0]
    conn.close()

    embed = discord.Embed(title="Current Prize Pool", description=f"**${current_amount:.2f}**",
                          color=discord.Color.green())
    embed.set_footer(text="Note: Only the Grand Champion will win the Prize Pool")

    await interaction.response.send_message(embed=embed)


# Run bot
@bot.event
async def on_ready():
    try:
        await bot.tree.sync()  # Globally sync commands
        print("Slash commands synced successfully!")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    print(f"Logged in as {bot.user}")


load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if TOKEN is None:
    print("Error: No bot token found!")
else:
    print("Bot token loaded successfully!")
