# Radiação de Chernobyl, não encostar.

from typing import Any, Dict, List, Optional
import requests
import logging
import asyncio
import time
import json
from pathlib import Path
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from src.platforms.base import AuthField, AuthFieldType, BasePlatform, PlatformFactory
from src.platforms.playwright_token_fetcher import PlaywrightTokenFetcher
from src.app.models import LessonContent, Attachment, Video
from src.app.api_service import ApiService
from src.config.settings_manager import SettingsManager

class UdemyTokenFetcher(PlaywrightTokenFetcher):
    @property
    def login_url(self) -> str:
        # Redirects to Udemy home after login
        return "https://www.udemy.com/join/login-popup/?locale=en_US&response_type=html&next=https%3A%2F%2Fwww.udemy.com%2F"

    @property
    def target_endpoints(self) -> List[str]:
        # We target a user API call to confirm login and retrieve auth headers.
        return [
            "api-2.0/users/me",
        ]

    async def fill_credentials(self, page: Page, username: str, password: str) -> None:
        # Login must be completed manually in the GUI (2FA aware). Do nothing here.
        return None

    async def submit_login(self, page: Page) -> None:
        try:
            await page.click('button[type="submit"]', timeout=3000)
        except:
            pass

    async def is_logged_in(self, page: Page) -> bool:
        """Check if the user appears to be logged in based on visual elements."""
        try:
            if "udemy.com/join" in page.url: 
                return False
            
            # Check for avatar or my-courses link (async)
            # Use gather to check parallel conditions
            # locator.count() is async in python playwright
            
            avatar_count = await page.locator('[data-purpose="header-user-avatar"]').count()
            if avatar_count > 0: return True
            
            courses_link_count = await page.locator('a[href*="/home/my-courses/"]').count()
            if courses_link_count > 0: return True

            return False
        except Exception:
            return False

    async def _capture_authorization_header(self, page: Page) -> tuple[Optional[str], Optional[str]]:
        """
        Robust capture strategy:
        1. Listen for background XHR requests (Authorization header).
        2. Poll for visual login success -> Extract Cookies.
        """
        found_token_queue = asyncio.Queue()

        async def handle_request(request):
            # Check if request targets our API
            url = request.url
            if "api-2.0/" in url and "users/me" in url:
                auth = request.headers.get("authorization")
                if auth:
                    await found_token_queue.put((auth, url))
                    return
                # Sometimes auth is in cookie for these requests too
                cookie = request.headers.get("cookie")
                if cookie:
                    if not self._has_required_cookies(cookie):
                        logging.info("Udemy: Ignorando captura parcial de cookies da requisição %s", url)
                    else:
                        self._log_cookies_from_header(cookie, source="request")
                        payload = await self._build_cookie_payload(page, cookie)
                        await found_token_queue.put((payload, url))

        # Attach listener
        page.on("request", handle_request)

        # Loop until timeout
        end_time = time.time() + (self.network_idle_timeout_ms / 1000)
        
        while time.time() < end_time:
            # 1. Check if we caught a token from XHR
            try:
                # Non-blocking check
                token_data = found_token_queue.get_nowait()
                if token_data:
                    return token_data
            except asyncio.QueueEmpty:
                pass

            # 2. Check if we are visually logged in
            if await self.is_logged_in(page):
                 # Give a small buffer for cookies to settle
                 await asyncio.sleep(4)
                 cookies = await page.context.cookies()
                 # Build cookie string (Playwright includes HttpOnly/secure values)
                 cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                 
                 if cookie_str:
                     if not self._has_required_cookies(cookie_str):
                         logging.info("Udemy: Cookies ainda incompletos, aguardando mais capturas...")
                         await asyncio.sleep(3)
                         continue

                     logging.info("Udemy: Estado logado detectado. Capturando cookies completos.")
                     for cookie in cookies:
                         logging.info("Udemy: Cookie capturado %s=%s", cookie.get("name"), cookie.get("value"))

                     self._log_cookies_from_header(cookie_str, source="context")

                     payload = await self._build_cookie_payload(page, cookie_str)
                     return payload, page.url
            
            await asyncio.sleep(1)

        return None, None

    async def _build_cookie_payload(self, page: Page, cookie_header: str) -> str:
        local_storage = await self._get_local_storage(page)
        session_storage = await self._get_session_storage(page)
        payload = {
            "token_type": "cookie",
            "cookie": cookie_header,
            "local_storage": local_storage,
            "session_storage": session_storage,
        }
        return json.dumps(payload)

    async def _get_local_storage(self, page: Page) -> Dict[str, str]:
        try:
            return await page.evaluate("() => JSON.parse(JSON.stringify(localStorage))")
        except Exception:
            return {}

    async def _get_session_storage(self, page: Page) -> Dict[str, str]:
        try:
            return await page.evaluate("() => JSON.parse(JSON.stringify(sessionStorage))")
        except Exception:
            return {}

    def _has_required_cookies(self, cookie_header: str) -> bool:
        required = ["cf_clearance", "csrftoken", "ud_cache_user", "dj_session_id"]
        cookie_parts = [part.strip() for part in cookie_header.split(";") if part.strip()]
        for req in required:
            if not any(part.startswith(f"{req}=") for part in cookie_parts):
                return False
        return True

    def _log_cookies_from_header(self, cookie_header: str, *, source: str) -> None:
        cookie_parts = [part.strip() for part in cookie_header.split(";") if part.strip()]
        for part in cookie_parts:
            logging.info("Udemy: Cookie (%s) %s", source, part)


