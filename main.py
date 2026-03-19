import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
import openai
from openai import OpenAI
import json
import asyncio

load_dotenv()

#all tokens and stuff from .env
TOKEN = os.getenv ("DISCORD_TOKEN")
HACKCLUB_API_KEY = os.getenv('HACKCLUB_API_KEY')
HACKCLUB_BASE_URL = 'https://ai.hackclub.com/proxy/v1'
CONTEXT_MESSAGES = int(os.getenv('CONTEXT_MESSAGES', '10'))
BAD_CONFIDENCE_THRESHOLD = float(os.getenv('BAD_CONFIDENCE_THRESHOLD', '0.8'))

if not TOKEN or not HACKCLUB_API_KEY:
    raise ValueError("Error: Missing DISCORD_TOKEN or HACKCLUB_API_KEY in environment variables.")

client = OpenAI(api_key=HACKCLUB_API_KEY, base_url=HACKCLUB_BASE_URL)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

#when the bot has started, this notifies in the console
@bot.event
async def on_ready():
    print(f'{bot.user} has started.')

# this analyses all messages and deletes bad ones.
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
        response = client.chat.completions.create(  
            model="google/gemini-2.5-flash",   #this model is very fast and doesnt use too much tokens
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

        if content.strip().startswith("```"):
            lines = content.splitlines()
            if len(lines) >= 3:
                content = "\n".join(lines[1:-1])

        result = json.loads(content)

        if result['is_bad'] and result['confidence'] >= BAD_CONFIDENCE_THRESHOLD:
            await message.delete()
            log_embed = discord.Embed(
                title="Moderation Action",
                description=(
                    f"Deleted bad message by {message.author.mention}\n"
                    f"Reason: {result['reason']}\n"
                    f"Confidence: {result['confidence']:.2f}"
                ),
                color=0xff0000,
            )
            await message.channel.send(embed=log_embed, delete_after=10)
            print(f"Moderated {message.author}: {result}")

    except Exception as e:
        print(f"Oh no! Something went wrong. Error: {e}")

bot.run(TOKEN)
