import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
from discord import app_commands
import yt_dlp
import asyncio
import os
from myserver import server_on
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "I'm alive"

def run():
  app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# กำหนด intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents)

# ตัวแปร Global
song_queue = {}          # คิวเพลง
current_song = {}        # เพลงปัจจุบัน
loop_status = {}         # สถานะ loop
previous_songs = {}      # เพลงที่เคยเล่นแล้ว (สำหรับ back_button)

# ฟังก์ชันโหลด stream จาก yt-dlp
def get_stream_url(url):
    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'quiet': False,  # เปลี่ยนเป็น False เพื่อดู log
        'no_warnings': False,
        'default_search': 'auto',
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            print(f"[DEBUG] Extracted info: {info}")  # เพิ่ม log
            if 'entries' in info:
                info = info['entries'][0]
            return info['url'], info.get('title', 'Unknown Title')
    except Exception as e:
        print(f"⚠️ Error extracting info: {e}")
        return None, None



async def play_next(ctx):
    guild_id = ctx.guild.id

    if loop_status.get(guild_id, False) and current_song.get(guild_id):
        url, title = current_song[guild_id]
        stream_url, _ = get_stream_url(url)
        if not stream_url:
            if isinstance(ctx, commands.Context):
                await ctx.send("⚠️ ไม่สามารถโหลดเพลงซ้ำได้")
            else:
                await ctx.followup.send("⚠️ ไม่สามารถโหลดเพลงซ้ำได้")
            return

        source = discord.FFmpegPCMAudio(stream_url)
        voice_client = ctx.guild.voice_client

        if voice_client is None or not voice_client.is_connected():
            if ctx.author.voice:
                voice_client = await ctx.author.voice.channel.connect()
            else:
                if isinstance(ctx, commands.Context):
                    await ctx.send("❗ คุณต้องอยู่ในห้องเสียงก่อนเล่นเพลง")
                else:
                    await ctx.followup.send("❗ คุณต้องอยู่ในห้องเสียงก่อนเล่นเพลง")
                return

        voice_client.play(source, after=lambda e: bot.loop.create_task(play_next(ctx)))
        if isinstance(ctx, commands.Context):
            await ctx.send(f"🔁 กำลังเล่นซ้ำ: {title}")
        else:
            await ctx.followup.send(f"🔁 กำลังเล่นซ้ำ: {title}")

        return

    if song_queue.get(guild_id) and len(song_queue[guild_id]) > 0:
        url, title = song_queue[guild_id].pop(0)
        stream_url, _ = get_stream_url(url)

        if not stream_url:
            if isinstance(ctx, commands.Context):
                await ctx.send("⚠️ ไม่สามารถโหลดเพลงถัดไปได้")
            else:
                await ctx.followup.send("⚠️ ไม่สามารถโหลดเพลงถัดไปได้")
            return

        # เพิ่มเพลงปัจจุบันเข้า previous_songs ก่อนเปลี่ยน
        if guild_id not in previous_songs:
            previous_songs[guild_id] = []
        if current_song.get(guild_id):
            previous_songs[guild_id].append(current_song[guild_id])
        current_song[guild_id] = (url, title)

        # ตรวจสอบ voice client
        voice_client = ctx.guild.voice_client
        if voice_client is None or not voice_client.is_connected():
            if ctx.author.voice:
                voice_client = await ctx.author.voice.channel.connect()
            else:
                if isinstance(ctx, commands.Context):
                    await ctx.send("❗ กรุณาเข้าห้องเสียงก่อน")
                else:
                    await ctx.followup.send("❗ กรุณาเข้าห้องเสียงก่อน")
                return

        source = discord.FFmpegPCMAudio(stream_url)
        voice_client.play(source, after=lambda e: bot.loop.create_task(play_next(ctx)))

        if isinstance(ctx, commands.Context):
            await ctx.send(f"🎶 กำลังเล่น: {title}")
        else:
            await ctx.followup.send(f"🎶 กำลังเล่น: {title}")

    else:
        voice_client = ctx.guild.voice_client
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()

        if isinstance(ctx, commands.Context):
            await ctx.send("คิวเพลงหมดแล้ว บอทออกจากห้องเสียง")

        current_song.pop(guild_id, None)


