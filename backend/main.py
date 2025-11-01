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
        
        browser = BrowserController(
            headless=request.headless and os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true",
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
        
        # Check if login is required (even if session exists, it might be expired)
        login_check = await browser.check_login_required()
        
        if login_check.get("requires_login", False):
            await browser.close()
            logger.info(f"Login required for {request.app_name} (session may be expired)")
            return TaskResponse(
                success=False,
                requires_login=True,
                login_url=login_check.get("current_url", request.app_url),
                app_name=request.app_name,
                original_task=request.task_query,
                screenshots=[],
                steps_completed=0,
                error="Login required",
                oauth_providers=login_check.get("oauth_providers", []),
                has_password_form=login_check.get("has_password_form", False)
            )
        
        workflow = AgentWorkflow(
            browser=browser,
            llm_model=os.getenv("CREWAI_LLM_MODEL", "gpt-4o"),
            max_steps=int(os.getenv("LANGGRAPH_MAX_STEPS", "50")),
            retry_attempts=int(os.getenv("LANGGRAPH_RETRY_ATTEMPTS", "3")),
            capture_metadata=request.capture_metadata
        )
        
        task_name = request.task_name or sanitize_filename(request.task_query)
        
        result = await workflow.execute(
            task_query=request.task_query,
            app_url=request.app_url,
            app_name=request.app_name,
            task_name=task_name
        )
        
        screenshot_urls = []
        for screenshot_path in result.get("screenshots", []):
            if screenshot_path.startswith("./data/screenshots/"):
                screenshot_urls.append(screenshot_path.replace("./data/screenshots/", ""))
            elif screenshot_path.startswith("data/screenshots/"):
                screenshot_urls.append(screenshot_path.replace("data/screenshots/", ""))
            else:
                screenshot_urls.append(screenshot_path)
        
        result["screenshots"] = screenshot_urls
        
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
        
        headed_env = os.getenv("VIEW_BROWSER", "false").lower() == "true"
        headless_env = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
        browser = BrowserController(
            headless=(False if headed_env else headless_env),
            browser_type=os.getenv("PLAYWRIGHT_BROWSER", "chromium"),
            timeout=int(os.getenv("PLAYWRIGHT_TIMEOUT", "60000")),
            viewport_width=int(os.getenv("PLAYWRIGHT_VIEWPORT_WIDTH", "1920")),
            viewport_height=int(os.getenv("PLAYWRIGHT_VIEWPORT_HEIGHT", "1080")),
            context_state_file=context_state_file
        )
        
        await browser.start()
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
                if headed_env:
                    logger.info("Visual login mode enabled (VIEW_BROWSER=true). Open http://localhost:7900/vnc.html to complete login.")
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
                        "[aria-label*='Google' i]",
                        "[data-provider='google']",
                        "a[href*='google.com']"
                    ],
                    "github": [
                        "button:has-text('GitHub')",
                        "button:has-text('Sign in with GitHub')",
                        "[aria-label*='GitHub' i]",
                        "[data-provider='github']"
                    ],
                    "microsoft": [
                        "button:has-text('Microsoft')",
                        "button:has-text('Sign in with Microsoft')",
                        "[aria-label*='Microsoft' i]",
                        "[data-provider='microsoft']"
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
                if headed_env:
                    logger.info("Visual mode: Complete OAuth in noVNC (http://localhost:7900/vnc.html)")
                import asyncio
                max_wait = 180
                waited = 0
                def is_app_url(url: str) -> bool:
                    lowered = url.lower()
                    # GitHub-specific: accept any non-login GitHub URL
                    if "github.com" in login_request.app_url.lower():
                        return "github.com" in lowered and not any(u in lowered for u in ["/login", "/signin", "/session", "/authorize"])
                    return not any(u in lowered for u in ["/login", "/signin", "/auth", "accounts.google.com", "github.com/login", "login.microsoftonline.com"]) and (login_request.app_url.split("//")[-1].split("/")[0].split(":")[0] in lowered)
                
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
            
            # Find OAuth button
            oauth_selectors = {
                "google": [
                    "button:has-text('Google')",
                    "button:has-text('Sign in with Google')",
                    "button:has-text('Continue with Google')",
                    "[aria-label*='Google' i]",
                    "[data-provider='google']",
                    "a[href*='google.com']"
                ],
                "github": [
                    "button:has-text('GitHub')",
                    "button:has-text('Sign in with GitHub')",
                    "[aria-label*='GitHub' i]",
                    "[data-provider='github']"
                ],
                "microsoft": [
                    "button:has-text('Microsoft')",
                    "button:has-text('Sign in with Microsoft')",
                    "[aria-label*='Microsoft' i]",
                    "[data-provider='microsoft']"
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

            # Handle OAuth flows that open in a new popup/page
            popup_page = None
            try:
                popup_page = await browser.context.wait_for_event("page", timeout=5000)
                logger.info("OAuth popup detected, waiting for it to complete...")
                await popup_page.wait_for_load_state("domcontentloaded")
            except Exception:
                logger.info("No OAuth popup detected; continuing in current page")

            # Wait for OAuth redirect and user interaction (in popup or current page)
            logger.info("Waiting for OAuth flow to complete...")
            import asyncio
            max_wait = 180  # allow up to 3 minutes
            waited = 0

            def is_app_url(url: str) -> bool:
                lowered = url.lower()
                return not any(u in lowered for u in ["/login", "/signin", "/auth", "accounts.google.com", "github.com/login", "login.microsoftonline.com"]) and (login_request.app_url.split("//")[-1].split("/")[0].split(":")[0] in lowered)

            initial_url = await browser.get_url()

            while waited < max_wait:
                await asyncio.sleep(2)
                waited += 2
                try:
                    if popup_page and not popup_page.is_closed():
                        current_url = popup_page.url
                        if is_app_url(current_url):
                            logger.info(f"OAuth completed via popup: {current_url}")
                            # Close popup if it stayed open after redirect
                            try:
                                await popup_page.close()
                            except Exception:
                                pass
                            break
                    else:
                        current_url = await browser.get_url()
                        if current_url != initial_url and is_app_url(current_url):
                            logger.info(f"OAuth redirect detected in main page: {current_url}")
                            break
                except Exception:
                    # continue polling
                    pass

            # Final settle
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
