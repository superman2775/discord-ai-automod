import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
import openai
from openai import OpenAI
import json
import asyncio

load_dotenv()

TOKEN = os.getenv ("DISCORD_TOKEN")
HACKCLUB_API_KEY = os.getenv('HACKCLUB_API_KEY')
HACKCLUB_BASE_URL = 'https://ai.hackclub.com/proxy/v1/chat/completions'
CONTEXT_MESSAGES = int(os.getenv('CONTEXT_MESSAGES', '10'))
BAD_CONFIDENCE_THRESHOLD = float(os.getenv('BAD_CONFIDENCE_THRESHOLD', '0.8'))

if not TOKEN or not HACKCLUB_API_KEY:
    raise ValueError("Error: Missing DISCORD_TOKEN or HACKCLUB_API_KEY in environment variables.")

# openai keys setup
openai.api_key = HACKCLUB_API_KEY
openai.api_base = HACKCLUB_BASE_URL

client = OpenAI(api_key=HACKCLUB_API_KEY, base_url=HACKCLUB_BASE_URL)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user} has started.')

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    async for msg in message.channel.history(limit=CONTEXT_MESSAGES + 1, before=message):
        if msg.author.bot:
            continue

    context = [msg async for msg in message.channel.history(limit=CONTEXT_MESSAGES, before=message) if not msg.author.bot]
    context_text = '\n'.join([f"{msg.author.name}: {msg.content}" for msg in context[-CONTEXT_MESSAGES:]]) + f"\n{message.author.name}: {message.content}"

    try:
        response = await openai.ChatCompletion.acreate(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": "Classify if this message in context is bad (hate speech, harassment, spam, explicit). Respond ONLY with JSON: {'is_bad': true/false, 'confidence': 0-1, 'reason': 'brief reason'}"},
                {"role": "user", "content": context_text}
            ],
            max_tokens=100,
        )
        result = eval(response.choices[0].message.content)

        if result['is_bad'] and result['confidence'] >= BAD_CONFIDENCE_THRESHOLD:
            await message.delete()
            log_embed = discord.Embed(title="Moderation Action", description=f"Deleted bad message by {message.author.mention}\nReason: {result['reason']}\nConfidence: {result['confidence']:.2f}", color=0xff0000)
            log_embed.add_field(name="Context", value=context_text[:1000], inline=False)
            await message.channel.send(embed=log_embed, delete_after=10)
            print(f"Moderated {message.author}: {result}")

    except Exception as e:
        print(f"Oh no! Something went wrong. Error: {e}")

bot.run(TOKEN)
