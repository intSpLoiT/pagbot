from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Iterable

import httpx

from utils.errors import PAGError


# ============================================================
# ERRORS
# ============================================================


class RobloxServiceError(PAGError):
    """Roblox API işlemleri sırasında oluşan hatalar."""


class RobloxNotFoundError(RobloxServiceError):
    """Roblox kullanıcısı bulunamadığında oluşur."""


class RobloxAPIError(RobloxServiceError):
    """Roblox API başarısız olduğunda oluşur."""


# ============================================================
# DATA MODELS
# ============================================================


@dataclass(slots=True, frozen=True)
class RobloxUser:
    """
    Roblox kullanıcı bilgileri.
    """

    id: int
    name: str
    display_name: str
    description: str
    created: str
    is_banned: bool


@dataclass(slots=True, frozen=True)
class RobloxAvatar:
    """
    Roblox avatar bilgileri.
    """

    user_id: int
    image_url: str


# ============================================================
# CACHE
# ============================================================


@dataclass(slots=True)
class _CacheEntry:
    """
    Basit TTL cache entry.
    """

    value: Any
    expires_at: float


class TTLCache:
    """
    Küçük ve hafif memory cache.

    Redis gibi harici bir sistem kullanmıyoruz.
    PAG Bot için bu yeterli.
    """

    def __init__(
        self,
        ttl: int = 300,
        max_size: int = 1000,
    ) -> None:
        self.ttl = ttl
        self.max_size = max_size

        self._cache: dict[Any, _CacheEntry] = {}

    def get(
        self,
        key: Any,
    ) -> Any | None:
        entry = self._cache.get(key)

        if entry is None:
            return None

        if time.monotonic() >= entry.expires_at:
            self._cache.pop(key, None)
            return None

        return entry.value

    def set(
        self,
        key: Any,
        value: Any,
    ) -> None:
        if len(self._cache) >= self.max_size:
            self._remove_expired()

        if len(self._cache) >= self.max_size:
            oldest_key = next(
                iter(self._cache)
            )

            self._cache.pop(
                oldest_key,
                None,
            )

        self._cache[key] = _CacheEntry(
            value=value,
            expires_at=(
                time.monotonic() + self.ttl
            ),
        )

    def delete(
        self,
        key: Any,
    ) -> None:
        self._cache.pop(
            key,
            None,
        )

    def clear(self) -> None:
        self._cache.clear()

    def _remove_expired(self) -> None:
        now = time.monotonic()

        expired_keys = [
            key
            for key, entry in self._cache.items()
            if now >= entry.expires_at
        ]

        for key in expired_keys:
            self._cache.pop(
                key,
                None,
            )


# ============================================================
# ROBLOX SERVICE
# ============================================================


