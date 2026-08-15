import asyncio
import discord
from discord.ext import commands

OWNER_USERNAME = "velgrath_"

class DMCleanup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="cleanup-dm")
    async def cleanup_dm(self, ctx, limit_per_dm: int = 500):
        """
        Botun gönderdiği DM mesajlarını temizler.
        Velgrath ile olan DM kanalına ASLA dokunmaz.
        """

        # Sadece velgrath_ kullanabilsin
        if ctx.author.name.lower() != OWNER_USERNAME:
            return

        await ctx.reply(
            "🧹 DM temizleme başlatıldı. Velgrath DM kanalı korunuyor.",
            mention_author=False
        )

        deleted = 0
        scanned_channels = 0
        skipped_channels = 0
        failed_channels = 0

        for channel in list(self.bot.private_channels):
            if not isinstance(channel, discord.DMChannel):
                continue

            scanned_channels += 1

            recipient = getattr(channel, "recipient", None)

            # Velgrath ile olan DM kanalını tamamen koru
            if recipient and recipient.name.lower() == OWNER_USERNAME:
                skipped_channels += 1
                continue

            try:
                async for message in channel.history(limit=limit_per_dm):
                    # Sadece botun kendi mesajlarını sil
                    if message.author.id != self.bot.user.id:
                        continue

                    try:
                        await message.delete()
                        deleted += 1
                        await asyncio.sleep(0.25)

                    except discord.NotFound:
                        continue
                    except discord.Forbidden:
                        break
                    except discord.HTTPException:
                        await asyncio.sleep(1)

            except discord.Forbidden:
                failed_channels += 1
            except discord.HTTPException:
                failed_channels += 1

        await ctx.send(
            (
                "✅ **DM temizleme tamamlandı**\\n\\n"
                f"• Silinen bot mesajı: **{deleted}**\\n"
                f"• Taranan DM kanalı: **{scanned_channels}**\\n"
                f"• Korunan kanal (Velgrath): **{skipped_channels}**\\n"
                f"• Hata alınan kanal: **{failed_channels}**"
            ),
            delete_after=15
        )

async def setup(bot):
    await bot.add_cog(DMCleanup(bot))
