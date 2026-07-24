from __future__ import annotations

import logging
from typing import Iterable

import discord
from discord import app_commands
from discord.ext import commands

from services.roblox_service import (
    RobloxAPIError,
    RobloxAvatar,
    RobloxNotFoundError,
    RobloxService,
    RobloxUser,
)


class Roblox(commands.GroupCog, group_name="roblox"):
    """
    PAG Roblox komutları.

    Public:
        /roblox user
        /roblox id
        /roblox avatar
        /roblox search
        /roblox batch
        /roblox avatars

    Admin:
        /roblox admin user
        /roblox admin avatar
        /roblox admin batch
        /roblox admin avatars
    """

    def __init__(
        self,
        bot: commands.Bot,
        *,
        roblox_service: RobloxService,
        logger: logging.Logger,
    ) -> None:
        self.bot = bot
        self.roblox_service = roblox_service
        self.logger = logger

        self.admin = RobloxAdmin(
            roblox_service=roblox_service,
            logger=logger,
        )

    # ========================================================
    # HELPERS
    # ========================================================

    @staticmethod
    def _error(
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
    def _info(
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

    @staticmethod
    def _success(
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
    def _user_profile_url(
        user_id: int,
    ) -> str:
        """
        Roblox profil URL'si.
        """

        return (
            "https://www.roblox.com/users/"
            f"{user_id}/profile"
        )

    @staticmethod
    def _format_date(
        value: str,
    ) -> str:
        """
        Tarih bilgisini güvenli şekilde formatlar.
        """

        if not value:
            return "Bilinmiyor"

        return value[:100]

    @staticmethod
    def _parse_id_list(
        value: str,
        *,
        limit: int = 25,
    ) -> list[int]:
        """
        Virgül veya boşluk ile ayrılmış ID listesini parse eder.

        Örnek:

            123, 456, 789

        veya:

            123 456 789
        """

        raw_items = (
            value
            .replace(",", " ")
            .split()
        )

        if not raw_items:
            raise ValueError(
                "En az bir Roblox User ID gerekli.",
            )

        if len(raw_items) > limit:
            raise ValueError(
                f"En fazla {limit} adet ID kullanılabilir.",
            )

        user_ids: list[int] = []

        for item in raw_items:
            try:
                user_id = int(item)

            except ValueError as error:
                raise ValueError(
                    f"Geçersiz Roblox User ID: {item}",
                ) from error

            if user_id <= 0:
                raise ValueError(
                    "Roblox User ID pozitif olmalıdır.",
                )

            user_ids.append(user_id)

        return list(
            dict.fromkeys(user_ids),
        )

    @staticmethod
    def _build_user_embed(
        user: RobloxUser,
        *,
        avatar: RobloxAvatar | None = None,
        detailed: bool = False,
    ) -> discord.Embed:
        """
        RobloxUser modelini Discord embed'ine çevirir.
        """

        embed = discord.Embed(
            title=(
                f"👤 {user.display_name}"
            ),
            description=(
                f"**@{user.name}**"
            ),
            url=(
                "https://www.roblox.com/users/"
                f"{user.id}/profile"
            ),
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="Username",
            value=f"`{user.name}`",
            inline=True,
        )

        embed.add_field(
            name="Display Name",
            value=f"`{user.display_name}`",
            inline=True,
        )

        embed.add_field(
            name="User ID",
            value=f"`{user.id}`",
            inline=True,
        )

        if detailed:
            embed.add_field(
                name="Account Created",
                value=(
                    f"`{user.created}`"
                    if user.created
                    else "Bilinmiyor"
                ),
                inline=False,
            )

            embed.add_field(
                name="Account Status",
                value=(
                    "🔴 Banned"
                    if user.is_banned
                    else "🟢 Active"
                ),
                inline=True,
            )

        if user.description:
            description = user.description

            if len(description) > 1024:
                description = (
                    description[:1021]
                    + "..."
                )

            embed.add_field(
                name="Description",
                value=description,
                inline=False,
            )

        if avatar is not None:
            embed.set_thumbnail(
                url=avatar.image_url,
            )

        return embed

    @staticmethod
    def _build_avatar_embed(
        user: RobloxUser,
        avatar: RobloxAvatar,
    ) -> discord.Embed:
        """
        Avatar embed'i.
        """

        embed = discord.Embed(
            title=(
                f"🧍 {user.display_name}"
            ),
            description=(
                f"**@{user.name}**\n"
                f"Roblox User ID: `{user.id}`"
            ),
            url=(
                "https://www.roblox.com/users/"
                f"{user.id}/profile"
            ),
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        embed.set_image(
            url=avatar.image_url,
        )

        embed.set_footer(
            text=(
                "PAG Roblox Service"
            ),
        )

        return embed

    @staticmethod
    def _build_user_list_embed(
        users: Iterable[RobloxUser],
        *,
        title: str,
    ) -> discord.Embed:
        """
        Kullanıcı listesini embed'e çevirir.
        """

        users = list(users)

        embed = discord.Embed(
            title=title,
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        if not users:
            embed.description = (
                "Hiçbir Roblox kullanıcısı bulunamadı."
            )

            return embed

        lines: list[str] = []

        for index, user in enumerate(
            users,
            start=1,
        ):
            lines.append(
                f"**{index}.** "
                f"[{user.display_name}]"
                f"({Roblox._user_profile_url(user.id)}) "
                f"`@{user.name}` "
                f"`{user.id}`"
            )

        description = "\n".join(
            lines,
        )

        if len(description) > 4000:
            description = (
                description[:3997]
                + "..."
            )

        embed.description = description

        embed.set_footer(
            text=(
                f"{len(users)} kullanıcı bulundu."
            ),
        )

        return embed

    # ========================================================
    # USER
    # ========================================================

    @app_commands.command(
        name="user",
        description="Roblox kullanıcı adından profil bilgisi getirir.",
    )
    @app_commands.describe(
        username="Roblox kullanıcı adı.",
    )
    async def user(
        self,
        interaction: discord.Interaction,
        username: str,
    ) -> None:
        """
        Username üzerinden Roblox kullanıcı arar.
        """

        username = username.strip()

        if not username:
            await interaction.response.send_message(
                embed=self._error(
                    "❌ Geçersiz Kullanıcı Adı",
                    (
                        "Roblox kullanıcı adı boş bırakılamaz."
                    ),
                ),
                ephemeral=True,
            )

            return

        await interaction.response.defer()

        try:
            user = (
                await self.roblox_service
                .get_user_by_username(
                    username,
                )
            )

        except RobloxNotFoundError:
            await interaction.followup.send(
                embed=self._error(
                    "❌ Kullanıcı Bulunamadı",
                    (
                        f"`{username}` adlı Roblox "
                        "kullanıcısı bulunamadı."
                    ),
                ),
            )

            return

        except RobloxAPIError:
            self.logger.exception(
                "Roblox username lookup failed: %s",
                username,
            )

            await interaction.followup.send(
                embed=self._error(
                    "❌ Roblox API Hatası",
                    (
                        "Roblox API'sine erişilirken "
                        "bir hata oluştu."
                    ),
                ),
            )

            return

        except Exception:
            self.logger.exception(
                "Unexpected Roblox username error: %s",
                username,
            )

            await interaction.followup.send(
                embed=self._error(
                    "❌ Beklenmeyen Hata",
                    (
                        "Roblox kullanıcısı aranırken "
                        "beklenmeyen bir hata oluştu."
                    ),
                ),
            )

            return

        avatar: RobloxAvatar | None = None

        try:
            avatar = (
                await self.roblox_service
                .get_avatar(
                    user.id,
                )
            )

        except RobloxNotFoundError:
            self.logger.warning(
                "Avatar not found for user: %s",
                user.id,
            )

        except RobloxAPIError:
            self.logger.warning(
                "Avatar API failed for user: %s",
                user.id,
            )

        embed = self._build_user_embed(
            user,
            avatar=avatar,
            detailed=True,
        )

        await interaction.followup.send(
            embed=embed,
        )

    # ========================================================
    # ID
    # ========================================================

    @app_commands.command(
        name="id",
        description="Roblox User ID üzerinden kullanıcı bilgisi getirir.",
    )
    @app_commands.describe(
        user_id="Roblox User ID.",
    )
    async def user_by_id(
        self,
        interaction: discord.Interaction,
        user_id: int,
    ) -> None:
        """
        User ID üzerinden Roblox kullanıcı arar.
        """

        if user_id <= 0:
            await interaction.response.send_message(
                embed=self._error(
                    "❌ Geçersiz User ID",
                    (
                        "Roblox User ID pozitif "
                        "bir sayı olmalıdır."
                    ),
                ),
                ephemeral=True,
            )

            return

        await interaction.response.defer()

        try:
            user = (
                await self.roblox_service
                .get_user(
                    user_id,
                )
            )

        except RobloxNotFoundError:
            await interaction.followup.send(
                embed=self._error(
                    "❌ Kullanıcı Bulunamadı",
                    (
                        f"`{user_id}` ID'sine sahip "
                        "Roblox kullanıcısı bulunamadı."
                    ),
                ),
            )

            return

        except RobloxAPIError:
            self.logger.exception(
                "Roblox ID lookup failed: %s",
                user_id,
            )

            await interaction.followup.send(
                embed=self._error(
                    "❌ Roblox API Hatası",
                    (
                        "Roblox API'sinden kullanıcı "
                        "bilgisi alınamadı."
                    ),
                ),
            )

            return

        except Exception:
            self.logger.exception(
                "Unexpected Roblox ID lookup error: %s",
                user_id,
            )

            await interaction.followup.send(
                embed=self._error(
                    "❌ Beklenmeyen Hata",
                    (
                        "Kullanıcı bilgisi alınırken "
                        "beklenmeyen bir hata oluştu."
                    ),
                ),
            )

            return

        avatar: RobloxAvatar | None = None

        try:
            avatar = (
                await self.roblox_service
                .get_avatar(
                    user.id,
                )
            )

        except (
            RobloxNotFoundError,
            RobloxAPIError,
        ):
            pass

        embed = self._build_user_embed(
            user,
            avatar=avatar,
            detailed=True,
        )

        await interaction.followup.send(
            embed=embed,
        )

    # ========================================================
    # AVATAR
    # ========================================================

    @app_commands.command(
        name="avatar",
        description="Bir Roblox kullanıcısının avatarını gösterir.",
    )
    @app_commands.describe(
        username="Roblox kullanıcı adı.",
    )
    async def avatar(
        self,
        interaction: discord.Interaction,
        username: str,
    ) -> None:
        """
        Roblox avatarını gösterir.
        """

        username = username.strip()

        if not username:
            await interaction.response.send_message(
                embed=self._error(
                    "❌ Geçersiz Kullanıcı Adı",
                    (
                        "Roblox kullanıcı adı boş bırakılamaz."
                    ),
                ),
                ephemeral=True,
            )

            return

        await interaction.response.defer()

        try:
            user = (
                await self.roblox_service
                .get_user_by_username(
                    username,
                )
            )

            avatar = (
                await self.roblox_service
                .get_avatar(
                    user.id,
                )
            )

        except RobloxNotFoundError:
            await interaction.followup.send(
                embed=self._error(
                    "❌ Avatar Bulunamadı",
                    (
                        "Kullanıcı veya avatar "
                        "bulunamadı."
                    ),
                ),
            )

            return

        except RobloxAPIError:
            self.logger.exception(
                "Roblox avatar lookup failed: %s",
                username,
            )

            await interaction.followup.send(
                embed=self._error(
                    "❌ Roblox API Hatası",
                    (
                        "Avatar alınırken Roblox API "
                        "hatası oluştu."
                    ),
                ),
            )

            return

        except Exception:
            self.logger.exception(
                "Unexpected Roblox avatar error: %s",
                username,
            )

            await interaction.followup.send(
                embed=self._error(
                    "❌ Beklenmeyen Hata",
                    (
                        "Avatar alınırken beklenmeyen "
                        "bir hata oluştu."
                    ),
                ),
            )

            return

        embed = self._build_avatar_embed(
            user,
            avatar,
        )

        await interaction.followup.send(
            embed=embed,
        )

    # ========================================================
    # SEARCH
    # ========================================================

    @app_commands.command(
        name="search",
        description="Roblox kullanıcı adıyla kullanıcı bilgisi arar.",
    )
    @app_commands.describe(
        username="Aranacak Roblox kullanıcı adı.",
    )
    async def search(
        self,
        interaction: discord.Interaction,
        username: str,
    ) -> None:
        """
        User komutunun daha basit arama versiyonu.
        """

        await self.user(
            interaction,
            username,
        )

    # ========================================================
    # BATCH
    # ========================================================

    @app_commands.command(
        name="batch",
        description="Birden fazla Roblox User ID'sini sorgular.",
    )
    @app_commands.describe(
        user_ids=(
            "Virgül veya boşluk ile ayrılmış "
            "Roblox User ID'leri."
        ),
    )
    async def batch(
        self,
        interaction: discord.Interaction,
        user_ids: str,
    ) -> None:
        """
        Birden fazla Roblox kullanıcısını sorgular.
        """

        try:
            parsed_ids = self._parse_id_list(
                user_ids,
                limit=25,
            )

        except ValueError as error:
            await interaction.response.send_message(
                embed=self._error(
                    "❌ Geçersiz ID Listesi",
                    str(error),
                ),
                ephemeral=True,
            )

            return

        await interaction.response.defer()

        try:
            users = (
                await self.roblox_service
                .get_users(
                    parsed_ids,
                )
            )

        except RobloxAPIError:
            self.logger.exception(
                "Roblox batch user lookup failed.",
            )

            await interaction.followup.send(
                embed=self._error(
                    "❌ Roblox API Hatası",
                    (
                        "Kullanıcılar sorgulanırken "
                        "bir API hatası oluştu."
                    ),
                ),
            )

            return

        except Exception:
            self.logger.exception(
                "Unexpected Roblox batch lookup error.",
            )

            await interaction.followup.send(
                embed=self._error(
                    "❌ Beklenmeyen Hata",
                    (
                        "Kullanıcılar sorgulanırken "
                        "beklenmeyen bir hata oluştu."
                    ),
                ),
            )

            return

        embed = self._build_user_list_embed(
            users,
            title="👥 Roblox Users",
        )

        await interaction.followup.send(
            embed=embed,
        )

    # ========================================================
    # AVATARS
    # ========================================================

    @app_commands.command(
        name="avatars",
        description="Birden fazla Roblox avatarını sorgular.",
    )
    @app_commands.describe(
        user_ids=(
            "Virgül veya boşluk ile ayrılmış "
            "Roblox User ID'leri."
        ),
    )
    async def avatars(
        self,
        interaction: discord.Interaction,
        user_ids: str,
    ) -> None:
        """
        Birden fazla avatarı kontrollü şekilde alır.

        Not:
            RobloxService batch avatar desteğini
            kendi içinde yönetir.
        """

        try:
            parsed_ids = self._parse_id_list(
                user_ids,
                limit=25,
            )

        except ValueError as error:
            await interaction.response.send_message(
                embed=self._error(
                    "❌ Geçersiz ID Listesi",
                    str(error),
                ),
                ephemeral=True,
            )

            return

        await interaction.response.defer()

        try:
            avatars = (
                await self.roblox_service
                .get_avatars(
                    parsed_ids,
                )
            )

        except RobloxAPIError:
            self.logger.exception(
                "Roblox batch avatar lookup failed.",
            )

            await interaction.followup.send(
                embed=self._error(
                    "❌ Roblox API Hatası",
                    (
                        "Avatarlar alınırken "
                        "bir API hatası oluştu."
                    ),
                ),
            )

            return

        except Exception:
            self.logger.exception(
                "Unexpected Roblox batch avatar error.",
            )

            await interaction.followup.send(
                embed=self._error(
                    "❌ Beklenmeyen Hata",
                    (
                        "Avatarlar alınırken "
                        "beklenmeyen bir hata oluştu."
                    ),
                ),
            )

            return

        if not avatars:
            await interaction.followup.send(
                embed=self._info(
                    "ℹ️ Avatar Bulunamadı",
                    (
                        "Verilen ID'ler için avatar "
                        "bulunamadı."
                    ),
                ),
            )

            return

        user_ids_found = [
            avatar.user_id
            for avatar in avatars
        ]

        users = (
            await self.roblox_service
            .get_users(
                user_ids_found,
            )
        )

        user_map = {
            user.id: user
            for user in users
        }

        for avatar in avatars[:10]:
            user = user_map.get(
                avatar.user_id,
            )

            if user is None:
                continue

            embed = self._build_avatar_embed(
                user,
                avatar,
            )

            await interaction.followup.send(
                embed=embed,
            )

    # ========================================================
    # ERROR HANDLER
    # ========================================================

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """
        Roblox command hata yöneticisi.
        """

        self.logger.error(
            "Roblox command error: %s",
            error,
            exc_info=(
                type(error),
                error,
                error.__traceback__,
            ),
        )

        message = (
            "❌ Roblox komutu çalıştırılırken "
            "beklenmeyen bir hata oluştu."
        )

        if interaction.response.is_done():
            await interaction.followup.send(
                message,
                ephemeral=True,
            )

        else:
            await interaction.response.send_message(
                message,
                ephemeral=True,
            )


# ============================================================
# ADMIN COMMANDS
# ============================================================


class RobloxAdmin(
    app_commands.Group,
):
    """
    Roblox admin komutları.

    Bu grup sadece Administrator yetkisi
    olan kullanıcılar tarafından kullanılabilir.
    """

    def __init__(
        self,
        *,
        roblox_service: RobloxService,
        logger: logging.Logger,
    ) -> None:
        super().__init__(
            name="admin",
            description="Roblox yönetim komutları.",
            default_permissions=discord.Permissions(
                administrator=True,
            ),
        )

        self.roblox_service = roblox_service
        self.logger = logger

    # ========================================================
    # ADMIN HELPERS
    # ========================================================

    @staticmethod
    def _error(
        title: str,
        description: str,
    ) -> discord.Embed:
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def _user_embed(
        user: RobloxUser,
        avatar: RobloxAvatar | None = None,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=(
                f"🛡️ Roblox Admin Lookup"
            ),
            description=(
                f"**{user.display_name}**\n"
                f"@{user.name}"
            ),
            url=(
                "https://www.roblox.com/users/"
                f"{user.id}/profile"
            ),
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="User ID",
            value=f"`{user.id}`",
            inline=True,
        )

        embed.add_field(
            name="Username",
            value=f"`{user.name}`",
            inline=True,
        )

        embed.add_field(
            name="Display Name",
            value=f"`{user.display_name}`",
            inline=True,
        )

        embed.add_field(
            name="Created",
            value=(
                f"`{user.created}`"
                if user.created
                else "Unknown"
            ),
            inline=False,
        )

        embed.add_field(
            name="Status",
            value=(
                "🔴 Banned"
                if user.is_banned
                else "🟢 Active"
            ),
            inline=True,
        )

        if user.description:
            description = user.description

            if len(description) > 1024:
                description = (
                    description[:1021]
                    + "..."
                )

            embed.add_field(
                name="Description",
                value=description,
                inline=False,
            )

        if avatar:
            embed.set_thumbnail(
                url=avatar.image_url,
            )

        embed.set_footer(
            text="PAG Roblox Admin Tools",
        )

        return embed

    # ========================================================
    # ADMIN USER
    # ========================================================

    @app_commands.command(
        name="user",
        description="Admin: Roblox kullanıcı bilgilerini görüntüler.",
    )
    @app_commands.describe(
        username="Roblox kullanıcı adı.",
    )
    async def user(
        self,
        interaction: discord.Interaction,
        username: str,
    ) -> None:
        """
        Admin kullanıcı sorgusu.
        """

        await interaction.response.defer(
            ephemeral=True,
        )

        try:
            user = (
                await self.roblox_service
                .get_user_by_username(
                    username.strip(),
                )
            )

            avatar = (
                await self.roblox_service
                .get_avatar(
                    user.id,
                )
            )

        except RobloxNotFoundError:
            await interaction.followup.send(
                embed=self._error(
                    "❌ Kullanıcı Bulunamadı",
                    (
                        "Roblox kullanıcısı "
                        "bulunamadı."
                    ),
                ),
                ephemeral=True,
            )

            return

        except RobloxAPIError:
            self.logger.exception(
                "Admin Roblox lookup failed: %s",
                username,
            )

            await interaction.followup.send(
                embed=self._error(
                    "❌ Roblox API Hatası",
                    (
                        "Roblox API'si kullanıcı "
                        "bilgisi döndüremedi."
                    ),
                ),
                ephemeral=True,
            )

            return

        embed = self._user_embed(
            user,
            avatar,
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ========================================================
    # ADMIN AVATAR
    # ========================================================

    @app_commands.command(
        name="avatar",
        description="Admin: Roblox avatarı görüntüler.",
    )
    @app_commands.describe(
        user_id="Roblox User ID.",
    )
    async def avatar(
        self,
        interaction: discord.Interaction,
        user_id: int,
    ) -> None:
        """
        Admin avatar lookup.
        """

        if user_id <= 0:
            await interaction.response.send_message(
                embed=self._error(
                    "❌ Geçersiz User ID",
                    (
                        "User ID pozitif olmalıdır."
                    ),
                ),
                ephemeral=True,
            )

            return

        await interaction.response.defer(
            ephemeral=True,
        )

        try:
            user = (
                await self.roblox_service
                .get_user(
                    user_id,
                )
            )

            avatar = (
                await self.roblox_service
                .get_avatar(
                    user_id,
                )
            )

        except RobloxNotFoundError:
            await interaction.followup.send(
                embed=self._error(
                    "❌ Bulunamadı",
                    (
                        "Roblox kullanıcısı veya "
                        "avatarı bulunamadı."
                    ),
                ),
                ephemeral=True,
            )

            return

        except RobloxAPIError:
            self.logger.exception(
                "Admin Roblox avatar lookup failed: %s",
                user_id,
            )

            await interaction.followup.send(
                embed=self._error(
                    "❌ Roblox API Hatası",
                    (
                        "Avatar bilgisi alınamadı."
                    ),
                ),
                ephemeral=True,
            )

            return

        embed = self._user_embed(
            user,
            avatar,
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ========================================================
    # ADMIN BATCH
    # ========================================================

    @app_commands.command(
        name="batch",
        description="Admin: Birden fazla Roblox kullanıcısını sorgular.",
    )
    @app_commands.describe(
        user_ids=(
            "Virgül veya boşluk ile ayrılmış "
            "Roblox User ID'leri."
        ),
    )
    async def batch(
        self,
        interaction: discord.Interaction,
        user_ids: str,
    ) -> None:
        """
        Admin batch user lookup.
        """

        try:
            parsed_ids = Roblox._parse_id_list(
                user_ids,
                limit=100,
            )

        except ValueError as error:
            await interaction.response.send_message(
                embed=self._error(
                    "❌ Geçersiz ID Listesi",
                    str(error),
                ),
                ephemeral=True,
            )

            return

        await interaction.response.defer(
            ephemeral=True,
        )

        try:
            users = (
                await self.roblox_service
                .get_users(
                    parsed_ids,
                )
            )

        except RobloxAPIError:
            self.logger.exception(
                "Admin Roblox batch lookup failed.",
            )

            await interaction.followup.send(
                embed=self._error(
                    "❌ Roblox API Hatası",
                    (
                        "Toplu kullanıcı sorgusu "
                        "başarısız oldu."
                    ),
                ),
                ephemeral=True,
            )

            return

        lines: list[str] = []

        for user in users:
            status = (
                "🔴 Banned"
                if user.is_banned
                else "🟢 Active"
            )

            lines.append(
                f"{status} "
                f"`{user.id}` "
                f"**{user.display_name}** "
                f"(`{user.name}`)"
            )

        if not lines:
            description = (
                "Hiçbir kullanıcı bulunamadı."
            )

        else:
            description = "\n".join(
                lines,
            )

        if len(description) > 4000:
            description = (
                description[:3997]
                + "..."
            )

        embed = discord.Embed(
            title="🛡️ Roblox Admin Batch",
            description=description,
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )

        embed.set_footer(
            text=(
                f"{len(users)} kullanıcı bulundu."
            ),
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ========================================================
    # ADMIN AVATARS
    # ========================================================

    @app_commands.command(
        name="avatars",
        description="Admin: Toplu Roblox avatar sorgusu yapar.",
    )
    @app_commands.describe(
        user_ids=(
            "Virgül veya boşluk ile ayrılmış "
            "Roblox User ID'leri."
        ),
    )
    async def avatars(
        self,
        interaction: discord.Interaction,
        user_ids: str,
    ) -> None:
        """
        Admin batch avatar lookup.
        """

        try:
            parsed_ids = Roblox._parse_id_list(
                user_ids,
                limit=100,
            )

        except ValueError as error:
            await interaction.response.send_message(
                embed=self._error(
                    "❌ Geçersiz ID Listesi",
                    str(error),
                ),
                ephemeral=True,
            )

            return

        await interaction.response.defer(
            ephemeral=True,
        )

        try:
            avatars = (
                await self.roblox_service
                .get_avatars(
                    parsed_ids,
                )
            )

        except RobloxAPIError:
            self.logger.exception(
                "Admin Roblox batch avatar lookup failed.",
            )

            await interaction.followup.send(
                embed=self._error(
                    "❌ Roblox API Hatası",
                    (
                        "Toplu avatar sorgusu "
                        "başarısız oldu."
                    ),
                ),
                ephemeral=True,
            )

            return

        lines: list[str] = []

        for avatar in avatars:
            lines.append(
                f"🖼️ "
                f"`{avatar.user_id}`\n"
                f"{avatar.image_url}"
            )

        if not lines:
            description = (
                "Avatar bulunamadı."
            )

        else:
            description = "\n\n".join(
                lines,
            )

        if len(description) > 4000:
            description = (
                description[:3997]
                + "..."
            )

        embed = discord.Embed(
            title="🛡️ Roblox Admin Avatars",
            description=description,
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )

        embed.set_footer(
            text=(
                f"{len(avatars)} avatar bulundu."
            ),
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )


# ============================================================
# SETUP
# ============================================================


async def setup(
    bot: commands.Bot,
) -> None:
    """
    Roblox Cog setup.
    """

    roblox_cog = Roblox(
        bot,
        roblox_service=bot.roblox_service,
        logger=bot.logger,
    )

    await bot.add_cog(
        roblox_cog,
    )

    roblox_cog.__cog_app_commands__.append(
        roblox_cog.admin,
    )