class RobloxService:
    """
    PAG Bot Roblox API Service.

    Tasarım hedefleri:

    - Tek HTTP client
    - Connection pooling
    - Async işlemler
    - Kontrollü paralel istekler
    - TTL cache
    - Batch user sorguları
    - Avatar batch sorguları
    - Retry sistemi
    """

    USERS_API = (
        "https://users.roblox.com/v1"
    )

    AVATAR_API = (
        "https://thumbnails.roblox.com/v1"
    )

    DEFAULT_TIMEOUT = 10.0

    MAX_RETRIES = 3

    RETRY_DELAY = 0.5

    MAX_CONCURRENT_REQUESTS = 10

    USER_CACHE_TTL = 600

    AVATAR_CACHE_TTL = 300

    def __init__(
        self,
        logger: logging.Logger | None = None,
    ) -> None:

        self.logger = logger

        self._client: httpx.AsyncClient | None = None

        self._request_semaphore = asyncio.Semaphore(
            self.MAX_CONCURRENT_REQUESTS
        )

        self._user_cache = TTLCache(
            ttl=self.USER_CACHE_TTL,
            max_size=2000,
        )

        self._avatar_cache = TTLCache(
            ttl=self.AVATAR_CACHE_TTL,
            max_size=2000,
        )

        self._started = False

    # ========================================================
    # START
    # ========================================================

    async def start(self) -> None:
        """
        HTTP client'ı başlatır.

        Service yaşam döngüsü boyunca tek client kullanılır.
        """

        if self._client is not None:
            return

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=5.0,
                read=self.DEFAULT_TIMEOUT,
                write=self.DEFAULT_TIMEOUT,
                pool=5.0,
            ),
            limits=httpx.Limits(
                max_connections=30,
                max_keepalive_connections=15,
            ),
            headers={
                "User-Agent": "PAG-Bot/1.0",
                "Accept": "application/json",
            },
            follow_redirects=True,
        )

        self._started = True

        self._log(
            logging.INFO,
            "Roblox service started.",
        )

    # ========================================================
    # CLOSE
    # ========================================================

    async def close(self) -> None:
        """
        HTTP client'ı kapatır.
        """

        if self._client is None:
            return

        await self._client.aclose()

        self._client = None

        self._started = False

        self._user_cache.clear()
        self._avatar_cache.clear()

        self._log(
            logging.INFO,
            "Roblox service closed.",
        )

    # ========================================================
    # GET USER BY USERNAME
    # ========================================================

    async def get_user_by_username(
        self,
        username: str,
    ) -> RobloxUser:
        """
        Roblox username üzerinden kullanıcı bilgisi alır.
        """

        username = username.strip()

        if not username:
            raise RobloxNotFoundError(
                "Roblox username cannot be empty."
            )

        cache_key = (
            "username",
            username.lower(),
        )

        cached = self._user_cache.get(
            cache_key,
        )

        if cached is not None:
            return cached

        response = await self._request(
            method="POST",
            url=(
                f"{self.USERS_API}"
                "/usernames/users"
            ),
            json={
                "usernames": [
                    username,
                ],
                "excludeBannedUsers": False,
            },
        )

        users = response.get(
            "data",
            [],
        )

        if not users:
            raise RobloxNotFoundError(
                f"Roblox user not found: {username}"
            )

        user_data = users[0]

        user = await self.get_user(
            int(user_data["id"]),
        )

        self._user_cache.set(
            cache_key,
            user,
        )

        return user

    # ========================================================
    # GET USER BY ID
    # ========================================================

    async def get_user(
        self,
        user_id: int,
    ) -> RobloxUser:
        """
        Roblox user ID üzerinden kullanıcı bilgisi alır.
        """

        if user_id <= 0:
            raise ValueError(
                "Roblox user ID must be positive."
            )

        cache_key = (
            "user",
            user_id,
        )

        cached = self._user_cache.get(
            cache_key,
        )

        if cached is not None:
            return cached

        response = await self._request(
            method="GET",
            url=(
                f"{self.USERS_API}"
                f"/users/{user_id}"
            ),
        )

        user = self._parse_user(
            response,
        )

        self._user_cache.set(
            cache_key,
            user,
        )

        return user

    # ========================================================
    # GET MULTIPLE USERS
    # ========================================================

    async def get_users(
        self,
        user_ids: Iterable[int],
    ) -> list[RobloxUser]:
        """
        Birden fazla kullanıcıyı kontrollü paralel şekilde alır.

        Cache'de olan kullanıcılar için API isteği atılmaz.
        """

        unique_ids = list(
            dict.fromkeys(
                int(user_id)
                for user_id in user_ids
            )
        )

        if not unique_ids:
            return []

        users: list[RobloxUser] = []

        missing_ids: list[int] = []

        for user_id in unique_ids:
            cached = self._user_cache.get(
                (
                    "user",
                    user_id,
                )
            )

            if cached is not None:
                users.append(cached)

            else:
                missing_ids.append(user_id)

        if missing_ids:

            results = await asyncio.gather(
                *(
                    self.get_user(user_id)
                    for user_id in missing_ids
                ),
                return_exceptions=True,
            )

            for result in results:

                if isinstance(
                    result,
                    RobloxUser,
                ):
                    users.append(result)

                else:
                    self._log(
                        logging.WARNING,
                        "Failed to fetch Roblox user: %s",
                        result,
                    )

        return users

    # ========================================================
    # GET AVATAR
    # ========================================================

    async def get_avatar(
        self,
        user_id: int,
        *,
        size: str = "420x420",
        format: str = "Png",
    ) -> RobloxAvatar:
        """
        Bir Roblox kullanıcısının avatar thumbnail'ını alır.
        """

        if user_id <= 0:
            raise ValueError(
                "Roblox user ID must be positive."
            )

        cache_key = (
            user_id,
            size,
            format,
        )

        cached = self._avatar_cache.get(
            cache_key,
        )

        if cached is not None:
            return cached

        response = await self._request(
            method="GET",
            url=(
                f"{self.AVATAR_API}"
                "/users/avatar"
            ),
            params={
                "userIds": str(user_id),
                "size": size,
                "format": format,
                "isCircular": "false",
            },
        )

        data = response.get(
            "data",
            [],
        )

        if not data:
            raise RobloxNotFoundError(
                f"Avatar not found: {user_id}"
            )

        avatar_data = data[0]

        image_url = avatar_data.get(
            "imageUrl",
        )

        if not image_url:
            raise RobloxNotFoundError(
                f"Avatar URL not found: {user_id}"
            )

        avatar = RobloxAvatar(
            user_id=user_id,
            image_url=image_url,
        )

        self._avatar_cache.set(
            cache_key,
            avatar,
        )

        return avatar

    # ========================================================
    # GET MULTIPLE AVATARS
    # ========================================================

    async def get_avatars(
        self,
        user_ids: Iterable[int],
        *,
        size: str = "420x420",
        format: str = "Png",
    ) -> list[RobloxAvatar]:
        """
        Birden fazla avatarı aynı anda alır.

        Önemli:
        Roblox thumbnail API'si batch desteklediği için
        mümkün olduğunda tek API isteği kullanılır.
        """

        unique_ids = list(
            dict.fromkeys(
                int(user_id)
                for user_id in user_ids
            )
        )

        if not unique_ids:
            return []

        avatars: list[RobloxAvatar] = []

        missing_ids: list[int] = []

        for user_id in unique_ids:

            cached = self._avatar_cache.get(
                (
                    user_id,
                    size,
                    format,
                )
            )

            if cached is not None:
                avatars.append(cached)

            else:
                missing_ids.append(user_id)

        if not missing_ids:
            return avatars

        # Roblox API batch limitlerine takılmamak için
        # ID'leri parçalara bölüyoruz.
        chunks = self._chunks(
            missing_ids,
            100,
        )

        results = await asyncio.gather(
            *(
                self._get_avatar_batch(
                    chunk,
                    size=size,
                    format=format,
                )
                for chunk in chunks
            ),
            return_exceptions=True,
        )

        for result in results:

            if isinstance(
                result,
                list,
            ):
                avatars.extend(result)

            else:
                self._log(
                    logging.WARNING,
                    "Failed to fetch avatar batch: %s",
                    result,
                )

        return avatars

    # ========================================================
    # AVATAR BATCH
    # ========================================================

    async def _get_avatar_batch(
        self,
        user_ids: list[int],
        *,
        size: str,
        format: str,
    ) -> list[RobloxAvatar]:
        """
        Avatar batch isteği.
        """

        response = await self._request(
            method="GET",
            url=(
                f"{self.AVATAR_API}"
                "/users/avatar"
            ),
            params=[
                (
                    "userIds",
                    str(user_id),
                )
                for user_id in user_ids
            ]
            + [
                (
                    "size",
                    size,
                ),
                (
                    "format",
                    format,
                ),
                (
                    "isCircular",
                    "false",
                ),
            ],
        )

        avatars: list[RobloxAvatar] = []

        for item in response.get(
            "data",
            [],
        ):

            image_url = item.get(
                "imageUrl",
            )

            if not image_url:
                continue

            avatar = RobloxAvatar(
                user_id=int(
                    item["targetId"]
                ),
                image_url=image_url,
            )

            self._avatar_cache.set(
                (
                    avatar.user_id,
                    size,
                    format,
                ),
                avatar,
            )

            avatars.append(avatar)

        return avatars

    # ========================================================
    # HTTP REQUEST
    # ========================================================

    async def _request(
        self,
        *,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Kontrollü HTTP request sistemi.

        Özellikler:
        - Semaphore
        - Retry
        - Timeout
        - HTTP status kontrolü
        - JSON kontrolü
        """

        client = self._get_client()

        async with self._request_semaphore:

            for attempt in range(
                1,
                self.MAX_RETRIES + 1,
            ):

                try:

                    response = await client.request(
                        method,
                        url,
                        **kwargs,
                    )

                    if response.status_code == 404:
                        raise RobloxNotFoundError(
                            "Roblox resource not found."
                        )

                    if response.status_code == 429:

                        if attempt >= self.MAX_RETRIES:
                            raise RobloxAPIError(
                                "Roblox API rate limit reached."
                            )

                        await asyncio.sleep(
                            self.RETRY_DELAY
                            * attempt
                        )

                        continue

                    response.raise_for_status()

                    try:
                        return response.json()

                    except ValueError as error:
                        raise RobloxAPIError(
                            "Roblox API returned invalid JSON."
                        ) from error

                except RobloxNotFoundError:
                    raise

                except RobloxAPIError:
                    raise

                except (
                    httpx.TimeoutException,
                    httpx.NetworkError,
                    httpx.RemoteProtocolError,
                ) as error:

                    if attempt >= self.MAX_RETRIES:
                        raise RobloxAPIError(
                            "Roblox API request failed after retries."
                        ) from error

                    await asyncio.sleep(
                        self.RETRY_DELAY
                        * attempt
                    )

                except httpx.HTTPStatusError as error:

                    status_code = (
                        error.response.status_code
                    )

                    if (
                        status_code >= 500
                        and attempt < self.MAX_RETRIES
                    ):
                        await asyncio.sleep(
                            self.RETRY_DELAY
                            * attempt
                        )

                        continue

                    raise RobloxAPIError(
                        f"Roblox API returned HTTP "
                        f"{status_code}."
                    ) from error

                except Exception as error:

                    self._log(
                        logging.ERROR,
                        "Unexpected Roblox API error: %s",
                        error,
                    )

                    raise RobloxAPIError(
                        "Unexpected Roblox API error."
                    ) from error

        raise RobloxAPIError(
            "Roblox API request failed."
        )

    # ========================================================
    # PARSE USER
    # ========================================================

    @staticmethod
    def _parse_user(
        data: dict[str, Any],
    ) -> RobloxUser:
        """
        API response'unu RobloxUser modeline çevirir.
        """

        try:

            return RobloxUser(
                id=int(
                    data["id"]
                ),
                name=str(
                    data["name"]
                ),
                display_name=str(
                    data["displayName"]
                ),
                description=str(
                    data.get(
                        "description",
                        "",
                    )
                ),
                created=str(
                    data.get(
                        "created",
                        "",
                    )
                ),
                is_banned=bool(
                    data.get(
                        "isBanned",
                        False,
                    )
                ),
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ) as error:

            raise RobloxAPIError(
                "Invalid Roblox user response."
            ) from error

    # ========================================================
    # CLIENT CHECK
    # ========================================================

    def _get_client(
        self,
    ) -> httpx.AsyncClient:
        """
        Aktif HTTP client'ı döndürür.
        """

        if (
            self._client is None
            or not self._started
        ):
            raise RuntimeError(
                "RobloxService is not started. "
                "Call 'await service.start()' first."
            )

        return self._client

    # ========================================================
    # CHUNKS
    # ========================================================

    @staticmethod
    def _chunks(
        items: list[int],
        size: int,
    ) -> list[list[int]]:
        """
        Listeyi küçük parçalara böler.
        """

        return [
            items[index:index + size]
            for index in range(
                0,
                len(items),
                size,
            )
        ]

    # ========================================================
    # LOGGER
    # ========================================================

    def _log(
        self,
        level: int,
        message: str,
        *args: Any,
    ) -> None:

        if self.logger is not None:
            self.logger.log(
                level,
                message,
                *args,
            )