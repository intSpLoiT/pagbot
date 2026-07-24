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
    """
    Roblox API işlemleri sırasında oluşan temel hata.
    """


class RobloxNotFoundError(RobloxServiceError):
    """
    Roblox kullanıcısı veya kaynağı bulunamadığında oluşur.
    """


class RobloxAPIError(RobloxServiceError):
    """
    Roblox API isteği başarısız olduğunda oluşur.
    """


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
    Roblox avatar thumbnail bilgileri.
    """

    user_id: int
    image_url: str


# ============================================================
# CACHE
# ============================================================


@dataclass(slots=True)
class _CacheEntry:
    """
    TTL cache kaydı.
    """

    value: Any
    expires_at: float


class TTLCache:
    """
    Küçük, hafif ve process-local TTL cache.

    Harici Redis veya başka bir cache sistemi
    kullanılmaz.

    PAG Bot için:

        username -> RobloxUser
        user_id  -> RobloxUser
        avatar   -> RobloxAvatar

    gibi kısa süreli veriler için yeterlidir.
    """

    def __init__(
        self,
        ttl: int = 300,
        max_size: int = 1000,
    ) -> None:

        self.ttl = ttl
        self.max_size = max_size

        self._cache: dict[
            Any,
            _CacheEntry,
        ] = {}

    # ========================================================
    # GET
    # ========================================================

    def get(
        self,
        key: Any,
    ) -> Any | None:

        entry = self._cache.get(
            key,
        )

        if entry is None:
            return None

        if time.monotonic() >= entry.expires_at:

            self._cache.pop(
                key,
                None,
            )

            return None

        return entry.value

    # ========================================================
    # SET
    # ========================================================

    def set(
        self,
        key: Any,
        value: Any,
    ) -> None:

        self._remove_expired()

        if (
            key not in self._cache
            and len(self._cache) >= self.max_size
        ):

            oldest_key = next(
                iter(
                    self._cache,
                ),
            )

            self._cache.pop(
                oldest_key,
                None,
            )

        self._cache[key] = _CacheEntry(
            value=value,
            expires_at=(
                time.monotonic()
                + self.ttl
            ),
        )

    # ========================================================
    # DELETE
    # ========================================================

    def delete(
        self,
        key: Any,
    ) -> None:

        self._cache.pop(
            key,
            None,
        )

    # ========================================================
    # CLEAR
    # ========================================================

    def clear(
        self,
    ) -> None:

        self._cache.clear()

    # ========================================================
    # REMOVE EXPIRED
    # ========================================================

    def _remove_expired(
        self,
    ) -> None:

        now = time.monotonic()

        expired_keys = [
            key
            for key, entry
            in self._cache.items()
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

        - Tek AsyncClient
        - Connection pooling
        - Async HTTP
        - Kontrollü concurrency
        - TTL cache
        - Username lookup
        - User ID lookup
        - Batch user lookup
        - Avatar lookup
        - Batch avatar lookup
        - Retry sistemi
        - Timeout kontrolü
        - Top10Service uyumluluğu

    PUBLIC API:

        start()
        close()

        get_user_by_username()
        get_user()
        get_users()

        get_avatar()
        get_avatars()

        get_profile()

    Mevcut public metodlar korunmuştur.
    """

    # ========================================================
    # API ENDPOINTS
    # ========================================================

    USERS_API = (
        "https://users.roblox.com/v1"
    )

    AVATAR_API = (
        "https://thumbnails.roblox.com/v1"
    )

    # ========================================================
    # HTTP SETTINGS
    # ========================================================

    DEFAULT_TIMEOUT = 10.0

    CONNECT_TIMEOUT = 5.0

    POOL_TIMEOUT = 5.0

    MAX_RETRIES = 3

    RETRY_DELAY = 0.5

    # ========================================================
    # CONCURRENCY
    # ========================================================

    MAX_CONCURRENT_REQUESTS = 10

    # ========================================================
    # CACHE
    # ========================================================

    USER_CACHE_TTL = 600

    AVATAR_CACHE_TTL = 300

    USER_CACHE_SIZE = 2000

    AVATAR_CACHE_SIZE = 2000

    # ========================================================
    # CONSTRUCTOR
    # ========================================================

    def __init__(
        self,
        logger: logging.Logger | None = None,
    ) -> None:

        self.logger = logger

        # ----------------------------------------------------
        # HTTP CLIENT
        # ----------------------------------------------------

        self._client: (
            httpx.AsyncClient | None
        ) = None

        # ----------------------------------------------------
        # SERVICE STATE
        # ----------------------------------------------------

        self._started = False

        # ----------------------------------------------------
        # START LOCK
        # ----------------------------------------------------

        self._start_lock = asyncio.Lock()

        # ----------------------------------------------------
        # CLOSE LOCK
        # ----------------------------------------------------

        self._close_lock = asyncio.Lock()

        # ----------------------------------------------------
        # REQUEST SEMAPHORE
        # ----------------------------------------------------

        self._request_semaphore = (
            asyncio.Semaphore(
                self.MAX_CONCURRENT_REQUESTS,
            )
        )

        # ----------------------------------------------------
        # USER CACHE
        # ----------------------------------------------------

        self._user_cache = TTLCache(
            ttl=self.USER_CACHE_TTL,
            max_size=self.USER_CACHE_SIZE,
        )

        # ----------------------------------------------------
        # AVATAR CACHE
        # ----------------------------------------------------

        self._avatar_cache = TTLCache(
            ttl=self.AVATAR_CACHE_TTL,
            max_size=self.AVATAR_CACHE_SIZE,
        )

    # ========================================================
    # START
    # ========================================================

    async def start(
        self,
    ) -> None:
        """
        HTTP client'ı başlatır.

        Aynı service birden fazla kez start edilse
        bile yeni client oluşturmaz.
        """

        if (
            self._client is not None
            and self._started
        ):
            return

        async with self._start_lock:

            if (
                self._client is not None
                and self._started
            ):
                return

            self._client = (
                httpx.AsyncClient(
                    timeout=httpx.Timeout(
                        connect=(
                            self.CONNECT_TIMEOUT
                        ),
                        read=(
                            self.DEFAULT_TIMEOUT
                        ),
                        write=(
                            self.DEFAULT_TIMEOUT
                        ),
                        pool=(
                            self.POOL_TIMEOUT
                        ),
                    ),
                    limits=httpx.Limits(
                        max_connections=30,
                        max_keepalive_connections=15,
                    ),
                    headers={
                        "User-Agent": (
                            "PAG-Bot/1.0"
                        ),
                        "Accept": (
                            "application/json"
                        ),
                    },
                    follow_redirects=True,
                )
            )

            self._started = True

            self._log(
                logging.INFO,
                "Roblox service started.",
            )

    # ========================================================
    # CLOSE
    # ========================================================

    async def close(
        self,
    ) -> None:
        """
        HTTP client'ı güvenli şekilde kapatır.
        """

        async with self._close_lock:

            client = self._client

            if client is None:

                self._started = False

                return

            self._client = None

            self._started = False

            try:

                await client.aclose()

            except Exception as error:

                self._log(
                    logging.ERROR,
                    (
                        "Failed to close Roblox "
                        "HTTP client: %s"
                    ),
                    error,
                )

            finally:

                self._user_cache.clear()

                self._avatar_cache.clear()

                self._log(
                    logging.INFO,
                    "Roblox service closed.",
                )

    # ========================================================
    # GET PROFILE
    # ========================================================

    async def get_profile(
        self,
        username: str,
    ) -> dict[str, Any]:
        """
        Top10Service uyumluluk metodu.

        Username üzerinden:

            - username
            - display name
            - user ID
            - avatar URL
            - profile URL

        bilgilerini tek dictionary olarak döndürür.

        Dönüş:

            {
                "username": str,
                "display_name": str,
                "user_id": int,
                "avatar_url": str | None,
                "profile_url": str,
            }

        Kullanıcı bilgisi zorunludur.

        Avatar bilgisi opsiyoneldir.

        Böylece avatar API geçici olarak başarısız
        olsa bile kullanıcı işlemi devam edebilir.
        """

        if not isinstance(
            username,
            str,
        ):

            raise RobloxNotFoundError(
                "Roblox username must be a string.",
            )

        username = username.strip()

        if not username:

            raise RobloxNotFoundError(
                "Roblox username cannot be empty.",
            )

        # ----------------------------------------------------
        # USER
        # ----------------------------------------------------

        user = await (
            self.get_user_by_username(
                username,
            )
        )

        # ----------------------------------------------------
        # AVATAR
        # ----------------------------------------------------

        avatar_url: str | None = None

        try:

            avatar = await (
                self.get_avatar(
                    user.id,
                )
            )

            avatar_url = avatar.image_url

        except (
            RobloxNotFoundError,
            RobloxAPIError,
        ) as error:

            self._log(
                logging.WARNING,
                (
                    "Avatar lookup failed for "
                    "Roblox user %s: %s"
                ),
                user.id,
                error,
            )

        # ----------------------------------------------------
        # PROFILE URL
        # ----------------------------------------------------

        profile_url = (
            "https://www.roblox.com/users/"
            f"{user.id}/profile"
        )

        return {
            "username": user.name,
            "display_name": user.display_name,
            "user_id": user.id,
            "avatar_url": avatar_url,
            "profile_url": profile_url,
        }

    # ========================================================
    # GET USER BY USERNAME
    # ========================================================

    async def get_user_by_username(
        self,
        username: str,
    ) -> RobloxUser:
        """
        Roblox username üzerinden kullanıcı bulur.

        Akış:

            username
                ↓
            cache
                ↓
            Roblox username API
                ↓
            user ID
                ↓
            get_user()
                ↓
            RobloxUser
        """

        if not isinstance(
            username,
            str,
        ):

            raise RobloxNotFoundError(
                "Roblox username must be a string.",
            )

        username = username.strip()

        if not username:

            raise RobloxNotFoundError(
                "Roblox username cannot be empty.",
            )

        cache_key = (
            "username",
            username.lower(),
        )

        cached = self._user_cache.get(
            cache_key,
        )

        if isinstance(
            cached,
            RobloxUser,
        ):

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
                (
                    "Roblox user not found: "
                    f"{username}"
                ),
            )

        user_data = users[0]

        try:

            user_id = int(
                user_data["id"],
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ) as error:

            raise RobloxAPIError(
                (
                    "Roblox username API "
                    "returned invalid user ID."
                ),
            ) from error

        user = await self.get_user(
            user_id,
        )

        # ----------------------------------------------------
        # CACHE BOTH WAYS
        # ----------------------------------------------------

        self._user_cache.set(
            cache_key,
            user,
        )

        self._user_cache.set(
            (
                "user",
                user.id,
            ),
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

        try:

            user_id = int(
                user_id,
            )

        except (
            TypeError,
            ValueError,
        ) as error:

            raise ValueError(
                "Roblox user ID must be an integer.",
            ) from error

        if user_id <= 0:

            raise ValueError(
                "Roblox user ID must be positive.",
            )

        cache_key = (
            "user",
            user_id,
        )

        cached = self._user_cache.get(
            cache_key,
        )

        if isinstance(
            cached,
            RobloxUser,
        ):

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

        self._user_cache.set(
            (
                "username",
                user.name.lower(),
            ),
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
        Birden fazla Roblox kullanıcısını alır.

        Cache'de olanlar için API isteği yapılmaz.

        Cache'de olmayanlar kontrollü paralel
        şekilde alınır.
        """

        unique_ids: list[int] = []

        seen_ids: set[int] = set()

        for raw_user_id in user_ids:

            try:

                user_id = int(
                    raw_user_id,
                )

            except (
                TypeError,
                ValueError,
            ):

                self._log(
                    logging.WARNING,
                    (
                        "Ignoring invalid Roblox "
                        "user ID: %r"
                    ),
                    raw_user_id,
                )

                continue

            if user_id <= 0:

                self._log(
                    logging.WARNING,
                    (
                        "Ignoring non-positive Roblox "
                        "user ID: %s"
                    ),
                    user_id,
                )

                continue

            if user_id in seen_ids:

                continue

            seen_ids.add(
                user_id,
            )

            unique_ids.append(
                user_id,
            )

        if not unique_ids:

            return []

        users: list[RobloxUser] = []

        missing_ids: list[int] = []

        # ----------------------------------------------------
        # CACHE
        # ----------------------------------------------------

        for user_id in unique_ids:

            cached = self._user_cache.get(
                (
                    "user",
                    user_id,
                ),
            )

            if isinstance(
                cached,
                RobloxUser,
            ):

                users.append(
                    cached,
                )

            else:

                missing_ids.append(
                    user_id,
                )

        # ----------------------------------------------------
        # API
        # ----------------------------------------------------

        if not missing_ids:

            return users

        results = await asyncio.gather(
            *(
                self.get_user(
                    user_id,
                )
                for user_id in missing_ids
            ),
            return_exceptions=True,
        )

        for result in results:

            if isinstance(
                result,
                RobloxUser,
            ):

                users.append(
                    result,
                )

            else:

                self._log(
                    logging.WARNING,
                    (
                        "Failed to fetch Roblox "
                        "user: %s"
                    ),
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
        Tek bir Roblox kullanıcısının avatarını alır.
        """

        try:

            user_id = int(
                user_id,
            )

        except (
            TypeError,
            ValueError,
        ) as error:

            raise ValueError(
                "Roblox user ID must be an integer.",
            ) from error

        if user_id <= 0:

            raise ValueError(
                "Roblox user ID must be positive.",
            )

        cache_key = (
            user_id,
            size,
            format,
        )

        cached = self._avatar_cache.get(
            cache_key,
        )

        if isinstance(
            cached,
            RobloxAvatar,
        ):

            return cached

        response = await self._request(
            method="GET",
            url=(
                f"{self.AVATAR_API}"
                "/users/avatar"
            ),
            params={
                "userIds": str(
                    user_id,
                ),
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
                (
                    "Avatar not found: "
                    f"{user_id}"
                ),
            )

        avatar_data = data[0]

        image_url = avatar_data.get(
            "imageUrl",
        )

        if not image_url:

            raise RobloxNotFoundError(
                (
                    "Avatar URL not found: "
                    f"{user_id}"
                ),
            )

        avatar = RobloxAvatar(
            user_id=user_id,
            image_url=str(
                image_url,
            ),
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
        Birden fazla Roblox avatarını alır.

        Özellikler:

            - Duplicate ID temizleme
            - Cache kullanımı
            - 100'lük batch'ler
            - Kontrollü paralel istek
            - Hatalı batch'in diğerlerini
              engellememesi
        """

        unique_ids: list[int] = []

        seen_ids: set[int] = set()

        for raw_user_id in user_ids:

            try:

                user_id = int(
                    raw_user_id,
                )

            except (
                TypeError,
                ValueError,
            ):

                self._log(
                    logging.WARNING,
                    (
                        "Ignoring invalid Roblox "
                        "avatar user ID: %r"
                    ),
                    raw_user_id,
                )

                continue

            if user_id <= 0:

                continue

            if user_id in seen_ids:

                continue

            seen_ids.add(
                user_id,
            )

            unique_ids.append(
                user_id,
            )

        if not unique_ids:

            return []

        avatars: list[RobloxAvatar] = []

        missing_ids: list[int] = []

        # ----------------------------------------------------
        # CACHE
        # ----------------------------------------------------

        for user_id in unique_ids:

            cached = self._avatar_cache.get(
                (
                    user_id,
                    size,
                    format,
                ),
            )

            if isinstance(
                cached,
                RobloxAvatar,
            ):

                avatars.append(
                    cached,
                )

            else:

                missing_ids.append(
                    user_id,
                )

        if not missing_ids:

            return avatars

        # ----------------------------------------------------
        # BATCH
        # ----------------------------------------------------

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

                avatars.extend(
                    result,
                )

            else:

                self._log(
                    logging.WARNING,
                    (
                        "Failed to fetch Roblox "
                        "avatar batch: %s"
                    ),
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

        Bir batch içindeki tüm kullanıcıların
        avatarlarını tek API request'i ile ister.
        """

        if not user_ids:

            return []

        response = await self._request(
            method="GET",
            url=(
                f"{self.AVATAR_API}"
                "/users/avatar"
            ),
            params={
                "userIds": ",".join(
                    str(
                        user_id,
                    )
                    for user_id in user_ids
                ),
                "size": size,
                "format": format,
                "isCircular": "false",
            },
        )

        avatars: list[RobloxAvatar] = []

        for item in response.get(
            "data",
            [],
        ):

            image_url = item.get(
                "imageUrl",
            )

            target_id = item.get(
                "targetId",
            )

            if not image_url:

                continue

            if target_id is None:

                continue

            try:

                user_id = int(
                    target_id,
                )

            except (
                TypeError,
                ValueError,
            ):

                self._log(
                    logging.WARNING,
                    (
                        "Invalid Roblox avatar "
                        "target ID: %r"
                    ),
                    target_id,
                )

                continue

            avatar = RobloxAvatar(
                user_id=user_id,
                image_url=str(
                    image_url,
                ),
            )

            self._avatar_cache.set(
                (
                    user_id,
                    size,
                    format,
                ),
                avatar,
            )

            avatars.append(
                avatar,
            )

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
        Merkezi HTTP request sistemi.

        Özellikler:

            - Tek AsyncClient
            - Semaphore
            - Retry
            - Timeout
            - 404 kontrolü
            - 429 retry
            - 5xx retry
            - Network retry
            - JSON validation
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

                    # ------------------------------------------------
                    # NOT FOUND
                    # ------------------------------------------------

                    if response.status_code == 404:

                        raise RobloxNotFoundError(
                            "Roblox resource not found.",
                        )

                    # ------------------------------------------------
                    # RATE LIMIT
                    # ------------------------------------------------

                    if response.status_code == 429:

                        if (
                            attempt
                            >= self.MAX_RETRIES
                        ):

                            raise RobloxAPIError(
                                (
                                    "Roblox API rate "
                                    "limit reached."
                                ),
                            )

                        retry_after = (
                            self._get_retry_after(
                                response,
                                attempt,
                            )
                        )

                        await asyncio.sleep(
                            retry_after,
                        )

                        continue

                    # ------------------------------------------------
                    # HTTP STATUS
                    # ------------------------------------------------

                    response.raise_for_status()

                    # ------------------------------------------------
                    # JSON
                    # ------------------------------------------------

                    try:

                        payload = response.json()

                    except ValueError as error:

                        raise RobloxAPIError(
                            (
                                "Roblox API returned "
                                "invalid JSON."
                            ),
                        ) from error

                    if not isinstance(
                        payload,
                        dict,
                    ):

                        raise RobloxAPIError(
                            (
                                "Roblox API returned "
                                "invalid response format."
                            ),
                        )

                    return payload

                # ====================================================
                # KNOWN PAG ERRORS
                # ====================================================

                except RobloxNotFoundError:

                    raise

                except RobloxAPIError:

                    raise

                # ====================================================
                # NETWORK / TIMEOUT
                # ====================================================

                except (
                    httpx.TimeoutException,
                    httpx.NetworkError,
                    httpx.RemoteProtocolError,
                ) as error:

                    if (
                        attempt
                        >= self.MAX_RETRIES
                    ):

                        raise RobloxAPIError(
                            (
                                "Roblox API request "
                                "failed after retries."
                            ),
                        ) from error

                    await asyncio.sleep(
                        self._retry_delay(
                            attempt,
                        ),
                    )

                # ====================================================
                # HTTP STATUS ERROR
                # ====================================================

                except httpx.HTTPStatusError as error:

                    status_code = (
                        error.response.status_code
                    )

                    # 5xx retry
                    if (
                        status_code >= 500
                        and attempt
                        < self.MAX_RETRIES
                    ):

                        await asyncio.sleep(
                            self._retry_delay(
                                attempt,
                            ),
                        )

                        continue

                    raise RobloxAPIError(
                        (
                            "Roblox API returned "
                            f"HTTP {status_code}."
                        ),
                    ) from error

                # ====================================================
                # UNEXPECTED
                # ====================================================

                except Exception as error:

                    self._log(
                        logging.ERROR,
                        (
                            "Unexpected Roblox API "
                            "error: %s"
                        ),
                        error,
                    )

                    raise RobloxAPIError(
                        "Unexpected Roblox API error.",
                    ) from error

        raise RobloxAPIError(
            "Roblox API request failed.",
        )

    # ========================================================
    # RETRY AFTER
    # ========================================================

    def _get_retry_after(
        self,
        response: httpx.Response,
        attempt: int,
    ) -> float:
        """
        429 durumunda retry süresini belirler.

        Roblox header verirse onu kullanır.
        Geçersizse kontrollü fallback uygulanır.
        """

        header_value = response.headers.get(
            "Retry-After",
        )

        if header_value:

            try:

                retry_after = float(
                    header_value,
                )

                return max(
                    0.1,
                    min(
                        retry_after,
                        10.0,
                    ),
                )

            except (
                TypeError,
                ValueError,
            ):

                pass

        return self._retry_delay(
            attempt,
        )

    # ========================================================
    # RETRY DELAY
    # ========================================================

    def _retry_delay(
        self,
        attempt: int,
    ) -> float:
        """
        Retry delay hesaplar.

        Örnek:

            attempt 1 -> 0.5
            attempt 2 -> 1.0
            attempt 3 -> 1.5
        """

        return (
            self.RETRY_DELAY
            * attempt
        )

    # ========================================================
    # PARSE USER
    # ========================================================

    @staticmethod
    def _parse_user(
        data: dict[str, Any],
    ) -> RobloxUser:
        """
        Roblox API user response'unu
        RobloxUser modeline dönüştürür.
        """

        try:

            user_id = int(
                data["id"],
            )

            name = str(
                data["name"],
            )

            display_name = str(
                data["displayName"],
            )

            description = str(
                data.get(
                    "description",
                    "",
                )
                or "",
            )

            created = str(
                data.get(
                    "created",
                    "",
                )
                or "",
            )

            is_banned = bool(
                data.get(
                    "isBanned",
                    False,
                ),
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ) as error:

            raise RobloxAPIError(
                (
                    "Invalid Roblox user "
                    "response."
                ),
            ) from error

        if user_id <= 0:

            raise RobloxAPIError(
                (
                    "Roblox user response "
                    "contained invalid ID."
                ),
            )

        if not name.strip():

            raise RobloxAPIError(
                (
                    "Roblox user response "
                    "contained empty username."
                ),
            )

        return RobloxUser(
            id=user_id,
            name=name,
            display_name=(
                display_name
                or name
            ),
            description=description,
            created=created,
            is_banned=is_banned,
        )

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
                (
                    "RobloxService is not started. "
                    "Call 'await service.start()' "
                    "first."
                ),
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
        Listeyi batch'lere böler.
        """

        if size <= 0:

            raise ValueError(
                "Chunk size must be positive.",
            )

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