class UdemyPlatform(BasePlatform):
    def __init__(self, api_service: ApiService, settings_manager: SettingsManager):
        super().__init__(api_service, settings_manager)
        self._token_fetcher = UdemyTokenFetcher()
        self._captured_local_storage: Dict[str, Any] = {}
        self._captured_session_storage: Dict[str, Any] = {}

    @classmethod
    def auth_fields(cls) -> List[AuthField]:
        return []

    @classmethod
    def auth_instructions(cls) -> str:
        return """
    Para realizar o login na Udemy:
    1. Marque obrigatoriamente a opção "Emular Navegador".
    2. Uma janela do navegador será aberta. Realize TODO o processo manualmente (incluindo 2FA).
    3. Após acessar https://www.udemy.com/home/my-courses/learning/, clique em OK na aplicação.
    4. Não há preenchimento automático de credenciais; o usuário precisa digitar/colar diretamente no navegador.
    """.strip()

    def authenticate(self, credentials: Dict[str, Any]) -> None:
        self.credentials = credentials
        token_data = self.resolve_access_token(credentials, self._exchange_credentials_for_token)
        
        self._session = requests.Session()
        # Mimic browser headers observed in HAR capture
        self._session.headers.update({
            "User-Agent": self._settings.user_agent,
            "Referer": "https://www.udemy.com/home/my-courses/learning/",
            "Accept-Language": "pt-BR",
            "Sec-GPC": "1",
        })
        
        payload = self._try_parse_cookie_payload(token_data)
        cookie_content: Optional[str] = None

        if payload and payload.get("cookie"):
            cookie_content = payload.get("cookie")
            self._captured_local_storage = payload.get("local_storage", {}) or {}
            self._captured_session_storage = payload.get("session_storage", {}) or {}
        elif token_data.startswith("Cookie:"):
            cookie_content = token_data[7:]

        if cookie_content:
            self._apply_cookie_headers(cookie_content)
        elif token_data.lower().startswith("bearer "):
             self._session.headers["Authorization"] = token_data
        else:
             self._apply_cookie_headers(token_data)

    def _apply_cookie_headers(self, cookie_content: str) -> None:
        self._session.headers["Cookie"] = cookie_content
        self._session.headers["X-Requested-With"] = "XMLHttpRequest"
        self._session.headers["Accept"] = "application/json, text/plain, */*"
        self._session.headers["X-Udemy-Cache-Logged-In"] = "1"

        if "csrftoken=" in cookie_content:
            try:
                parts = cookie_content.split(";")
                for p in parts:
                    p = p.strip()
                    if p.startswith("csrftoken="):
                        csrf = p.split("=", 1)[1]
                        self._session.headers["X-CSRFToken"] = csrf
                        break
            except Exception:
                pass

        try:
            parts = [seg.strip() for seg in cookie_content.split(";") if seg.strip()]
            kv = {}
            for p in parts:
                if "=" in p:
                    k, v = p.split("=", 1)
                    kv[k] = v

            def _set_if_present(header_name: str, cookie_key: str) -> None:
                value = kv.get(cookie_key)
                if value:
                    self._session.headers[header_name] = value

            _set_if_present("X-Udemy-Cache-Release", "ud_cache_release")
            _set_if_present("X-Udemy-Cache-User", "ud_cache_user")
            _set_if_present("X-Udemy-Cache-Brand", "ud_cache_brand")
            _set_if_present("X-Udemy-Cache-Marketplace-Country", "ud_cache_marketplace_country")
            _set_if_present("X-Udemy-Cache-Price-Country", "ud_cache_price_country")
            _set_if_present("X-Udemy-Cache-Version", "ud_cache_version")
            _set_if_present("X-Udemy-Cache-Language", "ud_cache_language")
            _set_if_present("X-Udemy-Cache-Device", "ud_cache_device")
            _set_if_present("X-Udemy-Cache-Campaign-Code", "ud_cache_campaign_code")
            _set_if_present("X-Udemy-Client-Id", "client_id")
        except Exception:
            pass

    def _try_parse_cookie_payload(self, token_data: str) -> Optional[Dict[str, Any]]:
        try:
            parsed = json.loads(token_data)
        except Exception:
            return None

        if isinstance(parsed, dict) and parsed.get("token_type") == "cookie" and parsed.get("cookie"):
            return parsed

        return None

    def _exchange_credentials_for_token(self, username: str, password: str, credentials: Dict[str, Any]) -> str:
        use_browser_emulation = bool(credentials.get("browser_emulation"))
        confirmation_event = credentials.get("manual_auth_confirmation")
        custom_ua = self._settings.user_agent
        
        if not use_browser_emulation:
            raise ConnectionError("Para Udemy é obrigatório habilitar 'Emular Navegador' e efetuar login manualmente.")
        
        try:
            return self._token_fetcher.fetch_token(
                username,
                password,
                headless=not use_browser_emulation,
                user_agent=custom_ua,
                wait_for_user_confirmation=(
                    confirmation_event.wait if confirmation_event else None
                ),
            )
        except Exception as exc:
            raise ConnectionError("Falha no login via Browser. Verifique credenciais ou 2FA.") from exc

    def fetch_courses(self) -> List[Dict[str, Any]]:
        if not self._session:
            raise ConnectionError("A sessão não foi autenticada.")
            
        url = "https://www.udemy.com/api-2.0/users/me/subscribed-courses/"
        params = {
            "ordering": "-last_accessed",
            "fields[course]": "id,title,url,image_480x270",
            "page": 1,
            "page_size": 100,
            "is_archived": False
        }
        
        all_courses = []
        while url:
            # If next url comes full, use it, but be careful with params duplication
            # Only use params for the first call
            is_initial = "api-2.0/users/me/subscribed-courses/" in url and "page=" not in url
            
            # Actually next url contains all params needed
            p = params if is_initial else None
            
            resp = self._session.get(url, params=p)
            resp.raise_for_status()
            data = resp.json()
            
            for result in data.get("results", []):
                all_courses.append({
                    "id": str(result.get("id")),
                    "name": result.get("title"),
                    "url": f"https://www.udemy.com{result.get('url')}",
                    "image": result.get("image_480x270"),
                    "slug": result.get("url", "").strip("/").split("/")[-2] if result.get("url") else ""
                })
            
            url = data.get("next")
            
        return all_courses

    def fetch_course_content(self, courses: List[Dict[str, Any]]) -> Dict[str, Any]:
        final_structure = {"modules": []}
        
        for course in courses:
             course_id = course["id"]
             try:
                 curriculum = self._fetch_curriculum(course_id)
                 
                 # Grouping logic
                 current_module = None
                 # If no chapters, create a default one
                 if not any(item.get("_class") == "chapter" for item in curriculum):
                     current_module = {"id": f"c_{course_id}_default", "name": course["name"], "lessons": []}
                     final_structure["modules"].append(current_module)

                 for item in curriculum:
                     _class = item.get("_class")
                     
                     if _class == "chapter":
                         current_module = {
                             "id": str(item.get("id")),
                             "name": item.get("title"),
                             "lessons": []
                         }
                         final_structure["modules"].append(current_module)
                         
                     elif _class == "lecture":
                         if current_module is None:
                             # Should have been created if no chapters, or we just hit a lecture before first chapter
                             current_module = {"id": f"c_{course_id}_startup", "name": "Introduction", "lessons": []}
                             final_structure["modules"].append(current_module)
                             
                         current_module["lessons"].append({
                             "id": str(item.get("id")),
                             "name": item.get("title"),
                             "asset": item.get("asset"),
                             "supplementary_assets": item.get("supplementary_assets")
                         })
                         
             except Exception as e:
                 logging.error(f"Error fetching curriculum for course {course['name']}: {e}")
                 
        return final_structure

    def _fetch_curriculum(self, course_id: str) -> List[Dict[str, Any]]:
        url = f"https://www.udemy.com/api-2.0/courses/{course_id}/subscriber-curriculum-items/"
        params = {
            "curriculum_types": "chapter,lecture,quiz,practice", 
            "page_size": 200,
            "fields[lecture]": "title,object_index,is_published,sort_order,created,asset,supplementary_assets",
            "fields[chapter]": "title,object_index,is_published,sort_order",
            "fields[asset]": "title,filename,asset_type,status,time_estimation,is_external", 
            "caching_intent": "True"
        }
        
        items = []
        current_url = url
        first_call = True
        
        while current_url:
            p = params if first_call else None
            resp = self._session.get(current_url, params=p)
            resp.raise_for_status()
            data = resp.json()
            
            items.extend(data.get("results", []))
            current_url = data.get("next")
            first_call = False
            
        return items

    def fetch_lesson_details(self, lesson: Dict[str, Any], course_slug: str, course_id: str, module_id: str) -> LessonContent:
        content = LessonContent()
        
        asset = lesson.get("asset")
        if asset and asset.get("asset_type") == "Video":
            asset_id = asset.get("id")
            if asset_id:
                video_url, quality = self._get_video_details(asset_id)
                if video_url:
                    content.videos.append(Video(
                        video_id=str(asset_id),
                        url=video_url,
                        order=1,
                        title=f"{lesson.get('name')} - {quality}",
                        size=0,
                        duration=asset.get("time_estimation", 0) or 0
                    ))
        
        # Attachments
        supp_assets = lesson.get("supplementary_assets", [])
        for idx, supp in enumerate(supp_assets, 1):
            if supp.get("asset_type") == "File":
                supp_id = supp.get("id")
                u = self._get_attachment_url(supp_id)
                if u:
                    content.attachments.append(Attachment(
                        attachment_id=str(supp_id),
                        url=u,
                        filename=supp.get("filename"),
                        order=idx,
                        extension=supp.get("filename").split(".")[-1] if "." in supp.get("filename") else "",
                        size=0
                    ))
                    
        return content

    def _get_video_details(self, asset_id: int) -> tuple[Optional[str], str]:
        url = f"https://www.udemy.com/api-2.0/assets/{asset_id}/"
        params = {
            "fields[asset]": "stream_urls,download_urls,media_sources"
        }
        try:
             resp = self._session.get(url, params=params)
             resp.raise_for_status()
             data = resp.json()
             
             # Priority: media_sources -> download_urls
             media_sources = data.get("media_sources")
             if media_sources:
                 best = None
                 max_res = -1
                 for src in media_sources:
                     label = src.get("label", "0")
                     try:
                        res = int(label.replace("p", ""))
                     except:
                        res = 0
                     
                     if res > max_res:
                         max_res = res
                         best = src
                 
                 if best:
                     return best.get("src"), best.get("label")
             
             download_urls = data.get("download_urls")
             if download_urls and isinstance(download_urls, dict):
                  videos = download_urls.get("Video", [])
                  if videos:
                      return videos[0].get("file"), "Download"

        except Exception as e:
            logging.error(f"Error fetching video url for asset {asset_id}: {e}")
            
        return None, ""
    
    def _get_attachment_url(self, asset_id: int) -> Optional[str]:
         url = f"https://www.udemy.com/api-2.0/assets/{asset_id}/"
         params = {"fields[asset]": "download_urls"}
         try:
             resp = self._session.get(url, params=params)
             resp.raise_for_status()
             data = resp.json()
             d_urls = data.get("download_urls")
             if d_urls and isinstance(d_urls, dict):
                 files = d_urls.get("File", [])
                 if files:
                     return files[0].get("file")
         except:
             pass
         return None

    def download_attachment(self, attachment: "Attachment", download_path: Path, course_slug: str, course_id: str, module_id: str) -> bool:
        try:
            r = self._session.get(attachment.url, stream=True)
            r.raise_for_status()
            with open(download_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception:
            return False

# PlatformFactory.register_platform("Udemy", UdemyPlatform)
