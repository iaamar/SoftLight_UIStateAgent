from crewai import Agent, Task, Crew
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from typing import Optional, Dict, Any, List
from utils.logger import get_logger
from utils.browser_controller import BrowserController
import asyncio
import time

logger = get_logger(name="login_agent")


class LoginAgent:
    def __init__(self, browser: BrowserController, llm_model: str = "claude-sonnet-4-5-20250929"):
        self.browser = browser
        self.llm = self._get_llm(llm_model)
        self.agent = Agent(
            role="Authentication Specialist",
            goal="Determine if authentication is required and handle login across different web applications",
            backstory="""Expert in authentication detection and handling across various web applications. 
            Can identify login requirements, detect OAuth providers, and determine the best authentication 
            approach for different apps. Works with both traditional email/password login and modern OAuth flows.""",
            verbose=True,
            llm=self.llm
        )
    
    def _get_llm(self, model: str):
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        if "claude" in model.lower():
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not found")
            return ChatAnthropic(model=model, api_key=api_key)
        else:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not found")
            return ChatOpenAI(model=model, api_key=api_key)
    
    async def check_authentication_required(self, app_url: str) -> Dict[str, Any]:
        """
        Check if authentication is required for the given application.
        Returns comprehensive authentication status and requirements.
        """
        logger.log_agent_start("LoginAgent", task="Check authentication")
        
        try:
            # Navigate to the app URL
            await self.browser.navigate(app_url)
            await self.browser.wait_for_stable_page()
            
            # Get current state
            current_url = await self.browser.get_url()
            page_text = await self.browser.get_page_text()
            page_html = await self.browser.get_page_html()
            
            # Use browser's built-in login check
            login_check = await self.browser.check_login_required()
            
            # Use LLM to analyze the page and provide strategic advice
            analysis = await self._analyze_authentication_page(
                current_url=current_url,
                page_text=page_text[:2000],
                page_html=page_html[:15000],
                login_check=login_check
            )
            
            # Combine browser check with LLM analysis
            result = {
                "requires_login": login_check.get("requires_login", False) or analysis.get("requires_login", False),
                "login_method": analysis.get("recommended_method"),
                "has_login_form": login_check.get("has_login_form", False),
                "is_login_page": login_check.get("is_login_page", False),
                "current_url": current_url,
                "oauth_providers": login_check.get("oauth_providers", []) + analysis.get("detected_oauth_providers", []),
                "has_password_form": login_check.get("has_password_form", False),
                "login_url": current_url if login_check.get("is_login_page", False) else None,
                "analysis": analysis,
                "browser_check": login_check
            }
            
            logger.info(f"Authentication check: requires_login={result['requires_login']}, method={result['login_method']}")
            logger.log_agent_end("LoginAgent", success=True)
            
            return result
            
        except Exception as e:
            logger.log_error(e, context={"agent": "LoginAgent", "action": "check_authentication"})
            logger.log_agent_end("LoginAgent", success=False)
            return {
                "requires_login": False,
                "error": str(e),
                "login_method": None
            }
    
    async def _analyze_authentication_page(
        self,
        current_url: str,
        page_text: str,
        page_html: str,
        login_check: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Use LLM to analyze the authentication page and recommend approach"""
        
        task_description = f"""
You are an authentication specialist analyzing a web application page to determine authentication requirements.

**Current Situation**:
- Current URL: {current_url}
- Browser detected login form: {login_check.get('has_login_form', False)}
- Browser detected login page: {login_check.get('is_login_page', False)}
- OAuth providers detected: {login_check.get('oauth_providers', [])}

**Page Content Preview** (first 2000 chars):
{page_text}

**Page HTML** (first 15000 chars):
{page_html[:15000]}

**Your Task**:
1. Analyze if authentication is REQUIRED for this application
2. Determine the best authentication method (OAuth vs manual login)
3. Identify which OAuth provider would be best if multiple options exist
4. Check for any indicators that user is already logged in

**Analysis Criteria**:
- Look for login prompts, authentication gates, or "Sign in" requirements
- Check for user avatars, profile menus, account settings (indicates logged in)
- Identify OAuth providers (Google, GitHub, Microsoft, Apple, etc.)
- Determine if it's a password-based login or OAuth-only
- Check if user is already authenticated (presence of user info, logout buttons, etc.)

**Output Format**:
Return a JSON object with:
{{
    "requires_login": boolean (true if authentication is definitely required),
    "is_already_logged_in": boolean (true if user appears to be authenticated),
    "recommended_method": string ("oauth_google" | "oauth_github" | "oauth_microsoft" | "oauth_apple" | "manual" | "none"),
    "detected_oauth_providers": array of strings (e.g., ["google", "github"]),
    "reasoning": string (brief explanation of your analysis),
    "confidence": float (0.0 to 1.0, how confident you are in the recommendation)
}}

**Important**: 
- Be conservative: only say requires_login=true if you're confident authentication is needed
- If you see user profile info, account menus, or logout buttons, user is likely already logged in
- Prefer OAuth methods when available (simpler and more secure)
- Return ONLY the JSON object, no explanation text
"""
        
        task = Task(
            description=task_description,
            expected_output="A JSON object with authentication analysis including requires_login, recommended_method, and reasoning",
            agent=self.agent
        )
        
        crew = Crew(agents=[self.agent], tasks=[task])
        result = crew.kickoff()
        
        # Parse the result
        analysis = self._parse_authentication_analysis(str(result))
        
        return analysis
    
    def _parse_authentication_analysis(self, analysis_text: str) -> Dict[str, Any]:
        """Parse LLM analysis result"""
        import json
        import re
        
        # Try to extract JSON from the response
        json_match = re.search(r'\{.*\}', analysis_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except:
                pass
        
        # Fallback: extract key information
        analysis = {
            "requires_login": "requires_login" in analysis_text.lower() and "true" in analysis_text.lower(),
            "is_already_logged_in": "already" in analysis_text.lower() and "logged" in analysis_text.lower(),
            "recommended_method": "manual",
            "detected_oauth_providers": [],
            "reasoning": analysis_text[:200],
            "confidence": 0.5
        }
        
        # Detect OAuth providers
        if "google" in analysis_text.lower():
            analysis["detected_oauth_providers"].append("google")
            analysis["recommended_method"] = "oauth_google"
        if "github" in analysis_text.lower():
            analysis["detected_oauth_providers"].append("github")
            if analysis["recommended_method"] == "manual":
                analysis["recommended_method"] = "oauth_github"
        if "microsoft" in analysis_text.lower():
            analysis["detected_oauth_providers"].append("microsoft")
            if analysis["recommended_method"] == "manual":
                analysis["recommended_method"] = "oauth_microsoft"
        if "apple" in analysis_text.lower():
            analysis["detected_oauth_providers"].append("apple")
            if analysis["recommended_method"] == "manual":
                analysis["recommended_method"] = "oauth_apple"
        
        return analysis
    
    async def handle_login(
        self,
        app_url: str,
        login_method: Optional[str] = None,
        headless: bool = False
    ) -> Dict[str, Any]:
        """
        Handle login process. Opens browser for user interaction if needed.
        
        Args:
            app_url: Application URL
            login_method: Preferred login method (oauth_google, oauth_github, manual, etc.)
            headless: Whether to run browser in headless mode (should be False for login)
        
        Returns:
            Dict with login status and session information
        """
        logger.log_agent_start("LoginAgent", task="Handle login")
        
        try:
            # Ensure browser is in headed mode for login
            if headless:
                logger.warning("Login requires headed mode, switching to visible browser")
                # Note: This would require restarting browser, handled by caller
            
            # Navigate to login page
            await self.browser.navigate(app_url)
            await self.browser.wait_for_stable_page()
            
            current_url = await self.browser.get_url()
            
            # Check authentication status first
            auth_check = await self.check_authentication_required(app_url)
            
            # If already logged in, return success
            if not auth_check.get("requires_login", False) or auth_check.get("analysis", {}).get("is_already_logged_in", False):
                logger.info("User is already authenticated")
                return {
                    "success": True,
                    "already_logged_in": True,
                    "message": "User is already authenticated"
                }
            
            # Determine login method
            if not login_method:
                login_method = auth_check.get("login_method", "manual")
            
            # Handle OAuth login
            if login_method and login_method.startswith("oauth_"):
                provider = login_method.replace("oauth_", "")
                result = await self._handle_oauth_login(provider, app_url)
                return result
            
            # Handle manual login (open browser for user)
            return await self._handle_manual_login(app_url)
            
        except Exception as e:
            logger.log_error(e, context={"agent": "LoginAgent", "action": "handle_login"})
            logger.log_agent_end("LoginAgent", success=False)
            return {
                "success": False,
                "error": str(e),
                "message": "Login handling failed"
            }
    
    async def _handle_oauth_login(self, provider: str, app_url: str) -> Dict[str, Any]:
        """Handle OAuth login flow"""
        logger.info(f"Handling OAuth login with {provider}")
        
        # OAuth selectors for different providers
        oauth_selectors = {
            "google": [
                "button:has-text('Google')",
                "button:has-text('Sign in with Google')",
                "button:has-text('Continue with Google')",
                "button[aria-label*='Google' i]",
                "[data-provider='google']"
            ],
            "github": [
                "button:has-text('GitHub')",
                "button:has-text('Sign in with GitHub')",
                "button:has-text('Continue with GitHub')",
                "button[aria-label*='GitHub' i]",
                "[data-provider='github']"
            ],
            "microsoft": [
                "button:has-text('Microsoft')",
                "button:has-text('Sign in with Microsoft')",
                "button[aria-label*='Microsoft' i]",
                "[data-provider='microsoft']"
            ],
            "apple": [
                "button:has-text('Apple')",
                "button:has-text('Sign in with Apple')",
                "button[aria-label*='Apple' i]",
                "[data-provider='apple']"
            ]
        }
        
        selectors = oauth_selectors.get(provider.lower(), [])
        
        # Try to click OAuth button
        for selector in selectors:
            try:
                await self.browser.click(selector, timeout=3000)
                logger.info(f"Clicked OAuth button: {selector}")
                
                # Wait for OAuth redirect
                await asyncio.sleep(2)
                
                # Check if redirected to OAuth provider
                current_url = await self.browser.get_url()
                if any(domain in current_url for domain in [
                    "accounts.google.com", "github.com/login",
                    "login.microsoftonline.com", "appleid.apple.com"
                ]):
                    logger.info(f"Redirected to {provider} OAuth page - user should complete login")
                    return {
                        "success": True,
                        "message": f"OAuth flow initiated - complete login in browser",
                        "oauth_provider": provider,
                        "requires_user_action": True
                    }
            except Exception as e:
                logger.debug(f"OAuth selector {selector} failed: {e}")
                continue
        
        # If OAuth button not found, fall back to manual
        logger.warning(f"OAuth button not found for {provider}, falling back to manual login")
        return await self._handle_manual_login(app_url)
    
    async def _handle_manual_login(self, app_url: str) -> Dict[str, Any]:
        """Handle manual login - opens browser for user to login"""
        logger.info("Handling manual login - browser window will open for user")
        
        # Wait for user to complete login
        initial_url = await self.browser.get_url()
        logger.info(f"Waiting for user to complete login. Initial URL: {initial_url}")
        logger.info("Browser window is open - please complete authentication")
        
        # Monitor for login completion
        max_wait = 300  # 5 minutes
        waited = 0
        check_interval = 3  # Check every 3 seconds
        
        while waited < max_wait:
            await asyncio.sleep(check_interval)
            waited += check_interval
            
            try:
                current_url = await self.browser.get_url()
                
                # Check if URL changed (likely logged in)
                if current_url != initial_url:
                    # Check if we're no longer on login page
                    login_patterns = ["/login", "/signin", "/auth", "/sign-in"]
                    if not any(pattern in current_url.lower() for pattern in login_patterns):
                        # Verify login by checking for user indicators
                        login_check = await self.browser.check_login_required()
                        if not login_check.get("requires_login", False):
                            logger.info(f"Login appears complete: {current_url}")
                            await asyncio.sleep(2)  # Wait for page to stabilize
                            await self.browser.wait_for_stable_page()
                            
                            return {
                                "success": True,
                                "message": "Login completed successfully",
                                "final_url": current_url,
                                "requires_user_action": True
                            }
                
                # Check for user profile indicators
                has_user_indicator = await self.browser.page.evaluate("""
                    () => {
                        const indicators = [
                            'summary[aria-label*="profile" i]',
                            'button[aria-label*="account" i]',
                            'button[aria-label*="user" i]',
                            '[data-testid*="user"]',
                            '[data-testid*="profile"]',
                            '.user-avatar',
                            '.profile-menu'
                        ];
                        return indicators.some(sel => document.querySelector(sel) !== null);
                    }
                """)
                
                if has_user_indicator:
                    logger.info("Detected user profile indicators - login likely complete")
                    await asyncio.sleep(2)
                    await self.browser.wait_for_stable_page()
                    
                    return {
                        "success": True,
                        "message": "Login completed (user indicators detected)",
                        "final_url": current_url,
                        "requires_user_action": True
                    }
                    
            except Exception as e:
                logger.debug(f"Error checking login status: {e}")
                continue
        
        # Timeout
        logger.warning("Login timeout - user may still be logging in")
        return {
            "success": False,
            "message": "Login timeout - please complete login manually",
            "requires_user_action": True,
            "timeout": True
        }
    
    async def verify_authentication(self) -> bool:
        """Verify that user is currently authenticated"""
        try:
            login_check = await self.browser.check_login_required()
            return not login_check.get("requires_login", False)
        except Exception as e:
            logger.error(f"Error verifying authentication: {e}")
            return False