class AddSongModal(Modal, title="เพิ่มเพลง"):
    url_input = TextInput(
        label="ลิงก์เพลง",
        placeholder="https://youtube.com/watch?v=... ",
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        url = self.url_input.value
        guild_id = interaction.guild.id

        # ✅ ตรวจสอบลิงก์ก่อน
        if not url.startswith(("https://youtube.com",  "https://www.youtube.com",  "https://youtu.be")): 
            return await interaction.followup.send("⚠️ รองรับเฉพาะลิงก์ YouTube", ephemeral=True)

        # ✅ ตรวจสอบและ defer ก่อนใช้งาน
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        else:
            return await interaction.followup.send("⚠️ การโต้ตอบหมดอายุแล้ว", ephemeral=True)

        # ✅ โหลดเพลง
        stream_url, title = get_stream_url(url)
        if not stream_url:
            return await interaction.followup.send(
                "⚠️ ไม่สามารถโหลดเพลงได้\n"
                "อาจเกิดจาก:\n"
                "- ลิงก์ไม่ถูกต้อง\n"
                "- เพลงถูกลบหรือถูกจำกัดสิทธิ์\n"
                "- ปัญหาการเชื่อมต่อเซิร์ฟเวอร์",
                ephemeral=True
            )

        # ✅ เพิ่มเพลงลงคิว
        if guild_id not in song_queue:
            song_queue[guild_id] = []
        song_queue[guild_id].append((url, title))
        await interaction.followup.send(f"📥 เพิ่มเข้าในคิว: {title}", ephemeral=True)

        # ✅ เชื่อมต่อกับห้องเสียง
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_connected():
            if interaction.user.voice:
                voice_client = await interaction.user.voice.channel.connect()
            else:
                return await interaction.followup.send("❗ คุณต้องอยู่ในห้องเสียงก่อน", ephemeral=True)

        # ✅ เริ่มเล่นเพลงถ้าไม่มีเพลงกำลังเล่น
        if not voice_client.is_playing() and not voice_client.is_paused():
            await play_next(interaction)

# ตัวแปร Global
song_queue = {}          # คิวเพลง
current_song = {}        # เพลงปัจจุบัน
loop_status = {}         # สถานะ loop
previous_songs = {}      # เพลงที่เคยเล่นแล้ว

class FullCommandButtonView(View):
    def __init__(self, ctx):
        super().__init__(timeout=None)
        self.ctx = ctx

    @discord.ui.button(label="รายการเพลง", style=discord.ButtonStyle.success, emoji="📋", row=0)
    async def queue_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานปุ่มนี้ กรุณาพิมพ์คำสั่ง  !p  เพิ่มเริ่มใช้งาน", ephemeral=True)
            return

        guild_id = interaction.guild.id
        if guild_id not in song_queue or not song_queue[guild_id]:
            await interaction.response.send_message("📭 คิวเพลงว่างเปล่า", ephemeral=True)
        else:
            message = "**🎶 คิวเพลง:**\n"
            for i, (_, title) in enumerate(song_queue[guild_id], 1):
                message += f"{i}. {title}\n"
            await interaction.response.send_message(message, ephemeral=True)

    @discord.ui.button(label="เพิ่มเพลง", style=discord.ButtonStyle.blurple, emoji="➕", row=0)
    async def add_song_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานปุ่มนี้ กรุณาพิมพ์คำสั่ง  !p  เพิ่มเริ่มใช้งาน", ephemeral=True)
            return

        await interaction.response.send_modal(AddSongModal())


    @discord.ui.button(label="เล่น / หยุด", style=discord.ButtonStyle.secondary, emoji="⏯️", row=0)
    async def play_pause_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานปุ่มนี้ กรุณาพิมพ์คำสั่ง  !p  เพิ่มเริ่มใช้งาน", ephemeral=True)
            return

        if self.ctx.voice_client.is_paused():
            self.ctx.voice_client.resume()
            await interaction.response.send_message("▶️ เริ่มเล่นเพลงต่อ", ephemeral=True)
        else:
            self.ctx.voice_client.pause()
            await interaction.response.send_message("⏸️ หยุดเล่นเพลงชั่วคราว", ephemeral=True)


    @discord.ui.button(label="ลูป‍", style=discord.ButtonStyle.secondary, emoji="🔁", row=0)
    async def loop_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานปุ่มนี้ กรุณาพิมพ์คำสั่ง  !p  เพิ่มเริ่มใช้งาน", ephemeral=True)
            return

        guild_id = interaction.guild.id
        loop_status[guild_id] = not loop_status.get(guild_id, False)
        status = "เปิด" if loop_status[guild_id] else "ปิด"
        await interaction.response.send_message(f"🔁 โหมดวนลูปถูก {status}", ephemeral=True)


    @discord.ui.button(label="ย้อนกลับ", style=discord.ButtonStyle.grey, emoji="⏮️", row=1)
    async def back_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานปุ่มนี้ กรุณาพิมพ์คำสั่ง  !p  เพิ่มเริ่มใช้งาน", ephemeral=True)
            return

        guild_id = interaction.guild.id

        if guild_id not in previous_songs or len(previous_songs[guild_id]) < 2:
            return await interaction.response.send_message("❗ ไม่มีเพลงที่ย้อนกลับได้", ephemeral=True)

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        else:
            return await interaction.followup.send("⚠️ การโต้ตอบหมดอายุแล้ว", ephemeral=True)

        prev_url, prev_title = previous_songs[guild_id][-2]
        stream_url, title = get_stream_url(prev_url)
        voice_client = interaction.guild.voice_client

        if not stream_url:
            return await interaction.followup.send("⚠️ ไม่สามารถโหลดเพลงได้", ephemeral=True)

        if voice_client and voice_client.is_playing():
            voice_client.stop()

        source = discord.FFmpegPCMAudio(stream_url)
        voice_client.play(source, after=lambda e: self.ctx.bot.loop.create_task(play_next(interaction)))
        previous_songs[guild_id].append((prev_url, prev_title))
        await interaction.followup.send(f"⏮️ ย้อนกลับไป: {title}", ephemeral=True)


    @discord.ui.button(label="ข้าม", style=discord.ButtonStyle.grey, emoji="⏭️", row=1)
    async def skip_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานปุ่มนี้ กรุณาพิมพ์คำสั่ง  !p  เพิ่มเริ่มใช้งาน", ephemeral=True)
            return

        if self.ctx.voice_client and self.ctx.voice_client.is_playing():
            self.ctx.voice_client.stop()
            await interaction.response.send_message("⏭️ ข้ามเพลง", ephemeral=True)
        else:
            await interaction.response.send_message("❗ ไม่มีเพลงกำลังเล่น", ephemeral=True)


    @discord.ui.button(label="ออก", style=discord.ButtonStyle.red, emoji="⏹️", row=1)
    async def stop_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานปุ่มนี้ กรุณาพิมพ์คำสั่ง  !p  เพิ่มเริ่มใช้งาน", ephemeral=True)
            return

        guild_id = interaction.guild.id
        if self.ctx.voice_client:
            await self.ctx.voice_client.disconnect()
            song_queue[guild_id] = []
            loop_status[guild_id] = False
            current_song[guild_id] = None
            await interaction.response.send_message("⏹️ หยุดและออกจากห้องเสียง", ephemeral=True)
        else:
            await interaction.response.send_message("❗ บอทไม่อยู่ในห้องเสียง", ephemeral=True)


@bot.command(name='p')
async def open_controls(ctx):
    if ctx.author.voice is None:
        await ctx.send("❗ เข้าห้องเสียงก่อนนะ")
        return
    if ctx.voice_client is None:
        await ctx.author.voice.channel.connect(timeout=60.0, reconnect=True)
    view = FullCommandButtonView(ctx)
    await ctx.send("🎛️ **แผงควบคุมเพลง**", view=view)


@bot.event
async def on_ready():
    print("Bot Started!")
    synced = await bot.tree.sync()
    print(f"{len(synced)} command(s)")


@bot.event
async def on_member_join(member):
    channel = bot.get_channel(1371431002093912126)
    if channel:
        embed = discord.Embed(
            title="🎉 ยินดีต้อนรับสมาชิกใหม่!!",
            description=f"{member.mention} เดินผ่านประตู... อาณาจักร MisterOue เริ่มต้นขึ้นแล้ว",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=member.avatar.url)
        await channel.send(embed=embed)


@bot.event
async def on_member_remove(member):
    channel = bot.get_channel(1371431002093912126)
    if channel:
        embed = discord.Embed(
            title="🚪 สมาชิกจากไป...",
            description=f"เมื่อประตูปิดลง... แต่โชคชะตาของ {member.mention} ยังคงวนลูปอยู่ใน MisterOue",
            color=discord.Color.red()
        )
        embed.set_thumbnail(url=member.avatar.url)
        await channel.send(embed=embed)

@bot.command()
@commands.is_owner()  # ใช้ได้เฉพาะเจ้าของบอท
async def say(ctx, *, message: str = None):
    if message is None:
        await ctx.send("❗ กรุณาระบุข้อความ เช่น `!say สวัสดี`")
        return

    embed = discord.Embed(
        description=message,
        color=discord.Color.gold()
    )
    embed.set_author(name="📢 แจ้งเตือนข่าวสาร", icon_url=ctx.bot.user.avatar.url)
    await ctx.send(embed=embed)


server_on()
bot.run(os.getenv('TOKEN'))