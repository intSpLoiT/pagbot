from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from services.roblox_service import (
    RobloxAPIError,
    RobloxNotFoundError,
)
from services.top10_service import (
    Top10Entry,
    Top10Service,
)


class Top10ConfirmView(
    discord.ui.View,
):
    """
    Top 10 reset işlemi için onay paneli.

    Kullanıcı:
        Confirm → reset işlemini gerçekleştirir.

        Cancel → işlemi iptal eder.

    timeout:
        30 saniye.
    """

    def __init__(
        self,
        *,
        cog: "Top10",
        author_id: int,
    ) -> None:
        super().__init__(
            timeout=30,
        )

        self.cog = cog
        self.author_id = author_id
        self.confirmed = False

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        """
        Sadece komutu kullanan kişinin
        butonları kullanmasına izin verir.
        """

        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                (
                    "❌ Bu onay panelini "
                    "sadece komutu kullanan kişi "
                    "kullanabilir."
                ),
                ephemeral=True,
            )

            return False

        return True

    @discord.ui.button(
        label="Reset",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        """
        Reset işlemini onaylar.
        """

        self.confirmed = True

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content=(
                "⏳ PAG Top 10 sıfırlanıyor..."
            ),
            view=self,
        )

        try:
            await self.cog.service.reset()

        except Exception:
            self.cog.logger.exception(
                "Top 10 reset confirmation failed.",
            )

            await interaction.edit_original_response(
                content=(
                    "❌ Top 10 sıfırlanırken "
                    "beklenmeyen bir hata oluştu."
                ),
                view=None,
            )

            return

        await interaction.edit_original_response(
            content=(
                "✅ **PAG Top 10 başarıyla sıfırlandı.**"
            ),
            view=None,
        )

        self.stop()

    @discord.ui.button(
        label="Cancel",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        """
        Reset işlemini iptal eder.
        """

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content=(
                "❎ Top 10 reset işlemi iptal edildi."
            ),
            view=self,
        )

        self.stop()

    async def on_timeout(
        self,
    ) -> None:
        """
        Onay süresi dolduğunda butonları kapatır.
        """

        for child in self.children:
            child.disabled = True


