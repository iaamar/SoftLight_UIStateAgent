from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import os
import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from utils.logger import get_logger
from utils.browser_controller import BrowserController
from graph.workflow import AgentWorkflow
from utils.helpers import sanitize_filename
from agents.ui_navigator_agent import UINavigatorAgent
from utils.dataset_exporter import DatasetExporter

# Load .env file - check both mounted path and current directory
env_file = os.getenv("ENV_FILE", ".env")
try:
    if os.path.exists(env_file):
        load_dotenv(env_file, override=True)
    else:
        load_dotenv(override=True)
except (PermissionError, OSError):
    # If we can't access the file directly, try loading from current directory
    load_dotenv(override=True)
logger = get_logger(name="api")

app = FastAPI(title="SoftLight UI State Agent API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

data_dir = Path(__file__).parent.parent / "data"
if data_dir.exists():
    app.mount("/data", StaticFiles(directory=str(data_dir)), name="data")


class TaskRequest(BaseModel):
    task_query: str
    app_url: str
    app_name: str
    task_name: Optional[str] = None
    capture_metadata: Optional[bool] = True
    headless: Optional[bool] = True


class TaskResponse(BaseModel):
    success: bool
    screenshots: List[str]
    step_descriptions: Optional[List[str]] = None
    steps_completed: int
    error: Optional[str] = None
    final_url: Optional[str] = None
    requires_login: Optional[bool] = False
    login_url: Optional[str] = None
    app_name: Optional[str] = None
    original_task: Optional[str] = None
    oauth_providers: Optional[List[str]] = None
    has_password_form: Optional[bool] = False
    # Enhanced features
    ui_states_captured: Optional[int] = 0
    modals_detected: Optional[int] = 0
    forms_filled: Optional[int] = 0
    execution_time: Optional[float] = 0


class LoginRequest(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    app_name: str
    app_url: str
    original_task: Optional[str] = None
    login_method: Optional[str] = "email_password"  # "email_password" or "oauth_google", "oauth_github", etc.


class LoginResponse(BaseModel):
    success: bool
    message: str
    task_result: Optional[Dict[str, Any]] = None


@app.get("/")
async def root():
    return {
        "message": "SoftLight UI State Agent API",
        "version": "2.0.0",
        "status": "running",
        "features": [
            "Enhanced browser automation",
            "Modal and popup detection",
            "Dynamic content handling",
            "Form interaction tracking",
            "Comprehensive UI state capture"
        ]
    }


@app.get("/health")
async def health():
    openai_key = os.getenv("OPENAI_API_KEY")
    return {
        "status": "healthy",
        "openai_configured": bool(openai_key and openai_key.strip())
    }


@app.get("/api/v1/screenshot/{file_path:path}")
async def get_screenshot(file_path: str):
    screenshot_path = data_dir / "screenshots" / file_path
    if screenshot_path.exists() and screenshot_path.is_file():
        return FileResponse(str(screenshot_path))
    raise HTTPException(status_code=404, detail="Screenshot not found")


@app.post("/api/v1/execute", response_model=TaskResponse)
async def execute_task(request: TaskRequest):
    logger.info(f"Task request received: {request.task_query}")
    
    # Check for OpenAI API key
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key or not openai_key.strip():
        error_msg = (
            "OPENAI_API_KEY not found or is empty in environment. "
            "Please ensure your .env file contains: OPENAI_API_KEY=sk-... "
            "(with your actual API key, no spaces around the = sign)"
        )
        logger.error(error_msg)
        logger.debug(f"ENV_FILE={os.getenv('ENV_FILE')}, Current dir={os.getcwd()}")
        raise HTTPException(status_code=400, detail=error_msg)
    
    browser = None
    try:
        # Create context state file path per app to persist login sessions
        data_dir = Path(__file__).parent.parent / "data"
        context_state_dir = data_dir / "sessions"
        context_state_dir.mkdir(parents=True, exist_ok=True)
        context_state_file = str(context_state_dir / f"{request.app_name}_session.json")
        
        # Check if session exists
        session_exists = os.path.exists(context_state_file)
        
        # Use headless by default, but can be overridden per request
        use_headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
        browser = BrowserController(
            headless=use_headless,
            browser_type=os.getenv("PLAYWRIGHT_BROWSER", "chromium"),
            timeout=int(os.getenv("PLAYWRIGHT_TIMEOUT", "60000")),
            viewport_width=int(os.getenv("PLAYWRIGHT_VIEWPORT_WIDTH", "1920")),
            viewport_height=int(os.getenv("PLAYWRIGHT_VIEWPORT_HEIGHT", "1080")),
            context_state_file=context_state_file,
            locale=os.getenv("BROWSER_LOCALE", "en-US"),
            timezone=os.getenv("BROWSER_TIMEZONE", "America/New_York")
        )
        
        await browser.start()
        
        # Navigate to app URL first
        await browser.navigate(request.app_url)
        await browser.wait_for_load_state("domcontentloaded")
        
        # Wait for any redirects to settle (important for auth redirects)
        await asyncio.sleep(2)
        
        # Check final URL after navigation (might have redirected to login)
        final_url = await browser.get_url()
        logger.info(f"Initial URL: {request.app_url}, Final URL after navigation: {final_url}")
        
        # Detect if user provided a direct authenticated page URL
        is_direct_url = "/" in request.app_url.split("//")[-1].split("/", 1)[1] if "//" in request.app_url and "/" in request.app_url.split("//")[-1] else False
        
        # Check if we were redirected to login
        login_url_patterns = ["/login", "/signin", "/auth", "/sign-in", "/sign-up", "/signup"]
        url_redirected_to_login = any(pattern in final_url.lower() for pattern in login_url_patterns)
        
        # Also check if on external auth domain
        original_domain = request.app_url.split("//")[-1].split("/")[0] if "//" in request.app_url else ""
        final_domain = final_url.split("//")[-1].split("/")[0] if "//" in final_url else ""
        is_auth_domain = any(domain in final_domain for domain in [
            "accounts.google.com", "login.microsoftonline.com", 
            "appleid.apple.com", "auth0.com", "okta.com"
        ])
        
        # Check if login is required
        login_check = await browser.check_login_required()
        
        # If URL redirected to login page, definitely needs login
        if (url_redirected_to_login or is_auth_domain) and not login_check.get("requires_login", False):
            logger.info(f"URL redirected to login/auth page: {final_url}")
            login_check["requires_login"] = True
            login_check["current_url"] = final_url
        
        if login_check.get("requires_login", False):
            # Check if we're in an environment that supports headed browser
            import platform
            is_docker = os.path.exists("/.dockerenv") or os.getenv("DOCKER_CONTAINER") == "true"
            view_browser = os.getenv("VIEW_BROWSER", "false").lower() == "true"
            
            # Detect if we can open a visible browser
            # On macOS: Playwright works natively without DISPLAY env var
            # On Linux: Need DISPLAY env var or X11 session
            # On Windows: Always works
            # In Docker: Need DISPLAY (xvfb) or VIEW_BROWSER=true
            system = platform.system()
            display_available = False
            
            if is_docker:
                # In Docker, need DISPLAY env var (xvfb) or VIEW_BROWSER=true
                display_available = os.getenv("DISPLAY") is not None or view_browser
            elif system == "Darwin":  # macOS
                # macOS can always open browsers natively
                display_available = True
            elif system == "Windows":
                # Windows always works
                display_available = True
            elif system == "Linux":
                # Linux: check for DISPLAY or GUI session
                display_available = (
                    os.getenv("DISPLAY") is not None or
                    os.getenv("XDG_SESSION_TYPE") == "x11" or
                    os.getenv("WAYLAND_DISPLAY") is not None
                )
            
            # In Docker without display support, use login endpoint
            if is_docker and not display_available and not view_browser:
                # Docker without display - can't open headed browser
                await browser.close()
                logger.warning("Login required but running in Docker without display support.")
                logger.info("Please use /api/v1/login endpoint for login, or set VIEW_BROWSER=true in docker-compose.yml")
                
                # Detect available OAuth providers
                available_providers = login_check.get("oauth_providers", [])
                if not available_providers:
                    # Quick scan before closing
                    oauth_provider_selectors = {
                        "google": ["button:has-text('Google')", "[data-provider='google']"],
                        "github": ["button:has-text('GitHub')", "[data-provider='github']"],
                        "microsoft": ["button:has-text('Microsoft')", "[data-provider='microsoft']"],
                        "apple": ["button:has-text('Apple')", "[data-provider='apple']"],
                        "sso": ["button:has-text('SSO')", "[data-provider='sso']"]
                    }
                    for provider, selectors in oauth_provider_selectors.items():
                        for selector in selectors:
                            try:
                                if await browser.evaluate_selector(selector):
                                    if provider not in available_providers:
                                        available_providers.append(provider)
                                    break
                            except:
                                pass
                
                return TaskResponse(
                    success=False,
                    requires_login=True,
                    login_url=final_url,
                    app_name=request.app_name,
                    original_task=request.task_query,
                    screenshots=[],
                    steps_completed=0,
                    error="Login required. In Docker environment, please use /api/v1/login endpoint or set VIEW_BROWSER=true to enable visual browser.",
                    oauth_providers=available_providers,
                    has_password_form=login_check.get("has_password_form", False)
                )
            
            # Close current browser (might be headless)
            await browser.close()
            
            # Reopen browser in HEADED mode for interactive login
            # On local (non-Docker), always use headed mode for better UX
            use_headless_for_login = not display_available
            
            if not use_headless_for_login:
                logger.info(f"Login required for {request.app_name}. Opening browser in visible mode for login...")
                if is_docker:
                    logger.info(f"💡 Connect to http://localhost:7900/vnc.html to view the browser")
                else:
                    logger.info(f"💡 Browser window will open automatically on your screen")
            else:
                logger.warning(f"Display not available - cannot open visible browser for login")
                logger.info(f"Please use /api/v1/login endpoint or enable VIEW_BROWSER=true")
            
            # Don't load existing session for login - start fresh to avoid conflicts
            browser = BrowserController(
                headless=use_headless_for_login,  # Only use headed if display available
                browser_type=os.getenv("PLAYWRIGHT_BROWSER", "chromium"),
                timeout=int(os.getenv("PLAYWRIGHT_TIMEOUT", "60000")),
                viewport_width=int(os.getenv("PLAYWRIGHT_VIEWPORT_WIDTH", "1920")),
                viewport_height=int(os.getenv("PLAYWRIGHT_VIEWPORT_HEIGHT", "1080")),
                context_state_file=None,  # Don't load session for login flow - start fresh
                locale=os.getenv("BROWSER_LOCALE", "en-US"),
                timezone=os.getenv("BROWSER_TIMEZONE", "America/New_York")
            )
            
            try:
                await browser.start()
                # Give browser extra time to fully initialize in headed mode
                await asyncio.sleep(1)
            except Exception as e:
                # If browser start fails (no display), fall back to login endpoint
                if "Target page" in str(e) or "XServer" in str(e) or "closed" in str(e).lower():
                    logger.error(f"Failed to start browser: {e}")
                    logger.info("Falling back to login endpoint approach")
                    available_providers = login_check.get("oauth_providers", [])
                    return TaskResponse(
                        success=False,
                        requires_login=True,
                        login_url=final_url,
                        app_name=request.app_name,
                        original_task=request.task_query,
                        screenshots=[],
                        steps_completed=0,
                        error="Login required. Please use /api/v1/login endpoint for authentication.",
                        oauth_providers=available_providers,
                        has_password_form=login_check.get("has_password_form", False)
                    )
                raise
            
            # Navigate to the URL again (or to login page if redirected)
            await browser.navigate(request.app_url)
            await browser.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(2)
            
            current_url = await browser.get_url()
            logger.info(f"Browser opened at: {current_url}")
            
            if not use_headless_for_login:
                logger.info(f"📝 Please complete login in the browser window that opened.")
                if is_docker:
                    logger.info(f"💡 View browser at: http://localhost:7900/vnc.html")
                logger.info(f"💡 The system will automatically detect when login is complete and continue with your task.")
            else:
                logger.info(f"⚠️ Browser running in headless mode - login detection may be limited")
            
            # Detect available OAuth providers from the page
            current_login_check = await browser.check_login_required()
            available_providers = current_login_check.get("oauth_providers", [])
            
            # If no providers detected, scan the page for OAuth buttons
            if not available_providers:
                oauth_provider_selectors = {
                    "google": [
                        "button:has-text('Google')",
                        "button:has-text('Sign in with Google')",
                        "button:has-text('Continue with Google')",
                        "[data-provider='google']"
                    ],
                    "github": [
                        "button:has-text('GitHub')",
                        "button:has-text('Sign in with GitHub')",
                        "[data-provider='github']"
                    ],
                    "microsoft": [
                        "button:has-text('Microsoft')",
                        "button:has-text('Sign in with Microsoft')",
                        "[data-provider='microsoft']"
                    ],
                    "apple": [
                        "button:has-text('Apple')",
                        "button:has-text('Sign in with Apple')",
                        "[data-provider='apple']"
                    ],
                    "sso": [
                        "button:has-text('SSO')",
                        "button:has-text('Single Sign-On')",
                        "[data-provider='sso']"
                    ]
                }
                
                for provider, selectors in oauth_provider_selectors.items():
                    for selector in selectors:
                        try:
                            if await browser.evaluate_selector(selector):
                                if provider not in available_providers:
                                    available_providers.append(provider)
                                break
                        except:
                            continue
            
            logger.info(f"Detected OAuth providers: {available_providers}")
            
            # Wait for user to complete login in the browser window
            logger.info(f"⏳ Waiting for login to complete... (max 5 minutes)")
            max_wait = 300  # 5 minutes
            waited = 0
            login_success = False
            initial_url = current_url
            
            while waited < max_wait:
                await asyncio.sleep(3)  # Check every 3 seconds
                waited += 3
                
                try:
                    current_url_check = await browser.get_url()
                    
                    # Check if still on login page
                    still_on_login = any(pattern in current_url_check.lower() for pattern in login_url_patterns)
                    still_on_auth_domain = any(domain in current_url_check.split("//")[-1].split("/")[0] for domain in [
                        "accounts.google.com", "login.microsoftonline.com", 
                        "appleid.apple.com", "auth0.com", "okta.com"
                    ])
                    
                    # If not on login page and not on auth domain, check if authenticated
                    if not still_on_login and not still_on_auth_domain:
                        # Verify by checking if login is still required
                        new_login_check = await browser.check_login_required()
                        if not new_login_check.get("requires_login", False):
                            logger.info(f"✅ Login successful! Detected authenticated page: {current_url_check}")
                            # If user provided direct URL, check if we reached it or equivalent
                            if is_direct_url:
                                original_path = request.app_url.split("//")[-1].split("/", 1)[1] if "/" in request.app_url.split("//")[-1] else ""
                                current_path = current_url_check.split("//")[-1].split("/", 1)[1] if "/" in current_url_check.split("//")[-1] else ""
                                if original_path in current_path or request.app_url in current_url_check:
                                    logger.info(f"✅ Successfully accessed target page: {current_url_check}")
                                else:
                                    logger.info(f"ℹ️ Navigated to authenticated page (different from target): {current_url_check}")
                            # Save the new session
                            await browser.save_context_state()
                            login_success = True
                            break
                        elif current_url_check != initial_url:
                            # URL changed but still might be on login flow
                            logger.debug(f"URL changed to: {current_url_check}, still checking...")
                    
                    # Log progress every 15 seconds
                    if waited % 15 == 0:
                        if still_on_login or still_on_auth_domain:
                            logger.info(f"⏳ Still on login page... (waited {waited}s) - Please complete login")
                        else:
                            logger.info(f"⏳ Verifying authentication... (waited {waited}s)")
                            
                except Exception as e:
                    logger.warning(f"Error checking login status: {e}")
                    continue
            
            if not login_success:
                await browser.close()
                logger.warning(f"⚠️ Login timeout after {max_wait}s")
                return TaskResponse(
                    success=False,
                    requires_login=True,
                    login_url=current_url,
                    app_name=request.app_name,
                    original_task=request.task_query,
                    screenshots=[],
                    steps_completed=0,
                    error=f"Login timeout - please use /api/v1/login endpoint or complete login within {max_wait}s",
                    oauth_providers=available_providers,
                    has_password_form=current_login_check.get("has_password_form", False)
                )
            
            # Login successful! Continue with task execution using the same browser
            logger.info(f"✅ Login completed successfully! Continuing with task execution...")
            
            # If user provided a direct URL and we're not on it, navigate to it
            current_url_after_login = await browser.get_url()
            if is_direct_url and request.app_url not in current_url_after_login:
                logger.info(f"Navigating to original target URL: {request.app_url}")
                try:
                    await browser.navigate(request.app_url)
                    await browser.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(2)
                    final_target_url = await browser.get_url()
                    logger.info(f"Navigated to: {final_target_url}")
                except Exception as e:
                    logger.warning(f"Could not navigate to target URL, continuing with current page: {e}")
            
            # Don't close browser - we'll use it for the task
        
        # Create progress callback
        async def send_progress(step: int, total_steps: int, description: str, current_action: str = None):
            await progress_manager.broadcast({
                "step": step,
                "total_steps": total_steps,
                "description": description,
                "current_action": current_action or description
            })
        
        workflow = AgentWorkflow(
            browser=browser,
            llm_model=os.getenv("CREWAI_LLM_MODEL", "claude-sonnet-4-5-20250929"),
            max_steps=int(os.getenv("LANGGRAPH_MAX_STEPS", "50")),
            retry_attempts=int(os.getenv("LANGGRAPH_RETRY_ATTEMPTS", "3")),
            capture_metadata=request.capture_metadata,
            progress_callback=send_progress
        )
        
        task_name = request.task_name or sanitize_filename(request.task_query)
        
        result = await workflow.execute(
            task_query=request.task_query,
            app_url=request.app_url,
            app_name=request.app_name,
            task_name=task_name
        )
        
        screenshot_urls = []
        screenshot_metadata = result.get("screenshot_metadata", [])
        
        # Create a mapping of original paths to new URLs
        path_to_url = {}
        for screenshot_path in result.get("screenshots", []):
            if screenshot_path.startswith("./data/screenshots/"):
                url = screenshot_path.replace("./data/screenshots/", "")
            elif screenshot_path.startswith("data/screenshots/"):
                url = screenshot_path.replace("data/screenshots/", "")
            else:
                url = screenshot_path
            screenshot_urls.append(url)
            path_to_url[screenshot_path] = url
        
        # Update screenshot metadata with new URLs
        updated_metadata = []
        for meta in screenshot_metadata:
            original_path = meta.get("path", "")
            new_url = path_to_url.get(original_path, original_path.replace("./data/screenshots/", "").replace("data/screenshots/", ""))
            updated_metadata.append({
                "path": new_url,
                "step_index": meta.get("step_index", -1),
                "step_number": meta.get("step_number", None)
            })
        
        result["screenshots"] = screenshot_urls
        result["screenshot_metadata"] = updated_metadata
        
        return TaskResponse(**result)
    
    except Exception as e:
        logger.log_error(e, context={"endpoint": "execute_task"})
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        if browser:
            await browser.close()


@app.post("/api/v1/login", response_model=LoginResponse)
async def perform_login(login_request: LoginRequest):
    """Handle login and optionally resume original task"""
    logger.info(f"Login request received for {login_request.app_name} with method: {login_request.login_method}")
    
    browser = None
    try:
        # Create context state file path
        data_dir = Path(__file__).parent.parent / "data"
        context_state_dir = data_dir / "sessions"
        context_state_dir.mkdir(parents=True, exist_ok=True)
        context_state_file = str(context_state_dir / f"{login_request.app_name}_session.json")
        
        # Always use headed mode during login so browser window appears
        # Don't load existing session - start fresh for login
        browser = BrowserController(
            headless=False,  # Browser window will open for user to complete login
            browser_type=os.getenv("PLAYWRIGHT_BROWSER", "chromium"),
            timeout=int(os.getenv("PLAYWRIGHT_TIMEOUT", "60000")),
            viewport_width=int(os.getenv("PLAYWRIGHT_VIEWPORT_WIDTH", "1920")),
            viewport_height=int(os.getenv("PLAYWRIGHT_VIEWPORT_HEIGHT", "1080")),
            context_state_file=None  # Start fresh for login, don't load old session
        )
        
        await browser.start()
        # Give browser time to fully initialize
        await asyncio.sleep(1)
        await browser.navigate(login_request.app_url)
        await browser.wait_for_load_state("domcontentloaded")
        
        # Handle OAuth login
        if login_request.login_method and login_request.login_method.startswith("oauth_"):
            provider = login_request.login_method.replace("oauth_", "")
            logger.info(f"Attempting OAuth login with {provider}")

            # Special case: when authenticating to GitHub itself, prefer direct login page
            if provider == "github" and ("github.com" in login_request.app_url.lower()):
                logger.info("GitHub app detected; opening native GitHub login page for manual sign-in")
                await browser.navigate("https://github.com/login")
                await browser.wait_for_load_state("domcontentloaded")
                logger.info("Browser window opened for login - please complete authentication")
                import asyncio
                max_wait = 300
                waited = 0
                initial_url = await browser.get_url()
                while waited < max_wait:
                    await asyncio.sleep(2)
                    waited += 2
                    try:
                        current_url = await browser.get_url()
                        if "/login" not in current_url.lower() and "github.com" in current_url.lower():
                            logger.info(f"GitHub login appears complete: {current_url}")
                            break
                        # Avatar presence heuristic
                        if await browser.evaluate_selector("summary[aria-label*='View profile']"):
                            logger.info("Detected logged-in avatar on GitHub")
                            break
                    except Exception:
                        pass
                await asyncio.sleep(2)
                await browser.wait_for_load_state("domcontentloaded")
            else:
                # Find OAuth button on third-party app login page
                oauth_selectors = {
                    "google": [
                        "button:has-text('Google')",
                        "button:has-text('Sign in with Google')",
                        "button:has-text('Continue with Google')",
                        "button[aria-label*='Google' i]",
                        "[data-provider='google']",
                        "[data-testid*='google']",
                        "a[href*='google.com']"
                    ],
                    "github": [
                        "button:has-text('GitHub')",
                        "button:has-text('Sign in with GitHub')",
                        "button:has-text('Continue with GitHub')",
                        "button[aria-label*='GitHub' i]",
                        "[data-provider='github']",
                        "[data-testid*='github']"
                    ],
                    "microsoft": [
                        "button:has-text('Microsoft')",
                        "button:has-text('Sign in with Microsoft')",
                        "button:has-text('Continue with Microsoft')",
                        "button[aria-label*='Microsoft' i]",
                        "[data-provider='microsoft']",
                        "[data-testid*='microsoft']"
                    ],
                    "apple": [
                        "button:has-text('Apple')",
                        "button:has-text('Sign in with Apple')",
                        "button:has-text('Continue with Apple')",
                        "button[aria-label*='Apple' i]",
                        "[data-provider='apple']",
                        "[data-testid*='apple']"
                    ],
                    "sso": [
                        "button:has-text('SSO')",
                        "button:has-text('Single Sign-On')",
                        "button:has-text('Sign in with SSO')",
                        "button:has-text('Continue with SSO')",
                        "button[aria-label*='SSO' i]",
                        "[data-provider='sso']",
                        "[data-testid*='sso']"
                    ]
                }
                selectors = oauth_selectors.get(provider, [])
                oauth_clicked = False
                for selector in selectors:
                    try:
                        if await browser.evaluate_selector(selector):
                            await browser.click(selector)
                            oauth_clicked = True
                            logger.info(f"Clicked {provider} OAuth button using selector: {selector}")
                            break
                    except Exception as e:
                        logger.warning(f"Failed to click OAuth button with {selector}: {e}")
                        continue
                if not oauth_clicked:
                    raise ValueError(f"Could not find {provider} OAuth button")

                # Handle popup
                popup_page = None
                try:
                    popup_page = await browser.context.wait_for_event("page", timeout=5000)
                    logger.info("OAuth popup detected, waiting for it to complete...")
                    await popup_page.wait_for_load_state("domcontentloaded")
                except Exception:
                    logger.info("No OAuth popup detected; continuing in current page")

                # Wait for redirect
                logger.info("Waiting for OAuth flow to complete...")
                logger.info("Browser window opened - please complete OAuth authentication")
                import asyncio
                max_wait = 180
                waited = 0
                
                def is_app_url(url: str) -> bool:
                    """Robust URL detection for any application"""
                    lowered = url.lower()
                    app_domain = login_request.app_url.split("//")[-1].split("/")[0].split(":")[0]
                    
                    # Common authentication URLs to exclude
                    auth_urls = [
                        "/login", "/signin", "/auth", "/sign-in", "/sign-up", "/signup",
                        "/session", "/authorize", "/oauth",
                        "accounts.google.com",
                        "github.com/login", "github.com/session",
                        "login.microsoftonline.com",
                        "appleid.apple.com",
                        "auth0.com",
                        "okta.com"
                    ]
                    
                    # Check if URL is an authentication page
                    is_auth_page = any(auth_url in lowered for auth_url in auth_urls)
                    
                    # Special handling for specific apps
                    if "linear.app" in lowered or "linear.app" in app_domain:
                        return not is_auth_page and ("linear.app" in lowered)
                    
                    if "notion.so" in lowered or "notion.so" in app_domain:
                        return not is_auth_page and ("notion.so" in lowered)
                    
                    if "github.com" in lowered or "github.com" in app_domain:
                        return "github.com" in lowered and not is_auth_page
                    
                    # Generic check: app domain and not auth page
                    return app_domain in lowered and not is_auth_page
                
                initial_url = await browser.get_url()
                logger.info(f"Starting OAuth wait from URL: {initial_url}")
                
                while waited < max_wait:
                    await asyncio.sleep(2)
                    waited += 2
                    try:
                        if popup_page and not popup_page.is_closed():
                            current_url = popup_page.url
                            if waited % 10 == 0:  # Log every 10s
                                logger.info(f"Popup URL at {waited}s: {current_url}")
                            if is_app_url(current_url):
                                logger.info(f"OAuth completed via popup: {current_url}")
                                try:
                                    await popup_page.close()
                                except Exception:
                                    pass
                                break
                        else:
                            current_url = await browser.get_url()
                            if waited % 10 == 0:  # Log every 10s
                                logger.info(f"Main page URL at {waited}s: {current_url}")
                            if current_url != initial_url and is_app_url(current_url):
                                logger.info(f"OAuth redirect detected in main page: {current_url}")
                                break
                    except Exception as e:
                        if waited % 20 == 0:
                            logger.debug(f"Polling exception: {e}")
                
                logger.info(f"OAuth wait ended after {waited}s")
                await asyncio.sleep(2)
                await browser.wait_for_load_state("domcontentloaded")
            
        else:
            # Handle email/password login
            if not login_request.email or not login_request.password:
                raise ValueError("Email and password are required for email/password login")
            
            email_selectors = [
                "input[type='email']",
                "input[type=\"email\"]",
                "input[name*='email' i]",
                "input[id*='email' i]",
                "input[placeholder*='email' i]",
                "input[autocomplete='email']",
                "input[autocomplete=\"email\"]"
            ]
            
            password_selectors = [
                "input[type='password']",
                "input[type=\"password\"]",
                "input[name*='password' i]",
                "input[id*='password' i]",
                "input[autocomplete='current-password']",
                "input[autocomplete=\"current-password\"]"
            ]
            
            submit_selectors = [
                "button[type='submit']",
                "button[type=\"submit\"]",
                "input[type='submit']",
                "input[type=\"submit\"]",
                "button:has-text('sign in')",
                "button:has-text('log in')",
                "button:has-text('login')",
                "button:has-text('Sign In')",
                "button:has-text('Log In')"
            ]
            
            # Find and fill email
            email_filled = False
            for email_sel in email_selectors:
                try:
                    if await browser.evaluate_selector(email_sel):
                        await browser.type(email_sel, login_request.email)
                        email_filled = True
                        logger.info(f"Email filled using selector: {email_sel}")
                        break
                except Exception as e:
                    logger.warning(f"Failed to fill email with {email_sel}: {e}")
                    continue
            
            if not email_filled:
                raise ValueError("Could not find email input field")
            
            await asyncio.sleep(0.5)
            
            # Find and fill password
            password_filled = False
            for pwd_sel in password_selectors:
                try:
                    if await browser.evaluate_selector(pwd_sel):
                        await browser.type(pwd_sel, login_request.password)
                        password_filled = True
                        logger.info(f"Password filled using selector: {pwd_sel}")
                        break
                except Exception as e:
                    logger.warning(f"Failed to fill password with {pwd_sel}: {e}")
                    continue
            
            if not password_filled:
                raise ValueError("Could not find password input field")
            
            await asyncio.sleep(0.5)
            
            # Find and click submit button
            submit_clicked = False
            for submit_sel in submit_selectors:
                try:
                    if await browser.evaluate_selector(submit_sel):
                        await browser.click(submit_sel)
                        submit_clicked = True
                        logger.info(f"Submit clicked using selector: {submit_sel}")
                        break
                except Exception as e:
                    logger.warning(f"Failed to click submit with {submit_sel}: {e}")
                    continue
            
            if not submit_clicked:
                # Try pressing Enter as fallback
                logger.warning("Submit button not found, trying Enter key")
                try:
                    await browser.page.keyboard.press("Enter")
                except:
                    pass
            
            # Wait for login to complete
            await asyncio.sleep(3)
            await browser.wait_for_load_state("domcontentloaded")
        
        # Save session
        await browser.save_context_state()
        await browser.close()
        browser = None
        
        logger.info(f"Login successful for {login_request.app_name}")
        
        # If original task provided, resume it
        task_result = None
        if login_request.original_task:
            logger.info(f"Resuming original task: {login_request.original_task}")
            task_result = await execute_task(TaskRequest(
                task_query=login_request.original_task,
                app_url=login_request.app_url,
                app_name=login_request.app_name
            ))
            task_result = task_result.dict()
        
        return LoginResponse(
            success=True,
            message="Login successful",
            task_result=task_result
        )
        
    except Exception as e:
        logger.log_error(e, context={"endpoint": "perform_login"})
        if browser:
            await browser.close()
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")


@app.post("/api/v1/export-task")
async def export_task(request: TaskRequest):
    """Export a single task's dataset"""
    logger.info(f"Export request for {request.app_name} - {request.task_query}")
    
    # First execute the task to capture screenshots
    task_result = await execute_task(request)
    
    if not task_result.success:
        raise HTTPException(status_code=400, detail="Task execution failed")
    
    # Export the dataset
    exporter = DatasetExporter()
    export_path = exporter.export_task_dataset(
        app_name=request.app_name,
        task_query=request.task_query,
        screenshots=task_result.screenshots,
        step_descriptions=task_result.step_descriptions or [],
        metadata={
            "final_url": task_result.final_url,
            "steps_completed": task_result.steps_completed
        }
    )
    
    return {
        "success": True,
        "export_path": export_path,
        "task_result": task_result.dict()
    }


@app.post("/api/v1/export-batch")
async def export_batch(tasks: List[TaskRequest]):
    """Export multiple tasks as a dataset"""
    logger.info(f"Batch export request for {len(tasks)} tasks")
    
    results = []
    for task_request in tasks:
        try:
            result = await execute_task(task_request)
            results.append({
                "app_name": task_request.app_name,
                "task_query": task_request.task_query,
                "screenshots": result.screenshots,
                "step_descriptions": result.step_descriptions or [],
                "success": result.success,
                "capture_date": datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Failed to execute task {task_request.task_query}: {e}")
            results.append({
                "app_name": task_request.app_name,
                "task_query": task_request.task_query,
                "screenshots": [],
                "step_descriptions": [],
                "success": False,
                "error": str(e)
            })
    
    # Export the dataset
    exporter = DatasetExporter()
    export_path = exporter.export_batch_dataset(results)
    
    return {
        "success": True,
        "export_path": export_path,
        "total_tasks": len(tasks),
        "successful_tasks": sum(1 for r in results if r.get("success", False))
    }


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass


# WebSocket connection manager for progress updates
class ProgressManager:
    def __init__(self):
        self.connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.connections:
            self.connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        disconnected = []
        for connection in self.connections:
            try:
                await connection.send_json(message)
            except:
                disconnected.append(connection)
        
        for connection in disconnected:
            self.disconnect(connection)

progress_manager = ProgressManager()


@app.websocket("/ws/progress")
async def websocket_progress(websocket: WebSocket):
    await progress_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive by waiting for messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        progress_manager.disconnect(websocket)


@app.get("/api/v1/workflows")
async def list_workflows():
    """List all captured workflows"""
    screenshots_dir = data_dir / "screenshots"
    workflows = []
    
    if screenshots_dir.exists():
        for app_dir in screenshots_dir.iterdir():
            if app_dir.is_dir():
                for task_dir in app_dir.iterdir():
                    if task_dir.is_dir():
                        metadata_file = task_dir / "workflow_metadata.json"
                        if metadata_file.exists():
                            with open(metadata_file) as f:
                                metadata = json.load(f)
                                workflows.append({
                                    "app_name": app_dir.name,
                                    "task_name": task_dir.name,
                                    "task_query": metadata.get("task_query"),
                                    "screenshots": len(metadata.get("screenshots", [])),
                                    "completed": metadata.get("completed"),
                                    "execution_time": metadata.get("execution_time", 0)
                                })
    
    return {"workflows": workflows}


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("BACKEND_HOST", "0.0.0.0")
    port = int(os.getenv("BACKEND_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
