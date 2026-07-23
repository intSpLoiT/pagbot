from __future__ import annotations

import logging
from typing import Iterable

import discord

from utils.errors import PAGError


# ============================================================
# ERRORS
# ============================================================


class DiscordServiceError(PAGError):
    """
    Discord Service kaynaklı hataların temel sınıfı.
    """


class DiscordMemberNotFoundError(DiscordServiceError):
    """
    Discord üyesi bulunamadığında kullanılır.
    """


class DiscordRoleNotFoundError(DiscordServiceError):
    """
    Discord rolü bulunamadığında kullanılır.
    """


class DiscordPermissionError(DiscordServiceError):
    """
    Botun Discord üzerinde gerekli yetkisi olmadığında kullanılır.
    """


# ============================================================
# DISCORD SERVICE
# ============================================================


class DiscordService:
    """
    PAG Bot Discord işlemleri için merkezi servis.

    Bu servis:
    - Member bulma
    - Rol kontrolü
    - Rol ekleme
    - Rol kaldırma
    - Rol adına göre arama
    - Kullanıcı durumu kontrolü

    gibi tekrar kullanılabilir Discord işlemlerini yönetir.

    Verify akışının kendisi burada bulunmaz.
    Verify sistemi bu servisi kullanır.
    """

    def __init__(
        self,
        logger: logging.Logger | None = None,
    ) -> None:
        self.logger = logger

    # ========================================================
    # MEMBER
    # ========================================================

    async def get_member(
        self,
        guild: discord.Guild,
        user_id: int,
    ) -> discord.Member:
        """
        Guild içerisindeki bir üyeyi bulur.

        Önce cache kullanılır.
        Cache'de yoksa Discord API'ye istek atılır.
        """

        member = guild.get_member(
            user_id,
        )

        if member is not None:
            return member

        try:
            return await guild.fetch_member(
                user_id,
            )

        except discord.NotFound as error:
            raise DiscordMemberNotFoundError(
                f"Member not found: {user_id}"
            ) from error

        except discord.HTTPException as error:
            self._log(
                logging.ERROR,
                "Failed to fetch member %s: %s",
                user_id,
                error,
            )

            raise DiscordServiceError(
                "Failed to fetch Discord member."
            ) from error

    # ========================================================
    # ROLE LOOKUP
    # ========================================================

    @staticmethod
    def get_role(
        guild: discord.Guild,
        role_id: int,
    ) -> discord.Role | None:
        """
        ID üzerinden rol bulur.

        Bu işlem cache üzerinden yapılır.
        Gereksiz API isteği atılmaz.
        """

        return guild.get_role(
            role_id,
        )

    @staticmethod
    def find_role(
        guild: discord.Guild,
        role_name: str,
        *,
        case_sensitive: bool = False,
    ) -> discord.Role | None:
        """
        Rol adına göre rol bulur.
        """

        if not case_sensitive:
            target_name = role_name.casefold()

            return next(
                (
                    role
                    for role in guild.roles
                    if role.name.casefold()
                    == target_name
                ),
                None,
            )

        return next(
            (
                role
                for role in guild.roles
                if role.name == role_name
            ),
            None,
        )

    # ========================================================
    # ROLE NAME CHECK
    # ========================================================

    @staticmethod
    def has_role_containing(
        member: discord.Member,
        text: str,
    ) -> bool:
        """
        Üyenin rollerinden birinin adında belirli bir
        metin geçip geçmediğini kontrol eder.

        Örnek:

            text = "ally"

        Eşleşen roller:

            Ally
            PAG Ally
            ally team
            ALLY MEMBER

        Büyük/küçük harf fark etmez.
        """

        search_text = text.strip().casefold()

        if not search_text:
            return False

        return any(
            search_text in role.name.casefold()
            for role in member.roles
        )

    # ========================================================
    # MULTIPLE ROLE TEXT CHECK
    # ========================================================

    @staticmethod
    def has_any_role_containing(
        member: discord.Member,
        texts: Iterable[str],
    ) -> bool:
        """
        Birden fazla metin için rol kontrolü yapar.

        Örnek:

            ("ally", "enemy", "partner")

        Bunlardan herhangi biri bir rol adında geçerse
        True döner.
        """

        search_texts = tuple(
            text.strip().casefold()
            for text in texts
            if text.strip()
        )

        if not search_texts:
            return False

        return any(
            search_text in role.name.casefold()
            for role in member.roles
            for search_text in search_texts
        )

    # ========================================================
    # EXACT ROLE CHECK
    # ========================================================

    @staticmethod
    def has_role(
        member: discord.Member,
        role_id: int,
    ) -> bool:
        """
        ID üzerinden rol kontrolü yapar.
        """

        return any(
            role.id == role_id
            for role in member.roles
        )

    # ========================================================
    # ADD ROLE
    # ========================================================

    async def add_role(
        self,
        member: discord.Member,
        role: discord.Role,
        *,
        reason: str | None = None,
    ) -> bool:
        """
        Üyeye rol verir.

        Zaten role sahipse tekrar API isteği atmaz.
        """

        if role in member.roles:
            return False

        try:
            await member.add_roles(
                role,
                reason=reason,
            )

            self._log(
                logging.INFO,
                "Role '%s' added to member %s.",
                role.name,
                member.id,
            )

            return True

        except discord.Forbidden as error:
            self._log(
                logging.ERROR,
                "Missing permission to add role '%s'.",
                role.name,
            )

            raise DiscordPermissionError(
                "Bot does not have permission to add this role."
            ) from error

        except discord.HTTPException as error:
            self._log(
                logging.ERROR,
                "Failed to add role '%s' to member %s: %s",
                role.name,
                member.id,
                error,
            )

            raise DiscordServiceError(
                "Failed to add Discord role."
            ) from error

    # ========================================================
    # REMOVE ROLE
    # ========================================================

    async def remove_role(
        self,
        member: discord.Member,
        role: discord.Role,
        *,
        reason: str | None = None,
    ) -> bool:
        """
        Üyeden rol kaldırır.

        Üyede rol yoksa gereksiz API isteği atmaz.
        """

        if role not in member.roles:
            return False

        try:
            await member.remove_roles(
                role,
                reason=reason,
            )

            self._log(
                logging.INFO,
                "Role '%s' removed from member %s.",
                role.name,
                member.id,
            )

            return True

        except discord.Forbidden as error:
            self._log(
                logging.ERROR,
                "Missing permission to remove role '%s'.",
                role.name,
            )

            raise DiscordPermissionError(
                "Bot does not have permission to remove this role."
            ) from error

        except discord.HTTPException as error:
            self._log(
                logging.ERROR,
                "Failed to remove role '%s' from member %s: %s",
                role.name,
                member.id,
                error,
            )

            raise DiscordServiceError(
                "Failed to remove Discord role."
            ) from error

    # ========================================================
    # ROLE VALIDATION
    # ========================================================

    @staticmethod
    def can_manage_role(
        guild: discord.Guild,
        role: discord.Role,
    ) -> bool:
        """
        Botun rolü yönetip yönetemeyeceğini kontrol eder.

        Discord'da bot yalnızca kendi en yüksek rolünün
        altında bulunan rolleri yönetebilir.
        """

        me = guild.me

        if me is None:
            return False

        if not me.guild_permissions.manage_roles:
            return False

        return role < me.top_role

    # ========================================================
    # BOT ROLE CHECK
    # ========================================================

    @staticmethod
    def validate_role_management(
        guild: discord.Guild,
        role: discord.Role,
    ) -> None:
        """
        Rol yönetimi için gerekli şartları kontrol eder.
        """

        me = guild.me

        if me is None:
            raise DiscordPermissionError(
                "Bot member information is unavailable."
            )

        if not me.guild_permissions.manage_roles:
            raise DiscordPermissionError(
                "Bot does not have Manage Roles permission."
            )

        if role >= me.top_role:
            raise DiscordPermissionError(
                "The target role is above the bot's highest role."
            )

    # ========================================================
    # VERIFY BLOCK CHECK
    # ========================================================

    @staticmethod
    def is_blocked_from_verification(
        member: discord.Member,
        blocked_role_texts: Iterable[str] = (
            "ally",
        ),
    ) -> bool:
        """
        Üyenin verify işleminden engellenip engellenmeyeceğini
        kontrol eder.

        Varsayılan olarak rol adında 'ally' geçen üyeleri
        engeller.

        Örnek:

            Ally
            PAG Ally
            Ally Team

        Hepsi engellenir.
        """

        return DiscordService.has_any_role_containing(
            member,
            blocked_role_texts,
        )

    # ========================================================
    # LOGGER
    # ========================================================

    def _log(
        self,
        level: int,
        message: str,
        *args: object,
    ) -> None:
        """
        Logger varsa loglar.
        """

        if self.logger is not None:
            self.logger.log(
                level,
                message,
                *args,
            )