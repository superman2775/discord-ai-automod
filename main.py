import os
import json
import asyncio
from pathlib import Path
from dotenv import load_dotenv
import discord
from discord.ext import commands
from openai import OpenAI

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
HACKCLUB_API_KEY = os.getenv("HACKCLUB_API_KEY")
HACKCLUB_BASE_URL = "https://ai.hackclub.com/proxy/v1" 
CONTEXT_MESSAGES = int(os.getenv("CONTEXT_MESSAGES", "10"))
BAD_CONFIDENCE_THRESHOLD = float(os.getenv("BAD_CONFIDENCE_THRESHOLD", "0.8"))

if not TOKEN or not HACKCLUB_API_KEY:
    raise ValueError("Error: Missing DISCORD_TOKEN or HACKCLUB_API_KEY in environment variables.")

client = OpenAI(api_key=HACKCLUB_API_KEY, base_url=HACKCLUB_BASE_URL)

LOG_CONFIG_FILE = Path("log_channels.json")

if LOG_CONFIG_FILE.exists():
    with LOG_CONFIG_FILE.open("r", encoding="utf-8") as f:
        LOG_CHANNELS = json.load(f)
else:
    LOG_CHANNELS = {}  


def save_log_channels():
    with LOG_CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(LOG_CHANNELS, f, indent=2)


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} has started.")


@bot.tree.command(name="log-channel", description="Set the moderation log channel for this server")
@discord.app_commands.describe(channel="Channel where moderation logs will be sent")
@discord.app_commands.checks.has_permissions(manage_guild=True)
async def set_log_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    guild_id_str = str(interaction.guild_id)
    LOG_CHANNELS[guild_id_str] = channel.id
    save_log_channels()
    await interaction.response.send_message(
        f"Log channel set to {channel.mention}", ephemeral=True
    )


@set_log_channel.error
async def set_log_channel_error(interaction: discord.Interaction, error):
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.response.send_message(
            "You need the **Manage Server** permission to use this command.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            "Something went wrong while setting the log channel.",
            ephemeral=True,
        )


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    try:
        context = [
            msg
            async for msg in message.channel.history(
                limit=CONTEXT_MESSAGES, before=message
            )
            if not msg.author.bot
        ]
    except Exception as e:
        print(f"Failed to fetch history: {e}")
        context = []

    context_text = "\n".join(
        f"{msg.author.name}: {msg.content}" for msg in context[-CONTEXT_MESSAGES:]
    ) + f"\n{message.author.name}: {message.content}"

    try:
        response = client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a JSON-only classifier. "
                        "Given the chat context, decide if the LAST user message is bad "
                        "(hate speech, harassment, spam, explicit). "
                        "Respond ONLY with valid JSON and nothing else, in this exact shape: "
                        "{"
                        "\"is_bad\": true or false, "
                        "\"confidence\": number between 0 and 1, "
                        "\"reason\": \"brief reason\""
                        "}"
                    ),
                },
                {"role": "user", "content": context_text},
            ],
            max_tokens=100,
            temperature=0.1,
        )

        content = response.choices[0].message.content or ""
        print("AI raw content:", repr(content))

        if content.strip().startswith("```"):
            lines = content.splitlines()
            if len(lines) >= 3:
                content = "\n".join(lines[1:-1])

        result = json.loads(content)

        if result["is_bad"] and result["confidence"] >= BAD_CONFIDENCE_THRESHOLD:
            await message.delete()
            log_embed = discord.Embed(
                title="Moderation Action",
                description=(
                    f"Deleted bad message by {message.author.mention}\n"
                    f"Reason: {result['reason']}\n"
                    f"Confidence: {result['confidence']:.2f}"
                ),
                color=0xFF0000,
            )

            await message.channel.send(embed=log_embed)

            if message.guild is not None:
                guild_id_str = str(message.guild.id)
                log_channel_id = LOG_CHANNELS.get(guild_id_str)
                if log_channel_id:
                    log_channel = message.guild.get_channel(log_channel_id)
                    if log_channel and log_channel.id != message.channel.id:
                        await log_channel.send(embed=log_embed)

            print(f"Moderated {message.author}: {result}")

    except Exception as e:
        print(f"Oh no! Something went wrong. Error: {e}")

    await bot.process_commands(message)


bot.run(TOKEN)
