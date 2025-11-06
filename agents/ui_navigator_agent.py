from crewai import Agent, Task, Crew
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from typing import Optional, Dict, Any, List, Tuple
from utils.logger import get_logger
from utils.browser_controller import BrowserController
import json
import re
from bs4 import BeautifulSoup

logger = get_logger(name="ui_navigator_agent")


class UINavigatorAgent:
    def __init__(self, browser: BrowserController, llm_model: str = "claude-sonnet-4-5-20250929"):
        self.browser = browser
        self.llm = self._get_llm(llm_model)
        self.agent = Agent(
            role="Advanced UI Navigation Specialist",
            goal="Navigate complex web applications, handle dynamic content, and identify all UI states",
            backstory="""Expert in modern web UI navigation with deep knowledge of:
            - Single Page Applications (React, Vue, Angular)
            - Dynamic content loading patterns
            - Modal dialogs and popups
            - Form interactions and validation
            - Multi-step workflows
            - Authentication flows
            - Accessibility patterns (ARIA labels, roles)
            """,
            verbose=True,
            llm=self.llm
        )
    
    def _get_llm(self, model: str):
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        if "claude" in model.lower() or "anthropic" in model.lower():
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not found")
            return ChatAnthropic(model=model, api_key=api_key)
        else:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not found")
            # Remove temperature parameter entirely for compatibility
            return ChatOpenAI(model=model, api_key=api_key)
    
    async def analyze_page_structure(self) -> Dict[str, Any]:
        """Analyze the current page structure for navigation opportunities"""
        page_html = await self.browser.get_page_html()
        soup = BeautifulSoup(page_html, 'html.parser')
        
        # Find interactive elements
        buttons = soup.find_all(['button', 'a', 'input'])
        forms = soup.find_all('form')
        
        # Detect modals/dialogs
        modals = soup.find_all(['div', 'section'], attrs={
            'role': ['dialog', 'alertdialog'],
            'aria-modal': 'true'
        })
        
        # Find navigation elements
        nav_elements = soup.find_all(['nav', 'menu'])
        
        # Extract key information
        structure = {
            "interactive_elements": len(buttons),
            "forms": len(forms),
            "modals": len(modals),
            "navigation_areas": len(nav_elements),
            "has_dropdown": bool(soup.find_all(attrs={'aria-haspopup': 'true'})),
            "has_tabs": bool(soup.find_all(attrs={'role': 'tablist'})),
            "page_title": soup.title.string if soup.title else "",
            "main_headings": [h.get_text(strip=True) for h in soup.find_all(['h1', 'h2'])[:5]]
        }
        
        return structure
    
    async def detect_workflow_type(self, task_query: str, page_structure: Dict[str, Any]) -> str:
        """
        Detect workflow type for logging/metrics purposes only.
        NOTE: This is NOT used for hardcoded navigation - the LLM generates steps dynamically.
        """
        task_lower = task_query.lower()
        
        # Simple categorization for logging/debugging only
        if any(word in task_lower for word in ["create", "new", "add"]):
            if "project" in task_lower:
                return "create_project"
            elif "repository" in task_lower or "repo" in task_lower:
                return "create_repository"
            elif "task" in task_lower or "issue" in task_lower:
                return "create_task"
            elif "database" in task_lower or "table" in task_lower:
                return "create_database"
            else:
                return "create_generic"
        
        elif any(word in task_lower for word in ["filter", "search", "find"]):
            return "filter_search"
        
        elif any(word in task_lower for word in ["settings", "preferences", "configure"]):
            return "settings_navigation"
        
        elif any(word in task_lower for word in ["edit", "update", "modify"]):
            return "edit_workflow"
        
        elif any(word in task_lower for word in ["delete", "remove"]):
            return "delete_workflow"
        
        else:
            return "generic_navigation"
    
    async def generate_smart_navigation_steps(
        self, 
        task_query: str, 
        workflow_type: str,
        page_html: str,
        current_url: str,
        is_logged_in: bool = True  # Default True - authentication handled by API
    ) -> List[Dict[str, Any]]:
        """Generate navigation steps dynamically by analyzing the page and understanding the task"""
        
        # Authentication context (generic - works for any application)
        auth_context = """
**Authentication Status**: 
✅ User is ALREADY authenticated/logged in (authentication handled separately via API).

**Critical Instructions**:
- DO NOT generate any login, sign-in, or authentication steps
- Authentication was already completed before this navigation agent was called
- If you see "Sign in", "Login", "Sign up", or authentication buttons in the HTML, IGNORE them completely
- Focus ONLY on completing the user's actual task, not authentication
- The user can proceed directly to the task without any authentication steps

**Your job**: Navigate the authenticated application to complete the task.
"""
        
        # Fully dynamic prompt - NO hardcoded workflows, NO app-specific logic
        task_description = f"""
You are an expert UI navigation agent analyzing a live web application. Your goal is to understand EXACTLY what the user wants to accomplish and generate a PRECISE, TASK-SPECIFIC navigation plan by analyzing the actual HTML.

{auth_context}

**User's Task**: {task_query}
**Current URL**: {current_url}

**CRITICAL INSTRUCTIONS - Generate Task-Specific Navigation Plan**:

1. **UNDERSTAND THE TASK DEEPLY**:
   - Parse the user's task query carefully to identify:
     * What object/entity they want to create/modify/view (e.g., "goal", "task", "project", "pricing page")
     * What action they want to perform (e.g., "create", "view", "go to", "capture")
     * Any specific details mentioned (e.g., names, types, locations)
   - Your navigation plan MUST be specific to THIS EXACT TASK - not a generic workflow
   - Think step-by-step: What is the shortest, most direct path to complete THIS specific task?

2. **VERIFY authentication status by analyzing the HTML**:
   - Look for user avatars, profile menus, account settings, "Sign out"/"Logout" buttons (indicates logged in)
   - If you see "Sign in", "Login", authentication forms - IGNORE them (user is already authenticated)

3. **ANALYZE the HTML to find task-specific elements**:
   - Search for elements that match the TASK keywords (e.g., if task says "create goal", look for "goal", "create goal", "new goal" buttons/links)
   - Look for navigation patterns that lead to the task objective (e.g., if task is "go to pricing", find pricing links/buttons)
   - Identify the EXACT sequence of clicks/types needed for THIS task

4. **GENERATE PRECISE, TASK-SPECIFIC STEPS**:
   - Each step should directly advance toward completing the user's specific task
   - Use ONLY elements that exist in the HTML provided
   - Be specific: Instead of "click create button", say "click 'Create Goal' button" or "click button with text 'New Goal'"
   - Include ALL steps needed, even if they seem obvious (e.g., opening dropdowns, selecting options)
   - If the task involves viewing/capturing a page, ensure you navigate to the correct page FIRST

5. **SKIP all authentication/login related elements** - user is already logged in

**Authentication Detection Pattern** (works for any application):
- Logged IN indicators: User avatar/profile picture, account menu, settings icon, "Sign out"/"Logout" button, user name/email displayed
- Logged OUT indicators: "Sign in"/"Login" button/link, authentication form visible, "Create account" prompt
- Since user is authenticated, focus on authenticated UI elements only

**Selector Priority** (use most specific available):
   - ID selectors: #element-id
   - Data attributes: [data-testid="..."], [data-test="..."], [data-test-id="..."]
   - ARIA labels: [aria-label="..."], [aria-labelledby="..."]
   - Button/link text: button:has-text('Exact Text'), a:has-text('Exact Text')
   - Role + text: [role="button"]:has-text('Text')
   - Placeholder: input[placeholder="..."]
   - Name attribute: input[name="..."], select[name="..."]
   - Class names (only if unique and semantic): .create-button, .submit-form

**Important Considerations**:
- Modals/dialogs may appear after clicking certain buttons (look for "new", "create", "add" buttons)
- Forms may have multiple steps - include all fields you find
- Wait for dynamic content after actions that load data
- Some workflows need scrolling to reveal elements
- **Dropdowns/Menus (CRITICAL)**: 
  - When you see buttons like "Create", "New", "Add", "..." that typically open dropdowns/menus:
    1. First step: Click the button (e.g., `button:has-text('Create')`)
    2. Second step: Wait 1-2 seconds for dropdown to appear
    3. Third step: Click the menu item using a selector that searches WITHIN the dropdown:
       - `[role='menu']:visible >> button:has-text('Project')` 
       - `[role='menuitem']:has-text('Project'):visible`
       - `.dropdown-menu:visible >> text='Project'`
       - Or if HTML shows menu structure: analyze the menu container and target items inside
  - Common dropdown containers: `[role='menu']`, `[role='listbox']`, `.dropdown-menu`, `[class*='menu']`, `[class*='dropdown']`
  - IMPORTANT: If the HTML doesn't show the dropdown content (it's dynamically rendered), still generate steps assuming the dropdown will appear after clicking the trigger button
  - For menu items, prefer text-based selectors like `button:has-text('Project')` or `[role='menuitem']:has-text('Project')` - they work universally across applications
- **Scroll actions**: If elements might be below the fold, include scroll steps BEFORE clicking them
- **JavaScript-heavy sites**: Include wait steps after clicks/actions on dynamic sites (2-3 seconds)
- NEVER include login/authentication steps even if login buttons are visible in HTML

**Page HTML** (analyze this carefully - first 15000 characters):
{page_html[:15000]}

**Output Format**: Generate a JSON array with steps. Each step object:
{{
  "action_type": "click" | "type" | "wait" | "select" | "hover" | "scroll" | "navigate",
  "selector": "valid CSS/Playwright selector from the HTML above",
  "description": "Human-readable description of what this step does",
  "text": "text to type (only for type actions - ALWAYS include dummy/test text if user doesn't specify)",
  "wait_time": 2 (seconds, for wait actions),
  "options": "option value (for select dropdowns)"
}}

**IMPORTANT - Text Generation for Type Actions**:
- If the user's query specifies exact text to type (e.g., "create a task with name 'Meeting'"), use that exact text
- If the user's query does NOT specify text (e.g., "how do I create a task?"), ALWAYS generate descriptive placeholder text that guides the user:
  - For task/project names: "Your task name", "Task name", "Project name", etc.
  - For descriptions: "Description", "Task description", "Your description"
  - For names: "Your name", "Name", "Your full name"
  - For emails: "your.email@example.com" (descriptive placeholder)
  - For any other field: Use descriptive placeholder text that indicates what should be entered (e.g., "Your title", "Your message", "Your comment")
- The goal is to guide the user through the UI steps with screenshots showing what to type, using clear placeholder text
- ALWAYS include "text" field for type actions, using descriptive placeholders that help users understand what to enter

**Critical Rules**:
- ONLY use selectors for elements that EXIST in the HTML provided
- NEVER include login, sign-in, or authentication steps (user is already authenticated)
- Generate descriptive placeholder text for form fields (e.g., "Project name" or "Your task name" to guide users)
- Include wait steps after clicks that might trigger modals or loading states
- If you're not sure an element exists, DON'T include that step
- Return ONLY the JSON array, no explanation text

Generate the navigation steps now:
        """
        
        # Create and execute the task
        task = Task(
            description=task_description,
            expected_output="A JSON array of navigation steps with exact selectors from the HTML",
            agent=self.agent
        )
        
        crew = Crew(agents=[self.agent], tasks=[task])
        result = crew.kickoff()
        
        # Parse the result
        steps = self._parse_enhanced_navigation_plan(str(result))
        return steps
    
    def _parse_enhanced_navigation_plan(self, plan_text: str) -> List[Dict[str, Any]]:
        """Enhanced parser for navigation plans with better error handling"""
        logger.debug(f"Parsing navigation plan, length: {len(plan_text)} chars")
        
        # Multiple strategies to extract JSON
        strategies = [
            # Strategy 1: Look for markdown code blocks
            lambda: re.search(r'```(?:json)?\s*(\[.*?\])\s*```', plan_text, re.DOTALL),
            # Strategy 2: Find array with balanced brackets
            lambda: self._extract_json_array(plan_text),
            # Strategy 3: Find individual JSON objects
            lambda: self._extract_json_objects(plan_text)
        ]
        
        for strategy in strategies:
            try:
                result = strategy()
                if result:
                    if isinstance(result, re.Match):
                        json_str = result.group(1)
                    else:
                        json_str = result
                    
                    parsed = json.loads(json_str) if isinstance(json_str, str) else json_str
                    if isinstance(parsed, list) and len(parsed) > 0:
                        logger.info(f"Successfully parsed {len(parsed)} navigation steps")
                        return self._validate_navigation_steps(parsed)
            except Exception as e:
                logger.debug(f"Strategy failed: {e}")
                continue
        
        # Fallback: Generate basic steps based on common patterns
        logger.warning("Failed to parse LLM response, generating fallback steps")
        return self._generate_fallback_steps(plan_text)
    
    def _extract_json_array(self, text: str) -> Optional[str]:
        """Extract JSON array with proper bracket matching"""
        bracket_count = 0
        start_idx = -1
        in_string = False
        escape_next = False
        
        for i, char in enumerate(text):
            if escape_next:
                escape_next = False
                continue
                
            if char == '\\':
                escape_next = True
                continue
                
            if char == '"' and not escape_next:
                in_string = not in_string
                continue
                
            if not in_string:
                if char == '[':
                    if bracket_count == 0:
                        start_idx = i
                    bracket_count += 1
                elif char == ']':
                    bracket_count -= 1
                    if bracket_count == 0 and start_idx != -1:
                        return text[start_idx:i+1]
        
        return None
    
    def _extract_json_objects(self, text: str) -> Optional[List[Dict]]:
        """Extract individual JSON objects and return as list"""
        objects = []
        brace_count = 0
        start_idx = -1
        in_string = False
        escape_next = False
        
        for i, char in enumerate(text):
            if escape_next:
                escape_next = False
                continue
                
            if char == '\\':
                escape_next = True
                continue
                
            if char == '"' and not escape_next:
                in_string = not in_string
                continue
                
            if not in_string:
                if char == '{':
                    if brace_count == 0:
                        start_idx = i
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0 and start_idx != -1:
                        try:
                            obj_str = text[start_idx:i+1]
                            obj = json.loads(obj_str)
                            if self._is_valid_navigation_step(obj):
                                objects.append(obj)
                        except:
                            pass
                        start_idx = -1
        
        return objects if objects else None
    
    def _is_valid_navigation_step(self, obj: Dict) -> bool:
        """Check if object is a valid navigation step"""
        required_fields = ["action_type", "selector", "description"]
        return all(field in obj for field in required_fields)
    
    def _validate_navigation_steps(self, steps: List[Dict]) -> List[Dict]:
        """Validate and enhance navigation steps"""
        validated_steps = []
        
        for step in steps:
            # Ensure required fields
            if not self._is_valid_navigation_step(step):
                continue
            
            # Enhance step with defaults
            enhanced_step = {
                "action_type": step.get("action_type", "click").lower(),
                "selector": step.get("selector", "").strip(),
                "description": step.get("description", ""),
                "text": step.get("text", ""),
                "wait_time": step.get("wait_time", 2),
                "options": step.get("options", "")
            }
            
            # Skip invalid selectors
            if not enhanced_step["selector"] and enhanced_step["action_type"] != "wait":
                continue
            
            # Auto-generate descriptive placeholder text for type actions if missing
            if enhanced_step["action_type"] == "type" and not enhanced_step.get("text", "").strip():
                # Generate descriptive placeholder text that guides the user
                selector_lower = enhanced_step["selector"].lower()
                desc_lower = enhanced_step["description"].lower()
                
                # Determine field type from selector/description and generate helpful placeholder
                if any(word in selector_lower or word in desc_lower for word in ["name", "title"]):
                    if "task" in selector_lower or "task" in desc_lower:
                        enhanced_step["text"] = "Your task name"
                    elif "project" in selector_lower or "project" in desc_lower:
                        enhanced_step["text"] = "Project name"
                    else:
                        enhanced_step["text"] = "Your name"
                elif "description" in selector_lower or "description" in desc_lower:
                    enhanced_step["text"] = "Description"
                elif any(word in selector_lower or word in desc_lower for word in ["task"]):
                    enhanced_step["text"] = "Your task name"
                elif any(word in selector_lower or word in desc_lower for word in ["project"]):
                    enhanced_step["text"] = "Project name"
                elif any(word in selector_lower or word in desc_lower for word in ["goal"]):
                    enhanced_step["text"] = "Your goal"
                elif any(word in selector_lower or word in desc_lower for word in ["email", "e-mail"]):
                    enhanced_step["text"] = "your.email@example.com"
                elif any(word in selector_lower or word in desc_lower for word in ["url", "link", "website"]):
                    enhanced_step["text"] = "https://example.com"
                elif any(word in selector_lower or word in desc_lower for word in ["comment", "note", "message"]):
                    enhanced_step["text"] = "Your comment"
                else:
                    # Generic descriptive placeholder - try to extract from placeholder attribute if available
                    placeholder_match = re.search(r'placeholder[=:]["\']([^"\']+)["\']', selector_lower)
                    if placeholder_match:
                        enhanced_step["text"] = placeholder_match.group(1)
                    else:
                        enhanced_step["text"] = "Your text"
                
                logger.debug(f"Generated placeholder text '{enhanced_step['text']}' for type action: {enhanced_step['selector']}")
            
            validated_steps.append(enhanced_step)
        
        return validated_steps
    
    def _generate_fallback_steps(self, text: str) -> List[Dict]:
        """Generate basic navigation steps from text analysis"""
        steps = []
        
        # Look for action keywords in the text
        action_patterns = [
            (r"click[s]?\s+(?:on\s+)?(?:the\s+)?['\"]([^'\"]+)['\"]", "click"),
            (r"type[s]?\s+['\"]([^'\"]+)['\"]", "type"),
            (r"select[s]?\s+['\"]([^'\"]+)['\"]", "select"),
            (r"wait[s]?\s+(?:for\s+)?(\d+)", "wait")
        ]
        
        for pattern, action_type in action_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                if action_type == "wait":
                    steps.append({
                        "action_type": "wait",
                        "wait_time": int(match.group(1)),
                        "selector": "",
                        "description": f"Wait for {match.group(1)} seconds"
                    })
                else:
                    steps.append({
                        "action_type": action_type,
                        "selector": match.group(1),
                        "description": f"{action_type.capitalize()} {match.group(1)}"
                    })
        
        return steps
    
    async def navigate_to_task(self, task_query: str, app_url: str) -> List[Dict[str, Any]]:
        """Main navigation method with enhanced capabilities"""
        logger.log_agent_start("UINavigatorAgent", task=task_query)
        
        try:
            # Navigate to the app
            await self.browser.navigate(app_url)
            await self.browser.wait_for_stable_page()
            
            # Check login status (authentication handled by API layer - navigation agent only runs if authenticated)
            login_check = await self.browser.check_login_required()
            is_logged_in = not login_check.get("requires_login", False)
            
            if not is_logged_in:
                # This shouldn't happen - API should have caught this
                logger.warning("Navigation agent called but user not authenticated. Returning empty steps.")
                logger.log_agent_end("UINavigatorAgent", success=False)
                return []  # Return empty - user needs to authenticate first
            
            logger.info(f"User is authenticated - proceeding with task navigation")
            
            # Analyze page structure
            page_structure = await self.analyze_page_structure()
            logger.info(f"Page structure: {page_structure}")
            
            # Detect workflow type
            workflow_type = await self.detect_workflow_type(task_query, page_structure)
            logger.info(f"Detected workflow type: {workflow_type}")
            
            # Get current state
            current_url = await self.browser.get_url()
            page_html = await self.browser.get_page_html()
            
            # Check for modals that might be blocking
            modals = await self.browser.detect_and_handle_modals()
            if modals:
                logger.info(f"Detected {len(modals)} modals on page")
            
            # Generate navigation steps (user is confirmed authenticated - skip login steps)
            steps = await self.generate_smart_navigation_steps(
                task_query=task_query,
                workflow_type=workflow_type,
                page_html=page_html,
                current_url=current_url,
                is_logged_in=True  # Always true at this point
            )
            
            # Enhance steps with dynamic content handling
            enhanced_steps = await self._enhance_steps_for_dynamic_content(steps)
            
            logger.log_agent_end("UINavigatorAgent", success=True)
            logger.info(f"Generated {len(enhanced_steps)} enhanced navigation steps")
            
            return enhanced_steps
            
        except Exception as e:
            logger.log_error(e, context={"agent": "UINavigatorAgent"})
            logger.log_agent_end("UINavigatorAgent", success=False)
            raise
    
    async def _enhance_steps_for_dynamic_content(self, steps: List[Dict]) -> List[Dict]:
        """Add wait steps and handle dynamic content"""
        enhanced_steps = []
        
        for i, step in enumerate(steps):
            enhanced_steps.append(step)
            
            # Add wait after actions that typically trigger dynamic content
            if step["action_type"] == "click":
                # Check if this might open a modal or load content
                description_lower = step["description"].lower()
                if any(word in description_lower for word in ["new", "create", "add", "open", "show", "filter"]):
                    enhanced_steps.append({
                        "action_type": "wait",
                        "wait_time": 2,
                        "selector": "",
                        "description": "Wait for dynamic content to load"
                    })
        
        return enhanced_steps
    
    # Backward compatibility - keep original method name
    def _parse_navigation_plan(self, plan_text: str) -> List[Dict[str, Any]]:
        """Backward compatible method that calls the enhanced parser"""
        return self._parse_enhanced_navigation_plan(plan_text)