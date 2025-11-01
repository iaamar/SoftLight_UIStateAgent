import os
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, ElementHandle
from typing import Optional, Dict, Any, List, Union, Callable
from utils.logger import get_logger
from utils.helpers import get_screenshot_path, ensure_dir
from functools import wraps
import time

logger = get_logger(name="browser_automation")


def retry_on_error(max_attempts: int = 3, delay: float = 1.0):
    """Decorator for retrying operations on failure"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_attempts - 1:
                        logger.warning(f"Attempt {attempt + 1} failed: {str(e)}. Retrying...")
                        await asyncio.sleep(delay * (attempt + 1))
                    else:
                        logger.error(f"All {max_attempts} attempts failed: {str(e)}")
            raise last_error
        return wrapper
    return decorator


class BrowserController:
    def __init__(
        self,
        headless: bool = True,
        browser_type: str = "chromium",
        timeout: int = 30000,
        viewport_width: int = 1920,
        viewport_height: int = 1080,
        context_state_file: Optional[str] = None,
        user_agent: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        locale: str = "en-US",
        timezone: str = "America/New_York"
    ):
        self.headless = headless
        self.browser_type = browser_type
        self.timeout = timeout
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.context_state_file = context_state_file
        self.user_agent = user_agent
        self.extra_headers = extra_headers or {}
        self.locale = locale
        self.timezone = timezone
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self.navigation_history: List[Dict[str, Any]] = []
        self.detected_modals: List[Dict[str, Any]] = []
    
    async def start(self):
        logger.info("Starting enhanced browser automation")
        self.playwright = await async_playwright().start()
        
        # Try to connect to an external browser first (visible window on host)
        connected = False
        ws_endpoint = os.getenv("PLAYWRIGHT_WS_ENDPOINT", "").strip()
        cdp_port = os.getenv("PLAYWRIGHT_REMOTE_DEBUG_PORT", "").strip()
        if ws_endpoint:
            try:
                logger.info(f"Connecting to Playwright WS endpoint: {ws_endpoint}")
                self.browser = await self.playwright.connect(ws_endpoint)
                connected = True
            except Exception as e:
                logger.warning(f"WS connect failed: {e}")
        elif cdp_port:
            try:
                import httpx
                host = os.getenv("PLAYWRIGHT_REMOTE_DEBUG_HOST", "host.docker.internal")
                version_url = f"http://{host}:{cdp_port}/json/version"
                logger.info(f"Resolving CDP endpoint from {version_url}")
                async with httpx.AsyncClient(timeout=5) as client:
                    resp = await client.get(version_url)
                    resp.raise_for_status()
                    ws_url = resp.json().get("webSocketDebuggerUrl", "")
                if not ws_url:
                    raise RuntimeError("webSocketDebuggerUrl not found from CDP version endpoint")
                logger.info(f"Connecting over CDP: {ws_url}")
                self.browser = await self.playwright.chromium.connect_over_cdp(ws_url)
                connected = True
            except Exception as e:
                logger.warning(f"CDP connect failed: {e}")
        
        if not connected:
            browser_map = {
                "chromium": self.playwright.chromium,
                "firefox": self.playwright.firefox,
                "webkit": self.playwright.webkit
            }
            browser_class = browser_map.get(self.browser_type, self.playwright.chromium)
            # Launch with additional options for stability
            launch_options = {
                "headless": self.headless,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process"
                ]
            }
            # Optional channel selection via env (e.g., PLAYWRIGHT_CHANNEL=chrome)
            channel_env = os.getenv("PLAYWRIGHT_CHANNEL", "").strip()
            if channel_env:
                launch_options["channel"] = channel_env
            # Launch with fallback if a specific channel is unavailable
            try:
                self.browser = await browser_class.launch(**launch_options)
            except Exception as launch_error:
                if "channel" in launch_options:
                    failed_channel = launch_options.pop("channel")
                    logger.warning(f"Browser launch failed with channel '{failed_channel}', retrying with bundled binary: {launch_error}")
                    self.browser = await browser_class.launch(**launch_options)
                else:
                    raise
        
        # Load saved context state if available
        storage_state = None
        if self.context_state_file and os.path.exists(self.context_state_file):
            try:
                storage_state = self.context_state_file
                logger.info(f"Loading browser context state from {self.context_state_file}")
            except Exception as e:
                logger.warning(f"Failed to load context state: {e}")
        
        # Create context with enhanced options
        context_options = {
            "viewport": {'width': self.viewport_width, 'height': self.viewport_height},
            "storage_state": storage_state,
            "locale": self.locale,
            "timezone_id": self.timezone,
            "permissions": ["geolocation", "notifications"],
            "ignore_https_errors": True,
            "extra_http_headers": self.extra_headers
        }
        
        if self.user_agent:
            context_options["user_agent"] = self.user_agent
        
        self.context = await self.browser.new_context(**context_options)
        
        # Set up request interception for better control
        await self.context.route("**/*", self._handle_route)
        
        # Create page with event handlers
        self.page = await self.context.new_page()
        self.page.set_default_timeout(self.timeout)
        
        # Set up event handlers for better monitoring
        self.page.on("dialog", self._handle_dialog)
        self.page.on("download", self._handle_download)
        self.page.on("popup", self._handle_popup)
        self.page.on("pageerror", self._handle_page_error)
        self.page.on("console", self._handle_console)
        
        logger.info(f"Browser started: {self.browser_type}, headless={self.headless}")
    
    async def _handle_route(self, route):
        """Handle route interception for blocking ads/trackers"""
        if any(domain in route.request.url for domain in ["googletagmanager.com", "google-analytics.com", "doubleclick.net"]):
            await route.abort()
        else:
            await route.continue_()
    
    async def _handle_dialog(self, dialog):
        """Handle JavaScript dialogs automatically"""
        logger.info(f"Dialog detected: {dialog.type} - {dialog.message}")
        await dialog.accept()
    
    async def _handle_download(self, download):
        """Handle downloads"""
        logger.info(f"Download started: {download.url}")
    
    async def _handle_popup(self, popup):
        """Handle popups"""
        logger.info(f"Popup detected: {popup.url}")
    
    async def _handle_page_error(self, error):
        """Handle page errors"""
        logger.error(f"Page error: {error}")
    
    async def _handle_console(self, msg):
        """Handle console messages for debugging"""
        if msg.type in ["error", "warning"]:
            logger.debug(f"Console {msg.type}: {msg.text}")
    
    @retry_on_error(max_attempts=3)
    async def navigate(self, url: str, wait_until: str = "domcontentloaded"):
        if not self.page:
            raise RuntimeError("Browser not started")
        
        logger.log_action("navigate", {"url": url})
        
        # Record navigation
        self.navigation_history.append({
            "url": url,
            "timestamp": time.time(),
            "type": "navigate"
        })
        
        try:
            # Use multiple wait strategies
            response = await self.page.goto(url, wait_until=wait_until, timeout=self.timeout)
            
            # Additional wait for dynamic content
            await self.wait_for_stable_page()
            
            # Check for common error pages
            if response and response.status >= 400:
                logger.warning(f"Navigation resulted in error status: {response.status}")
            
            return response
        except Exception as e:
            logger.warning(f"Navigation failed with {wait_until}, trying networkidle: {e}")
            try:
                response = await self.page.goto(url, wait_until="networkidle", timeout=self.timeout)
                return response
            except Exception as e2:
                logger.warning(f"Navigation failed with networkidle, trying domcontentloaded: {e2}")
                response = await self.page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
                return response
    
    async def wait_for_stable_page(self, stability_time: float = 0.5, max_wait: float = 5.0):
        """Wait for page to be stable (no network activity or DOM changes)"""
        start_time = time.time()
        last_activity = time.time()
        
        async def check_activity():
            nonlocal last_activity
            # Check for ongoing network requests
            requests = await self.page.evaluate("() => window.performance.getEntriesByType('resource').length")
            # Check DOM mutation
            dom_state = await self.page.evaluate("() => document.body.innerHTML.length")
            return requests, dom_state
        
        prev_state = await check_activity()
        
        while time.time() - start_time < max_wait:
            await asyncio.sleep(0.1)
            current_state = await check_activity()
            
            if current_state != prev_state:
                last_activity = time.time()
                prev_state = current_state
            elif time.time() - last_activity >= stability_time:
                # Page has been stable
                break
    
    async def click(self, selector: str, timeout: Optional[int] = None, force: bool = True, retry: bool = True):
        """Robust click with scroll, force, and multiple fallback strategies"""
        if not self.page:
            raise RuntimeError("Browser not started")
        
        logger.log_action("click", {"selector": selector})
        
        try:
            # Ensure element exists
            await self.wait_for_element(selector, state="attached", timeout=timeout or 5000)
            
            element = await self.page.query_selector(selector)
            if not element:
                raise ValueError(f"Element not found: {selector}")
            
            # Scroll element into view
            try:
                await element.scroll_into_view_if_needed()
                await asyncio.sleep(0.2)  # Let scroll settle
            except:
                pass
            
            # Try click strategies in order
            clicked = False
            
            # Strategy 1: Playwright click with force
            try:
                await element.click(force=True, timeout=3000)
                clicked = True
                logger.debug("Playwright force click succeeded")
            except Exception as e1:
                logger.debug(f"Force click failed: {e1}")
                
                # Strategy 2: JavaScript click
                try:
                    await self.page.evaluate(f"""
                        const elem = document.querySelector('{selector}');
                        if (elem) elem.click();
                    """)
                    clicked = True
                    logger.debug("JavaScript click succeeded")
                except Exception as e2:
                    logger.debug(f"JS click failed: {e2}")
                    
                    # Strategy 3: Dispatch click event
                    try:
                        await element.dispatch_event("click")
                        clicked = True
                        logger.debug("Dispatch event succeeded")
                    except Exception as e3:
                        logger.debug(f"Dispatch event failed: {e3}")
                        
                        if retry:
                            # Try finding alternative selector
                            alt_selector = await self.find_alternative_selector(selector)
                            if alt_selector:
                                logger.info(f"Retrying with alternative selector: {alt_selector}")
                                return await self.click(alt_selector, timeout, force, retry=False)
                        raise Exception(f"All click strategies failed for {selector}")
            
            # Brief wait for page reaction
            await asyncio.sleep(0.5)
            await self.wait_for_stable_page(max_wait=2.0)
            
        except Exception as e:
            logger.warning(f"Click failed for {selector}: {e}")
            raise e
    
    async def type(self, selector: str, text: str, delay: int = 50, clear_first: bool = True):
        if not self.page:
            raise RuntimeError("Browser not started")
        
        logger.log_action("type", {"selector": selector, "text_length": len(text)})
        
        await self.wait_for_element(selector, state="visible")
        
        element = await self.page.query_selector(selector)
        if not element:
            raise ValueError(f"Element not found: {selector}")
        
        # Click to focus
        await element.click()
        
        # Clear existing content if requested
        if clear_first:
            await element.evaluate("el => el.value = ''")
            # Triple click to select all and then type
            await element.click(click_count=3)
        
        # Type with delay for more human-like behavior
        await element.type(text, delay=delay)
    
    async def wait_for_element(
        self, 
        selector: str, 
        state: str = "visible", 
        timeout: Optional[int] = None
    ):
        """Enhanced wait for element with multiple strategies"""
        try:
            await self.page.wait_for_selector(
                selector, 
                state=state, 
                timeout=timeout or self.timeout
            )
        except Exception as e:
            # Try with text selector
            if "text=" not in selector:
                text_selector = f"text={selector}"
                try:
                    await self.page.wait_for_selector(
                        text_selector, 
                        state=state, 
                        timeout=1000  # Quick check
                    )
                    return
                except:
                    pass
            raise e
    
    async def wait_for_element_clickable(self, selector: str, timeout: Optional[int] = None):
        """Wait for element to be clickable (visible, enabled, not covered)"""
        timeout = timeout or self.timeout
        start_time = time.time()
        
        while time.time() - start_time < timeout / 1000:
            element = await self.page.query_selector(selector)
            if element and await self.is_element_clickable(element):
                return
            await asyncio.sleep(0.1)
        
        raise TimeoutError(f"Element {selector} not clickable after {timeout}ms")
    
    async def is_element_clickable(self, element: ElementHandle) -> bool:
        """Check if element is truly clickable"""
        try:
            # Check if element is visible
            is_visible = await element.is_visible()
            if not is_visible:
                return False
            
            # Check if element is enabled
            is_enabled = await element.is_enabled()
            if not is_enabled:
                return False
            
            # Check if element is not covered by other elements
            box = await element.bounding_box()
            if not box:
                return False
            
            # Check element at center point
            center_x = box['x'] + box['width'] / 2
            center_y = box['y'] + box['height'] / 2
            
            element_at_point = await self.page.evaluate(
                f"document.elementFromPoint({center_x}, {center_y})"
            )
            
            # Element might be covered
            if not element_at_point:
                return False
            
            return True
        except:
            return False
    
    async def find_alternative_selector(self, original_selector: str) -> Optional[str]:
        """Find alternative selector for element"""
        try:
            element = await self.page.query_selector(original_selector)
            if not element:
                return None
            
            # Try to get unique attributes
            tag_name = await element.evaluate("el => el.tagName.toLowerCase()")
            id_attr = await element.evaluate("el => el.id")
            class_attr = await element.evaluate("el => el.className")
            text_content = await element.evaluate("el => el.textContent.trim()")
            
            alternatives = []
            
            if id_attr:
                alternatives.append(f"#{id_attr}")
            
            if class_attr:
                first_class = class_attr.split()[0]
                alternatives.append(f"{tag_name}.{first_class}")
            
            if text_content and len(text_content) < 50:
                alternatives.append(f"{tag_name}:has-text('{text_content}')")
            
            # Test alternatives
            for alt in alternatives:
                if alt != original_selector:
                    try:
                        test_element = await self.page.query_selector(alt)
                        if test_element:
                            return alt
                    except:
                        continue
            
            return None
        except:
            return None
    
    async def detect_and_handle_modals(self) -> List[Dict[str, Any]]:
        """Detect modal dialogs and popups"""
        modal_selectors = [
            "[role='dialog']",
            "[aria-modal='true']",
            ".modal",
            ".dialog",
            ".popup",
            "[class*='modal']",
            "[class*='dialog']",
            "[class*='popup']",
            "[class*='overlay']"
        ]
        
        detected_modals = []
        
        for selector in modal_selectors:
            try:
                modals = await self.page.query_selector_all(selector)
                for modal in modals:
                    is_visible = await modal.is_visible()
                    if is_visible:
                        # Get modal details
                        box = await modal.bounding_box()
                        text = await modal.inner_text()
                        
                        modal_info = {
                            "selector": selector,
                            "text": text[:200],  # First 200 chars
                            "position": box,
                            "timestamp": time.time()
                        }
                        
                        detected_modals.append(modal_info)
                        logger.info(f"Modal detected: {selector}")
            except:
                continue
        
        self.detected_modals = detected_modals
        return detected_modals
    
    async def handle_form_fields(self, form_data: Dict[str, str]):
        """Intelligently fill form fields"""
        for field_name, value in form_data.items():
            # Try multiple strategies to find form fields
            selectors = [
                f"input[name='{field_name}']",
                f"input[id='{field_name}']",
                f"input[placeholder*='{field_name}' i]",
                f"textarea[name='{field_name}']",
                f"select[name='{field_name}']"
            ]
            
            filled = False
            for selector in selectors:
                try:
                    element = await self.page.query_selector(selector)
                    if element:
                        tag_name = await element.evaluate("el => el.tagName.toLowerCase()")
                        
                        if tag_name == "select":
                            await self.page.select_option(selector, value)
                        else:
                            await self.type(selector, value)
                        
                        filled = True
                        logger.info(f"Filled form field: {field_name}")
                        break
                except:
                    continue
            
            if not filled:
                logger.warning(f"Could not find form field: {field_name}")
    
    async def capture_full_workflow_state(self) -> Dict[str, Any]:
        """Capture comprehensive UI state information"""
        state = {
            "url": await self.get_url(),
            "title": await self.page.title(),
            "viewport": self.page.viewport_size,  # Property, not method
            "cookies": await self.context.cookies(),
            "local_storage": await self.get_local_storage(),
            "session_storage": await self.get_session_storage(),
            "modals": await self.detect_and_handle_modals(),
            "forms": await self.detect_forms(),
            "navigation_history": self.navigation_history,
            "timestamp": time.time()
        }
        
        return state
    
    async def detect_forms(self) -> List[Dict[str, Any]]:
        """Detect all forms on the page"""
        forms = await self.page.query_selector_all("form")
        form_data = []
        
        for form in forms:
            form_info = {
                "fields": [],
                "action": await form.get_attribute("action"),
                "method": await form.get_attribute("method")
            }
            
            # Find all input fields
            inputs = await form.query_selector_all("input, textarea, select")
            for input_elem in inputs:
                field_info = {
                    "name": await input_elem.get_attribute("name"),
                    "type": await input_elem.get_attribute("type"),
                    "required": await input_elem.get_attribute("required") is not None,
                    "placeholder": await input_elem.get_attribute("placeholder")
                }
                form_info["fields"].append(field_info)
            
            form_data.append(form_info)
        
        return form_data
    
    async def get_local_storage(self) -> Dict[str, Any]:
        """Get localStorage data"""
        try:
            return await self.page.evaluate("Object.fromEntries(Object.entries(localStorage))")
        except:
            return {}
    
    async def get_session_storage(self) -> Dict[str, Any]:
        """Get sessionStorage data"""
        try:
            return await self.page.evaluate("Object.fromEntries(Object.entries(sessionStorage))")
        except:
            return {}
    
    async def smart_screenshot(
        self, 
        app: str, 
        task: str, 
        step: int, 
        full_page: bool = False,  # Changed default to False for cropped shots
        highlight_elements: Optional[List[str]] = None
    ):
        """Enhanced screenshot with smart cropping and element highlighting"""
        if not self.page:
            raise RuntimeError("Browser not started")
        
        screenshot_path = get_screenshot_path(app, task, step)
        ensure_dir(os.path.dirname(screenshot_path))
        
        # Determine what to capture
        clip_region = None
        
        if highlight_elements and len(highlight_elements) > 0:
            # Crop to the highlighted element + context
            for selector in highlight_elements:
                try:
                    element = await self.page.query_selector(selector)
                    if element:
                        # Scroll element into view
                        await element.scroll_into_view_if_needed()
                        await asyncio.sleep(0.3)  # Let scroll settle
                        
                        # Get element bounding box
                        box = await element.bounding_box()
                        if box:
                            # Add padding around element (300px each side)
                            padding = 300
                            viewport = self.page.viewport_size
                            clip_region = {
                                'x': max(0, box['x'] - padding),
                                'y': max(0, box['y'] - padding),
                                'width': min(viewport['width'], box['width'] + padding * 2),
                                'height': min(viewport['height'], box['height'] + padding * 2)
                            }
                            
                            # Highlight the element
                            await self.page.evaluate(f"""
                                document.querySelector('{selector}').style.outline = '4px solid #FF4444';
                                document.querySelector('{selector}').style.outlineOffset = '2px';
                                document.querySelector('{selector}').style.boxShadow = '0 0 20px rgba(255,68,68,0.5)';
                            """)
                        break
                except Exception as e:
                    logger.debug(f"Could not process highlight element {selector}: {e}")
        
        # Capture screenshot
        screenshot_options = {
            "path": screenshot_path,
            "animations": "disabled",
            "caret": "hide"
        }
        
        if clip_region:
            screenshot_options["clip"] = clip_region
        elif full_page:
            screenshot_options["full_page"] = True
        # else: viewport screenshot (default)
        
        await self.page.screenshot(**screenshot_options)
        
        # Remove highlights
        if highlight_elements:
            for selector in highlight_elements:
                try:
                    await self.page.evaluate(f"""
                        const elem = document.querySelector('{selector}');
                        if (elem) {{
                            elem.style.outline = '';
                            elem.style.boxShadow = '';
                        }}
                    """)
                except:
                    pass
        
        # Capture metadata
        metadata = {
            "url": await self.get_url(),
            "title": await self.page.title(),
            "timestamp": time.time(),
            "step": step,
            "modals": len(self.detected_modals) > 0,
            "viewport": self.page.viewport_size,
            "cropped": clip_region is not None,
            "clip_region": clip_region
        }
        
        # Save metadata
        metadata_path = screenshot_path.replace('.png', '_metadata.json')
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        logger.log_action("screenshot", {"path": screenshot_path, "step": step, "cropped": clip_region is not None})
        return screenshot_path
    
    async def wait_for_navigation_complete(self, timeout: Optional[int] = None):
        """Wait for navigation to complete with multiple checks"""
        timeout = timeout or self.timeout
        
        async def navigation_complete():
            # Check multiple conditions
            ready_state = await self.page.evaluate("document.readyState")
            if ready_state != "complete":
                return False
            
            # Check for pending requests
            pending = await self.page.evaluate("""
                () => {
                    const entries = performance.getEntriesByType('resource');
                    const now = performance.now();
                    return entries.some(e => e.responseEnd === 0 && (now - e.startTime) < 1000);
                }
            """)
            
            return not pending
        
        start_time = time.time()
        while time.time() - start_time < timeout / 1000:
            if await navigation_complete():
                return
            await asyncio.sleep(0.1)
    
    async def close(self, save_state: bool = True):
        """Close browser and optionally save context state"""
        if self.context:
            if save_state and self.context_state_file:
                await self.save_context_state()
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("Browser closed")

    async def screenshot(self, app: str, task: str, step: int, full_page: bool = True):
        """Backward compatible screenshot method"""
        return await self.smart_screenshot(app, task, step, full_page)
    
    async def wait_for_selector(self, selector: str, timeout: Optional[int] = None):
        """Backward compatible wait method"""
        await self.wait_for_element(selector, timeout=timeout)
    
    async def wait_for_load_state(self, state: str = "networkidle"):
        if not self.page:
            raise RuntimeError("Browser not started")
        try:
            await self.page.wait_for_load_state(state, timeout=self.timeout)
        except Exception as e:
            logger.warning(f"Wait for {state} timeout, trying domcontentloaded: {e}")
            await self.page.wait_for_load_state("domcontentloaded", timeout=self.timeout)
    
    async def get_page_html(self) -> str:
        """Get the HTML content of the current page"""
        if not self.page:
            raise RuntimeError("Browser not started")
        return await self.page.content()
    
    async def get_text(self, selector: str) -> str:
        """Get text content from a selector"""
        if not self.page:
            raise RuntimeError("Browser not started")
        if selector == "body":
            return await self.get_page_text()
        element = await self.page.query_selector(selector)
        if element:
            return await element.inner_text() or ""
        return ""
    
    async def get_page_text(self) -> str:
        """Get the visible text content of the page"""
        if not self.page:
            raise RuntimeError("Browser not started")
        return await self.page.inner_text("body") or ""
    
    async def find_element_by_text(self, text: str, element_type: str = "button") -> Optional[str]:
        """Find a CSS selector for an element by its visible text"""
        if not self.page:
            raise RuntimeError("Browser not started")
        
        try:
            # Enhanced selectors with more options
            selectors = [
                f"{element_type}:has-text('{text}')",
                f"{element_type}:text-is('{text}')",
                f"text='{text}'",
                f"[aria-label*='{text}' i]",
                f"[title*='{text}' i]",
                f"a:has-text('{text}')",
                f"button:has-text('{text}')",
                f"span:has-text('{text}')",
                f"div:has-text('{text}')",
                f"input[type='button'][value*='{text}' i]",
                f"input[type='submit'][value*='{text}' i]",
                f"*:has-text('{text}')"  # Any element
            ]
            
            # Also try case variations
            text_lower = text.lower()
            text_upper = text.upper()
            text_title = text.title()
            
            for case_text in [text, text_lower, text_upper, text_title]:
                for selector in selectors:
                    selector_with_case = selector.replace(text, case_text)
                    try:
                        elements = await self.page.query_selector_all(selector_with_case)
                        if elements:
                            for element in elements[:5]:  # Check first 5 matches
                                is_visible = await element.is_visible()
                                if is_visible:
                                    # Get a more specific selector
                                    element_id = await element.get_attribute("id")
                                    if element_id:
                                        return f"#{element_id}"
                                    
                                    element_class = await element.get_attribute("class")
                                    if element_class:
                                        classes = element_class.split()
                                        if classes:
                                            return f".{classes[0]}"
                                    
                                    # Get data attributes
                                    attrs = await element.evaluate("""
                                        el => {
                                            const attrs = {};
                                            for (const attr of el.attributes) {
                                                if (attr.name.startsWith('data-')) {
                                                    attrs[attr.name] = attr.value;
                                                }
                                            }
                                            return attrs;
                                        }
                                    """)
                                    
                                    for attr_name, attr_value in attrs.items():
                                        return f"[{attr_name}='{attr_value}']"
                                    
                                    # Return the working selector
                                    return selector_with_case
                    except:
                        continue
            
            return None
        except Exception as e:
            logger.warning(f"Failed to find element by text '{text}': {e}")
            return None
    
    async def evaluate_selector(self, selector: str) -> bool:
        """Check if a selector exists on the page"""
        if not self.page:
            raise RuntimeError("Browser not started")
        
        try:
            element = await self.page.query_selector(selector)
            return element is not None
        except Exception as e:
            logger.warning(f"Error evaluating selector '{selector}': {e}")
            return False
    
    async def check_login_required(self) -> Dict[str, Any]:
        """Enhanced login detection with more patterns"""
        if not self.page:
            raise RuntimeError("Browser not started")
        
        try:
            current_url = await self.get_url()
            page_text = await self.get_page_text()
            page_html = await self.get_page_html()
            
            # Enhanced login indicators
            login_indicators = [
                "sign in", "log in", "login", "email", "password", 
                "create account", "sign up", "authentication", "forgot password",
                "continue with", "sign in with", "register", "authenticate",
                "get started", "join now", "create your account"
            ]
            
            text_lower = page_text.lower()
            has_login_text = any(indicator in text_lower for indicator in login_indicators)
            
            # Check URL patterns
            login_urls = ["/login", "/signin", "/auth", "/sign-in", "/signup", 
                         "/register", "/accounts", "/session", "/sso"]
            is_login_page = any(url in current_url.lower() for url in login_urls)
            
            # Enhanced form detection
            has_email_input = await self.evaluate_selector("input[type='email']") or \
                            await self.evaluate_selector("input[name*='email' i]") or \
                            await self.evaluate_selector("input[placeholder*='email' i]")
            
            has_password_input = await self.evaluate_selector("input[type='password']") or \
                               await self.evaluate_selector("input[name*='password' i]")
            
            has_login_form = has_email_input and has_password_input
            
            # Enhanced OAuth detection
            oauth_providers = []
            oauth_patterns = {
                "google": ["google", "continue with google", "sign in with google"],
                "github": ["github", "continue with github", "sign in with github"],
                "microsoft": ["microsoft", "continue with microsoft", "sign in with microsoft"],
                "apple": ["apple", "continue with apple", "sign in with apple"],
                "facebook": ["facebook", "continue with facebook", "sign in with facebook"],
                "twitter": ["twitter", "continue with twitter", "sign in with twitter"],
                "linkedin": ["linkedin", "continue with linkedin", "sign in with linkedin"]
            }
            
            for provider, patterns in oauth_patterns.items():
                if any(pattern in text_lower for pattern in patterns):
                    oauth_providers.append(provider)
            
            # Check for SSO
            has_sso = "single sign-on" in text_lower or "sso" in text_lower
            
            # Be more conservative: only require login if we're actually on a login page
            # or if there's a login form AND we're blocked from content
            requires_login = is_login_page or (has_login_form and is_login_page) or \
                           (is_login_page and len(oauth_providers) > 0)
            
            logger.info(f"Login check: requires_login={requires_login}, has_form={has_login_form}, "
                       f"is_login_page={is_login_page}, oauth_providers={oauth_providers}")
            
            return {
                "requires_login": requires_login,
                "has_login_form": has_login_form,
                "is_login_page": is_login_page,
                "current_url": current_url,
                "has_email_input": has_email_input,
                "has_password_input": has_password_input,
                "oauth_providers": oauth_providers,
                "has_password_form": has_password_input,
                "has_sso": has_sso
            }
        except Exception as e:
            logger.error(f"Error checking login requirement: {e}")
            return {
                "requires_login": False,
                "has_login_form": False,
                "is_login_page": False,
                "current_url": "",
                "error": str(e)
            }
    
    async def get_url(self) -> str:
        if not self.page:
            return ""
        return self.page.url
    
    async def save_context_state(self, file_path: Optional[str] = None):
        """Save browser context state (cookies, localStorage, etc.) to file"""
        if not self.context:
            raise RuntimeError("Browser context not available")
        
        save_path = file_path or self.context_state_file
        if not save_path:
            logger.warning("No file path provided for saving context state")
            return False
        
        try:
            ensure_dir(os.path.dirname(save_path))
            await self.context.storage_state(path=save_path)
            logger.info(f"Browser context state saved to {save_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save context state: {e}")
            return False