class Top10(
    commands.Cog,
):
    """
    PAG Core
    Top 10 Cog

    This Cog provides the complete Discord interface
    for the PAG Top 10 ranking system.

    Public:

        /top10

    Administrator:

        /top10-set
        /top10-edit
        /top10-remove
        /top10-reset

    Ranking:

        Position 1 = Best player
        Position 2 = Second best player
        ...
        Position 10 = Tenth best player

    Data is managed by:

        services.top10_service.Top10Service

    Responsibilities:

        - Discord commands
        - Discord permissions
        - Embeds
        - Validation
        - Error handling
        - Reset confirmation
    """

    def __init__(
        self,
        bot: commands.Bot,
        *,
        top10_service: Top10Service,
        logger: logging.Logger,
    ) -> None:
        self.bot = bot
        self.service = top10_service
        self.logger = logger

    # ========================================================
    # CONSTANTS
    # ========================================================

    MIN_POSITION = 1
    MAX_POSITION = 10

    # ========================================================
    # EMBEDS
    # ========================================================

    @staticmethod
    def _build_top10_embed(
        entries: list[Top10Entry],
    ) -> discord.Embed:
        """
        PAG Top 10 embed'i oluşturur.
        """

        embed = discord.Embed(
            title="🏆 PAG TOP 10",
            description=(
                "The strongest players of PAG.\n\n"
                "Every position is earned."
            ),
            timestamp=discord.utils.utcnow(),
        )

        if not entries:
            embed.description = (
                "The PAG Top 10 is currently empty."
            )

            embed.set_footer(
                text=(
                    "PAG • Top 10 Rankings"
                ),
            )

            return embed

        medals = {
            1: "🥇",
            2: "🥈",
            3: "🥉",
        }

        lines: list[str] = []

        for entry in entries:
            prefix = medals.get(
                entry.position,
                f"`#{entry.position}`",
            )

            if entry.discord_id:
                member_text = (
                    f"<@{entry.discord_id}>"
                )

            else:
                member_text = (
                    f"**{entry.display_name}**"
                )

            lines.append(
                (
                    f"{prefix} "
                    f"{member_text}\n"
                    f"└ `{entry.roblox_username}`"
                )
            )

        embed.description = (
            "\n\n".join(
                lines,
            )
        )

        embed.set_footer(
            text=(
                "PAG • Top 10 Rankings"
            ),
        )

        return embed

    @staticmethod
    def _build_success_embed(
        title: str,
        description: str,
    ) -> discord.Embed:
        """
        Başarılı işlem embed'i.
        """

        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def _build_error_embed(
        title: str,
        description: str,
    ) -> discord.Embed:
        """
        Hata embed'i.
        """

        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def _build_info_embed(
        title: str,
        description: str,
    ) -> discord.Embed:
        """
        Bilgi embed'i.
        """

        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

    # ========================================================
    # VALIDATION
    # ========================================================

    @classmethod
    def _validate_position(
        cls,
        position: int,
    ) -> bool:
        """
        Pozisyonun 1-10 arasında olup olmadığını kontrol eder.
        """

        return (
            cls.MIN_POSITION
            <= position
            <= cls.MAX_POSITION
        )

    @staticmethod
    def _clean_username(
        username: str | None,
    ) -> str:
        """
        Roblox username temizler.
        """

        if username is None:
            return ""

        return username.strip()

    @staticmethod
    def _resolve_username(
        *,
        roblox_username: str | None,
    ) -> str | None:
        """
        Roblox username'i doğrular.
        """

        username = (
            Top10._clean_username(
                roblox_username,
            )
        )

        if not username:
            return None

        return username

    # ========================================================
    # DATABASE HELPERS
    # ========================================================

    async def _get_entries(
        self,
    ) -> list[Top10Entry]:
        """
        Güncel Top 10 listesini getirir.
        """

        return await self.service.get_all()

    async def _get_entry_at_position(
        self,
        position: int,
    ) -> Top10Entry | None:
        """
        Belirli pozisyondaki oyuncuyu bulur.
        """

        entries = await self._get_entries()

        for entry in entries:
            if entry.position == position:
                return entry

        return None

    # ========================================================
    # PUBLIC COMMAND
    # ========================================================

    @app_commands.command(
        name="top10",
        description="PAG Top 10 sıralamasını gösterir.",
    )
    async def top10(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        PAG Top 10 sıralamasını gösterir.

        Herkes kullanabilir.
        """

        await interaction.response.defer()

        try:
            entries = await self._get_entries()

        except Exception:
            self.logger.exception(
                "Failed to load PAG Top 10.",
            )

            await interaction.followup.send(
                embed=self._build_error_embed(
                    "❌ Top 10 Yüklenemedi",
                    (
                        "PAG Top 10 listesi "
                        "yüklenirken bir hata oluştu."
                    ),
                ),
            )

            return

        await interaction.followup.send(
            embed=self._build_top10_embed(
                entries,
            ),
        )

    # ========================================================
    # SET
    # ========================================================

    @app_commands.command(
        name="top10-set",
        description="Top 10'a oyuncu ekler veya pozisyonu değiştirir.",
    )
    @app_commands.describe(
        position="Oyuncunun yerleşeceği pozisyon. 1-10.",
        roblox_username="Roblox kullanıcı adı.",
        member="İsteğe bağlı Discord üyesi.",
    )
    @app_commands.checks.has_permissions(
        administrator=True,
    )
    async def top10_set(
        self,
        interaction: discord.Interaction,
        position: app_commands.Range[
            int,
            1,
            10,
        ],
        roblox_username: str,
        member: discord.Member | None = None,
    ) -> None:
        """
        Top 10'a oyuncu ekler veya mevcut oyuncuyu
        belirtilen pozisyona yerleştirir.

        Senaryolar:

        1.
            Boş pozisyona yeni oyuncu eklenir.

        2.
            Dolu pozisyona yeni oyuncu yazılır.
            Eski oyuncu o pozisyondan çıkarılır.

        3.
            Aynı Roblox oyuncusu başka pozisyondaysa
            service eski kaydı kaldırır.

        4.
            Discord member verilirse Discord ID
            Top 10 kaydına eklenir.
        """

        username = self._resolve_username(
            roblox_username=roblox_username,
        )

        if username is None:
            await interaction.response.send_message(
                embed=self._build_error_embed(
                    "❌ Geçersiz Roblox Kullanıcı Adı",
                    (
                        "Roblox kullanıcı adı "
                        "boş bırakılamaz."
                    ),
                ),
                ephemeral=True,
            )

            return

        await interaction.response.defer(
            ephemeral=True,
        )

        try:
            entry = await self.service.set_player(
                position=position,
                roblox_username=username,
                discord_id=(
                    member.id
                    if member is not None
                    else None
                ),
            )

        except RobloxNotFoundError:
            await interaction.followup.send(
                embed=self._build_error_embed(
                    "❌ Roblox Kullanıcısı Bulunamadı",
                    (
                        f"`{username}` adlı Roblox "
                        "kullanıcısı bulunamadı."
                    ),
                ),
                ephemeral=True,
            )

            return

        except RobloxAPIError:
            self.logger.exception(
                "Roblox API failed during Top 10 set.",
            )

            await interaction.followup.send(
                embed=self._build_error_embed(
                    "❌ Roblox API Hatası",
                    (
                        "Roblox API'sine erişilirken "
                        "bir hata oluştu."
                    ),
                ),
                ephemeral=True,
            )

            return

        except ValueError as error:
            await interaction.followup.send(
                embed=self._build_error_embed(
                    "❌ Geçersiz Pozisyon",
                    str(error),
                ),
                ephemeral=True,
            )

            return

        except Exception:
            self.logger.exception(
                "Top 10 set command failed.",
            )

            await interaction.followup.send(
                embed=self._build_error_embed(
                    "❌ Top 10 Güncellenemedi",
                    (
                        "Oyuncu Top 10'a eklenirken "
                        "beklenmeyen bir hata oluştu."
                    ),
                ),
                ephemeral=True,
            )

            return

        member_text = (
            member.mention
            if member is not None
            else "Discord üyesi bağlı değil"
        )

        await interaction.followup.send(
            embed=self._build_success_embed(
                "✅ Top 10 Güncellendi",
                (
                    f"**#{entry.position}** pozisyonuna "
                    f"**{entry.display_name}** eklendi.\n\n"
                    f"Roblox: `{entry.roblox_username}`\n"
                    f"Discord: {member_text}"
                ),
            ),
            ephemeral=True,
        )

    # ========================================================
    # EDIT
    # ========================================================

    @app_commands.command(
        name="top10-edit",
        description="Top 10'daki mevcut oyuncuyu düzenler.",
    )
    @app_commands.describe(
        position="Düzenlenecek mevcut pozisyon. 1-10.",
        roblox_username="Yeni Roblox kullanıcı adı.",
        member="Yeni Discord üyesi. İsteğe bağlı.",
        new_position="Oyuncunun yeni pozisyonu. İsteğe bağlı.",
    )
    @app_commands.checks.has_permissions(
        administrator=True,
    )
    async def top10_edit(
        self,
        interaction: discord.Interaction,
        position: app_commands.Range[
            int,
            1,
            10,
        ],
        roblox_username: str | None = None,
        member: discord.Member | None = None,
        new_position: app_commands.Range[
            int,
            1,
            10,
        ] | None = None,
    ) -> None:
        """
        Mevcut Top 10 kaydını düzenler.

        Önemli:

        Top10Service'in mevcut API'sinde
        doğrudan update_player metodu yoktur.

        Bu nedenle:

            - Aynı pozisyonda düzenleme:
                set_player()

            - Pozisyon değişikliği:
                move_player()
                ardından set_player()

        kullanılır.

        Böylece Cog, service'in mevcut gerçek
        public API'siyle çalışır.
        """

        current_entry = None

        try:
            current_entry = (
                await self._get_entry_at_position(
                    position,
                )
            )

        except Exception:
            self.logger.exception(
                "Failed to find Top 10 entry for edit.",
            )

            await interaction.response.send_message(
                embed=self._build_error_embed(
                    "❌ Top 10 Yüklenemedi",
                    (
                        "Düzenlenecek oyuncu "
                        "kontrol edilemedi."
                    ),
                ),
                ephemeral=True,
            )

            return

        if current_entry is None:
            await interaction.response.send_message(
                embed=self._build_error_embed(
                    "❌ Pozisyon Boş",
                    (
                        f"**#{position}** pozisyonunda "
                        "düzenlenecek oyuncu bulunmuyor."
                    ),
                ),
                ephemeral=True,
            )

            return

        username = self._clean_username(
            roblox_username,
        )

        if not username:
            username = (
                current_entry.roblox_username
            )

        target_position = (
            new_position
            if new_position is not None
            else position
        )

        await interaction.response.defer(
            ephemeral=True,
        )

        try:
            if target_position != position:
                await self.service.move_player(
                    old_position=position,
                    new_position=target_position,
                )

            entry = await self.service.set_player(
                position=target_position,
                roblox_username=username,
                discord_id=(
                    member.id
                    if member is not None
                    else current_entry.discord_id
                ),
            )

        except RobloxNotFoundError:
            await interaction.followup.send(
                embed=self._build_error_embed(
                    "❌ Roblox Kullanıcısı Bulunamadı",
                    (
                        f"`{username}` adlı Roblox "
                        "kullanıcısı bulunamadı."
                    ),
                ),
                ephemeral=True,
            )

            return

        except RobloxAPIError:
            self.logger.exception(
                "Roblox API failed during Top 10 edit.",
            )

            await interaction.followup.send(
                embed=self._build_error_embed(
                    "❌ Roblox API Hatası",
                    (
                        "Oyuncu düzenlenirken Roblox "
                        "API'sine erişilemedi."
                    ),
                ),
                ephemeral=True,
            )

            return

        except ValueError as error:
            await interaction.followup.send(
                embed=self._build_error_embed(
                    "❌ Geçersiz Pozisyon",
                    str(error),
                ),
                ephemeral=True,
            )

            return

        except Exception:
            self.logger.exception(
                "Top 10 edit command failed.",
            )

            await interaction.followup.send(
                embed=self._build_error_embed(
                    "❌ Düzenleme Başarısız",
                    (
                        "Top 10 oyuncusu düzenlenirken "
                        "beklenmeyen bir hata oluştu."
                    ),
                ),
                ephemeral=True,
            )

            return

            await interaction.followup.send(
                embed=self._build_error_embed(
                    "❌ Top 10 Güncellenemedi",
                    (
                        "Oyuncu Top 10'a eklenirken "
                        "beklenmeyen bir hata oluştu."
                    ),
                ),
                ephemeral=True,
            )

            return

        member_text = (
            member.mention
            if member is not None
            else "Discord üyesi bağlı değil"
        )

        await interaction.followup.send(
            embed=self._build_success_embed(
                "✅ Top 10 Güncellendi",
                (
                    f"**#{entry.position}** pozisyonuna "
                    f"**{entry.display_name}** eklendi.\n\n"
                    f"Roblox: `{entry.roblox_username}`\n"
                    f"Discord: {member_text}"
                ),
            ),
            ephemeral=True,
        )
    # EDIT
    # ========================================================

    @app_commands.command(
        name="top10-edit",
        description="Top 10'daki mevcut oyuncuyu düzenler.",
    )
    @app_commands.describe(
        position="Düzenlenecek mevcut pozisyon. 1-10.",
        roblox_username="Yeni Roblox kullanıcı adı.",
        member="Yeni Discord üyesi. İsteğe bağlı.",
        new_position="Oyuncunun yeni pozisyonu. İsteğe bağlı.",
    )
    @app_commands.checks.has_permissions(
        administrator=True,
    )
    async def top10_edit(
        self,
        interaction: discord.Interaction,
        position: app_commands.Range[
            int,
            1,
            10,
        ],
        roblox_username: str | None = None,
        member: discord.Member | None = None,
        new_position: app_commands.Range[
            int,
            1,
            10,
        ] | None = None,
    ) -> None:
        """
        Mevcut Top 10 kaydını düzenler.

        Önemli:

        Top10Service'in mevcut API'sinde
        doğrudan update_player metodu yoktur.

        Bu nedenle:

            - Aynı pozisyonda düzenleme:
                set_player()

            - Pozisyon değişikliği:
                move_player()
                ardından set_player()

        kullanılır.

        Böylece Cog, service'in mevcut gerçek
        apiyle çalışır 
        """
        current_entry = None

        try:
            current_entry = (
                await self._get_entry_at_position(
                    position,
                )
            )

        except Exception:
            self.logger.exception(
                "Failed to find Top 10 entry for edit.",
            )

            await interaction.response.send_message(
                embed=self._build_error_embed(
                    "❌ Top 10 Yüklenemedi",
                    (
                        "Düzenlenecek oyuncu "
                        "kontrol edilemedi."
                    ),
                ),
                ephemeral=True,
            )

            return

        if current_entry is None:
            await interaction.response.send_message(
                embed=self._build_error_embed(
                    "❌ Pozisyon Boş",
                    (
                        f"**#{position}** pozisyonunda "
                        "düzenlenecek oyuncu bulunmuyor."
                    ),
                ),
                ephemeral=True,
            )

            return

        username = self._clean_username(
            roblox_username,
        )
        username = self._clean_username(
            roblox_username,
        )

        if not username:
            username = (
                current_entry.roblox_username
            )

        target_position = (
            new_position
            if new_position is not None
            else position
        )

        await interaction.response.defer(
            ephemeral=True,
        )

        try:
            if target_position != position:
                await self.service.move_player(
                    old_position=position,
                    new_position=target_position,
                )

            entry = await self.service.set_player(
                position=target_position,
                roblox_username=username,
                discord_id=(
                    member.id
                    if member is not None
                    else current_entry.discord_id
                ),
            )
        try:
            if target_position != position:
                await self.service.move_player(
                    old_position=position,
                    new_position=target_position,
                )

            entry = await self.service.set_player(
                position=target_position,
                roblox_username=username,
                discord_id=(
                    member.id
                    if member is not None
                    else current_entry.discord_id
                ),
            )

        except RobloxNotFoundError:
            await interaction.followup.send(
                embed=self._build_error_embed(
                    "❌ Roblox Kullanıcısı Bulunamadı",
                    (
                        f"`{username}` adlı Roblox "
                        "kullanıcısı bulunamadı."
                    ),
                ),
                ephemeral=True,
            )

            return